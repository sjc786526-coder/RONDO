"""Strict Terminal-Bench result parsing and private artifact publication."""

from __future__ import annotations

import json
import math
import os
import re
import stat
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from ..api_budget_proxy import ApiBudgetProxyError, completed_run_accounting
from ..artifacts import ArtifactWriter
from ..config import RepoPaths
from ..contracts import BinaryManifest, ProviderProjection, RunOutcome, Side
from .freeze import (
    FIX_GIT_IMAGE_DIGEST,
    FIX_GIT_TASK_ID,
    TERMINAL_BENCH_COMMIT,
    TERMINAL_BENCH_VERSION,
)
from .live import BudgetedTerminalBenchResult, load_guardian_evidence_bundle
from .metrics import RunMetricsError, metrics_from_dict
from .pair import (
    RunPublicationContext,
    has_complete_guardian_approval_sequence,
)


UPSTREAM_CODEX = {
    "tag": "rust-v0.147.0",
    "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
    "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
}
_MAX_RESULT_BYTES = 8 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_AGENT_EXCEPTION_TYPES = {
    "AgentSafetyRefusalError",
    "AgentTimeoutError",
    "ContextWindowExceededError",
    "NonZeroAgentExitCodeError",
    "OutputTokenExceededError",
}
_PRIVATE_EVIDENCE_FILES = (
    "agent/codex.txt",
    "artifacts/manifest.json",
    "verifier/ctrf.json",
    "verifier/reward.txt",
    "verifier/test-stdout.txt",
)


class HarborResultError(ValueError):
    """Raised when Harbor's one-task result is missing or ambiguous."""


@dataclass(frozen=True)
class ParsedHarborResult:
    outcome: RunOutcome
    task_outcome: str
    reward: float
    duration_seconds: float
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    job_result: Mapping[str, Any]
    trial_result: Mapping[str, Any]


def validate_measurement_checkout(
    paths: RepoPaths,
    *,
    side: Side,
    manifest: BinaryManifest,
) -> str:
    """Require a clean detached measurement worktree before any paid request."""

    root = paths.worktree_root
    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise HarborResultError("measurement checkout is not the worktree root")
    commit = _git(root, "rev-parse", "HEAD")
    symbolic = _git_result(root, "symbolic-ref", "-q", "HEAD")
    if symbolic.returncode != 1:
        raise HarborResultError("measurement checkout must be detached")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise HarborResultError("measurement checkout is dirty")
    if side is Side.RONDO:
        if manifest.source_commit != commit or manifest.workspace_lock_normalization is not None:
            raise HarborResultError("RONDO binary does not match the measurement commit")
    elif side is Side.CODEX:
        if (
            manifest.source_commit != UPSTREAM_CODEX["commit"]
            or manifest.workspace_lock_normalization
            != UPSTREAM_CODEX["workspace_lock_normalization"]
        ):
            raise HarborResultError("Codex binary does not match the frozen upstream baseline")
    else:  # pragma: no cover - Side is closed, retained for defensive callers.
        raise HarborResultError("unsupported Terminal-Bench side")
    return commit


