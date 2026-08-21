"""Fail-closed Phase-B gate and the concrete Plan 049 paid entry."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from ..config import RepoPaths, load_provider_secret, load_runtime_config
from ..docker_supervisor import DockerCounter, HeavyLockGuard, HeavyLockLease
from ..multi_m5.archive import harness_identity
from .contract import CampaignContract, load_contract
from .formal import (
    FormalStore,
    Plan049TerminalBenchExecutor,
    formal_identity,
    formal_paths,
    open_paid_ledger,
    plan049_provider_projection,
    require_safe_formal_prefix,
    run_formal_campaign,
)
from .readiness import require_phase_a_evidence
from .recovery import (
    RECOVERY_ID,
    RECOVERY_REMAINING_USD,
    require_safe_recovery_prefix,
)


PHASE_B_AUTHORIZATION = "AUTHORIZE RONDO PLAN 049 PHASE B REAL API AND DOCKER UP TO USD 100.00"
ACTIVATION_ACTION = "START RONDO PLAN 049 ACTIVATION PILOT"
LOCAL_ACTIVATION_CONFIRMATION = (
    "CONFIRM RONDO PLAN 049 LOCAL ACTIVATION CONDITIONS READY"
)


class PaidGuardError(PermissionError):
    """Raised before secret, network, Docker, ledger, receipt, or run creation."""


@dataclass(frozen=True)
class PaidResources:
    """The already-checked single Docker/build-lock lease for one paid call."""

    counter: DockerCounter
    lock_guard: HeavyLockGuard
    lease: HeavyLockLease


@dataclass(frozen=True)
class PaidRuntimeDependencies:
    """Side effects invoked by the concrete entry, only after its pure gates."""

    acquire_docker_gate: Callable[[], PaidResources]


def production_paid_dependencies(paths: RepoPaths) -> PaidRuntimeDependencies:
    """Bind the paid CLI to the existing watchdog and Docker counter."""

    def acquire() -> PaidResources:
        from ..runtime_bridge import (
            DockerCliCounter,
            PowerShellDockerDesktopHostProbe,
            lease_from_watchdog,
        )

        proof = lease_from_watchdog()
        lease = HeavyLockLease(proof.lease.token, proof.lease.held)
        counter = DockerCliCounter(
            host_data_root=paths.common_root / "eval-data" / "docker-host",
            desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        )
        resources = PaidResources(counter=counter, lock_guard=proof.guard, lease=lease)
        if resources.lock_guard.is_held(resources.lease) is not True:
            raise PaidGuardError("Plan 049 Docker/build-lock lease is not held")
        return resources

    return PaidRuntimeDependencies(acquire_docker_gate=acquire)


def enter_paid_phase(
    *,
    repo_root: Path,
    authorization: str | None,
    activation_action: str | None,
    confirmed_balance_usd: str | None,
    harness_clean: bool,
    resume_prefix_safe: bool,
    activation_conditions_ready: bool,
    docker_resource_gate_ready: bool,
    phase_a_evidence_ready: bool,
    independent_review_passed: bool,
    minimum_balance_usd: Decimal | str = Decimal("100.00"),
) -> CampaignContract:
    """Pure authorization gate; it has no callback and creates no state."""

    if authorization != PHASE_B_AUTHORIZATION:
        raise PaidGuardError("Plan 049 Phase B authorization is absent")
    if activation_action != ACTIVATION_ACTION:
        raise PaidGuardError("Plan 049 activation action is absent")
    try:
        balance = Decimal(confirmed_balance_usd or "")
    except InvalidOperation as exc:
        raise PaidGuardError("Plan 049 balance confirmation is invalid") from exc
    try:
        minimum_balance = Decimal(str(minimum_balance_usd))
    except InvalidOperation as exc:
        raise PaidGuardError("Plan 049 minimum balance is invalid") from exc
    if (
        not minimum_balance.is_finite()
        or minimum_balance <= 0
        or not balance.is_finite()
        or balance < minimum_balance
    ):
        raise PaidGuardError("Plan 049 confirmed balance is below the required cap")
    if harness_clean is not True:
        raise PaidGuardError("Plan 049 paid harness is not clean")
    if resume_prefix_safe is not True:
        raise PaidGuardError("Plan 049 paid resume prefix is unsafe")
    if phase_a_evidence_ready is not True:
        raise PaidGuardError("Plan 049 Phase A evidence is not ready")
    if independent_review_passed is not True:
        raise PaidGuardError("Plan 049 independent review has not passed")
    if activation_conditions_ready is not True:
        raise PaidGuardError("Plan 049 local activation conditions are not ready")
    if docker_resource_gate_ready is not True:
        raise PaidGuardError("Plan 049 Docker resource gate is not ready")
    contract = load_contract(repo_root)
    paths = RepoPaths.discover(repo_root)
    try:
        plan049_provider_projection(load_runtime_config(paths), contract)
    except Exception as exc:
        raise PaidGuardError("Plan 049 local provider projection drifted") from exc
    return contract


def run_authorized_paid_phase(
    *,
    repo_root: Path,
    authorization: str | None,
    activation_action: str | None,
    confirmed_balance_usd: str | None,
    local_activation_confirmation: str | None,
    independent_review_commit: str | None,
    rehearsal_namespace: str,
    loopback_namespace: str,
    phase: str,
    dependencies: PaidRuntimeDependencies | None = None,
    recovery_id: str | None = None,
) -> dict:
    """Run the real pilot/formal schedule through the shared paid runner.

    The order is deliberate: offline evidence and all authorization booleans,
    then the Docker/resource gate, then the secret, then receipt/ledger state,
    and only then the budget proxy plus Terminal-Bench executor.
    """

    paths = RepoPaths.discover(repo_root)
    if phase not in {"pilot", "formal"}:
        raise PaidGuardError("Plan 049 paid phase is invalid")
    actual_harness = harness_identity(paths.worktree_root)
    harness_commit = actual_harness.get("harness_commit")
    harness_clean = actual_harness.get("harness_dirty") is False
    if recovery_id not in {None, RECOVERY_ID}:
        raise PaidGuardError("Plan 049 recovery identity is invalid")
    contract = enter_paid_phase(
        repo_root=paths.worktree_root,
        authorization=authorization,
        activation_action=activation_action,
        confirmed_balance_usd=confirmed_balance_usd,
        harness_clean=harness_clean,
        # Both are revalidated below by the production path before secrets or
        # formal state.  These booleans say the concrete checks are wired.
        resume_prefix_safe=True,
        activation_conditions_ready=(
            local_activation_confirmation == LOCAL_ACTIVATION_CONFIRMATION
        ),
        docker_resource_gate_ready=True,
        # Verified immediately below before any resource/secret/state action.
        phase_a_evidence_ready=True,
        independent_review_passed=(
            isinstance(harness_commit, str)
            and independent_review_commit == harness_commit
        ),
        minimum_balance_usd=(
            RECOVERY_REMAINING_USD if recovery_id is not None else Decimal("100.00")
        ),
    )
    try:
        require_phase_a_evidence(
            contract,
            common_root=paths.common_root,
            rehearsal_namespace=rehearsal_namespace,
            loopback_namespace=loopback_namespace,
        )
    except Exception as exc:
        raise PaidGuardError("Plan 049 Phase A evidence is unavailable") from exc
    config = load_runtime_config(paths)
    provider = plan049_provider_projection(config, contract)
    if (
        not isinstance(harness_commit, str)
        or actual_harness.get("harness_dirty") is not False
    ):
        raise PaidGuardError("Plan 049 harness identity changed after authorization")
    if recovery_id is None:
        identity = formal_identity(
            contract, provider=provider, harness_commit=harness_commit
        )
        paid_paths = formal_paths(paths.common_root, contract)
    else:
        try:
            recovery = require_safe_recovery_prefix(
                contract,
                common_root=paths.common_root,
                provider=provider,
                recovery_harness_commit=harness_commit,
                recovery_id=recovery_id,
            )
        except Exception as exc:
            raise PaidGuardError("Plan 049 recovery prefix is unsafe") from exc
        identity = recovery.identity
        paid_paths = recovery.paths.formal
    try:
        require_safe_formal_prefix(paid_paths, identity, contract)
    except Exception as exc:
        raise PaidGuardError("Plan 049 formal resume prefix is unsafe") from exc
    # This is the first authorized Docker interaction. The factory owns the
    # before/after resource observations and returns the held shared lock.
    runtime_dependencies = dependencies or production_paid_dependencies(paths)
    try:
        resources = runtime_dependencies.acquire_docker_gate()
    except PaidGuardError:
        raise
    except Exception as exc:
        raise PaidGuardError(
            "Plan 049 Docker/build-lock resource gate is unavailable"
        ) from exc
    if (
        not isinstance(resources, PaidResources)
        or not resources.lock_guard.is_held(resources.lease)
    ):
        raise PaidGuardError("Plan 049 Docker/build-lock lease is not held")
    _secret_name, api_key = load_provider_secret(
        config, str(contract.lock["provider"]["name"])
    )
    if not isinstance(api_key, str) or not api_key or "\r" in api_key or "\n" in api_key:
        raise PaidGuardError("Plan 049 provider secret is unavailable")
    store = FormalStore(paid_paths, identity)
    store.ensure_receipt()
    with open_paid_ledger(store.paths.ledger, contract) as ledger:
        executor = Plan049TerminalBenchExecutor(
            contract=contract,
            common_root=paths.common_root,
            repo_root=paths.worktree_root,
            ledger=ledger,
            api_key=api_key,
            counter=resources.counter,
            lock_guard=resources.lock_guard,
            lease=resources.lease,
            config=config,
            formal_identity_sha256=store.identity_sha256,
            paid_paths=paid_paths,
        )
        return run_formal_campaign(
            contract,
            store=store,
            ledger=ledger,
            executor=executor,
            phase=phase,
        )
