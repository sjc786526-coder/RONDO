"""Strict Terminal-Bench result parsing and private artifact publication."""

from __future__ import annotations

import json
import math
import os
import stat
import subprocess
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from ..artifacts import ArtifactWriter
from ..config import RepoPaths
from ..contracts import BinaryManifest, RunOutcome, Side
from .freeze import (
    FIX_GIT_IMAGE_DIGEST,
    FIX_GIT_TASK_ID,
    TERMINAL_BENCH_COMMIT,
    TERMINAL_BENCH_VERSION,
)
from .live import BudgetedTerminalBenchResult, load_guardian_evidence_bundle


UPSTREAM_CODEX = {
    "tag": "rust-v0.147.0",
    "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
    "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
}
_MAX_RESULT_BYTES = 8 * 1024 * 1024
_MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
_SUCCESS_COUNTS = {
    "n_completed_trials": 1,
    "n_errored_trials": 0,
    "n_running_trials": 0,
    "n_pending_trials": 0,
    "n_cancelled_trials": 0,
    "n_retries": 0,
}
_CANCELLED_COUNTS = {
    "n_completed_trials": 0,
    "n_errored_trials": 0,
    "n_running_trials": 0,
    "n_pending_trials": 0,
    "n_cancelled_trials": 1,
    "n_retries": 0,
}
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
    jobs_dir: Path,
    *,
    host_returncode: int,
) -> ParsedHarborResult:
    """Parse exactly one Harbor job and trial; host rc alone is never success."""

    if isinstance(host_returncode, bool) or not isinstance(host_returncode, int):
        raise HarborResultError("Harbor host return code is invalid")
    root = _optional_jobs_directory(
        jobs_dir,
        allow_missing=host_returncode != 0,
    )
    if root is None:
        return _infra_result_without_harbor_tree()
    job_directories = _child_directories(root)
    if not job_directories and host_returncode != 0:
        return _infra_result_without_harbor_tree()
    if len(job_directories) != 1:
        raise HarborResultError("Harbor jobs directory must contain exactly one job")
    job_directory = job_directories[0]
    job = _read_json_object(job_directory / "result.json")
    trial_directories = _child_directories(job_directory, allow_regular_files=True)
    if len(trial_directories) != 1:
        raise HarborResultError("Harbor job must contain exactly one trial")
    trial = _read_json_object(trial_directories[0] / "result.json")

    stats = job.get("stats")
    if not isinstance(stats, dict):
        raise HarborResultError("Harbor job stats are missing")
    counts = {
        name: _uint(stats.get(name), name)
        for name in (
            "n_completed_trials",
            "n_errored_trials",
            "n_running_trials",
            "n_pending_trials",
            "n_cancelled_trials",
            "n_retries",
        )
    }
    if _uint(job.get("n_total_trials"), "n_total_trials") != 1:
        raise HarborResultError("Harbor job is not a one-trial run")
    exception_type = _exception_type(trial.get("exception_info"))
    if host_returncode != 0:
        outcome = RunOutcome.INFRA_FAILED
    elif counts == _SUCCESS_COUNTS and exception_type is None:
        outcome = RunOutcome.COMPLETED
    elif counts == _CANCELLED_COUNTS and exception_type == "CancelledError":
        outcome = RunOutcome.CANCELLED
    elif (
        counts["n_completed_trials"] == 0
        and counts["n_errored_trials"] == 1
        and counts["n_running_trials"] == 0
        and counts["n_pending_trials"] == 0
        and counts["n_cancelled_trials"] == 0
        and counts["n_retries"] == 0
        and exception_type in _AGENT_EXCEPTION_TYPES
    ):
        outcome = RunOutcome.AGENT_FAILED
    else:
        outcome = RunOutcome.INFRA_FAILED

    if trial.get("task_name") != FIX_GIT_TASK_ID:
        raise HarborResultError("Harbor trial task identity differs from the freeze")
    verifier = trial.get("verifier_result")
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else None
    reward = rewards.get("reward") if isinstance(rewards, dict) else None
    if reward is None and outcome is not RunOutcome.COMPLETED:
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
        job_result=job,
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
    writer: ArtifactWriter | None = None,
) -> Path:
    """Archive private raw evidence and append one strict tracked record."""

    parsed = classify_terminal_bench_result(live_result, parsed)
    if not _is_commit(eval_harness_commit):
        raise HarborResultError("eval harness commit is invalid")
    if live_result.prepared.spec.side is not side:
        raise HarborResultError("prepared side differs from publication side")
    request_roles = _validate_publication_evidence(
        live_result,
        parsed,
        metadata_path=metadata_path,
    )
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
    )
    writer.write_json("run-summary.json", summary)
    if parsed.job_result or parsed.trial_result:
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
        "metrics": None,
        "cost": {"estimated_usd": spent, "actual_usd": spent},
        "artifacts": f"eval-data/runs/{run_id}",
        "notes": "API usage priced at the frozen official Luna Standard rates; no invoice query.",
    }
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
    budget_snapshot: Mapping[str, object],
    metadata_path: Path,
    outcome: RunOutcome,
    failure_stage: str,
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
    spent = _run_spend(budget_snapshot, run_id)
    config = {
        "batch_id": budget_snapshot.get("batch_id"),
        "terminal_bench_version": TERMINAL_BENCH_VERSION,
        "terminal_bench_commit": TERMINAL_BENCH_COMMIT,
        "task_image_digest": FIX_GIT_IMAGE_DIGEST,
        "binary_source_commit": manifest.source_commit,
        "eval_harness_commit": eval_harness_commit,
        "binary_workspace_lock_normalization": manifest.workspace_lock_normalization,
        "failure_stage": failure_stage,
    }
    metadata: dict[str, Any] | None = None
    request_roles: tuple[str, ...] = ()
    try:
        candidate_metadata = _read_json_object(metadata_path)
        request_roles = _request_roles(candidate_metadata)
        metadata = candidate_metadata
    except HarborResultError:
        pass
    metadata_ready = metadata is not None
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
        "metrics": None,
        "cost": {"estimated_usd": spent, "actual_usd": spent},
        "artifacts": f"eval-data/runs/{run_id}",
        "notes": "Run exited after its paid-run claim; failure details are intentionally categorical.",
    }
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
) -> dict[str, Any]:
    spec = live_result.prepared.spec
    evidence = [
        {
            "relative_path": item.relative_path,
            "review_id": item.review_id,
            "guardian_source_baseline": item.guardian_source_baseline,
            "guardian_source_commit": item.guardian_source_commit,
            "policy_sha256": item.policy.sha256,
            "request_shape": item.policy.request_shape,
            "model": item.model,
            "reasoning_effort": item.reasoning_effort,
            "terminal_status": item.terminal_status,
        }
        for item in live_result.evidence
    ]
    return {
        "schema_version": 1,
        "run_id": run_id,
        "side": side.value,
        "git_commit": git_commit,
        "outcome": parsed.outcome.value,
        "config": {
            "main_model": spec.provider.main_model,
            "guardian_model": spec.provider.guardian_model,
            "guardian_effort": spec.provider.guardian_effort,
            "provider": spec.provider.provider_id,
            "provider_config_sha256": spec.provider.config_sha256,
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
        },
        "summary": {
            "success_rate": 1.0 if parsed.task_outcome == "pass" else 0.0,
            "tasks_total": 1,
            "infra_failed": 1 if parsed.outcome is RunOutcome.INFRA_FAILED else 0,
            "host_returncode": live_result.harbor.returncode,
            "metadata_ready": live_result.metadata_ready,
            "api_request_roles": {
                "main": request_roles.count("main"),
                "guardian": request_roles.count("guardian"),
            },
            "docker_samples": len(live_result.harbor.docker_evidence.samples)
            if live_result.harbor.docker_evidence is not None
            else 0,
            "docker_warnings": list(live_result.harbor.docker_evidence.warnings)
            if live_result.harbor.docker_evidence is not None
            else [],
            "evidence": evidence,
        },
        "tasks": [
            {
                "task_id": FIX_GIT_TASK_ID,
                "outcome": parsed.task_outcome,
                "attribution": "infra"
                if parsed.outcome is RunOutcome.INFRA_FAILED
                else "agent",
                "reward": parsed.reward,
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

    root = _regular_directory(source)
    job_directories = _child_directories(root)
    if len(job_directories) != 1:
        raise HarborResultError("Harbor evidence must contain exactly one job")
    trial_directories = _child_directories(job_directories[0], allow_regular_files=True)
    if len(trial_directories) != 1:
        raise HarborResultError("Harbor evidence must contain exactly one trial")
    trial_directory = trial_directories[0]
    stats = parsed.job_result.get("stats")
    if not isinstance(stats, dict):  # pragma: no cover - parser already guarantees this.
        raise HarborResultError("parsed Harbor job stats are unavailable")
    writer.write_json(
        "harbor/job-result.json",
        {
            "schema_version": 1,
            "n_total_trials": 1,
            "stats": {name: stats[name] for name in _SUCCESS_COUNTS},
        },
    )
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
    has_job_result = bool(parsed.job_result)
    has_trial_result = bool(parsed.trial_result)
    if has_job_result != has_trial_result:
        raise HarborResultError("parsed Harbor result is internally inconsistent")
    if not has_job_result:
        if parsed.outcome is not RunOutcome.INFRA_FAILED:
            raise HarborResultError("only infra failure may omit the Harbor result tree")
        root = _optional_jobs_directory(
            live_result.harbor.jobs_dir,
            allow_missing=True,
        )
        if root is not None and _child_directories(root):
            raise HarborResultError("an existing Harbor result tree cannot be omitted")
    if parsed.outcome is RunOutcome.COMPLETED:
        if host_returncode != 0:
            raise HarborResultError("completed result has a non-zero Harbor return code")
        if not live_result.metadata_ready:
            raise HarborResultError("completed run lacks verified API metadata")
        roles = _verified_request_roles(metadata_path)
        if "main" not in roles:
            raise HarborResultError("completed run lacks a verified main-model request")
        if live_result.prepared.spec.side is Side.RONDO:
            guardian_observed = "guardian" in roles
            evidence_observed = bool(live_result.evidence)
            if guardian_observed != evidence_observed:
                raise HarborResultError(
                    "RONDO Guardian request and E_final evidence do not agree"
                )
    elif (
        parsed.outcome is RunOutcome.INFRA_FAILED
        and host_returncode == 0
        and not has_trial_result
    ):
        raise HarborResultError("infra-failed result lacks Harbor failure evidence")
    else:
        roles = ()
    return roles


def _verified_request_roles(metadata_path: Path) -> tuple[str, ...]:
    metadata = _read_json_object(metadata_path)
    return _request_roles(metadata)


def _request_roles(metadata: Mapping[str, Any]) -> tuple[str, ...]:
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
            or request.get("contract_match") is not True
            or request.get("usage_valid") is not True
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
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HarborResultError("budget snapshot lacks run spend") from exc
    if not amount.is_finite() or amount < 0 or amount > Decimal("5"):
        raise HarborResultError("budget snapshot run spend is invalid")
    return float(amount)


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


def _optional_jobs_directory(path: Path, *, allow_missing: bool) -> Path | None:
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
