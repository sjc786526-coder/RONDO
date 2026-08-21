"""Safe operator entry for the Plan 051 schema-v7 formal canary.

The default/status path is deliberately read-only and never loads a provider
secret.  ``prepare`` freezes or verifies the small cross-identity budget
envelope and validates all local campaign inputs, but also sends no request.
Only an explicit paid acknowledgement may delegate to the campaign runner.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from ..config import RepoPaths, load_runtime_config
from .baseline import BaselineStatus, load_campaign_identity
from .baseline_cli import (
    _load_and_validate_manifests,
    _require_all_preflight_receipts,
    main as baseline_main,
)
from .baseline_identity import required_successor_prior, retire_active_campaign_pointer
from .task_budget import (
    TaskBudgetIdentity,
    close_task_budget,
    load_task_budget,
    roll_forward_task_budget,
    start_task_budget,
    task_budget_path,
    task_budget_status,
    verify_active_identity,
)


PAID_ACTION = "plan-051-authorized-paid-run"


class FormalCanaryError(RuntimeError):
    """The stable entry cannot advance without changing the frozen contract."""


def _identity_budget(identity: object) -> tuple[TaskBudgetIdentity, Decimal]:
    try:
        if not identity.enforces_fair_comparison:
            raise FormalCanaryError("active campaign is not schema v7")
        budget_identity = TaskBudgetIdentity(identity.campaign_id, identity.batch_id)
        prior = Decimal(str(identity.budget["task_budget_prior_estimated_usd"]))
    except (AttributeError, KeyError, ArithmeticError) as exc:
        raise FormalCanaryError("active campaign task budget is invalid") from exc
    return budget_identity, prior


def prepare(paths: RepoPaths) -> dict[str, object]:
    """Validate the active identity and initialize its zero-cost envelope."""

    identity = load_campaign_identity(paths)
    active, prior = _identity_budget(identity)
    provider = identity.provider_projection(load_runtime_config(paths))
    manifests = _load_and_validate_manifests(paths, identity)
    envelope_path = task_budget_path(paths.common_root)
    if envelope_path.exists() or envelope_path.is_symlink():
        envelope = load_task_budget(envelope_path)
        stored = envelope.get("active_identity")
        if isinstance(stored, dict) and (
            stored.get("campaign_id"), stored.get("batch_id")
        ) != (active.campaign_id, active.batch_id):
            try:
                version = int(identity.campaign_id.rsplit("v", 1)[1])
            except (AttributeError, IndexError, ValueError) as exc:
                raise FormalCanaryError("successor campaign version is invalid") from exc
            expected_prior = required_successor_prior(paths, version=version - 1)
            if expected_prior != prior:
                raise FormalCanaryError(
                    "successor task prior differs from predecessor settlement"
                )
            predecessor = TaskBudgetIdentity(
                str(stored.get("campaign_id")), str(stored.get("batch_id"))
            )
            predecessor_state_path = (
                paths.common_root
                / "eval-data/campaigns"
                / predecessor.campaign_id
                / "state.json"
            )
            try:
                predecessor_state = json.loads(
                    predecessor_state_path.read_text(encoding="utf-8")
                )
                predecessor_status = str(predecessor_state["status"])
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as exc:
                raise FormalCanaryError(
                    "predecessor terminal state is unavailable"
                ) from exc
            roll_forward_task_budget(
                envelope_path,
                predecessor=predecessor,
                predecessor_terminal_status=predecessor_status,
                cumulative_settled_usd=prior,
                successor=active,
            )
        budget = verify_active_identity(
            envelope_path,
            active=active,
            prior_settled_usd=prior,
        )
    else:
        if prior != Decimal("0.000000"):
            raise FormalCanaryError("nonzero-prior identity has no task budget envelope")
        budget = task_budget_status(start_task_budget(envelope_path, active=active))
    receipts_ready = True
    receipt_error = None
    try:
        _require_all_preflight_receipts(paths, identity)
    except Exception as exc:
        receipts_ready = False
        receipt_error = str(exc)
    return {
        "status": "prepared" if receipts_ready else "preflight_receipts_required",
        "campaign_id": identity.campaign_id,
        "batch_id": identity.batch_id,
        "provider_profile_sha256": provider.profile_sha256,
        "main_model": provider.main_model,
        "guardian_model": provider.guardian_model,
        "main_effort": provider.main_effort,
        "guardian_effort": provider.guardian_effort,
        "bundle_source_commits": {
            side.value: manifest.source_commit for side, manifest in manifests.items()
        },
        "task_budget": budget,
        "preflight_receipts_ready": receipts_ready,
        "preflight_receipt_error": receipt_error,
        "paid_requests_sent": 0,
    }


def status(paths: RepoPaths) -> dict[str, object]:
    """Return non-secret state without loading config, credentials, Docker or API."""

    pointer = paths.worktree_root / "eval/locks/p2-b7-active.json"
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FormalCanaryError("active campaign pointer is unavailable") from exc
    if value.get("active_lock") is None:
        return {"status": "idle", "active_lock": None, "paid_requests_sent": 0}
    identity = load_campaign_identity(paths)
    active, prior = _identity_budget(identity)
    envelope_path = task_budget_path(paths.common_root)
    budget = (
        task_budget_status(load_task_budget(envelope_path))
        if envelope_path.exists() and not envelope_path.is_symlink()
        else {"status": "missing"}
    )
    campaign_state_path = (
        paths.common_root / "eval-data/campaigns" / identity.campaign_id / "state.json"
    )
    campaign_status = "not_started"
    if campaign_state_path.is_file() and not campaign_state_path.is_symlink():
        try:
            campaign_state = json.loads(campaign_state_path.read_text(encoding="utf-8"))
            campaign_status = str(campaign_state.get("status", "invalid"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            campaign_status = "invalid"
    return {
        "status": "active",
        "campaign_id": active.campaign_id,
        "batch_id": active.batch_id,
        "identity_prior_usd": f"{prior:.6f}",
        "campaign_status": campaign_status,
        "task_budget": budget,
        "paid_requests_sent": 0,
    }


def _runner_argv(args: argparse.Namespace) -> list[str]:
    required = {
        "docker_host_volume": args.docker_host_volume,
        "results_worktree_root": args.results_worktree_root,
        "rondo_measurement_worktree_root": args.rondo_measurement_worktree_root,
        "codex_measurement_worktree_root": args.codex_measurement_worktree_root,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise FormalCanaryError("runner arguments are missing: " + ",".join(missing))
    return [
        "--docker-host-volume",
        str(args.docker_host_volume),
        "--results-worktree-root",
        str(args.results_worktree_root),
        "--rondo-measurement-worktree-root",
        str(args.rondo_measurement_worktree_root),
        "--codex-measurement-worktree-root",
        str(args.codex_measurement_worktree_root),
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rondo-plan051-canary")
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=("status", "prepare", "run", "resume", "finalize"),
    )
    parser.add_argument("--paid-action")
    parser.add_argument("--docker-host-volume", type=Path)
    parser.add_argument("--results-worktree-root", type=Path)
    parser.add_argument("--rondo-measurement-worktree-root", type=Path)
    parser.add_argument("--codex-measurement-worktree-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = RepoPaths.discover(Path.cwd())
    if args.action == "status":
        print(json.dumps(status(paths), sort_keys=True))
        return 0
    if args.action == "prepare":
        print(json.dumps(prepare(paths), sort_keys=True))
        return 0
    if args.action in {"run", "resume"}:
        if args.paid_action != PAID_ACTION:
            raise FormalCanaryError("explicit Plan 051 paid action is required")
        prepared = prepare(paths)
        if not prepared["preflight_receipts_ready"]:
            raise FormalCanaryError("all stub preflight receipts are required")
        return baseline_main(_runner_argv(args))
    identity = load_campaign_identity(paths)
    state_path = (
        paths.common_root / "eval-data/campaigns" / identity.campaign_id / "state.json"
    )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        terminal = BaselineStatus(str(state["status"]))
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise FormalCanaryError("campaign is not in a terminal state") from exc
    exit_code = baseline_main(_runner_argv(args))
    if exit_code != 0:
        return exit_code
    if terminal in {BaselineStatus.PASSED, BaselineStatus.FAILED}:
        active, _prior = _identity_budget(identity)
        envelope_path = task_budget_path(paths.common_root)
        envelope = load_task_budget(envelope_path)
        if envelope.get("active_identity") is not None:
            cumulative = required_successor_prior(
                paths,
                version=int(identity.campaign_id.rsplit("v", 1)[1]),
            )
            envelope = close_task_budget(
                envelope_path,
                active=active,
                terminal_status=terminal.value,
                cumulative_settled_usd=cumulative,
            )
        closed = envelope.get("closed_identities")
        if not isinstance(closed, list) or not any(
            isinstance(row, dict)
            and row.get("campaign_id") == active.campaign_id
            and row.get("batch_id") == active.batch_id
            and row.get("terminal_status") == terminal.value
            for row in closed
        ):
            raise FormalCanaryError(
                "terminal identity is not closed in the task budget"
            )
        retire_active_campaign_pointer(paths, identity=identity)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
