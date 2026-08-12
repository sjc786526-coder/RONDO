"""Budgeted, supervised Terminal-Bench live-run orchestration."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from ..api_budget_proxy import (
    ApiBudgetProxyError,
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    UPSTREAM_TIMEOUT_SECONDS,
    canonical_request_sha256,
    milestone_metadata_ready,
)
from ..config import RuntimeConfig
from ..contracts import Side
from ..docker_supervisor import DockerCounter, HeavyLockGuard, HeavyLockLease
from ..evidence import PolicyIdentity, policy_identity
from ..frozen_model_catalog import load_frozen_model_catalog
from .runner import (
    DockerSupervisedHostHarborExecutor,
    HostHarborResult,
    InjectedHostHarborBackend,
    PreparedTerminalBenchRun,
    TaskMaterializer,
    TerminalBenchRequest,
    TerminalBenchRunError,
    UnifiedTerminalBenchRunner,
    prepare_terminal_bench_run,
)
from .baseline import CampaignIdentity, CampaignSlotPlan
from .pair import PairIdentity
from .tasksets import FrozenTask


GUARDIAN_SOURCE_BASELINE = "rust-v0.147.0"
GUARDIAN_SOURCE_COMMIT = "be6e8eac029b183056b7e4402879f15d2c85f61b"
_MAX_GUARDIAN_EVIDENCE_BYTES = 8 * 1024 * 1024
_GUARDIAN_META_FIELDS = {
    "review_id",
    "guardian_source_baseline",
    "guardian_source_commit",
    "evidence",
    "decision",
    "terminal_status",
    "failure_reason",
    "attempt_count",
    "duration_ms",
    "guardian_thread_id",
    "model",
    "reasoning_effort",
    "token_usage",
    "time_to_first_token_ms",
}
_GUARDIAN_TERMINAL_COMBINATIONS = {
    ("approved", "approved", None),
    ("denied", "denied", None),
    ("aborted", "aborted", "cancelled"),
    ("denied", "timed_out", "timeout"),
    ("denied", "failed_closed", "prompt_build_error"),
    ("denied", "failed_closed", "session_error"),
    ("denied", "failed_closed", "parse_error"),
}


@dataclass(frozen=True)
class EvidenceObservation:
    relative_path: str
    review_id: str
    guardian_source_baseline: str
    guardian_source_commit: str
    policy: PolicyIdentity
    model: str
    reasoning_effort: str
    decision: str
    terminal_status: str
    failure_reason: str | None
    canonical_request_sha256: str


@dataclass(frozen=True)
class BudgetedTerminalBenchResult:
    prepared: PreparedTerminalBenchRun
    harbor: HostHarborResult
    budget_snapshot: Mapping[str, object]
    metadata_ready: bool
    evidence: tuple[EvidenceObservation, ...]
    redaction_secrets: tuple[str, ...] = field(repr=False)


async def run_budgeted_terminal_bench(
    config: RuntimeConfig,
    request: TerminalBenchRequest,
    *,
    api_key: str,
    ledger: PersistentBudgetLedger,
    metadata_path: Path,
    counter: DockerCounter,
    lock_guard: HeavyLockGuard,
    lease: HeavyLockLease,
    pair_identity: PairIdentity | None = None,
    campaign_identity: CampaignIdentity | None = None,
    campaign_slot: CampaignSlotPlan | None = None,
    campaign_task: FrozenTask | None = None,
    campaign_seccomp_profile: Path | None = None,
    materializer: TaskMaterializer | None = None,
) -> BudgetedTerminalBenchResult:
    """Run one side through the only paid path: the local budget proxy.

    The selected provider key remains in this host process. Harbor receives a random,
    short-lived placeholder key and the Docker bridge URL for the loopback
    proxy; direct upstream-provider transport is rejected by the runner.
    """

    if not isinstance(api_key, str) or not api_key or "\r" in api_key or "\n" in api_key:
        raise TerminalBenchRunError("the in-memory provider key is invalid")
    if (pair_identity is None) == (campaign_identity is None):
        raise TerminalBenchRunError("exactly one paid execution identity is required")
    provider = config.paid_provider_projection(request.provider_name)
    if campaign_identity is None:
        assert pair_identity is not None
        pair_identity.validate_selected_profile(provider)
        max_guardian_logical_requests = (
            pair_identity.require_selected_profile().max_guardian_logical_requests
        )
    else:
        if (
            campaign_slot is None
            or campaign_task is None
            or campaign_seccomp_profile is None
        ):
            raise TerminalBenchRunError("campaign execution projection is incomplete")
        campaign_identity.validate_provider(provider)
        max_guardian_logical_requests = (
            campaign_identity.max_guardian_logical_requests
        )
    proxy = LoopbackResponsesProxy(
        upstream_base_url=provider.base_url,
        api_key=api_key,
        ledger=ledger,
        run_id=request.docker_task_id,
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
        max_guardian_logical_requests=max_guardian_logical_requests,
        timeout_seconds=UPSTREAM_TIMEOUT_SECONDS,
    )
    with proxy:
        projected_request = replace(
            request,
            provider_transport_base_url=proxy.docker_base_url,
        )
        if request.side is Side.CODEX:
            catalog = load_frozen_model_catalog(
                config.paths.common_root,
                source_commit=request.binary.source_commit,
                main_model=provider.main_model,
                guardian_model=provider.guardian_model,
            )
            identity = campaign_identity or pair_identity
            assert identity is not None
            identity.validate_frozen_model_catalog(
                source_commit=catalog.source_commit,
                sha256=catalog.sha256,
                main_model=catalog.main_model,
                guardian_model=catalog.guardian_model,
            )
            catalog_path = metadata_path.with_name("frozen-model-catalog.json")
            catalog.write_private(catalog_path)
            projected_request = replace(
                projected_request,
                frozen_model_catalog_path=str(catalog_path),
                frozen_model_catalog_sha256=catalog.sha256,
                frozen_model_catalog_source_commit=catalog.source_commit,
            )
        prepared = prepare_terminal_bench_run(
            config,
            projected_request,
            materializer=materializer,
        )
        if campaign_identity is None:
            assert pair_identity is not None
            pair_identity.validate_prepared(prepared, mode="paid")
        else:
            assert campaign_slot is not None
            assert campaign_task is not None
            assert campaign_seccomp_profile is not None
            campaign_identity.validate_prepared(
                prepared,
                slot=campaign_slot,
                task=campaign_task,
                seccomp_profile=campaign_seccomp_profile,
            )
        executor = DockerSupervisedHostHarborExecutor(
            counter=counter,
            lock_guard=lock_guard,
            lease=lease,
        )
        backend = InjectedHostHarborBackend(
            executor,
            getenv=lambda name: (
                proxy.downstream_api_key
                if name == prepared.spec.provider.api_key_env
                else None
            ),
        )
        harbor = await UnifiedTerminalBenchRunner(backend).run(prepared)
        redaction_secrets = (api_key, proxy.downstream_api_key)

    metadata_ready = milestone_metadata_ready(metadata_path)
    evidence = (
        _collect_evidence(
            harbor.jobs_dir,
            expected_model=provider.guardian_model,
            expected_effort=provider.guardian_effort,
        )
        if request.side is Side.RONDO
        else ()
    )
    return BudgetedTerminalBenchResult(
        prepared=prepared,
        harbor=harbor,
        budget_snapshot=ledger.snapshot(),
        metadata_ready=metadata_ready,
        evidence=evidence,
        redaction_secrets=redaction_secrets,
    )


def _collect_evidence(
    jobs_dir: Path,
    *,
    expected_model: str,
    expected_effort: str,
) -> tuple[EvidenceObservation, ...]:
    try:
        root = jobs_dir.resolve(strict=True)
    except OSError:
        return ()
    if not root.is_dir() or root.is_symlink():
        return ()
    observations: list[EvidenceObservation] = []
    for e_final_path in sorted(root.glob("**/guardian-evidence/*/E_final.json")):
        observation, _e_final_bytes, _meta_bytes = load_guardian_evidence_bundle(
            root,
            e_final_path.relative_to(root).as_posix(),
            expected_model=expected_model,
            expected_effort=expected_effort,
        )
        observations.append(observation)
    return tuple(observations)


def load_guardian_evidence_bundle(
    jobs_dir: Path,
    relative_path: str,
    *,
    expected_model: str,
    expected_effort: str,
) -> tuple[EvidenceObservation, bytes, bytes]:
    """Read and fully revalidate one production Guardian evidence bundle."""

    try:
        root = jobs_dir.resolve(strict=True)
    except OSError as exc:
        raise TerminalBenchRunError("Guardian evidence root is unavailable") from exc
    relative = Path(relative_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or len(relative.parts) < 3
        or relative.parts[-3] != "guardian-evidence"
        or relative.parts[-1] != "E_final.json"
    ):
        raise TerminalBenchRunError("Guardian evidence relative path is invalid")
    review_id = relative.parts[-2]
    e_final_bytes = _read_safe_evidence_file(root, root / relative)
    meta_bytes = _read_safe_evidence_file(root, root / relative.with_name("meta.json"))
    try:
        e_final = json.loads(e_final_bytes.decode("utf-8"))
        meta = json.loads(meta_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TerminalBenchRunError("Guardian evidence bundle is unreadable") from exc
    try:
        identity = policy_identity(e_final)
        request_sha256 = canonical_request_sha256(e_final)
    except (ApiBudgetProxyError, TypeError, ValueError) as exc:
        raise TerminalBenchRunError("Guardian evidence policy identity is invalid") from exc
    if not identity.aggregatable or not isinstance(meta, dict):
        raise TerminalBenchRunError("Guardian evidence bundle is not aggregatable")
    _validate_guardian_meta(
        meta,
        review_id=review_id,
        expected_model=expected_model,
        expected_effort=expected_effort,
    )
    return (
        EvidenceObservation(
            relative_path=relative.as_posix(),
            review_id=review_id,
            guardian_source_baseline=GUARDIAN_SOURCE_BASELINE,
            guardian_source_commit=GUARDIAN_SOURCE_COMMIT,
            policy=identity,
            model=expected_model,
            reasoning_effort=expected_effort,
            decision=meta["decision"],
            terminal_status=meta["terminal_status"],
            failure_reason=meta["failure_reason"],
            canonical_request_sha256=request_sha256,
        ),
        e_final_bytes,
        meta_bytes,
    )


def _validate_guardian_meta(
    meta: Mapping[str, Any],
    *,
    review_id: str,
    expected_model: str,
    expected_effort: str,
) -> None:
    if set(meta) != _GUARDIAN_META_FIELDS:
        raise TerminalBenchRunError("Guardian evidence metadata schema differs from production")
    if (
        meta.get("review_id") != review_id
        or meta.get("guardian_source_baseline") != GUARDIAN_SOURCE_BASELINE
        or meta.get("guardian_source_commit") != GUARDIAN_SOURCE_COMMIT
        or meta.get("evidence") != "e_final"
        or meta.get("model") != expected_model
        or meta.get("reasoning_effort") != expected_effort
    ):
        raise TerminalBenchRunError("Guardian evidence metadata differs from the freeze")
    decision = meta.get("decision")
    terminal_status = meta.get("terminal_status")
    failure_reason = meta.get("failure_reason")
    if decision not in {"approved", "denied", "aborted"}:
        raise TerminalBenchRunError("Guardian evidence decision is invalid")
    if terminal_status not in {
        "approved",
        "denied",
        "aborted",
        "timed_out",
        "failed_closed",
    }:
        raise TerminalBenchRunError("Guardian evidence terminal status is invalid")
    if failure_reason not in {
        None,
        "timeout",
        "cancelled",
        "prompt_build_error",
        "session_error",
        "parse_error",
    }:
        raise TerminalBenchRunError("Guardian evidence failure reason is invalid")
    if (decision, terminal_status, failure_reason) not in _GUARDIAN_TERMINAL_COMBINATIONS:
        raise TerminalBenchRunError("Guardian evidence terminal fields are contradictory")
    for key in ("attempt_count", "duration_ms"):
        value = meta.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TerminalBenchRunError(f"Guardian evidence {key} is invalid")
    if meta["attempt_count"] < 1:
        raise TerminalBenchRunError("E_final evidence must record at least one attempt")
    thread_id = meta.get("guardian_thread_id")
    if thread_id is not None and (not isinstance(thread_id, str) or not thread_id):
        raise TerminalBenchRunError("Guardian evidence thread id is invalid")
    first_token = meta.get("time_to_first_token_ms")
    if first_token is not None and (
        isinstance(first_token, bool) or not isinstance(first_token, int) or first_token < 0
    ):
        raise TerminalBenchRunError("Guardian evidence first-token timing is invalid")
    usage = meta.get("token_usage")
    if usage is not None:
        expected = {
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
            "total_tokens",
        }
        if not isinstance(usage, dict) or set(usage) != expected:
            raise TerminalBenchRunError("Guardian evidence token usage is invalid")
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in usage.values()
        ):
            raise TerminalBenchRunError("Guardian evidence token usage is invalid")


def _read_safe_evidence_file(root: Path, path: Path) -> bytes:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise TerminalBenchRunError("Guardian evidence path escaped jobs_dir") from exc
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise TerminalBenchRunError("Guardian evidence path is unavailable") from exc
        if stat.S_ISLNK(mode):
            raise TerminalBenchRunError("Guardian evidence path contains a symlink")
    try:
        final_stat = path.stat()
    except OSError as exc:
        raise TerminalBenchRunError("Guardian evidence file is unavailable") from exc
    if not stat.S_ISREG(final_stat.st_mode) or final_stat.st_size > _MAX_GUARDIAN_EVIDENCE_BYTES:
        raise TerminalBenchRunError("Guardian evidence file is not regular")
    try:
        contents = path.read_bytes()
    except OSError as exc:
        raise TerminalBenchRunError("Guardian evidence file cannot be read") from exc
    if len(contents) != final_stat.st_size:
        raise TerminalBenchRunError("Guardian evidence file changed while being read")
    return contents
