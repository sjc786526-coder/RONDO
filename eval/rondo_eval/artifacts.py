"""Private raw artifacts plus a locked append-only tracked run index."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from .config import RepoPaths
from .contracts import RunOutcome


_RUN_ID = re.compile(
    r"(?P<stamp>[0-9]{8}-[0-9]{9})-"
    r"(?P<track>tb|replay|shadow)-"
    r"(?P<side>[0-9a-z][0-9a-z._-]{0,63})-r(?P<round>[1-9][0-9]*)\Z"
)
_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"
)
_MAX_SCAN_BYTES = 128 * 1024 * 1024
_SENSITIVE_ASSIGNMENT = re.compile(
    rb"(?:^|[,{\s])(?![\"']?user_authorization[\"']?\s*[:=])[\"']?"
    rb"(?:[a-z0-9]+[-_])*(?:api[-_]?key|access[-_]?token|bearer[-_]?token|"
    rb"client[-_]?secret|refresh[-_]?token|private[-_]?key|password|secret|token|authorization|"
    rb"proxy-authorization|x-api-key)[\"']?\s*[:=]\s*[\"']?\s*[^\s\"'},\]]+",
    re.IGNORECASE,
)
_AUTH_HEADER = re.compile(
    rb"(?:^|\n)(?:authorization|proxy-authorization|x-api-key|cookie|set-cookie)\s*:\s*\S+",
    re.IGNORECASE,
)
_URL_CREDENTIAL = re.compile(
    rb"(?:https?|wss?)://[^\s/:@]+:[^\s/@]+@",
    re.IGNORECASE,
)
_SIDES = {
    "tb": {"codex", "rondo"},
    "replay": {"codex", "rondo"},
    "shadow": {"luna-static", "sol-static", "local-static"},
}
_RECORD_FIELDS = {
    "schema_version",
    "run_id",
    "created_at",
    "track",
    "side",
    "git_commit",
    "git_dirty",
    "binary_sha256",
    "upstream_codex",
    "config",
    "outcome",
    "summary",
    "tasks",
    "metrics",
    "cost",
    "artifacts",
    "notes",
}
_UPSTREAM_CODEX_IDENTITY = {
    "tag": "rust-v0.147.0",
    "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
    "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
}


class ArtifactError(ValueError):
    """Raised when artifact publication cannot be completed safely."""


def validate_run_id(
    run_id: str,
    *,
    track: str | None = None,
    side: str | None = None,
) -> None:
    """Validate a run identity before any external work or budget reservation."""

    match = _match_run_id(run_id)
    if match is None:
        raise ArtifactError("run id is invalid")
    if track is not None and match.group("track") != track:
        raise ArtifactError("run id track is invalid")
    if side is not None and match.group("side") != side:
        raise ArtifactError("run id side is invalid")


class ArtifactWriter:
    def __init__(
        self,
        paths: RepoPaths,
        run_id: str,
        *,
        results_worktree_root: Path | None = None,
    ):
        validate_run_id(run_id)
        self.paths = paths
        self.run_id = run_id
        self.runs_root = paths.common_root / "eval-data" / "runs"
        self.target = self.runs_root / run_id
        self.staging = self.runs_root / f".{run_id}.staging-{os.getpid()}"
        self.journal = self.runs_root / f".{run_id}.publish.json"
        results_root = results_worktree_root or paths.worktree_root
        self.results = results_root / "eval" / "results" / "runs.jsonl"
        self._started = False

    def start(self) -> "ArtifactWriter":
        self._validate_roots()
        _make_directories(self.runs_root, self.paths.common_root, mode=0o700)
        self._recover_pending_publications()
        self._assert_run_paths()
        self._assert_run_unclaimed()
        self.staging.mkdir(mode=0o700)
        self._started = True
        return self

    def recover_only(self) -> None:
        """Recover existing publication journals without claiming new staging."""

        self._validate_roots()
        _require_directory(self.runs_root, "artifact runs root")
        self._assert_run_paths()
        self._recover_pending_publications()

    def write_json(self, relative_path: str, value: Any) -> None:
        try:
            contents = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ArtifactError("artifact JSON is not serializable") from exc
        self.write_bytes(relative_path, contents + b"\n")

    def write_bytes(self, relative_path: str, contents: bytes) -> None:
        if not self._started:
            raise ArtifactError("artifact writer has not started")
        if not isinstance(contents, bytes):
            raise ArtifactError("artifact contents must be bytes")
        self._assert_staging_tree()
        destination = self._safe_destination(relative_path)
        _make_directories(destination.parent, self.staging, mode=0o700)
        self._assert_staging_tree()
        temporary = destination.with_name(f".{destination.name}.tmp")
        if _path_present(temporary):
            raise ArtifactError("artifact temporary file already exists or is unsafe")
        try:
            descriptor = _open_new_regular_file(temporary, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(contents)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            _fsync_directory(destination.parent)
        except BaseException:
            if temporary.is_file() and not temporary.is_symlink():
                temporary.unlink()
            raise

    def finalize(self, record: Mapping[str, Any], *, secrets: Iterable[str]) -> Path:
        if not self._started:
            raise ArtifactError("artifact writer has not started")
        self._validate_roots()
        self._assert_staging_tree()
        _validate_record(record, self.run_id, self.paths.common_root)
        secret_bytes = _normalize_secrets(secrets)
        record_bytes = _encode_record(record)
        tree_identity = _artifact_tree_identity(self.staging, secret_bytes)
        _scan_bytes(record_bytes, secret_bytes, "tracked run record")
        _make_directories(self.results.parent, self.paths.common_root)
        lock_path = self.results.with_suffix(".jsonl.lock")
        _assert_safe_index_paths(self.results, lock_path, self.paths.common_root)
        with _open_lock_file(lock_path) as lock_handle:
            _lock(lock_handle)
            try:
                self._recover_pending_publications_locked()
                self._assert_publication_paths()
                index_before, rows = _read_index(self.results)
                if any(row["run_id"] == self.run_id for row in rows):
                    raise ArtifactError("run id is already present in the tracked index")
                index_after = index_before + record_bytes + b"\n"
                self._write_journal(
                    record,
                    tree_identity=tree_identity,
                    index_before=index_before,
                    index_after=index_after,
                )
                _assert_artifact_tree_identity(self.staging, tree_identity)
                os.replace(self.staging, self.target)
                _fsync_directory(self.runs_root)
                _assert_artifact_tree_identity(self.target, tree_identity)
                _atomic_replace_index(
                    self.results,
                    index_after,
                    _index_temporary_name(self.run_id),
                )
                self.journal.unlink()
                _fsync_directory(self.runs_root)
            finally:
                _unlock(lock_handle)
        self._started = False
        return self.target

    def publication_started(self) -> bool:
        """Return whether the recoverable publication transaction has begun."""

        if not self._started:
            raise ArtifactError("artifact writer has not started")
        return _path_present(self.journal) or _path_present(self.target)

    def abort(self) -> None:
        """Release only this process's unpublished staging claim."""

        if not self._started:
            return
        self._assert_staging_tree()
        if _path_present(self.target) or _path_present(self.journal):
            raise ArtifactError("published artifact state cannot be aborted")
        shutil.rmtree(self.staging)
        _fsync_directory(self.runs_root)
        self._started = False

    def _validate_roots(self) -> None:
        common_root = self.paths.common_root
        _require_directory(common_root, "common root")
        _require_below(self.paths.worktree_root, common_root, "worktree root")
        _require_directory(self.paths.worktree_root, "worktree root")
        results_root = self.results.parents[2]
        _require_below(results_root, common_root, "results worktree root")
        _require_directory(results_root, "results worktree root")
        _assert_no_symlink_components(common_root, results_root)

    def _assert_run_paths(self) -> None:
        _require_below(self.runs_root, self.paths.common_root, "runs root")
        _assert_no_symlink_components(self.paths.common_root, self.runs_root)
        for path in (self.target, self.staging, self.journal):
            _require_below(path, self.runs_root, "artifact publication path")

    def _assert_run_unclaimed(self) -> None:
        if _path_present(self.target) or _path_present(self.journal):
            raise ArtifactError("artifact destination already exists or is unsafe")
        prefix = f".{self.run_id}.staging-"
        try:
            if any(entry.name.startswith(prefix) for entry in os.scandir(self.runs_root)):
                raise ArtifactError("artifact run id already has an active staging claim")
        except OSError as exc:
            raise ArtifactError("artifact runs directory cannot be checked safely") from exc
        _make_directories(self.results.parent, self.paths.common_root)
        lock_path = self.results.with_suffix(".jsonl.lock")
        _assert_safe_index_paths(self.results, lock_path, self.paths.common_root)
        with _open_lock_file(lock_path) as lock_handle:
            _lock(lock_handle)
            try:
                if _run_id_exists(self.results, self.run_id):
                    raise ArtifactError("run id is already present in the tracked index")
            finally:
                _unlock(lock_handle)

    def _assert_staging_tree(self) -> None:
        self._assert_run_paths()
        if self.staging.is_symlink() or not self.staging.is_dir():
            raise ArtifactError("artifact staging directory is unsafe")
        _assert_no_symlink_components(self.runs_root, self.staging)

    def _assert_publication_paths(self) -> None:
        self._assert_staging_tree()
        if _path_present(self.target) or _path_present(self.journal):
            raise ArtifactError("artifact publication path appeared before publication")
        lock_path = self.results.with_suffix(".jsonl.lock")
        _assert_safe_index_paths(self.results, lock_path, self.paths.common_root)

    def _safe_destination(self, relative_path: str) -> Path:
        relative = Path(relative_path)
        if (
            relative.is_absolute()
            or not relative.parts
            or relative == Path(".")
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise ArtifactError("artifact path must stay below the run directory")
        destination = self.staging.joinpath(relative)
        _require_below(destination, self.staging, "artifact path")
        _assert_no_symlink_components(self.staging, destination.parent)
        if _path_present(destination):
            raise ArtifactError("artifact file already exists or is unsafe")
        return destination

    def _write_journal(
        self,
        record: Mapping[str, Any],
        *,
        tree_identity: Mapping[str, Any],
        index_before: bytes,
        index_after: bytes,
    ) -> None:
        try:
            results_relative = self.results.relative_to(self.paths.common_root).as_posix()
        except ValueError as exc:  # pragma: no cover - guarded by root validation
            raise ArtifactError("tracked result path escapes the common root") from exc
        value = {
            "schema_version": 2,
            "run_id": self.run_id,
            "staging_name": self.staging.name,
            "results": results_relative,
            "index_temporary_name": _index_temporary_name(self.run_id),
            "index_before": _bytes_identity(index_before),
            "index_after": _bytes_identity(index_after),
            "record_identity": _bytes_identity(_encode_record(record)),
            "tree_identity": dict(tree_identity),
            "record": dict(record),
        }
        _write_private_json(self.journal, value)

    def _recover_pending_publications(self) -> None:
        _make_directories(self.results.parent, self.paths.common_root)
        lock_path = self.results.with_suffix(".jsonl.lock")
        _assert_safe_index_paths(self.results, lock_path, self.paths.common_root)
        with _open_lock_file(lock_path) as lock_handle:
            _lock(lock_handle)
            try:
                self._recover_pending_publications_locked()
            finally:
                _unlock(lock_handle)

    def _recover_pending_publications_locked(self) -> None:
        try:
            journals = sorted(
                Path(entry.path)
                for entry in os.scandir(self.runs_root)
                if entry.name.startswith(".") and entry.name.endswith(".publish.json")
            )
        except OSError as exc:
            raise ArtifactError("artifact publication journals cannot be scanned safely") from exc
        expected_results = self.results.relative_to(self.paths.common_root).as_posix()
        for journal in journals:
            value = _read_publication_journal(journal)
            if value["results"] == expected_results:
                self._recover_publication_locked(journal, value)

    def _recover_publication_locked(self, journal: Path, value: Mapping[str, Any]) -> None:
        run_id = value["run_id"]
        target = self.runs_root / run_id
        try:
            expected_results = self.results.relative_to(self.paths.common_root).as_posix()
        except ValueError as exc:  # pragma: no cover - guarded by root validation
            raise ArtifactError("tracked result path escapes the common root") from exc
        if value["results"] != expected_results:
            raise ArtifactError("artifact publication journal targets another result index")
        staging_name = value.get("staging_name")
        staged = self.runs_root / staging_name
        record = value["record"]
        _validate_record(record, run_id, self.paths.common_root)
        record_bytes = _encode_record(record)
        _scan_bytes(record_bytes, (), "tracked run record")
        if value["record_identity"] != _bytes_identity(record_bytes):
            raise ArtifactError("artifact publication journal record identity differs")
        index_bytes, _rows = _read_index(self.results)
        index_identity = _bytes_identity(index_bytes)
        index_before = value["index_before"]
        index_after = value["index_after"]
        target_present = _path_present(target)
        staged_present = _path_present(staged)
        tree_identity = value["tree_identity"]
        if index_identity == index_after:
            if not target_present or staged_present:
                raise ArtifactError("published run has inconsistent recovery state")
            _assert_artifact_tree_identity(target, tree_identity)
            _discard_index_temporary(self.results.parent / value["index_temporary_name"])
            journal.unlink()
            _fsync_directory(self.runs_root)
            return
        if index_identity != index_before:
            raise ArtifactError("tracked run index differs from both journal identities")
        expected_after = index_bytes + record_bytes + b"\n"
        if _bytes_identity(expected_after) != index_after:
            raise ArtifactError("artifact publication journal index transition is invalid")
        if target_present and staged_present:
            raise ArtifactError("pending artifact publication has two artifact trees")
        artifact_tree = target if target_present else staged
        if not _path_present(artifact_tree):
            raise ArtifactError("pending artifact staging directory is unavailable")
        _assert_artifact_tree_identity(artifact_tree, tree_identity)
        if not target_present:
            os.replace(staged, target)
            _fsync_directory(self.runs_root)
        _atomic_replace_index(
            self.results,
            expected_after,
            value["index_temporary_name"],
        )
        journal.unlink()
        _fsync_directory(self.runs_root)


def _validate_record(record: Mapping[str, Any], run_id: str, common_root: Path) -> None:
    if not isinstance(record, Mapping):
        raise ArtifactError("run record must be an object")
    match = _match_run_id(run_id)
    if (
        match is None
        or set(record) != _RECORD_FIELDS
        or record.get("schema_version") != 1
        or record.get("run_id") != run_id
    ):
        raise ArtifactError("run record fields do not match schema v1")
    track = record.get("track")
    side = record.get("side")
    if track != match.group("track") or side != match.group("side") or side not in _SIDES[track]:
        raise ArtifactError("run record track or side is invalid")
    created_at = record.get("created_at")
    if not isinstance(created_at, str) or not _TIMESTAMP.fullmatch(created_at):
        raise ArtifactError("run record timestamp is invalid")
    try:
        parsed_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArtifactError("run record timestamp is invalid") from exc
    if parsed_at.utcoffset() is None:
        raise ArtifactError("run record timestamp must include a UTC offset")
    try:
        outcome = RunOutcome(record["outcome"])
    except (TypeError, ValueError) as exc:
        raise ArtifactError("run record outcome is invalid") from exc
    commit = record.get("git_commit")
    digest = record.get("binary_sha256")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ArtifactError("run record git commit is invalid")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ArtifactError("run record binary sha256 is invalid")
    upstream_codex = record.get("upstream_codex")
    if not isinstance(upstream_codex, dict) or upstream_codex != _UPSTREAM_CODEX_IDENTITY:
        raise ArtifactError("run record upstream Codex identity is invalid")
    expected = f"eval-data/runs/{run_id}"
    artifact_path = common_root / expected
    if record.get("artifacts") != expected or _path_present(artifact_path) and artifact_path.is_symlink():
        raise ArtifactError("run record artifact reference is invalid")
    if not isinstance(record.get("git_dirty"), bool):
        raise ArtifactError("run record git_dirty must be a boolean")
    config = record.get("config")
    summary = record.get("summary")
    tasks = record.get("tasks")
    metrics = record.get("metrics")
    if not isinstance(config, dict) or not isinstance(summary, dict):
        raise ArtifactError("run record config and summary must be objects")
    if tasks is not None and (
        not isinstance(tasks, list) or any(not isinstance(task, dict) or not task for task in tasks)
    ):
        raise ArtifactError("run record tasks must be a list of objects or null")
    if metrics is not None and not isinstance(metrics, dict):
        raise ArtifactError("run record metrics must be an object or null")
    if track == "tb" and metrics is not None:
        _validate_terminal_bench_metrics(metrics)
    cost = record.get("cost")
    if not isinstance(cost, dict) or set(cost) != {"estimated_usd", "actual_usd"}:
        raise ArtifactError("run record cost is invalid")
    for key, value in cost.items():
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
        ):
            raise ArtifactError(f"run record {key} must be a non-negative finite number or null")
    if not isinstance(record.get("notes"), str):
        raise ArtifactError("run record notes must be a string")
    if outcome is RunOutcome.COMPLETED:
        if not config or not summary or cost["estimated_usd"] is None:
            raise ArtifactError("completed run record is missing required results")
        if track == "tb" and (not tasks or metrics is None):
            raise ArtifactError("completed Terminal-Bench run requires tasks and external metrics")
        if track == "replay" and (tasks is not None or not metrics):
            raise ArtifactError("completed replay run requires metrics and null tasks")
        if track == "shadow" and not metrics:
            raise ArtifactError("completed shadow run requires metrics")


