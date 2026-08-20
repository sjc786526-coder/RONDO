"""Narrow, fail-closed resume primitives for the formal M-5 v6 batch."""

from __future__ import annotations

import json
import os
import stat
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from ..api_budget_proxy import ApiBudgetProxyError, PersistentBudgetLedger
from .budget import BATCH_ID
from .load import NONDEGRADATION_LOCK_ID, RUNTIME_LOCK_ID, WORKFLOW_LOCK_ID
from .store import load_archive_records


class ResumeError(ValueError):
    """Raised when formal archive/ledger state is not a safe schedule prefix."""


def formal_identity(provider_identity: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(provider_identity, Mapping) or not provider_identity:
        raise ResumeError("formal resume requires a frozen provider identity")
    return {
        "budget_batch_id": BATCH_ID,
        "workflow_lock_id": WORKFLOW_LOCK_ID,
        "nondegradation_lock_id": NONDEGRADATION_LOCK_ID,
        "runtime_lock_id": RUNTIME_LOCK_ID,
        "provider_identity": dict(provider_identity),
    }


def require_formal_receipt(path: Path, identity: Mapping[str, Any]) -> None:
    if path.is_symlink() or not path.is_file():
        raise ResumeError("formal batch identity receipt is unsafe")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ResumeError("formal batch identity receipt must have mode 0600")
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResumeError("formal batch identity receipt is invalid") from exc
    if value != {"schema_version": 1, **dict(identity)}:
        raise ResumeError("formal batch identity receipt differs")


def ensure_formal_receipt(path: Path, identity: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        require_formal_receipt(path, identity)
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise ResumeError("formal batch identity receipt parent is unsafe") from exc
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise ResumeError("formal batch identity receipt parent is unsafe")
    payload = (
        json.dumps(
            {"schema_version": 1, **dict(identity)},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(path, 0o600)
    except OSError as exc:
        raise ResumeError("formal batch identity receipt could not be created") from exc


def load_formal_records(
    path: Path,
    *,
    identity: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    if path.is_symlink():
        raise ResumeError("formal v6 archive path is unsafe")
    if not path.exists():
        return ()
    records = load_archive_records(path)
    seen: set[str] = set()
    for record in records:
        if record.get("evidence_kind") != "real_api":
            raise ResumeError("formal v6 archive contains non-real evidence")
        if record.get("gate") not in {1, 2}:
            raise ResumeError("formal v6 archive has an invalid gate")
        run_id = record.get("budget_run_id")
        if not isinstance(run_id, str) or not run_id:
            raise ResumeError("formal v6 archive row has no budget run id")
        if run_id in seen:
            raise ResumeError("formal v6 archive repeats a budget run id")
        seen.add(run_id)
        for name, expected in identity.items():
            if record.get(name) != expected:
                raise ResumeError(f"formal v6 archive {name} differs")
        expected_lock = (
            WORKFLOW_LOCK_ID if record["gate"] == 1 else NONDEGRADATION_LOCK_ID
        )
        if record.get("lock_id") != expected_lock:
            raise ResumeError("formal v6 archive row names the wrong gate lock")
        if record.get("outcome") not in {
            "completed",
            "agent_failed",
            "infra_failed",
            "budget_stopped",
        }:
            raise ResumeError("formal v6 archive row has an invalid outcome")
        if record.get("abandoned") not in {None, True}:
            raise ResumeError("formal v6 archive abandoned flag is invalid")
        if record.get("abandoned") is True and (
            record.get("outcome") != "infra_failed"
            or record.get("counts_as_effective") is not False
        ):
            raise ResumeError("an abandoned run must be non-effective infra")
    return records


def claimed_run_disposition(
    ledger: PersistentBudgetLedger,
    run_id: str,
    *,
    cap_usd: Decimal,
    conflict_paths: tuple[Path, ...] = (),
) -> str:
    """Return new/reclaimed/abandon, refusing ambiguous zero-use state."""

    run = ledger.snapshot()["runs"].get(run_id)
    if run is None:
        return "new"
    if not isinstance(run, dict):
        raise ResumeError("formal ledger run state is invalid")
    requests = run.get("requests")
    if not isinstance(requests, dict):
        raise ResumeError("formal ledger requests state is invalid")
    conflicts = [
        path for path in conflict_paths if path.exists() or path.is_symlink()
    ]
    if not requests:
        if conflicts:
            raise ResumeError("zero-request run has conflicting artifacts")
        try:
            ledger.resume_pristine_run(run_id, cap_usd=cap_usd)
        except ApiBudgetProxyError as exc:
            raise ResumeError("zero-request run is not safely reclaimable") from exc
        return "reclaimed"
    return "abandon"


def require_archived_runs_in_ledger(
    records: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ledger: PersistentBudgetLedger,
) -> None:
    runs = ledger.snapshot().get("runs")
    if not isinstance(runs, dict):
        raise ResumeError("formal ledger runs state is invalid")
    missing = [row["budget_run_id"] for row in records if row["budget_run_id"] not in runs]
    if missing:
        raise ResumeError("formal archive names a run missing from the ledger")


def require_single_unarchived_run(
    records: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ledger: PersistentBudgetLedger,
    *,
    expected_run_id: str | None,
) -> None:
    runs = ledger.snapshot().get("runs")
    if not isinstance(runs, dict):
        raise ResumeError("formal ledger runs state is invalid")
    archived = {str(row["budget_run_id"]) for row in records}
    unarchived = sorted(set(runs) - archived)
    if not unarchived:
        return
    if len(unarchived) != 1 or unarchived[0] != expected_run_id:
        raise ResumeError("formal ledger has a future or conflicting unarchived run")


def require_contiguous_attempts(attempts: list[int], *, maximum: int) -> None:
    if not attempts:
        return
    if attempts != list(range(1, len(attempts) + 1)) or attempts[-1] > maximum:
        raise ResumeError("formal archive attempts are not a contiguous prefix")


def validate_gate1_resume_prefix(
    records: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    *,
    maximum: int,
) -> dict[int, dict[str, Any]]:
    """Validate and index the one legal Gate 1 prefix shared by both gates."""

    archived_by_attempt: dict[int, dict[str, Any]] = {}
    gate2_seen = False
    for record in records:
        if record.get("gate") == 2:
            gate2_seen = True
            continue
        if record.get("gate") != 1:
            continue
        if gate2_seen:
            raise ResumeError("formal gate 1 row appears after gate 2 started")
        attempt = record.get("attempt")
        if isinstance(attempt, bool) or not isinstance(attempt, int):
            raise ResumeError("formal gate 1 archive attempt is invalid")
        if record.get("budget_run_id") != f"m5-g1-v6-paid-a{attempt}":
            raise ResumeError("formal gate 1 archive run id differs")
        if record.get("counts_as_effective") is not False:
            raise ResumeError("formal gate 1 row cannot count as effective")
        if record.get("passed") is not (record.get("outcome") == "completed"):
            raise ResumeError("formal gate 1 pass flag differs from its outcome")
        archived_by_attempt[attempt] = record
    require_contiguous_attempts(sorted(archived_by_attempt), maximum=maximum)
    terminal_attempts = [
        attempt
        for attempt, row in archived_by_attempt.items()
        if row.get("outcome") in {"completed", "budget_stopped"}
    ]
    if terminal_attempts and terminal_attempts != [max(archived_by_attempt)]:
        raise ResumeError("formal gate 1 archive continues after a terminal row")
    if gate2_seen:
        last = archived_by_attempt.get(max(archived_by_attempt, default=0))
        if last is None or last.get("outcome") != "completed":
            raise ResumeError("formal gate 2 rows exist before gate 1 completed")
    return archived_by_attempt
