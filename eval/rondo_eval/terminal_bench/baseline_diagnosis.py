"""Resolve or retire one Plan 051 diagnosis without Docker or API work."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from ..api_budget_proxy import (
    ApiBudgetProxyError,
    completed_run_accounting,
    load_validated_budget_ledger_state,
)
from ..config import RepoPaths
from .baseline import (
    RUN_CAP_USD,
    BaselineError,
    CampaignStateLedger,
    DiagnosisDisposition,
    DiagnosisEvidenceCode,
    MechanicalFailureCategory,
    load_campaign_identity,
)
from .baseline_cli import CampaignExecutionLease


_PLAN051_UNPRICED_FALLBACK_USD = "1.000000"


def _running_local_defect_settlement(
    identity: object,
    state: dict[str, object],
    budget: dict[str, object],
) -> tuple[str, str]:
    slots = state.get("slots")
    if not isinstance(slots, list):
        raise SystemExit("campaign state slots are invalid")
    running = [row for row in slots if row.get("status") == "running"]
    if len(running) != 1 or running[0].get("slot_id") == "wire-canary":
        raise SystemExit("local-defect retirement has no unique paid running slot")
    slot_id = str(running[0].get("slot_id"))
    try:
        slot = identity.slot(slot_id)
        accounting = completed_run_accounting(budget, slot.run_id)
    except (ApiBudgetProxyError, AttributeError, BaselineError, ValueError) as exc:
        raise SystemExit("running paid slot has no complete usage settlement") from exc
    return slot_id, str(accounting["spent_usd"])


def _load_local_defect_budget(
    paths: RepoPaths,
    identity: object,
    state: dict[str, object],
) -> dict[str, object]:
    slots = state.get("slots")
    if not isinstance(slots, list):
        raise SystemExit("campaign state slots are invalid")
    wire_rows = [row for row in slots if row.get("slot_id") == "wire-canary"]
    if len(wire_rows) != 1 or wire_rows[0].get("status") != "completed":
        raise SystemExit("running paid slot has no completed wire canary")
    try:
        remaining = (
            Decimal(str(identity.budget["campaign_cap_usd"]))
            - Decimal(str(identity.budget["prior_estimated_usd"]))
            - Decimal(str(wire_rows[0]["estimated_usd"]))
        )
        return load_validated_budget_ledger_state(
            paths.common_root / "eval-data/budgets" / f"{identity.batch_id}.json",
            batch_id=identity.batch_id,
            total_cap_usd=remaining,
            max_runs=len(identity.slots) - 1,
            default_run_cap_usd=RUN_CAP_USD,
            unpriced_fallback_usd=_PLAN051_UNPRICED_FALLBACK_USD,
        )
    except (
        ApiBudgetProxyError,
        AttributeError,
        KeyError,
        ArithmeticError,
        ValueError,
    ) as exc:
        raise SystemExit("running paid slot budget cannot be validated") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.terminal_bench.baseline_diagnosis"
    )
    parser.add_argument("--chain-id")
    parser.add_argument(
        "--category", choices=[item.value for item in MechanicalFailureCategory]
    )
    parser.add_argument(
        "--disposition", choices=[item.value for item in DiagnosisDisposition]
    )
    parser.add_argument(
        "--evidence-code", choices=[item.value for item in DiagnosisEvidenceCode]
    )
    parser.add_argument("--retire-local-defect", action="store_true")
    args = parser.parse_args(argv)
    supplied = (args.chain_id, args.category, args.disposition, args.evidence_code)
    if args.retire_local_defect and any(item is not None for item in supplied):
        parser.error("campaign retirement cannot resolve a task diagnosis")
    if any(item is not None for item in supplied) and not all(
        item is not None for item in supplied
    ):
        parser.error("resolution requires chain, category, disposition, and evidence code")

    paths = RepoPaths.discover(Path.cwd())
    identity = load_campaign_identity(paths)
    state_path = (
        paths.common_root
        / "eval-data/campaigns"
        / identity.campaign_id
        / "state.json"
    )
    campaign_root = state_path.parent
    with CampaignExecutionLease(campaign_root / "executor.lock"):
        with CampaignStateLedger(
            state_path,
            identity=identity,
            allow_interrupted_recovery=args.retire_local_defect,
        ) as state:
            snapshot = state.snapshot()
            if snapshot["status"] != "running":
                raise SystemExit("campaign diagnosis can only update a running identity")
            if args.retire_local_defect:
                reason = (
                    "diagnosed_campaign_defect:"
                    "local_implementation_defect:harness_runtime"
                )
                if any(row["status"] == "running" for row in snapshot["slots"]):
                    budget = _load_local_defect_budget(paths, identity, snapshot)
                    _slot_id, spent = _running_local_defect_settlement(
                        identity, snapshot, budget
                    )
                    state.fail_interrupted(estimated_usd=spent, reason=reason)
                    snapshot = state.snapshot()
                if all(row["status"] == "planned" for row in snapshot["slots"]):
                    state.retire_preflight_blocked(
                        reason=(
                            "diagnosed_campaign_defect:"
                            "local_implementation_defect:preflight_projection"
                        )
                    )
                else:
                    state.retire_blocked(reason=reason)
            elif all(item is not None for item in supplied):
                state.resolve_diagnosis(
                    chain_id=args.chain_id,
                    category=MechanicalFailureCategory(args.category),
                    disposition=DiagnosisDisposition(args.disposition),
                    evidence_code=DiagnosisEvidenceCode(args.evidence_code),
                )
            snapshot = state.snapshot()
            print(
                json.dumps(
                    {
                        "campaign_id": identity.campaign_id,
                        "status": snapshot["status"],
                        "diagnoses": snapshot.get("diagnoses", []),
                    },
                    sort_keys=True,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
