"""Resumable, body-free Plan 097 commissioning and formal engineering runs.

Each command produces one write-once receipt under the physical repository's
ignored ``eval-data/publication-critic/plan097`` namespace.  Runtime packets,
Responses bodies, rollout traces, and credentials stay in private temporary
directories and are removed before a receipt is committed.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time
from typing import Any

from ...api_budget_proxy import (
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    UsageEnvelope,
    maximum_usage_cost,
)
from ...config import (
    RepoPaths,
    load_allowlisted_secret_values,
    load_provider_secret,
    load_runtime_config,
)
from ...multi_m5.capture import CaptureProxy
from ...multi_m5.command import build_multi_exec_command
from ...multi_m5.loopback import LOOPBACK_BEARER, LOOPBACK_MODEL
from ...multi_m5.predicates import evaluate_collaboration
from ...multi_m5.rehearsal import CollaborationStub
from ...multi_m5.trace import find_trace_bundle, load_rollout_trace
from ..identity import sha256_file
from ..write_once import WriteOnceNamespace
from .cloud_budget_proxy import CloudBudgetProxy
from .contract import EngineeringContract, load_contract
from .producer_runtime import (
    INITIAL_SYNTHETIC_DRAFT,
    ProducerEvidenceError,
    build_producer_command,
    evaluate_producer_evidence,
    project_producer_attempts,
)
from .service_runtime import (
    LocalRuntime,
    RunningScorerService,
    RuntimeBinaries,
    start_cloud_service,
    start_local_service,
    write_packet,
)


RECEIPT_SCHEMA = "rondo-publication-critic-plan097-step-v1"
SUMMARY_SCHEMA = "rondo-publication-critic-plan097-engineering-result-v1"
_RUN_ID = re.compile(r"plan097-[a-z0-9][a-z0-9-]{0,79}\Z")
_PHASES = {"commissioning", "formal"}
_BACKENDS = {"local", "cloud"}
_PRODUCER_BATCH_ID = "plan097-producer-terra-v6"
_PRODUCER_LEDGER_NAME = "producer-terra-v6-ledger.json"
_PRIOR_PRODUCER_LEDGERS = (
    ("plan097-producer-v1", "producer-ledger.json"),
    ("plan097-producer-terra-v2", "producer-terra-ledger.json"),
    ("plan097-producer-terra-v3", "producer-terra-v3-ledger.json"),
    ("plan097-producer-terra-v4", "producer-terra-v4-ledger.json"),
    ("plan097-producer-terra-v5", "producer-terra-v5-ledger.json"),
)
_PRODUCER_MAX_RUNS = 4
_PRODUCER_RUN_CAP_USD = Decimal("2.4")
_PRODUCER_TOTAL_CAP_USD = Decimal("19") / Decimal("7.5")
_CLOUD_LEDGER_NAME = "cloud-scorer-v2-ledger.json"
_PRIOR_CLOUD_LEDGER_NAME = "cloud-scorer-ledger.json"
_PRIOR_CLOUD_LEDGER_CAP_RMB = Decimal("12")
_CONTROLLED_FILTER = "test(process_tests)"
_OFF_FINDING = "A bounded synthetic migration leaves one report column unresolved."
_MAX_RECEIPT_BYTES = 1024 * 1024


class CampaignError(RuntimeError):
    """Stable body-free Plan 097 campaign failure."""


@dataclass(frozen=True)
class CampaignPaths:
    repos: RepoPaths
    runtime_root: Path
    binaries: RuntimeBinaries
    controlled_service: Path
    local: LocalRuntime

    @classmethod
    def discover(cls, start: Path) -> "CampaignPaths":
        repos = RepoPaths.discover(start)
        runtime_root = (
            repos.common_root / "eval-data/publication-critic/plan097"
        )
        target = repos.common_root / ".codex/cargo-target/rondo-multi/debug"
        binaries = RuntimeBinaries(
            codex=target / "codex",
            real_service=target / "codex-publication-critic-real-service",
            cloud_service=target / "codex-publication-critic-cloud-service",
            probe=target / "codex-publication-critic-probe",
        )
        local = LocalRuntime(
            python=(
                repos.common_root
                / "eval-data/envs/publication-critic-plan068/bin/python"
            ),
            snapshot=(
                repos.common_root
                / "eval-data/publication-critic/plan068/handoff/model"
            ),
            repo_root=repos.worktree_root,
            descriptor=(
                repos.worktree_root
                / "eval/locks/publication-critic-plan097-local-descriptor-v1.json"
            ),
        )
        return cls(
            repos=repos,
            runtime_root=runtime_root,
            binaries=binaries,
            controlled_service=target / "codex-publication-critic-service",
            local=local,
        )

    def validate(self) -> None:
        self.binaries.validate()
        self.local.validate()
        if (
            self.controlled_service.is_symlink()
            or not self.controlled_service.is_file()
            or not os.access(self.controlled_service, os.X_OK)
        ):
            raise CampaignError("controlled_service_invalid")
        expected_target = (
            self.repos.common_root / ".codex/cargo-target/rondo-multi"
        ).resolve()
        for binary in (
            self.binaries.codex,
            self.binaries.real_service,
            self.binaries.cloud_service,
            self.binaries.probe,
            self.controlled_service,
        ):
            try:
                binary.resolve().relative_to(expected_target)
            except (OSError, ValueError) as exc:
                raise CampaignError("binary_outside_shared_target") from exc

    def run_root(self, phase: str, run_id: str) -> Path:
        _require_phase(phase)
        _require_run_id(run_id)
        return self.runtime_root / phase / run_id


def preflight(start: Path, *, require_clean: bool) -> dict[str, Any]:
    paths = CampaignPaths.discover(start)
    contract = load_contract(paths.repos.worktree_root)
    paths.validate()
    source = _source_identity(paths.repos.worktree_root)
    if require_clean and source["dirty"]:
        raise CampaignError("source_not_clean")
    local_descriptor = contract.backends["local"].descriptor_document
    model_file = paths.local.snapshot / "model.safetensors"
    if (
        model_file.is_symlink()
        or not model_file.is_file()
        or model_file.stat().st_size != 3_441_189_792
        or local_descriptor["deployment_artifact_sha256"]
        != "117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9"
    ):
        raise CampaignError("local_model_identity_invalid")
    identities = paths.binaries.identities()
    identities.update(
        {
            "controlled_service_sha256": sha256_file(paths.controlled_service),
            "python_sha256": sha256_file(paths.local.python),
            "worker_sha256": sha256_file(
                paths.repos.worktree_root
                / "eval/rondo_eval/publication_critic/local_deployment/worker.py"
            ),
            "inference_sha256": sha256_file(
                paths.repos.worktree_root
                / "eval/rondo_eval/publication_critic/local_deployment/inference.py"
            ),
            "serving_lock_sha256": sha256_file(
                paths.repos.worktree_root
                / "eval/environments/publication-critic-plan068/uv.lock"
            ),
        }
    )
    return {
        "schema": RECEIPT_SCHEMA,
        "step": "preflight",
        "source": source,
        "contract_sha256": contract.contract_sha256,
        "backend_descriptor_sha256": {
            name: backend.descriptor_sha256
            for name, backend in contract.backends.items()
        },
        "runtime_identity": identities,
        "local_model": {
            "bytes": model_file.stat().st_size,
            "expected_sha256": local_descriptor["deployment_artifact_sha256"],
            "verified_by_worker_before_ready": True,
        },
        "shared_target": "physical-root/.codex/cargo-target/rondo-multi",
    }


def record_preflight(start: Path, *, phase: str, run_id: str) -> Path:
    paths = CampaignPaths.discover(start)
    value = preflight(start, require_clean=phase == "formal")
    return _write_receipt(paths, phase, run_id, "preflight.json", value)


def run_controlled_gates(start: Path, *, phase: str, run_id: str) -> Path:
    """Run the focused failure/cancel product tests through the build lock."""

    paths = CampaignPaths.discover(start)
    frozen = preflight(start, require_clean=phase == "formal")
    metrics = paths.runtime_root / "build-watchdog"
    metrics.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = [
        "just",
        "--justfile",
        str(paths.repos.worktree_root / "multidev/justfile"),
        "test",
        "-p",
        "codex-core",
        "-E",
        _CONTROLLED_FILTER,
    ]
    environment = dict(os.environ)
    environment["RONDO_BUILD_METRICS_DIR"] = str(metrics)
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=paths.repos.worktree_root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60 * 60,
        check=False,
    )
    elapsed = round((time.monotonic() - started) * 1000)
    if completed.returncode != 0:
        raise CampaignError("controlled_gates_failed")
    receipt = {
        **frozen,
        "step": "controlled_gates",
        "elapsed_ms": elapsed,
        "returncode": completed.returncode,
        "test_filter": _CONTROLLED_FILTER,
        "failure_fallback": "one_canonical_commit",
        "cancellation": "zero_commit",
        "evidence_kind": "controlled_rust_process_tests",
    }
    return _write_receipt(paths, phase, run_id, "controlled-gates.json", receipt)


def run_off_step(start: Path, *, phase: str, run_id: str) -> Path:
    """Run the current CLI without any Publication Critic configuration."""

    paths = CampaignPaths.discover(start)
    frozen = preflight(start, require_clean=phase == "formal")
    stub = CollaborationStub(finding_line=_OFF_FINDING)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(
        prefix="plan097-off-", dir=paths.runtime_root
    ) as temporary:
        private = Path(temporary)
        private.chmod(0o700)
        home = private / "home"
        workspace = private / "workspace"
        trace_root = private / "trace"
        home.mkdir(mode=0o700)
        workspace.mkdir(mode=0o700)
        trace_root.mkdir(mode=0o700)
        (workspace / "NOTES.md").write_text(
            f"Bound synthetic note for the OFF engineering path.\n{_OFF_FINDING}\n",
            encoding="utf-8",
        )
        auth = home / "auth.json"
        auth.write_text(
            json.dumps({"OPENAI_API_KEY": LOOPBACK_BEARER}, separators=(",", ":")),
            encoding="utf-8",
        )
        auth.chmod(0o600)
        with CaptureProxy(
            mode="stub",
            handler=stub,
            bearer=LOOPBACK_BEARER,
            model=LOOPBACK_MODEL,
            capture_path=None,
        ) as capture:
            command = build_multi_exec_command(
                paths.binaries.codex,
                base_url=capture.base_url,
                instruction="Complete the bounded synthetic collaboration task.",
                model=LOOPBACK_MODEL,
                effort="low",
                member_model=LOOPBACK_MODEL,
                member_effort="low",
            )
            if any("publication_critic" in argument for argument in command):
                raise CampaignError("off_path_contains_critic_configuration")
            completed = _run_owned_command(
                command,
                cwd=workspace,
                env=_codex_environment(
                    home=home,
                    trace_root=trace_root,
                    downstream_key=LOOPBACK_BEARER,
                ),
                timeout=180,
                timeout_code="off_process_timeout",
            )
            wire = capture.jsonl()
        trace = load_rollout_trace(find_trace_bundle(trace_root))
        verdict = evaluate_collaboration(
            {},
            workspace=workspace,
            finding_line=_OFF_FINDING,
            report_filename="TEAM_REPORT.md",
            max_members=1,
            jsonl=wire,
            trace=trace,
        )
        if completed.returncode != 0:
            raise CampaignError("off_process_failed")
        if stub.errors:
            raise CampaignError("off_stub_failed")
        if not stub.finished:
            raise CampaignError("off_stub_incomplete")
        if not verdict.passed:
            failed = "-".join(
                sorted(
                    key
                    for key, passed in verdict.predicates.items()
                    if passed is not True
                )
            )
            raise CampaignError(f"off_predicates_failed:{failed}")
        receipt = {
            **frozen,
            "step": "off",
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "returncode": completed.returncode,
            "publication_critic_configured": False,
            "scorer_process_started": False,
            "scorer_secret_loaded": False,
            "review_cycle_created": False,
            "team_state_contract": "unchanged",
            "canonical_flow_passed": True,
            "wire_request_count": len(capture.bodies),
            "trace_nested_call_count": len(trace.calls),
            "private_runtime_removed_before_receipt": True,
            "evidence_kind": "loopback_model_current_cli",
        }
    return _write_receipt(paths, phase, run_id, "off.json", receipt)


def run_backend_step(
    start: Path,
    *,
    phase: str,
    run_id: str,
    backend: str,
    producer_run_id: str,
    skip_direct_cases: bool = False,
) -> Path:
    """Run direct branch cases and one normal Producer through a real backend."""

    paths = CampaignPaths.discover(start)
    _require_backend(backend)
    _require_backend_mode(phase, skip_direct_cases)
    frozen = preflight(start, require_clean=phase == "formal")
    contract = load_contract(paths.repos.worktree_root)
    run_root = _existing_run_root(paths, phase, run_id)
    started = time.monotonic()
    if backend == "local":
        _require_watchdog_scope()
        service = start_local_service(
            binaries=paths.binaries,
            runtime=paths.local,
            call_timeout_ms=contract.backends[backend].client_call_timeout_ms,
            startup_timeout_ms=contract.backends[backend].client_startup_timeout_ms,
        )
        return _finish_backend_step(
            paths=paths,
            contract=contract,
            frozen=frozen,
            service=service,
            phase=phase,
            run_id=run_id,
            run_root=run_root,
            backend=backend,
            producer_run_id=producer_run_id,
            started=started,
            cloud_proxy=None,
            prior_cloud_budget=None,
            skip_direct_cases=skip_direct_cases,
        )

    runtime_config = load_runtime_config(paths.repos)
    provider = runtime_config.provider("deepseek")
    descriptor_provider = contract.backends["cloud"].descriptor_document["provider"]
    if (
        provider.get("api") != "chat_completions"
        or provider.get("model") != descriptor_provider["model"]
        or provider.get("base_url") != descriptor_provider["base_url"]
        or provider.get("api_key_env") != descriptor_provider["api_key_env"]
    ):
        raise CampaignError("cloud_provider_configuration_drift")
    secret_name = provider["api_key_env"]
    secret = load_allowlisted_secret_values(paths.repos, (secret_name,))[secret_name]
    prior_cloud_budget = _prior_cloud_budget_projection(paths)
    current_cloud_cap = (
        contract.budgets.cloud_scorer_rmb
        - prior_cloud_budget["conservative_charged_rmb"]
    )
    if current_cloud_cap < Decimal("1"):
        raise CampaignError("cloud_budget_derivation_invalid")
    cloud_proxy = CloudBudgetProxy(
        upstream_endpoint=provider["base_url"].rstrip("/") + "/chat/completions",
        upstream_api_key=secret,
        ledger_path=paths.runtime_root / f"budget/{_CLOUD_LEDGER_NAME}",
        cap_rmb=current_cloud_cap,
        timeout_seconds=90,
    )
    runtime_descriptor = run_root / "cloud-runtime-descriptor.json"
    with cloud_proxy:
        service = start_cloud_service(
            binaries=paths.binaries,
            tracked_descriptor=contract.backends[backend].descriptor_path,
            runtime_descriptor=runtime_descriptor,
            proxy_base_url=cloud_proxy.base_url,
            downstream_api_key=cloud_proxy.downstream_api_key,
            call_timeout_ms=contract.backends[backend].client_call_timeout_ms,
            startup_timeout_ms=contract.backends[backend].client_startup_timeout_ms,
        )
        return _finish_backend_step(
            paths=paths,
            contract=contract,
            frozen=frozen,
            service=service,
            phase=phase,
            run_id=run_id,
            run_root=run_root,
            backend=backend,
            producer_run_id=producer_run_id,
            started=started,
            cloud_proxy=cloud_proxy,
            prior_cloud_budget=prior_cloud_budget,
            skip_direct_cases=skip_direct_cases,
        )


def _finish_backend_step(
    *,
    paths: CampaignPaths,
    contract: EngineeringContract,
    frozen: Mapping[str, Any],
    service: RunningScorerService,
    phase: str,
    run_id: str,
    run_root: Path,
    backend: str,
    producer_run_id: str,
    started: float,
    cloud_proxy: CloudBudgetProxy | None,
    prior_cloud_budget: Mapping[str, Any] | None,
    skip_direct_cases: bool,
) -> Path:
    backend_contract = contract.backends[backend]
    direct: list[dict[str, Any]] = []
    producer: dict[str, Any]
    observation: dict[str, Any]
    diagnostics: tuple[str, ...]
    with tempfile.TemporaryDirectory(
        prefix=f"plan097-{backend}-packets-", dir=paths.runtime_root
    ) as temporary:
        packet_root = Path(temporary)
        packet_root.chmod(0o700)
        try:
            with service:
                ready = service.ready()
                if ready.get("result") != "ready":
                    raise CampaignError("backend_not_ready")
                if not skip_direct_cases:
                    for index, case in enumerate(
                        contract.commissioning_cases, start=1
                    ):
                        packet = packet_root / f"case-{index}.json"
                        write_packet(packet, case.packet)
                        result = service.review(packet)
                        verdict = result.get("result")
                        if verdict not in {"pass", "rewrite"}:
                            raise CampaignError("direct_verdict_invalid")
                        direct.append(
                            {
                                "case_id": case.case_id,
                                "expected_branch": case.expected_engineering_branch,
                                "observed_branch": verdict,
                                "matched": (
                                    verdict == case.expected_engineering_branch
                                ),
                            }
                        )
                    if {row["observed_branch"] for row in direct} != {
                        "pass",
                        "rewrite",
                    }:
                        raise CampaignError("direct_branch_coverage_incomplete")
                    if not all(row["matched"] for row in direct):
                        raise CampaignError("direct_case_expectation_mismatch")
                producer = _run_producer(
                    paths=paths,
                    contract=contract,
                    service=service,
                    backend=backend,
                    producer_run_id=producer_run_id,
                    metadata_path=(
                        run_root / f"{backend}-producer-budget-metadata.json"
                    ),
                )
                observation = {
                    "backend": service.observation.backend,
                    "descriptor_sha256": service.observation.descriptor_sha256,
                    "startup_elapsed_ms": service.observation.startup_elapsed_ms,
                    "ready_elapsed_ms": service.observation.ready_elapsed_ms,
                }
                diagnostics = service.diagnostic_codes
        finally:
            service.close()
    if service.process.poll() is None:
        raise CampaignError("service_process_not_reaped")
    cloud_budget = (
        _combined_cloud_budget_projection(
            contract,
            prior_cloud_budget,
            cloud_proxy.snapshot(),
        )
        if cloud_proxy is not None
        else None
    )
    if cloud_proxy is not None:
        # Linearization barrier: no paid scorer attempt may start after the
        # body-free receipt says this backend step is complete.
        cloud_proxy.close()
    receipt = {
        **dict(frozen),
        "step": (
            f"backend_{backend}_producer_only"
            if skip_direct_cases
            else f"backend_{backend}"
        ),
        "mode": "producer_only" if skip_direct_cases else "full",
        "backend": backend,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "service": {
            **observation,
            "process_reaped": True,
            "diagnostic_codes": list(diagnostics),
        },
        "direct_cases": direct,
        "direct_branch_coverage": [] if skip_direct_cases else ["pass", "rewrite"],
        "producer": producer,
        "cloud_scorer_budget": cloud_budget,
        "private_packets_and_traces_removed_before_receipt": True,
        "conclusion_boundary": dict(contract.conclusion_boundary),
    }
    return _write_receipt(
        paths,
        phase,
        run_id,
        (
            f"backend-{backend}-producer-only.json"
            if skip_direct_cases
            else f"backend-{backend}.json"
        ),
        receipt,
    )


def _run_producer(
    *,
    paths: CampaignPaths,
    contract: EngineeringContract,
    service: RunningScorerService,
    backend: str,
    producer_run_id: str,
    metadata_path: Path,
) -> dict[str, Any]:
    _require_run_id(producer_run_id)
    runtime_config = load_runtime_config(paths.repos)
    model = runtime_config.paid_model(contract.producer.model_alias)
    model_id = model.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise CampaignError("producer_model_invalid")
    provider = runtime_config.paid_provider_projection(
        model_id=model_id,
        main_effort=contract.producer.reasoning_effort,
        guardian_effort=contract.producer.reasoning_effort,
    )
    _secret_name, upstream_key = load_provider_secret(runtime_config)
    envelope = UsageEnvelope(
        max_input_tokens=contract.producer.max_input_tokens,
        max_output_tokens=contract.producer.max_output_tokens,
    )
    envelope.validate()
    reservation = maximum_usage_cost(provider.main_pricing, envelope)
    total_cap = contract.budgets.producer_rmb / contract.budgets.rmb_per_usd
    prior_budget = _prior_producer_budget_projection(paths)
    current_cap = total_cap - prior_budget["spent_usd"]
    run_cap = min(_PRODUCER_RUN_CAP_USD, current_cap)
    if (
        total_cap != _PRODUCER_TOTAL_CAP_USD
        or current_cap <= 0
        or reservation > run_cap
    ):
        raise CampaignError("producer_budget_derivation_invalid")
    ledger_path = paths.runtime_root / f"budget/{_PRODUCER_LEDGER_NAME}"
    ledger_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with PersistentBudgetLedger(
        ledger_path,
        batch_id=_PRODUCER_BATCH_ID,
        total_cap_usd=current_cap,
        max_runs=_PRODUCER_MAX_RUNS,
        default_run_cap_usd=run_cap,
        usage_envelope=envelope,
        unpriced_stop_threshold=1,
        unpriced_fallback_usd=reservation,
        reservation_upstream_attempts=provider.max_attempts,
    ) as ledger:
        ledger.claim_run(producer_run_id, cap_usd=run_cap)
        with LoopbackResponsesProxy(
            upstream_base_url=provider.base_url,
            api_key=upstream_key,
            ledger=ledger,
            run_id=producer_run_id,
            metadata_path=metadata_path,
            main_model=provider.main_model,
            main_effort=provider.main_effort,
            main_pricing=provider.main_pricing,
            guardian_model=provider.main_model,
            guardian_pricing=provider.main_pricing,
            guardian_effort=provider.main_effort,
            max_attempts=provider.max_attempts,
            retry_backoff_seconds=provider.retry_backoff_seconds,
            unbilled_retry_statuses=provider.unbilled_retry_statuses,
            request_reservation_usd=reservation,
            run_cap_usd=run_cap,
            max_concurrent_main=2,
            usage_envelope=envelope,
            timeout_seconds=180,
        ) as budget_proxy:
            with tempfile.TemporaryDirectory(
                prefix=f"plan097-{backend}-producer-",
                dir=paths.runtime_root,
            ) as temporary:
                private = Path(temporary)
                private.chmod(0o700)
                home = private / "home"
                workspace = private / "workspace"
                trace_root = private / "trace"
                home.mkdir(mode=0o700)
                workspace.mkdir(mode=0o700)
                trace_root.mkdir(mode=0o700)
                auth = home / "auth.json"
                auth.write_text(
                    json.dumps(
                        {"OPENAI_API_KEY": budget_proxy.downstream_api_key},
                        separators=(",", ":"),
                    ),
                    encoding="utf-8",
                )
                auth.chmod(0o600)
                with CaptureProxy(
                    mode="forward",
                    upstream_base_url=budget_proxy.base_url,
                    bearer=budget_proxy.downstream_api_key,
                    model=provider.main_model,
                    capture_path=None,
                    forward_timeout_seconds=180,
                ) as capture:
                    command = build_producer_command(
                        paths.binaries.codex,
                        base_url=capture.base_url,
                        endpoint=service.endpoint,
                        expected_descriptor=contract.backends[backend].service_descriptor,
                        call_timeout_ms=(
                            contract.backends[backend].client_call_timeout_ms
                        ),
                        startup_timeout_ms=(
                            contract.backends[backend].client_startup_timeout_ms
                        ),
                        model=provider.main_model,
                        effort=provider.main_effort,
                        member_model=provider.main_model,
                        member_effort=provider.main_effort,
                    )
                    completed = _run_owned_command(
                        command,
                        cwd=workspace,
                        env=_codex_environment(
                            home=home,
                            trace_root=trace_root,
                            downstream_key=budget_proxy.downstream_api_key,
                        ),
                        timeout=contract.producer.run_timeout_seconds,
                        timeout_code="producer_process_timeout",
                    )
                    wire = capture.jsonl()
                trace = load_rollout_trace(find_trace_bundle(trace_root))
                if completed.returncode != 0:
                    raise CampaignError("producer_process_failed")
                try:
                    evidence = evaluate_producer_evidence(wire, trace)
                except ProducerEvidenceError as exc:
                    error_code = str(exc)
                    if not re.fullmatch(r"[a-z0-9_]{1,120}", error_code):
                        error_code = "producer_evidence_invalid"
                    try:
                        diagnostic = project_producer_attempts(wire, trace)
                    except ProducerEvidenceError:
                        diagnostic = {
                            "schema": (
                                "rondo-publication-critic-plan097-"
                                "producer-failure-v1"
                            ),
                            "projection_status": "unavailable",
                        }
                    _write_private_diagnostic(
                        metadata_path.with_name(
                            f"{metadata_path.stem}-evidence-failure.json"
                        ),
                        {**diagnostic, "error_code": error_code},
                    )
                    raise
        snapshot = ledger.snapshot()
    _assert_body_free_file(
        metadata_path,
        forbidden=(
            upstream_key,
            budget_proxy.downstream_api_key,
            provider.base_url,
            INITIAL_SYNTHETIC_DRAFT,
        ),
    )
    run = snapshot.get("runs", {}).get(producer_run_id)
    if not isinstance(run, dict):
        raise CampaignError("producer_budget_receipt_missing")
    requests = run.get("requests")
    if (
        not isinstance(requests, dict)
        or not requests
        or any(
            not isinstance(row, dict) or row.get("status") != "settled"
            for row in requests.values()
        )
        or run.get("stopped") is not False
    ):
        raise CampaignError("producer_budget_not_cleanly_settled")
    return {
        **evidence,
        "budget_run_id": producer_run_id,
        "request_count": len(requests),
        "spent_usd": run["spent_usd"],
        "run_stopped": run["stopped"],
        "provider_profile_sha256": provider.profile_sha256,
        "model": provider.main_model,
        "effort": provider.main_effort,
        "private_wire_and_trace_removed_before_receipt": True,
    }


def finalize_run(start: Path, *, phase: str, run_id: str) -> Path:
    paths = CampaignPaths.discover(start)
    contract = load_contract(paths.repos.worktree_root)
    run_root = _existing_run_root(paths, phase, run_id)
    names = (
        "preflight.json",
        "controlled-gates.json",
        "off.json",
        "backend-local.json",
        "backend-cloud.json",
    )
    receipts = {name: _read_json(run_root / name) for name in names}
    preflight_receipt = receipts["preflight.json"]
    for name, value in receipts.items():
        if (
            value.get("schema") != RECEIPT_SCHEMA
            or value.get("source") != preflight_receipt.get("source")
            or value.get("contract_sha256") != contract.contract_sha256
            or value.get("runtime_identity")
            != preflight_receipt.get("runtime_identity")
        ):
            raise CampaignError(f"step_receipt_identity_mismatch:{name}")
    if phase == "formal" and preflight_receipt["source"].get("dirty") is not False:
        raise CampaignError("formal_source_not_clean")
    controlled = receipts["controlled-gates.json"]
    off = receipts["off.json"]
    local = receipts["backend-local.json"]
    cloud = receipts["backend-cloud.json"]
    if (
        controlled.get("failure_fallback") != "one_canonical_commit"
        or controlled.get("cancellation") != "zero_commit"
        or off.get("publication_critic_configured") is not False
        or off.get("canonical_flow_passed") is not True
        or local.get("backend") != "local"
        or cloud.get("backend") != "cloud"
        or local.get("direct_branch_coverage") != ["pass", "rewrite"]
        or cloud.get("direct_branch_coverage") != ["pass", "rewrite"]
        or local.get("service", {}).get("process_reaped") is not True
        or cloud.get("service", {}).get("process_reaped") is not True
        or local.get("producer", {}).get("status") != "passed"
        or cloud.get("producer", {}).get("status") != "passed"
    ):
        raise CampaignError("step_receipt_incomplete")
    producer_budget = _producer_budget_snapshot(paths, contract)
    cloud_budget = cloud.get("cloud_scorer_budget")
    if not isinstance(cloud_budget, dict):
        raise CampaignError("cloud_budget_receipt_missing")
    producer_spent_usd = Decimal(producer_budget["spent_usd"])
    producer_spent_rmb = producer_spent_usd * contract.budgets.rmb_per_usd
    cloud_conservative_rmb = Decimal(cloud_budget["conservative_charged_rmb"])
    total_rmb = producer_spent_rmb + cloud_conservative_rmb
    if (
        producer_spent_rmb > contract.budgets.producer_rmb
        or cloud_conservative_rmb > contract.budgets.cloud_scorer_rmb
        or total_rmb > contract.budgets.total_rmb
    ):
        raise CampaignError("total_budget_exceeded")
    terminal = (
        "M3_D_DUAL_BACKEND_ENGINEERING_PASS"
        if phase == "formal"
        else "COMMISSIONING_COMPLETE"
    )
    summary = {
        "schema": SUMMARY_SCHEMA,
        "phase": phase,
        "run_id": run_id,
        "terminal": terminal,
        "source": preflight_receipt["source"],
        "contract_sha256": contract.contract_sha256,
        "runtime_identity": preflight_receipt["runtime_identity"],
        "backend_descriptor_sha256": preflight_receipt[
            "backend_descriptor_sha256"
        ],
        "off": {
            "bypass": True,
            "canonical_flow_passed": True,
            "scorer_secret_loaded": False,
            "scorer_process_started": False,
            "review_cycle_created": False,
        },
        "backends": {
            "local": _backend_projection(local),
            "cloud": _backend_projection(cloud),
        },
        "controlled_paths": {
            "failure_fallback": "one_canonical_commit",
            "cancellation": "zero_commit",
            "evidence_kind": controlled["evidence_kind"],
        },
        "budget": {
            "producer_cap_rmb": str(contract.budgets.producer_rmb),
            "producer_spent_usd": _decimal_text(producer_spent_usd),
            "producer_spent_rmb": _decimal_text(producer_spent_rmb),
            "producer_request_count": producer_budget["request_count"],
            "cloud_cap_rmb": str(contract.budgets.cloud_scorer_rmb),
            "cloud_conservative_charged_rmb": _decimal_text(
                cloud_conservative_rmb
            ),
            "cloud_attempt_count": cloud_budget["attempt_count"],
            "total_cap_rmb": str(contract.budgets.total_rmb),
            "total_conservative_rmb": _decimal_text(total_rmb),
        },
        "resource_terminal": {
            "local_service_reaped": True,
            "local_worker_reaped": True,
            "cloud_service_reaped": True,
            "paid_proxies_closed_before_summary": True,
            "private_packets_wire_and_trace_removed": True,
        },
        "conclusion_boundary": dict(contract.conclusion_boundary),
    }
    return _write_receipt(paths, phase, run_id, "result.json", summary)


def _producer_budget_snapshot(
    paths: CampaignPaths, contract: EngineeringContract
) -> dict[str, Any]:
    runtime_config = load_runtime_config(paths.repos)
    model = runtime_config.paid_model(contract.producer.model_alias)
    model_id = model.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise CampaignError("producer_model_invalid")
    provider = runtime_config.paid_provider_projection(
        model_id=model_id,
        main_effort=contract.producer.reasoning_effort,
        guardian_effort=contract.producer.reasoning_effort,
    )
    envelope = UsageEnvelope(
        max_input_tokens=contract.producer.max_input_tokens,
        max_output_tokens=contract.producer.max_output_tokens,
    )
    reservation = maximum_usage_cost(provider.main_pricing, envelope)
    prior = _prior_producer_budget_projection(paths)
    total_cap = contract.budgets.producer_rmb / contract.budgets.rmb_per_usd
    current_cap = total_cap - prior["spent_usd"]
    run_cap = min(_PRODUCER_RUN_CAP_USD, current_cap)
    if current_cap <= 0 or reservation > run_cap:
        raise CampaignError("producer_budget_derivation_invalid")
    with PersistentBudgetLedger(
        paths.runtime_root / f"budget/{_PRODUCER_LEDGER_NAME}",
        batch_id=_PRODUCER_BATCH_ID,
        total_cap_usd=current_cap,
        max_runs=_PRODUCER_MAX_RUNS,
        default_run_cap_usd=run_cap,
        usage_envelope=envelope,
        unpriced_stop_threshold=1,
        unpriced_fallback_usd=reservation,
        reservation_upstream_attempts=provider.max_attempts,
    ) as ledger:
        current = _producer_ledger_projection(
            ledger.snapshot(), expected_batch_id=_PRODUCER_BATCH_ID
        )
    return {
        "spent_usd": _decimal_text(current["spent_usd"] + prior["spent_usd"]),
        "request_count": current["request_count"] + prior["request_count"],
    }


def _prior_producer_budget_projection(paths: CampaignPaths) -> dict[str, Any]:
    spent = Decimal("0")
    requests = 0
    for batch_id, filename in _PRIOR_PRODUCER_LEDGERS:
        path = paths.runtime_root / f"budget/{filename}"
        if not path.exists():
            continue
        projection = _producer_ledger_projection(
            _read_json(path), expected_batch_id=batch_id
        )
        spent += projection["spent_usd"]
        requests += projection["request_count"]
    return {"spent_usd": spent, "request_count": requests}


def _producer_ledger_projection(
    snapshot: Mapping[str, Any], *, expected_batch_id: str
) -> dict[str, Any]:
    if snapshot.get("batch_id") != expected_batch_id:
        raise CampaignError("producer_budget_batch_invalid")
    runs = snapshot.get("runs")
    if not isinstance(runs, dict):
        raise CampaignError("producer_budget_invalid")
    spent = Decimal("0")
    requests = 0
    for run in runs.values():
        if (
            not isinstance(run, dict)
            or not isinstance(run.get("requests"), dict)
            or any(
                not isinstance(request, dict)
                or request.get("status") != "settled"
                for request in run["requests"].values()
            )
        ):
            raise CampaignError("producer_budget_invalid")
        spent += Decimal(run["spent_usd"])
        requests += len(run["requests"])
    return {
        "spent_usd": spent,
        "request_count": requests,
    }


def _backend_projection(receipt: Mapping[str, Any]) -> dict[str, Any]:
    producer = receipt["producer"]
    return {
        "descriptor_sha256": receipt["service"]["descriptor_sha256"],
        "startup_elapsed_ms": receipt["service"]["startup_elapsed_ms"],
        "ready_elapsed_ms": receipt["service"]["ready_elapsed_ms"],
        "direct_cases": list(receipt["direct_cases"]),
        "direct_branch_coverage": list(receipt["direct_branch_coverage"]),
        "producer": {
            "status": producer["status"],
            "publish_attempt_count": producer["publish_attempt_count"],
            "rewrite_count": producer["rewrite_count"],
            "cycle_hop_count": producer["cycle_hop_count"],
            "final_review_status": producer["final_review_status"],
            "canonical_commit_count": producer["canonical_commit_count"],
            "event_count": producer["event_count"],
            "version_count": producer["version_count"],
            "publish_mutation_count": producer["publish_mutation_count"],
            "revision": producer["revision"],
            "root_wake": producer["root_wake"],
            "request_count": producer["request_count"],
            "spent_usd": producer["spent_usd"],
        },
        "service_process_reaped": True,
    }


def _cloud_budget_projection(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    attempts = value.get("attempts")
    if not isinstance(attempts, list):
        raise CampaignError("cloud_budget_invalid")
    return {
        "cap_rmb": value["cap_rmb"],
        "conservative_charged_rmb": value["conservative_charged_rmb"],
        "remaining_rmb": value["remaining_rmb"],
        "attempt_count": len(attempts),
        "usage_priced_count": sum(
            row.get("state") == "usage_priced"
            for row in attempts
            if isinstance(row, dict)
        ),
        "unknown_usage_count": sum(
            row.get("state") == "unknown_usage_charged"
            for row in attempts
            if isinstance(row, dict)
        ),
    }


def _prior_cloud_budget_projection(paths: CampaignPaths) -> dict[str, Any]:
    path = paths.runtime_root / f"budget/{_PRIOR_CLOUD_LEDGER_NAME}"
    if not path.exists():
        return {
            "conservative_charged_rmb": Decimal("0"),
            "attempt_count": 0,
            "usage_priced_count": 0,
            "unknown_usage_count": 0,
        }
    value = _read_json(path)
    if (
        value.get("schema")
        != "rondo-publication-critic-plan097-cloud-budget-v1"
        or value.get("cap_rmb")
        != _decimal_text(_PRIOR_CLOUD_LEDGER_CAP_RMB)
    ):
        raise CampaignError("prior_cloud_budget_invalid")
    attempts = value.get("attempts")
    if not isinstance(attempts, list):
        raise CampaignError("prior_cloud_budget_invalid")
    charged = Decimal("0")
    usage_priced = 0
    unknown = 0
    for expected, row in enumerate(attempts, start=1):
        if (
            not isinstance(row, Mapping)
            or row.get("attempt") != expected
            or row.get("state")
            not in {"usage_priced", "unknown_usage_charged"}
        ):
            raise CampaignError("prior_cloud_budget_invalid")
        try:
            charge = Decimal(str(row.get("conservative_charge_rmb")))
        except (ArithmeticError, ValueError):
            raise CampaignError("prior_cloud_budget_invalid") from None
        if not charge.is_finite() or charge < 0 or charge > Decimal("1"):
            raise CampaignError("prior_cloud_budget_invalid")
        charged += charge
        usage_priced += row.get("state") == "usage_priced"
        unknown += row.get("state") == "unknown_usage_charged"
    if charged > _PRIOR_CLOUD_LEDGER_CAP_RMB:
        raise CampaignError("prior_cloud_budget_invalid")
    return {
        "conservative_charged_rmb": charged,
        "attempt_count": len(attempts),
        "usage_priced_count": usage_priced,
        "unknown_usage_count": unknown,
    }


def _combined_cloud_budget_projection(
    contract: EngineeringContract,
    prior: Mapping[str, Any] | None,
    current: Mapping[str, Any],
) -> dict[str, Any]:
    if prior is None:
        raise CampaignError("prior_cloud_budget_missing")
    projected = _cloud_budget_projection(current)
    if projected is None:
        raise CampaignError("cloud_budget_invalid")
    prior_charged = prior.get("conservative_charged_rmb")
    if not isinstance(prior_charged, Decimal):
        raise CampaignError("prior_cloud_budget_invalid")
    total = prior_charged + Decimal(projected["conservative_charged_rmb"])
    if total > contract.budgets.cloud_scorer_rmb:
        raise CampaignError("cloud_budget_invalid")
    return {
        "cap_rmb": _decimal_text(contract.budgets.cloud_scorer_rmb),
        "conservative_charged_rmb": _decimal_text(total),
        "remaining_rmb": _decimal_text(
            contract.budgets.cloud_scorer_rmb - total
        ),
        "attempt_count": prior["attempt_count"] + projected["attempt_count"],
        "usage_priced_count": (
            prior["usage_priced_count"] + projected["usage_priced_count"]
        ),
        "unknown_usage_count": (
            prior["unknown_usage_count"] + projected["unknown_usage_count"]
        ),
    }


def _source_identity(root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if commit.returncode != 0 or status.returncode != 0:
        raise CampaignError("source_identity_unavailable")
    revision = commit.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise CampaignError("source_commit_invalid")
    return {"commit": revision, "dirty": bool(status.stdout)}


def _codex_environment(
    *, home: Path, trace_root: Path, downstream_key: str
) -> dict[str, str]:
    if not downstream_key or "\n" in downstream_key or "\r" in downstream_key:
        raise CampaignError("downstream_key_invalid")
    private_tmp = home / "tmp"
    private_tmp.mkdir(mode=0o700)
    return {
        "CODEX_HOME": str(home),
        "HOME": str(home),
        "TMPDIR": str(private_tmp),
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "OPENAI_API_KEY": downstream_key,
        "CODEX_ROLLOUT_TRACE_ROOT": str(trace_root),
    }


def _write_receipt(
    paths: CampaignPaths,
    phase: str,
    run_id: str,
    filename: str,
    value: Mapping[str, Any],
) -> Path:
    _require_phase(phase)
    _require_run_id(run_id)
    namespace = WriteOnceNamespace(
        paths.runtime_root / phase,
        run_id,
        validate_run_id=lambda candidate: _RUN_ID.fullmatch(candidate) is not None,
    )
    namespace.create(exist_ok=filename != "preflight.json")
    if filename != "preflight.json" and not (namespace.path / "preflight.json").is_file():
        raise CampaignError("preflight_receipt_missing")
    try:
        body = (
            json.dumps(
                dict(value),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise CampaignError("receipt_not_json") from exc
    if len(body) > _MAX_RECEIPT_BYTES:
        raise CampaignError("receipt_too_large")
    return namespace.write_bytes(filename, body)


def _existing_run_root(paths: CampaignPaths, phase: str, run_id: str) -> Path:
    root = paths.run_root(phase, run_id)
    if root.is_symlink() or not root.is_dir() or not (root / "preflight.json").is_file():
        raise CampaignError("run_preflight_missing")
    return root


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise CampaignError(f"receipt_missing:{path.name}")
    metadata = path.stat()
    if metadata.st_size <= 0 or metadata.st_size > _MAX_RECEIPT_BYTES:
        raise CampaignError(f"receipt_unsafe:{path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignError(f"receipt_invalid:{path.name}") from exc
    if not isinstance(value, dict):
        raise CampaignError(f"receipt_invalid:{path.name}")
    return value


def _assert_body_free_file(path: Path, *, forbidden: Sequence[str]) -> None:
    if path.is_symlink() or not path.is_file():
        raise CampaignError("body_free_metadata_missing")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise CampaignError("body_free_metadata_permissions_invalid")
    raw = path.read_bytes()
    for value in forbidden:
        if value and value.encode("utf-8") in raw:
            raise CampaignError("body_free_metadata_leak")


def _write_private_diagnostic(path: Path, value: Mapping[str, Any]) -> None:
    try:
        body = (
            json.dumps(
                dict(value),
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise CampaignError("private_diagnostic_invalid") from exc
    if not body or len(body) > _MAX_RECEIPT_BYTES:
        raise CampaignError("private_diagnostic_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise CampaignError("private_diagnostic_output_exists") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def _require_phase(value: str) -> None:
    if value not in _PHASES:
        raise CampaignError("phase_invalid")


def _require_backend(value: str) -> None:
    if value not in _BACKENDS:
        raise CampaignError("backend_invalid")


def _require_backend_mode(phase: str, skip_direct_cases: bool) -> None:
    _require_phase(phase)
    if not isinstance(skip_direct_cases, bool):
        raise CampaignError("backend_mode_invalid")
    if skip_direct_cases and phase != "commissioning":
        raise CampaignError("producer_only_requires_commissioning")


def _require_watchdog_scope() -> None:
    required = (
        "RONDO_WATCHDOG_WRAPPER_PID",
        "RONDO_WATCHDOG_WRAPPER_START_TICKS",
        "RONDO_WATCHDOG_HEARTBEAT_PATH",
        "RONDO_WATCHDOG_SCRIPT_PATH",
    )
    if any(not os.environ.get(name) for name in required):
        raise CampaignError("local_backend_requires_watchdog_scope")


def _require_run_id(value: str) -> None:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise CampaignError("run_id_invalid")


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _run_owned_command(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int,
    timeout_code: str,
) -> subprocess.CompletedProcess[bytes]:
    """Run one task-owned CLI and reap descendants in its private process group."""

    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _signal_process_group(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            _signal_process_group(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
        raise CampaignError(timeout_code) from None
    finally:
        _reap_residual_process_group(process.pid)
    return subprocess.CompletedProcess(
        args=list(command),
        returncode=process.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _reap_residual_process_group(process_group: int) -> None:
    _signal_process_group(process_group, signal.SIGTERM)
    deadline = time.monotonic() + 3
    while _process_group_exists(process_group) and time.monotonic() < deadline:
        time.sleep(0.05)
    if _process_group_exists(process_group):
        _signal_process_group(process_group, signal.SIGKILL)
        deadline = time.monotonic() + 2
        while _process_group_exists(process_group) and time.monotonic() < deadline:
            time.sleep(0.05)
    if _process_group_exists(process_group):
        raise CampaignError("owned_process_group_not_reaped")


def _signal_process_group(process_group: int, sig: signal.Signals) -> None:
    try:
        os.killpg(process_group, sig)
    except ProcessLookupError:
        pass


def _process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bounded Plan 097 dual-backend engineering steps"
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "controlled-gates", "off", "finalize"):
        child = subparsers.add_parser(command)
        child.add_argument("--phase", choices=sorted(_PHASES), required=True)
        child.add_argument("--run-id", required=True)
    backend = subparsers.add_parser("backend")
    backend.add_argument("--phase", choices=sorted(_PHASES), required=True)
    backend.add_argument("--run-id", required=True)
    backend.add_argument("--backend", choices=sorted(_BACKENDS), required=True)
    backend.add_argument("--producer-run-id", required=True)
    backend.add_argument(
        "--producer-only",
        action="store_true",
        help="commissioning recovery after prior valid direct verdicts",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            output = record_preflight(
                args.repo_root, phase=args.phase, run_id=args.run_id
            )
        elif args.command == "controlled-gates":
            output = run_controlled_gates(
                args.repo_root, phase=args.phase, run_id=args.run_id
            )
        elif args.command == "off":
            output = run_off_step(
                args.repo_root, phase=args.phase, run_id=args.run_id
            )
        elif args.command == "backend":
            output = run_backend_step(
                args.repo_root,
                phase=args.phase,
                run_id=args.run_id,
                backend=args.backend,
                producer_run_id=args.producer_run_id,
                skip_direct_cases=args.producer_only,
            )
        else:
            output = finalize_run(
                args.repo_root, phase=args.phase, run_id=args.run_id
            )
    except (CampaignError, OSError, RuntimeError, ValueError) as exc:
        code = str(exc)
        if not re.fullmatch(r"[a-z0-9_:-]{1,160}", code):
            code = "unclassified_campaign_failure"
        print(json.dumps({"status": "failed", "code": code}, separators=(",", ":")))
        return 1
    print(
        json.dumps(
            {"status": "completed", "receipt": str(output)},
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
