"""Resolve one durable Plan 020 task-local diagnosis hold without running work."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config import RepoPaths
from .baseline import (
    CampaignStateLedger,
    DiagnosisDisposition,
    DiagnosisEvidenceCode,
    MechanicalFailureCategory,
    load_campaign_identity,
)
from .baseline_cli import CampaignExecutionLease


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
        with CampaignStateLedger(state_path, identity=identity) as state:
            snapshot = state.snapshot()
            if snapshot["status"] != "running":
                raise SystemExit("campaign diagnosis can only update a running identity")
            if args.retire_local_defect:
                state.retire_blocked(
                    reason=(
                        "diagnosed_campaign_defect:"
                        "local_implementation_defect:harness_runtime"
                    )
                )
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