def validate_results_worktree(path: Path, *, common_root: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        result_paths = RepoPaths.discover(resolved)
    except (OSError, ValueError) as exc:
        raise HarborResultError("results worktree is unavailable") from exc
    if result_paths.worktree_root != resolved or result_paths.common_root != common_root:
        raise HarborResultError("results worktree does not belong to this RONDO repository")
    return resolved


def validate_eval_harness_checkout(*, common_root: Path) -> str:
    """Bind the externally loaded eval harness to one clean repository commit."""

    root = Path(__file__).resolve().parents[3]
    try:
        harness_paths = RepoPaths.discover(root)
    except (OSError, ValueError) as exc:
        raise HarborResultError("eval harness checkout is unavailable") from exc
    if harness_paths.worktree_root != root or harness_paths.common_root != common_root:
        raise HarborResultError("eval harness checkout is outside this RONDO repository")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise HarborResultError("eval harness checkout is dirty")
    relative_source = Path(__file__).resolve().relative_to(root).as_posix()
    if _git_result(root, "ls-files", "--error-unmatch", relative_source).returncode != 0:
        raise HarborResultError("eval harness source is not tracked")
    return _git(root, "rev-parse", "HEAD")


def parse_single_task_result(
    trial_dir: Path,
    *,
    host_returncode: int,
) -> ParsedHarborResult:
    """Parse Harbor 0.20's exact single-trial result; host rc alone is not success."""

    if isinstance(host_returncode, bool) or not isinstance(host_returncode, int):
        raise HarborResultError("Harbor host return code is invalid")
    root = _optional_result_directory(
        trial_dir,
        allow_missing=host_returncode != 0,
    )
    if root is None:
        return _infra_result_without_harbor_tree()
    if host_returncode != 0 and not _path_present(root / "result.json"):
        return _infra_result_without_harbor_tree()
    trial = _read_json_object(root / "result.json")
    trial_name = trial.get("trial_name")
    if not isinstance(trial_name, str) or trial_name != root.name:
        raise HarborResultError("Harbor trial identity differs from its directory")
    exception_type = _exception_type(trial.get("exception_info"))
    if host_returncode != 0:
        outcome = RunOutcome.INFRA_FAILED
    elif exception_type is None:
        outcome = RunOutcome.COMPLETED
    elif exception_type == "CancelledError":
        outcome = RunOutcome.CANCELLED
    elif exception_type in _AGENT_EXCEPTION_TYPES:
        outcome = RunOutcome.AGENT_FAILED
    else:
        outcome = RunOutcome.INFRA_FAILED

    if trial.get("task_name") != FIX_GIT_TASK_ID:
        raise HarborResultError("Harbor trial task identity differs from the freeze")
    verifier = trial.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    reward = rewards.get("reward") if isinstance(rewards, dict) else None
    if outcome is not RunOutcome.COMPLETED:
        reward = 0.0
    if (
        isinstance(reward, bool)
        or not isinstance(reward, (int, float))
        or not math.isfinite(float(reward))
        or not 0 <= float(reward) <= 1
    ):
        raise HarborResultError("Harbor trial reward is invalid")
    duration = _trial_duration(trial, outcome=outcome)
    agent_result = trial.get("agent_result")
    if agent_result is None and outcome is not RunOutcome.COMPLETED:
        input_tokens = cached_tokens = output_tokens = 0
    elif not isinstance(agent_result, dict):
        raise HarborResultError("Harbor agent result is missing")
    else:
        input_tokens = _optional_uint(agent_result.get("n_input_tokens"), "input tokens")
        cached_tokens = _optional_uint(agent_result.get("n_cache_tokens"), "cache tokens")
        output_tokens = _optional_uint(agent_result.get("n_output_tokens"), "output tokens")
    if cached_tokens > input_tokens:
        raise HarborResultError("Harbor cached tokens exceed input tokens")
    return ParsedHarborResult(
        outcome=outcome,
        task_outcome="pass" if float(reward) > 0 else "fail",
        reward=float(reward),
        duration_seconds=duration,
        input_tokens=input_tokens,
        cached_tokens=cached_tokens,
        output_tokens=output_tokens,
        # The official single-trial CLI has no JobResult.  Keep the field empty
        # for the stable internal type instead of fabricating aggregate stats.
        job_result={},
        trial_result=trial,
    )


def publish_terminal_bench_result(
    paths: RepoPaths,
    *,
    results_worktree_root: Path,
    run_id: str,
    side: Side,
    git_commit: str,
    eval_harness_commit: str,
    live_result: BudgetedTerminalBenchResult,
    parsed: ParsedHarborResult,
    metadata_path: Path,
    publication: RunPublicationContext,
    writer: ArtifactWriter | None = None,
) -> Path:
    """Archive private raw evidence and append one strict tracked record."""

    parsed = classify_terminal_bench_result(live_result, parsed)
    if not _is_commit(eval_harness_commit):
        raise HarborResultError("eval harness commit is invalid")
    if live_result.prepared.spec.side is not side:
        raise HarborResultError("prepared side differs from publication side")
    _validate_publication_context(publication, side=side)
    request_roles = _validate_publication_evidence(
        live_result,
        parsed,
        metadata_path=metadata_path,
    )
    budget_accounting: dict[str, object] | None = None
    if parsed.outcome is RunOutcome.COMPLETED:
        try:
            budget_accounting = completed_run_accounting(
                live_result.budget_snapshot, run_id
            )
        except ApiBudgetProxyError as exc:
            raise HarborResultError("completed run budget accounting is invalid") from exc
        metadata_request_ids = _verified_request_ids(metadata_path)
        budget_runs = live_result.budget_snapshot.get("runs")
        budget_run = budget_runs.get(run_id) if isinstance(budget_runs, Mapping) else None
        budget_requests = (
            budget_run.get("requests") if isinstance(budget_run, Mapping) else None
        )
        if (
            budget_accounting["request_count"] != len(request_roles)
            or not isinstance(budget_requests, Mapping)
            or set(budget_requests) != set(metadata_request_ids)
        ):
            raise HarborResultError("completed budget requests differ from API metadata")
    writer = writer or ArtifactWriter(
        paths, run_id, results_worktree_root=results_worktree_root
    ).start()
    if writer.run_id != run_id or writer.paths.common_root != paths.common_root:
        raise HarborResultError("artifact writer claim differs from the run")
    summary = _safe_summary(
        run_id,
        side,
        git_commit,
        eval_harness_commit,
        live_result,
        parsed,
        request_roles=request_roles,
        budget_accounting=budget_accounting,
        publication=publication,
    )
    writer.write_json("run-summary.json", summary)
    if parsed.trial_result:
        _write_harbor_evidence(writer, live_result.harbor.jobs_dir, parsed)
    else:
        writer.write_json(
            "harbor/jobs-unavailable.json",
            {
                "schema_version": 1,
                "outcome": RunOutcome.INFRA_FAILED.value,
                "host_returncode": live_result.harbor.returncode,
            },
        )
    _write_guardian_evidence(writer, live_result, side=side)
    try:
        metadata = _read_json_object(metadata_path)
    except HarborResultError:
        if (
            parsed.outcome is RunOutcome.COMPLETED
            or live_result.metadata_ready
            or _path_present(metadata_path)
        ):
            raise
        writer.write_json(
            "api-metadata-unavailable.json",
            {
                "schema_version": 1,
                "metadata_ready": False,
                "outcome": parsed.outcome.value,
            },
        )
    else:
        writer.write_json("api-metadata.json", metadata)

    spent = _run_spend(live_result.budget_snapshot, run_id)
    has_unsettled_reservation = _run_has_unsettled_reservation(
        live_result.budget_snapshot, run_id
    )
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "track": "tb",
        "side": side.value,
        "git_commit": git_commit,
        "git_dirty": False,
        "binary_sha256": live_result.prepared.spec.binary.sha256,
        "upstream_codex": dict(UPSTREAM_CODEX),
        "config": summary["config"],
        "outcome": parsed.outcome.value,
        "summary": summary["summary"],
        "tasks": summary["tasks"],
        "metrics": dict(publication.metrics),
        "cost": _cost_from_budget_spend(
            spent, has_unsettled_reservation=has_unsettled_reservation
        ),
        "artifacts": f"eval-data/runs/{run_id}",
        "notes": (
            "estimated_usd is settled local budget accounting from the selected rate-card "
            "snapshot; "
            "actual_usd is null for non-zero spend or an unsettled reservation because no "
            "invoice was queried."
        ),
    }
    _validate_terminal_bench_record(record)
    return writer.finalize(record, secrets=live_result.redaction_secrets)


