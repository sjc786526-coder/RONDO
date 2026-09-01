"""Plan 102 five-dimension cloud-seam campaign.

Reuses Plan 097 service_runtime, producer_runtime, CloudBudgetProxy, and
PersistentBudgetLedger. Owns a separate budget identity, ledger names, and
receipts. Does not score judge quality and does not touch Plan 097 ledgers.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
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
from ...multi_m5.trace import TraceError, find_trace_bundle, load_rollout_trace
from ..identity import sha256_file
from ..write_once import WriteOnceNamespace
from .cloud_budget_proxy import CloudBudgetProxy
from .plan102_contract import (
    PROXY_KEY_ENV,
    Plan102Contract,
    load_plan102_contract,
)
from .producer_runtime import (
    INITIAL_SYNTHETIC_DRAFT,
    ProducerEvidenceError,
    build_producer_command,
    evaluate_producer_evidence,
    project_producer_attempts,
)

PLAN102_PRODUCER_FORMAL_PROMPT = """Run one bounded synthetic Plan 102 Publication Critic engineering flow as Root.
1. Spawn exactly one member with task_name producer and the exact user task: Complete the full Producer rewrite cycle and do not finish until canonical commit. The runtime supplies that member its complete detailed task as developer instructions, so add no other task detail. Do not spawn any other member. Root must never call team_publish.
2. Immediately call wait_agent once with timeout_ms 900000 and wait for the Producer's canonical Team State publish to wake Root. A blocked rewrite is not a publish and must not wake Root.
3. After the wake, call team_inspect exactly once with action dump and limit 50, then exactly once with action log and limit 50. Do not mutate Team State.
4. Stop after both inspections. Do not quote or summarize the publication body in the final response.
"""
# Root waits for the member's canonical publish. At `high` effort the rewrite
# cycle takes far longer than the 180s that sufficed at `low`, and a Root that
# wakes early loses the evidence the round was run for. This is a ceiling, so a
# round that finishes sooner still wakes on the publish.
_PRODUCER_WAIT_TIMEOUT_MS = 900_000
# Plan 097's member prompt states the retry rule in prose. Under `terra` at
# `low` effort that reliably produced a second `team_publish` that dropped
# `review_cycle_id` and resent the identical candidate, which `team_publish`
# rejects with a cycle mismatch; the model then treated the rejection as
# terminal. This variant pins the same rules to a concrete mechanic (keep the
# result, read the id off it) and says a rejection must be corrected rather
# than ended on. It relaxes none of the evidence invariants: one publish per
# fresh cell, no prewriting, one Event, one canonical commit.
PLAN102_PRODUCER_MEMBER_PROMPT = f"""You are the only Producer in a bounded synthetic Plan 102 engineering run.
Do not spawn another agent and do not ask Root to publish for you.
Your assignment is complete only after team_publish returns the canonical event_id, version_id, and revision. Neither a rewrite_required result nor a rejected attempt is ever a terminal result: do not send a final response or end your assignment on one.
1. Your first action on the publication path must be one team_publish opening a new Event. Use a short synthetic title, omit event_id and review_cycle_id, and make the complete summary exactly: {INITIAL_SYNTHETIC_DRAFT}
2. Use exactly one fresh code cell for each team_publish attempt. That cell must contain exactly one awaited team_publish call and no second publish call. Bind the awaited result to a variable, then print its status, its feedback, and its review_cycle_id -- print nothing else from it, and never print the candidate or any publication body. The cell output is the only part of the result you can read, so a cell that prints nothing tells you nothing. End the cell after that print; when the result is rewrite_required you MUST continue in the next model turn and make the required revised attempt. Never prewrite, duplicate, batch, or parallelize publish attempts.
3. Inspect the actual team_publish result. If and only if its status is rewrite_required, read its fixed feedback and autonomously write a materially revised, concise, self-contained synthetic summary. The revised summary must differ in wording from the one you just sent; never resend the previous candidate unchanged. Retry from this same thread with the same new-Event title. Do not prepare or copy a second draft before receiving feedback.
4. The first team_publish is the only call that may omit review_cycle_id. Every later team_publish MUST pass the review_cycle_id of the immediately preceding rewrite_required result. Pass it as an expression that indexes the variable you bound in step 2, never as a literal string you transcribed: a retyped id will not match and the attempt will be rejected. Cells share one session, so that variable is still in scope. Never open a second Event and never issue a retry without it.
5. If a team_publish attempt is rejected instead of reviewed, the cycle is still open: read the error, correct that same attempt in a fresh cell in the next model turn, and retry. A rejection does not consume a rewrite opportunity and must not end your assignment.
6. Repeat steps 3-5 for at most the two blocking rewrite opportunities. The third review is non-blocking. Stop immediately when team_publish returns event_id, version_id, and revision; do not publish another Version.
7. End your assignment after the canonical commit. Never print or send the publication body to Root.
"""
from .service_runtime import (
    RunningScorerService,
    RuntimeBinaries,
    start_cloud_service,
    write_packet,
)


RECEIPT_SCHEMA = "rondo-publication-critic-plan102-step-v1"
_RUN_ID = re.compile(r"plan102-[a-z0-9][a-z0-9-]{0,79}\Z")
# Producer ledgers are generational: a generation is retired once its run slots
# are used up, and the next one carries only the budget the earlier generations
# left behind. Opening a generation with the full task cap would let a new
# ledger silently reset the task-wide `producer_usd` limit.
_PRODUCER_LEDGER_GENERATIONS: tuple[tuple[str, str], ...] = (
    ("plan102-producer-terra-v1", "producer-terra-v1-ledger.json"),
    ("plan102-producer-terra-v2", "producer-terra-v2-ledger.json"),
    ("plan102-producer-terra-v3", "producer-terra-v3-ledger.json"),
    # v4 is the first `high` effort generation. A generation also has to be
    # retired when the per-request reservation changes, because the ledger
    # pins `unpriced_fallback_usd`; that keeps the `low` and `high` rounds in
    # separate books without loosening the task cap.
    ("plan102-producer-terra-v4", "producer-terra-v4-ledger.json"),
    ("plan102-producer-terra-v5", "producer-terra-v5-ledger.json"),
)
_PRODUCER_BATCH_ID, _PRODUCER_LEDGER_NAME = _PRODUCER_LEDGER_GENERATIONS[-1]
_CLOUD_LEDGER_NAME = "cloud-scorer-v1-ledger.json"
_PRODUCER_MAX_CONCURRENT_MAIN = 1
_MAX_RECEIPT_BYTES = 1024 * 1024
_B2_JUDGE_CALL_EXTRAPOLATION = 8
_B2_PRODUCER_REQUEST_EXTRAPOLATION = 40
_PLAN097_PRODUCER_USD_PER_REQUEST = Decimal("0.0165")


class Plan102CampaignError(RuntimeError):
    """Stable body-free Plan 102 campaign failure."""


@dataclass(frozen=True)
class Plan102Paths:
    repos: RepoPaths
    runtime_root: Path
    binaries: RuntimeBinaries

    @classmethod
    def discover(cls, start: Path) -> "Plan102Paths":
        repos = RepoPaths.discover(start)
        target = repos.common_root / ".codex/cargo-target/rondo-multi/debug"
        return cls(
            repos=repos,
            runtime_root=repos.common_root / "eval-data/publication-critic/plan102",
            binaries=RuntimeBinaries(
                codex=target / "codex",
                real_service=target / "codex-publication-critic-real-service",
                cloud_service=target / "codex-publication-critic-cloud-service",
                probe=target / "codex-publication-critic-probe",
            ),
        )

    def validate(self) -> None:
        self.binaries.validate()
        expected_target = (
            self.repos.common_root / ".codex/cargo-target/rondo-multi"
        ).resolve()
        for binary in (
            self.binaries.codex,
            self.binaries.cloud_service,
            self.binaries.probe,
        ):
            try:
                binary.resolve().relative_to(expected_target)
            except (OSError, ValueError) as exc:
                raise Plan102CampaignError("binary_outside_shared_target") from exc

    def run_root(self, run_id: str) -> Path:
        _require_run_id(run_id)
        return self.runtime_root / "runs" / run_id


def record_preflight(start: Path, *, run_id: str, require_clean: bool) -> Path:
    paths = Plan102Paths.discover(start)
    contract = load_plan102_contract(paths.repos.worktree_root)
    paths.validate()
    source = _source_identity(paths.repos.worktree_root)
    if require_clean and source["dirty"]:
        raise Plan102CampaignError("source_not_clean")
    _require_secrets(paths)
    identities = {
        "codex_sha256": sha256_file(paths.binaries.codex),
        "cloud_service_sha256": sha256_file(paths.binaries.cloud_service),
        "probe_sha256": sha256_file(paths.binaries.probe),
        "descriptor_sha256": contract.backend.descriptor_sha256,
        "contract_sha256": contract.contract_sha256,
    }
    judge_budget = _judge_budget_snapshot(paths, contract)
    producer_budget = _producer_budget_snapshot(paths, contract)
    return _write_receipt(
        paths,
        run_id,
        "preflight.json",
        {
            "schema": RECEIPT_SCHEMA,
            "step": "preflight",
            "evidence_class": "offline_plus_secret_presence",
            "source": source,
            "runtime_identity": identities,
            "product_default": contract.product_default,
            "quality_evaluation": contract.quality_evaluation,
            "judge_budget": judge_budget,
            "producer_budget": producer_budget,
            "secrets": {"judge_present": True, "producer_present": True},
        },
    )


def run_judge_step(start: Path, *, run_id: str) -> Path:
    return _run_paid_step(start, run_id=run_id, mode="judge", producer_run_id=None)


def run_producer_step(start: Path, *, run_id: str, producer_run_id: str) -> Path:
    return _run_paid_step(
        start, run_id=run_id, mode="producer", producer_run_id=producer_run_id
    )


def run_e2e_step(start: Path, *, run_id: str, producer_run_id: str) -> Path:
    return _run_paid_step(
        start, run_id=run_id, mode="e2e", producer_run_id=producer_run_id
    )


def _run_paid_step(
    start: Path,
    *,
    run_id: str,
    mode: str,
    producer_run_id: str | None,
) -> Path:
    if mode not in {"judge", "producer", "e2e"}:
        raise Plan102CampaignError("step_mode_invalid")
    if mode in {"producer", "e2e"} and producer_run_id is None:
        raise Plan102CampaignError("producer_run_id_required")
    paths = Plan102Paths.discover(start)
    contract = load_plan102_contract(paths.repos.worktree_root)
    paths.validate()
    run_root = _existing_run_root(paths, run_id)
    started = time.monotonic()
    cloud_proxy = _start_judge_proxy(paths, contract)
    stamp = producer_run_id or mode
    runtime_descriptor = run_root / f"{mode}-{stamp}-runtime-descriptor.json"
    with cloud_proxy:
        service = start_cloud_service(
            binaries=paths.binaries,
            tracked_descriptor=contract.backend.descriptor_path,
            runtime_descriptor=runtime_descriptor,
            proxy_base_url=cloud_proxy.base_url,
            downstream_api_key=cloud_proxy.downstream_api_key,
            call_timeout_ms=contract.backend.client_call_timeout_ms,
            startup_timeout_ms=contract.backend.client_startup_timeout_ms,
            proxy_key_env=PROXY_KEY_ENV,
        )
        try:
            receipt = _finish_paid_step(
                paths=paths,
                contract=contract,
                service=service,
                cloud_proxy=cloud_proxy,
                run_id=run_id,
                run_root=run_root,
                mode=mode,
                producer_run_id=producer_run_id,
                started=started,
            )
        finally:
            service.close()
            cloud_proxy.close()
    return receipt


def _finish_paid_step(
    *,
    paths: Plan102Paths,
    contract: Plan102Contract,
    service: RunningScorerService,
    cloud_proxy: CloudBudgetProxy,
    run_id: str,
    run_root: Path,
    mode: str,
    producer_run_id: str | None,
    started: float,
) -> Path:
    direct: list[dict[str, Any]] = []
    producer: dict[str, Any] | None = None
    with tempfile.TemporaryDirectory(
        prefix=f"plan102-{mode}-packets-", dir=paths.runtime_root
    ) as temporary:
        packet_root = Path(temporary)
        packet_root.chmod(0o700)
        with service:
            ready = service.ready()
            if ready.get("result") != "ready":
                raise Plan102CampaignError("backend_not_ready")
            if mode in {"judge", "e2e"}:
                direct = _review_direct_cases(contract, service, packet_root)
            if mode in {"producer", "e2e"}:
                assert producer_run_id is not None
                producer = _run_producer(
                    paths=paths,
                    contract=contract,
                    service=service,
                    producer_run_id=producer_run_id,
                    metadata_path=run_root / f"{mode}-producer-budget-metadata.json",
                    require_canonical=mode == "e2e",
                )
            observation = {
                "backend": service.observation.backend,
                "descriptor_sha256": service.observation.descriptor_sha256,
                "startup_elapsed_ms": service.observation.startup_elapsed_ms,
                "ready_elapsed_ms": service.observation.ready_elapsed_ms,
            }
            diagnostics = service.diagnostic_codes
    if service.process.poll() is None:
        raise Plan102CampaignError("service_process_not_reaped")
    judge_budget = cloud_proxy.snapshot()
    request_shapes = cloud_proxy.request_shapes()
    thinking = _thinking_observation(
        request_shapes, judge_budget, contract.budgets.thinking_off_completion_token_max
    )
    if mode in {"judge", "e2e"} and not thinking["thinking_disabled"]:
        raise Plan102CampaignError("thinking_not_disabled")
    if mode in {"judge", "e2e"} and not thinking["completion_tokens_short"]:
        raise Plan102CampaignError("thinking_off_completion_not_short")
    observed = {row["observed_verdict"] for row in direct}
    if mode in {"judge", "e2e"} and observed != {"pass", "rewrite"}:
        raise Plan102CampaignError("direct_branch_coverage_incomplete")
    extrapolation = _extrapolate_budgets(paths, contract, judge_budget, producer)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "step": mode,
        "evidence_class": "real_api",
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "service": {
            **observation,
            "process_reaped": True,
            "shutdown_outcome": service.shutdown_outcome,
            "diagnostic_codes": list(diagnostics),
        },
        "direct_cases": direct,
        "direct_branch_coverage": sorted(observed),
        "thinking": thinking,
        "producer": producer,
        "judge_budget": {
            "schema": judge_budget["schema"],
            "cap_rmb": judge_budget["cap_rmb"],
            "conservative_charged_rmb": judge_budget["conservative_charged_rmb"],
            "remaining_rmb": judge_budget["remaining_rmb"],
            "attempt_count": len(judge_budget["attempts"]),
            "attempts": [
                {
                    "attempt": row["attempt"],
                    "state": row["state"],
                    "usage": row["usage"],
                    "actual_charge_rmb": row["actual_charge_rmb"],
                    "conservative_charge_rmb": row["conservative_charge_rmb"],
                }
                for row in judge_budget["attempts"]
            ],
        },
        "budget_extrapolation": extrapolation,
        "product_default": contract.product_default,
        "quality_evaluation": contract.quality_evaluation,
        "private_packets_and_traces_removed_before_receipt": True,
    }
    return _write_receipt(paths, run_id, f"{mode}.json", receipt)


def _review_direct_cases(
    contract: Plan102Contract,
    service: RunningScorerService,
    packet_root: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, case in enumerate(contract.direct_cases, start=1):
        packet = packet_root / f"case-{index}.json"
        write_packet(packet, case.packet)
        result = service.review(packet)
        verdict = result.get("result")
        if verdict not in {"pass", "rewrite"}:
            raise Plan102CampaignError("direct_verdict_invalid")
        rows.append({"case_id": case.case_id, "observed_verdict": verdict})
    return rows


def _thinking_observation(
    request_shapes: Sequence[Mapping[str, Any]],
    judge_budget: Mapping[str, Any],
    token_max: int,
) -> dict[str, Any]:
    thinking_types = [row.get("thinking_type") for row in request_shapes]
    completions: list[int] = []
    for row in judge_budget.get("attempts", []):
        usage = row.get("usage")
        if isinstance(usage, Mapping) and type(usage.get("completion_tokens")) is int:
            completions.append(usage["completion_tokens"])
    return {
        "request_count": len(request_shapes),
        "thinking_types": thinking_types,
        "thinking_disabled": bool(thinking_types)
        and all(item == "disabled" for item in thinking_types),
        "completion_tokens": completions,
        "completion_tokens_short": bool(completions)
        and all(item <= token_max for item in completions),
        "thinking_off_completion_token_max": token_max,
    }


def _run_producer(
    *,
    paths: Plan102Paths,
    contract: Plan102Contract,
    service: RunningScorerService,
    producer_run_id: str,
    metadata_path: Path,
    require_canonical: bool,
) -> dict[str, Any]:
    _require_run_id(producer_run_id)
    runtime_config = load_runtime_config(paths.repos)
    model = runtime_config.paid_model(contract.producer.model_alias)
    model_id = model.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise Plan102CampaignError("producer_model_invalid")
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
    snapshot = _producer_budget_snapshot(paths, contract)
    remaining = contract.budgets.producer_usd - Decimal(snapshot["spent_usd"])
    run_cap = min(contract.producer.run_cap_usd, remaining)
    if remaining <= 0 or reservation > run_cap:
        raise Plan102CampaignError("producer_budget_derivation_invalid")
    ledger_path = paths.runtime_root / f"budget/{_PRODUCER_LEDGER_NAME}"
    ledger_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    active_cap = contract.budgets.producer_usd - _producer_retired_spend(paths)
    if active_cap <= 0 or run_cap > active_cap:
        raise Plan102CampaignError("producer_budget_derivation_invalid")
    with PersistentBudgetLedger(
        ledger_path,
        batch_id=_PRODUCER_BATCH_ID,
        total_cap_usd=active_cap,
        max_runs=contract.producer.max_runs,
        default_run_cap_usd=contract.producer.run_cap_usd,
        usage_envelope=envelope,
        unpriced_stop_threshold=1,
        unpriced_fallback_usd=reservation,
        reservation_upstream_attempts=provider.max_attempts,
    ) as ledger:
        _claim_or_resume_producer_run(ledger, producer_run_id, run_cap)
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
            max_guardian_logical_requests=0,
            max_concurrent_main=_PRODUCER_MAX_CONCURRENT_MAIN,
            usage_envelope=envelope,
            timeout_seconds=180,
        ) as budget_proxy:
            with tempfile.TemporaryDirectory(
                prefix="plan102-producer-",
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
                        expected_descriptor=contract.backend.service_descriptor,
                        call_timeout_ms=contract.backend.client_call_timeout_ms,
                        startup_timeout_ms=contract.backend.client_startup_timeout_ms,
                        model=provider.main_model,
                        effort=provider.main_effort,
                        member_model=provider.main_model,
                        member_effort=provider.main_effort,
                        instruction=PLAN102_PRODUCER_FORMAL_PROMPT,
                        member_instruction=PLAN102_PRODUCER_MEMBER_PROMPT,
                    )
                    separator = command.index("--")
                    command = [
                        *command[:separator],
                        "-c",
                        f"features.multi_agent_v2.default_wait_timeout_ms={_PRODUCER_WAIT_TIMEOUT_MS}",
                        *command[separator:],
                    ]
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
                # Check the process first: a failed or timed-out `codex` leaves a
                # truncated trace, and loading it first reports the truncation
                # instead of the reason the run died.
                if completed.returncode != 0:
                    raise Plan102CampaignError("producer_process_failed")
                trace = _load_producer_trace(trace_root)
                evidence, rewrite_then_retry = _producer_evidence(
                    wire, trace, metadata_path, require_canonical=require_canonical
                )
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
        raise Plan102CampaignError("producer_budget_receipt_missing")
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
        raise Plan102CampaignError("producer_budget_not_cleanly_settled")
    return {
        **evidence,
        "rewrite_then_retry": rewrite_then_retry,
        "budget_run_id": producer_run_id,
        "request_count": len(requests),
        "spent_usd": run["spent_usd"],
        "run_stopped": run["stopped"],
        "provider_profile_sha256": provider.profile_sha256,
        "model": provider.main_model,
        "effort": provider.main_effort,
        "private_wire_and_trace_removed_before_receipt": True,
    }


def _producer_evidence(
    wire: str,
    trace: Any,
    metadata_path: Path,
    *,
    require_canonical: bool,
) -> tuple[dict[str, Any], bool]:
    try:
        diagnostic = project_producer_attempts(wire, trace)
    except ProducerEvidenceError:
        diagnostic = {
            "schema": "rondo-publication-critic-plan102-producer-failure-v1",
            "projection_status": "unavailable",
            "attempts": [],
        }
    attempts = diagnostic.get("attempts")
    rewrite_then_retry = (
        isinstance(attempts, list)
        and len(attempts) >= 2
        and any(
            isinstance(row, Mapping) and row.get("result_kind") == "rewrite_required"
            for row in attempts
        )
    )
    try:
        evidence = evaluate_producer_evidence(wire, trace)
        return evidence, True
    except ProducerEvidenceError as exc:
        error_code = str(exc)
        if not re.fullmatch(r"[a-z0-9_]{1,120}", error_code):
            error_code = "producer_evidence_invalid"
        _write_private_diagnostic(
            metadata_path.with_name(f"{metadata_path.stem}-evidence-failure.json"),
            {**diagnostic, "error_code": error_code},
        )
        if require_canonical or not rewrite_then_retry:
            raise Plan102CampaignError(f"producer_evidence_failed:{error_code}") from exc
        return {
            "schema_version": 1,
            "status": "rewrite_observed_canonical_not_required",
            "error_code": error_code,
            "publish_attempt_count": len(attempts) if isinstance(attempts, list) else 0,
        }, True


def _start_judge_proxy(
    paths: Plan102Paths, contract: Plan102Contract
) -> CloudBudgetProxy:
    runtime_config = load_runtime_config(paths.repos)
    provider = runtime_config.provider("deepseek")
    descriptor_provider = contract.backend.descriptor_document["provider"]
    if (
        provider.get("api") != "chat_completions"
        or provider.get("model") != descriptor_provider["model"]
        or provider.get("base_url") != descriptor_provider["base_url"]
        or provider.get("api_key_env") != descriptor_provider["api_key_env"]
    ):
        raise Plan102CampaignError("cloud_provider_configuration_drift")
    secret_name = provider["api_key_env"]
    secret = load_allowlisted_secret_values(paths.repos, (secret_name,))[secret_name]
    snapshot = _judge_budget_snapshot(paths, contract)
    remaining = Decimal(snapshot["remaining_rmb"])
    if remaining < contract.budgets.judge_reservation_rmb:
        raise Plan102CampaignError("judge_budget_exhausted")
    ledger_path = paths.runtime_root / f"budget/{_CLOUD_LEDGER_NAME}"
    return CloudBudgetProxy(
        upstream_endpoint=provider["base_url"].rstrip("/") + "/chat/completions",
        upstream_api_key=secret,
        ledger_path=ledger_path,
        cap_rmb=contract.budgets.judge_rmb,
        timeout_seconds=90,
        identity=contract.cloud_budget_identity,
    )


def _judge_budget_snapshot(
    paths: Plan102Paths, contract: Plan102Contract
) -> dict[str, Any]:
    ledger_path = paths.runtime_root / f"budget/{_CLOUD_LEDGER_NAME}"
    if not ledger_path.exists():
        return {
            "schema": contract.cloud_budget_identity.schema,
            "cap_rmb": _decimal_text(contract.budgets.judge_rmb),
            "conservative_charged_rmb": "0",
            "remaining_rmb": _decimal_text(contract.budgets.judge_rmb),
            "attempt_count": 0,
        }
    ledger = _read_json(ledger_path, "judge_ledger")
    if ledger.get("schema") != contract.cloud_budget_identity.schema:
        raise Plan102CampaignError("judge_ledger_identity_invalid")
    charged = Decimal("0")
    attempts = ledger.get("attempts")
    if not isinstance(attempts, list):
        raise Plan102CampaignError("judge_ledger_invalid")
    for row in attempts:
        if not isinstance(row, Mapping):
            raise Plan102CampaignError("judge_ledger_invalid")
        charged += Decimal(str(row["conservative_charge_rmb"]))
    remaining = contract.budgets.judge_rmb - charged
    if remaining < 0:
        raise Plan102CampaignError("judge_ledger_over_cap")
    return {
        "schema": contract.cloud_budget_identity.schema,
        "cap_rmb": _decimal_text(contract.budgets.judge_rmb),
        "conservative_charged_rmb": _decimal_text(charged),
        "remaining_rmb": _decimal_text(remaining),
        "attempt_count": len(attempts),
    }


def _load_producer_trace(trace_root: Path):
    """Load the rollout trace, keeping the reason it failed as a stable code.

    Every `TraceError` message in `multi_m5.trace` is a fixed literal, so
    folding it into the failure code stays body-free and tells a later run what
    to look at instead of collapsing to the exception class name.
    """

    try:
        return load_rollout_trace(find_trace_bundle(trace_root))
    except TraceError as exc:
        slug = re.sub(r"[^a-z0-9]+", "_", str(exc).lower()).strip("_")
        raise Plan102CampaignError(f"producer_trace_invalid:{slug}"[:160]) from exc


def _producer_generation_spend(
    paths: Plan102Paths, batch_id: str, ledger_name: str
) -> tuple[Decimal, int]:
    ledger_path = paths.runtime_root / f"budget/{ledger_name}"
    if not ledger_path.exists():
        return Decimal("0"), 0
    ledger = _read_json(ledger_path, "producer_ledger")
    if ledger.get("batch_id") != batch_id:
        raise Plan102CampaignError("producer_ledger_identity_invalid")
    runs = ledger.get("runs")
    if not isinstance(runs, Mapping):
        raise Plan102CampaignError("producer_ledger_invalid")
    spent = Decimal("0")
    for run in runs.values():
        if not isinstance(run, Mapping):
            raise Plan102CampaignError("producer_ledger_invalid")
        spent += Decimal(str(run.get("spent_usd", "0")))
    return spent, len(runs)


def _producer_retired_spend(paths: Plan102Paths) -> Decimal:
    """Sum what every retired generation already charged against the task cap."""

    spent = Decimal("0")
    for batch_id, ledger_name in _PRODUCER_LEDGER_GENERATIONS[:-1]:
        generation, _ = _producer_generation_spend(paths, batch_id, ledger_name)
        spent += generation
    return spent


def _producer_budget_snapshot(
    paths: Plan102Paths, contract: Plan102Contract
) -> dict[str, Any]:
    spent = Decimal("0")
    run_count = 0
    for batch_id, ledger_name in _PRODUCER_LEDGER_GENERATIONS:
        generation, generation_runs = _producer_generation_spend(
            paths, batch_id, ledger_name
        )
        spent += generation
        run_count += generation_runs
    remaining = contract.budgets.producer_usd - spent
    if remaining < 0:
        raise Plan102CampaignError("producer_ledger_over_cap")
    return {
        "batch_id": _PRODUCER_BATCH_ID,
        "generations": [batch_id for batch_id, _ in _PRODUCER_LEDGER_GENERATIONS],
        "spent_usd": _decimal_text(spent),
        "remaining_usd": _decimal_text(remaining),
        "run_count": run_count,
    }


def _extrapolate_budgets(
    paths: Plan102Paths,
    contract: Plan102Contract,
    judge_budget: Mapping[str, Any],
    producer: Mapping[str, Any] | None,
) -> dict[str, Any]:
    attempts = [
        row
        for row in judge_budget.get("attempts", [])
        if isinstance(row, Mapping) and row.get("state") == "usage_priced"
    ]
    if attempts:
        judge_per_call = sum(
            (Decimal(str(row["actual_charge_rmb"])) for row in attempts),
            start=Decimal("0"),
        ) / len(attempts)
    else:
        judge_per_call = contract.budgets.judge_missing_usage_rmb
    charged = Decimal(str(judge_budget["conservative_charged_rmb"]))
    b2_judge = charged + judge_per_call * _B2_JUDGE_CALL_EXTRAPOLATION
    if producer is not None and producer.get("request_count"):
        producer_per = Decimal(str(producer["spent_usd"])) / int(
            producer["request_count"]
        )
        producer_spent = Decimal(str(producer["spent_usd"]))
    else:
        producer_per = _PLAN097_PRODUCER_USD_PER_REQUEST
        producer_spent = Decimal(_producer_budget_snapshot(paths, contract)["spent_usd"])
    b2_producer = producer_spent + producer_per * _B2_PRODUCER_REQUEST_EXTRAPOLATION
    return {
        "judge_per_call_rmb": _decimal_text(judge_per_call),
        "b2_judge_projected_rmb": _decimal_text(b2_judge),
        "b2_judge_within_cap": b2_judge <= contract.budgets.judge_rmb,
        "producer_per_request_usd": _decimal_text(producer_per),
        "b2_producer_projected_usd": _decimal_text(b2_producer),
        "b2_producer_within_cap": b2_producer <= contract.budgets.producer_usd,
        "within_both_caps": (
            b2_judge <= contract.budgets.judge_rmb
            and b2_producer <= contract.budgets.producer_usd
        ),
    }


def _claim_or_resume_producer_run(
    ledger: PersistentBudgetLedger, producer_run_id: str, run_cap: Decimal
) -> None:
    runs = ledger.snapshot().get("runs")
    if isinstance(runs, Mapping) and producer_run_id in runs:
        ledger.resume_pristine_run(producer_run_id, cap_usd=run_cap)
        return
    ledger.claim_run(producer_run_id, cap_usd=run_cap)


def _require_secrets(paths: Plan102Paths) -> None:
    env_path = paths.repos.common_root / ".env.local"
    try:
        metadata = env_path.lstat()
    except OSError as exc:
        raise Plan102CampaignError("env_local_missing") from exc
    if env_path.is_symlink() or not env_path.is_file():
        raise Plan102CampaignError("env_local_unsafe")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise Plan102CampaignError("env_local_permissions_invalid")
    load_allowlisted_secret_values(paths.repos, ("DEEPSEEK_API_KEY",))
    load_provider_secret(load_runtime_config(paths.repos))


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
        raise Plan102CampaignError("source_identity_unavailable")
    revision = commit.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise Plan102CampaignError("source_commit_invalid")
    return {"commit": revision, "dirty": bool(status.stdout)}


def _codex_environment(
    *, home: Path, trace_root: Path, downstream_key: str
) -> dict[str, str]:
    if not downstream_key or "\n" in downstream_key or "\r" in downstream_key:
        raise Plan102CampaignError("downstream_key_invalid")
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
    paths: Plan102Paths, run_id: str, filename: str, value: Mapping[str, Any]
) -> Path:
    _require_run_id(run_id)
    namespace = WriteOnceNamespace(
        paths.runtime_root / "runs",
        run_id,
        validate_run_id=lambda candidate: _RUN_ID.fullmatch(candidate) is not None,
    )
    namespace.create(exist_ok=filename != "preflight.json")
    if filename != "preflight.json" and not (namespace.path / "preflight.json").is_file():
        raise Plan102CampaignError("preflight_receipt_missing")
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
        raise Plan102CampaignError("receipt_not_json") from exc
    if len(body) > _MAX_RECEIPT_BYTES:
        raise Plan102CampaignError("receipt_too_large")
    return namespace.write_bytes(filename, body)


def _existing_run_root(paths: Plan102Paths, run_id: str) -> Path:
    root = paths.run_root(run_id)
    if root.is_symlink() or not root.is_dir() or not (root / "preflight.json").is_file():
        raise Plan102CampaignError("run_preflight_missing")
    return root


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise Plan102CampaignError(f"{label}_missing")
    metadata = path.stat()
    if metadata.st_size <= 0 or metadata.st_size > _MAX_RECEIPT_BYTES:
        raise Plan102CampaignError(f"{label}_unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise Plan102CampaignError(f"{label}_invalid") from exc
    if not isinstance(value, dict):
        raise Plan102CampaignError(f"{label}_invalid")
    return value


def _assert_body_free_file(path: Path, *, forbidden: Sequence[str]) -> None:
    if path.is_symlink() or not path.is_file():
        raise Plan102CampaignError("body_free_metadata_missing")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise Plan102CampaignError("body_free_metadata_permissions_invalid")
    raw = path.read_bytes()
    for value in forbidden:
        if value and value.encode("utf-8") in raw:
            raise Plan102CampaignError("body_free_metadata_leak")


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
        raise Plan102CampaignError("private_diagnostic_invalid") from exc
    if not body or len(body) > _MAX_RECEIPT_BYTES:
        raise Plan102CampaignError("private_diagnostic_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise Plan102CampaignError("private_diagnostic_output_exists") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())


def _require_run_id(value: str) -> None:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise Plan102CampaignError("run_id_invalid")


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
        raise Plan102CampaignError(timeout_code) from None
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
        raise Plan102CampaignError("owned_process_group_not_reaped")


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
        description="Run bounded Plan 102 five-dimension cloud-seam steps"
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--run-id", required=True)
    preflight.add_argument("--require-clean", action="store_true")
    judge = subparsers.add_parser("judge")
    judge.add_argument("--run-id", required=True)
    producer = subparsers.add_parser("producer")
    producer.add_argument("--run-id", required=True)
    producer.add_argument("--producer-run-id", required=True)
    e2e = subparsers.add_parser("e2e")
    e2e.add_argument("--run-id", required=True)
    e2e.add_argument("--producer-run-id", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preflight":
            output = record_preflight(
                args.repo_root, run_id=args.run_id, require_clean=args.require_clean
            )
        elif args.command == "judge":
            output = run_judge_step(args.repo_root, run_id=args.run_id)
        elif args.command == "producer":
            output = run_producer_step(
                args.repo_root,
                run_id=args.run_id,
                producer_run_id=args.producer_run_id,
            )
        else:
            output = run_e2e_step(
                args.repo_root,
                run_id=args.run_id,
                producer_run_id=args.producer_run_id,
            )
    except (Plan102CampaignError, OSError, RuntimeError, ValueError) as exc:
        code = str(exc)
        if not re.fullmatch(r"[a-z0-9_:-]{1,160}", code):
            kind = type(exc).__name__
            folded = re.sub(r"[^a-z0-9]+", "_", kind.lower()).strip("_")
            code = folded or "unclassified_campaign_failure"
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
