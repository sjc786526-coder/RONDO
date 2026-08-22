"""Safe operator entry for schema-v7 direction-0 formal canaries.

The default/status path is deliberately read-only and never loads a provider
secret.  ``prepare`` freezes or verifies the small cross-identity budget
envelope and validates all local campaign inputs, but also sends no request.
Only an explicit paid acknowledgement may delegate to the campaign runner.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..config import RepoPaths, load_runtime_config
from .baseline import (
    BaselineStatus,
    load_campaign_identity,
    load_historical_campaign_identity,
)
from .baseline_cli import (
    _load_and_validate_manifests,
    _require_all_preflight_receipts,
    main as baseline_main,
    publish_relative_baseline_comparison,
)
from .baseline_identity import (
    generate_successor_lock,
    required_successor_prior,
    retire_active_campaign_pointer,
)
from .task_budget import (
    TASK_BUDGET_ID,
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
_PAID_ACTION_PREFIX = "direction0-authorized-paid-run:"


class FormalCanaryError(RuntimeError):
    """The stable entry cannot advance without changing the frozen contract."""


def _required_paid_action(identity: object) -> str:
    try:
        task_budget_id = str(identity.budget["task_budget_id"])
    except (AttributeError, KeyError) as exc:
        raise FormalCanaryError("active campaign task budget is invalid") from exc
    return (
        PAID_ACTION
        if task_budget_id == TASK_BUDGET_ID
        else _PAID_ACTION_PREFIX + task_budget_id
    )


def _identity_budget(
    identity: object,
) -> tuple[TaskBudgetIdentity, Decimal, str, Decimal]:
    try:
        if not identity.enforces_fair_comparison:
            raise FormalCanaryError("active campaign is not schema v7")
        budget_identity = TaskBudgetIdentity(identity.campaign_id, identity.batch_id)
        prior = Decimal(str(identity.budget["task_budget_prior_estimated_usd"]))
        task_budget_id = str(identity.budget["task_budget_id"])
        task_budget_cap = Decimal(str(identity.budget["task_budget_cap_usd"]))
    except (AttributeError, KeyError, ArithmeticError) as exc:
        raise FormalCanaryError("active campaign task budget is invalid") from exc
    return budget_identity, prior, task_budget_id, task_budget_cap


def prepare(paths: RepoPaths) -> dict[str, object]:
    """Validate the active identity and initialize its zero-cost envelope."""

    identity = load_campaign_identity(paths)
    active, prior, task_budget_id, task_budget_cap = _identity_budget(identity)
    provider = identity.provider_projection(load_runtime_config(paths))
    manifests = _load_and_validate_manifests(paths, identity)
    envelope_path = task_budget_path(paths.common_root, task_budget_id)
    if envelope_path.exists() or envelope_path.is_symlink():
        envelope = load_task_budget(
            envelope_path,
            task_budget_id=task_budget_id,
            cap_usd=task_budget_cap,
        )
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
                task_budget_id=task_budget_id,
                cap_usd=task_budget_cap,
            )
        budget = verify_active_identity(
            envelope_path,
            active=active,
            prior_settled_usd=prior,
            task_budget_id=task_budget_id,
            cap_usd=task_budget_cap,
        )
    else:
        if prior != Decimal("0.000000"):
            raise FormalCanaryError("nonzero-prior identity has no task budget envelope")
        budget = task_budget_status(
            start_task_budget(
                envelope_path,
                active=active,
                task_budget_id=task_budget_id,
                cap_usd=task_budget_cap,
            )
        )
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
        "required_paid_action": _required_paid_action(identity),
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
    active, prior, task_budget_id, task_budget_cap = _identity_budget(identity)
    envelope_path = task_budget_path(paths.common_root, task_budget_id)
    budget = (
        task_budget_status(
            load_task_budget(
                envelope_path,
                task_budget_id=task_budget_id,
                cap_usd=task_budget_cap,
            )
        )
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
    parser = argparse.ArgumentParser(prog="rondo-direction0-canary")
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=(
            "status",
            "initialize",
            "prepare",
            "preflight",
            "compare",
            "run",
            "resume",
            "finalize",
        ),
    )
    parser.add_argument("--paid-action")
    parser.add_argument("--docker-host-volume", type=Path)
    parser.add_argument("--results-worktree-root", type=Path)
    parser.add_argument("--rondo-measurement-worktree-root", type=Path)
    parser.add_argument("--codex-measurement-worktree-root", type=Path)
    parser.add_argument("--campaign-id")
    parser.add_argument("--batch-id")
    parser.add_argument("--run-id-date")
    parser.add_argument("--run-id-sequence-base", type=int)
    parser.add_argument("--comparison-contract", type=Path)
    parser.add_argument("--rondo-runtime-manifest", type=Path)
    parser.add_argument("--rondo-source-commit")
    parser.add_argument("--codex-runtime-manifest", type=Path)
    parser.add_argument("--price-snapshot-date")
    parser.add_argument("--task-budget-id")
    parser.add_argument("--task-budget-cap-usd")
    parser.add_argument("--task-budget-prior-estimated-usd")
    parser.add_argument("--metrics-dir", type=Path)
    return parser


def initialize(paths: RepoPaths, args: argparse.Namespace) -> dict[str, object]:
    """Mint one explicit identity and initialize its new or successor envelope."""

    required = (
        "campaign_id",
        "batch_id",
        "run_id_date",
        "run_id_sequence_base",
        "comparison_contract",
        "rondo_runtime_manifest",
        "rondo_source_commit",
        "codex_runtime_manifest",
        "price_snapshot_date",
        "task_budget_id",
        "task_budget_cap_usd",
        "task_budget_prior_estimated_usd",
    )
    missing = [name for name in required if getattr(args, name) is None]
    if missing:
        raise FormalCanaryError(
            "initialize arguments are missing: " + ",".join(missing)
        )
    contract_path = args.comparison_contract
    assert isinstance(contract_path, Path)
    if contract_path.is_symlink() or not contract_path.is_file():
        raise FormalCanaryError("comparison contract file is unavailable")
    try:
        comparison = json.loads(contract_path.read_bytes())
        task_budget_cap = Decimal(str(args.task_budget_cap_usd))
        task_budget_prior = Decimal(str(args.task_budget_prior_estimated_usd))
    except (OSError, UnicodeError, json.JSONDecodeError, InvalidOperation) as exc:
        raise FormalCanaryError("initialize input is unreadable") from exc
    if not isinstance(comparison, dict):
        raise FormalCanaryError("comparison contract is not an object")
    path, prior = generate_successor_lock(
        paths,
        campaign_id=str(args.campaign_id),
        batch_id=str(args.batch_id),
        run_id_date=str(args.run_id_date),
        run_id_sequence_base=int(args.run_id_sequence_base),
        comparison=comparison,
        rondo_runtime_manifest=args.rondo_runtime_manifest,
        rondo_source_commit=str(args.rondo_source_commit),
        codex_runtime_manifest=args.codex_runtime_manifest,
        price_snapshot_date=str(args.price_snapshot_date),
        task_budget_id=str(args.task_budget_id),
        task_budget_cap_usd=task_budget_cap,
        task_budget_prior_estimated_usd=task_budget_prior,
    )
    prepared = prepare(paths)
    return {
        **prepared,
        "status": "initialized",
        "lock_path": path.as_posix(),
        "task_budget_prior_estimated_usd": f"{prior:.6f}",
        "next_action": (
            "run" if prepared["preflight_receipts_ready"] else "preflight"
        ),
    }


def run_preflight(paths: RepoPaths, args: argparse.Namespace) -> int:
    """Run the stub producer under the shared heavy lock and resource watchdog."""

    if args.docker_host_volume is None:
        raise FormalCanaryError("preflight docker host volume is required")
    if args.metrics_dir is None:
        raise FormalCanaryError("preflight metrics directory is required")
    metrics_dir = (
        args.metrics_dir
        if args.metrics_dir.is_absolute()
        else paths.common_root / args.metrics_dir
    )
    if metrics_dir.exists() or metrics_dir.is_symlink():
        raise FormalCanaryError("preflight metrics directory already exists")
    environment = dict(os.environ)
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        environment.pop(name, None)
    environment.update(
        {
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "RONDO_BUILD_METRICS_DIR": str(metrics_dir),
        }
    )
    completed = subprocess.run(
        (
            str(paths.worktree_root / "scripts/with-build-lock.sh"),
            sys.executable,
            "-B",
            "-m",
            "rondo_eval.terminal_bench.preflight_producer",
            "--docker-host-volume",
            str(args.docker_host_volume),
        ),
        cwd=paths.worktree_root / "eval",
        env=environment,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = RepoPaths.discover(Path.cwd())
    if args.action == "status":
        print(json.dumps(status(paths), sort_keys=True))
        return 0
    if args.action == "initialize":
        print(json.dumps(initialize(paths, args), sort_keys=True))
        return 0
    if args.action == "prepare":
        print(json.dumps(prepare(paths), sort_keys=True))
        return 0
    if args.action == "preflight":
        return run_preflight(paths, args)
    if args.action == "compare":
        if args.results_worktree_root is None:
            raise FormalCanaryError("comparison results worktree is required")
        if args.campaign_id is None:
            identity = load_campaign_identity(paths)
        else:
            try:
                version = int(str(args.campaign_id).rsplit("v", 1)[1])
            except (IndexError, ValueError) as exc:
                raise FormalCanaryError("comparison campaign ID is invalid") from exc
            identity = load_historical_campaign_identity(paths, version)
            if identity.campaign_id != args.campaign_id:
                raise FormalCanaryError("comparison campaign ID is invalid")
        destination = publish_relative_baseline_comparison(
            paths,
            identity=identity,
            results_worktree_root=args.results_worktree_root,
        )
        print(
            json.dumps(
                {
                    "status": "published",
                    "comparison_path": destination.as_posix(),
                    "paid_requests_sent": 0,
                },
                sort_keys=True,
            )
        )
        return 0
    if args.action in {"run", "resume"}:
        if args.paid_action is None:
            raise FormalCanaryError("explicit paid action is required")
        paid_identity = load_campaign_identity(paths)
        if args.paid_action != _required_paid_action(paid_identity):
            raise FormalCanaryError("paid action differs from the task budget identity")
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
    if terminal in {BaselineStatus.PASSED, BaselineStatus.FAILED}:
        expected_exit_code = 0 if terminal is BaselineStatus.PASSED else 2
        if exit_code != expected_exit_code:
            return exit_code
        active, _prior, task_budget_id, task_budget_cap = _identity_budget(identity)
        envelope_path = task_budget_path(paths.common_root, task_budget_id)
        envelope = load_task_budget(
            envelope_path,
            task_budget_id=task_budget_id,
            cap_usd=task_budget_cap,
        )
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
                task_budget_id=task_budget_id,
                cap_usd=task_budget_cap,
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