def classify_terminal_bench_result(
    live_result: BudgetedTerminalBenchResult,
    parsed: ParsedHarborResult,
) -> ParsedHarborResult:
    """Treat pre-API adapter exits as infrastructure, not model behavior."""

    if parsed.outcome is RunOutcome.AGENT_FAILED and not live_result.metadata_ready:
        return replace(parsed, outcome=RunOutcome.INFRA_FAILED)
    return parsed


def publish_terminal_bench_failure(
    paths: RepoPaths,
    *,
    writer: ArtifactWriter,
    run_id: str,
    side: Side,
    git_commit: str,
    eval_harness_commit: str,
    manifest: BinaryManifest,
    provider: ProviderProjection,
    budget_snapshot: Mapping[str, object],
    metadata_path: Path,
    outcome: RunOutcome,
    failure_stage: str,
    publication: RunPublicationContext,
    secrets: tuple[str, ...],
) -> Path:
    """Publish a safe terminal record after a claimed run exits exceptionally."""

    if outcome not in {
        RunOutcome.INFRA_FAILED,
        RunOutcome.BUDGET_STOPPED,
        RunOutcome.CANCELLED,
    }:
        raise HarborResultError("exceptional publication outcome is invalid")
    if failure_stage not in {
        "budget",
        "docker",
        "runtime",
        "result",
        "publication",
        "interrupted",
    }:
        raise HarborResultError("exceptional publication stage is invalid")
    if not _is_commit(git_commit) or not _is_commit(eval_harness_commit):
        raise HarborResultError("exceptional publication commit is invalid")
    if writer.run_id != run_id or writer.paths.common_root != paths.common_root:
        raise HarborResultError("artifact writer claim differs from the failed run")
    try:
        provider_public = provider.to_public_dict()
    except ValueError as exc:
        raise HarborResultError("exceptional publication provider is invalid") from exc
    _validate_publication_context(publication, side=side)
    selected_profile = dict(publication.selected_profile)
    if any(selected_profile.get(key) != value for key, value in provider_public.items()):
        raise HarborResultError("exceptional publication provider differs from the pair lock")
    spent = _run_spend(budget_snapshot, run_id)
    has_unsettled_reservation = _run_has_unsettled_reservation(
        budget_snapshot, run_id
    )
    config = {
        **selected_profile,
        "batch_id": budget_snapshot.get("batch_id"),
        "terminal_bench_version": TERMINAL_BENCH_VERSION,
        "terminal_bench_commit": TERMINAL_BENCH_COMMIT,
        "task_image_digest": FIX_GIT_IMAGE_DIGEST,
        "binary_source_commit": manifest.source_commit,
        "eval_harness_commit": eval_harness_commit,
        "binary_workspace_lock_normalization": manifest.workspace_lock_normalization,
        "failure_stage": failure_stage,
        "pair_id": publication.pair_id,
        "pair_lock_sha256": publication.pair_lock_sha256,
        "pair_slot": publication.pair_slot,
        "pair_round": publication.pair_round,
    }
    metadata: dict[str, Any] | None = None
    request_roles: tuple[str, ...] = ()
    try:
        candidate_metadata = _read_json_object(metadata_path)
        metadata = candidate_metadata
    except HarborResultError:
        pass
    if metadata is not None:
        try:
            request_roles = _declared_request_roles(metadata)
        except HarborResultError:
            request_roles = ()
    try:
        metadata_ready = (
            bool(_request_roles(metadata)) if metadata is not None else False
        )
    except HarborResultError:
        metadata_ready = False
    summary = {
        "tasks_total": 1,
        "infra_failed": 1 if outcome is RunOutcome.INFRA_FAILED else 0,
        "budget_stopped": 1 if outcome is RunOutcome.BUDGET_STOPPED else 0,
        "cancelled": 1 if outcome is RunOutcome.CANCELLED else 0,
        "metadata_ready": metadata_ready,
        "api_request_roles": {
            "main": request_roles.count("main"),
            "guardian": request_roles.count("guardian"),
        },
        "api_request_sequence": list(request_roles),
    }
    tasks = [
        {
            "task_id": FIX_GIT_TASK_ID,
            "outcome": "fail",
            "attribution": "infra",
            "reward": 0.0,
            "duration_s": 0.0,
            "tokens_in": 0,
            "tokens_cached": 0,
            "tokens_out": 0,
        }
    ]
    writer.write_json(
        "run-failure.json",
        {
            "schema_version": 1,
            "run_id": run_id,
            "outcome": outcome.value,
            "failure_stage": failure_stage,
        },
    )
    if metadata is None:
        writer.write_json(
            "api-metadata-unavailable.json",
            {"schema_version": 1, "metadata_ready": False, "outcome": outcome.value},
        )
    else:
        writer.write_json("api-metadata.json", metadata)
    record = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "track": "tb",
        "side": side.value,
        "git_commit": git_commit,
        "git_dirty": False,
        "binary_sha256": manifest.sha256,
        "upstream_codex": dict(UPSTREAM_CODEX),
        "config": config,
        "outcome": outcome.value,
        "summary": summary,
        "tasks": tasks,
        "metrics": dict(publication.metrics),
        "cost": _cost_from_budget_spend(
            spent, has_unsettled_reservation=has_unsettled_reservation
        ),
        "artifacts": f"eval-data/runs/{run_id}",
        "notes": (
            "Run exited after its paid-run claim; failure details are intentionally categorical. "
            "estimated_usd is settled local budget accounting; actual_usd is null for non-zero "
            "spend or an unsettled reservation."
        ),
    }
    _validate_terminal_bench_record(record)
    return writer.finalize(record, secrets=secrets)


