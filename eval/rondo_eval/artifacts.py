"""Private raw artifacts plus a locked append-only tracked run index."""

from __future__ import annotations

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
    rb"(?:^|[,{\s])[\"']?(?:[a-z0-9]+[-_])*(?:api[-_]?key|access[-_]?token|bearer[-_]?token|"
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
        self._recover_pending_publication()
        self._assert_run_paths()
        self._assert_run_unclaimed()
        self.staging.mkdir(mode=0o700)
        self._started = True
        return self

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
        except Exception:
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
        self._scan_staging(secret_bytes)
        _scan_bytes(_encode_record(record), secret_bytes, "tracked run record")
        _make_directories(self.results.parent, self.paths.common_root)
        lock_path = self.results.with_suffix(".jsonl.lock")
        _assert_safe_index_paths(self.results, lock_path, self.paths.common_root)
        with _open_lock_file(lock_path) as lock_handle:
            _lock(lock_handle)
            try:
                self._assert_publication_paths()
                if _run_id_exists(self.results, self.run_id):
                    raise ArtifactError("run id is already present in the tracked index")
                self._write_journal(record)
                os.replace(self.staging, self.target)
                _fsync_directory(self.runs_root)
                try:
                    _append_json_line(self.results, record)
                except Exception:
                    os.replace(self.target, self.staging)
                    _fsync_directory(self.runs_root)
                    raise
                self.journal.unlink()
                _fsync_directory(self.runs_root)
            finally:
                _unlock(lock_handle)
        self._started = False
        return self.target

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

    def _scan_staging(self, secrets: tuple[bytes, ...]) -> None:
        total_size = 0
        for path in self.staging.rglob("*"):
            if path.is_symlink() or (not path.is_file() and not path.is_dir()):
                raise ArtifactError("artifact staging tree contains an unsafe entry")
            if not path.is_file():
                continue
            size = path.stat().st_size
            total_size += size
            if size > _MAX_SCAN_BYTES or total_size > _MAX_SCAN_BYTES:
                raise ArtifactError("artifacts exceed the bounded secret scan size")
            try:
                contents = path.read_bytes()
            except OSError as exc:
                raise ArtifactError("artifact cannot be scanned safely") from exc
            _scan_bytes(contents, secrets, "artifact")

    def _write_journal(self, record: Mapping[str, Any]) -> None:
        try:
            results_relative = self.results.relative_to(self.paths.common_root).as_posix()
        except ValueError as exc:  # pragma: no cover - guarded by root validation
            raise ArtifactError("tracked result path escapes the common root") from exc
        value = {
            "schema_version": 1,
            "run_id": self.run_id,
            "staging_name": self.staging.name,
            "results": results_relative,
            "record": dict(record),
        }
        _write_private_json(self.journal, value)
        _fsync_directory(self.runs_root)

    def _recover_pending_publication(self) -> None:
        if not _path_present(self.journal):
            return
        if self.journal.is_symlink() or not self.journal.is_file():
            raise ArtifactError("artifact publication journal is unsafe")
        try:
            value = json.loads(self.journal.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactError("artifact publication journal is invalid") from exc
        expected_results = self.results.relative_to(self.paths.common_root).as_posix()
        if (
            not isinstance(value, dict)
            or set(value) != {"schema_version", "run_id", "staging_name", "results", "record"}
            or value.get("schema_version") != 1
            or value.get("run_id") != self.run_id
            or value.get("results") != expected_results
            or not isinstance(value.get("record"), dict)
        ):
            raise ArtifactError("artifact publication journal does not match this writer")
        staging_name = value.get("staging_name")
        if not isinstance(staging_name, str) or Path(staging_name).name != staging_name:
            raise ArtifactError("artifact publication journal has an unsafe staging path")
        staged = self.runs_root / staging_name
        if not staging_name.startswith(f".{self.run_id}.staging-"):
            raise ArtifactError("artifact publication journal has an invalid staging path")
        record = value["record"]
        _validate_record(record, self.run_id, self.paths.common_root)
        _scan_bytes(_encode_record(record), (), "tracked run record")
        _make_directories(self.results.parent, self.paths.common_root)
        lock_path = self.results.with_suffix(".jsonl.lock")
        _assert_safe_index_paths(self.results, lock_path, self.paths.common_root)
        with _open_lock_file(lock_path) as lock_handle:
            _lock(lock_handle)
            try:
                indexed = _run_id_exists(self.results, self.run_id)
                target_present = _path_present(self.target)
                staged_present = _path_present(staged)
                if indexed:
                    if not target_present or staged_present:
                        raise ArtifactError("published run has inconsistent recovery state")
                    self.journal.unlink()
                    _fsync_directory(self.runs_root)
                    return
                if not target_present:
                    if not staged_present or staged.is_symlink() or not staged.is_dir():
                        raise ArtifactError("pending artifact staging directory is unavailable")
                    _assert_no_symlink_components(self.runs_root, staged)
                    os.replace(staged, self.target)
                    _fsync_directory(self.runs_root)
                elif staged_present or self.target.is_symlink() or not self.target.is_dir():
                    raise ArtifactError("pending artifact publication state is inconsistent")
                try:
                    _append_json_line(self.results, record)
                except Exception:
                    os.replace(self.target, staged)
                    _fsync_directory(self.runs_root)
                    raise
                self.journal.unlink()
                _fsync_directory(self.runs_root)
            finally:
                _unlock(lock_handle)


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
        if not config or not summary or any(value is None for value in cost.values()):
            raise ArtifactError("completed run record is missing required results")
        if track == "tb" and (not tasks or metrics is not None):
            raise ArtifactError("completed Terminal-Bench run requires tasks and no metrics")
        if track == "replay" and (tasks is not None or not metrics):
            raise ArtifactError("completed replay run requires metrics and null tasks")
        if track == "shadow" and not metrics:
            raise ArtifactError("completed shadow run requires metrics")


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


def _append_json_line(path: Path, record: Mapping[str, Any]) -> None:
    payload = _encode_record(record) + b"\n"
    descriptor = _open_append_file(path, 0o644)
    try:
        original_size = os.lseek(descriptor, 0, os.SEEK_END)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short JSONL append")
                view = view[written:]
            os.fsync(descriptor)
        except Exception:
            os.ftruncate(descriptor, original_size)
            os.fsync(descriptor)
            raise
    finally:
        os.close(descriptor)


def _run_id_exists(path: Path, run_id: str) -> bool:
    if not _path_present(path):
        return False
    if path.is_symlink() or not path.is_file():
        raise ArtifactError("tracked run index is unsafe")
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ArtifactError("tracked run index contains invalid JSON") from exc
                if not isinstance(row, dict) or not isinstance(row.get("run_id"), str):
                    raise ArtifactError("tracked run index contains an invalid row")
                if row["run_id"] == run_id:
                    return True
    except (OSError, UnicodeError) as exc:
        raise ArtifactError("tracked run index cannot be checked safely") from exc
    return False


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
    except Exception:
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


def _open_append_file(path: Path, mode: int) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ArtifactError("tracked run index is not a regular file")
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
