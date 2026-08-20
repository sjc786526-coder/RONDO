"""One thin, injected Plan 049 orchestration state machine."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .aggregate import aggregate, synthetic_team_view, write_replay_artifacts
from .contract import CampaignContract
from .schedule import Slot, slots
from .store import RehearsalStore


VALID_OUTCOMES = {"completed", "task_failed", "product_failed"}


@dataclass(frozen=True)
class ExecutionResult:
    outcome: str
    trace_status: str = "synthetic_fixture"
    reason_code: str | None = None


class SlotExecutor(Protocol):
    def __call__(self, slot: Slot, attempt: int) -> ExecutionResult: ...


def run_rehearsal(
    contract: CampaignContract,
    *,
    common_root: Path,
    namespace: str,
    executor: SlotExecutor,
    artifact_writer: Callable[[Path, dict], dict[str, str]] = write_replay_artifacts,
) -> dict:
    """Resume the fixed schedule; never creates a paid identity or cost row."""

    store = RehearsalStore(common_root, namespace)
    for existing in store.records():
        if (
            existing["lock_id"] != contract.lock_id
            or existing["lock_sha256"] != contract.lock_sha256
            or existing["policy_sha256"] != contract.policy_sha256
            or existing["taskset_sha256"] != contract.taskset_sha256
        ):
            raise ValueError("Plan 049 rehearsal contract drifted on resume")
    schedule = slots(contract)
    for slot in schedule:
        claim = store.claim(slot.slot_id, slot.run_id)
        if claim is None:
            continue
        attempt, run_id, claim_status = claim
        run_root = store.runs_root / run_id
        checkpoint_path = run_root / "execution.json"
        if claim_status == "executing":
            result = _read_execution_checkpoint(
                checkpoint_path,
                contract=contract,
                slot=slot,
                attempt=attempt,
                run_id=run_id,
            )
        else:
            store.mark_execution_started(slot.slot_id)
            try:
                result = executor(slot, attempt)
            except Exception:
                _persist_infra(
                    store,
                    contract,
                    slot,
                    attempt,
                    run_id,
                    reason_code="simulated_runner_failure",
                    trace_status="missing",
                )
                continue
            _write_execution_checkpoint(
                checkpoint_path,
                result,
                contract=contract,
                slot=slot,
                attempt=attempt,
                run_id=run_id,
            )
        if result.outcome not in VALID_OUTCOMES:
            _persist_infra(
                store,
                contract,
                slot,
                attempt,
                run_id,
                reason_code=result.reason_code or "simulated_provider_failure",
                trace_status=(
                    result.trace_status
                    if result.trace_status in {"missing", "partial"}
                    else "partial"
                ),
            )
            continue
        view = synthetic_team_view(side=slot.side, run_id=run_id, ordinal=slot.ordinal)
        try:
            digests = artifact_writer(run_root, view)
        except Exception:
            # The executor result is durable. Resume repairs only this exact
            # attempt's body-free artifacts and never invokes it a second time.
            continue
        record = _record(
            contract,
            slot,
            attempt,
            run_id,
            outcome=result.outcome,
            trace_status=result.trace_status,
            team_view_sha256=digests["team_view_sha256"],
            team_report_sha256=digests["team_report_sha256"],
            reason_code=result.reason_code,
        )
        _write_run_record(store.runs_root / run_id / "run.json", record)
        store.append(record)
        store.settle(slot.slot_id, outcome=result.outcome)
    records = store.records()
    views = {}
    for record in records:
        if record["terminal"] is not True:
            continue
        path = store.runs_root / record["run_id"] / "team_view.json"
        try:
            value = json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("trusted Plan 049 Team View is unavailable") from exc
        views[record["run_id"]] = value
    result = aggregate(
        records,
        views,
        lock_id=contract.lock_id,
        lock_sha256=contract.lock_sha256,
        policy_sha256=contract.policy_sha256,
        expected_slots={slot.slot_id: slot.pair_id for slot in schedule},
    )
    store.write_aggregate(result)
    return result


def default_fake_executor(slot: Slot, attempt: int) -> ExecutionResult:
    del attempt
    # Deterministic valid task failures exercise their terminal semantics while
    # keeping both sides present and the rest of the fixed schedule green.
    if slot.pair_id in {"P02", "F08"} and slot.side == "codex":
        return ExecutionResult("task_failed", reason_code="task_native_verifier_failed")
    return ExecutionResult("completed")


def _persist_infra(
    store: RehearsalStore,
    contract: CampaignContract,
    slot: Slot,
    attempt: int,
    run_id: str,
    *,
    reason_code: str,
    trace_status: str,
) -> None:
    record = _record(
        contract,
        slot,
        attempt,
        run_id,
        outcome="infra_failed",
        trace_status=trace_status,
        team_view_sha256=None,
        team_report_sha256=None,
        reason_code=reason_code,
    )
    store.append(record)
    store.settle(slot.slot_id, outcome="infra_failed")


def _record(
    contract: CampaignContract,
    slot: Slot,
    attempt: int,
    run_id: str,
    *,
    outcome: str,
    trace_status: str,
    team_view_sha256: str | None,
    team_report_sha256: str | None,
    reason_code: str | None,
) -> dict:
    terminal = outcome in VALID_OUTCOMES
    return {
        "schema_version": 1,
        "evidence_kind": "rehearsal",
        "identity_class": "rehearsal",
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "policy_sha256": contract.policy_sha256,
        "taskset_sha256": contract.taskset_sha256,
        "phase": slot.phase,
        "pair_id": slot.pair_id,
        "slot_id": slot.slot_id,
        "run_id": run_id,
        "attempt": attempt,
        "task_id": slot.task_id,
        "side": slot.side,
        "product": None if slot.side == "codex" else "rondo-multi",
        "outcome": outcome,
        "terminal": terminal,
        "counts_as_effective": terminal,
        "cost_usd": "0.00",
        "trace_status": trace_status,
        "team_view_sha256": team_view_sha256,
        "team_report_sha256": team_report_sha256,
        "reason_code": reason_code,
    }


def _write_run_record(path: Path, record: dict) -> None:
    payload = (
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValueError("Plan 049 run record drifted on resume")
        return
    path.write_bytes(payload)


def _write_execution_checkpoint(
    path: Path,
    result: ExecutionResult,
    *,
    contract: CampaignContract,
    slot: Slot,
    attempt: int,
    run_id: str,
) -> None:
    value = {
        "schema_version": 1,
        "evidence_kind": "rehearsal",
        "identity_class": "rehearsal",
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "taskset_sha256": contract.taskset_sha256,
        "policy_sha256": contract.policy_sha256,
        "slot_id": slot.slot_id,
        "run_id": run_id,
        "attempt": attempt,
        "outcome": result.outcome,
        "trace_status": result.trace_status,
        "reason_code": result.reason_code,
    }
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValueError("Plan 049 execution checkpoint drifted on resume")
        return
    path.write_bytes(payload)


def _read_execution_checkpoint(
    path: Path,
    *,
    contract: CampaignContract,
    slot: Slot,
    attempt: int,
    run_id: str,
) -> ExecutionResult:
    if path.is_symlink() or not path.is_file():
        raise ValueError(
            "Plan 049 execution state is uncertain; refusing to repeat the executor"
        )
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Plan 049 execution checkpoint is unreadable") from exc
    expected = {
        "schema_version": 1,
        "evidence_kind": "rehearsal",
        "identity_class": "rehearsal",
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "taskset_sha256": contract.taskset_sha256,
        "policy_sha256": contract.policy_sha256,
        "slot_id": slot.slot_id,
        "run_id": run_id,
        "attempt": attempt,
    }
    if not isinstance(value, dict) or any(
        value.get(key) != item for key, item in expected.items()
    ):
        raise ValueError("Plan 049 execution checkpoint identity differs")
    if set(value) != {*expected, "outcome", "trace_status", "reason_code"}:
        raise ValueError("Plan 049 execution checkpoint shape differs")
    outcome = value.get("outcome")
    trace_status = value.get("trace_status")
    reason_code = value.get("reason_code")
    if (
        not isinstance(outcome, str)
        or not isinstance(trace_status, str)
        or (reason_code is not None and not isinstance(reason_code, str))
    ):
        raise ValueError("Plan 049 execution checkpoint result is invalid")
    return ExecutionResult(outcome, trace_status=trace_status, reason_code=reason_code)
