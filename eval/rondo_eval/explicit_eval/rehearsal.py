"""Plan 050 zero-cost rehearsal built on the shared Plan 049 thin layer."""

from __future__ import annotations

from pathlib import Path

from ..proactive_eval.campaign import ExecutionResult, run_rehearsal
from ..proactive_eval.store import RehearsalStore
from .contract import CampaignContract
from .report import build_case_outputs, write_case_outputs


def run_fake(
    contract: CampaignContract,
    *,
    common_root: Path,
    namespace: str,
) -> dict:
    aggregate = run_rehearsal(
        contract,
        common_root=common_root,
        namespace=namespace,
        executor=_fake_executor,
    )
    store = plan050_store(contract, common_root=common_root, namespace=namespace)
    cases, overview = build_case_outputs(aggregate)
    report = write_case_outputs(store.root, cases, overview)
    return {**aggregate, "case_outputs": report}


def plan050_store(
    contract: CampaignContract,
    *,
    common_root: Path,
    namespace: str,
) -> RehearsalStore:
    return RehearsalStore(
        common_root,
        namespace,
        ignored_root=str(contract.lock["artifacts"]["ignored_root"]),
        max_infra_attempts_per_slot=None,
        max_infra_attempts_total=None,
    )


def _fake_executor(slot, attempt: int) -> ExecutionResult:
    del attempt
    if slot.pair_id == "C02" and slot.side == "rondo":
        return ExecutionResult(
            "task_failed", reason_code="task_native_verifier_failed"
        )
    if slot.pair_id == "C03" and slot.side == "codex":
        return ExecutionResult(
            "product_failed", reason_code="synthetic_product_terminal"
        )
    return ExecutionResult("completed")