def _safe_summary(
    run_id: str,
    side: Side,
    git_commit: str,
    eval_harness_commit: str,
    live_result: BudgetedTerminalBenchResult,
    parsed: ParsedHarborResult,
    *,
    request_roles: tuple[str, ...],
    budget_accounting: Mapping[str, object] | None,
    publication: RunPublicationContext,
) -> dict[str, Any]:
    spec = live_result.prepared.spec
    evidence = [
        {
            # Publication revalidates the private Harbor source path, then
            # archives under a review-id-independent stable location.  Public
            # consumers must only receive the durable archived path.
            "relative_path": f"guardian-evidence/{index:04d}/E_final.json",
            "review_id": item.review_id,
            "guardian_source_baseline": item.guardian_source_baseline,
            "guardian_source_commit": item.guardian_source_commit,
            "policy_sha256": item.policy.sha256,
            "request_shape": item.policy.request_shape,
            "model": item.model,
            "reasoning_effort": item.reasoning_effort,
            "terminal_status": item.terminal_status,
            "canonical_request_sha256": item.canonical_request_sha256,
        }
        for index, item in enumerate(live_result.evidence, start=1)
    ]
    effective_task_outcome = (
        parsed.task_outcome
        if parsed.outcome in {RunOutcome.COMPLETED, RunOutcome.AGENT_FAILED}
        else "fail"
    )
    effective_reward = (
        parsed.reward
        if parsed.outcome in {RunOutcome.COMPLETED, RunOutcome.AGENT_FAILED}
        else 0.0
    )
    guardian_requests = request_roles.count("guardian")
    if side is Side.RONDO and (
        parsed.outcome is RunOutcome.COMPLETED
        and guardian_requests >= 1
        and len(evidence) == guardian_requests
        and all(item["terminal_status"] == "approved" for item in evidence)
        and has_complete_guardian_approval_sequence(request_roles)
    ):
        # The paid pair bounds distinct Guardian request bodies and rejects a
        # duplicate charged replay. Equal verified request/evidence counts form
        # a task-scoped set binding without persisting a private request body.
        s2_binding = "verified"
    elif side is Side.RONDO and (guardian_requests or evidence):
        s2_binding = "unbound"
    else:
        s2_binding = "not_triggered"
    provider_public = spec.provider.to_public_dict()
    selected_profile = dict(publication.selected_profile)
    if any(selected_profile.get(key) != value for key, value in provider_public.items()):
        raise HarborResultError("result provider differs from the selected pair profile")
    return {
        "schema_version": 1,
        "run_id": run_id,
        "side": side.value,
        "git_commit": git_commit,
        "outcome": parsed.outcome.value,
        "config": {
            **selected_profile,
            "approvals_reviewer": spec.approvals_reviewer,
            "approval_policy": spec.approval_policy,
            "sandbox_mode": spec.sandbox_mode,
            "sandbox_network_access": spec.sandbox_network_access,
            "websocket": spec.websocket,
            "code_mode_host": spec.code_mode_host,
            "terminal_bench_version": TERMINAL_BENCH_VERSION,
            "terminal_bench_commit": TERMINAL_BENCH_COMMIT,
            "task_image_digest": FIX_GIT_IMAGE_DIGEST,
            "binary_source_commit": spec.binary.source_commit,
            "eval_harness_commit": eval_harness_commit,
            "binary_workspace_lock_normalization": spec.binary.workspace_lock_normalization,
            "bwrap_runtime_path": "/opt/rondo-eval/bin/codex-resources/bwrap",
            "bwrap_sha256": spec.binary.bwrap_sha256,
            "bwrap_asset_url": spec.binary.bwrap_asset_url,
            "bwrap_archive_sha256": spec.binary.bwrap_archive_sha256,
            "bwrap_source_tree_sha256": spec.binary.bwrap_source_tree_sha256,
            "timeout_seconds": spec.timeout_seconds,
            "max_retries": spec.max_retries,
            "budget_usd": spec.budget_usd,
            "pair_id": publication.pair_id,
            "pair_lock_sha256": publication.pair_lock_sha256,
            "pair_slot": publication.pair_slot,
            "pair_round": publication.pair_round,
        },
        "summary": {
            "success_rate": 1.0
            if parsed.outcome is RunOutcome.COMPLETED and effective_task_outcome == "pass"
            else 0.0,
            "tasks_total": 1,
            "infra_failed": 1 if parsed.outcome is RunOutcome.INFRA_FAILED else 0,
            "host_returncode": live_result.harbor.returncode,
            "metadata_ready": live_result.metadata_ready,
            "api_request_roles": {
                "main": request_roles.count("main"),
                "guardian": guardian_requests,
            },
            "api_request_sequence": list(request_roles),
            "budget_accounting": (
                dict(budget_accounting) if budget_accounting is not None else None
            ),
            "docker_samples": len(live_result.harbor.docker_evidence.samples)
            if live_result.harbor.docker_evidence is not None
            else 0,
            "docker_warnings": list(live_result.harbor.docker_evidence.warnings)
            if live_result.harbor.docker_evidence is not None
            else [],
            "evidence": evidence,
            "s2_request_evidence_binding": s2_binding,
        },
        "tasks": [
            {
                "task_id": FIX_GIT_TASK_ID,
                "outcome": effective_task_outcome,
                "attribution": "agent"
                if parsed.outcome in {RunOutcome.COMPLETED, RunOutcome.AGENT_FAILED}
                else "infra",
                "reward": effective_reward,
                "duration_s": parsed.duration_seconds,
                "tokens_in": parsed.input_tokens,
                "tokens_cached": parsed.cached_tokens,
                "tokens_out": parsed.output_tokens,
            }
        ],
    }


