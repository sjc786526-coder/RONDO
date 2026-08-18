"""Light interleaved gate 2 orchestrator.

Slot walking, attempt/budget caps, and archives live here. Fake execution uses
``ScriptedSlotExecutor``. Real execution uses ``TerminalBenchSlotExecutor``:
existing ``terminal_bench`` adapters, runner, and result parsing — not a v7
campaign or preflight receipt.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Protocol

from ..api_budget_proxy import (
    ApiBudgetProxyError,
    BudgetStopped,
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    Usage,
    _UrllibTransport,
    price_usage,
)
from ..config import RepoPaths, RuntimeConfig, load_runtime_config
from ..contracts import BinaryManifest, Product, RunOutcome, Side
from ..docker_supervisor import (
    DATA_ROOT_FREE_STOP_BYTES,
    DOCKER_GROWTH_STOP_BYTES,
    DOCKER_GROWTH_WARN_BYTES,
    DockerCounter,
    DockerResourceStop,
    HeavyLockGuard,
    HeavyLockLease,
)
from ..terminal_bench.tasksets import (
    FrozenCanaryCatalog,
    FrozenTask,
    SOURCE_DIRECTORY,
    load_successor_canary_catalog,
)
from ..terminal_bench.results import HarborResultError, parse_single_task_result
from ..terminal_bench.runner import (
    DockerSupervisedHostHarborExecutor,
    InjectedHostHarborBackend,
    PreparedTerminalBenchRun,
    TerminalBenchRequest,
    TerminalBenchRunError,
    UnifiedTerminalBenchRunner,
    prepare_terminal_bench_run,
)
from .archive import archive_record, harness_identity
from .budget import (
    BATCH_ID,
    GATE2_REQUEST_RESERVATION_USD,
    GATE2_RUN_CAP_USD,
    REQUEST_LIMIT_STOP_REASON,
    RequestCappedLedger,
    phase_b_pricing,
    require_frozen_provider,
    run_request_count,
    run_stop_reason,
)
from .bundle import load_side_manifest
from .capture import FORWARD_TIMEOUT_SECONDS
from .load import load_nondegradation_contract, load_runtime_identity
from .paid import PaidAuthorization
from .schedule import (
    DIAGNOSTIC_SLOT_KIND,
    Slot,
    base_slots,
    conditional_slots,
    degradation_on_task,
    diagnostic_slots,
    outcomes_by_task,
)
from .store import persist_archive_record, scratch_root

_FAKE_USAGE = Usage(1_000, 0, 0, 0)
_SECCOMP_RELPATH = "eval/seccomp/plan008-userns-minimal-v0.2.3.json"
_SECCOMP_SOURCE_SHA256 = "9c5198e529f03d38babe9f270f663fa6867bda4e4d14a37a1f6680179d9bbd2f"
_SECCOMP_EFFECTIVE_SHA256 = "a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf"
_SOURCE_RELPATH = f"eval-data/sources/{SOURCE_DIRECTORY}"


class Gate2Error(RuntimeError):
    """Gate 2 orchestrator failed closed."""


@dataclass
class SlotResult:
    outcome: str
    request_count: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


class SlotExecutor(Protocol):
    def execute(self, slot: Slot, *, attempt: int, run_id: str) -> SlotResult:
        ...


class ScriptedSlotExecutor:
    """Deterministic fake host execution. No Docker, no API."""

    def __init__(
        self,
        script: Mapping[tuple[str, str, int], tuple[str, ...]] | None = None,
    ) -> None:
        self.script = dict(script or {})

    def execute(self, slot: Slot, *, attempt: int, run_id: str) -> SlotResult:
        del run_id
        key = (slot.task_id, slot.side.value, slot.round_index)
        outcomes = self.script.get(key, (RunOutcome.COMPLETED.value,))
        index = min(max(attempt, 1) - 1, len(outcomes) - 1)
        return SlotResult(outcome=outcomes[index], extra={"executor": "scripted"})


class DockerNotAuthorizedExecutor:
    def execute(self, slot: Slot, *, attempt: int, run_id: str) -> SlotResult:
        del slot, attempt, run_id
        raise Gate2Error("Docker execution is not authorized")


class TerminalBenchSlotExecutor:
    """One Harbor slot through adapters/runner/results. Not a v7 campaign."""

    def __init__(
        self,
        *,
        common_root: Path,
        authorize_docker: bool = False,
        config: RuntimeConfig | None = None,
        ledger: PersistentBudgetLedger | None = None,
        api_key: str | None = None,
        identity=None,
        catalog: FrozenCanaryCatalog | None = None,
        binaries: Mapping[Side, BinaryManifest] | None = None,
        work_root: Path | None = None,
        paths: RepoPaths | None = None,
        transport: _UrllibTransport | None = None,
        counter: DockerCounter | None = None,
        lock_guard: HeavyLockGuard | None = None,
        lease: HeavyLockLease | None = None,
        materializer=None,
    ) -> None:
        if authorize_docker:
            if api_key is None or ledger is None:
                raise Gate2Error("authorized Docker execution needs a ledger and in-memory key")
            if counter is None or lock_guard is None or lease is None:
                raise Gate2Error("authorized Docker execution needs the heavy lock and Docker counter")
        self._common_root = common_root
        self._paths = paths or RepoPaths.discover(Path.cwd())
        self.authorize_docker = authorize_docker
        self._config = config
        self._ledger = ledger
        self._api_key = api_key
        self._identity = identity
        self._catalog = catalog
        self._binaries = dict(binaries or {})
        self._work_root = work_root
        self._transport = transport
        self._counter = counter
        self._lock_guard = lock_guard
        self._lease = lease
        self._materializer = materializer
        self._provider_identity: dict[str, str] | None = None

    def execute(self, slot: Slot, *, attempt: int, run_id: str) -> SlotResult:
        request = self.build_request(slot, attempt=attempt, run_id=run_id)
        if not self.authorize_docker:
            raise Gate2Error("Docker execution is not authorized")
        return self._run_live(request, slot=slot, attempt=attempt, run_id=run_id)

    def build_request(self, slot: Slot, *, attempt: int, run_id: str) -> TerminalBenchRequest:
        """Frozen-task Terminal-Bench request. No campaign id, no preflight receipt."""

        del attempt
        task = self._task(slot.task_id)
        binary = self._binary(slot.side)
        seccomp = self._seccomp()
        work_root = self._work_root or scratch_root(self._common_root) / "multi-m5-gate2-work"
        work_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        return TerminalBenchRequest(
            side=slot.side,
            batch_id=BATCH_ID,
            binary=binary,
            product=slot.product,
            image_digest=task.image_digest,
            source_checkout=str(self._common_root / _SOURCE_RELPATH),
            staging_root=str(work_root / "staging"),
            docker_task_id=run_id,
            memory_bytes=task.memory_mb * 1024**2,
            memory_swap_bytes=(task.memory_mb + 1024) * 1024**2,
            pids_limit=task.pids_limit,
            provider_transport_base_url="http://host.docker.internal:9/v1",
            timeout_seconds=task.timeout_seconds,
            max_retries=0,
            budget_usd=float(GATE2_RUN_CAP_USD),
            frozen_task=task,
            require_container_metrics=True,
            seccomp_profile_path=str(seccomp) if seccomp is not None else None,
            seccomp_profile_source_sha256=(
                _SECCOMP_SOURCE_SHA256 if seccomp is not None else None
            ),
            seccomp_profile_effective_sha256=(
                _SECCOMP_EFFECTIVE_SHA256 if seccomp is not None else None
            ),
            # The attribution diagnostic is the one slot that runs Multi with the
            # team layer off. Everything else about the run is unchanged.
            team_state_enabled=slot.kind != DIAGNOSTIC_SLOT_KIND,
        )

    def _run_live(
        self,
        request: TerminalBenchRequest,
        *,
        slot: Slot,
        attempt: int,
        run_id: str,
    ) -> SlotResult:
        del slot, attempt
        assert self._ledger is not None and self._api_key is not None
        contract = load_nondegradation_contract()
        config = self._config or load_runtime_config(self._paths)
        # Resolved from the lock's own model, not the host-wide `main_model`
        # alias, so M-5 running on terra cannot rewrite the frozen provider
        # identity of the sol campaigns that share this machine config.
        provider = config.paid_provider_projection(model_id=contract.root_model)
        # Binds the endpoint, effort, retry policy and every rate to the lock.
        # The proxy meters the $120 batch with these numbers, so the mutable
        # `rondo.local.toml` must not be able to change what the cap buys.
        self._provider_identity = require_frozen_provider(
            provider, effort=contract.root_effort, contract=contract
        )
        metadata_path = (
            scratch_root(self._common_root) / "multi-m5-gate2-meta" / f"{run_id}.json"
        )
        metadata_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            proxy = LoopbackResponsesProxy(
                upstream_base_url=provider.base_url,
                api_key=self._api_key,
                # Request 81 must never leave the process; classifying it after
                # the fact still bills money and still sends workspace content.
                ledger=RequestCappedLedger(
                    self._ledger,
                    max_requests_per_run=contract.max_requests_per_run,
                ),
                run_id=run_id,
                metadata_path=metadata_path,
                main_model=provider.main_model,
                main_effort=provider.main_effort,
                main_pricing=provider.main_pricing,
                guardian_model=provider.guardian_model,
                guardian_pricing=provider.guardian_pricing,
                guardian_effort=provider.guardian_effort,
                max_attempts=provider.max_attempts,
                retry_backoff_seconds=provider.retry_backoff_seconds,
                unbilled_retry_statuses=provider.unbilled_retry_statuses,
                request_reservation_usd=GATE2_REQUEST_RESERVATION_USD,
                run_cap_usd=GATE2_RUN_CAP_USD,
                timeout_seconds=FORWARD_TIMEOUT_SECONDS,
                # Root and its members are concurrent by design.
                allow_concurrent_main=True,
                _transport=self._transport,
            )
            with proxy:
                projected = replace(
                    request, provider_transport_base_url=proxy.docker_base_url
                )
                prepared = prepare_terminal_bench_run(
                    config,
                    projected,
                    materializer=self._materializer,
                )
                harbor = asyncio.run(self._harbor(prepared, proxy.downstream_api_key))
            parsed = parse_single_task_result(
                harbor.trial_dir,
                host_returncode=harbor.returncode,
                expected_task_id=prepared.spec.task_id,
            )
        except BudgetStopped:
            raise
        except DockerResourceStop:
            # The 80 GiB floor and the 60 GB growth ceiling are batch-wide stop
            # lines from the authorization. Retrying the slot would keep running
            # containers past a limit the user set, so this must not become a
            # plain infra failure.
            raise
        except (
            TerminalBenchRunError,
            HarborResultError,
            ApiBudgetProxyError,
            OSError,
            RuntimeError,
        ) as exc:
            raise Gate2Error(str(exc)) from exc
        return self._slot_result(parsed, run_id, docker_evidence=harbor.docker_evidence)

    def _slot_result(self, parsed, run_id: str, *, docker_evidence=None) -> SlotResult:
        """One Harbor trial as a slot result.

        The request count is read back from the ledger: a Terminal-Bench slot is
        one host process making many model calls, so a hardcoded 1 would both
        misstate the archive row and leave the frozen `max_requests_per_run`
        cap dead.
        """

        assert self._ledger is not None
        extra: dict[str, Any] = {
            "executor": "terminal_bench",
            "task_outcome": parsed.task_outcome,
            "reward": parsed.reward,
            "duration_seconds": parsed.duration_seconds,
        }
        if self._provider_identity is not None:
            extra["provider_identity"] = dict(self._provider_identity)
        extra.update(harness_identity(self._paths.worktree_root))
        evidence = docker_summary(docker_evidence)
        if evidence is not None:
            extra["docker_evidence"] = evidence
        return SlotResult(
            outcome=_slot_outcome(parsed),
            request_count=run_request_count(self._ledger, run_id),
            extra=extra,
        )

    async def _harbor(self, prepared: PreparedTerminalBenchRun, downstream_key: str):
        assert self._counter is not None
        assert self._lock_guard is not None
        assert self._lease is not None
        executor = DockerSupervisedHostHarborExecutor(
            counter=self._counter,
            lock_guard=self._lock_guard,
            lease=self._lease,
        )
        backend = InjectedHostHarborBackend(
            executor,
            getenv=lambda name: (
                downstream_key if name == prepared.spec.provider.api_key_env else None
            ),
        )
        return await UnifiedTerminalBenchRunner(backend).run(prepared)

    def _task(self, task_id: str) -> FrozenTask:
        catalog = self._catalog or load_successor_canary_catalog(self._paths)
        return catalog.task(task_id)

    def _binary(self, side: Side) -> BinaryManifest:
        if side in self._binaries:
            return self._binaries[side]
        identity = self._identity or load_runtime_identity(
            require_frozen=True, common_root=self._common_root
        )
        return load_side_manifest(identity, side, common_root=self._common_root)

    def _seccomp(self) -> Path | None:
        profile = self._paths.worktree_root / _SECCOMP_RELPATH
        if profile.is_symlink() or not profile.is_file():
            raise Gate2Error("tracked Terminal-Bench seccomp profile is missing")
        digest = hashlib.sha256(profile.read_bytes()).hexdigest()
        if digest != _SECCOMP_SOURCE_SHA256:
            raise Gate2Error("tracked Terminal-Bench seccomp profile digest differs")
        return profile


def run_gate2_real(
    *,
    authorization: PaidAuthorization,
    api_key: str,
    ledger: PersistentBudgetLedger,
    common_root: Path,
    counter: DockerCounter,
    lock_guard: HeavyLockGuard,
    lease: HeavyLockLease,
    config: RuntimeConfig | None = None,
    persist: bool = True,
    archive_file=None,
    transport: _UrllibTransport | None = None,
) -> dict[str, Any]:
    """Paid gate 2. Explicit real_api evidence. No v7 campaign."""

    authorization.require_api_and_docker()
    if not isinstance(api_key, str) or not api_key or "\r" in api_key or "\n" in api_key:
        raise Gate2Error("the in-memory provider key is invalid")
    executor = TerminalBenchSlotExecutor(
        common_root=common_root,
        authorize_docker=True,
        config=config,
        ledger=ledger,
        api_key=api_key,
        transport=transport,
        counter=counter,
        lock_guard=lock_guard,
        lease=lease,
    )
    return run_light_interleaved(
        executor=executor,
        common_root=common_root,
        ledger=ledger,
        persist=persist,
        archive_file=archive_file,
        charge_fake_usage=False,
        evidence_kind="real_api",
    )


def _is_request_cap_stop(ledger, run_id: str) -> bool:
    return ledger is not None and run_stop_reason(ledger, run_id) == REQUEST_LIMIT_STOP_REASON


def docker_summary(evidence) -> dict[str, Any] | None:
    """Persist the before/after Docker facts the authorization asked us to keep.

    A bounded projection on purpose: enough to audit the 40 GB warning, the
    60 GB stop line, the host free-space floor and that cleanup verified empty,
    without dumping whole `docker system df` payloads into every archive row.
    """

    if evidence is None:
        return None
    vhdx = getattr(evidence, "desktop_vhdx", None)
    summary: dict[str, Any] = {
        "returncode": getattr(evidence, "returncode", None),
        "warnings": list(getattr(evidence, "warnings", ()) or ()),
        **_stop_thresholds(),
        "samples": _sample_rows(getattr(evidence, "samples", ())),
    }
    if vhdx is not None:
        summary["desktop_vhdx"] = {
            "baseline_bytes": vhdx.baseline_bytes,
            "peak_bytes": vhdx.peak_bytes,
            "final_bytes": vhdx.final_bytes,
            "peak_growth_bytes": vhdx.peak_growth_bytes,
        }
    identity = getattr(evidence, "image_identity", None)
    if identity is not None:
        summary["image_reference"] = getattr(identity, "image_reference", None)
        summary["image_id"] = getattr(identity, "image_id", None)
    return summary


def docker_stop_summary(exc: DockerResourceStop) -> dict[str, Any]:
    """Evidence carried by a capacity stop.

    The moment a stop line is crossed is exactly when the samples matter most,
    so the exception's own readings are archived rather than reduced to a
    message string.
    """

    return {
        "reason": getattr(exc, "reason", str(exc)),
        "failed_probe": getattr(exc, "failed_probe", None),
        **_stop_thresholds(),
        "samples": _sample_rows(getattr(exc, "samples", ())),
    }


def _stop_thresholds() -> dict[str, int]:
    return {
        "growth_warn_bytes": DOCKER_GROWTH_WARN_BYTES,
        "growth_stop_bytes": DOCKER_GROWTH_STOP_BYTES,
        "data_root_free_stop_bytes": DATA_ROOT_FREE_STOP_BYTES,
    }


def _sample_rows(samples) -> list[dict[str, Any]]:
    return [
        {
            "phase": sample.phase,
            "docker_total_bytes": sample.docker_total_bytes,
            "docker_growth_bytes": sample.docker_growth_bytes,
            "task_growth_bytes": sample.task_growth_bytes,
            "docker_desktop_vhdx_bytes": sample.docker_desktop_vhdx_bytes,
            "docker_desktop_vhdx_growth_bytes": sample.docker_desktop_vhdx_growth_bytes,
            "data_root": sample.data_root,
            "data_root_filesystem_free_bytes": sample.data_root_filesystem_free_bytes,
        }
        for sample in samples or ()
    ]


def _slot_outcome(parsed) -> str:
    if parsed.outcome is RunOutcome.BUDGET_STOPPED:
        return RunOutcome.BUDGET_STOPPED.value
    if parsed.outcome is RunOutcome.COMPLETED and parsed.task_outcome == "pass":
        return RunOutcome.COMPLETED.value
    if parsed.outcome in {RunOutcome.COMPLETED, RunOutcome.AGENT_FAILED}:
        return RunOutcome.AGENT_FAILED.value
    return RunOutcome.INFRA_FAILED.value


def run_light_interleaved(
    *,
    executor: SlotExecutor,
    common_root,
    ledger: PersistentBudgetLedger | None = None,
    persist: bool = True,
    archive_file=None,
    charge_fake_usage: bool = False,
    identity=None,
    contract=None,
    evidence_kind: str = "fake",
) -> dict[str, Any]:
    """Walk frozen base slots, then conditional extras. Infra is not effective."""

    if evidence_kind not in {"fake", "loopback", "real_api"}:
        raise Gate2Error("gate 2 evidence kind is not an M-5 partition")
    if evidence_kind == "real_api" and not isinstance(executor, TerminalBenchSlotExecutor):
        raise Gate2Error("only the Terminal-Bench slot executor can produce real_api evidence")
    if evidence_kind != "real_api" and isinstance(executor, TerminalBenchSlotExecutor):
        raise Gate2Error("the Terminal-Bench executor cannot write fake evidence")
    if evidence_kind == "real_api" and isinstance(
        executor, (ScriptedSlotExecutor, DockerNotAuthorizedExecutor)
    ):
        raise Gate2Error("a scripted executor cannot produce real_api evidence")
    loaded = contract or load_nondegradation_contract()
    # A paid row carries both sides' binary identity. Check the bundle is really
    # frozen on disk before the first slot, not after burning the infra budget.
    runtime = identity or load_runtime_identity(
        require_frozen=evidence_kind == "real_api",
        common_root=Path(common_root),
    )
    pricing = phase_b_pricing(loaded) if charge_fake_usage else None
    records: list[dict[str, Any]] = []
    infra_used = 0
    effective = 0
    stopped = False
    stop_reason: str | None = None

    def run_slot(slot: Slot) -> list[dict[str, Any]]:
        """Every attempt on this slot, in order. A retried infra failure stays
        on the record: it must be auditable that the slot was re-run, and the
        infra rows are exactly what proves they were not counted as effective."""

        nonlocal infra_used, effective, stopped, stop_reason
        produced: list[dict[str, Any]] = []

        def emit(**kwargs: Any) -> list[dict[str, Any]]:
            produced.append(
                _record_for(slot, runtime, evidence_kind=evidence_kind, **kwargs)
            )
            return produced

        # The attribution diagnostic is evidence about *why* a task degraded, not
        # another observation of whether it did. It never counts as effective and
        # never draws on the effective-run budget, but it does share the dollars,
        # the infra attempts and every stop line.
        is_diagnostic = slot.kind == DIAGNOSTIC_SLOT_KIND

        for attempt in range(1, loaded.max_slot_attempts + 1):
            if stopped:
                return emit(
                    outcome=RunOutcome.BUDGET_STOPPED.value,
                    counts_as_effective=False,
                    extra={"stop_reason": stop_reason, "attempt": attempt},
                )
            if not is_diagnostic and effective >= loaded.max_effective_runs:
                return emit(
                    outcome="uncertain",
                    counts_as_effective=False,
                    extra={"reason": "max_effective_runs", "attempt": attempt},
                )
            run_id = _run_id(slot, attempt)
            if ledger is not None:
                try:
                    cap = GATE2_RUN_CAP_USD if evidence_kind == "real_api" else None
                    ledger.ensure_run(run_id, cap_usd=cap)
                except BudgetStopped as exc:
                    stopped = True
                    stop_reason = str(exc)
                    return emit(
                        outcome=RunOutcome.BUDGET_STOPPED.value,
                        counts_as_effective=False,
                        extra={"stop_reason": stop_reason, "attempt": attempt},
                    )
            try:
                result = executor.execute(slot, attempt=attempt, run_id=run_id)
            except DockerResourceStop as exc:
                # A host capacity stop line. Ends the batch, never a retry.
                stopped = True
                stop_reason = "docker_resource_stop"
                return emit(
                    outcome=RunOutcome.INFRA_FAILED.value,
                    counts_as_effective=False,
                    extra={
                        "stop_reason": stop_reason,
                        "error": str(exc),
                        "attempt": attempt,
                        "docker_evidence": docker_stop_summary(exc),
                    },
                )
            except BudgetStopped as exc:
                # The per-run request cap only ends this slot; dollars are shared
                # across the batch and end everything.
                if _is_request_cap_stop(ledger, run_id):
                    infra_used += 1
                    emit(
                        outcome=RunOutcome.INFRA_FAILED.value,
                        counts_as_effective=False,
                        extra={
                            "stop_reason": REQUEST_LIMIT_STOP_REASON,
                            "error": str(exc),
                            "attempt": attempt,
                            "infra_used": infra_used,
                        },
                    )
                    if infra_used >= loaded.max_infra_attempts_total:
                        stopped = True
                        stop_reason = "max_infra_attempts_total"
                        return produced
                    if attempt == loaded.max_slot_attempts:
                        return produced
                    continue
                stopped = True
                stop_reason = str(exc)
                return emit(
                    outcome=RunOutcome.BUDGET_STOPPED.value,
                    counts_as_effective=False,
                    extra={"stop_reason": stop_reason, "attempt": attempt},
                )
            except Gate2Error as exc:
                infra_used += 1
                emit(
                    outcome=RunOutcome.INFRA_FAILED.value,
                    counts_as_effective=False,
                    extra={"error": str(exc), "attempt": attempt, "infra_used": infra_used},
                )
                if infra_used >= loaded.max_infra_attempts_total:
                    stopped = True
                    stop_reason = "max_infra_attempts_total"
                    return produced
                if attempt == loaded.max_slot_attempts:
                    return produced
                continue
            if ledger is not None:
                # The proxy stops an exhausted run in-band with HTTP 429, so the
                # agent just looks like it gave up. Counting that as an effective
                # "Multi incomplete" would feed the degradation verdict a result
                # the budget produced, and Multi is the pricier side.
                exhausted = run_stop_reason(ledger, run_id)
                if exhausted == REQUEST_LIMIT_STOP_REASON:
                    # Per-run cap: this slot is spent, the batch is not. The next
                    # attempt gets a fresh run id and a fresh request budget.
                    infra_used += 1
                    emit(
                        outcome=RunOutcome.INFRA_FAILED.value,
                        counts_as_effective=False,
                        extra={
                            **result.extra,
                            "stop_reason": exhausted,
                            "reason": "max_requests_per_run",
                            "attempt": attempt,
                            "infra_used": infra_used,
                            "request_count": result.request_count,
                        },
                    )
                    if infra_used >= loaded.max_infra_attempts_total:
                        stopped = True
                        stop_reason = "max_infra_attempts_total"
                        return produced
                    if attempt == loaded.max_slot_attempts:
                        return produced
                    continue
                if exhausted is not None:
                    stopped = True
                    stop_reason = exhausted
                    return emit(
                        outcome=RunOutcome.BUDGET_STOPPED.value,
                        counts_as_effective=False,
                        extra={**result.extra, "stop_reason": exhausted, "attempt": attempt},
                    )
            if result.request_count > loaded.max_requests_per_run:
                result = SlotResult(
                    outcome=RunOutcome.INFRA_FAILED.value,
                    request_count=result.request_count,
                    extra={**result.extra, "reason": "max_requests_per_run"},
                )
            if result.outcome == RunOutcome.INFRA_FAILED.value:
                infra_used += 1
                emit(
                    outcome=result.outcome,
                    counts_as_effective=False,
                    extra={**result.extra, "attempt": attempt, "infra_used": infra_used},
                )
                if infra_used >= loaded.max_infra_attempts_total:
                    stopped = True
                    stop_reason = "max_infra_attempts_total"
                    return produced
                if attempt == loaded.max_slot_attempts:
                    return produced
                continue
            billable = result.outcome != RunOutcome.BUDGET_STOPPED.value
            counts = billable and not is_diagnostic
            if billable and ledger is not None and charge_fake_usage and pricing is not None:
                try:
                    _charge(ledger, run_id, attempt, pricing)
                except BudgetStopped as exc:
                    stopped = True
                    stop_reason = str(exc)
                    return emit(
                        outcome=RunOutcome.BUDGET_STOPPED.value,
                        counts_as_effective=False,
                        extra={"stop_reason": stop_reason, "attempt": attempt},
                    )
            if counts:
                effective += 1
            return emit(
                outcome=result.outcome,
                counts_as_effective=counts,
                extra={**result.extra, "attempt": attempt, "request_count": result.request_count},
            )
        return produced

    for slot in base_slots(loaded):
        for record in run_slot(slot):
            records.append(record)
            if persist:
                persist_archive_record(record, common_root=common_root, path=archive_file)
        if stopped:
            break

    first_round: dict[str, dict[str, str]] = {}
    for record in records:
        if record.get("counts_as_effective") is not True:
            continue
        task_id = str(record["task_id"])
        key = (
            Product.RONDO_MULTI.value
            if record.get("product") == Product.RONDO_MULTI.value
            else Side.CODEX.value
        )
        if record.get("round_index") != 1:
            continue
        first_round.setdefault(task_id, {})[key] = str(record["outcome"])

    extras: tuple[Slot, ...] = ()
    if not stopped:
        extras = conditional_slots(loaded, first_round)
        for slot in extras:
            for record in run_slot(slot):
                records.append(record)
                if persist:
                    persist_archive_record(record, common_root=common_root, path=archive_file)
            if stopped:
                break

    grouped = outcomes_by_task(records)
    verdicts = {
        task_id: degradation_on_task(observations)
        for task_id, observations in grouped.items()
    }

    # Only now, with the verdicts settled, can the lock's
    # `diagnostic_v2_on_team_state_off` slot exist: the contract requires it on a
    # degraded task and forbids pre-running it. It is attribution evidence, so it
    # cannot change a verdict -- but leaving it unrun would make an honest
    # "the team layer caused this" impossible to state.
    diagnostics: tuple[Slot, ...] = ()
    if not stopped:
        diagnostics = diagnostic_slots(loaded, verdicts)
        for slot in diagnostics:
            for record in run_slot(slot):
                records.append(record)
                if persist:
                    persist_archive_record(record, common_root=common_root, path=archive_file)
            if stopped:
                break

    return {
        "records": records,
        "verdicts": verdicts,
        "effective_runs": effective,
        "infra_used": infra_used,
        "conditional_slots": len(extras),
        "diagnostic_slots": len(diagnostics),
        "diagnostics": diagnostic_outcomes(records),
        "stopped": stopped,
        "stop_reason": stop_reason,
        "passed": gate2_passed(loaded, verdicts, stopped=stopped),
        "ledger_snapshot": None if ledger is None else ledger.snapshot(),
    }


def diagnostic_outcomes(records) -> dict[str, str]:
    """Per-task outcome of the team-state-off diagnostic, for attribution only.

    A `completed` here says the task passes with upstream V2 alone, so the team
    layer is implicated. Anything else says the degradation is not attributable
    to the team layer on this evidence. Neither changes the gate 2 verdict.
    """

    outcomes: dict[str, str] = {}
    for record in records:
        if record.get("slot_kind") != DIAGNOSTIC_SLOT_KIND:
            continue
        task_id = record.get("task_id")
        outcome = record.get("outcome")
        if isinstance(task_id, str) and isinstance(outcome, str):
            outcomes[task_id] = outcome
    return outcomes


def gate2_passed(contract, verdicts: Mapping[str, str], *, stopped: bool) -> bool:
    """Gate 2 passes only on complete evidence with no task degrading.

    Reporting success off `stopped` alone would exit 0 on a batch that found
    `stable_one_way_degradation`, or on one whose evidence never completed. Both
    are M-5 failures, so the shell has to see them as failures.
    """

    if stopped:
        return False
    if set(verdicts) != set(contract.tasks):
        return False
    return all(value == "no_stable_one_way_degradation" for value in verdicts.values())


def _charge(
    ledger: PersistentBudgetLedger,
    run_id: str,
    attempt: int,
    pricing,
) -> None:
    request_id = f"{run_id}-req-{attempt}"
    amount = price_usage(_FAKE_USAGE, pricing=pricing)
    ledger.reserve(run_id, request_id, amount)
    ledger.begin_attempt(run_id, request_id, max_attempts=5)
    ledger.settle(run_id, request_id, _FAKE_USAGE, pricing=pricing)


def _record_for(
    slot: Slot,
    runtime,
    *,
    outcome: str,
    counts_as_effective: bool,
    extra: Mapping[str, Any],
    evidence_kind: str = "fake",
) -> dict[str, Any]:
    kind = evidence_kind
    if slot.side is Side.RONDO:
        source_commit = runtime.source_commit
        binary_sha256 = runtime.codex_sha256
    else:
        source_commit = str(runtime.baseline["source_commit"])
        binary_sha256 = str(runtime.baseline["codex_sha256"])
    # The fairness contract requires both sides' binary identity on every row.
    # A placeholder digest would make an unfrozen bundle look comparable.
    if not binary_sha256:
        raise Gate2Error("gate 2 needs a frozen binary digest for both sides")
    return archive_record(
        evidence_kind=kind,
        gate=2,
        lock_id="multi-m5-nondegradation-v1",
        side=slot.side,
        product=slot.product,
        source_commit=source_commit,
        binary_sha256=binary_sha256,
        outcome=outcome,
        counts_as_effective=counts_as_effective,
        # Derived from the slot rather than passed in, so a diagnostic row can
        # never report the team layer as on while the command switched it off.
        team_state=slot.kind != DIAGNOSTIC_SLOT_KIND,
        extra={
            "task_id": slot.task_id,
            "round_index": slot.round_index,
            "slot_kind": slot.kind,
            **dict(extra),
        },
    )


def _run_id(slot: Slot, attempt: int) -> str:
    task = slot.task_id.rsplit("/", 1)[-1]
    side = slot.side.value
    return f"m5-g2-{task}-{side}-r{slot.round_index}-a{attempt}"
