"""On-disk M-5 archive and scratch paths under ignored eval-data/."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from .archive import REQUIRED_ARCHIVE_FIELDS

ARCHIVE_RELPATH = "eval-data/multi-m5/archives/records.jsonl"
CAPTURE_RELDIR = "eval-data/multi-m5/captures"
BUDGET_RELPATH = "eval-data/budgets/multi-m5-phase-b.json"
SMOKE_ARCHIVE_RELPATH = "eval-data/multi-m5/archives/clean-smoke-v4-records.jsonl"
# The exploratory runs, runtime-v2 clean smokes, and sandbox-blocked v3 row stay
# immutable. Runtime-v3 gets a fresh one-run v4 identity for the replacement.
SMOKE_BUDGET_RELPATH = "eval-data/budgets/multi-m5-clean-smoke-v4.json"


class StoreError(ValueError):
    """Raised when an M-5 archive cannot be written fail-closed."""


def archive_path(common_root: Path) -> Path:
    return _under_eval_data(common_root, ARCHIVE_RELPATH)


def smoke_archive_path(common_root: Path) -> Path:
    """Separate file for the pre-contract smoke run.

    Kept out of the contract archive on purpose: a real-API row sitting beside
    the gate rows invites being read as gate evidence later, and this run is
    explicitly not that.
    """

    return _under_eval_data(common_root, SMOKE_ARCHIVE_RELPATH)


def smoke_ledger_path(common_root: Path) -> Path:
    return _under_eval_data(common_root, SMOKE_BUDGET_RELPATH)


def capture_dir(common_root: Path, run_id: str) -> Path:
    _require_run_id(run_id)
    return _under_eval_data(common_root, f"{CAPTURE_RELDIR}/{run_id}")


def budget_ledger_path(common_root: Path) -> Path:
    return _under_eval_data(common_root, BUDGET_RELPATH)


def scratch_root(common_root: Path) -> Path:
    """Host CODEX_HOME must not live under /tmp: the release binary refuses PATH aliases there."""

    root = common_root / "eval-data" / "tmp"
    if root.exists() and (root.is_symlink() or not root.is_dir()):
        raise StoreError("scratch is not a regular directory")
    root.mkdir(mode=0o700, exist_ok=True)
    resolved = root.resolve()
    if resolved != (common_root / "eval-data" / "tmp").resolve() or resolved.is_symlink():
        raise StoreError("scratch must stay under eval-data/tmp")
    return resolved


def persist_archive_record(
    record: Mapping[str, Any],
    *,
    common_root: Path,
    path: Path | None = None,
) -> Path:
    """Append one archive dict. Gate 1 must carry ignored_evidence (F4)."""

    _require_archive(record)
    target = path or archive_path(common_root)
    _require_eval_data_file(common_root, target)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise StoreError("archive jsonl path is unsafe")
    payload = json.dumps(dict(record), sort_keys=True, separators=(",", ":")) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, payload.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return target


def load_archive_records(path: Path) -> tuple[dict[str, Any], ...]:
    if path.is_symlink() or not path.is_file():
        raise StoreError("archive jsonl is not a regular file")
    records: list[dict[str, Any]] = []
    for line in path.read_text("utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise StoreError("archive jsonl line is not an object")
        _require_archive(value)
        records.append(value)
    return tuple(records)


def _require_archive(record: Mapping[str, Any]) -> None:
    missing = [name for name in REQUIRED_ARCHIVE_FIELDS if name not in record]
    if missing:
        raise StoreError("archive record is missing required fields")
    kind = record.get("evidence_kind")
    if kind not in {"loopback", "fake", "real_api"}:
        raise StoreError("archive evidence kind is not an M-5 partition")
    gate = record.get("gate")
    if gate == 1 and "ignored_evidence" not in record:
        raise StoreError("gate 1 archive must include ignored_evidence")
    if gate == 2:
        for name in ("task_id", "round_index", "counts_as_effective"):
            if name not in record:
                raise StoreError("gate 2 archive must include task_id, round_index, and counts_as_effective")


def _under_eval_data(common_root: Path, relpath: str) -> Path:
    if ".." in relpath.split("/"):
        raise StoreError("M-5 path escaped eval-data")
    if not relpath.startswith("eval-data/"):
        raise StoreError("M-5 artifacts must stay under eval-data/")
    return (common_root / relpath).resolve()


def _require_eval_data_file(common_root: Path, path: Path) -> None:
    root = (common_root / "eval-data").resolve()
    resolved = path if path.is_absolute() else (common_root / path).resolve()
    if not resolved.is_relative_to(root):
        raise StoreError("M-5 archive path escaped eval-data/")


def _require_run_id(run_id: str) -> None:
    if not run_id or any(part in run_id for part in ("/", "..", "\\")):
        raise StoreError("run id is unsafe")