def _write_harbor_evidence(
    writer: ArtifactWriter,
    source: Path,
    parsed: ParsedHarborResult,
) -> None:
    """Archive a deliberate private subset, never Harbor configs, locks, or raw logs."""

    trial_directory = _regular_directory(source)
    if parsed.job_result:
        raise HarborResultError("single-trial publication cannot contain a JobResult")
    writer.write_json(
        "harbor/trial-result.json",
        {
            "schema_version": 1,
            "task_name": FIX_GIT_TASK_ID,
            "outcome": parsed.outcome.value,
            "task_outcome": parsed.task_outcome,
            "reward": parsed.reward,
            "duration_seconds": parsed.duration_seconds,
            "tokens": {
                "input": parsed.input_tokens,
                "cached": parsed.cached_tokens,
                "output": parsed.output_tokens,
            },
            "exception_type": _exception_type(parsed.trial_result.get("exception_info")),
        },
    )
    total = 0
    for relative in _PRIVATE_EVIDENCE_FILES:
        path = trial_directory.joinpath(*relative.split("/"))
        try:
            contents = _read_bounded_regular_file(
                trial_directory,
                path,
                limit=_MAX_ARCHIVE_BYTES,
            )
        except FileNotFoundError:
            continue
        total += len(contents)
        if total > _MAX_ARCHIVE_BYTES:
            raise HarborResultError("Harbor evidence exceeds the bounded archive size")
        writer.write_bytes(f"harbor/{relative}", contents)


def _write_guardian_evidence(
    writer: ArtifactWriter,
    live_result: BudgetedTerminalBenchResult,
    *,
    side: Side,
) -> None:
    """Archive verified E_final/meta pairs under review-id-independent names."""

    if side is Side.CODEX:
        if live_result.evidence:
            raise HarborResultError("Codex baseline cannot publish RONDO Guardian evidence")
        return
    for index, expected in enumerate(live_result.evidence, start=1):
        observed, e_final_bytes, meta_bytes = load_guardian_evidence_bundle(
            live_result.harbor.jobs_dir,
            expected.relative_path,
            expected_model=live_result.prepared.spec.provider.guardian_model,
            expected_effort=live_result.prepared.spec.provider.guardian_effort,
        )
        if observed != expected:
            raise HarborResultError("Guardian evidence changed before publication")
        destination = f"guardian-evidence/{index:04d}"
        writer.write_bytes(f"{destination}/E_final.json", e_final_bytes)
        writer.write_bytes(f"{destination}/meta.json", meta_bytes)


def _read_bounded_regular_file(root: Path, path: Path, *, limit: int) -> bytes:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise HarborResultError("Harbor evidence path escaped the trial directory") from exc
    current = root
    for part in relative.parts:
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            raise
        except OSError as exc:
            raise HarborResultError("Harbor evidence file is unavailable") from exc
        if stat.S_ISLNK(mode):
            raise HarborResultError("Harbor evidence path contains a symlink")
    try:
        file_stat = path.stat()
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise HarborResultError("Harbor evidence file is unavailable") from exc
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > limit:
        raise HarborResultError("Harbor evidence file is unsafe")
    try:
        contents = path.read_bytes()
    except OSError as exc:
        raise HarborResultError("Harbor evidence cannot be read") from exc
    if len(contents) != file_stat.st_size:
        raise HarborResultError("Harbor evidence changed while being read")
    return contents


