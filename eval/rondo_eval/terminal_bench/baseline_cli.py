"""Execute the one frozen P2 B7 canary-baseline campaign."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..api_budget_proxy import PersistentBudgetLedger
from ..artifacts import ArtifactWriter
from ..config import RepoPaths, load_provider_secret, load_runtime_config
from ..contracts import BinaryManifest, RunOutcome, Side
from ..docker_supervisor import DockerOperation, DockerTaskIdentity
from ..model_cli_diagnostic import run_campaign as run_model_cli_campaign
from ..runtime_bridge import (
    DockerCliCounter,
    PowerShellDockerDesktopHostProbe,
    SubprocessCommandExecutor,
    lease_from_watchdog,
)
from .__main__ import (
    _docker_failure_diagnostic,
    _exception_failure,
    _load_manifest,
    _outcome_exit_code,
)
from .baseline import (
    BASE_ROUNDS,
    RUN_CAP_USD,
    SOL_MAX_LEGAL_REQUEST_RESERVATION_USD,
    BaselineRun,
    BaselineAssessment,
    BaselineStatus,
    CampaignIdentity,
    CampaignSlotPlan,
    CampaignSlotStatus,
    CampaignStateLedger,
    ConditionalRun,
    DiagnosisDisposition,
    DiagnosisStatus,
    MECHANICAL_CIRCUIT_BREAKER_TASKS,
    MAX_REMAINING_INFRA_PER_ROUND,
    MIN_COMMON_VALID_TASKS,
    MechanicalFailureCategory,
    assess_baseline,
    campaign_slot_chain_id,
    load_campaign_identity,
)
from .live import run_budgeted_terminal_bench
from .materialize import validate_frozen_task_source
from .oracle_proof import OracleProofStore, build_oracle_contract
from .metrics import RunnerMetricsTimer
from .pair import (
    CampaignPublicationContext,
    load_historical_pair_identity,
    validate_harbor_installation,
)
from .results import (
    classify_terminal_bench_result,
    parse_single_task_result,
    publish_terminal_bench_failure,
    publish_terminal_bench_result,
    validate_eval_harness_checkout,
    validate_measurement_checkout,
    validate_results_worktree,
)
from .runner import HARBOR_EXECUTABLE, TerminalBenchRequest
from .runner import DockerSupervisedHostHarborExecutor
from .materialize import PinnedTaskMaterializer
from .scoring import (
    GuardianDecision,
    GuardianOutcome,
    TaskOutcome,
    TaskScoreInput,
    aggregate_scores,
    score_task,
)


_WINDOWS_C_FLOOR_BYTES = 80 * 1024**3
_DOCKER_WARN_GROWTH_BYTES = 40 * 1024**3
_DOCKER_STOP_GROWTH_BYTES = 60 * 1024**3


class CampaignExecutionError(RuntimeError):
    """Raised when the frozen B7 campaign cannot progress safely."""


class _CampaignStepAdvanced(RuntimeError):
    """Internal control flow after one paid slot is durably terminal."""


class _CampaignReplayBoundary(RuntimeError):
    """Recovery replay reached the first slot that has never been claimed."""


class _CampaignDiagnosisRequired(RuntimeError):
    """One task chain is safely paused for offline structured RCA."""

    def __init__(self, *, chain_id: str, category: MechanicalFailureCategory) -> None:
        super().__init__(f"diagnosis_required:{chain_id}:{category.value}")
        self.chain_id = chain_id
        self.category = category


@dataclass(frozen=True)
class ExecutedSlot:
    slot: CampaignSlotPlan
    outcome: RunOutcome
    task_outcome: TaskOutcome
    estimated_usd: Decimal
    failure_category: MechanicalFailureCategory | None = None


class MechanicalFailureTracker:
    """Open the campaign circuit after one category reaches three tasks."""

    def __init__(self) -> None:
        self._tasks: dict[MechanicalFailureCategory, set[str]] = {
            item: set() for item in MechanicalFailureCategory
        }

    def observe(self, executed: ExecutedSlot) -> None:
        if executed.task_outcome is not TaskOutcome.INFRA:
            if executed.failure_category is not None:
                raise CampaignExecutionError(
                    "non-infra result has a mechanical failure category"
                )
            return
        category = executed.failure_category
        task_id = executed.slot.task_id
        if category is None or task_id is None:
            raise CampaignExecutionError(
                "infra result lacks a structured mechanical failure category"
            )
        if category in {
            MechanicalFailureCategory.BUDGET_CAPACITY,
            MechanicalFailureCategory.OPERATOR_INTERRUPTION,
        }:
            raise CampaignExecutionError(f"campaign_terminal_failure:{category.value}")
        self._tasks[category].add(task_id)
        if len(self._tasks[category]) >= MECHANICAL_CIRCUIT_BREAKER_TASKS:
            raise CampaignExecutionError(
                f"mechanical_circuit_breaker:{category.value}"
            )


@dataclass(frozen=True)
class StorageBaseline:
    docker_total_bytes: int
    docker_desktop_vhdx_bytes: int
    windows_free_bytes: int


class CampaignExecutionLease:
    """Non-blocking coordinator lease observed by each locked worker."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._descriptor: int | None = None
        self._token: str | None = None

    def __enter__(self) -> "CampaignExecutionLease":
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            self.path,
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise CampaignExecutionError("campaign lease path is unsafe")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(descriptor)
            raise CampaignExecutionError(
                "another executor already owns the campaign lease"
            ) from exc
        token = os.urandom(32).hex()
        payload = (token + "\n").encode("ascii")
        try:
            os.ftruncate(descriptor, 0)
            os.lseek(descriptor, 0, os.SEEK_SET)
            if os.write(descriptor, payload) != len(payload):
                raise OSError("short campaign lease token write")
            os.fsync(descriptor)
        except OSError as exc:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
            raise CampaignExecutionError(
                "campaign lease token write was incomplete"
            ) from exc
        self._descriptor = descriptor
        self._token = token
        return self

    def __exit__(self, *_ignored: object) -> None:
        descriptor = self._descriptor
        self._descriptor = None
        self._token = None
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    @property
    def descriptor(self) -> int:
        if self._descriptor is None:
            raise CampaignExecutionError("campaign execution lease is not open")
        return self._descriptor

    @property
    def token(self) -> str:
        if self._token is None:
            raise CampaignExecutionError("campaign execution lease is not open")
        return self._token


