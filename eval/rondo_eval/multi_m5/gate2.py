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
from ..docker_supervisor import DockerCounter, HeavyLockGuard, HeavyLockLease
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
from .archive import archive_record
from .budget import (
    BATCH_ID,
    GATE2_REQUEST_RESERVATION_USD,
    GATE2_RUN_CAP_USD,
    phase_b_pricing,
    run_stop_reason,
)
from .bundle import load_side_manifest
from .capture import FORWARD_TIMEOUT_SECONDS
from .load import load_nondegradation_contract, load_runtime_identity
from .paid import PaidAuthorization
from .schedule import Slot, base_slots, conditional_slots, degradation_on_task, outcomes_by_task
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
        config = self._config or load_runtime_config(self._paths)
        provider = config.paid_provider_projection()
        pricing = phase_b_pricing()
        if provider.main_model != pricing.model_id:
            raise Gate2Error("paid gate 2 model differs from the frozen price snapshot")
        metadata_path = (
            scratch_root(self._common_root) / "multi-m5-gate2-meta" / f"{run_id}.json"
        )
        metadata_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            proxy = LoopbackResponsesProxy(
                upstream_base_url=provider.base_url,
                api_key=self._api_key,
                ledger=self._ledger,
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
        except (
            TerminalBenchRunError,
            HarborResultError,
            ApiBudgetProxyError,
            OSError,
            RuntimeError,
        ) as exc:
            raise Gate2Error(str(exc)) from exc
        outcome = _slot_outcome(parsed)
        return SlotResult(
            outcome=outcome,
            request_count=1,
            extra={
                "executor": "terminal_bench",
                "task_outcome": parsed.task_outcome,
                "reward": parsed.reward,
                "duration_seconds": parsed.duration_seconds,
            },
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
    runtime = identity or load_runtime_identity(require_frozen=False)
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

        for attempt in range(1, loaded.max_slot_attempts + 1):
            if stopped:
                return emit(
                    outcome=RunOutcome.BUDGET_STOPPED.value,
                    counts_as_effective=False,
                    extra={"stop_reason": stop_reason, "attempt": attempt},
                )
            if effective >= loaded.max_effective_runs:
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
            except BudgetStopped as exc:
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
            counts = result.outcome != RunOutcome.BUDGET_STOPPED.value
            if counts and ledger is not None and charge_fake_usage and pricing is not None:
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
    return {
        "records": records,
        "verdicts": verdicts,
        "effective_runs": effective,
        "infra_used": infra_used,
        "conditional_slots": len(extras),
        "stopped": stopped,
        "stop_reason": stop_reason,
        "ledger_snapshot": None if ledger is None else ledger.snapshot(),
    }


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
