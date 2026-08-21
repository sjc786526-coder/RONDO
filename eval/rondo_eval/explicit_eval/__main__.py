"""Offline-first CLI for Plan 050 Phase A and its locked Phase-B entry."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

from ..config import RepoPaths
from ..proactive_eval.loopback import run_common_v2_loopback
from ..proactive_eval.readiness import secret_readiness
from ..proactive_eval.store import assert_body_free
from .contract import REPO_ROOT, load_contract
from .paid import PaidGuardError, run_authorized_paid_phase
from .readiness import ReadinessError, require_phase_a_evidence
from .rehearsal import run_fake
from .report import ReportError, finalize_paid_case_outputs
from .schedule import dry_run_projection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rondo-eval-plan050")
    parser.add_argument(
        "command",
        choices=(
            "dry-run",
            "fake",
            "loopback",
            "replay",
            "ready",
            "finalize-cases",
            "phase-b-paid",
        ),
    )
    parser.add_argument("--namespace", default="phase-a-final")
    parser.add_argument("--loopback-namespace", default=None)
    parser.add_argument("--authorize-phase-b", default=None)
    parser.add_argument("--phase-b-action", default=None)
    parser.add_argument("--actual-cap-usd", default=None)
    parser.add_argument("--confirmed-balance-usd", default=None)
    parser.add_argument("--confirm-local-conditions", default=None)
    parser.add_argument("--independent-review-commit", default=None)
    parser.add_argument("--impact-assessments-json", default=None)
    args = parser.parse_args(argv)

    paths = RepoPaths.discover(REPO_ROOT)
    contract = load_contract(paths.worktree_root)
    loopback_namespace = args.loopback_namespace or args.namespace
    if args.command == "dry-run":
        _print(
            dry_run_projection(
                contract, common_root=paths.common_root, namespace=args.namespace
            )
        )
        return 0
    if args.command == "fake":
        _print(
            run_fake(
                contract, common_root=paths.common_root, namespace=args.namespace
            )
        )
        return 0
    if args.command == "loopback":
        _print(
            run_common_v2_loopback(
                contract, common_root=paths.common_root, namespace=args.namespace
            )
        )
        return 0
    if args.command == "replay":
        fixture = paths.worktree_root / contract.lock["artifacts"]["replay_fixture"]
        raw = fixture.read_bytes()
        value = json.loads(raw)
        assert_body_free(value)
        _print(
            {
                "schema_version": 1,
                "evidence_kind": "replay",
                "identity_class": "rehearsal",
                "lock_id": contract.lock_id,
                "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                "record_count": len(value["records"]),
                "deterministic": json.dumps(
                    value, sort_keys=True, separators=(",", ":")
                )
                == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")),
            }
        )
        return 0
    if args.command == "ready":
        projection = dry_run_projection(
            contract, common_root=paths.common_root, namespace=args.namespace
        )
        try:
            evidence = require_phase_a_evidence(
                contract,
                common_root=paths.common_root,
                rehearsal_namespace=args.namespace,
                loopback_namespace=loopback_namespace,
            )
        except ReadinessError as exc:
            print(str(exc), file=sys.stderr)
            return 77
        _print(
            {
                "schema_version": 1,
                "phase_a_status": "offline-evidence-ready",
                "paid_ready_candidate": True,
                "lock_id": contract.lock_id,
                "slot_count": len(projection["slots"]),
                "evidence": evidence,
                "secret_readiness": secret_readiness(
                    paths, provider_name=str(contract.lock["provider"]["name"])
                ),
                "request_observation": {
                    "root": "observed_in_zero_api_loopback",
                    "member": "config_projection_only",
                    "guardian": "config_projection_only",
                },
                "phase_b_requires": [
                    "separate_explicit_phase_b_authorization",
                    "exact_actual_cap_not_above_usd_100",
                    "confirmed_balance_at_least_actual_cap",
                    "clean_reviewed_harness_commit",
                    "safe_resume_prefix",
                    "local_paid_conditions",
                    "shared_docker_and_build_lock_resource_gate",
                ],
                "phase_b_not_authorized": True,
            }
        )
        return 0
    if args.command == "finalize-cases":
        try:
            assessments = json.loads(args.impact_assessments_json or "null")
            if not isinstance(assessments, dict):
                raise ReportError("impact assessments must be a JSON object")
            result = finalize_paid_case_outputs(
                contract,
                common_root=paths.common_root,
                impact_assessments=assessments,
            )
        except (json.JSONDecodeError, ReportError) as exc:
            print(str(exc), file=sys.stderr)
            return 77
        _print(result)
        return 0

    try:
        result = run_authorized_paid_phase(
            repo_root=paths.worktree_root,
            authorization=args.authorize_phase_b,
            phase_b_action=args.phase_b_action,
            actual_cap_usd=args.actual_cap_usd,
            confirmed_balance_usd=args.confirmed_balance_usd,
            local_confirmation=args.confirm_local_conditions,
            independent_review_commit=args.independent_review_commit,
            rehearsal_namespace=args.namespace,
            loopback_namespace=loopback_namespace,
        )
    except Exception as exc:
        if not isinstance(exc, PaidGuardError):
            print("Plan 050 paid entry failed closed", file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 78
    _print(result)
    if result.get("missing_slot_ids"):
        return 1
    if result.get("case_outputs", {}).get("status") == "awaiting_impact_assessment":
        return 3
    return 0


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
