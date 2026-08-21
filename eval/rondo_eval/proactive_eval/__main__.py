"""Offline-first CLI for Plan 049 Phase A."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys

from ..config import RepoPaths, load_runtime_config
from ..multi_m5.archive import harness_identity
from .campaign import default_fake_executor, run_rehearsal
from .contract import REPO_ROOT, load_contract
from .loopback import run_common_v2_loopback
from .formal import FormalError, plan049_provider_projection
from .paid import (
    PaidGuardError,
    run_authorized_paid_phase,
)
from .schedule import dry_run_projection
from .recovery import (
    RECOVERY_ID,
    RecoveryError,
    prepare_recovery_prefix,
)
from .readiness import ReadinessError, require_phase_a_evidence, secret_readiness
from .store import assert_body_free


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rondo-eval-plan049")
    parser.add_argument(
        "command",
        choices=(
            "dry-run",
            "fake",
            "loopback",
            "replay",
            "ready",
            "recover-paid",
            "phase-b-paid",
        ),
    )
    parser.add_argument("--namespace", default="phase-a-final")
    parser.add_argument("--loopback-namespace", default=None)
    parser.add_argument("--authorize-phase-b", default=None)
    parser.add_argument("--activation-action", default=None)
    parser.add_argument("--confirmed-balance-usd", default=None)
    parser.add_argument("--confirm-local-activation", default=None)
    parser.add_argument("--independent-review-commit", default=None)
    parser.add_argument("--recovery-action", default=None)
    parser.add_argument("--recovery-id", default=None)
    parser.add_argument("--phase", choices=("pilot", "formal"), default="pilot")
    args = parser.parse_args(argv)
    paths = RepoPaths.discover(REPO_ROOT)
    contract = load_contract(paths.worktree_root)
    if args.command == "dry-run":
        _print(dry_run_projection(contract, common_root=paths.common_root, namespace=args.namespace))
        return 0
    if args.command == "fake":
        result = run_rehearsal(
            contract,
            common_root=paths.common_root,
            namespace=args.namespace,
            executor=default_fake_executor,
        )
        _print(result)
        return 0
    if args.command == "loopback":
        _print(
            run_common_v2_loopback(
                contract,
                common_root=paths.common_root,
                namespace=args.namespace,
            )
        )
        return 0
    if args.command == "replay":
        fixture = paths.worktree_root / "eval/fixtures/multi-proactive-delegation-v1/body-free-replay-v1.json"
        raw = fixture.read_bytes()
        value = json.loads(raw)
        assert_body_free(value)
        _print(
            {
                "schema_version": 1,
                "evidence_kind": "replay",
                "fixture_sha256": hashlib.sha256(raw).hexdigest(),
                "record_count": len(value["records"]),
                "deterministic": json.dumps(value, sort_keys=True, separators=(",", ":"))
                == json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")),
            }
        )
        return 0
    if args.command == "ready":
        projection = dry_run_projection(contract, common_root=paths.common_root, namespace=args.namespace)
        try:
            evidence = require_phase_a_evidence(
                contract,
                common_root=paths.common_root,
                rehearsal_namespace=args.namespace,
                loopback_namespace=args.loopback_namespace or args.namespace,
            )
        except ReadinessError as exc:
            print(str(exc), file=sys.stderr)
            return 77
        _print(
            {
                "schema_version": 1,
                "phase_a_status": "offline-evidence-ready",
                "lock_id": contract.lock_id,
                "slot_count": len(projection["slots"]),
                "evidence": evidence,
                "secret_readiness": secret_readiness(
                    paths,
                    provider_name=contract.lock["provider"]["name"],
                ),
                "phase_b_requires": [
                    "explicit_phase_b_authorization",
                    "explicit_activation_action",
                    "usd_100_hard_cap_confirmation",
                    "available_balance_at_least_usd_100",
                    "clean_harness_commit",
                    "safe_resume_prefix",
                    "local_activation_conditions",
                    "docker_resource_gate",
                    "independent_review_pass",
                ],
                "pilot_pass_conditions": [
                    "six_valid_terminal_runs",
                    "six_policy_hash_matches",
                    "six_native_trace_team_lens_outputs",
                    "at_least_one_trace_backed_root_spawn_accept",
                ],
                "autonomously_recoverable": [
                    "configuration_or_fixture_error",
                    "scheduler_archive_resume_or_report_error",
                    "bounded_provider_or_network_infra_error",
                    "missing_side_without_trusted_terminal_record",
                ],
                "principled_stop_conditions": [
                    "usd_100_hard_cap_or_balance_exhaustion",
                    "usage_cannot_be_conservatively_settled",
                    "identity_or_fairness_contract_drift",
                    "body_or_secret_leak_risk",
                    "run_state_cannot_be_safely_determined",
                    "pilot_has_no_trace_backed_autonomous_spawn",
                ],
                "first_real_connection_only": [
                    "provider_connectivity",
                    "provider_model_identity",
                    "provider_usage_accounting",
                    "trace_backed_autonomous_spawn_activation",
                ],
            }
        )
        return 0
    if args.command == "recover-paid":
        actual_harness = harness_identity(paths.worktree_root)
        harness_commit = actual_harness.get("harness_commit")
        if (
            not isinstance(harness_commit, str)
            or actual_harness.get("harness_dirty") is not False
            or args.independent_review_commit != harness_commit
        ):
            print("Plan 049 recovery requires its clean reviewed commit", file=sys.stderr)
            return 78
        try:
            provider = plan049_provider_projection(
                load_runtime_config(paths), contract
            )
            result = prepare_recovery_prefix(
                contract,
                common_root=paths.common_root,
                provider=provider,
                recovery_harness_commit=harness_commit,
                recovery_action=args.recovery_action,
                recovery_id=args.recovery_id or RECOVERY_ID,
            )
        except (FormalError, RecoveryError) as exc:
            print(str(exc), file=sys.stderr)
            return 78
        except Exception:
            print("Plan 049 recovery source validation failed", file=sys.stderr)
            return 78
        _print(result)
        return 0
    try:
        result = run_authorized_paid_phase(
            repo_root=paths.worktree_root,
            authorization=args.authorize_phase_b,
            activation_action=args.activation_action,
            confirmed_balance_usd=args.confirmed_balance_usd,
            local_activation_confirmation=args.confirm_local_activation,
            independent_review_commit=args.independent_review_commit,
            rehearsal_namespace=args.namespace,
            loopback_namespace=args.loopback_namespace or args.namespace,
            phase=args.phase,
            recovery_id=args.recovery_id,
        )
    except (PaidGuardError, FormalError) as exc:
        print(str(exc), file=sys.stderr)
        return 78
    _print(result)
    if args.phase == "pilot":
        pilot_runs = [
            row
            for row in result.get("runs", [])
            if row.get("phase") == "pilot" and row.get("counts_as_effective") is True
        ]
        return 0 if len(pilot_runs) == 6 and result.get("activation_observed") is True else 1
    return 0 if not result.get("missing_slot_ids") else 1


def _print(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