def _validate_terminal_bench_metrics(metrics: Mapping[str, Any]) -> None:
    expected = {
        "wall_seconds",
        "cpu_user_seconds",
        "cpu_system_seconds",
        "peak_rss_bytes",
        "exit_code",
    }
    if set(metrics) != expected:
        raise ArtifactError("Terminal-Bench metrics differ from schema v1")
    for key in ("wall_seconds", "cpu_user_seconds", "cpu_system_seconds"):
        value = metrics[key]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ArtifactError(f"Terminal-Bench {key} must be finite and non-negative")
    peak_rss = metrics["peak_rss_bytes"]
    if isinstance(peak_rss, bool) or not isinstance(peak_rss, int) or peak_rss <= 0:
        raise ArtifactError("Terminal-Bench peak_rss_bytes must be a positive integer")
    exit_code = metrics["exit_code"]
    if (
        isinstance(exit_code, bool)
        or not isinstance(exit_code, int)
        or not 0 <= exit_code <= 255
    ):
        raise ArtifactError("Terminal-Bench exit_code must be between 0 and 255")


def _normalize_secrets(secrets: Iterable[str]) -> tuple[bytes, ...]:
    normalized: list[bytes] = []
    try:
        for secret in secrets:
            if not isinstance(secret, str):
                raise ArtifactError("configured secrets must be strings")
            if secret:
                raw = secret.encode("utf-8")
                escaped = json.dumps(secret, ensure_ascii=False)[1:-1].encode("utf-8")
                normalized.append(raw)
                if escaped != raw:
                    normalized.append(escaped)
    except TypeError as exc:
        raise ArtifactError("configured secrets must be iterable") from exc
    return tuple(normalized)


