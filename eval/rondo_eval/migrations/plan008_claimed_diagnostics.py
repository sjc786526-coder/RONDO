"""One-time F-08 migration for the three retained Plan 008 diagnostics.

The default command is a read-only preview.  ``--apply`` only publishes corrected
``infra_failed`` records and small provenance artifacts; it never edits the budget
ledger or the retained Harbor work directories.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from ..artifacts import ArtifactError, ArtifactWriter, _read_index
from ..config import RepoPaths


MIGRATION_ID = "plan008-f08-claimed-diagnostics-v1"
_BATCH_ID = "p1-fix-git-20260810"
_SOURCE_REVISION = "d72c222b6ac1a6c3f2c82681e34b4094ea6e5cc0"
_SOURCE_OBJECT = f"{_SOURCE_REVISION}:eval/results/runs.jsonl"
_SOURCE_SHA256 = "0a89579d04829d987ec811ca61adebf1161b0be268a51b342e5a01bb3e51523f"
_LEDGER_SHA256 = "22eaa6be79d59e4e891d21380e7e884e6471fa34e782ddbbf0aad8d0fd49fca8"


class MigrationError(ValueError):
    """Raised when the retained evidence cannot support this fixed migration."""


@dataclass(frozen=True)
class _EvidenceSpec:
    row_sha256: str
    job_sha256: str
    trial_sha256: str
    exception_type: str
    message_marker: str


_EVIDENCE = {
    "20260810-022300000-tb-codex-r1": _EvidenceSpec(
        row_sha256="5258109d698f0623b6bfc0125da6e88080643441aaa5174ea3b90c8d5711e3b4",
        job_sha256="8d5b060c043aa0094bdc713806028f4f1651f76e4212372e5267402c4ac26705",
        trial_sha256="c0b0e519c28370ca1c2878064a0159ca1c69966e1672745e16c8dd8dfd5b7376",
        exception_type="AdapterError",
        message_marker="container command failed",
    ),
    "20260810-024000000-tb-codex-r2": _EvidenceSpec(
        row_sha256="e3928195055ec9e4f2a3e5d85a3658b00f4c00658a550b80b1235b7f858bf18a",
        job_sha256="55d5579cd78bd853654b33a08eecaa08f77daf3ae3da6a72a38e36df63fa9c0b",
        trial_sha256="b2aa034aed30dfac84fa7eee650852af5578203f0f0b4b4c131da2a4260708d1",
        exception_type="NonZeroAgentExitCodeError",
        message_marker="GLIBC_2.39",
    ),
    "20260810-032600000-tb-codex-r3": _EvidenceSpec(
        row_sha256="bbad5f2d90f863ea74de67010608c34f59e3b188e4252a90d1d6e1abb42dd0cd",
        job_sha256="2fe700195d3c87393fe04232aab88799ba74aec138e2a93f83d79e793eeecce1",
        trial_sha256="f504ffbd02a4773c4ae98cb9b528f4c960bda823c33432e72cedcc9394e5a475",
        exception_type="NonZeroAgentExitCodeError",
        message_marker="reserved built-in provider IDs",
    ),
}


@dataclass(frozen=True)
class _PreparedRun:
    run_id: str
    status: str
    record: dict[str, Any]
    artifact: dict[str, Any]


def prepare_migration(
    common_root: Path,
    results_worktree_root: Path,
    *,
    source_bytes: bytes | None = None,
) -> tuple[_PreparedRun, ...]:
    """Validate all immutable evidence and return a side-effect-free migration plan."""

    common_root = _real_directory(common_root, "common root")
    results_worktree_root = _real_directory(results_worktree_root, "results worktree root")
    try:
        results_worktree_root.relative_to(common_root)
    except ValueError as exc:
        raise MigrationError("results worktree root must stay below the common root") from exc
    source = source_bytes if source_bytes is not None else _git_source(common_root)
    if _sha256(source) != _SOURCE_SHA256:
        raise MigrationError("provisional Git result source differs from the frozen migration input")
    provisional = _provisional_rows(source)
    ledger_path = common_root / "eval-data" / "budgets" / f"{_BATCH_ID}.json"
    ledger_bytes = _regular_bytes(ledger_path, "budget ledger")
    if _sha256(ledger_bytes) != _LEDGER_SHA256:
        raise MigrationError("budget ledger differs from the reviewed F-08 evidence")
    ledger = _json_object(ledger_bytes, "budget ledger")
    _validate_ledger(ledger)

    results_path = results_worktree_root / "eval" / "results" / "runs.jsonl"
    _contents, existing_rows = _read_index(results_path)
    existing = {row["run_id"]: row for row in existing_rows}
    prepared: list[_PreparedRun] = []
    for run_id, evidence in _EVIDENCE.items():
        source_record = provisional[run_id]
        run_ledger = ledger["runs"][run_id]
        corrected = _corrected_record(source_record, run_ledger)
        work_evidence = _expected_work_evidence(run_id, evidence)
        artifact = {
            "schema_version": 1,
            "migration_id": MIGRATION_ID,
            "run_id": run_id,
            "source_revision": _SOURCE_REVISION,
            "source_row_sha256": evidence.row_sha256,
            "ledger_sha256": _LEDGER_SHA256,
            "ledger_requests": 0,
            "ledger_spent_usd": "0.000000",
            "work": work_evidence,
            "correction": {"outcome": "infra_failed", "attribution": "infra"},
        }
        target = common_root / "eval-data" / "runs" / run_id
        current = existing.get(run_id)
        if current == corrected and _migration_artifact_matches(target, artifact):
            status = "already_applied"
        elif current is not None or _path_present(target):
            status = "conflict"
        else:
            actual_work = _validate_work(common_root, run_id, source_record, evidence)
            if actual_work != work_evidence:
                raise MigrationError(f"retained work identity differs: {run_id}")
            status = "pending"
        prepared.append(_PreparedRun(run_id, status, corrected, artifact))
    return tuple(prepared)


def preview(prepared: tuple[_PreparedRun, ...]) -> dict[str, Any]:
    """Return a bounded JSON-safe preview without raw logs or model prompts."""

    return {
        "schema_version": 1,
        "migration_id": MIGRATION_ID,
        "mode": "dry-run",
        "source_revision": _SOURCE_REVISION,
        "batch_id": _BATCH_ID,
        "runs": [
            {
                "run_id": item.run_id,
                "status": item.status,
                "outcome": "infra_failed",
                "request_count": 0,
                "spent_usd": "0.000000",
                "work_job_sha256": item.artifact["work"]["job_result_sha256"],
                "work_trial_sha256": item.artifact["work"]["trial_result_sha256"],
            }
            for item in prepared
        ],
    }


def apply_migration(
    common_root: Path,
    results_worktree_root: Path,
    *,
    source_bytes: bytes | None = None,
) -> tuple[_PreparedRun, ...]:
    """Publish pending rows; source work is read-only and may be removed afterward."""

    prepared = prepare_migration(
        common_root,
        results_worktree_root,
        source_bytes=source_bytes,
    )
    conflicts = [item.run_id for item in prepared if item.status == "conflict"]
    if conflicts:
        raise MigrationError(f"migration conflicts with existing state: {', '.join(conflicts)}")
    paths = RepoPaths(Path(common_root), Path(results_worktree_root))
    for item in prepared:
        if item.status == "already_applied":
            continue
        writer = ArtifactWriter(
            paths,
            item.run_id,
            results_worktree_root=Path(results_worktree_root),
        ).start()
        writer.write_json("migration.json", item.artifact)
        writer.finalize(item.record, secrets=())
    return prepare_migration(
        common_root,
        results_worktree_root,
        source_bytes=source_bytes,
    )


def _git_source(common_root: Path) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(common_root), "show", _SOURCE_OBJECT],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise MigrationError("frozen provisional Git result source is unavailable")
    return completed.stdout


def _provisional_rows(source: bytes) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for line in source.splitlines():
        row = _json_object(line, "provisional result row")
        run_id = row.get("run_id")
        evidence = _EVIDENCE.get(run_id) if isinstance(run_id, str) else None
        if evidence is None or _sha256(line) != evidence.row_sha256 or run_id in rows:
            raise MigrationError("provisional result rows differ from the reviewed F-08 set")
        rows[run_id] = row
    if set(rows) != set(_EVIDENCE):
        raise MigrationError("provisional result source is incomplete")
    return rows


def _validate_ledger(ledger: Mapping[str, Any]) -> None:
    expected_fields = {
        "schema_version",
        "batch_id",
        "total_cap_usd",
        "max_runs",
        "default_run_cap_usd",
        "runs",
    }
    if (
        set(ledger) != expected_fields
        or ledger.get("schema_version") != 1
        or ledger.get("batch_id") != _BATCH_ID
        or ledger.get("total_cap_usd") != "20.000000"
        or ledger.get("max_runs") != 4
        or ledger.get("default_run_cap_usd") != "5.000000"
        or not isinstance(ledger.get("runs"), dict)
        or set(ledger["runs"]) != set(_EVIDENCE)
    ):
        raise MigrationError("budget ledger does not match the reviewed F-08 batch")
    for run_id, run in ledger["runs"].items():
        if (
            not isinstance(run, dict)
            or set(run) != {"cap_usd", "spent_usd", "stopped", "stop_reason", "requests"}
            or run != {
                "cap_usd": "5.000000",
                "spent_usd": "0.000000",
                "stopped": False,
                "stop_reason": None,
                "requests": {},
            }
        ):
            raise MigrationError(f"budget ledger run evidence is not zero-API: {run_id}")


def _validate_work(
    common_root: Path,
    run_id: str,
    source_record: Mapping[str, Any],
    expected: _EvidenceSpec,
) -> dict[str, Any]:
    jobs = common_root / "eval-data" / "work" / run_id / "staging" / "jobs"
    job_directories = _child_directories(jobs, "Harbor jobs directory")
    if len(job_directories) != 1:
        raise MigrationError(f"retained work must contain exactly one job: {run_id}")
    job = job_directories[0]
    trial_directories = _child_directories(job, "Harbor job directory")
    if len(trial_directories) != 1:
        raise MigrationError(f"retained work must contain exactly one trial: {run_id}")
    trial = trial_directories[0]
    job_bytes = _regular_bytes(job / "result.json", "Harbor job result")
    trial_bytes = _regular_bytes(trial / "result.json", "Harbor trial result")
    if _sha256(job_bytes) != expected.job_sha256 or _sha256(trial_bytes) != expected.trial_sha256:
        raise MigrationError(f"retained work result digest differs: {run_id}")
    job_result = _json_object(job_bytes, "Harbor job result")
    trial_result = _json_object(trial_bytes, "Harbor trial result")
    exception = trial_result.get("exception_info")
    stats = job_result.get("stats")
    message = exception.get("exception_message") if isinstance(exception, dict) else None
    if (
        not isinstance(stats, dict)
        or stats.get("n_completed_trials") != 1
        or stats.get("n_errored_trials") != 1
        or trial_result.get("task_name") != "terminal-bench/fix-git"
        or not isinstance(exception, dict)
        or exception.get("exception_type") != expected.exception_type
        or not isinstance(message, str)
        or expected.message_marker not in message
    ):
        raise MigrationError(f"retained work does not prove the reviewed infrastructure failure: {run_id}")
    config = _json_object(_regular_bytes(trial / "config.json", "Harbor trial config"), "Harbor trial config")
    agent = config.get("agent")
    kwargs = agent.get("kwargs") if isinstance(agent, dict) else None
    if (
        not isinstance(kwargs, dict)
        or kwargs.get("binary_sha256") != source_record.get("binary_sha256")
        or kwargs.get("binary_source_commit")
        != source_record.get("upstream_codex", {}).get("commit")
    ):
        raise MigrationError(f"retained work binary identity differs: {run_id}")
    task = source_record.get("tasks")
    duration = task[0].get("duration_s") if isinstance(task, list) and len(task) == 1 else None
    started = _timestamp(trial_result.get("started_at"), "trial start")
    finished = _timestamp(trial_result.get("finished_at"), "trial finish")
    if not isinstance(duration, (int, float)) or abs((finished - started).total_seconds() - duration) > 0.001:
        raise MigrationError(f"retained work duration differs from the provisional row: {run_id}")
    return {
        "relative_path": jobs.parent.parent.relative_to(common_root).as_posix(),
        "job_result_sha256": expected.job_sha256,
        "trial_result_sha256": expected.trial_sha256,
        "exception_type": expected.exception_type,
    }


def _expected_work_evidence(run_id: str, expected: _EvidenceSpec) -> dict[str, Any]:
    return {
        "relative_path": f"eval-data/work/{run_id}",
        "job_result_sha256": expected.job_sha256,
        "trial_result_sha256": expected.trial_sha256,
        "exception_type": expected.exception_type,
    }


def _corrected_record(source: Mapping[str, Any], run_ledger: Mapping[str, Any]) -> dict[str, Any]:
    record = copy.deepcopy(dict(source))
    record["outcome"] = "infra_failed"
    record["summary"]["infra_failed"] = 1
    record["summary"]["success_rate"] = 0.0
    record["tasks"][0]["outcome"] = "fail"
    record["tasks"][0]["attribution"] = "infra"
    record["config"]["legacy_migration"] = MIGRATION_ID
    record["config"]["failure_stage"] = "runtime"
    spent = float(run_ledger["spent_usd"])
    record["cost"] = {"estimated_usd": spent, "actual_usd": spent}
    record["notes"] = (
        "One-time F-08 migration of a claimed, zero-API diagnostic; retained work proves an "
        "infrastructure failure. Historical external resource metrics remain unavailable."
    )
    return record


def _migration_artifact_matches(target: Path, expected: Mapping[str, Any]) -> bool:
    try:
        actual = _json_object(_regular_bytes(target / "migration.json", "migration artifact"), "migration artifact")
    except MigrationError:
        return False
    return actual == expected


def _child_directories(path: Path, label: str) -> list[Path]:
    path = _real_directory(path, label)
    result: list[Path] = []
    try:
        for entry in os.scandir(path):
            if entry.is_symlink():
                raise MigrationError(f"{label} contains a symlink")
            if entry.is_dir(follow_symlinks=False):
                result.append(Path(entry.path))
    except OSError as exc:
        raise MigrationError(f"{label} cannot be inspected safely") from exc
    return sorted(result)


def _real_directory(path: Path, label: str) -> Path:
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_dir() or path.resolve() != path:
        raise MigrationError(f"{label} must be a real directory")
    return path


def _regular_bytes(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise MigrationError(f"{label} must be a regular file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MigrationError(f"{label} cannot be read safely") from exc


def _json_object(contents: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(contents)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"{label} must be a JSON object")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise MigrationError(f"{label} is invalid")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MigrationError(f"{label} is invalid") from exc


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--results-worktree-root", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    results_root = args.results_worktree_root or args.repo_root
    try:
        if args.apply:
            if args.confirm != MIGRATION_ID:
                raise MigrationError(f"--apply requires --confirm {MIGRATION_ID}")
            prepared = apply_migration(args.repo_root, results_root)
            output = preview(prepared)
            output["mode"] = "applied"
        else:
            if args.confirm is not None:
                raise MigrationError("--confirm is only valid with --apply")
            output = preview(prepare_migration(args.repo_root, results_root))
    except (ArtifactError, MigrationError) as exc:
        parser.error(str(exc))
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
