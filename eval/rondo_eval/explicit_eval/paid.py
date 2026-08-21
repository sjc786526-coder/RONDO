"""Fail-closed Phase-B entry for the Plan 050 fixed six-slot case study."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from ..config import RepoPaths, load_provider_secret, load_runtime_config
from ..docker_supervisor import DockerCounter, HeavyLockGuard, HeavyLockLease
from ..multi_m5.archive import harness_identity
from ..proactive_eval.formal import (
    FormalStore,
    Plan049TerminalBenchExecutor,
    formal_identity,
    formal_paths,
    open_paid_ledger,
    plan049_provider_projection,
    require_safe_formal_prefix,
    run_formal_campaign,
)
from .contract import CampaignContract, ContractError, load_contract
from .readiness import require_phase_a_evidence
from .report import paid_case_output_state


PHASE_B_AUTHORIZATION = "AUTHORIZE RONDO PLAN 050 PHASE B REAL API AND DOCKER"
PHASE_B_ACTION = "START RONDO PLAN 050 FIXED SIX-SLOT CASE"
LOCAL_CONDITIONS = "CONFIRM RONDO PLAN 050 LOCAL PAID CONDITIONS READY"


class PaidGuardError(PermissionError):
    """Raised before a secret, Docker, paid state, or provider can be touched."""


@dataclass(frozen=True)
class PaidResources:
    """The checked single Docker/build-lock lease for one paid call."""

    counter: DockerCounter
    lock_guard: HeavyLockGuard
    lease: HeavyLockLease


@dataclass(frozen=True)
class PaidRuntimeDependencies:
    """The first side-effecting production dependency, invoked after pure gates."""

    acquire_docker_gate: Callable[[], PaidResources]


def production_paid_dependencies(paths: RepoPaths) -> PaidRuntimeDependencies:
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
            raise PaidGuardError("Plan 050 Docker/build-lock lease is not held")
        return resources

    return PaidRuntimeDependencies(acquire_docker_gate=acquire)


def enter_paid_phase(
    *,
    repo_root: Path,
    authorization: str | None,
    phase_b_action: str | None,
    actual_cap_usd: str | None,
    confirmed_balance_usd: str | None,
    harness_clean: bool,
    resume_prefix_safe: bool,
    phase_a_evidence_ready: bool,
    independent_review_passed: bool,
    local_conditions_ready: bool,
    docker_resource_gate_ready: bool,
) -> CampaignContract:
    """Pure authorization and actual-cap gate; it performs no callbacks or writes."""

    if authorization != PHASE_B_AUTHORIZATION:
        raise PaidGuardError("Plan 050 Phase B authorization is absent")
    if phase_b_action != PHASE_B_ACTION:
        raise PaidGuardError("Plan 050 Phase B action is absent")
    try:
        balance = Decimal(confirmed_balance_usd or "")
    except InvalidOperation as exc:
        raise PaidGuardError("Plan 050 balance confirmation is invalid") from exc
    if not balance.is_finite() or balance <= 0:
        raise PaidGuardError("Plan 050 balance confirmation is invalid")
    try:
        contract = load_contract(repo_root).bind_actual_cap(actual_cap_usd or "")
    except ContractError as exc:
        raise PaidGuardError("Plan 050 actual campaign cap is invalid") from exc
    if balance < contract.campaign_cap_usd:
        raise PaidGuardError("Plan 050 confirmed balance is below the actual cap")
    if harness_clean is not True:
        raise PaidGuardError("Plan 050 paid harness is not clean")
    if resume_prefix_safe is not True:
        raise PaidGuardError("Plan 050 paid resume prefix is unsafe")
    if phase_a_evidence_ready is not True:
        raise PaidGuardError("Plan 050 Phase A evidence is not ready")
    if independent_review_passed is not True:
        raise PaidGuardError("Plan 050 independent review has not passed")
    if local_conditions_ready is not True:
        raise PaidGuardError("Plan 050 local paid conditions are not ready")
    if docker_resource_gate_ready is not True:
        raise PaidGuardError("Plan 050 Docker resource gate is not ready")
    return contract


def run_authorized_paid_phase(
    *,
    repo_root: Path,
    authorization: str | None,
    phase_b_action: str | None,
    actual_cap_usd: str | None,
    confirmed_balance_usd: str | None,
    local_confirmation: str | None,
    independent_review_commit: str | None,
    rehearsal_namespace: str,
    loopback_namespace: str,
    dependencies: PaidRuntimeDependencies | None = None,
) -> dict:
    """Run the exact case schedule only after every Phase-B gate succeeds."""

    paths = RepoPaths.discover(repo_root)
    actual_harness = harness_identity(paths.worktree_root)
    harness_commit = actual_harness.get("harness_commit")
    harness_clean = actual_harness.get("harness_dirty") is False
    contract = enter_paid_phase(
        repo_root=paths.worktree_root,
        authorization=authorization,
        phase_b_action=phase_b_action,
        actual_cap_usd=actual_cap_usd,
        confirmed_balance_usd=confirmed_balance_usd,
        harness_clean=harness_clean,
        resume_prefix_safe=True,
        phase_a_evidence_ready=True,
        independent_review_passed=(
            isinstance(harness_commit, str)
            and independent_review_commit == harness_commit
        ),
        local_conditions_ready=local_confirmation == LOCAL_CONDITIONS,
        docker_resource_gate_ready=True,
    )
    try:
        require_phase_a_evidence(
            contract,
            common_root=paths.common_root,
            rehearsal_namespace=rehearsal_namespace,
            loopback_namespace=loopback_namespace,
        )
    except Exception as exc:
        raise PaidGuardError("Plan 050 Phase A evidence is unavailable") from exc
    config = load_runtime_config(paths)
    try:
        provider = plan049_provider_projection(config, contract)
    except Exception as exc:
        raise PaidGuardError("Plan 050 local provider projection drifted") from exc
    if not isinstance(harness_commit, str) or not harness_clean:
        raise PaidGuardError("Plan 050 harness identity changed after authorization")
    identity = formal_identity(
        contract, provider=provider, harness_commit=harness_commit
    )
    paid_paths = formal_paths(paths.common_root, contract)
    try:
        require_safe_formal_prefix(paid_paths, identity, contract)
    except Exception as exc:
        raise PaidGuardError("Plan 050 formal resume prefix is unsafe") from exc

    # This is the first Docker-capable call. The shell entry reaches here only
    # through the shared heavy-operation watchdog.
    runtime_dependencies = dependencies or production_paid_dependencies(paths)
    try:
        resources = runtime_dependencies.acquire_docker_gate()
    except PaidGuardError:
        raise
    except Exception as exc:
        raise PaidGuardError(
            "Plan 050 Docker/build-lock resource gate is unavailable"
        ) from exc
    if (
        not isinstance(resources, PaidResources)
        or not resources.lock_guard.is_held(resources.lease)
    ):
        raise PaidGuardError("Plan 050 Docker/build-lock lease is not held")

    _secret_name, api_key = load_provider_secret(
        config, str(contract.lock["provider"]["name"])
    )
    if not isinstance(api_key, str) or not api_key or "\r" in api_key or "\n" in api_key:
        raise PaidGuardError("Plan 050 provider secret is unavailable")
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
        aggregate = run_formal_campaign(
            contract,
            store=store,
            ledger=ledger,
            executor=executor,
            phase="case",
        )
    # The trace-backed influence judgment can only be made after all Team Lens
    # artifacts exist.  Do not freeze six implicit ``unknown`` values here;
    # the local-only finalize entry requires one explicit assessment per slot.
    return {**aggregate, "case_outputs": paid_case_output_state(aggregate)}