def _encode_record(record: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            record,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ArtifactError("run record is not JSON serializable") from exc


def _scan_bytes(contents: bytes, secrets: tuple[bytes, ...], label: str) -> None:
    if _SENSITIVE_ASSIGNMENT.search(contents) or _AUTH_HEADER.search(contents):
        raise ArtifactError(f"{label} contains a sensitive key or header")
    if _URL_CREDENTIAL.search(contents):
        raise ArtifactError(f"{label} contains URL credentials")
    if any(secret in contents for secret in secrets):
        raise ArtifactError(f"{label} contains a configured secret value")


def _bytes_identity(contents: bytes) -> dict[str, int | str]:
    return {"size": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}


def _artifact_tree_identity(root: Path, secrets: tuple[bytes, ...]) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise ArtifactError("artifact tree is unsafe")
    entries: list[dict[str, Any]] = []
    total_size = 0
    try:
        paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    except OSError as exc:
        raise ArtifactError("artifact tree cannot be scanned safely") from exc
    for path in paths:
        relative = path.relative_to(root).as_posix()
        try:
            before = path.lstat()
        except OSError as exc:
            raise ArtifactError("artifact tree cannot be scanned safely") from exc
        if stat.S_ISLNK(before.st_mode):
            raise ArtifactError("artifact tree contains a symlink")
        mode = stat.S_IMODE(before.st_mode)
        if stat.S_ISDIR(before.st_mode):
            entries.append({"path": relative, "type": "directory", "mode": mode})
            continue
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactError("artifact tree contains an unsafe entry")
        size = before.st_size
        total_size += size
        if size > _MAX_SCAN_BYTES or total_size > _MAX_SCAN_BYTES:
            raise ArtifactError("artifacts exceed the bounded secret scan size")
        try:
            contents = path.read_bytes()
            after = path.lstat()
        except OSError as exc:
            raise ArtifactError("artifact cannot be scanned safely") from exc
        if (
            not stat.S_ISREG(after.st_mode)
            or before.st_dev != after.st_dev
            or before.st_ino != after.st_ino
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(contents) != size
        ):
            raise ArtifactError("artifact changed while it was being scanned")
        _scan_bytes(contents, secrets, "artifact")
        entries.append(
            {
                "path": relative,
                "type": "file",
                "mode": mode,
                "size": size,
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        )
    payload = {
        "schema_version": 1,
        "root_mode": stat.S_IMODE(root.stat().st_mode),
        "total_size": total_size,
        "entries": entries,
    }
    return {**payload, "tree_sha256": hashlib.sha256(_encode_record(payload)).hexdigest()}


def _assert_artifact_tree_identity(root: Path, expected: object) -> None:
    if not isinstance(expected, dict) or _artifact_tree_identity(root, ()) != expected:
        raise ArtifactError("artifact tree differs from its publication journal")


def _read_index(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    if not _path_present(path):
        return b"", []
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("tracked run index is unsafe")
    try:
        contents = path.read_bytes()
        text = contents.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArtifactError("tracked run index cannot be checked safely") from exc
    if contents and not contents.endswith(b"\n"):
        raise ArtifactError("tracked run index contains a partial row")
    rows: list[dict[str, Any]] = []
    run_ids: set[str] = set()
    for line in text.splitlines():
        if not line:
            raise ArtifactError("tracked run index contains an empty row")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ArtifactError("tracked run index contains invalid JSON") from exc
        run_id = row.get("run_id") if isinstance(row, dict) else None
        if not isinstance(run_id, str):
            raise ArtifactError("tracked run index contains an invalid row")
        if run_id in run_ids:
            raise ArtifactError("tracked run index contains a duplicate run id")
        run_ids.add(run_id)
        rows.append(row)
    return contents, rows


def _index_temporary_name(run_id: str) -> str:
    validate_run_id(run_id)
    return f".runs.jsonl.publish-{run_id}.tmp"


def _discard_index_temporary(path: Path) -> None:
    if not _path_present(path):
        return
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("tracked run index temporary path is unsafe")
    path.unlink()
    _fsync_directory(path.parent)


def _write_all(descriptor: int, contents: bytes) -> None:
    view = memoryview(contents)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("short file write")
        view = view[written:]


def _atomic_replace_index(path: Path, contents: bytes, temporary_name: str) -> None:
    if Path(temporary_name).name != temporary_name or not temporary_name.startswith(
        ".runs.jsonl.publish-"
    ):
        raise ArtifactError("tracked run index temporary name is invalid")
    temporary = path.parent / temporary_name
    _discard_index_temporary(temporary)
    descriptor: int | None = None
    try:
        descriptor = _open_new_regular_file(temporary, 0o644)
        _write_all(descriptor, contents)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
            _fsync_directory(temporary.parent)
        raise


def _run_id_exists(path: Path, run_id: str) -> bool:
    _contents, rows = _read_index(path)
    return any(row["run_id"] == run_id for row in rows)


def _read_publication_journal(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("artifact publication journal is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArtifactError("artifact publication journal is invalid") from exc
    fields = {
        "schema_version",
        "run_id",
        "staging_name",
        "results",
        "index_temporary_name",
        "index_before",
        "index_after",
        "record_identity",
        "tree_identity",
        "record",
    }
    if not isinstance(value, dict) or set(value) != fields or value.get("schema_version") != 2:
        raise ArtifactError("artifact publication journal differs from schema v2")
    run_id = value.get("run_id")
    if not isinstance(run_id, str):
        raise ArtifactError("artifact publication journal run id is invalid")
    validate_run_id(run_id)
    if path.name != f".{run_id}.publish.json":
        raise ArtifactError("artifact publication journal filename is invalid")
    staging_name = value.get("staging_name")
    if (
        not isinstance(staging_name, str)
        or Path(staging_name).name != staging_name
        or not staging_name.startswith(f".{run_id}.staging-")
    ):
        raise ArtifactError("artifact publication journal has an unsafe staging path")
    results = value.get("results")
    if (
        not isinstance(results, str)
        or Path(results).is_absolute()
        or not Path(results).parts
        or any(part in {"", ".", ".."} for part in Path(results).parts)
    ):
        raise ArtifactError("artifact publication journal result path is invalid")
    if value.get("index_temporary_name") != _index_temporary_name(run_id):
        raise ArtifactError("artifact publication journal temporary path is invalid")
    for key in ("index_before", "index_after", "record_identity"):
        identity = value.get(key)
        if (
            not isinstance(identity, dict)
            or set(identity) != {"size", "sha256"}
            or not isinstance(identity.get("size"), int)
            or isinstance(identity.get("size"), bool)
            or identity["size"] < 0
            or not isinstance(identity.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])
        ):
            raise ArtifactError("artifact publication journal identity is invalid")
    if not isinstance(value.get("tree_identity"), dict) or not isinstance(value.get("record"), dict):
        raise ArtifactError("artifact publication journal payload is invalid")
    return value


def _write_private_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    if _path_present(path) or _path_present(temporary):
        raise ArtifactError("artifact publication journal already exists or is unsafe")
    payload = _encode_record(value) + b"\n"
    try:
        descriptor = _open_new_regular_file(temporary, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _make_directories(path: Path, boundary: Path, *, mode: int = 0o755) -> None:
    _require_directory(boundary, "path boundary")
    _require_below(path, boundary, "directory")
    current = boundary
    for part in path.relative_to(boundary).parts:
        current = current / part
        if current.is_symlink():
            raise ArtifactError("directory path contains a symlink")
        if current.exists():
            if not current.is_dir():
                raise ArtifactError("directory path contains a non-directory")
        else:
            current.mkdir(mode=mode)


def _assert_safe_index_paths(results: Path, lock: Path, boundary: Path) -> None:
    for path, label in ((results, "tracked run index"), (lock, "tracked run lock")):
        _require_below(path, boundary, label)
        _assert_no_symlink_components(boundary, path.parent)
        if path.is_symlink() or (_path_present(path) and not path.is_file()):
            raise ArtifactError(f"{label} is unsafe")


def _assert_no_symlink_components(boundary: Path, path: Path) -> None:
    _require_below(path, boundary, "path")
    current = boundary
    if current.is_symlink():
        raise ArtifactError("path boundary must not be a symlink")
    for part in path.relative_to(boundary).parts:
        current = current / part
        if current.is_symlink():
            raise ArtifactError("path contains a symlink")


def _require_below(path: Path, boundary: Path, label: str) -> None:
    if not path.is_absolute() or not boundary.is_absolute():
        raise ArtifactError(f"{label} must be absolute")
    if ".." in path.parts or ".." in boundary.parts:
        raise ArtifactError(f"{label} contains an unresolved parent component")
    try:
        path.relative_to(boundary)
    except ValueError as exc:
        raise ArtifactError(f"{label} escapes the common root") from exc


def _require_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise ArtifactError(f"{label} must be a real directory")


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _match_run_id(run_id: str) -> re.Match[str] | None:
    match = _RUN_ID.fullmatch(run_id)
    if match is None:
        return None
    try:
        datetime.strptime(match.group("stamp"), "%Y%m%d-%H%M%S%f")
    except ValueError:
        return None
    return match


def _open_new_regular_file(path: Path, mode: int) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ArtifactError("new artifact path is not a regular file")
    return descriptor


def _open_lock_file(path: Path):
    descriptor = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        descriptor |= os.O_NOFOLLOW
    file_descriptor = os.open(path, descriptor, 0o600)
    if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
        os.close(file_descriptor)
        raise ArtifactError("tracked run lock is not a regular file")
    return os.fdopen(file_descriptor, "r+b")


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


if os.name == "nt":
    import msvcrt

    def _lock(handle) -> None:
        handle.seek(0)
        if handle.read(1) == b"":
            handle.seek(0)
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
