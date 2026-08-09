"""Budgeted, supervised Terminal-Bench live-run orchestration."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Mapping

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


@dataclass(frozen=True)
class EvidenceObservation:
    relative_path: str
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
    if harbor.returncode == 0 and not metadata_ready:
        raise TerminalBenchRunError("successful Harbor run lacks verified API metadata")
    if harbor.returncode == 0 and request.side is Side.RONDO and not evidence:
        raise TerminalBenchRunError("successful RONDO run lacks an aggregatable E_final bundle")
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
        _require_safe_regular_file(root, e_final_path)
        meta_path = e_final_path.with_name("meta.json")
        _require_safe_regular_file(root, meta_path)
        try:
            e_final = json.loads(e_final_path.read_text(encoding="utf-8"))
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise TerminalBenchRunError("Guardian evidence bundle is unreadable") from exc
        identity = policy_identity(e_final)
        if not identity.aggregatable or not isinstance(meta, dict):
            raise TerminalBenchRunError("Guardian evidence bundle is not aggregatable")
        model = meta.get("model")
        effort = meta.get("reasoning_effort")
        terminal_status = meta.get("terminal_status")
        if (
            meta.get("evidence") != "e_final"
            or model != "gpt-5.6-luna"
            or effort != "low"
            or not isinstance(terminal_status, str)
        ):
            raise TerminalBenchRunError("Guardian evidence metadata differs from the freeze")
        observations.append(
            EvidenceObservation(
                relative_path=e_final_path.relative_to(root).as_posix(),
                policy=identity,
                model=model,
                reasoning_effort=effort,
                terminal_status=terminal_status,
            )
        )
    return tuple(observations)


def _require_safe_regular_file(root: Path, path: Path) -> None:
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
    if not stat.S_ISREG(path.lstat().st_mode):
        raise TerminalBenchRunError("Guardian evidence file is not regular")
