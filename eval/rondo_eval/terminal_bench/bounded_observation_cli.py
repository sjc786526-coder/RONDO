"""Safe operator entry for the Plan 056 bounded Local observation campaign."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import stat
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..api_budget_proxy import (
    PersistentBudgetLedger,
    load_validated_budget_ledger_state,
)
from ..config import RepoPaths, load_provider_secret, load_runtime_config
from ..contracts import BinaryManifest, Product, RunOutcome, Side
from ..docker_supervisor import DockerSupervisionError
from ..harness_observation import project_task_observation
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
from .bounded_observation import (
    PLAN056_LOCK_RELPATH,
    PLAN056_PAID_ACTION,
    PLAN056_POINTER_RELPATH,
    PLAN056_PUBLIC_RESULT_RELPATH,
    PLAN056_RUN_CAP_USD,
    PLAN056_UNPRICED_FALLBACK_USD,
    BoundedObservationError,
    BoundedObservationIdentity,
    BoundedObservationSlot,
    BoundedObservationState,
    _atomic_json,
    _read_json,
    _read_regular,
    budget_path,
    build_slot_record,
    campaign_root,
    close_envelope_and_pointer,
    initialize_identity,
    load_identity,
    preflight_receipt_path,
    public_result,
    slot_record_path,
    slot_root,
    state_path,
    validate_slot_record,
    verify_task_budget,
)
from .live import run_budgeted_terminal_bench_core
from .materialize import validate_frozen_task_source
from .pair import (
    guardian_review_count,
    has_complete_guardian_approval_sequence,
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
_DEFAULT_METRICS_RELPATH = Path("eval-data/build/plan056-watchdog")
_MAX_COORDINATOR_STEPS = 40
_PLAN056_DOCKER_COUNTER_SAMPLE_TIMEOUT_SECONDS = 60.0
_PLAN056_DOCKER_FACT_COMMAND_MAX_ATTEMPTS = 4


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rondo-direction1-observation")
    parser.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=("status", "initialize", "preflight", "run", "resume", "finalize"),
    )
    parser.add_argument("--runtime-manifest", type=Path)
    parser.add_argument("--run-id-date")
    parser.add_argument("--run-id-sequence-base", type=int)
    parser.add_argument("--docker-host-volume", type=Path)
    parser.add_argument("--metrics-dir", type=Path)
    parser.add_argument("--paid-action")
    parser.add_argument("--snapshot-date", default="2026-08-22")
    parser.add_argument(
        "--worker-mode", choices=("preflight", "paid"), help=argparse.SUPPRESS
    )
    parser.add_argument("--campaign-lease-token", help=argparse.SUPPRESS)
    return parser


def status(paths: RepoPaths) -> dict[str, Any]:
    """Read only Plan 056 public state; never load config, a secret, Docker or API."""

    pointer = paths.worktree_root / PLAN056_POINTER_RELPATH
    if not pointer.exists() and not pointer.is_symlink():
        return {"status": "uninitialized", "paid_requests_sent": 0}
    pointer_value = _read_json(pointer)
    retired_pointer = {
        "schema_version": 1,
        "kind": "rondo_direction1_bounded_observation",
        "active_lock": None,
        "active_lock_sha256": None,
    }
    if (
        pointer_value == retired_pointer
        and not (paths.worktree_root / PLAN056_LOCK_RELPATH).exists()
    ):
        return {"status": "awaiting_initialization", "paid_requests_sent": 0}
    identity = load_identity(paths, allow_retired=True)
    state = _read_json(state_path(paths, identity))
    ledger_path = budget_path(paths, identity)
    budget: Mapping[str, Any] | None = None
    if ledger_path.exists() and not ledger_path.is_symlink():
        budget = _load_budget_snapshot(paths, identity)
    attempts = (
        sum(
            int(request["attempt_count"])
            for run in budget["runs"].values()
            for request in run["requests"].values()
        )
        if budget is not None
        else 0
    )
    return {
        "status": state["status"],
        "campaign_id": identity.campaign_id,
        "campaign_lock_sha256": identity.lock_sha256,
        "preflight_complete": sum(
            row["status"] == "complete" for row in state["preflight"]
        ),
        "campaign_slots_published": sum(
            row["status"] == "published" for row in state["slots"]
        ),
        "formal_boundary": state["formal_boundary"],
        "durable_upstream_attempts": attempts,
        "estimated_usd": budget["spent_usd"] if budget is not None else "0.000000",
        "reserved_usd": budget["reserved_usd"] if budget is not None else "0.000000",
        "invalid_reason": state["invalid_reason"],
        "selected_candidate": state["selected_candidate"],
        "paid_requests_sent": 0,
    }


def _load_budget_snapshot(
    paths: RepoPaths, identity: BoundedObservationIdentity
) -> dict[str, Any]:
    """Add the read-only totals that a live ledger snapshot normally exposes."""

    value = load_validated_budget_ledger_state(
        budget_path(paths, identity),
        batch_id=identity.batch_id,
        total_cap_usd=identity.campaign_cap_usd,
        max_runs=len(identity.slots),
        default_run_cap_usd=PLAN056_RUN_CAP_USD,
        unpriced_fallback_usd=PLAN056_UNPRICED_FALLBACK_USD,
        unpriced_fallback_per_attempt=True,
    )
    spent = sum(
        (Decimal(str(run["spent_usd"])) for run in value["runs"].values()),
        Decimal(0),
    )
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
        {
            "run_slots_used": len(value["runs"]),
            "spent_usd": f"{spent:.6f}",
            "reserved_usd": f"{reserved:.6f}",
        }
    )
    return snapshot


def _make_request(
    *,
    paths: RepoPaths,
    identity: BoundedObservationIdentity,
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
        budget_usd=float(PLAN056_RUN_CAP_USD),
        seccomp_profile_path=str(seccomp_profile),
        seccomp_profile_source_sha256=identity.value["seccomp"]["source_sha256"],
        seccomp_profile_effective_sha256=identity.value["seccomp"]["effective_sha256"],
        require_container_metrics=True,
        frozen_task=task,
        stub_verifier=stub,
        delete_environment=not stub,
        pinned_model_id=identity.value["provider"]["public_profile"]["main_model"],
        pinned_main_effort=identity.value["provider"]["public_profile"]["main_effort"],
        pinned_guardian_effort=identity.value["provider"]["public_profile"][
            "guardian_effort"
        ],
    )
    return enable_local_harness_observation(request)


def _validate_prepared(
    prepared: Any,
    *,
    identity: BoundedObservationIdentity,
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
        or spec.provider.to_public_dict()
        != identity.value["provider"]["public_profile"]
        or prepared.adapter.rollout_trace_root != "/logs/agent/rollout-trace"
        or prepared.command.stub_verifier is not stub
        or prepared.command.delete_environment is stub
    ):
        raise BoundedObservationError("Plan 056 prepared run differs from its lock")


def _worker_inputs(
    paths: RepoPaths, args: argparse.Namespace
) -> tuple[
    BoundedObservationIdentity,
    Any,
    BinaryManifest,
    Path,
    Any,
    DockerCliCounter,
    StorageBaseline,
    Any,
]:
    if args.docker_host_volume is None:
        raise BoundedObservationError("Plan 056 Docker host volume is required")
    identity = load_identity(paths)
    _require_held_campaign_lease(
        campaign_root(paths, identity) / "executor.lock",
        args.campaign_lease_token,
    )
    identity.validate_runtime_checkout(paths)
    config = load_runtime_config(paths)
    provider = identity.provider_projection(config)
    manifest = identity.manifest(paths)
    seccomp = identity.seccomp_profile(paths)
    validate_harbor_installation(
        load_historical_pair_identity(), executable=HARBOR_EXECUTABLE
    )
    proof = lease_from_watchdog()
    counter = DockerCliCounter(
        host_data_root=args.docker_host_volume,
        desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        probe_timeout_seconds=_PLAN056_DOCKER_COUNTER_SAMPLE_TIMEOUT_SECONDS,
        command_max_attempts=_PLAN056_DOCKER_FACT_COMMAND_MAX_ATTEMPTS,
    )
    baseline = _load_or_create_storage_baseline(
        campaign_root(paths, identity), counter, identity.slots[0].run_id
    )
    return identity, config, manifest, seccomp, provider, counter, baseline, proof


def _preflight_worker(paths: RepoPaths, args: argparse.Namespace) -> int:
    identity, config, manifest, seccomp, provider, counter, baseline, proof = (
        _worker_inputs(paths, args)
    )
    _sample_storage(counter, identity.slots[0].run_id, baseline=baseline)
    with BoundedObservationState(
        state_path(paths, identity), identity=identity
    ) as state:
        claimed = state.claim_preflight()
    if claimed is None:
        return 0
    task_id, attempt = claimed
    task = identity.task(task_id)
    destination = preflight_receipt_path(paths, identity, task)
    if destination.exists() and not destination.is_symlink():
        raw = _read_regular(destination)
        receipt = json.loads(raw)
        if (
            receipt.get("campaign_lock_sha256") != identity.lock_sha256
            or receipt.get("task_id") != task.task_id
        ):
            raise BoundedObservationError("Plan 056 preflight receipt drifted")
        with BoundedObservationState(
            state_path(paths, identity), identity=identity
        ) as state:
            state.finish_preflight(
                task.task_id, receipt_sha256=hashlib.sha256(raw).hexdigest()
            )
        return 10
    root = (
        campaign_root(paths, identity)
        / "preflight-work"
        / task.slug
        / f"attempt-{attempt}"
    )
    if root.exists() or root.is_symlink():
        raise BoundedObservationError("Plan 056 preflight attempt already exists")
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
                docker_task_id=f"plan056-preflight-{task.slug}-a{attempt}",
                seccomp_profile=seccomp,
                stub=True,
            )
            projected = replace(
                request, provider_transport_base_url=server.docker_base_url
            )
            prepared = prepare_terminal_bench_run(config, projected)
            _validate_prepared(
                prepared,
                identity=identity,
                task=task,
                manifest=manifest,
                stub=True,
            )
            executor = DockerSupervisedHostHarborExecutor(
                counter=counter, lock_guard=proof.guard, lease=proof.lease
            )
            backend = InjectedHostHarborBackend(
                executor,
                getenv=lambda name: (
                    PREFLIGHT_STUB_BEARER
                    if name == prepared.spec.provider.api_key_env
                    else None
                ),
            )
            harbor = asyncio.run(UnifiedTerminalBenchRunner(backend).run(prepared))
            trace = _request_trace(server.bodies, provider=provider)
            if server.rejections:
                raise BoundedObservationError(
                    "Plan 056 preflight stub rejected a request"
                )
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
                        "usage": {
                            "input_tokens": 0,
                            "cached_input_tokens": 0,
                            "cache_write_input_tokens": 0,
                            "output_tokens": 0,
                        },
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
        observation = project_task_observation(
            harbor.trial_dir / "agent" / "rollout-trace", metadata_path
        )
        if harbor.docker_evidence is None:
            raise BoundedObservationError("Plan 056 preflight lacks Docker evidence")
        receipt = {
            "schema_version": 1,
            "kind": "rondo_direction1_bounded_observation_preflight",
            "campaign_lock_sha256": identity.lock_sha256,
            "task_id": task.task_id,
            "request_roles": [role for role, _body in trace],
            "request_body_sha256": [
                hashlib.sha256(
                    json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                for _role, body in trace
            ],
            "observation_sha256": hashlib.sha256(
                json.dumps(observation, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "docker": harbor.docker_evidence.receipt(),
            "upstream_api_requests": 0,
            "estimated_usd": "0.000000",
        }
        _atomic_json(destination, receipt, mode=0o600)
        raw = _read_regular(destination)
        _sample_storage(counter, identity.slots[0].run_id, baseline=baseline)
        with BoundedObservationState(
            state_path(paths, identity), identity=identity
        ) as state:
            state.finish_preflight(
                task.task_id, receipt_sha256=hashlib.sha256(raw).hexdigest()
            )
        return 10
    except BaseException as exc:
        with BoundedObservationState(
            state_path(paths, identity), identity=identity
        ) as state:
            state.preflight_retry(task.task_id, reason=type(exc).__name__)
        raise


def _meaningful_request_ids(run: Mapping[str, Any]) -> set[str]:
    requests = run.get("requests")
    if not isinstance(requests, Mapping):
        raise BoundedObservationError("Plan 056 budget run has no requests")
    return {
        str(request_id)
        for request_id, request in requests.items()
        if isinstance(request, Mapping) and int(request.get("attempt_count", -1)) >= 1
    }


def _metadata_request_ids(path: Path) -> set[str]:
    value = _read_json(path)
    requests = value.get("requests")
    if not isinstance(requests, list) or not requests:
        raise BoundedObservationError("Plan 056 API metadata is incomplete")
    ids = [row.get("request_id") for row in requests if isinstance(row, dict)]
    if len(ids) != len(requests) or any(
        not isinstance(item, str) or not item for item in ids
    ):
        raise BoundedObservationError(
            "Plan 056 API metadata request identity is invalid"
        )
    if len(set(ids)) != len(ids):
        raise BoundedObservationError(
            "Plan 056 API metadata request identity is duplicated"
        )
    return set(ids)


def _validate_guardian_binding(live: Any, parsed: Any, metadata_path: Path) -> None:
    metadata = _read_json(metadata_path)
    requests = metadata.get("requests")
    if not isinstance(requests, list):
        raise BoundedObservationError("Plan 056 API metadata is incomplete")
    roles = tuple(
        request.get("role") if isinstance(request, dict) else None
        for request in requests
    )
    guardian_requests = [
        request
        for role, request in zip(roles, requests, strict=True)
        if role == "guardian"
    ]
    if parsed.outcome is RunOutcome.COMPLETED and not (
        (not guardian_requests and all(role == "main" for role in roles))
        or has_complete_guardian_approval_sequence(roles)
    ):
        raise BoundedObservationError(
            "Plan 056 completed request sequence is not approval-complete"
        )
    bound_guardian_requests = guardian_requests
    if parsed.outcome is RunOutcome.COMPLETED and guardian_requests:
        bound_guardian_requests = [
            request
            for index, (role, request) in enumerate(zip(roles, requests, strict=True))
            if role == "guardian"
            and (index + 1 == len(roles) or roles[index + 1] != "guardian")
        ]
        if len(bound_guardian_requests) != guardian_review_count(roles):
            raise BoundedObservationError(
                "Plan 056 Guardian review grouping is inconsistent"
            )
    expected = tuple(
        request.get("canonical_body_sha256") for request in bound_guardian_requests
    )
    observed = tuple(item.canonical_request_sha256 for item in live.evidence)
    if (
        any(not isinstance(digest, str) or len(digest) != 64 for digest in expected)
        or len(set(expected)) != len(expected)
        or any(not isinstance(digest, str) or len(digest) != 64 for digest in observed)
        or len(set(observed)) != len(observed)
        or set(expected) != set(observed)
    ):
        raise BoundedObservationError("Plan 056 Guardian evidence binding is invalid")
    if parsed.outcome is RunOutcome.COMPLETED and any(
        (item.decision, item.terminal_status, item.failure_reason)
        not in {("approved", "approved", None), ("denied", "denied", None)}
        for item in live.evidence
    ):
        raise BoundedObservationError("Plan 056 Guardian evidence is not terminal")


def _private_source_relative(root: Path, path: Path, *, directory: bool) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise BoundedObservationError(
            "Plan 056 private source escaped its campaign"
        ) from exc
    if not relative.parts or ".." in relative.parts:
        raise BoundedObservationError("Plan 056 private source path is invalid")
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except OSError as exc:
            raise BoundedObservationError(
                "Plan 056 private source is unavailable"
            ) from exc
        if stat.S_ISLNK(mode):
            raise BoundedObservationError("Plan 056 private source contains a symlink")
        final = index == len(relative.parts) - 1
        if final:
            expected = stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)
            if not expected:
                raise BoundedObservationError("Plan 056 private source type is invalid")
        elif not stat.S_ISDIR(mode):
            raise BoundedObservationError("Plan 056 private source parent is invalid")
    return relative.as_posix()


def _source_file_sha256(root: Path, path: Path) -> tuple[str, str]:
    relative = _private_source_relative(root, path, directory=False)
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                total += len(chunk)
                if total > 512 * 1024**2:
                    raise BoundedObservationError(
                        "Plan 056 private source is too large"
                    )
                digest.update(chunk)
    except OSError as exc:
        raise BoundedObservationError("Plan 056 private source is unreadable") from exc
    return relative, digest.hexdigest()


def _source_tree_fingerprint(root: Path, tree: Path) -> dict[str, Any]:
    relative_root = _private_source_relative(root, tree, directory=True)
    entries: list[tuple[str, int, str]] = []
    total = 0
    stack = [tree]
    while stack:
        directory = stack.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            raise BoundedObservationError(
                "Plan 056 native trace is unreadable"
            ) from exc
        directories: list[Path] = []
        for child in children:
            try:
                metadata = child.lstat()
            except OSError as exc:
                raise BoundedObservationError(
                    "Plan 056 native trace is unavailable"
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise BoundedObservationError(
                    "Plan 056 native trace contains a symlink"
                )
            if stat.S_ISDIR(metadata.st_mode):
                directories.append(child)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise BoundedObservationError("Plan 056 native trace type is invalid")
            relative, digest = _source_file_sha256(tree, child)
            total += metadata.st_size
            entries.append((relative, metadata.st_size, digest))
            if len(entries) > 100_000 or total > 2 * 1024**3:
                raise BoundedObservationError("Plan 056 native trace exceeds its bound")
        stack.extend(reversed(directories))
    if not entries:
        raise BoundedObservationError("Plan 056 native trace is empty")
    encoded = json.dumps(entries, separators=(",", ":")).encode()
    return {
        "path": relative_root,
        "tree_sha256": hashlib.sha256(encoded).hexdigest(),
        "file_count": len(entries),
        "total_bytes": total,
    }


def _source_binding(
    *,
    paths: RepoPaths,
    identity: BoundedObservationIdentity,
    live: Any,
    metadata_path: Path,
) -> dict[str, Any]:
    root = campaign_root(paths, identity)
    result_path = live.harbor.trial_dir / "result.json"
    result_relative, result_sha256 = _source_file_sha256(root, result_path)
    metadata_relative, metadata_sha256 = _source_file_sha256(root, metadata_path)
    trace = _source_tree_fingerprint(
        root, live.harbor.trial_dir / "agent" / "rollout-trace"
    )
    return {
        "terminal_bench": {
            "path": result_relative,
            "sha256": result_sha256,
            "host_returncode": live.harbor.returncode,
        },
        "api_metadata": {"path": metadata_relative, "sha256": metadata_sha256},
        "native_trace": trace,
    }


def _revalidate_record_sources(
    *,
    paths: RepoPaths,
    identity: BoundedObservationIdentity,
    slot: BoundedObservationSlot,
    record: Mapping[str, Any],
    preserve_agent_failure_verifier_reward: bool = False,
) -> None:
    root = campaign_root(paths, identity)
    sources = record["sources"]
    terminal = sources["terminal_bench"]
    metadata = sources["api_metadata"]
    trace = sources["native_trace"]
    result_path = root / terminal["path"]
    metadata_path = root / metadata["path"]
    trace_path = root / trace["path"]
    if _source_file_sha256(root, result_path)[1] != terminal["sha256"]:
        raise BoundedObservationError("Plan 056 Terminal-Bench source drifted")
    if _source_file_sha256(root, metadata_path)[1] != metadata["sha256"]:
        raise BoundedObservationError("Plan 056 API metadata source drifted")
    if _source_tree_fingerprint(root, trace_path) != trace:
        raise BoundedObservationError("Plan 056 native trace source drifted")
    observation = project_task_observation(trace_path, metadata_path)
    if observation != record["observation"]:
        raise BoundedObservationError(
            "Plan 056 observation no longer matches its sources"
        )
    parsed = parse_single_task_result(
        result_path.parent,
        host_returncode=terminal["host_returncode"],
        expected_task_id=slot.task_id,
        preserve_agent_failure_verifier_reward=(
            preserve_agent_failure_verifier_reward
        ),
    )
    terminal_record = record["terminal_bench"]
    if (
        str(parsed.task_outcome) != terminal_record["task_outcome"]
        or float(parsed.reward) != terminal_record["reward"]
        or float(parsed.duration_seconds) != terminal_record["duration_seconds"]
        or int(parsed.input_tokens) != terminal_record["input_tokens"]
        or int(parsed.cached_tokens) != terminal_record["cached_tokens"]
        or int(parsed.output_tokens) != terminal_record["output_tokens"]
    ):
        raise BoundedObservationError("Plan 056 Terminal-Bench projection drifted")


def _write_slot_record(
    *,
    paths: RepoPaths,
    identity: BoundedObservationIdentity,
    slot: BoundedObservationSlot,
    live: Any,
    parsed: Any,
    metadata_path: Path,
) -> str:
    run = live.budget_snapshot["runs"].get(slot.run_id)
    if not isinstance(run, Mapping):
        raise BoundedObservationError("Plan 056 slot budget is unavailable")
    if _meaningful_request_ids(run) != _metadata_request_ids(metadata_path):
        raise BoundedObservationError(
            "Plan 056 budget and API request identities differ"
        )
    _validate_guardian_binding(live, parsed, metadata_path)
    observation = project_task_observation(
        live.harbor.trial_dir / "agent" / "rollout-trace", metadata_path
    )
    if live.harbor.docker_evidence is None:
        raise BoundedObservationError("Plan 056 slot lacks Docker evidence")
    record = build_slot_record(
        identity=identity,
        slot=slot,
        parsed=parsed,
        observation=observation,
        budget_run=run,
        docker_receipt=live.harbor.docker_evidence.receipt(),
        sources=_source_binding(
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
    _revalidate_record_sources(
        paths=paths,
        identity=identity,
        slot=slot,
        record=record,
    )
    return hashlib.sha256(raw).hexdigest()


def _recover_record_if_complete(
    *,
    paths: RepoPaths,
    identity: BoundedObservationIdentity,
    slot: BoundedObservationSlot,
    budget_snapshot: Mapping[str, Any],
) -> str | None:
    destination = slot_record_path(paths, identity, slot)
    if not destination.exists() and not destination.is_symlink():
        return None
    raw = _read_regular(destination)
    record = validate_slot_record(json.loads(raw), identity=identity, slot=slot)
    current = budget_snapshot.get("runs", {}).get(slot.run_id)
    if current != record["budget"]:
        raise BoundedObservationError("Plan 056 recovered record differs from budget")
    _revalidate_record_sources(
        paths=paths,
        identity=identity,
        slot=slot,
        record=record,
    )
    return hashlib.sha256(raw).hexdigest()


def _has_sent_attempt(run: Mapping[str, Any] | None) -> bool:
    if not isinstance(run, Mapping):
        return False
    requests = run.get("requests")
    return isinstance(requests, Mapping) and any(
        isinstance(request, Mapping) and int(request.get("attempt_count", 0)) >= 1
        for request in requests.values()
    )


def _storage_projection(
    baseline: StorageBaseline,
    final: StorageBaseline | None,
    *,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    if final is None:
        return {
            "final_sample_status": "unavailable_after_fail_closed",
            "final_sample_reason": unavailable_reason or "resource_sample_unavailable",
            "docker_total_bytes_before": baseline.docker_total_bytes,
            "docker_total_bytes_after": None,
            "docker_growth_bytes": None,
            "docker_desktop_vhdx_bytes_before": baseline.docker_desktop_vhdx_bytes,
            "docker_desktop_vhdx_bytes_after": None,
            "docker_desktop_vhdx_growth_bytes": None,
            "windows_c_free_bytes_before": baseline.windows_free_bytes,
            "windows_c_free_bytes_after": None,
        }
    return {
        "final_sample_status": "complete",
        "final_sample_reason": None,
        "docker_total_bytes_before": baseline.docker_total_bytes,
        "docker_total_bytes_after": final.docker_total_bytes,
        "docker_growth_bytes": final.docker_total_bytes - baseline.docker_total_bytes,
        "docker_desktop_vhdx_bytes_before": baseline.docker_desktop_vhdx_bytes,
        "docker_desktop_vhdx_bytes_after": final.docker_desktop_vhdx_bytes,
        "docker_desktop_vhdx_growth_bytes": (
            final.docker_desktop_vhdx_bytes - baseline.docker_desktop_vhdx_bytes
        ),
        "windows_c_free_bytes_before": baseline.windows_free_bytes,
        "windows_c_free_bytes_after": final.windows_free_bytes,
    }


def _store_final_storage(
    *,
    paths: RepoPaths,
    identity: BoundedObservationIdentity,
    counter: DockerCliCounter,
    baseline: StorageBaseline,
) -> None:
    with BoundedObservationState(
        state_path(paths, identity), identity=identity
    ) as state:
        if state.snapshot().get("final_storage") is not None:
            return
    unavailable_reason = None
    try:
        final = _sample_storage(counter, identity.slots[0].run_id, baseline=baseline)
    except (CampaignExecutionError, DockerSupervisionError, RuntimeBridgeError) as exc:
        final = None
        unavailable_reason = type(exc).__name__
    with BoundedObservationState(
        state_path(paths, identity), identity=identity
    ) as state:
        state.store_final_storage(
            _storage_projection(
                baseline,
                final,
                unavailable_reason=unavailable_reason,
            )
        )


def _paid_worker(paths: RepoPaths, args: argparse.Namespace) -> int:
    identity, config, manifest, seccomp, provider, counter, baseline, proof = (
        _worker_inputs(paths, args)
    )
    verify_task_budget(paths, identity)
    with BoundedObservationState(
        state_path(paths, identity), identity=identity
    ) as state:
        initial_state = state.snapshot()
    if initial_state["status"] == "running":
        try:
            _sample_storage(counter, identity.slots[0].run_id, baseline=baseline)
        except (CampaignExecutionError, DockerSupervisionError, RuntimeBridgeError):
            if not initial_state["formal_boundary"]:
                raise
            with BoundedObservationState(
                state_path(paths, identity), identity=identity
            ) as state:
                state.invalidate("campaign_resource_gate_rejected")
            _store_final_storage(
                paths=paths,
                identity=identity,
                counter=counter,
                baseline=baseline,
            )
            return 3
    with BoundedObservationState(
        state_path(paths, identity), identity=identity
    ) as state:
        claimed = state.claim_or_resume_slot()
        terminal_now = state.snapshot()["status"]
    if claimed is None:
        if terminal_now in {"ready_to_finalize", "invalid"}:
            _store_final_storage(
                paths=paths,
                identity=identity,
                counter=counter,
                baseline=baseline,
            )
        return 0 if terminal_now == "ready_to_finalize" else 3
    slot, execution_attempt = claimed
    work_root = slot_root(paths, identity, slot) / f"attempt-{execution_attempt}"
    work_root.mkdir(parents=True, exist_ok=False, mode=0o700)
    metadata_path = work_root / "api-metadata.json"
    validate_frozen_task_source(
        paths.common_root / _SOURCE_CHECKOUT_RELPATH, identity.task(slot.task_id)
    )
    with PersistentBudgetLedger(
        budget_path(paths, identity),
        batch_id=identity.batch_id,
        total_cap_usd=identity.campaign_cap_usd,
        max_runs=len(identity.slots),
        default_run_cap_usd=PLAN056_RUN_CAP_USD,
        unpriced_fallback_usd=PLAN056_UNPRICED_FALLBACK_USD,
        unpriced_fallback_per_attempt=True,
    ) as ledger:
        snapshot = ledger.snapshot()
        try:
            recovered = _recover_record_if_complete(
                paths=paths,
                identity=identity,
                slot=slot,
                budget_snapshot=snapshot,
            )
        except BoundedObservationError:
            if not _has_sent_attempt(snapshot["runs"].get(slot.run_id)):
                raise
            with BoundedObservationState(
                state_path(paths, identity), identity=identity
            ) as state:
                state.mark_formal_boundary()
                state.invalidate("published_slot_source_integrity_failed")
            _store_final_storage(
                paths=paths,
                identity=identity,
                counter=counter,
                baseline=baseline,
            )
            return 3
        if recovered is not None:
            with BoundedObservationState(
                state_path(paths, identity), identity=identity
            ) as state:
                state.mark_formal_boundary()
                state.publish_slot(slot.slot_id, record_sha256=recovered)
                terminal = state.snapshot()["status"]
            if terminal == "ready_to_finalize":
                _store_final_storage(
                    paths=paths, identity=identity, counter=counter, baseline=baseline
                )
            return 10
        run = snapshot["runs"].get(slot.run_id)
        if run is None:
            ledger.claim_run(slot.run_id, cap_usd=PLAN056_RUN_CAP_USD)
        elif _has_sent_attempt(run):
            with BoundedObservationState(
                state_path(paths, identity), identity=identity
            ) as state:
                state.mark_formal_boundary()
                state.invalidate("sent_slot_has_no_complete_projection")
            _store_final_storage(
                paths=paths, identity=identity, counter=counter, baseline=baseline
            )
            return 3
        elif not run["requests"]:
            ledger.resume_pristine_run(slot.run_id, cap_usd=PLAN056_RUN_CAP_USD)
        else:
            ledger.resume_unsent_run(slot.run_id, cap_usd=PLAN056_RUN_CAP_USD)
        _secret_name, api_key = load_provider_secret(config)
        request = _make_request(
            paths=paths,
            identity=identity,
            task=identity.task(slot.task_id),
            manifest=manifest,
            work_root=work_root,
            docker_task_id=slot.run_id,
            seccomp_profile=seccomp,
            stub=False,
        )

        def validate_prepared(prepared: Any) -> None:
            _validate_prepared(
                prepared,
                identity=identity,
                task=identity.task(slot.task_id),
                manifest=manifest,
                stub=False,
            )

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
                    run_cap_usd=PLAN056_RUN_CAP_USD,
                    max_concurrent_main=1,
                    counter_sample_timeout_seconds=(
                        _PLAN056_DOCKER_COUNTER_SAMPLE_TIMEOUT_SECONDS
                    ),
                )
            )
            parsed = parse_single_task_result(
                live.harbor.trial_dir,
                host_returncode=live.harbor.returncode,
                expected_task_id=slot.task_id,
            )
            parsed = classify_terminal_bench_result(live, parsed)
            digest = _write_slot_record(
                paths=paths,
                identity=identity,
                slot=slot,
                live=live,
                parsed=parsed,
                metadata_path=metadata_path,
            )
        except BaseException:
            ledger.recover_interrupted_requests()
            sent = _has_sent_attempt(ledger.snapshot()["runs"].get(slot.run_id))
            if sent:
                with BoundedObservationState(
                    state_path(paths, identity), identity=identity
                ) as state:
                    state.mark_formal_boundary()
                    state.invalidate("sent_slot_execution_or_projection_failed")
                _store_final_storage(
                    paths=paths, identity=identity, counter=counter, baseline=baseline
                )
            raise
    _sample_storage(counter, identity.slots[0].run_id, baseline=baseline)
    with BoundedObservationState(
        state_path(paths, identity), identity=identity
    ) as state:
        state.mark_formal_boundary()
        state.publish_slot(slot.slot_id, record_sha256=digest)
        terminal = state.snapshot()["status"]
    if terminal == "ready_to_finalize":
        _store_final_storage(
            paths=paths, identity=identity, counter=counter, baseline=baseline
        )
    return 10


def _metrics_root(paths: RepoPaths, value: Path | None) -> Path:
    candidate = value or (paths.common_root / _DEFAULT_METRICS_RELPATH)
    resolved = candidate if candidate.is_absolute() else paths.common_root / candidate
    resolved = resolved.resolve(strict=False)
    if not resolved.is_relative_to(paths.common_root.resolve(strict=True)):
        raise BoundedObservationError(
            "Plan 056 metrics directory is outside the project"
        )
    return resolved


def _coordinator(paths: RepoPaths, args: argparse.Namespace, *, mode: str) -> int:
    if args.docker_host_volume is None:
        raise BoundedObservationError("Plan 056 Docker host volume is required")
    identity = load_identity(paths)
    if mode == "paid":
        if args.paid_action != PLAN056_PAID_ACTION:
            raise BoundedObservationError("Plan 056 explicit paid action is required")
        verify_task_budget(paths, identity)
    metrics = _metrics_root(paths, args.metrics_dir)
    lease_path = campaign_root(paths, identity) / "executor.lock"
    with CampaignExecutionLease(lease_path) as lease:
        for _step in range(_MAX_COORDINATOR_STEPS):
            argv = (
                str(paths.worktree_root / "scripts/with-build-lock.sh"),
                sys.executable,
                "-B",
                "-m",
                "rondo_eval.terminal_bench.bounded_observation_cli",
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
            completed = subprocess.run(
                argv,
                cwd=paths.worktree_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                check=False,
            )
            if completed.returncode == 10:
                continue
            return completed.returncode
    raise BoundedObservationError("Plan 056 coordinator step bound was exceeded")


def _published_records(
    paths: RepoPaths,
    identity: BoundedObservationIdentity,
    state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    records = []
    for slot, row in zip(identity.slots, state["slots"], strict=True):
        if row["status"] != "published":
            continue
        raw = _read_regular(slot_record_path(paths, identity, slot))
        if hashlib.sha256(raw).hexdigest() != row["record_sha256"]:
            raise BoundedObservationError("Plan 056 slot record digest drifted")
        record = validate_slot_record(json.loads(raw), identity=identity, slot=slot)
        _revalidate_record_sources(
            paths=paths,
            identity=identity,
            slot=slot,
            record=record,
        )
        records.append(record)
    return records


def finalize(paths: RepoPaths, *, snapshot_date: str) -> dict[str, Any]:
    identity = load_identity(paths, allow_retired=True)
    state_file = state_path(paths, identity)
    state = _read_json(state_file)
    if state["status"] == "finalized":
        return status(paths)
    if state["status"] not in {"ready_to_finalize", "invalid"}:
        raise BoundedObservationError("Plan 056 campaign is not ready to finalize")
    if state.get("final_storage") is None:
        raise BoundedObservationError("Plan 056 final storage sample is missing")
    budget = _load_budget_snapshot(paths, identity)
    source_invalidated = False
    if state["status"] == "ready_to_finalize":
        try:
            records = _published_records(paths, identity, state)
        except BoundedObservationError:
            with BoundedObservationState(state_file, identity=identity) as state_ledger:
                state_ledger.invalidate("published_slot_source_integrity_failed")
                state = state_ledger.snapshot()
            records = []
            source_invalidated = True
    else:
        # An already invalid campaign makes no inference from its formal rows.
        # The budget and state remain authoritative for conservative closure.
        records = []
    if state["status"] == "ready_to_finalize" and len(records) != len(identity.slots):
        raise BoundedObservationError("Plan 056 valid denominator is incomplete")
    result = public_result(
        identity=identity,
        state=state,
        budget=budget,
        records=records,
        snapshot_date=snapshot_date,
    )
    destination = paths.worktree_root / PLAN056_PUBLIC_RESULT_RELPATH
    if destination.exists() and not destination.is_symlink():
        if json.loads(_read_regular(destination)) != result:
            if not source_invalidated:
                raise BoundedObservationError("Plan 056 public result drifted")
            _atomic_json(destination, result, mode=0o644)
    else:
        _atomic_json(destination, result, mode=0o644)
    terminal_status = "invalid" if result["status"] == "invalid" else "passed"
    close_envelope_and_pointer(
        paths,
        identity=identity,
        terminal_status=terminal_status,
        spent_usd=Decimal(str(budget["spent_usd"])),
    )
    with BoundedObservationState(state_file, identity=identity) as ledger:
        ledger.finalize(
            outcome=result["outcome"],
            selected_candidate=result["selected_candidate"],
        )
    return result


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
            if (
                args.runtime_manifest is None
                or args.run_id_date is None
                or args.run_id_sequence_base is None
            ):
                raise BoundedObservationError("Plan 056 initialize inputs are required")
            identity = initialize_identity(
                paths,
                runtime_manifest=args.runtime_manifest,
                run_id_date=args.run_id_date,
                run_id_sequence_base=args.run_id_sequence_base,
            )
            print(
                json.dumps(
                    {
                        "status": "initialized",
                        "campaign_id": identity.campaign_id,
                        "campaign_lock_sha256": identity.lock_sha256,
                        "campaign_slots": len(identity.slots),
                        "required_paid_action": PLAN056_PAID_ACTION,
                        "paid_requests_sent": 0,
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.action == "preflight":
            return _coordinator(paths, args, mode="preflight")
        if args.action in {"run", "resume"}:
            return _coordinator(paths, args, mode="paid")
        print(
            json.dumps(
                finalize(paths, snapshot_date=args.snapshot_date), sort_keys=True
            )
        )
        return 0
    except (
        BoundedObservationError,
        DockerSupervisionError,
        RuntimeBridgeError,
        ValueError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": str(exc),
                    "paid_requests_sent": 0,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
