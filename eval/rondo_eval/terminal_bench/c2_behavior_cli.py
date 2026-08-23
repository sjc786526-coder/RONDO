"""Operator CLI for the narrow Plan 058 C2 campaign."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..api_budget_proxy import PersistentBudgetLedger, load_validated_budget_ledger_state
from ..config import RepoPaths, load_provider_secret, load_runtime_config
from ..contracts import BinaryManifest, Product, RunOutcome, Side
from ..docker_supervisor import DockerSupervisionError
from ..harness_observation import _read_api_metadata, project_task_observation
from ..runtime_bridge import (
    DockerCliCounter,
    PowerShellDockerDesktopHostProbe,
    RuntimeBridgeError,
    lease_from_watchdog,
)
from .baseline_cli import (
    CampaignExecutionError,
    CampaignExecutionLease,
    StorageBaseline,
    _load_or_create_storage_baseline,
    _locked_worker_environment,
    _require_held_campaign_lease,
    _sample_storage,
)
from .adapters import AGENT_EXECUTION_RECEIPT_FILENAME
from .bounded_observation import (
    BoundedObservationError,
    _atomic_json,
    _read_json,
    _read_regular,
)
from .bounded_observation_cli import (
    _has_sent_attempt,
    _metadata_request_ids,
    _meaningful_request_ids,
    _revalidate_record_sources,
    _source_binding,
    _source_file_sha256,
    _storage_projection,
    _validate_guardian_binding,
)
from .c2_behavior import (
    PLAN058_KIND,
    PLAN058_PAID_ACTION,
    PLAN058_POINTER_RELPATH,
    PLAN058_PHYSICAL_RUN_BUDGET_USD,
    PLAN058_UNPRICED_FALLBACK_USD,
    C2BehaviorError,
    C2BehaviorIdentity,
    C2BehaviorSlot,
    C2BehaviorState,
    budget_path,
    build_slot_record,
    campaign_root,
    classify_provider_hard_stop,
    classify_pure_transport_retry,
    close_envelope_and_pointer,
    initialize_identity,
    load_identity,
    load_slot_records,
    preflight_receipt_path,
    public_result,
    slot_record_path,
    slot_root,
    state_path,
    validate_slot_record,
    verify_task_budget,
)
from .live import load_guardian_evidence_bundle, run_budgeted_terminal_bench_core
from .materialize import validate_frozen_task_source
from .pair import (
    load_historical_pair_identity,
    validate_harbor_installation,
)
from .preflight_producer import (
    PREFLIGHT_STUB_BEARER,
    PreflightCaptureServer,
    _request_trace,
)
from .results import classify_terminal_bench_result, parse_single_task_result
from .runner import (
    HARBOR_EXECUTABLE,
    DockerSupervisedHostHarborExecutor,
    InjectedHostHarborBackend,
    TerminalBenchRequest,
    UnifiedTerminalBenchRunner,
    enable_local_harness_observation,
    prepare_terminal_bench_run,
)


_SOURCE_CHECKOUT_RELPATH = Path("eval-data/sources/terminal-bench-2-1-ffccbe05")
_DEFAULT_METRICS_RELPATH = Path("eval-data/build/plan058-watchdog")
_DOCKER_COUNTER_SAMPLE_TIMEOUT_SECONDS = 60.0
_DOCKER_FACT_COMMAND_MAX_ATTEMPTS = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rondo-direction1-c2")
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=(
            "status",
            "initialize",
            "preflight",
            "run",
            "resume",
            "classification-template",
            "finalize",
        ),
    )
    parser.add_argument("--campaign-id")
    parser.add_argument("--batch-id")
    parser.add_argument(
        "--campaign-mode", choices=("commissioning", "diagnostic", "formal")
    )
    parser.add_argument("--result-namespace")
    parser.add_argument("--public-result-path", type=Path)
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--run-id-date")
    parser.add_argument("--run-id-sequence-base", type=int)
    parser.add_argument("--commissioning-task-id")
    parser.add_argument("--diagnostic-slot-start", type=int)
    parser.add_argument("--diagnostic-slot-end", type=int)
    parser.add_argument("--docker-host-volume", type=Path)
    parser.add_argument("--metrics-dir", type=Path)
    parser.add_argument("--paid-action")
    parser.add_argument("--snapshot-date", default="2026-08-22")
    parser.add_argument("--refined-classification", type=Path)
    parser.add_argument("--worker-mode", choices=("preflight", "paid"), help=argparse.SUPPRESS)
    parser.add_argument("--campaign-lease-token", help=argparse.SUPPRESS)
    return parser


def status(paths: RepoPaths) -> dict[str, Any]:
    """Read campaign state and ignored accounting without config, secret, or API."""

    pointer_path = paths.worktree_root / PLAN058_POINTER_RELPATH
    if not pointer_path.exists() and not pointer_path.is_symlink():
        return {"status": "uninitialized", "paid_requests_sent": 0}
    pointer = _read_json(pointer_path)
    if pointer.get("last_lock") is None:
        return {"status": "awaiting_initialization", "paid_requests_sent": 0}
    identity = load_identity(paths, allow_retired=True)
    state = _read_json(state_path(paths, identity))
    ledger_path = budget_path(paths, identity)
    budget = (
        _load_budget_snapshot(paths, identity)
        if ledger_path.exists() and not ledger_path.is_symlink()
        else None
    )
    attempts = (
        sum(
            int(request["attempt_count"])
            for run in budget["runs"].values()
            for request in run["requests"].values()
        )
        if budget is not None
        else 0
    )
    result = {
        "status": state["status"],
        "campaign_id": identity.campaign_id,
        "campaign_mode": identity.campaign_mode,
        "campaign_lock_sha256": identity.lock_sha256,
        "preflight_complete": sum(row["status"] == "complete" for row in state["preflight"]),
        "logical_results_published": sum(row["status"] == "published" for row in state["slots"]),
        "logical_denominator": len(identity.slots),
        "transport_retries": sum(len(row["transport_retries"]) for row in state["slots"]),
        "paid_boundary": state["paid_boundary"],
        "durable_upstream_attempts": attempts,
        "estimated_usd": budget["spent_usd"] if budget is not None else "0.000000",
        "reserved_usd": budget["reserved_usd"] if budget is not None else "0.000000",
        "invalid_reason": state["invalid_reason"],
        "paid_requests_sent": 0,
    }
    if identity.campaign_mode == "diagnostic":
        result["diagnostic_slot_range"] = identity.value["diagnostic_slot_range"]
    return result


def _load_budget_snapshot(paths: RepoPaths, identity: C2BehaviorIdentity) -> dict[str, Any]:
    value = load_validated_budget_ledger_state(
        budget_path(paths, identity),
        batch_id=identity.batch_id,
        total_cap_usd=identity.campaign_cap_usd,
        max_runs=len(identity.slots),
        default_run_cap_usd=identity.campaign_cap_usd,
        unpriced_fallback_usd=PLAN058_UNPRICED_FALLBACK_USD,
        unpriced_fallback_per_attempt=True,
        reservation_upstream_attempts=1,
    )
    spent = sum((Decimal(str(run["spent_usd"])) for run in value["runs"].values()), Decimal(0))
    reserved = sum(
        (
            Decimal(str(request["reserved_usd"]))
            for run in value["runs"].values()
            for request in run["requests"].values()
            if request["status"] == "reserved"
        ),
        Decimal(0),
    )
    snapshot = dict(value)
    snapshot.update(
        run_slots_used=len(value["runs"]),
        spent_usd=f"{spent:.6f}",
        reserved_usd=f"{reserved:.6f}",
    )
    return snapshot


def _budget_ledger(
    paths: RepoPaths, identity: C2BehaviorIdentity
) -> PersistentBudgetLedger:
    return PersistentBudgetLedger(
        budget_path(paths, identity),
        batch_id=identity.batch_id,
        total_cap_usd=identity.campaign_cap_usd,
        max_runs=len(identity.slots),
        default_run_cap_usd=identity.campaign_cap_usd,
        unpriced_fallback_usd=PLAN058_UNPRICED_FALLBACK_USD,
        unpriced_fallback_per_attempt=True,
        reservation_upstream_attempts=1,
        usage_envelope=identity.usage_envelope,
    )


def _make_request(
    *,
    paths: RepoPaths,
    identity: C2BehaviorIdentity,
    task: Any,
    manifest: BinaryManifest,
    work_root: Path,
    docker_task_id: str,
    seccomp_profile: Path,
    stub: bool,
) -> TerminalBenchRequest:
    request = TerminalBenchRequest(
        side=Side.RONDO,
        batch_id=identity.batch_id,
        binary=manifest,
        product=Product.RONDO_LOCAL,
        image_digest=task.image_digest,
        source_checkout=str(paths.common_root / _SOURCE_CHECKOUT_RELPATH),
        staging_root=str(work_root / "staging"),
        docker_task_id=docker_task_id,
        memory_bytes=task.memory_mb * 1024**2,
        memory_swap_bytes=(task.memory_mb + 1024) * 1024**2,
        pids_limit=task.pids_limit,
        provider_transport_base_url=None,
        timeout_seconds=task.timeout_seconds,
        max_retries=0,
        budget_usd=float(PLAN058_PHYSICAL_RUN_BUDGET_USD),
        seccomp_profile_path=str(seccomp_profile),
        seccomp_profile_source_sha256=identity.value["seccomp"]["source_sha256"],
        seccomp_profile_effective_sha256=identity.value["seccomp"]["effective_sha256"],
        require_container_metrics=True,
        frozen_task=task,
        stub_verifier=stub,
        delete_environment=not stub,
        pinned_model_id=identity.value["provider"]["public_profile"]["main_model"],
        pinned_main_effort=identity.value["provider"]["public_profile"]["main_effort"],
        pinned_guardian_effort=identity.value["provider"]["public_profile"]["guardian_effort"],
        exec_command_repeat_guidance_enabled=True,
        plan058_agent_execution_id=None if stub else docker_task_id,
    )
    return enable_local_harness_observation(request)


def _validate_prepared(
    prepared: Any,
    *,
    identity: C2BehaviorIdentity,
    task: Any,
    manifest: BinaryManifest,
    stub: bool,
) -> None:
    spec = prepared.spec
    if (
        spec.side is not Side.RONDO
        or spec.effective_product() is not Product.RONDO_LOCAL
        or spec.batch_id != identity.batch_id
        or spec.task_id != task.task_id
        or spec.task_image_digest != task.image_digest
        or spec.binary != manifest
        or spec.provider.to_public_dict() != identity.value["provider"]["public_profile"]
        or prepared.adapter.rollout_trace_root != "/logs/agent/rollout-trace"
        or prepared.command.stub_verifier is not stub
        or prepared.command.delete_environment is stub
        or prepared.adapter._exec_command_repeat_guidance_enabled is not True
        or prepared.adapter._plan058_agent_execution_id
        != (None if stub else prepared.materialized_task.task_label.removeprefix(
            "dev.rondo.eval.task="
        ))
    ):
        raise C2BehaviorError("Plan 058 prepared run differs from its lock")


def _worker_inputs(paths: RepoPaths, args: argparse.Namespace) -> tuple[Any, ...]:
    if args.docker_host_volume is None:
        raise C2BehaviorError("Plan 058 Docker host volume is required")
    identity = load_identity(paths)
    _require_held_campaign_lease(
        campaign_root(paths, identity) / "executor.lock",
        args.campaign_lease_token,
    )
    identity.validate_runtime_checkout(paths)
    config = load_runtime_config(paths)
    provider = identity.provider_projection(config)
    proxy_provider = replace(provider, max_attempts=1)
    manifest = identity.manifest(paths)
    seccomp = identity.seccomp_profile(paths)
    validate_harbor_installation(load_historical_pair_identity(), executable=HARBOR_EXECUTABLE)
    proof = lease_from_watchdog()
    counter = DockerCliCounter(
        host_data_root=args.docker_host_volume,
        desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        probe_timeout_seconds=_DOCKER_COUNTER_SAMPLE_TIMEOUT_SECONDS,
        command_max_attempts=_DOCKER_FACT_COMMAND_MAX_ATTEMPTS,
    )
    baseline = _load_or_create_storage_baseline(
        campaign_root(paths, identity), counter, identity.slots[0].logical_run_id
    )
    return identity, config, manifest, seccomp, proxy_provider, counter, baseline, proof


def _transition_preflight_worker_failure(
    state: C2BehaviorState,
    *,
    identity: C2BehaviorIdentity,
    reason: str,
) -> None:
    snapshot = state.snapshot()
    running = next(
        (row for row in snapshot["preflight"] if row["status"] == "running"),
        None,
    )
    if identity.campaign_mode == "formal" and snapshot["status"] == "running":
        state.invalidate(f"formal_preflight_failed:{reason}")
    elif running is not None:
        state.fail_preflight(str(running["task_id"]), reason=reason)


def _preflight_worker(paths: RepoPaths, args: argparse.Namespace) -> int:
    try:
        return _preflight_worker_inner(paths, args)
    except BaseException as exc:
        try:
            identity = load_identity(paths)
            with C2BehaviorState(
                state_path(paths, identity), identity=identity
            ) as state:
                _transition_preflight_worker_failure(
                    state,
                    identity=identity,
                    reason=type(exc).__name__,
                )
        except BaseException:
            pass
        raise


def _preflight_worker_inner(paths: RepoPaths, args: argparse.Namespace) -> int:
    identity, config, manifest, seccomp, provider, counter, baseline, proof = _worker_inputs(paths, args)
    _sample_storage(counter, identity.slots[0].logical_run_id, baseline=baseline)
    with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
        claimed = state.claim_preflight()
        terminal = state.snapshot()["status"]
    if claimed is None:
        if terminal == "invalid":
            _store_final_storage(
                paths=paths,
                identity=identity,
                counter=counter,
                baseline=baseline,
            )
            return 3
        return 0
    task_id, attempt = claimed
    task = identity.task(task_id)
    destination = preflight_receipt_path(paths, identity, task)
    if destination.exists() and not destination.is_symlink():
        raw = _read_regular(destination)
        receipt = json.loads(raw)
        if receipt.get("campaign_lock_sha256") != identity.lock_sha256 or receipt.get("task_id") != task.task_id:
            raise C2BehaviorError("Plan 058 preflight receipt drifted")
        with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
            state.finish_preflight(task.task_id, receipt_sha256=hashlib.sha256(raw).hexdigest())
        return 10
    root = campaign_root(paths, identity) / "preflight-work" / task.slug / f"attempt-{attempt}"
    if root.exists() or root.is_symlink():
        raise C2BehaviorError("Plan 058 preflight attempt already exists")
    root.mkdir(parents=True, mode=0o700)
    validate_frozen_task_source(paths.common_root / _SOURCE_CHECKOUT_RELPATH, task)
    server = PreflightCaptureServer()
    try:
        with server:
            request = _make_request(
                paths=paths,
                identity=identity,
                task=task,
                manifest=manifest,
                work_root=root,
                docker_task_id=f"plan058-preflight-{task.slug}-a{attempt}",
                seccomp_profile=seccomp,
                stub=True,
            )
            projected = replace(request, provider_transport_base_url=server.docker_base_url)
            prepared = prepare_terminal_bench_run(config, projected)
            _validate_prepared(prepared, identity=identity, task=task, manifest=manifest, stub=True)
            executor = DockerSupervisedHostHarborExecutor(counter=counter, lock_guard=proof.guard, lease=proof.lease)
            backend = InjectedHostHarborBackend(
                executor,
                getenv=lambda name: PREFLIGHT_STUB_BEARER if name == prepared.spec.provider.api_key_env else None,
            )
            harbor = asyncio.run(UnifiedTerminalBenchRunner(backend).run(prepared))
            trace = _request_trace(server.bodies, provider=provider)
            if server.rejections:
                raise C2BehaviorError("Plan 058 preflight stub rejected a request")
        metadata_path = root / "stub-api-metadata.json"
        _atomic_json(
            metadata_path,
            {
                "schema_version": 1,
                "requests": [
                    {
                        "request_id": f"preflight-{index}",
                        "role": role,
                        "role_provenance": "declared",
                        "declared_role": role,
                        "inferred_role": role,
                        "contract_match": True,
                        "usage_valid": True,
                        "usage": {"input_tokens": 0, "cached_input_tokens": 0, "cache_write_input_tokens": 0, "output_tokens": 0},
                        "upstream_status": 200,
                        "attempt_count": 1,
                        "stream": True,
                        "stream_end_kind": "terminal",
                        "terminal_event_type": "response.completed",
                        "terminal_response_status": "completed",
                        "terminal_error_code": None,
                    }
                    for index, (role, _body) in enumerate(trace, start=1)
                ],
            },
            mode=0o600,
        )
        observation = project_task_observation(harbor.trial_dir / "agent" / "rollout-trace", metadata_path)
        if harbor.docker_evidence is None:
            raise C2BehaviorError("Plan 058 preflight lacks Docker evidence")
        receipt = {
            "schema_version": 1,
            "kind": PLAN058_KIND + "_preflight",
            "campaign_lock_sha256": identity.lock_sha256,
            "task_id": task.task_id,
            "request_roles": [role for role, _body in trace],
            "request_body_sha256": [
                hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                for _role, body in trace
            ],
            "observation_sha256": hashlib.sha256(json.dumps(observation, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "docker": harbor.docker_evidence.receipt(),
            "upstream_api_requests": 0,
            "estimated_usd": "0.000000",
        }
        _atomic_json(destination, receipt, mode=0o600)
        raw = _read_regular(destination)
        _sample_storage(counter, identity.slots[0].logical_run_id, baseline=baseline)
        with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
            state.finish_preflight(task.task_id, receipt_sha256=hashlib.sha256(raw).hexdigest())
        return 10
    except BaseException as exc:
        with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
            state.fail_preflight(task.task_id, reason=type(exc).__name__)
        if identity.campaign_mode == "formal":
            _store_final_storage(
                paths=paths,
                identity=identity,
                counter=counter,
                baseline=baseline,
            )
        raise


def _write_slot_record(
    *,
    paths: RepoPaths,
    identity: C2BehaviorIdentity,
    slot: C2BehaviorSlot,
    attempt: int,
    attempt_run_id: str,
    transport_retries: list[Mapping[str, Any]],
    live: Any,
    parsed: Any,
    metadata_path: Path,
) -> str:
    run = live.budget_snapshot["runs"].get(slot.logical_run_id)
    if not isinstance(run, Mapping):
        raise C2BehaviorError("Plan 058 logical budget run is unavailable")
    request_ids = _metadata_request_ids(metadata_path)
    attempt_budget = _attempt_budget_projection(run, request_ids=request_ids)
    if _meaningful_request_ids(attempt_budget) != request_ids:
        raise C2BehaviorError("Plan 058 budget and API request identities differ")
    execution_receipt = _read_agent_execution_receipt(
        live.harbor.trial_dir / "agent" / AGENT_EXECUTION_RECEIPT_FILENAME
    )
    if parsed.outcome is RunOutcome.AGENT_FAILED:
        if not _is_typed_guardian_limit_result(
            parsed,
            budget_run=attempt_budget,
            receipt=execution_receipt,
            api_metadata={
                "schema_version": 1,
                "requests": _read_api_metadata(metadata_path),
            },
            evidence=live.evidence,
            max_guardian_logical_requests=identity.max_guardian_logical_requests,
            expected_execution_id=attempt_run_id,
            metadata_ready=live.metadata_ready,
        ):
            raise C2BehaviorError("Plan 058 typed Guardian stop is invalid")
    else:
        _validate_guardian_binding(live, parsed, metadata_path)
    observation = project_task_observation(live.harbor.trial_dir / "agent" / "rollout-trace", metadata_path)
    if live.harbor.docker_evidence is None:
        raise C2BehaviorError("Plan 058 slot lacks Docker evidence")
    record = build_slot_record(
        identity=identity,
        slot=slot,
        attempt=attempt,
        attempt_run_id=attempt_run_id,
        transport_retries=transport_retries,
        parsed=parsed,
        observation=observation,
        budget_run=attempt_budget,
        logical_budget=_logical_budget_summary(run, logical_run_id=slot.logical_run_id),
        docker_receipt=live.harbor.docker_evidence.receipt(),
        sources=_plan058_source_binding(
            paths=paths,
            identity=identity,
            live=live,
            metadata_path=metadata_path,
        ),
    )
    destination = slot_record_path(paths, identity, slot)
    _atomic_json(destination, record, mode=0o600)
    raw = _read_regular(destination)
    validate_slot_record(json.loads(raw), identity=identity, slot=slot)
    _revalidate_plan058_record_sources(
        paths=paths, identity=identity, slot=slot, record=record
    )
    return hashlib.sha256(raw).hexdigest()


def _recover_record_if_complete(
    *,
    paths: RepoPaths,
    identity: C2BehaviorIdentity,
    slot: C2BehaviorSlot,
    attempt: int,
    attempt_run_id: str,
    budget_snapshot: Mapping[str, Any],
) -> str | None:
    destination = slot_record_path(paths, identity, slot)
    if not destination.exists() and not destination.is_symlink():
        return None
    raw = _read_regular(destination)
    record = validate_slot_record(json.loads(raw), identity=identity, slot=slot)
    current = budget_snapshot.get("runs", {}).get(slot.logical_run_id)
    if (
        not isinstance(current, Mapping)
        or _json_sha256(current) != record["logical_budget"]["run_sha256"]
        or record["published_attempt"] != attempt
        or record["published_attempt_run_id"] != attempt_run_id
    ):
        raise C2BehaviorError("Plan 058 recovered record differs from durable state")
    _revalidate_plan058_record_sources(
        paths=paths, identity=identity, slot=slot, record=record
    )
    return hashlib.sha256(raw).hexdigest()


def _read_agent_execution_receipt(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(_read_regular(path, max_bytes=256))
    except (BoundedObservationError, UnicodeError, json.JSONDecodeError) as exc:
        raise C2BehaviorError("Plan 058 agent execution receipt is unavailable") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {
            "schema_version",
            "execution_id",
            "agent_exit_code",
            "tee_exit_code",
        }
        or value["schema_version"] != 1
        or not isinstance(value["execution_id"], str)
        or not value["execution_id"]
        or any(
            isinstance(value[name], bool)
            or not isinstance(value[name], int)
            or not 0 <= value[name] <= 255
            for name in ("agent_exit_code", "tee_exit_code")
        )
    ):
        raise C2BehaviorError("Plan 058 agent execution receipt is invalid")
    return {
        "execution_id": value["execution_id"],
        "exit_code": value["agent_exit_code"],
        "tee_exit_code": value["tee_exit_code"],
    }


def _guardian_source_bindings(
    *, paths: RepoPaths, identity: C2BehaviorIdentity, live: Any
) -> list[dict[str, str]]:
    root = campaign_root(paths, identity)
    values: list[dict[str, str]] = []
    for evidence in live.evidence:
        observation, e_final, meta = load_guardian_evidence_bundle(
            live.harbor.trial_dir,
            evidence.relative_path,
            expected_model=identity.value["provider"]["public_profile"][
                "guardian_model"
            ],
            expected_effort=identity.value["provider"]["public_profile"][
                "guardian_effort"
            ],
        )
        if observation != evidence:
            raise C2BehaviorError("Plan 058 Guardian evidence changed during binding")
        e_final_path = live.harbor.trial_dir / evidence.relative_path
        meta_path = e_final_path.with_name("meta.json")
        e_final_relative, e_final_sha256 = _source_file_sha256(root, e_final_path)
        meta_relative, meta_sha256 = _source_file_sha256(root, meta_path)
        if (
            hashlib.sha256(e_final).hexdigest() != e_final_sha256
            or hashlib.sha256(meta).hexdigest() != meta_sha256
        ):
            raise C2BehaviorError("Plan 058 Guardian source digest changed")
        values.append(
            {
                "e_final_path": e_final_relative,
                "e_final_sha256": e_final_sha256,
                "meta_path": meta_relative,
                "meta_sha256": meta_sha256,
            }
        )
    return values


def _plan058_source_binding(
    *,
    paths: RepoPaths,
    identity: C2BehaviorIdentity,
    live: Any,
    metadata_path: Path,
) -> dict[str, Any]:
    sources = _source_binding(
        paths=paths,
        identity=identity,
        live=live,
        metadata_path=metadata_path,
    )
    root = campaign_root(paths, identity)
    receipt_path = live.harbor.trial_dir / "agent" / AGENT_EXECUTION_RECEIPT_FILENAME
    receipt = _read_agent_execution_receipt(receipt_path)
    relative, digest = _source_file_sha256(root, receipt_path)
    return {
        **sources,
        "agent_execution": {
            "path": relative,
            "sha256": digest,
            "execution_id": receipt["execution_id"],
            "exit_code": receipt["exit_code"],
            "tee_exit_code": receipt["tee_exit_code"],
        },
        "guardian_evidence": _guardian_source_bindings(
            paths=paths, identity=identity, live=live
        ),
    }


def _revalidate_plan058_record_sources(
    *,
    paths: RepoPaths,
    identity: C2BehaviorIdentity,
    slot: C2BehaviorSlot,
    record: Mapping[str, Any],
) -> None:
    sources = record["sources"]
    execution = sources["agent_execution"]
    root = campaign_root(paths, identity)
    receipt_path = root / execution["path"]
    relative, digest = _source_file_sha256(root, receipt_path)
    receipt = _read_agent_execution_receipt(receipt_path)
    if (
        relative != execution["path"]
        or digest != execution["sha256"]
        or receipt["execution_id"] != execution["execution_id"]
        or receipt["exit_code"] != execution["exit_code"]
        or receipt["tee_exit_code"] != execution["tee_exit_code"]
    ):
        raise C2BehaviorError("Plan 058 agent execution source drifted")
    terminal_result_path = root / sources["terminal_bench"]["path"]
    trial_dir = terminal_result_path.parent
    evidence = []
    for binding in sources["guardian_evidence"]:
        observation, e_final, meta = load_guardian_evidence_bundle(
            trial_dir,
            Path(binding["e_final_path"]).relative_to(
                Path(sources["terminal_bench"]["path"]).parent
            ).as_posix(),
            expected_model=identity.value["provider"]["public_profile"][
                "guardian_model"
            ],
            expected_effort=identity.value["provider"]["public_profile"][
                "guardian_effort"
            ],
        )
        if (
            hashlib.sha256(e_final).hexdigest() != binding["e_final_sha256"]
            or hashlib.sha256(meta).hexdigest() != binding["meta_sha256"]
            or _source_file_sha256(root, root / binding["e_final_path"])[1]
            != binding["e_final_sha256"]
            or _source_file_sha256(root, root / binding["meta_path"])[1]
            != binding["meta_sha256"]
        ):
            raise C2BehaviorError("Plan 058 Guardian evidence source drifted")
        evidence.append(observation)
    shared_record = json.loads(json.dumps(record))
    shared_record["sources"] = {
        key: sources[key]
        for key in ("terminal_bench", "api_metadata", "native_trace")
    }
    _revalidate_record_sources(
        paths=paths,
        identity=identity,
        slot=slot,
        record=shared_record,
        preserve_agent_failure_verifier_reward=True,
    )
    parsed = parse_single_task_result(
        trial_dir,
        host_returncode=sources["terminal_bench"]["host_returncode"],
        expected_task_id=slot.task_id,
        preserve_agent_failure_verifier_reward=True,
    )
    metadata_path = root / sources["api_metadata"]["path"]
    if record["terminal_bench"]["outcome"] == RunOutcome.AGENT_FAILED.value:
        if not _is_typed_guardian_limit_result(
            parsed,
            budget_run=record["budget"],
            receipt=receipt,
            api_metadata={
                "schema_version": 1,
                "requests": _read_api_metadata(metadata_path),
            },
            evidence=tuple(evidence),
            max_guardian_logical_requests=identity.max_guardian_logical_requests,
            expected_execution_id=slot.attempt_run_id(
                record["published_attempt"]
            ),
            metadata_ready=True,
        ):
            raise C2BehaviorError("Plan 058 typed agent failure cannot be replayed")


def _is_typed_guardian_limit_result(
    parsed: Any,
    *,
    budget_run: Mapping[str, Any],
    receipt: Mapping[str, Any],
    api_metadata: Mapping[str, Any],
    evidence: tuple[Any, ...],
    max_guardian_logical_requests: int,
    expected_execution_id: str,
    metadata_ready: bool,
) -> bool:
    """Match only the frozen Guardian-limit shape that Harbor can score."""

    trial = parsed.trial_result
    exception = trial.get("exception_info") if isinstance(trial, Mapping) else None
    verifier = trial.get("verifier_result") if isinstance(trial, Mapping) else None
    requests = api_metadata.get("requests")
    guardians = (
        [row for row in requests if isinstance(row, Mapping) and row.get("role") == "guardian"]
        if isinstance(requests, list)
        else []
    )
    metadata_hashes = [row.get("canonical_body_sha256") for row in guardians]
    terminal = [
        item
        for item in evidence
        if (item.decision, item.terminal_status, item.failure_reason)
        in {("approved", "approved", None), ("denied", "denied", None)}
    ]
    failed_closed = [
        item
        for item in evidence
        if (item.decision, item.terminal_status, item.failure_reason)
        == ("denied", "failed_closed", "session_error")
    ]
    evidence_hashes = [item.canonical_request_sha256 for item in evidence]
    return (
        metadata_ready
        and parsed.outcome is RunOutcome.AGENT_FAILED
        and isinstance(exception, Mapping)
        and exception.get("exception_type") == "NonZeroAgentExitCodeError"
        and isinstance(verifier, Mapping)
        and receipt == {
            "execution_id": expected_execution_id,
            "exit_code": 1,
            "tee_exit_code": 0,
        }
        and budget_run.get("stopped") is True
        and budget_run.get("stop_reason")
        == "guardian_logical_request_limit_exceeded"
        and len(guardians) == max_guardian_logical_requests
        and len(metadata_hashes) == len(set(metadata_hashes))
        and all(isinstance(item, str) and len(item) == 64 for item in metadata_hashes)
        and len(evidence) == max_guardian_logical_requests + 1
        and len(evidence_hashes) == len(set(evidence_hashes))
        and len(terminal) == max_guardian_logical_requests
        and len(failed_closed) == 1
        and {item.canonical_request_sha256 for item in terminal}
        == set(metadata_hashes)
        and failed_closed[0].canonical_request_sha256 not in set(metadata_hashes)
    )


def _classify_plan058_agent_execution(
    live: Any,
    parsed: Any,
    *,
    budget_run: Mapping[str, Any],
    receipt: Mapping[str, Any],
    metadata_path: Path,
    identity: C2BehaviorIdentity,
    expected_execution_id: str,
) -> Any:
    if receipt == {
        "execution_id": expected_execution_id,
        "exit_code": 0,
        "tee_exit_code": 0,
    }:
        if budget_run.get("stop_reason") == "guardian_logical_request_limit_exceeded":
            return replace(parsed, outcome=RunOutcome.INFRA_FAILED)
        return classify_terminal_bench_result(live, parsed)
    if _is_typed_guardian_limit_result(
        parsed,
        budget_run=budget_run,
        receipt=receipt,
        api_metadata={
            "schema_version": 1,
            "requests": _read_api_metadata(metadata_path),
        },
        evidence=live.evidence,
        max_guardian_logical_requests=identity.max_guardian_logical_requests,
        expected_execution_id=expected_execution_id,
        metadata_ready=live.metadata_ready,
    ):
        return parsed
    return replace(parsed, outcome=RunOutcome.INFRA_FAILED)


def _json_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _attempt_budget_projection(
    run: Mapping[str, Any], *, request_ids: set[str]
) -> dict[str, Any]:
    requests = run.get("requests")
    if not isinstance(requests, Mapping) or not request_ids:
        raise C2BehaviorError("Plan 058 attempt budget population is missing")
    selected = {
        str(request_id): json.loads(json.dumps(requests[request_id]))
        for request_id in sorted(request_ids)
        if request_id in requests
    }
    if set(selected) != request_ids:
        raise C2BehaviorError("Plan 058 attempt budget request binding is incomplete")
    value = json.loads(json.dumps(run))
    value["requests"] = selected
    value["spent_usd"] = f"{sum((Decimal(str(row['charged_usd'])) for row in selected.values()), Decimal(0)):.6f}"
    return value


def _logical_budget_summary(
    run: Mapping[str, Any], *, logical_run_id: str
) -> dict[str, Any]:
    requests = run.get("requests")
    if not isinstance(requests, Mapping) or not requests:
        raise C2BehaviorError("Plan 058 logical budget population is missing")
    return {
        "logical_run_id": logical_run_id,
        "run_sha256": _json_sha256(run),
        "spent_usd": f"{Decimal(str(run['spent_usd'])):.6f}",
        "request_count": len(requests),
        "upstream_attempts": sum(int(row["attempt_count"]) for row in requests.values()),
    }


def _attempt_transport_evidence(
    *,
    attempt: int,
    attempt_run_id: str,
    metadata_path: Path,
    budget_run: Mapping[str, Any],
    prior_retry_evidence: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not metadata_path.exists() or metadata_path.is_symlink():
        return None
    requests = _read_api_metadata(metadata_path)
    request_ids = {str(request["request_id"]) for request in requests}
    return classify_pure_transport_retry(
        attempt=attempt,
        attempt_run_id=attempt_run_id,
        api_metadata={"schema_version": 1, "requests": requests},
        budget_run=_attempt_budget_projection(budget_run, request_ids=request_ids),
        logical_budget_run=budget_run,
        prior_retry_evidence=prior_retry_evidence,
    )


def _provider_hard_stop(metadata_path: Path) -> str | None:
    if not metadata_path.exists() or metadata_path.is_symlink():
        return None
    return classify_provider_hard_stop(
        {"schema_version": 1, "requests": _read_api_metadata(metadata_path)}
    )


def _formal_attempt_interrupted_without_projection(
    *,
    campaign_mode: str,
    attempt_was_running: bool,
    work_root_existed: bool,
    metadata_path: Path,
) -> bool:
    return (
        campaign_mode in {"diagnostic", "formal"}
        and (attempt_was_running or work_root_existed)
        and not metadata_path.exists()
        and not metadata_path.is_symlink()
    )


def _transport_receipt_path(work_root: Path) -> Path:
    return work_root / "transport-retry.json"


def _write_transport_receipt(
    work_root: Path,
    *,
    evidence: Mapping[str, Any],
    docker_receipt: Mapping[str, Any],
) -> None:
    if docker_receipt.get("cleanup") != "verified_empty":
        raise C2BehaviorError("Plan 058 transport retry lacks clean Docker completion")
    _atomic_json(
        _transport_receipt_path(work_root),
        {
            "schema_version": 1,
            "kind": PLAN058_KIND + "_transport_retry",
            "evidence": dict(evidence),
            "docker": dict(docker_receipt),
        },
        mode=0o600,
    )


def _load_transport_receipt(
    work_root: Path,
    *,
    expected_evidence: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    path = _transport_receipt_path(work_root)
    if expected_evidence is None or not path.exists() or path.is_symlink():
        return None
    value = _read_json(path)
    if (
        set(value) != {"schema_version", "kind", "evidence", "docker"}
        or value["schema_version"] != 1
        or value["kind"] != PLAN058_KIND + "_transport_retry"
        or value["evidence"] != expected_evidence
        or not isinstance(value["docker"], dict)
        or value["docker"].get("cleanup") != "verified_empty"
    ):
        return None
    return dict(expected_evidence)


def _store_final_storage(
    *,
    paths: RepoPaths,
    identity: C2BehaviorIdentity,
    counter: DockerCliCounter,
    baseline: StorageBaseline,
) -> None:
    with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
        if state.snapshot()["final_storage"] is not None:
            return
    reason = None
    try:
        final = _sample_storage(counter, identity.slots[0].logical_run_id, baseline=baseline)
    except (CampaignExecutionError, DockerSupervisionError, RuntimeBridgeError) as exc:
        final = None
        reason = type(exc).__name__
    with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
        state.store_final_storage(_storage_projection(baseline, final, unavailable_reason=reason))


def _paid_worker(paths: RepoPaths, args: argparse.Namespace) -> int:
    """Fail a diagnostic/formal identity closed on local paid-path faults."""

    try:
        return _paid_worker_inner(paths, args)
    except BaseException:
        # The inner path records more specific terminal reasons whenever it can.
        # This outer guard covers failures while opening accounting, validating
        # frozen inputs, or constructing local execution resources.  A later
        # operator resume may collect the final storage receipt, but it must not
        # continue the same formal denominator after a local-path interruption.
        try:
            identity = load_identity(paths)
            with C2BehaviorState(
                state_path(paths, identity), identity=identity
            ) as state:
                if state.snapshot()["status"] == "running":
                    state.invalidate("unhandled_local_paid_path_failure")
            with _budget_ledger(paths, identity):
                pass
        except BaseException:
            pass
        raise


def _paid_worker_inner(paths: RepoPaths, args: argparse.Namespace) -> int:
    identity, config, manifest, seccomp, provider, counter, baseline, proof = _worker_inputs(paths, args)
    verify_task_budget(paths, identity)
    # Persist the zero-request accounting identity before any later local gate
    # can invalidate the campaign, so an invalid campaign can still settle and
    # publish an honest zero-cost result.
    with _budget_ledger(paths, identity):
        pass
    with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
        initial = state.snapshot()
    attempt_was_running = any(
        row["status"] == "running" for row in initial["slots"]
    )
    if initial["status"] == "running":
        try:
            _sample_storage(counter, identity.slots[0].logical_run_id, baseline=baseline)
        except (CampaignExecutionError, DockerSupervisionError, RuntimeBridgeError):
            with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
                state.invalidate("campaign_resource_gate_rejected")
            _store_final_storage(paths=paths, identity=identity, counter=counter, baseline=baseline)
            return 3
    with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
        claimed = state.claim_or_resume_slot()
        terminal = state.snapshot()["status"]
    if claimed is None:
        if terminal in {"ready_to_finalize", "invalid"}:
            _store_final_storage(paths=paths, identity=identity, counter=counter, baseline=baseline)
        return 0 if terminal == "ready_to_finalize" else 3
    slot, attempt, attempt_run_id = claimed
    work_root = slot_root(paths, identity, slot) / f"attempt-{attempt}"
    work_root_existed = work_root.exists() or work_root.is_symlink()
    if work_root_existed:
        if work_root.is_symlink() or not work_root.is_dir():
            raise C2BehaviorError("Plan 058 attempt root is unsafe")
    else:
        work_root.mkdir(parents=True, mode=0o700)
    metadata_path = work_root / "api-metadata.json"
    validate_frozen_task_source(paths.common_root / _SOURCE_CHECKOUT_RELPATH, identity.task(slot.task_id))
    with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
        retry_history = state.snapshot()["slots"][identity.slots.index(slot)][
            "transport_retries"
        ]
    with _budget_ledger(paths, identity) as ledger:
        snapshot = ledger.snapshot()
        try:
            recovered = _recover_record_if_complete(
                paths=paths,
                identity=identity,
                slot=slot,
                attempt=attempt,
                attempt_run_id=attempt_run_id,
                budget_snapshot=snapshot,
            )
        except C2BehaviorError:
            with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
                state.invalidate("published_slot_source_integrity_failed")
            _store_final_storage(paths=paths, identity=identity, counter=counter, baseline=baseline)
            return 3
        if recovered is not None:
            with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
                state.mark_paid_boundary()
                state.publish_slot(slot.slot_id, attempt=attempt, attempt_run_id=attempt_run_id, record_sha256=recovered)
                terminal = state.snapshot()["status"]
            if terminal == "ready_to_finalize":
                _store_final_storage(paths=paths, identity=identity, counter=counter, baseline=baseline)
            return 10
        run = snapshot["runs"].get(slot.logical_run_id)
        if _formal_attempt_interrupted_without_projection(
            campaign_mode=identity.campaign_mode,
            attempt_was_running=attempt_was_running,
            work_root_existed=work_root_existed,
            metadata_path=metadata_path,
        ):
            with C2BehaviorState(
                state_path(paths, identity), identity=identity
            ) as state:
                state.invalidate("formal_attempt_interrupted_before_typed_projection")
            _store_final_storage(
                paths=paths,
                identity=identity,
                counter=counter,
                baseline=baseline,
            )
            return 3
        if metadata_path.exists() or metadata_path.is_symlink():
            try:
                hard_stop = _provider_hard_stop(metadata_path)
                projected_evidence = (
                    _attempt_transport_evidence(
                        attempt=attempt,
                        attempt_run_id=attempt_run_id,
                        metadata_path=metadata_path,
                        budget_run=run,
                        prior_retry_evidence=(
                            retry_history[-1] if retry_history else None
                        ),
                    )
                    if isinstance(run, Mapping)
                    else None
                )
                evidence = _load_transport_receipt(
                    work_root,
                    expected_evidence=projected_evidence,
                )
            except (C2BehaviorError, ValueError):
                hard_stop = None
                evidence = None
            with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
                state.mark_paid_boundary()
                if hard_stop is not None:
                    state.invalidate(hard_stop)
                elif evidence is None:
                    state.invalidate("sent_attempt_has_no_complete_or_typed_transport_projection")
                else:
                    state.mark_transport_retry(
                        slot.slot_id,
                        attempt=attempt,
                        attempt_run_id=attempt_run_id,
                        evidence=evidence,
                    )
            if hard_stop is not None or evidence is None:
                _store_final_storage(paths=paths, identity=identity, counter=counter, baseline=baseline)
                return 3
            return 10
        if attempt == 1:
            if run is None:
                ledger.claim_run(
                    slot.logical_run_id, cap_usd=identity.campaign_cap_usd
                )
            elif not run["requests"]:
                ledger.resume_pristine_run(
                    slot.logical_run_id, cap_usd=identity.campaign_cap_usd
                )
            elif not _has_sent_attempt(run):
                ledger.resume_unsent_run(
                    slot.logical_run_id, cap_usd=identity.campaign_cap_usd
                )
            else:
                with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
                    state.mark_paid_boundary()
                    state.invalidate("sent_attempt_has_no_private_metadata")
                _store_final_storage(
                    paths=paths,
                    identity=identity,
                    counter=counter,
                    baseline=baseline,
                )
                return 3
        else:
            try:
                if len(retry_history) != attempt - 1 or not isinstance(run, Mapping):
                    raise C2BehaviorError(
                        "Plan 058 transport retry history is incomplete"
                    )
                previous = retry_history[-1]
                normalized = json.loads(json.dumps(run))
                if run.get("stopped") is True:
                    if _json_sha256(run) != previous["budget_run_sha256"]:
                        raise C2BehaviorError(
                            "Plan 058 stopped logical budget run drifted"
                        )
                    ledger.resume_settled_infra_run(
                        slot.logical_run_id,
                        expected_stop_reason=previous["ledger_stop_reason"],
                        cap_usd=identity.campaign_cap_usd,
                    )
                else:
                    normalized["stopped"] = True
                    normalized["stop_reason"] = previous["ledger_stop_reason"]
                    if _json_sha256(normalized) != previous["budget_run_sha256"]:
                        raise C2BehaviorError(
                            "Plan 058 resumed logical budget run drifted"
                        )
            except BaseException:
                with C2BehaviorState(
                    state_path(paths, identity), identity=identity
                ) as state:
                    state.mark_paid_boundary()
                    state.invalidate("transport_budget_resume_failed")
                _store_final_storage(
                    paths=paths,
                    identity=identity,
                    counter=counter,
                    baseline=baseline,
                )
                raise
        try:
            _secret_name, api_key = load_provider_secret(config)
            request = _make_request(
                paths=paths,
                identity=identity,
                task=identity.task(slot.task_id),
                manifest=manifest,
                work_root=work_root,
                docker_task_id=attempt_run_id,
                seccomp_profile=seccomp,
                stub=False,
            )
        except BaseException:
            with C2BehaviorState(
                state_path(paths, identity), identity=identity
            ) as state:
                state.invalidate("provider_or_request_configuration_failed")
            _store_final_storage(
                paths=paths,
                identity=identity,
                counter=counter,
                baseline=baseline,
            )
            raise

        def validate_prepared(prepared: Any) -> None:
            _validate_prepared(prepared, identity=identity, task=identity.task(slot.task_id), manifest=manifest, stub=False)

        try:
            live = asyncio.run(
                run_budgeted_terminal_bench_core(
                    config,
                    request,
                    api_key=api_key,
                    ledger=ledger,
                    metadata_path=metadata_path,
                    counter=counter,
                    lock_guard=proof.guard,
                    lease=proof.lease,
                    provider=provider,
                    max_guardian_logical_requests=identity.max_guardian_logical_requests,
                    timeout_seconds=identity.upstream_timeout_seconds,
                    request_preflight=None,
                    preflight_task_id=None,
                    project_request=lambda value: value,
                    validate_prepared=validate_prepared,
                    retry_backoff_seconds=0,
                    request_reservation_usd=identity.request_reservation_usd,
                    run_cap_usd=identity.campaign_cap_usd,
                    max_concurrent_main=1,
                    usage_envelope=identity.usage_envelope,
                    counter_sample_timeout_seconds=_DOCKER_COUNTER_SAMPLE_TIMEOUT_SECONDS,
                    budget_run_id=slot.logical_run_id,
                )
            )
            hard_stop = _provider_hard_stop(metadata_path)
            if hard_stop is not None:
                with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
                    state.mark_paid_boundary()
                    state.invalidate(hard_stop)
                _store_final_storage(paths=paths, identity=identity, counter=counter, baseline=baseline)
                return 3
            run = live.budget_snapshot["runs"].get(slot.logical_run_id)
            if not isinstance(run, Mapping):
                raise C2BehaviorError("Plan 058 logical budget run is unavailable")
            execution_receipt = _read_agent_execution_receipt(
                live.harbor.trial_dir
                / "agent"
                / AGENT_EXECUTION_RECEIPT_FILENAME
            )
            evidence = (
                _attempt_transport_evidence(
                    attempt=attempt,
                    attempt_run_id=attempt_run_id,
                    metadata_path=metadata_path,
                    budget_run=run,
                    prior_retry_evidence=(
                        retry_history[-1] if retry_history else None
                    ),
                )
                if isinstance(run, Mapping)
                else None
            )
            if evidence is not None:
                if live.harbor.docker_evidence is None:
                    raise C2BehaviorError("Plan 058 transport retry lacks Docker evidence")
                _write_transport_receipt(
                    work_root,
                    evidence=evidence,
                    docker_receipt=live.harbor.docker_evidence.receipt(),
                )
                with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
                    state.mark_paid_boundary()
                    state.mark_transport_retry(
                        slot.slot_id,
                        attempt=attempt,
                        attempt_run_id=attempt_run_id,
                        evidence=evidence,
                    )
                return 10
            parsed = parse_single_task_result(
                live.harbor.trial_dir,
                host_returncode=live.harbor.returncode,
                expected_task_id=slot.task_id,
                preserve_agent_failure_verifier_reward=True,
            )
            parsed = _classify_plan058_agent_execution(
                live,
                parsed,
                budget_run=run,
                receipt=execution_receipt,
                metadata_path=metadata_path,
                identity=identity,
                expected_execution_id=attempt_run_id,
            )
            if parsed.outcome in {
                RunOutcome.INFRA_FAILED,
                RunOutcome.BUDGET_STOPPED,
                RunOutcome.CANCELLED,
            }:
                reason = {
                    RunOutcome.INFRA_FAILED: "terminal_bench_infrastructure_failed",
                    RunOutcome.BUDGET_STOPPED: "plan058_budget_hard_stop",
                    RunOutcome.CANCELLED: "terminal_bench_cancelled",
                }[parsed.outcome]
                with C2BehaviorState(
                    state_path(paths, identity), identity=identity
                ) as state:
                    state.mark_paid_boundary()
                    state.invalidate(reason)
                _store_final_storage(
                    paths=paths,
                    identity=identity,
                    counter=counter,
                    baseline=baseline,
                )
                return 3
            digest = _write_slot_record(
                paths=paths,
                identity=identity,
                slot=slot,
                attempt=attempt,
                attempt_run_id=attempt_run_id,
                transport_retries=retry_history,
                live=live,
                parsed=parsed,
                metadata_path=metadata_path,
            )
        except BaseException:
            ledger.recover_interrupted_requests()
            with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
                state.mark_paid_boundary()
                state.invalidate("local_execution_or_projection_failed")
            _store_final_storage(paths=paths, identity=identity, counter=counter, baseline=baseline)
            raise
    _sample_storage(counter, identity.slots[0].logical_run_id, baseline=baseline)
    with C2BehaviorState(state_path(paths, identity), identity=identity) as state:
        state.mark_paid_boundary()
        state.publish_slot(slot.slot_id, attempt=attempt, attempt_run_id=attempt_run_id, record_sha256=digest)
        terminal = state.snapshot()["status"]
    if terminal == "ready_to_finalize":
        _store_final_storage(paths=paths, identity=identity, counter=counter, baseline=baseline)
    return 10


def _metrics_root(paths: RepoPaths, value: Path | None) -> Path:
    candidate = value or (paths.common_root / _DEFAULT_METRICS_RELPATH)
    resolved = candidate if candidate.is_absolute() else paths.common_root / candidate
    resolved = resolved.resolve(strict=False)
    if not resolved.is_relative_to(paths.common_root.resolve(strict=True)):
        raise C2BehaviorError("Plan 058 metrics directory is outside project")
    return resolved


def _coordinator(paths: RepoPaths, args: argparse.Namespace, *, mode: str) -> int:
    if args.docker_host_volume is None:
        raise C2BehaviorError("Plan 058 Docker host volume is required")
    identity = load_identity(paths)
    if mode == "paid":
        if args.paid_action != PLAN058_PAID_ACTION:
            raise C2BehaviorError("Plan 058 explicit paid action is required")
        verify_task_budget(paths, identity)
    metrics = _metrics_root(paths, args.metrics_dir)
    lease_path = campaign_root(paths, identity) / "executor.lock"
    with CampaignExecutionLease(lease_path) as lease:
        while True:
            argv = (
                str(paths.worktree_root / "scripts/with-build-lock.sh"),
                sys.executable,
                "-B",
                "-m",
                "rondo_eval.terminal_bench.c2_behavior_cli",
                "status",
                "--worker-mode",
                mode,
                "--campaign-lease-token",
                lease.token,
                "--docker-host-volume",
                str(args.docker_host_volume),
            )
            environment = _locked_worker_environment(worktree_root=paths.worktree_root)
            environment["RONDO_BUILD_METRICS_DIR"] = str(metrics)
            completed = subprocess.run(argv, cwd=paths.worktree_root, env=environment, stdin=subprocess.DEVNULL, check=False)
            if completed.returncode == 10:
                continue
            return completed.returncode


def finalize(paths: RepoPaths, *, snapshot_date: str, refined_classification: Path | None) -> dict[str, Any]:
    identity = load_identity(paths, allow_retired=True)
    state_file = state_path(paths, identity)
    state = _read_json(state_file)
    if state["status"] == "finalized":
        return status(paths)
    if state["status"] not in {"ready_to_finalize", "invalid"}:
        raise C2BehaviorError("Plan 058 campaign is not ready to finalize")
    if state["final_storage"] is None:
        raise C2BehaviorError("Plan 058 final storage sample is missing")
    budget = _load_budget_snapshot(paths, identity)
    if state["status"] == "ready_to_finalize":
        try:
            records = load_slot_records(paths, identity, state)
            for slot, record in zip(identity.slots, records, strict=True):
                _revalidate_plan058_record_sources(
                    paths=paths,
                    identity=identity,
                    slot=slot,
                    record=record,
                )
                logical_run = budget["runs"].get(slot.logical_run_id)
                if (
                    not isinstance(logical_run, Mapping)
                    or _json_sha256(logical_run)
                    != record["logical_budget"]["run_sha256"]
                ):
                    raise C2BehaviorError(
                        "Plan 058 published logical budget binding drifted"
                    )
        except (BoundedObservationError, C2BehaviorError, ValueError):
            with C2BehaviorState(state_file, identity=identity) as ledger:
                ledger.invalidate("published_slot_source_integrity_failed")
                state = ledger.snapshot()
            records = []
    else:
        records = []
    refined = None
    if state["status"] == "ready_to_finalize":
        if refined_classification is None:
            raise C2BehaviorError("Plan 058 refined classification path is required")
        candidate = refined_classification if refined_classification.is_absolute() else paths.common_root / refined_classification
        resolved = candidate.resolve(strict=True)
        private_root = (campaign_root(paths, identity) / "classification").resolve(strict=False)
        if not resolved.is_relative_to(private_root):
            raise C2BehaviorError("Plan 058 refined classification is outside campaign private root")
        refined = _read_json(resolved)
    result = public_result(
        identity=identity,
        state=state,
        budget=budget,
        records=records,
        refined_assessment=refined,
        snapshot_date=snapshot_date,
    )
    destination = paths.worktree_root / identity.public_result_relative_path
    if destination.exists() and not destination.is_symlink():
        if json.loads(_read_regular(destination)) != result:
            raise C2BehaviorError("Plan 058 public result drifted")
    else:
        _atomic_json(destination, result, mode=0o644)
    close_envelope_and_pointer(
        paths,
        identity=identity,
        terminal_status="invalid" if result["status"] == "invalid" else "passed",
        spent_usd=Decimal(str(budget["spent_usd"])),
    )
    with C2BehaviorState(state_file, identity=identity) as ledger:
        ledger.finalize(outcome=result["outcome"])
    return result


def write_classification_template(paths: RepoPaths) -> Path:
    """Write one private, conservative body-free form for manual trace review."""

    identity = load_identity(paths)
    state = _read_json(state_path(paths, identity))
    if state["status"] != "ready_to_finalize":
        raise C2BehaviorError("Plan 058 classification requires a complete denominator")
    records = load_slot_records(paths, identity, state)
    rows = []
    for record in records:
        observation = project_task_observation(
            campaign_root(paths, identity) / record["sources"]["native_trace"]["path"],
            campaign_root(paths, identity) / record["sources"]["api_metadata"]["path"],
        )
        tools = observation["tools"]
        rows.append(
            {
                "slot_id": record["slot"]["slot_id"],
                "harmful": 0,
                "reasonable": 0,
                "insufficient": tools["repeated_exact_commands"],
                "harmful_duration_ms": 0,
                "reasonable_duration_ms": 0,
                "insufficient_duration_ms": tools[
                    "repeated_exact_command_lifecycle_duration_ms"
                ],
            }
        )
    destination = campaign_root(paths, identity) / "classification" / "refined.json"
    if destination.exists() or destination.is_symlink():
        raise C2BehaviorError("Plan 058 refined classification already exists")
    _atomic_json(
        destination,
        {
            "schema_version": 1,
            "kind": "plan058_c2_refined_classification",
            "slots": rows,
            "no_harm": {
                "reasonable_repeats_preserved": None,
                "recovery_and_user_control_preserved": None,
                "tools_remain_executable": None,
                "no_material_task_harm": None,
            },
        },
        mode=0o600,
    )
    return destination


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = RepoPaths.discover(Path.cwd())
    try:
        if args.worker_mode == "preflight":
            return _preflight_worker(paths, args)
        if args.worker_mode == "paid":
            return _paid_worker(paths, args)
        if args.action == "status":
            print(json.dumps(status(paths), sort_keys=True))
            return 0
        if args.action == "initialize":
            required = (
                args.campaign_id,
                args.batch_id,
                args.campaign_mode,
                args.result_namespace,
                args.public_result_path,
                args.runtime_manifest,
                args.run_id_date,
                args.run_id_sequence_base,
            )
            if any(item is None for item in required):
                raise C2BehaviorError("Plan 058 initialize inputs are required")
            identity = initialize_identity(
                paths,
                campaign_id=args.campaign_id,
                batch_id=args.batch_id,
                campaign_mode=args.campaign_mode,
                result_namespace=args.result_namespace,
                public_result_path=args.public_result_path,
                runtime_manifest=args.runtime_manifest,
                run_id_date=args.run_id_date,
                run_id_sequence_base=args.run_id_sequence_base,
                commissioning_task_id=args.commissioning_task_id,
                diagnostic_slot_start=args.diagnostic_slot_start,
                diagnostic_slot_end=args.diagnostic_slot_end,
            )
            initialized = {
                "status": "initialized",
                "campaign_id": identity.campaign_id,
                "campaign_mode": identity.campaign_mode,
                "campaign_lock_sha256": identity.lock_sha256,
                "logical_denominator": len(identity.slots),
                "required_paid_action": PLAN058_PAID_ACTION,
                "paid_requests_sent": 0,
            }
            if identity.campaign_mode == "diagnostic":
                initialized["diagnostic_slot_range"] = identity.value[
                    "diagnostic_slot_range"
                ]
            print(json.dumps(initialized, sort_keys=True))
            return 0
        if args.action == "preflight":
            return _coordinator(paths, args, mode="preflight")
        if args.action in {"run", "resume"}:
            return _coordinator(paths, args, mode="paid")
        if args.action == "classification-template":
            print(
                json.dumps(
                    {
                        "status": "classification_template_created",
                        "path": str(write_classification_template(paths)),
                        "paid_requests_sent": 0,
                    },
                    sort_keys=True,
                )
            )
            return 0
        print(json.dumps(finalize(paths, snapshot_date=args.snapshot_date, refined_classification=args.refined_classification), sort_keys=True))
        return 0
    except (
        BoundedObservationError,
        C2BehaviorError,
        CampaignExecutionError,
        DockerSupervisionError,
        RuntimeBridgeError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "error", "error": type(exc).__name__, "message": str(exc), "paid_requests_sent": 0}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