def _validate_publication_evidence(
    live_result: BudgetedTerminalBenchResult,
    parsed: ParsedHarborResult,
    *,
    metadata_path: Path,
) -> tuple[str, ...]:
    host_returncode = live_result.harbor.returncode
    has_trial_result = bool(parsed.trial_result)
    if parsed.job_result:
        raise HarborResultError("single-trial publication cannot contain a JobResult")
    if not has_trial_result:
        if parsed.outcome is not RunOutcome.INFRA_FAILED:
            raise HarborResultError("only infra failure may omit the Harbor result tree")
        root = _optional_result_directory(
            live_result.harbor.jobs_dir,
            allow_missing=True,
        )
        if root is not None and (root / "result.json").exists():
            raise HarborResultError("an existing Harbor result tree cannot be omitted")
    if parsed.outcome is RunOutcome.COMPLETED:
        if host_returncode != 0:
            raise HarborResultError("completed result has a non-zero Harbor return code")
        if not live_result.metadata_ready:
            raise HarborResultError("completed run lacks verified API metadata")
        roles = _verified_request_roles(metadata_path)
        if not has_complete_guardian_approval_sequence(roles):
            raise HarborResultError(
                "completed run lacks the verified main-Guardian-main sequence"
            )
        if live_result.prepared.spec.side is Side.RONDO:
            if (
                len(live_result.evidence) != roles.count("guardian")
                or any(
                    item.terminal_status != "approved"
                    for item in live_result.evidence
                )
            ):
                raise HarborResultError(
                    "RONDO completed run requires one approved evidence per Guardian request"
                )
            request_digests = _guardian_request_digests(metadata_path)
            evidence_digests = tuple(
                item.canonical_request_sha256 for item in live_result.evidence
            )
            if (
                any(digest is None for digest in evidence_digests)
                or len(set(evidence_digests)) != len(evidence_digests)
                or set(evidence_digests) != set(request_digests)
            ):
                raise HarborResultError(
                    "RONDO Guardian evidence is not bound to canonical requests"
                )
        elif live_result.evidence:
            raise HarborResultError("frozen Codex cannot publish RONDO Guardian evidence")
    elif (
        parsed.outcome is RunOutcome.INFRA_FAILED
        and host_returncode == 0
        and not has_trial_result
    ):
        raise HarborResultError("infra-failed result lacks Harbor failure evidence")
    else:
        roles = ()
        if _path_present(metadata_path):
            try:
                roles = _verified_request_roles(metadata_path)
            except HarborResultError:
                if live_result.metadata_ready:
                    raise
    return roles


def _validate_publication_context(
    publication: RunPublicationContext, *, side: Side
) -> None:
    try:
        publication.validate()
    except ValueError as exc:
        raise HarborResultError("Terminal-Bench publication context is invalid") from exc
    expected_slot = 1 if side is Side.RONDO else 2
    if publication.pair_slot != expected_slot:
        raise HarborResultError("publication side differs from the pair topology")


