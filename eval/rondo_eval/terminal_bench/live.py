"""Budgeted, supervised Terminal-Bench live-run orchestration."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from ..api_budget_proxy import (
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    milestone_metadata_ready,
)
from ..config import RuntimeConfig
from ..contracts import Side
from ..docker_supervisor import DockerCounter, HeavyLockGuard, HeavyLockLease
from ..evidence import PolicyIdentity, policy_identity
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


@dataclass(frozen=True)
class EvidenceObservation:
    relative_path: str
    review_id: str
    guardian_source_baseline: str
    guardian_source_commit: str
    policy: PolicyIdentity
    model: str
    reasoning_effort: str
    terminal_status: str


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
    materializer: TaskMaterializer | None = None,
) -> BudgetedTerminalBenchResult:
    """Run one side through the only paid path: the local budget proxy.

    The official key remains in this host process.  Harbor receives a random,
    short-lived placeholder key and the Docker bridge URL for the loopback
    proxy; direct official-provider transport is rejected by the runner.
    """

    if not isinstance(api_key, str) or not api_key or "\r" in api_key or "\n" in api_key:
        raise TerminalBenchRunError("the in-memory provider key is invalid")
    provider = config.provider(request.provider_name)
    upstream_base_url = provider.get("base_url")
    if not isinstance(upstream_base_url, str):
        raise TerminalBenchRunError("the configured provider base URL is invalid")
    proxy = LoopbackResponsesProxy(
        upstream_base_url=upstream_base_url,
        api_key=api_key,
        ledger=ledger,
        run_id=request.docker_task_id,
        metadata_path=metadata_path,
        timeout_seconds=float(request.timeout_seconds),
    )
    with proxy:
        prepared = prepare_terminal_bench_run(
            config,
            replace(request, provider_transport_base_url=proxy.docker_base_url),
            materializer=materializer,
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
    evidence = _collect_evidence(harbor.jobs_dir) if request.side is Side.RONDO else ()
    return BudgetedTerminalBenchResult(
        prepared=prepared,
        harbor=harbor,
        budget_snapshot=ledger.snapshot(),
        metadata_ready=metadata_ready,
        evidence=evidence,
        redaction_secrets=redaction_secrets,
    )


def _collect_evidence(jobs_dir: Path) -> tuple[EvidenceObservation, ...]:
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
        )
        observations.append(observation)
    return tuple(observations)


def load_guardian_evidence_bundle(
    jobs_dir: Path,
    relative_path: str,
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
    except (TypeError, ValueError) as exc:
        raise TerminalBenchRunError("Guardian evidence policy identity is invalid") from exc
    if not identity.aggregatable or not isinstance(meta, dict):
        raise TerminalBenchRunError("Guardian evidence bundle is not aggregatable")
    _validate_guardian_meta(meta, review_id=review_id)
    return (
        EvidenceObservation(
            relative_path=relative.as_posix(),
            review_id=review_id,
            guardian_source_baseline=GUARDIAN_SOURCE_BASELINE,
            guardian_source_commit=GUARDIAN_SOURCE_COMMIT,
            policy=identity,
            model="gpt-5.6-luna",
            reasoning_effort="low",
            terminal_status=meta["terminal_status"],
        ),
        e_final_bytes,
        meta_bytes,
    )


def _validate_guardian_meta(meta: Mapping[str, Any], *, review_id: str) -> None:
    if set(meta) != _GUARDIAN_META_FIELDS:
        raise TerminalBenchRunError("Guardian evidence metadata schema differs from production")
    if (
        meta.get("review_id") != review_id
        or meta.get("guardian_source_baseline") != GUARDIAN_SOURCE_BASELINE
        or meta.get("guardian_source_commit") != GUARDIAN_SOURCE_COMMIT
        or meta.get("evidence") != "e_final"
        or meta.get("model") != "gpt-5.6-luna"
        or meta.get("reasoning_effort") != "low"
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
