"""Light interleaved gate 2 orchestrator.

Fake this round. After Docker is authorized, slot execution must go through
``rondo_eval.terminal_bench`` adapters, runner, and results — not a v7
campaign or preflight receipt. This module only walks the frozen slots,
enforces the attempt/budget caps, and archives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Protocol

from ..api_budget_proxy import (
    BudgetStopped,
    PersistentBudgetLedger,
    Usage,
    price_usage,
)
from ..contracts import Product, RunOutcome, Side
from .archive import archive_record
from .budget import phase_b_pricing
from .load import load_nondegradation_contract, load_runtime_identity
from .schedule import Slot, base_slots, conditional_slots, degradation_on_task, outcomes_by_task
from .store import persist_archive_record

_FAKE_USAGE = Usage(1_000, 0, 0, 0)


class Gate2Error(RuntimeError):
    """Gate 2 orchestrator failed closed."""


@dataclass
class SlotResult:
    outcome: str
    request_count: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


class SlotExecutor(Protocol):
    def execute(self, slot: Slot, *, attempt: int, run_id: str) -> SlotResult:
        ...


class ScriptedSlotExecutor:
    """Deterministic fake host execution. No Docker, no API."""

    def __init__(
        self,
        script: Mapping[tuple[str, str, int], tuple[str, ...]] | None = None,
    ) -> None:
        self.script = dict(script or {})

    def execute(self, slot: Slot, *, attempt: int, run_id: str) -> SlotResult:
        del run_id
        key = (slot.task_id, slot.side.value, slot.round_index)
        outcomes = self.script.get(key, (RunOutcome.COMPLETED.value,))
        index = min(max(attempt, 1) - 1, len(outcomes) - 1)
        return SlotResult(outcome=outcomes[index], extra={"executor": "scripted"})


class DockerNotAuthorizedExecutor:
    def execute(self, slot: Slot, *, attempt: int, run_id: str) -> SlotResult:
        del slot, attempt, run_id
        raise Gate2Error("Docker execution is not authorized")


def run_light_interleaved(
    *,
    executor: SlotExecutor,
    common_root,
    ledger: PersistentBudgetLedger | None = None,
    persist: bool = True,
    archive_file=None,
    charge_fake_usage: bool = False,
    identity=None,
    contract=None,
    evidence_kind: str = "fake",
) -> dict[str, Any]:
    """Walk frozen base slots, then conditional extras. Infra is not effective."""

    if evidence_kind not in {"fake", "loopback", "real_api"}:
        raise Gate2Error("gate 2 evidence kind is not an M-5 partition")
    if evidence_kind == "real_api" and isinstance(
        executor, (ScriptedSlotExecutor, DockerNotAuthorizedExecutor)
    ):
        # A scripted or refusing executor never touched a provider. Labelling its
        # rows real_api would put fake results in the paid partition.
        raise Gate2Error("a scripted executor cannot produce real_api evidence")
    loaded = contract or load_nondegradation_contract()
    runtime = identity or load_runtime_identity(require_frozen=False)
    pricing = phase_b_pricing(loaded) if charge_fake_usage else None
    records: list[dict[str, Any]] = []
    infra_used = 0
    effective = 0
    stopped = False
    stop_reason: str | None = None

    def run_slot(slot: Slot) -> list[dict[str, Any]]:
        """Every attempt on this slot, in order. A retried infra failure stays
        on the record: it must be auditable that the slot was re-run, and the
        infra rows are exactly what proves they were not counted as effective."""

        nonlocal infra_used, effective, stopped, stop_reason
        produced: list[dict[str, Any]] = []

        def emit(**kwargs: Any) -> list[dict[str, Any]]:
            produced.append(
                _record_for(slot, runtime, evidence_kind=evidence_kind, **kwargs)
            )
            return produced

        for attempt in range(1, loaded.max_slot_attempts + 1):
            if stopped:
                return emit(
                    outcome=RunOutcome.BUDGET_STOPPED.value,
                    counts_as_effective=False,
                    extra={"stop_reason": stop_reason, "attempt": attempt},
                )
            if effective >= loaded.max_effective_runs:
                return emit(
                    outcome="uncertain",
                    counts_as_effective=False,
                    extra={"reason": "max_effective_runs", "attempt": attempt},
                )
            run_id = _run_id(slot, attempt)
            if ledger is not None:
                try:
                    ledger.ensure_run(run_id)
                except BudgetStopped as exc:
                    stopped = True
                    stop_reason = str(exc)
                    return emit(
                        outcome=RunOutcome.BUDGET_STOPPED.value,
                        counts_as_effective=False,
                        extra={"stop_reason": stop_reason, "attempt": attempt},
                    )
            try:
                result = executor.execute(slot, attempt=attempt, run_id=run_id)
            except BudgetStopped as exc:
                stopped = True
                stop_reason = str(exc)
                return emit(
                    outcome=RunOutcome.BUDGET_STOPPED.value,
                    counts_as_effective=False,
                    extra={"stop_reason": stop_reason, "attempt": attempt},
                )
            except Gate2Error as exc:
                infra_used += 1
                emit(
                    outcome=RunOutcome.INFRA_FAILED.value,
                    counts_as_effective=False,
                    extra={"error": str(exc), "attempt": attempt, "infra_used": infra_used},
                )
                if infra_used >= loaded.max_infra_attempts_total:
                    stopped = True
                    stop_reason = "max_infra_attempts_total"
                    return produced
                if attempt == loaded.max_slot_attempts:
                    return produced
                continue
            if result.request_count > loaded.max_requests_per_run:
                result = SlotResult(
                    outcome=RunOutcome.INFRA_FAILED.value,
                    request_count=result.request_count,
                    extra={**result.extra, "reason": "max_requests_per_run"},
                )
            if result.outcome == RunOutcome.INFRA_FAILED.value:
                infra_used += 1
                emit(
                    outcome=result.outcome,
                    counts_as_effective=False,
                    extra={**result.extra, "attempt": attempt, "infra_used": infra_used},
                )
                if infra_used >= loaded.max_infra_attempts_total:
                    stopped = True
                    stop_reason = "max_infra_attempts_total"
                    return produced
                if attempt == loaded.max_slot_attempts:
                    return produced
                continue
            counts = result.outcome != RunOutcome.BUDGET_STOPPED.value
            if counts and ledger is not None and charge_fake_usage and pricing is not None:
                try:
                    _charge(ledger, run_id, attempt, pricing)
                except BudgetStopped as exc:
                    stopped = True
                    stop_reason = str(exc)
                    return emit(
                        outcome=RunOutcome.BUDGET_STOPPED.value,
                        counts_as_effective=False,
                        extra={"stop_reason": stop_reason, "attempt": attempt},
                    )
            if counts:
                effective += 1
            return emit(
                outcome=result.outcome,
                counts_as_effective=counts,
                extra={**result.extra, "attempt": attempt, "request_count": result.request_count},
            )
        return produced

    for slot in base_slots(loaded):
        for record in run_slot(slot):
            records.append(record)
            if persist:
                persist_archive_record(record, common_root=common_root, path=archive_file)
        if stopped:
            break

    first_round: dict[str, dict[str, str]] = {}
    for record in records:
        if record.get("counts_as_effective") is not True:
            continue
        task_id = str(record["task_id"])
        key = (
            Product.RONDO_MULTI.value
            if record.get("product") == Product.RONDO_MULTI.value
            else Side.CODEX.value
        )
        if record.get("round_index") != 1:
            continue
        first_round.setdefault(task_id, {})[key] = str(record["outcome"])

    extras: tuple[Slot, ...] = ()
    if not stopped:
        extras = conditional_slots(loaded, first_round)
        for slot in extras:
            for record in run_slot(slot):
                records.append(record)
                if persist:
                    persist_archive_record(record, common_root=common_root, path=archive_file)
            if stopped:
                break

    grouped = outcomes_by_task(records)
    verdicts = {
        task_id: degradation_on_task(observations)
        for task_id, observations in grouped.items()
    }
    return {
        "records": records,
        "verdicts": verdicts,
        "effective_runs": effective,
        "infra_used": infra_used,
        "conditional_slots": len(extras),
        "stopped": stopped,
        "stop_reason": stop_reason,
        "ledger_snapshot": None if ledger is None else ledger.snapshot(),
    }


def _charge(
    ledger: PersistentBudgetLedger,
    run_id: str,
    attempt: int,
    pricing,
) -> None:
    request_id = f"{run_id}-req-{attempt}"
    amount = price_usage(_FAKE_USAGE, pricing=pricing)
    ledger.reserve(run_id, request_id, amount)
    ledger.begin_attempt(run_id, request_id, max_attempts=5)
    ledger.settle(run_id, request_id, _FAKE_USAGE, pricing=pricing)


def _record_for(
    slot: Slot,
    runtime,
    *,
    outcome: str,
    counts_as_effective: bool,
    extra: Mapping[str, Any],
    evidence_kind: str = "fake",
) -> dict[str, Any]:
    kind = evidence_kind
    if slot.side is Side.RONDO:
        source_commit = runtime.source_commit
        binary_sha256 = runtime.codex_sha256
    else:
        source_commit = str(runtime.baseline["source_commit"])
        binary_sha256 = str(runtime.baseline["codex_sha256"])
    # The fairness contract requires both sides' binary identity on every row.
    # A placeholder digest would make an unfrozen bundle look comparable.
    if not binary_sha256:
        raise Gate2Error("gate 2 needs a frozen binary digest for both sides")
    return archive_record(
        evidence_kind=kind,
        gate=2,
        lock_id="multi-m5-nondegradation-v1",
        side=slot.side,
        product=slot.product,
        source_commit=source_commit,
        binary_sha256=binary_sha256,
        outcome=outcome,
        counts_as_effective=counts_as_effective,
        extra={
            "task_id": slot.task_id,
            "round_index": slot.round_index,
            "slot_kind": slot.kind,
            **dict(extra),
        },
    )


def _run_id(slot: Slot, attempt: int) -> str:
    task = slot.task_id.rsplit("/", 1)[-1]
    side = slot.side.value
    return f"m5-g2-{task}-{side}-r{slot.round_index}-a{attempt}"