def _validate_terminal_bench_record(record: Mapping[str, Any]) -> None:
    """Enforce the P1 producer's cross-field invariants before publication."""

    try:
        outcome = RunOutcome(record.get("outcome"))
    except (TypeError, ValueError) as exc:
        raise HarborResultError("Terminal-Bench record outcome is invalid") from exc
    summary = record.get("summary")
    tasks = record.get("tasks")
    config = record.get("config")
    if (
        not isinstance(summary, dict)
        or not isinstance(tasks, list)
        or len(tasks) != 1
        or not isinstance(tasks[0], dict)
        or not isinstance(config, dict)
    ):
        raise HarborResultError("Terminal-Bench record sections are invalid")
    task = tasks[0]
    if task.get("task_id") != FIX_GIT_TASK_ID:
        raise HarborResultError("Terminal-Bench task identity is invalid")
    if task.get("attribution") not in {"agent", "infra"}:
        raise HarborResultError("Terminal-Bench attribution is invalid")
    if task.get("outcome") not in {"pass", "fail"}:
        raise HarborResultError("Terminal-Bench task outcome is invalid")
    reward = task.get("reward")
    if (
        isinstance(reward, bool)
        or not isinstance(reward, (int, float))
        or not math.isfinite(float(reward))
        or not 0 <= float(reward) <= 1
    ):
        raise HarborResultError("Terminal-Bench task reward is invalid")
    try:
        metrics = metrics_from_dict(record.get("metrics"))
    except RunMetricsError as exc:
        raise HarborResultError("Terminal-Bench external metrics are invalid") from exc
    if outcome is RunOutcome.COMPLETED:
        if metrics.exit_code != 0 or task["attribution"] != "agent":
            raise HarborResultError("completed Terminal-Bench record is contradictory")
    else:
        if (
            metrics.exit_code == 0
            or task["outcome"] != "fail"
            or float(reward) != 0.0
            or summary.get("success_rate", 0.0) != 0.0
        ):
            raise HarborResultError("non-completed Terminal-Bench record reports success")
        expected_attribution = "agent" if outcome is RunOutcome.AGENT_FAILED else "infra"
        if task["attribution"] != expected_attribution:
            raise HarborResultError("Terminal-Bench failure attribution is contradictory")
    roles = summary.get("api_request_roles")
    if not isinstance(roles, dict) or set(roles) != {"main", "guardian"} or any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in roles.values()
    ):
        raise HarborResultError("Terminal-Bench API role summary is invalid")
    sequence = summary.get("api_request_sequence")
    if (
        not isinstance(sequence, list)
        or any(role not in {"main", "guardian"} for role in sequence)
        or sequence.count("main") != roles["main"]
        or sequence.count("guardian") != roles["guardian"]
    ):
        raise HarborResultError("Terminal-Bench API request sequence is invalid")
    budget_accounting = summary.get("budget_accounting")
    if outcome is RunOutcome.COMPLETED:
        _validate_public_budget_accounting(
            budget_accounting,
            request_count=len(sequence),
            estimated_usd=record.get("cost", {}).get("estimated_usd")
            if isinstance(record.get("cost"), Mapping)
            else None,
        )
    elif budget_accounting is not None:
        raise HarborResultError("non-completed run contains completed budget accounting")
    if outcome is RunOutcome.COMPLETED and not has_complete_guardian_approval_sequence(
        sequence
    ):
        raise HarborResultError("completed Terminal-Bench approval sequence is incomplete")
    guardian_limit = config.get("max_guardian_logical_requests")
    if outcome is RunOutcome.COMPLETED and (
        isinstance(guardian_limit, bool)
        or not isinstance(guardian_limit, int)
        or roles["guardian"] > guardian_limit
    ):
        raise HarborResultError("completed Terminal-Bench approval count exceeds its lock")
    if outcome is RunOutcome.COMPLETED:
        evidence = summary.get("evidence")
        binding = summary.get("s2_request_evidence_binding")
        if record.get("side") == Side.RONDO.value:
            if (
                not isinstance(evidence, list)
                or len(evidence) != roles["guardian"]
                or any(
                    not isinstance(item, dict)
                    or item.get("terminal_status") != "approved"
                    or not isinstance(item.get("canonical_request_sha256"), str)
                    or re.fullmatch(
                        r"[0-9a-f]{64}", item["canonical_request_sha256"]
                    )
                    is None
                    for item in evidence
                )
                or len(
                    {item["canonical_request_sha256"] for item in evidence}
                )
                != len(evidence)
                or binding != "verified"
            ):
                raise HarborResultError("completed RONDO Guardian evidence is not bound")
        elif evidence or binding != "not_triggered":
            raise HarborResultError("completed frozen Codex record contains RONDO evidence")
    if (
        not isinstance(config.get("pair_id"), str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", config["pair_id"]) is None
        or not isinstance(config.get("pair_lock_sha256"), str)
        or config.get("pair_slot") not in {1, 2}
        or config.get("pair_round") != 1
    ):
        raise HarborResultError("Terminal-Bench pair identity is invalid")


def _validate_public_budget_accounting(
    value: object,
    *,
    request_count: int,
    estimated_usd: object,
) -> None:
    expected_keys = {
        "stopped",
        "stop_reason",
        "reserved_usd",
        "spent_usd",
        "request_count",
        "settled_request_count",
        "usage_valid_request_count",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise HarborResultError("completed budget accounting differs from schema v1")
    if (
        value.get("stopped") is not False
        or value.get("stop_reason") is not None
        or value.get("reserved_usd") != "0.000000"
        or value.get("request_count") != request_count
        or value.get("settled_request_count") != request_count
        or value.get("usage_valid_request_count") != request_count
        or request_count < 1
    ):
        raise HarborResultError("completed budget accounting is not fully settled")
    try:
        spent = Decimal(value.get("spent_usd"))
        estimated = Decimal(str(estimated_usd))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HarborResultError("completed budget spend is invalid") from exc
    if not spent.is_finite() or spent < 0 or spent != estimated:
        raise HarborResultError("completed budget spend differs from the public cost")


def _verified_request_roles(metadata_path: Path) -> tuple[str, ...]:
    metadata = _read_json_object(metadata_path)
    return _request_roles(metadata)


def _verified_request_ids(metadata_path: Path) -> tuple[str, ...]:
    metadata = _read_json_object(metadata_path)
    _request_roles(metadata)
    request_ids = tuple(item.get("request_id") for item in metadata["requests"])
    if (
        any(not isinstance(request_id, str) or not request_id for request_id in request_ids)
        or len(set(request_ids)) != len(request_ids)
    ):
        raise HarborResultError("API metadata request ids are invalid")
    return request_ids


def _guardian_request_digests(metadata_path: Path) -> tuple[str, ...]:
    metadata = _read_json_object(metadata_path)
    roles = _request_roles(metadata)
    requests = metadata["requests"]
    digests: list[str] = []
    for role, request in zip(roles, requests, strict=True):
        if role != "guardian":
            continue
        digest = request.get("canonical_body_sha256")
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise HarborResultError("Guardian request canonical digest is invalid")
        digests.append(digest)
    if len(set(digests)) != len(digests):
        raise HarborResultError("Guardian request canonical digest is duplicated")
    return tuple(digests)


def _request_roles(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    roles = _declared_request_roles(metadata)
    requests = metadata["requests"]
    if any(request.get("usage_valid") is not True for request in requests):
        raise HarborResultError("API metadata contains a request without valid usage")
    return roles


def _declared_request_roles(metadata: Mapping[str, Any]) -> tuple[str, ...]:
    if set(metadata) != {"schema_version", "requests"} or metadata.get("schema_version") != 1:
        raise HarborResultError("API metadata differs from schema v1")
    requests = metadata.get("requests")
    if not isinstance(requests, list) or not requests:
        raise HarborResultError("API metadata has no verified requests")
    roles: list[str] = []
    for request in requests:
        if (
            not isinstance(request, dict)
            or request.get("role") not in {"main", "guardian"}
            or request.get("role_provenance") != "declared"
            or request.get("declared_role") != request.get("role")
            or request.get("inferred_role") != request.get("role")
            or request.get("contract_match") is not True
        ):
            raise HarborResultError("API metadata contains an unverified request")
        roles.append(request["role"])
    return tuple(roles)


def _infra_result_without_harbor_tree() -> ParsedHarborResult:
    return ParsedHarborResult(
        outcome=RunOutcome.INFRA_FAILED,
        task_outcome="fail",
        reward=0.0,
        duration_seconds=0.0,
        input_tokens=0,
        cached_tokens=0,
        output_tokens=0,
        job_result={},
        trial_result={},
    )


def _trial_duration(trial: Mapping[str, Any], *, outcome: RunOutcome) -> float:
    started_raw = trial.get("started_at")
    finished_raw = trial.get("finished_at")
    if started_raw is None and finished_raw is None and outcome is not RunOutcome.COMPLETED:
        return 0.0
    if started_raw is None or finished_raw is None:
        raise HarborResultError("Harbor trial timestamps are incomplete")
    started = _timestamp(started_raw, "trial started_at")
    finished = _timestamp(finished_raw, "trial finished_at")
    duration = (finished - started).total_seconds()
    if not math.isfinite(duration) or duration < 0:
        raise HarborResultError("Harbor trial duration is invalid")
    return duration


def _run_spend(snapshot: Mapping[str, object], run_id: str) -> float:
    runs = snapshot.get("runs")
    run = runs.get(run_id) if isinstance(runs, dict) else None
    value = run.get("spent_usd") if isinstance(run, dict) else None
    cap_value = run.get("cap_usd") if isinstance(run, dict) else None
    try:
        amount = Decimal(value)
        cap = Decimal(cap_value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HarborResultError("budget snapshot lacks run spend") from exc
    if (
        not amount.is_finite()
        or not cap.is_finite()
        or cap <= 0
        or cap > Decimal("40")
        or amount < 0
        or amount > cap
    ):
        raise HarborResultError("budget snapshot run spend is invalid")
    return float(amount)


def _run_has_unsettled_reservation(snapshot: Mapping[str, object], run_id: str) -> bool:
    runs = snapshot.get("runs")
    run = runs.get(run_id) if isinstance(runs, dict) else None
    requests = run.get("requests") if isinstance(run, dict) else None
    if requests is None:
        return False
    if not isinstance(requests, dict):
        raise HarborResultError("budget snapshot run requests are invalid")
    unsettled = False
    for request in requests.values():
        if not isinstance(request, dict) or request.get("status") not in {
            "reserved",
            "settled",
        }:
            raise HarborResultError("budget snapshot request status is invalid")
        unsettled = unsettled or request["status"] == "reserved"
    return unsettled


def _cost_from_budget_spend(
    spent: float, *, has_unsettled_reservation: bool = False
) -> dict[str, float | None]:
    """Keep schema v1 while refusing to call local pricing an invoiced actual."""

    return {
        "estimated_usd": spent,
        "actual_usd": (
            0.0 if spent == 0.0 and not has_unsettled_reservation else None
        ),
    }


def _child_directories(root: Path, *, allow_regular_files: bool = False) -> list[Path]:
    result: list[Path] = []
    try:
        entries = list(os.scandir(root))
    except OSError as exc:
        raise HarborResultError("Harbor result directory is unreadable") from exc
    for entry in entries:
        if entry.is_symlink():
            raise HarborResultError("Harbor result directory contains a symlink")
        if entry.is_dir(follow_symlinks=False):
            result.append(Path(entry.path))
        elif not entry.is_file(follow_symlinks=False) or (
            not allow_regular_files and entry.name != "result.json"
        ):
            raise HarborResultError("Harbor result directory contains an unexpected file")
    return sorted(result)


def _regular_directory(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
        mode = path.lstat().st_mode
    except OSError as exc:
        raise HarborResultError("Harbor result directory is unavailable") from exc
    if resolved != path or not stat.S_ISDIR(mode):
        raise HarborResultError("Harbor result directory is unsafe")
    return path


def _optional_result_directory(path: Path, *, allow_missing: bool) -> Path | None:
    try:
        path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return None
        raise HarborResultError("Harbor result directory is unavailable")
    except OSError as exc:
        raise HarborResultError("Harbor result directory is unavailable") from exc
    return _regular_directory(path)


def _path_present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise HarborResultError("artifact input path is unavailable") from exc
    return True


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.stat().st_size > _MAX_RESULT_BYTES:
            raise HarborResultError("Harbor JSON result is unsafe")
        value = json.loads(path.read_text(encoding="utf-8"))
    except HarborResultError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarborResultError("Harbor JSON result is unreadable") from exc
    if not isinstance(value, dict):
        raise HarborResultError("Harbor JSON result must be an object")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise HarborResultError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HarborResultError(f"{label} is invalid") from exc
    if parsed.utcoffset() is None:
        raise HarborResultError(f"{label} lacks a UTC offset")
    return parsed


def _uint(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarborResultError(f"Harbor {label} is invalid")
    return value


def _optional_uint(value: object, label: str) -> int:
    return 0 if value is None else _uint(value, label)


def _is_commit(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _exception_type(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise HarborResultError("Harbor trial exception info is invalid")
    exception_type = value.get("exception_type", value.get("type"))
    if (
        not isinstance(exception_type, str)
        or not exception_type
        or len(exception_type) > 128
        or not exception_type.replace("_", "").isalnum()
    ):
        raise HarborResultError("Harbor trial exception type is invalid")
    return exception_type


def _git(root: Path, *args: str) -> str:
    result = _git_result(root, *args)
    if result.returncode != 0:
        raise HarborResultError("Git measurement state is unavailable")
    return result.stdout.strip()


def _git_result(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ("git", "-C", str(root), *args),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="strict",
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        raise HarborResultError("Git measurement state is unavailable") from exc