def _require_held_campaign_lease(path: Path, token: object) -> None:
    """Require the coordinator's live lease before a hidden worker can advance."""

    if not isinstance(token, str) or len(token) != 64 or any(
        character not in "0123456789abcdef" for character in token
    ):
        raise CampaignExecutionError("campaign worker has no valid lease token")
    try:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise OSError
        descriptor = os.open(
            path,
            os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
    except (OSError, UnicodeError) as exc:
        raise CampaignExecutionError("campaign execution lease is unavailable") from exc
    try:
        opened = os.fstat(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        observed = os.read(descriptor, 66)
        if (
            (opened.st_dev, opened.st_ino) != (metadata.st_dev, metadata.st_ino)
            or observed != (token + "\n").encode("ascii")
        ):
            raise CampaignExecutionError("campaign execution lease changed")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        raise CampaignExecutionError("campaign execution lease is not held")
    finally:
        os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rondo_eval.terminal_bench.baseline_cli")
    parser.add_argument("--docker-host-volume", required=True, type=Path)
    parser.add_argument("--results-worktree-root", required=True, type=Path)
    parser.add_argument("--rondo-measurement-worktree-root", required=True, type=Path)
    parser.add_argument("--codex-measurement-worktree-root", required=True, type=Path)
    parser.add_argument("--worker-step", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--campaign-lease-token", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.worker_step:
        return _worker_step_main(args)
    return _coordinator_main(args)


def _coordinator_main(args: argparse.Namespace) -> int:
    paths = RepoPaths.discover(Path.cwd())
    identity = load_campaign_identity(paths)
    results_root = validate_results_worktree(
        args.results_worktree_root,
        common_root=paths.common_root,
    )
    _require_distinct_results_worktree(paths, results_root)
    campaign_root = paths.common_root / "eval-data/campaigns" / identity.campaign_id
    campaign_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lease_path = campaign_root / "executor.lock"
    with CampaignExecutionLease(lease_path) as lease:
        for _ in range(len(identity.slots) + len(identity.catalog.tasks) + 10):
            completed = subprocess.run(
                _locked_worker_argv(paths, args, lease_token=lease.token),
                cwd=paths.worktree_root,
                env=_locked_worker_environment(worktree_root=paths.worktree_root),
                stdin=subprocess.DEVNULL,
                stdout=None,
                stderr=None,
                check=False,
            )
            if completed.returncode == 10:
                continue
            return completed.returncode
    raise CampaignExecutionError("campaign step bound was exceeded")


def _locked_worker_argv(
    paths: RepoPaths,
    args: argparse.Namespace,
    *,
    lease_token: str,
) -> tuple[str, ...]:
    return (
        str(paths.worktree_root / "mydev/scripts/with-build-lock.sh"),
        sys.executable,
        "-B",
        "-m",
        "rondo_eval.terminal_bench.baseline_cli",
        "--worker-step",
        "--campaign-lease-token",
        lease_token,
        "--docker-host-volume",
        str(args.docker_host_volume),
        "--results-worktree-root",
        str(args.results_worktree_root),
        "--rondo-measurement-worktree-root",
        str(args.rondo_measurement_worktree_root),
        "--codex-measurement-worktree-root",
        str(args.codex_measurement_worktree_root),
    )


_WORKER_ENV_KEYS = frozenset(
    {
        "HOME",
        "DBUS_SESSION_BUS_ADDRESS",
        "LANG",
        "LC_ALL",
        "LOGNAME",
        "PATH",
        "RONDO_BUILD_METRICS_DIR",
        "SHELL",
        "SYSTEMD_EXEC_PID",
        "TERM",
        "TMPDIR",
        "USER",
        "UV_CACHE_DIR",
        "UV_PROJECT_ENVIRONMENT",
        "WSL_DISTRO_NAME",
        "WSL_INTEROP",
        "XDG_RUNTIME_DIR",
    }
)


def _locked_worker_environment(
    source: dict[str, str] | None = None,
    *,
    worktree_root: Path | None = None,
) -> dict[str, str]:
    source = dict(os.environ if source is None else source)
    value = {key: source[key] for key in _WORKER_ENV_KEYS if source.get(key)}
    value["NO_PROXY"] = "127.0.0.1,localhost"
    value["no_proxy"] = "127.0.0.1,localhost"
    if worktree_root is not None:
        value["PYTHONPATH"] = str(worktree_root / "eval")
    return value


def _terminal_exit_code(status: object) -> int:
    if status == BaselineStatus.PASSED.value:
        return 0
    if status == BaselineStatus.FAILED.value:
        return 2
    if status == BaselineStatus.BLOCKED.value:
        return 3
    raise CampaignExecutionError("campaign terminal status is invalid")


def _worker_step_main(args: argparse.Namespace) -> int:
    paths = RepoPaths.discover(Path.cwd())
    identity = load_campaign_identity(paths)
    campaign_root = (
        paths.common_root / "eval-data" / "campaigns" / identity.campaign_id
    )
    _require_held_campaign_lease(
        campaign_root / "executor.lock",
        args.campaign_lease_token,
    )
    config = load_runtime_config(paths)
    provider = config.paid_provider_projection()
    identity.validate_provider(provider)
    eval_harness_commit = validate_eval_harness_checkout(common_root=paths.common_root)
    results_root = validate_results_worktree(
        args.results_worktree_root,
        common_root=paths.common_root,
    )
    _require_distinct_results_worktree(paths, results_root)
    manifests = _load_and_validate_manifests(paths, identity)
    measurement_roots = {
        Side.RONDO: RepoPaths.discover(args.rondo_measurement_worktree_root),
        Side.CODEX: RepoPaths.discover(args.codex_measurement_worktree_root),
    }
    measurement_commits = {
        side: validate_measurement_checkout(
            measurement_roots[side], side=side, manifest=manifests[side]
        )
        for side in Side
    }
    validate_harbor_installation(
        load_historical_pair_identity(), executable=HARBOR_EXECUTABLE
    )
    seccomp_profile = identity.validate_runtime_seccomp(
        project_root=paths.worktree_root
    )
    proof = lease_from_watchdog()
    counter = DockerCliCounter(
        host_data_root=args.docker_host_volume,
        desktop_host_probe=PowerShellDockerDesktopHostProbe(),
    )
    state_path = campaign_root / "state.json"
    budget_path = (
        paths.common_root / "eval-data" / "budgets" / f"{identity.batch_id}.json"
    )
    campaign_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    storage_baseline = _load_or_create_storage_baseline(
        campaign_root,
        counter,
        identity.slots[0].run_id,
    )
    _sample_storage(counter, identity.slots[0].run_id, baseline=storage_baseline)
    recovery_exit = _reconcile_before_oracle(
        paths=paths,
        identity=identity,
        campaign_root=campaign_root,
        state_path=state_path,
        budget_path=budget_path,
        config=config,
        counter=counter,
        proof=proof,
        storage_baseline=storage_baseline,
        results_root=results_root,
        manifests=manifests,
        measurement_roots=measurement_roots,
        measurement_commits=measurement_commits,
        eval_harness_commit=eval_harness_commit,
        seccomp_profile=seccomp_profile,
    )
    if recovery_exit is not None:
        return recovery_exit
    oracle_ready = _run_oracle_preflight(
        paths=paths,
        identity=identity,
        campaign_root=campaign_root,
        counter=counter,
        proof=proof,
        seccomp_profile=seccomp_profile,
        provider_api_key_env=provider.api_key_env,
        max_new_proofs=1,
    )
    if not oracle_ready:
        return 10
    with CampaignStateLedger(
        state_path,
        identity=identity,
        allow_interrupted_recovery=True,
    ) as state:
        return _advance_post_oracle_step(
            paths=paths,
            identity=identity,
            campaign_root=campaign_root,
            budget_path=budget_path,
            config=config,
            counter=counter,
            proof=proof,
            storage_baseline=storage_baseline,
            results_root=results_root,
            manifests=manifests,
            measurement_roots=measurement_roots,
            measurement_commits=measurement_commits,
            eval_harness_commit=eval_harness_commit,
            seccomp_profile=seccomp_profile,
            state=state,
        )


def _advance_post_oracle_step(
    *,
    paths: RepoPaths,
    identity: CampaignIdentity,
    campaign_root: Path,
    budget_path: Path,
    config: object,
    counter: DockerCliCounter,
    proof: object,
    storage_baseline: StorageBaseline,
    results_root: Path,
    manifests: dict[Side, BinaryManifest],
    measurement_roots: dict[Side, RepoPaths],
    measurement_commits: dict[Side, str],
    eval_harness_commit: str,
    seccomp_profile: Path,
    state: CampaignStateLedger,
) -> int:
    """Advance exactly one wire or paid step after all Oracle proofs validate."""

    snapshot = state.snapshot()
    if snapshot["status"] != "running":
        return _terminal_exit_code(snapshot["status"])
    try:
        _reconcile_running_wire_canary(
            paths=paths,
            identity=identity,
            campaign_root=campaign_root,
            state=state,
            counter=counter,
            storage_baseline=storage_baseline,
        )
    except CampaignExecutionError as exc:
        _skip_planned(state, identity, reason="wire_canary_interrupted")
        state.finalize(BaselineStatus.BLOCKED, reason=str(exc))
        return 3
    snapshot = state.snapshot()
    wire = next(row for row in snapshot["slots"] if row["slot_id"] == "wire-canary")
    if wire["status"] == CampaignSlotStatus.PLANNED.value:
        try:
            _execute_wire_canary(paths, identity, campaign_root, state)
        except CampaignExecutionError as exc:
            _skip_planned(state, identity, reason="wire_canary_failed")
            state.finalize(BaselineStatus.BLOCKED, reason=str(exc))
            return 3
        return 10
    if wire["status"] != CampaignSlotStatus.COMPLETED.value:
        _skip_planned(state, identity, reason="wire_canary_failed")
        state.finalize(BaselineStatus.BLOCKED, reason="wire_canary_not_completed")
        return 3
    canary_cost = Decimal(wire["estimated_usd"])
    prior_cost = Decimal(identity.budget["prior_estimated_usd"])
    campaign_cap = Decimal(identity.budget["campaign_cap_usd"])
    remaining_cap = campaign_cap - prior_cost - canary_cost
    if remaining_cap < SOL_MAX_LEGAL_REQUEST_RESERVATION_USD:
        _skip_planned(state, identity, reason="budget_after_wire_canary")
        state.finalize(BaselineStatus.BLOCKED, reason="budget_after_wire_canary")
        return 3
    _secret_name, api_key = load_provider_secret(config)
    with PersistentBudgetLedger(
        budget_path,
        batch_id=identity.batch_id,
        total_cap_usd=remaining_cap,
        max_runs=len(identity.slots) - 1,
        default_run_cap_usd=RUN_CAP_USD,
    ) as budget:
        try:
            _reconcile_running_paid_slot(
                paths=paths,
                identity=identity,
                state=state,
                budget=budget,
                counter=counter,
                storage_baseline=storage_baseline,
                results_root=results_root,
            )
            return _advance_one_paid_step(
                paths=paths,
                identity=identity,
                state=state,
                budget=budget,
                config=config,
                provider_key=api_key,
                counter=counter,
                proof=proof,
                storage_baseline=storage_baseline,
                results_root=results_root,
                manifests=manifests,
                measurement_roots=measurement_roots,
                measurement_commits=measurement_commits,
                eval_harness_commit=eval_harness_commit,
                seccomp_profile=seccomp_profile,
                campaign_root=campaign_root,
                canary_cost=canary_cost,
            )
        except _CampaignDiagnosisRequired as exc:
            print(
                json.dumps(
                    {
                        "status": "diagnosis_required",
                        "campaign_id": identity.campaign_id,
                        "chain_id": exc.chain_id,
                        "category": exc.category.value,
                    },
                    sort_keys=True,
                )
            )
            return 11
        except CampaignExecutionError as exc:
            _skip_planned(state, identity, reason="campaign_stopped")
            state.finalize(BaselineStatus.BLOCKED, reason=str(exc))
            final_storage = _optional_final_storage(
                counter,
                identity.slots[0].run_id,
                baseline=storage_baseline,
            )
            _write_aggregate(
                campaign_root,
                identity,
                state,
                budget.snapshot(),
                canary_cost,
                assessment=None,
                results_root=results_root,
                storage_baseline=storage_baseline,
                final_storage=final_storage,
            )
            return 3


def _reconcile_before_oracle(
    *,
    paths: RepoPaths,
    identity: CampaignIdentity,
    campaign_root: Path,
    state_path: Path,
    budget_path: Path,
    config: object,
    counter: DockerCliCounter,
    proof: object,
    storage_baseline: StorageBaseline,
    results_root: Path,
    manifests: dict[Side, BinaryManifest],
    measurement_roots: dict[Side, RepoPaths],
    measurement_commits: dict[Side, str],
    eval_harness_commit: str,
    seccomp_profile: Path,
) -> int | None:
    """Reconcile the one claimed slot before invalidating or rerunning Oracle proof."""

    with CampaignStateLedger(
        state_path,
        identity=identity,
        allow_interrupted_recovery=True,
    ) as state:
        snapshot = state.snapshot()
        if snapshot["status"] != "running":
            return _terminal_exit_code(snapshot["status"])
        running = [row for row in snapshot["slots"] if row["status"] == "running"]
        if not running:
            return None
        if len(running) != 1:
            raise CampaignExecutionError("campaign running slot recovery is ambiguous")
        if running[0]["slot_id"] == "wire-canary":
            try:
                _reconcile_running_wire_canary(
                    paths=paths,
                    identity=identity,
                    campaign_root=campaign_root,
                    state=state,
                    counter=counter,
                    storage_baseline=storage_baseline,
                )
            except CampaignExecutionError as exc:
                _skip_planned(state, identity, reason="wire_canary_interrupted")
                state.finalize(BaselineStatus.BLOCKED, reason=str(exc))
                return 3
            return 10

        wire = next(
            row for row in snapshot["slots"] if row["slot_id"] == "wire-canary"
        )
        if wire["status"] != CampaignSlotStatus.COMPLETED.value:
            raise CampaignExecutionError("paid slot exists before completed wire canary")
        canary_cost = Decimal(str(wire["estimated_usd"]))
        prior_cost = Decimal(str(identity.budget["prior_estimated_usd"]))
        campaign_cap = Decimal(str(identity.budget["campaign_cap_usd"]))
        remaining_cap = campaign_cap - prior_cost - canary_cost
        with PersistentBudgetLedger(
            budget_path,
            batch_id=identity.batch_id,
            total_cap_usd=remaining_cap,
            max_runs=len(identity.slots) - 1,
            default_run_cap_usd=RUN_CAP_USD,
        ) as budget:
            try:
                recovered = _reconcile_running_paid_slot(
                    paths=paths,
                    identity=identity,
                    state=state,
                    budget=budget,
                    counter=counter,
                    storage_baseline=storage_baseline,
                    results_root=results_root,
                )
                if not recovered:
                    raise CampaignExecutionError(
                        "campaign running slot recovery disappeared"
                    )
                slot = identity.slot(str(running[0]["slot_id"]))
                _replay_recovered_attempt_chain(
                    paths=paths,
                    identity=identity,
                    state=state,
                    budget=budget,
                    config=config,
                    counter=counter,
                    proof=proof,
                    storage_baseline=storage_baseline,
                    results_root=results_root,
                    manifests=manifests,
                    measurement_roots=measurement_roots,
                    measurement_commits=measurement_commits,
                    eval_harness_commit=eval_harness_commit,
                    seccomp_profile=seccomp_profile,
                    recovered_slot=slot,
                )
                return 10
            except _CampaignDiagnosisRequired as exc:
                print(
                    json.dumps(
                        {
                            "status": "diagnosis_required",
                            "campaign_id": identity.campaign_id,
                            "chain_id": exc.chain_id,
                            "category": exc.category.value,
                        },
                        sort_keys=True,
                    )
                )
                return 11
            except CampaignExecutionError as exc:
                _skip_planned(state, identity, reason="campaign_stopped")
                state.finalize(BaselineStatus.BLOCKED, reason=str(exc))
                final_storage = _optional_final_storage(
                    counter,
                    identity.slots[0].run_id,
                    baseline=storage_baseline,
                )
                _write_aggregate(
                    campaign_root,
                    identity,
                    state,
                    budget.snapshot(),
                    canary_cost,
                    assessment=None,
                    results_root=results_root,
                    storage_baseline=storage_baseline,
                    final_storage=final_storage,
                )
                return 3
            return 10


def _reconcile_running_wire_canary(
    *,
    paths: RepoPaths,
    identity: CampaignIdentity,
    campaign_root: Path,
    state: CampaignStateLedger,
    counter: DockerCliCounter,
    storage_baseline: StorageBaseline,
) -> None:
    running = [
        row for row in state.snapshot()["slots"] if row["status"] == "running"
    ]
    if not running:
        return
    if len(running) != 1 or running[0]["slot_id"] != "wire-canary":
        return
    receipt_path = campaign_root / "wire-canary/receipt.json"
    if receipt_path.is_symlink() or not receipt_path.is_file():
        state.fail_interrupted(
            estimated_usd="0.000000",
            reason=MechanicalFailureCategory.OPERATOR_INTERRUPTION.value,
        )
        raise CampaignExecutionError("wire canary was interrupted without a receipt")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        spent = Decimal(str(receipt["estimated_spent_usd"]))
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ArithmeticError) as exc:
        state.fail_interrupted(
            estimated_usd="0.000000",
            reason=MechanicalFailureCategory.OPERATOR_INTERRUPTION.value,
        )
        raise CampaignExecutionError("wire canary receipt is invalid") from exc
    if receipt.get("status") != "completed" or spent < 0:
        state.fail_interrupted(
            estimated_usd=f"{max(spent, Decimal(0)):.6f}",
            reason=MechanicalFailureCategory.OPERATOR_INTERRUPTION.value,
        )
        raise CampaignExecutionError("wire canary did not complete before interruption")
    _sample_storage(counter, identity.slots[0].run_id, baseline=storage_baseline)
    state.finish(
        "wire-canary",
        status=CampaignSlotStatus.COMPLETED,
        outcome="completed",
        estimated_usd=f"{spent:.6f}",
        artifact_path=receipt_path.relative_to(paths.common_root).as_posix(),
        result_record_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        reason=None,
    )


def _reconcile_running_paid_slot(
    *,
    paths: RepoPaths,
    identity: CampaignIdentity,
    state: CampaignStateLedger,
    budget: PersistentBudgetLedger,
    counter: DockerCliCounter,
    storage_baseline: StorageBaseline,
    results_root: Path,
) -> bool:
    running = [
        row for row in state.snapshot()["slots"] if row["status"] == "running"
    ]
    if not running:
        return False
    if len(running) != 1 or running[0]["slot_id"] == "wire-canary":
        raise CampaignExecutionError("campaign running slot recovery is ambiguous")
    row = running[0]
    slot = identity.slot(row["slot_id"])
    records, digests = _campaign_records(results_root, identity)
    budget_snapshot = budget.snapshot()
    run = budget_snapshot["runs"].get(slot.run_id)
    record = records.get(slot.run_id)
    if record is not None and isinstance(run, dict):
        _validate_recoverable_publication(identity, slot, record, run)
        _sample_storage(counter, slot.run_id, baseline=storage_baseline)
        task_outcome = _task_outcome_from_record(record)
        category = _record_failure_category(record, task_outcome, run)
        state.finish(
            slot.slot_id,
            status=CampaignSlotStatus.COMPLETED,
            outcome=str(record["outcome"]),
            estimated_usd=f"{Decimal(run['spent_usd']):.6f}",
            artifact_path=str(record["artifacts"]),
            result_record_sha256=digests[slot.run_id],
            reason=category.value if category is not None else None,
        )
        return True
    spent = Decimal(run["spent_usd"]) if isinstance(run, dict) else Decimal(0)
    state.fail_interrupted(
        estimated_usd=f"{spent:.6f}",
        reason=MechanicalFailureCategory.OPERATOR_INTERRUPTION.value,
    )
    raise CampaignExecutionError("paid campaign slot was interrupted ambiguously")


def _replay_recovered_attempt_chain(
    *,
    paths: RepoPaths,
    identity: CampaignIdentity,
    state: CampaignStateLedger,
    budget: PersistentBudgetLedger,
    config: object,
    counter: DockerCliCounter,
    proof: object,
    storage_baseline: StorageBaseline,
    results_root: Path,
    manifests: dict[Side, BinaryManifest],
    measurement_roots: dict[Side, RepoPaths],
    measurement_commits: dict[Side, str],
    eval_harness_commit: str,
    seccomp_profile: Path,
    recovered_slot: CampaignSlotPlan,
) -> None:
    task = next(
        (item for item in identity.catalog.tasks if item.task_id == recovered_slot.task_id),
        None,
    )
    if task is None:
        raise CampaignExecutionError("recovered campaign task is not frozen")
    records, digests = _campaign_records(results_root, identity)
    try:
        _execute_attempt_chain(
            identity=identity,
            state=state,
            tracker=MechanicalFailureTracker(),
            task=task,
            chain_id=campaign_slot_chain_id(recovered_slot),
            paths=paths,
            budget=budget,
            config=config,
            provider_key="",
            counter=counter,
            proof=proof,
            storage_baseline=storage_baseline,
            results_root=results_root,
            manifests=manifests,
            measurement_roots=measurement_roots,
            measurement_commits=measurement_commits,
            eval_harness_commit=eval_harness_commit,
            seccomp_profile=seccomp_profile,
            records=records,
            digests=digests,
            resumable=True,
            replay_only=True,
        )
    except _CampaignReplayBoundary:
        return


def _validate_recoverable_publication(
    identity: CampaignIdentity,
    slot: CampaignSlotPlan,
    record: dict[str, object],
    run: dict[str, object],
) -> None:
    config = record.get("config")
    cost = record.get("cost")
    requests = run.get("requests")
    if (
        record.get("run_id") != slot.run_id
        or not isinstance(config, dict)
        or config.get("campaign_id") != identity.campaign_id
        or config.get("campaign_lock_sha256") != identity.lock_sha256
        or config.get("campaign_slot_id") != slot.slot_id
        or not isinstance(cost, dict)
        or Decimal(str(cost.get("estimated_usd"))) != Decimal(str(run.get("spent_usd")))
        or not isinstance(requests, dict)
        or any(
            not isinstance(request, dict)
            or request.get("status") != "settled"
            or request.get("charged_usd") is None
            for request in requests.values()
        )
        or sum(Decimal(request["charged_usd"]) for request in requests.values())
        != Decimal(str(run.get("spent_usd")))
    ):
        raise CampaignExecutionError("interrupted slot publication cannot be reconciled")
    task_outcome = _task_outcome_from_record(record)
    if task_outcome is not TaskOutcome.INFRA and not requests:
        raise CampaignExecutionError("completed task publication has no settled request")


def _task_outcome_from_record(record: dict[str, object]) -> TaskOutcome:
    raw_outcome = record.get("outcome")
    tasks = record.get("tasks")
    if raw_outcome in {
        RunOutcome.INFRA_FAILED.value,
        RunOutcome.BUDGET_STOPPED.value,
        RunOutcome.CANCELLED.value,
    }:
        return TaskOutcome.INFRA
    if not isinstance(tasks, list) or len(tasks) != 1 or not isinstance(tasks[0], dict):
        raise CampaignExecutionError("campaign task result is invalid")
    return TaskOutcome.PASS if tasks[0].get("outcome") == "pass" else TaskOutcome.FAIL


def _record_failure_category(
    record: dict[str, object],
    task_outcome: TaskOutcome,
    run: dict[str, object],
) -> MechanicalFailureCategory | None:
    summary = record.get("summary")
    failure_stage = summary.get("failure_stage") if isinstance(summary, dict) else None
    evidence = summary.get("evidence", []) if isinstance(summary, dict) else []
    guardian_technical = isinstance(evidence, list) and any(
        isinstance(item, dict)
        and item.get("terminal_status") in {"aborted", "timed_out", "failed_closed"}
        for item in evidence
    )
    return _mechanical_failure_category(
        task_outcome=task_outcome,
        failure_stage=failure_stage if isinstance(failure_stage, str) else None,
        guardian_technical_failure=guardian_technical,
        budget_run=run,
    )


def _require_distinct_results_worktree(paths: RepoPaths, results_root: Path) -> None:
    if results_root == paths.worktree_root:
        raise CampaignExecutionError(
            "results worktree must be distinct from the eval harness checkout"
        )


def _load_and_validate_manifests(
    paths: RepoPaths, identity: CampaignIdentity
) -> dict[Side, BinaryManifest]:
    values: dict[Side, BinaryManifest] = {}
    for side in Side:
        relative = identity.bundles[side.value]["manifest_path"]
        manifest_path = paths.common_root / relative
        manifest = _load_manifest(manifest_path, paths.common_root)
        identity.validate_manifest(
            common_root=paths.common_root,
            side=side,
            manifest_path=manifest_path,
            manifest=manifest,
        )
        values[side] = manifest
    return values


def _sample_storage(
    counter: DockerCliCounter,
    run_id: str,
    *,
    baseline: StorageBaseline | None = None,
) -> StorageBaseline:
    reading = counter.sample(
        identity=DockerTaskIdentity(run_id),
        operation=DockerOperation.HOST,
    )
    reading.validate()
    if reading.docker_desktop_vhdx_bytes is None:
        raise CampaignExecutionError("Docker Desktop VHDX counter is unavailable")
    current = StorageBaseline(
        docker_total_bytes=reading.docker_total_bytes,
        docker_desktop_vhdx_bytes=reading.docker_desktop_vhdx_bytes,
        windows_free_bytes=reading.data_root_filesystem_free_bytes,
    )
    if current.windows_free_bytes < _WINDOWS_C_FLOOR_BYTES:
        raise CampaignExecutionError("Windows C: free space is below the 80 GiB floor")
    if baseline is not None:
        docker_growth = current.docker_total_bytes - baseline.docker_total_bytes
        vhd_growth = (
            current.docker_desktop_vhdx_bytes
            - baseline.docker_desktop_vhdx_bytes
        )
        growth = max(docker_growth, vhd_growth)
        if growth >= _DOCKER_STOP_GROWTH_BYTES:
            raise CampaignExecutionError("campaign Docker growth reached 60 GiB")
        if growth >= _DOCKER_WARN_GROWTH_BYTES:
            # The warning is preserved in the final aggregate; execution remains bounded.
            pass
    return current


def _optional_final_storage(
    counter: DockerCliCounter,
    run_id: str,
    *,
    baseline: StorageBaseline,
) -> StorageBaseline | None:
    """Best-effort terminal sample after the campaign is already fail-closed."""

    try:
        return _sample_storage(counter, run_id, baseline=baseline)
    except CampaignExecutionError:
        return None


def _load_or_create_storage_baseline(
    campaign_root: Path,
    counter: DockerCliCounter,
    run_id: str,
) -> StorageBaseline:
    path = campaign_root / "storage-baseline.json"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise CampaignExecutionError("campaign storage baseline is unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignExecutionError("campaign storage baseline is unreadable") from exc
        if not isinstance(value, dict) or set(value) != {
            "docker_total_bytes",
            "docker_desktop_vhdx_bytes",
            "windows_free_bytes",
        }:
            raise CampaignExecutionError("campaign storage baseline is invalid")
        if any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in value.values()
        ):
            raise CampaignExecutionError("campaign storage baseline is invalid")
        return StorageBaseline(**value)
    baseline = _sample_storage(counter, run_id)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    payload = json.dumps(
        {
            "docker_total_bytes": baseline.docker_total_bytes,
            "docker_desktop_vhdx_bytes": baseline.docker_desktop_vhdx_bytes,
            "windows_free_bytes": baseline.windows_free_bytes,
        },
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise
    return baseline


def _validate_daemon_image(task: object) -> None:
    from .tasksets import FrozenTask

    if not isinstance(task, FrozenTask):
        raise CampaignExecutionError("frozen Docker task is invalid")
    executor = SubprocessCommandExecutor(timeout_seconds=15)
    output = executor.run(
        (
            "docker",
            "image",
            "inspect",
            "--format",
            "{{json .Id}}",
            task.image_ref,
        )
    ).stdout.strip()
    try:
        image_id = json.loads(output)
    except json.JSONDecodeError as exc:
        raise CampaignExecutionError("frozen Docker image identity is invalid") from exc
    if (
        not isinstance(image_id, str)
        or not image_id.startswith("sha256:")
        or len(image_id) != 71
    ):
        raise CampaignExecutionError("frozen Docker image is not daemon-resolved")
    workdir_output = executor.run(
        (
            "docker",
            "image",
            "inspect",
            "--format",
            "{{json .Config.WorkingDir}}",
            task.image_ref,
        )
    ).stdout.strip()
    try:
        workdir = json.loads(workdir_output)
    except json.JSONDecodeError as exc:
        raise CampaignExecutionError("frozen Docker workdir is invalid") from exc
    if workdir != task.workdir:
        raise CampaignExecutionError("frozen Docker workdir differs from the catalog")


def _run_oracle_preflight(
    *,
    paths: RepoPaths,
    identity: CampaignIdentity,
    campaign_root: Path,
    counter: DockerCliCounter,
    proof: object,
    seccomp_profile: Path,
    provider_api_key_env: str,
    max_new_proofs: int | None = None,
) -> bool:
    receipt_path = campaign_root / "oracle-preflight.json"
    executor = DockerSupervisedHostHarborExecutor(
        counter=counter,
        lock_guard=proof.guard,
        lease=proof.lease,
    )
    source = paths.common_root / "eval-data/sources/terminal-bench-2-1-ffccbe05"
    store = OracleProofStore(
        paths.common_root / "eval-data/oracle-proofs/p2-b7-v1"
    )
    contracts = tuple(
        build_oracle_contract(
            paths,
            catalog=identity.catalog,
            task=task,
            seccomp_source_sha256=identity.no_api_seccomp["source_sha256"],
            seccomp_effective_sha256=identity.no_api_seccomp["effective_sha256"],
        )
        for task in identity.catalog.tasks
    )
    created = 0
    for task, contract in zip(identity.catalog.tasks, contracts, strict=True):
        if store.valid_proof(contract) is not None:
            continue
        if max_new_proofs is not None and created >= max_new_proofs:
            return False
        validate_frozen_task_source(source, task)
        _validate_daemon_image(task)
        task_root = (
            paths.common_root
            / "eval-data/work/oracle-proofs"
            / f"{contract.sha256}-{os.getpid()}"
        )
        if task_root.exists() or task_root.is_symlink():
            raise CampaignExecutionError("Oracle proof work directory already exists")
        materialized = PinnedTaskMaterializer().materialize(
            source_checkout=source,
            staging_root=task_root,
            staging_name="task",
            image_digest=task.image_digest,
            task_label=f"dev.rondo.eval.task=oracle-{contract.sha256[:20]}",
            memory_bytes=task.memory_mb * 1024**2,
            memory_swap_bytes=(task.memory_mb + 1024) * 1024**2,
            pids_limit=task.pids_limit,
            provider_api_key_env=provider_api_key_env,
            frozen_task=task,
            seccomp_profile=seccomp_profile,
            seccomp_profile_source_sha256=identity.no_api_seccomp["source_sha256"],
            seccomp_profile_effective_sha256=identity.no_api_seccomp["effective_sha256"],
        )
        harbor = asyncio.run(
            executor.run_oracle(materialized, timeout_seconds=task.timeout_seconds)
        )
        parsed = parse_single_task_result(
            harbor.jobs_dir,
            host_returncode=harbor.returncode,
            expected_task_id=task.task_id,
        )
        if (
            parsed.outcome is not RunOutcome.COMPLETED
            or parsed.task_outcome != "pass"
            or parsed.reward != 1.0
            or harbor.docker_evidence is None
        ):
            raise CampaignExecutionError(
                f"no-API oracle preflight failed for {task.task_id}"
            )
        _sample_storage(
            counter,
            identity.slots[0].run_id,
            baseline=_load_or_create_storage_baseline(
                campaign_root, counter, identity.slots[0].run_id
            ),
        )
        store.publish(
            contract,
            outcome=parsed.outcome.value,
            task_outcome=str(parsed.task_outcome),
            reward=float(parsed.reward),
            docker_receipt=harbor.docker_evidence.oracle_receipt(),
        )
        created += 1
    manifest = store.publish_manifest(catalog=identity.catalog, contracts=contracts)
    if manifest is None:
        return False
    reference = {
        "schema_version": 1,
        "relative_path": manifest.relative_to(paths.common_root).as_posix(),
        "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    payload = json.dumps(reference, sort_keys=True, separators=(",", ":")) + "\n"
    if receipt_path.exists() or receipt_path.is_symlink():
        if receipt_path.is_symlink() or receipt_path.read_text(encoding="utf-8") != payload:
            raise CampaignExecutionError("Oracle manifest reference drifted")
        return True
    _write_once_durable_text(receipt_path, payload)
    return True


def _write_once_durable_text(path: Path, payload: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            raise CampaignExecutionError("durable destination already exists")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _execute_wire_canary(
    paths: RepoPaths,
    identity: CampaignIdentity,
    campaign_root: Path,
    state: CampaignStateLedger,
) -> Decimal:
    row = state.snapshot()["slots"][0]
    if row["status"] == CampaignSlotStatus.COMPLETED.value:
        return Decimal(row["estimated_usd"])
    if row["status"] != CampaignSlotStatus.PLANNED.value:
        raise CampaignExecutionError("wire canary is not safely resumable")
    state.claim("wire-canary")
    output_root = campaign_root / "wire-canary"
    receipt = run_model_cli_campaign(
        paths,
        output_root=output_root,
        main_model_alias="sol",
        guardian_model_alias="sol",
        max_retries=0,
        plan014_canary=True,
        p2_campaign_identity=identity,
    )
    spent = Decimal(str(receipt["estimated_spent_usd"]))
    receipt_path = output_root / "receipt.json"
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    completed = receipt.get("status") == "completed"
    state.finish(
        "wire-canary",
        status=(
            CampaignSlotStatus.COMPLETED
            if completed
            else CampaignSlotStatus.FAILED
        ),
        outcome=str(receipt.get("status")),
        estimated_usd=f"{spent:.6f}",
        artifact_path=receipt_path.relative_to(paths.common_root).as_posix(),
        result_record_sha256=digest,
        reason=None if completed else str(receipt.get("stopped_phase")),
    )
    if not completed:
        raise CampaignExecutionError("fresh exact-wire canary failed")
    return spent


def _advance_one_paid_step(
    *,
    paths: RepoPaths,
    identity: CampaignIdentity,
    state: CampaignStateLedger,
    budget: PersistentBudgetLedger,
    counter: DockerCliCounter,
    storage_baseline: StorageBaseline,
    results_root: Path,
    campaign_root: Path,
    canary_cost: Decimal,
    **execute_kwargs: object,
) -> int:
    """Advance at most one paid task while applying every frozen gate in order."""

    records, digests = _campaign_records(results_root, identity)
    tracker = MechanicalFailureTracker()
    resumable = {
        "paths": paths,
        "identity": identity,
        "state": state,
        "budget": budget,
        "counter": counter,
        "storage_baseline": storage_baseline,
        "results_root": results_root,
        "records": records,
        "digests": digests,
        "resumable": True,
        **execute_kwargs,
    }
    try:
        base_runs = _execute_base_rounds(
            failure_tracker=tracker,
            **resumable,
        )
        _require_resolved_base_rounds(identity, base_runs)
        conditional_runs = _execute_conditionals(
            base_runs=base_runs,
            failure_tracker=tracker,
            **resumable,
        )
    except (_CampaignStepAdvanced, _CampaignReplayBoundary):
        return 10

    assessment = assess_baseline(
        tuple(task.task_id for task in identity.catalog.tasks),
        tuple(base_runs),
        tuple(conditional_runs),
        max_attempts=identity.max_attempts,
    )
    _skip_planned(state, identity, reason="not_activated")
    final_storage = _sample_storage(
        counter,
        identity.slots[0].run_id,
        baseline=storage_baseline,
    )
    state.finalize(assessment.status, reason=";".join(assessment.reasons) or None)
    _write_aggregate(
        campaign_root,
        identity,
        state,
        budget.snapshot(),
        canary_cost,
        assessment=assessment,
        results_root=results_root,
        storage_baseline=storage_baseline,
        final_storage=final_storage,
    )
    return 0 if assessment.status is BaselineStatus.PASSED else 2


def _executed_from_row(
    slot: CampaignSlotPlan,
    row: dict[str, object],
    *,
    records: dict[str, dict[str, object]],
    digests: dict[str, str],
) -> ExecutedSlot:
    status = row.get("status")
    if status == CampaignSlotStatus.FAILED.value:
        try:
            category = MechanicalFailureCategory(str(row.get("reason")))
        except ValueError as exc:
            raise CampaignExecutionError("failed slot lacks a mechanical category") from exc
        return ExecutedSlot(
            slot,
            RunOutcome.INFRA_FAILED,
            TaskOutcome.INFRA,
            Decimal(str(row["estimated_usd"])),
            category,
        )
    if status != CampaignSlotStatus.COMPLETED.value:
        raise CampaignExecutionError("required campaign slot is not completed")
    record = records.get(slot.run_id)
    if record is None or digests.get(slot.run_id) != row.get("result_record_sha256"):
        raise CampaignExecutionError("campaign state differs from its public result")
    task_outcome = _task_outcome_from_record(record)
    category: MechanicalFailureCategory | None = None
    if row.get("reason") is not None:
        try:
            category = MechanicalFailureCategory(str(row["reason"]))
        except ValueError as exc:
            raise CampaignExecutionError("campaign failure category is invalid") from exc
    if (task_outcome is TaskOutcome.INFRA) != (category is not None):
        raise CampaignExecutionError("campaign task outcome and category disagree")
    return ExecutedSlot(
        slot,
        RunOutcome(str(row["outcome"])),
        task_outcome,
        Decimal(str(row["estimated_usd"])),
        category,
    )


def _require_or_skip(
    state: CampaignStateLedger,
    slot_id: str,
    *,
    reason: str,
) -> None:
    row = _state_row(state.snapshot(), slot_id)
    if row["status"] == CampaignSlotStatus.PLANNED.value:
        state.skip(slot_id, reason=reason)
        return
    if row["status"] != CampaignSlotStatus.SKIPPED.value or row.get("reason") != reason:
        raise CampaignExecutionError("campaign skip projection drifted")


def _state_row(snapshot: dict[str, object], slot_id: str) -> dict[str, object]:
    rows = [row for row in snapshot["slots"] if row["slot_id"] == slot_id]
    if len(rows) != 1:
        raise CampaignExecutionError("campaign state row is ambiguous")
    return rows[0]


def _execute_base_rounds(
    *,
    failure_tracker: MechanicalFailureTracker | None = None,
    **kwargs: object,
) -> list[BaselineRun]:
    identity: CampaignIdentity = kwargs["identity"]
    state: CampaignStateLedger = kwargs["state"]
    tracker = failure_tracker or MechanicalFailureTracker()
    values: list[BaselineRun] = []
    for round_id in ("aa-rondo-1", "aa-rondo-2", "ab-rondo-1", "ab-codex-1"):
        side = Side.CODEX if round_id == "ab-codex-1" else Side.RONDO
        effective: dict[str, ExecutedSlot] = {}
        for task in identity.catalog.tasks:
            attempts = _execute_attempt_chain(
                tracker=tracker,
                task=task,
                chain_id=f"base:{round_id}:{task.task_id}",
                **kwargs,
            )
            for executed in attempts:
                values.append(
                    BaselineRun(
                        task.task_id,
                        round_id,
                        side,
                        executed.slot.attempt,
                        executed.task_outcome,
                        executed.slot.run_id,
                        executed.failure_category,
                    )
                )
            effective[task.task_id] = attempts[-1]
        if sum(
            item.task_outcome is TaskOutcome.INFRA for item in effective.values()
        ) > MAX_REMAINING_INFRA_PER_ROUND:
            raise CampaignExecutionError(
                f"base_round_infra_threshold_exceeded:{round_id}"
            )
    return values


def _execute_attempt_chain(
    *,
    identity: CampaignIdentity,
    state: CampaignStateLedger,
    tracker: MechanicalFailureTracker,
    task: object,
    chain_id: str,
    **kwargs: object,
) -> list[ExecutedSlot]:
    """Execute or replay one infra-only chain without crossing an RCA hold."""

    values: list[ExecutedSlot] = []
    for attempt in range(1, identity.max_attempts + 1):
        slot = identity.slot(f"{chain_id}:a{attempt}")
        if values and values[-1].task_outcome is not TaskOutcome.INFRA:
            _skip_inactive_attempt(
                state,
                slot.slot_id,
                resumable=kwargs.get("resumable") is True,
            )
            continue
        executed = _execute_task_slot(
            slot=slot,
            task=task,
            identity=identity,
            state=state,
            **kwargs,
        )
        tracker.observe(executed)
        values.append(executed)
        if executed.task_outcome is not TaskOutcome.INFRA:
            continue
        if identity.schema_version < 2:
            continue
        category = executed.failure_category
        if category is None:
            raise CampaignExecutionError(
                "infra result lacks a structured mechanical failure category"
            )
        same_category = tuple(
            item.slot.slot_id for item in values if item.failure_category is category
        )
        if len(same_category) >= 3:
            existing = _existing_diagnosis(
                state,
                chain_id=campaign_slot_chain_id(slot),
                category=category,
            )
            if existing is None or existing.get("status") != (
                DiagnosisStatus.TASK_LOCAL_REPRODUCIBLE_INFRA.value
            ):
                state.mark_task_local_reproducible(
                    chain_id=campaign_slot_chain_id(slot),
                    category=category,
                    trigger_slot_ids=same_category[:3],
                )
            for remaining in range(attempt + 1, identity.max_attempts + 1):
                _skip_inactive_attempt(
                    state,
                    identity.slot(f"{chain_id}:a{remaining}").slot_id,
                    resumable=kwargs.get("resumable") is True,
                    reason=f"task_local_reproducible_infra:{category.value}",
                )
            break
        if len(same_category) == 2:
            existing = _existing_diagnosis(
                state,
                chain_id=campaign_slot_chain_id(slot),
                category=category,
            )
            if existing is not None and existing.get("status") == (
                DiagnosisStatus.TASK_LOCAL_REPRODUCIBLE_INFRA.value
            ):
                continue
            diagnosis = state.require_diagnosis(
                chain_id=campaign_slot_chain_id(slot),
                category=category,
                trigger_slot_ids=same_category,
            )
            if diagnosis["status"] == DiagnosisStatus.REQUIRED.value:
                raise _CampaignDiagnosisRequired(
                    chain_id=campaign_slot_chain_id(slot),
                    category=category,
                )
            if diagnosis.get("disposition") != DiagnosisDisposition.EXTERNAL_TRANSIENT.value:
                raise CampaignExecutionError(
                    f"diagnosed_campaign_defect:{diagnosis.get('disposition')}:{category.value}"
                )
    if not values:
        raise CampaignExecutionError("campaign attempt chain produced no result")
    return values


def _existing_diagnosis(
    state: CampaignStateLedger,
    *,
    chain_id: str,
    category: MechanicalFailureCategory,
) -> dict[str, object] | None:
    loader = getattr(state, "diagnosis", None)
    if loader is None:
        return None
    return loader(chain_id=chain_id, category=category)


def _skip_inactive_attempt(
    state: CampaignStateLedger,
    slot_id: str,
    *,
    resumable: bool,
    reason: str = "infra_attempt_not_activated",
) -> None:
    if resumable:
        _require_or_skip(state, slot_id, reason=reason)
    else:
        state.skip(slot_id, reason=reason)


def _require_resolved_base_rounds(
    identity: CampaignIdentity,
    runs: list[BaselineRun],
) -> tuple[str, ...]:
    """Validate base completeness and return the common comparison set."""

    effective: dict[str, dict[str, BaselineRun]] = {}
    for round_id in ("aa-rondo-1", "aa-rondo-2", "ab-rondo-1", "ab-codex-1"):
        expected_side = Side.CODEX if round_id == "ab-codex-1" else Side.RONDO
        selected_by_task: dict[str, BaselineRun] = {}
        for task in identity.catalog.tasks:
            candidates = [
                run
                for run in runs
                if run.round_id == round_id and run.task_id == task.task_id
            ]
            if not candidates:
                raise CampaignExecutionError("base round result is incomplete")
            selected = max(candidates, key=lambda run: run.attempt)
            if selected.side is not expected_side:
                raise CampaignExecutionError("base round side is invalid")
            selected_by_task[task.task_id] = selected
        effective[round_id] = selected_by_task
    common = tuple(
        task.task_id
        for task in identity.catalog.tasks
        if all(
            effective[round_id][task.task_id].outcome is not TaskOutcome.INFRA
            for round_id in BASE_ROUNDS
        )
    )
    return common


def _execute_conditionals(
    *,
    base_runs: list[BaselineRun],
    failure_tracker: MechanicalFailureTracker | None = None,
    **kwargs: object,
) -> list[ConditionalRun]:
    identity: CampaignIdentity = kwargs["identity"]
    state: CampaignStateLedger = kwargs["state"]
    tracker = failure_tracker or MechanicalFailureTracker()
    tasks = tuple(task.task_id for task in identity.catalog.tasks)
    by_round: dict[str, dict[str, TaskOutcome]] = {}
    for round_id in ("aa-rondo-1", "aa-rondo-2", "ab-rondo-1", "ab-codex-1"):
        candidates = [item for item in base_runs if item.round_id == round_id]
        by_round[round_id] = {
            task_id: sorted(
                (item for item in candidates if item.task_id == task_id),
                key=lambda item: item.attempt,
            )[-1].outcome
            for task_id in tasks
        }
    common_valid_tasks = {
        task_id
        for task_id in tasks
        if all(
            by_round[round_id][task_id] is not TaskOutcome.INFRA
            for round_id in BASE_ROUNDS
        )
    }
    triggers = {
        task_id
        for task_id in common_valid_tasks
        if by_round["ab-rondo-1"][task_id] is TaskOutcome.FAIL
        and by_round["ab-codex-1"][task_id] is TaskOutcome.PASS
    }
    values: list[ConditionalRun] = []
    for task in identity.catalog.tasks:
        for side in (Side.RONDO, Side.CODEX):
            for repeat in (1, 2):
                chain_id = f"conditional:{task.task_id}:{side.value}:repeat{repeat}"
                slots = tuple(
                    identity.slot(f"{chain_id}:a{attempt}")
                    for attempt in range(1, identity.max_attempts + 1)
                )
                if (
                    len(common_valid_tasks) < MIN_COMMON_VALID_TASKS
                    or task.task_id not in triggers
                ):
                    reason = (
                        "common_valid_task_count_below_minimum"
                        if len(common_valid_tasks) < MIN_COMMON_VALID_TASKS
                        else "conditional_not_activated"
                    )
                    if kwargs.get("resumable") is True:
                        for slot in slots:
                            _require_or_skip(state, slot.slot_id, reason=reason)
                    else:
                        for slot in slots:
                            state.skip(slot.slot_id, reason=reason)
                    continue
                attempts = _execute_attempt_chain(
                    tracker=tracker,
                    task=task,
                    chain_id=chain_id,
                    **kwargs,
                )
                for executed in attempts:
                    values.append(
                        ConditionalRun(
                            task.task_id,
                            side,
                            repeat,
                            executed.slot.attempt,
                            executed.task_outcome,
                            executed.slot.run_id,
                            executed.failure_category,
                        )
                    )
    return values


def _execute_task_slot(
    *,
    slot: CampaignSlotPlan,
    task: object,
    paths: RepoPaths,
    identity: CampaignIdentity,
    state: CampaignStateLedger,
    budget: PersistentBudgetLedger,
    config: object,
    provider_key: str,
    counter: DockerCliCounter,
    proof: object,
    storage_baseline: StorageBaseline,
    results_root: Path,
    manifests: dict[Side, BinaryManifest],
    measurement_roots: dict[Side, RepoPaths],
    measurement_commits: dict[Side, str],
    eval_harness_commit: str,
    seccomp_profile: Path,
    records: dict[str, dict[str, object]] | None = None,
    digests: dict[str, str] | None = None,
    resumable: bool = False,
    replay_only: bool = False,
) -> ExecutedSlot:
    from .tasksets import FrozenTask

    if not isinstance(task, FrozenTask):
        raise CampaignExecutionError("campaign task projection is invalid")
    if resumable:
        if records is None or digests is None:
            raise CampaignExecutionError("resumable execution lacks public records")
        row = _state_row(state.snapshot(), slot.slot_id)
        if row["status"] != CampaignSlotStatus.PLANNED.value:
            return _executed_from_row(
                slot,
                row,
                records=records,
                digests=digests,
            )
        if replay_only:
            raise _CampaignReplayBoundary
    validate_frozen_task_source(
        paths.common_root / "eval-data/sources/terminal-bench-2-1-ffccbe05",
        task,
    )
    _validate_daemon_image(task)
    snapshot = budget.snapshot()
    if Decimal(snapshot["remaining_uncommitted_usd"]) < SOL_MAX_LEGAL_REQUEST_RESERVATION_USD:
        raise CampaignExecutionError("remaining campaign budget cannot fit the next request")
    _sample_storage(counter, slot.run_id, baseline=storage_baseline)
    identity.validate_provider(config.paid_provider_projection())
    if validate_eval_harness_checkout(common_root=paths.common_root) != eval_harness_commit:
        raise CampaignExecutionError("eval harness drifted during the campaign")
    if (
        validate_measurement_checkout(
            measurement_roots[slot.side],
            side=slot.side,
            manifest=manifests[slot.side],
        )
        != measurement_commits[slot.side]
    ):
        raise CampaignExecutionError("measurement checkout drifted during the campaign")
    work_root = paths.common_root / "eval-data" / "work" / slot.run_id
    if work_root.exists() or work_root.is_symlink():
        raise CampaignExecutionError("campaign work directory is already present")
    if slot.run_id in budget.snapshot()["runs"]:
        raise CampaignExecutionError("campaign budget run ID was already consumed")
    state.claim(slot.slot_id)
    try:
        budget.claim_run(slot.run_id)
    except Exception as exc:
        state.finish(
            slot.slot_id,
            status=CampaignSlotStatus.FAILED,
            outcome=RunOutcome.BUDGET_STOPPED.value,
            estimated_usd="0.000000",
            artifact_path=None,
            result_record_sha256=None,
            reason=MechanicalFailureCategory.BUDGET_CAPACITY.value,
        )
        raise CampaignExecutionError("campaign budget run cannot be claimed") from exc
    metadata_path = work_root / "api-metadata.json"
    request = TerminalBenchRequest(
        side=slot.side,
        batch_id=identity.batch_id,
        binary=manifests[slot.side],
        image_digest=task.image_digest,
        source_checkout=str(
            paths.common_root
            / "eval-data/sources/terminal-bench-2-1-ffccbe05"
        ),
        staging_root=str(work_root / "staging"),
        docker_task_id=slot.run_id,
        memory_bytes=task.memory_mb * 1024**2,
        memory_swap_bytes=(task.memory_mb + 1024) * 1024**2,
        pids_limit=task.pids_limit,
        provider_transport_base_url=None,
        timeout_seconds=task.timeout_seconds,
        max_retries=0,
        budget_usd=float(RUN_CAP_USD),
        seccomp_profile_path=str(seccomp_profile),
        seccomp_profile_source_sha256=identity.no_api_seccomp["source_sha256"],
        seccomp_profile_effective_sha256=identity.no_api_seccomp["effective_sha256"],
        require_container_metrics=True,
        frozen_task=task,
    )
    writer = ArtifactWriter(
        paths,
        slot.run_id,
        results_worktree_root=results_root,
    ).start()
    timer = RunnerMetricsTimer()
    publication = lambda exit_code: CampaignPublicationContext(
        campaign_id=identity.campaign_id,
        campaign_lock_sha256=identity.lock_sha256,
        campaign_slot_id=slot.slot_id,
        campaign_round_id=slot.round_id or slot.kind,
        campaign_attempt=slot.attempt,
        taskset_sha256=identity.taskset_sha256,
        canary_catalog_sha256=identity.canary_catalog_sha256,
        side=slot.side,
        metrics=timer.snapshot(exit_code=exit_code).to_dict(),
        selected_profile=identity.selected_profile,
    )
    failure_stage: str | None = None
    guardian_technical_failure = False
    try:
        live = asyncio.run(
            run_budgeted_terminal_bench(
                config,
                request,
                api_key=provider_key,
                ledger=budget,
                metadata_path=metadata_path,
                counter=counter,
                lock_guard=proof.guard,
                lease=proof.lease,
                campaign_identity=identity,
                campaign_slot=slot,
                campaign_task=task,
                campaign_seccomp_profile=seccomp_profile,
            )
        )
        parsed = parse_single_task_result(
            live.harbor.jobs_dir,
            host_returncode=live.harbor.returncode,
            expected_task_id=task.task_id,
        )
        parsed = classify_terminal_bench_result(live, parsed)
        guardian_technical_failure = any(
            item.terminal_status in {"aborted", "timed_out", "failed_closed"}
            for item in live.evidence
        )
        artifact = publish_terminal_bench_result(
            paths,
            results_worktree_root=results_root,
            run_id=slot.run_id,
            side=slot.side,
            git_commit=measurement_commits[slot.side],
            eval_harness_commit=eval_harness_commit,
            live_result=live,
            parsed=parsed,
            metadata_path=metadata_path,
            publication=publication(_outcome_exit_code(parsed.outcome)),
            writer=writer,
        )
        outcome = parsed.outcome
        task_outcome = (
            TaskOutcome.INFRA
            if outcome not in {RunOutcome.COMPLETED, RunOutcome.AGENT_FAILED}
            else (TaskOutcome.PASS if parsed.task_outcome == "pass" else TaskOutcome.FAIL)
        )
        secrets = live.redaction_secrets
    except (Exception, KeyboardInterrupt, asyncio.CancelledError) as exc:
        if writer.publication_started():
            raise
        writer.abort()
        writer = ArtifactWriter(
            paths,
            slot.run_id,
            results_worktree_root=results_root,
        ).start()
        outcome, failure_stage, exit_code = _exception_failure(exc)
        artifact = publish_terminal_bench_failure(
            paths,
            writer=writer,
            run_id=slot.run_id,
            side=slot.side,
            git_commit=measurement_commits[slot.side],
            eval_harness_commit=eval_harness_commit,
            manifest=manifests[slot.side],
            provider=config.paid_provider_projection(),
            budget_snapshot=budget.snapshot(),
            metadata_path=metadata_path,
            outcome=outcome,
            failure_stage=failure_stage,
            infra_diagnostic=_docker_failure_diagnostic(exc),
            publication=publication(exit_code),
            secrets=(provider_key,),
            task_id=task.task_id,
            task_image_digest=task.image_digest,
        )
        task_outcome = TaskOutcome.INFRA
        secrets = (provider_key,)
    del secrets
    run = budget.snapshot()["runs"][slot.run_id]
    spent = Decimal(run["spent_usd"])
    failure_category = _mechanical_failure_category(
        task_outcome=task_outcome,
        failure_stage=failure_stage,
        guardian_technical_failure=guardian_technical_failure,
        budget_run=run,
    )
    record_digest = _result_record_sha256(results_root, slot.run_id)
    _sample_storage(counter, slot.run_id, baseline=storage_baseline)
    state.finish(
        slot.slot_id,
        status=CampaignSlotStatus.COMPLETED,
        outcome=outcome.value,
        estimated_usd=f"{spent:.6f}",
        artifact_path=artifact.relative_to(paths.common_root).as_posix(),
        result_record_sha256=record_digest,
        reason=failure_category.value if failure_category is not None else None,
    )
    executed = ExecutedSlot(slot, outcome, task_outcome, spent, failure_category)
    if resumable:
        raise _CampaignStepAdvanced
    return executed


_PROVIDER_INTEGRITY_STOP_REASONS = frozenset(
    {
        "missing_or_invalid_usage",
        "upstream_deadline_exhausted",
        "upstream_unavailable",
        "upstream_failure",
        "unclassified_upstream_failure",
        "upstream_non_success",
        "upstream_response_unavailable",
        "operator_confirmed_unbilled_attempts_exhausted",
        "operator_confirmed_unbilled_deadline_exhausted",
        "operator_confirmed_unbilled_proxy_closing",
        "proxy_closing",
    }
)
_GUARDIAN_PROTOCOL_STOP_REASONS = frozenset(
    {
        "guardian_duplicate_logical_request_rejected",
        "guardian_logical_request_limit_exceeded",
        "logical_request_limit_exceeded",
    }
)


def _mechanical_failure_category(
    *,
    task_outcome: TaskOutcome,
    failure_stage: str | None,
    guardian_technical_failure: bool,
    budget_run: object,
) -> MechanicalFailureCategory | None:
    """Classify infra from typed stage and ledger state, never message text."""

    if task_outcome is not TaskOutcome.INFRA:
        return None
    if not isinstance(budget_run, dict):
        raise CampaignExecutionError("campaign budget run projection is invalid")
    stop_reason = budget_run.get("stop_reason")
    if stop_reason in _PROVIDER_INTEGRITY_STOP_REASONS:
        return MechanicalFailureCategory.PROVIDER_RESPONSE_INTEGRITY
    if stop_reason in _GUARDIAN_PROTOCOL_STOP_REASONS:
        return MechanicalFailureCategory.GUARDIAN_RUNTIME
    if stop_reason == "usage_cost_exceeded_reservation":
        return MechanicalFailureCategory.BUDGET_CAPACITY
    if stop_reason == "interrupted_request" or failure_stage == "interrupted":
        return MechanicalFailureCategory.OPERATOR_INTERRUPTION
    if failure_stage in {"docker", "runtime"}:
        return MechanicalFailureCategory.DOCKER_RUNTIME
    if failure_stage == "publication":
        return MechanicalFailureCategory.PUBLICATION_INTEGRITY
    if failure_stage == "budget":
        return MechanicalFailureCategory.BUDGET_CAPACITY
    if guardian_technical_failure:
        return MechanicalFailureCategory.GUARDIAN_RUNTIME
    return MechanicalFailureCategory.HARNESS_RUNTIME


def _result_record_sha256(results_root: Path, run_id: str) -> str:
    rows = [
        line
        for line in (results_root / "eval/results/runs.jsonl").read_bytes().splitlines()
        if json.loads(line).get("run_id") == run_id
    ]
    if len(rows) != 1:
        raise CampaignExecutionError("published campaign result is not unique")
    return hashlib.sha256(rows[0]).hexdigest()


def _skip_planned(
    state: CampaignStateLedger, identity: CampaignIdentity, *, reason: str
) -> None:
    snapshot = state.snapshot()
    by_id = {row["slot_id"]: row for row in snapshot["slots"]}
    for slot in identity.slots:
        if by_id[slot.slot_id]["status"] == CampaignSlotStatus.PLANNED.value:
            state.skip(slot.slot_id, reason=reason)


def _write_aggregate(
    campaign_root: Path,
    identity: CampaignIdentity,
    state: CampaignStateLedger,
    budget: dict[str, object],
    canary_cost: Decimal,
    *,
    assessment: object | None,
    results_root: Path,
    storage_baseline: StorageBaseline,
    final_storage: StorageBaseline | None,
) -> None:
    prior_cost = Decimal(identity.budget["prior_estimated_usd"])
    spent = prior_cost + canary_cost + Decimal(budget["spent_usd"])
    records, record_digests = _campaign_records(results_root, identity)
    usage = _campaign_usage(campaign_root.parents[2], records)
    request_count = sum(
        len(run["requests"])
        for run in budget["runs"].values()
    )
    upstream_attempt_count = sum(
        request["attempt_count"]
        for run in budget["runs"].values()
        for request in run["requests"].values()
    )
    public_assessment = _public_assessment(assessment, records)
    state_snapshot = state.snapshot()
    value = {
        "schema_version": identity.schema_version,
        "campaign_id": identity.campaign_id,
        "campaign_lock_sha256": identity.lock_sha256,
        "taskset_sha256": identity.taskset_sha256,
        "canary_catalog_sha256": identity.canary_catalog_sha256,
        "status": state_snapshot["status"],
        "actual_usd": None,
        "estimated_usd": f"{spent:.6f}",
        "prior_estimated_usd": f"{prior_cost:.6f}",
        "wire_canary_usd": f"{canary_cost:.6f}",
        "budget": budget,
        "assessment": public_assessment,
        "request_count": request_count,
        "upstream_attempt_count": upstream_attempt_count,
        "usage": usage,
        "result_record_sha256": record_digests,
        "storage": _storage_projection(storage_baseline, final_storage),
    }
    if identity.schema_version >= 2:
        value["diagnoses"] = state_snapshot["diagnoses"]
    path = campaign_root / "aggregate.json"
    temporary = path.with_name(".aggregate.json.tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    public = {
        key: value[key]
        for key in (
            "schema_version",
            "campaign_id",
            "campaign_lock_sha256",
            "taskset_sha256",
            "canary_catalog_sha256",
            "status",
            "actual_usd",
            "estimated_usd",
            "prior_estimated_usd",
            "wire_canary_usd",
            "assessment",
            "request_count",
            "upstream_attempt_count",
            "usage",
            "result_record_sha256",
            "storage",
        )
    }
    public["reserved_usd"] = budget["reserved_usd"]
    public["run_slots_used"] = budget["run_slots_used"]
    if identity.schema_version >= 2:
        public["diagnoses"] = value["diagnoses"]
    destination = (
        results_root
        / "eval/results/baselines"
        / f"{identity.campaign_id}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise CampaignExecutionError("tracked campaign aggregate already exists")
    tracked_temporary = destination.with_name(f".{destination.name}.tmp")
    tracked_temporary.write_text(
        json.dumps(public, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    tracked_temporary.replace(destination)


def _storage_projection(
    initial: StorageBaseline,
    final: StorageBaseline | None,
) -> dict[str, object]:
    initial_value = {
        "docker_total_bytes": initial.docker_total_bytes,
        "docker_desktop_vhdx_bytes": initial.docker_desktop_vhdx_bytes,
        "windows_free_bytes": initial.windows_free_bytes,
    }
    if final is None:
        return {"initial": initial_value, "final": None, "growth_bytes": None}
    final_value = {
        "docker_total_bytes": final.docker_total_bytes,
        "docker_desktop_vhdx_bytes": final.docker_desktop_vhdx_bytes,
        "windows_free_bytes": final.windows_free_bytes,
    }
    return {
        "initial": initial_value,
        "final": final_value,
        "growth_bytes": max(
            final.docker_total_bytes - initial.docker_total_bytes,
            final.docker_desktop_vhdx_bytes - initial.docker_desktop_vhdx_bytes,
        ),
    }


def _campaign_records(
    results_root: Path, identity: CampaignIdentity
) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    path = results_root / "eval/results/runs.jsonl"
    records: dict[str, dict[str, object]] = {}
    digests: dict[str, str] = {}
    for line in path.read_bytes().splitlines():
        record = json.loads(line)
        config = record.get("config") if isinstance(record, dict) else None
        if not isinstance(config, dict) or config.get("campaign_id") != identity.campaign_id:
            continue
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or run_id in records:
            raise CampaignExecutionError("campaign result index is ambiguous")
        records[run_id] = record
        digests[run_id] = hashlib.sha256(line).hexdigest()
    return records, dict(sorted(digests.items()))


def _campaign_usage(
    common_root: Path, records: dict[str, dict[str, object]]
) -> dict[str, int]:
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
    }
    for record in records.values():
        artifact = record.get("artifacts")
        if not isinstance(artifact, str):
            raise CampaignExecutionError("campaign artifact projection is invalid")
        path = common_root / artifact / "api-metadata.json"
        if not path.exists():
            summary = record.get("summary")
            if isinstance(summary, dict) and summary.get("metadata_ready") is False:
                continue
            raise CampaignExecutionError("campaign API metadata is unavailable")
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignExecutionError("campaign API metadata is unavailable") from exc
        requests = metadata.get("requests") if isinstance(metadata, dict) else None
        if not isinstance(requests, list):
            raise CampaignExecutionError("campaign API metadata is invalid")
        for request in requests:
            usage = request.get("usage") if isinstance(request, dict) else None
            if usage is None:
                continue
            if not isinstance(usage, dict) or set(usage) != set(totals):
                raise CampaignExecutionError("campaign usage projection is invalid")
            for key in totals:
                value = usage[key]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise CampaignExecutionError("campaign usage token count is invalid")
                totals[key] += value
    return totals


def _public_assessment(
    assessment: object | None,
    records: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    if assessment is None:
        return None
    if not isinstance(assessment, BaselineAssessment):
        raise CampaignExecutionError("campaign assessment type is invalid")
    rounds: dict[str, object] = {}
    for round_id in ("aa-rondo-1", "aa-rondo-2", "ab-rondo-1", "ab-codex-1"):
        selected = tuple(
            item
            for item in assessment.effective_base_runs
            if item.round_id == round_id
            and item.task_id in assessment.common_valid_tasks
        )
        scores = tuple(_score_record(records[item.run_id]) for item in selected)
        rounds[round_id] = aggregate_scores(scores, taskset="canary")
    conditionals = [
        {
            "run_id": item.run_id,
            "task_id": item.task_id,
            "side": item.side.value,
            "repeat": item.repeat,
            "score": _score_record(records[item.run_id]).outcome.value,
            "attribution": (
                _score_record(records[item.run_id]).attribution.value
                if _score_record(records[item.run_id]).attribution is not None
                else None
            ),
        }
        for item in assessment.effective_conditional_runs
    ]
    return {
        "status": assessment.status.value,
        "reasons": list(assessment.reasons),
        "sigma": assessment.sigma,
        "delta": assessment.delta,
        "common_valid_tasks": list(assessment.common_valid_tasks),
        "common_valid_task_count": len(assessment.common_valid_tasks),
        "conditional_tasks": list(assessment.conditional_tasks),
        "base_rounds": rounds,
        "conditional_runs": conditionals,
        "infra_failure_categories": _infra_failure_categories(assessment),
    }


def _infra_failure_categories(
    assessment: BaselineAssessment,
) -> dict[str, int]:
    counts = {item.value: 0 for item in MechanicalFailureCategory}
    for item in (
        *assessment.effective_base_runs,
        *assessment.effective_conditional_runs,
    ):
        if item.outcome is TaskOutcome.INFRA:
            if item.failure_category is None:
                raise CampaignExecutionError(
                    "public infra result lacks a mechanical failure category"
                )
            counts[item.failure_category.value] += 1
        elif item.failure_category is not None:
            raise CampaignExecutionError(
                "public non-infra result has a mechanical failure category"
            )
    return counts


def _score_record(record: dict[str, object]):
    tasks = record.get("tasks")
    summary = record.get("summary")
    if (
        not isinstance(tasks, list)
        or len(tasks) != 1
        or not isinstance(tasks[0], dict)
        or not isinstance(summary, dict)
    ):
        raise CampaignExecutionError("campaign result cannot be scored")
    task = tasks[0]
    raw_outcome = record.get("outcome")
    if raw_outcome in {
        RunOutcome.INFRA_FAILED.value,
        RunOutcome.BUDGET_STOPPED.value,
        RunOutcome.CANCELLED.value,
    }:
        outcome = TaskOutcome.INFRA
    else:
        outcome = TaskOutcome.PASS if task.get("outcome") == "pass" else TaskOutcome.FAIL
    evidence = summary.get("evidence", [])
    if not isinstance(evidence, list):
        raise CampaignExecutionError("campaign Guardian evidence is invalid")
    decisions: list[GuardianDecision] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise CampaignExecutionError("campaign Guardian evidence is invalid")
        terminal = item.get("terminal_status")
        if terminal == "approved":
            guardian_outcome = GuardianOutcome.APPROVED
        elif terminal == "denied":
            guardian_outcome = GuardianOutcome.DENIED
        else:
            guardian_outcome = GuardianOutcome.TECHNICAL_FAILURE
        decisions.append(
            GuardianDecision(
                guardian_outcome,
                item.get("canonical_request_sha256"),
            )
        )
    return score_task(
        TaskScoreInput(task["task_id"], outcome, tuple(decisions)),
        deny_adjudications={},
    )


if __name__ == "__main__":
    raise SystemExit(main())
