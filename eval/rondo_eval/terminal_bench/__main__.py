"""Command entrypoint for one budgeted, supervised Terminal-Bench side."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ..api_budget_proxy import BudgetStopped, PersistentBudgetLedger
from ..config import ConfigError, RepoPaths, load_provider_secret, load_runtime_config
from ..contracts import BinaryManifest, RunOutcome, Side
from ..docker_supervisor import DockerSupervisionError
from ..exit_codes import BUDGET_STOPPED, CONFIG_ERROR, EVIDENCE_ERROR, INFRA_ERROR
from ..runtime_bridge import (
    DockerCliCounter,
    PowerShellDockerDesktopHostProbe,
    RuntimeBridgeError,
    lease_from_watchdog,
)
from .freeze import FIX_GIT_IMAGE_DIGEST
from .live import run_budgeted_terminal_bench
from .results import (
    parse_single_task_result,
    publish_terminal_bench_result,
    validate_measurement_checkout,
    validate_results_worktree,
)
from .runner import TerminalBenchRequest, TerminalBenchRunError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rondo_eval.terminal_bench")
    parser.add_argument("--side", required=True, choices=[side.value for side in Side])
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--binary-manifest", required=True, type=Path)
    parser.add_argument("--docker-host-volume", required=True, type=Path)
    parser.add_argument("--results-worktree-root", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = RepoPaths.discover(Path.cwd())
        config = load_runtime_config(paths)
        side = Side(args.side)
        manifest = _load_manifest(args.binary_manifest, paths.common_root)
        results_root = validate_results_worktree(
            args.results_worktree_root,
            common_root=paths.common_root,
        )
        git_commit = validate_measurement_checkout(paths, side=side, manifest=manifest)
        _secret_name, api_key = load_provider_secret(config, "openai")
        source = paths.common_root / "eval-data" / "sources" / "terminal-bench-2-1-ffccbe05"
        work_root = paths.common_root / "eval-data" / "work" / args.run_id
        if work_root.exists() or work_root.is_symlink():
            raise TerminalBenchRunError("run work directory already exists")
        request = TerminalBenchRequest(
            side=side,
            batch_id=args.batch_id,
            binary=manifest,
            image_digest=FIX_GIT_IMAGE_DIGEST,
            source_checkout=str(source),
            staging_root=str(work_root / "staging"),
            docker_task_id=args.run_id,
            memory_bytes=2 * 1024**3,
            memory_swap_bytes=3 * 1024**3,
            pids_limit=256,
            provider_transport_base_url=None,
            timeout_seconds=args.timeout_seconds,
            max_retries=0,
            budget_usd=5.0,
        )
        proof = lease_from_watchdog()
        counter = DockerCliCounter(
            host_data_root=args.docker_host_volume,
            desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        )
        ledger_path = paths.common_root / "eval-data" / "budgets" / f"{args.batch_id}.json"
        metadata_path = work_root / "api-metadata.json"
        with PersistentBudgetLedger(ledger_path, batch_id=args.batch_id) as ledger:
            result = asyncio.run(
                run_budgeted_terminal_bench(
                    config,
                    request,
                    api_key=api_key,
                    ledger=ledger,
                    metadata_path=metadata_path,
                    counter=counter,
                    lock_guard=proof.guard,
                    lease=proof.lease,
                )
            )
        parsed = parse_single_task_result(
            result.harbor.jobs_dir,
            host_returncode=result.harbor.returncode,
        )
        if validate_measurement_checkout(paths, side=side, manifest=manifest) != git_commit:
            raise TerminalBenchRunError("measurement commit changed during the run")
        artifact_path = publish_terminal_bench_result(
            paths,
            results_worktree_root=results_root,
            run_id=args.run_id,
            side=side,
            git_commit=git_commit,
            live_result=result,
            parsed=parsed,
            metadata_path=metadata_path,
        )
        safe = {
            "schema_version": 1,
            "run_id": args.run_id,
            "side": args.side,
            "outcome": parsed.outcome.value,
            "task_outcome": parsed.task_outcome,
            "reward": parsed.reward,
            "artifacts": artifact_path.relative_to(paths.common_root).as_posix(),
            "metadata_ready": result.metadata_ready,
            "evidence": [
                {
                    "relative_path": item.relative_path,
                    "policy_sha256": item.policy.sha256,
                    "request_shape": item.policy.request_shape,
                    "model": item.model,
                    "reasoning_effort": item.reasoning_effort,
                    "terminal_status": item.terminal_status,
                }
                for item in result.evidence
            ],
            "budget": result.budget_snapshot,
            "docker_samples": (
                len(result.harbor.docker_evidence.samples)
                if result.harbor.docker_evidence is not None
                else 0
            ),
            "docker_warnings": (
                list(result.harbor.docker_evidence.warnings)
                if result.harbor.docker_evidence is not None
                else []
            ),
        }
        print(json.dumps(safe, sort_keys=True, separators=(",", ":")))
        return _outcome_exit_code(parsed.outcome)
    except BudgetStopped:
        return BUDGET_STOPPED
    except ConfigError:
        return CONFIG_ERROR
    except (DockerSupervisionError, RuntimeBridgeError):
        return INFRA_ERROR
    except (TerminalBenchRunError, OSError, ValueError, json.JSONDecodeError):
        return EVIDENCE_ERROR


def _outcome_exit_code(outcome: RunOutcome) -> int:
    if outcome is RunOutcome.COMPLETED:
        return 0
    if outcome is RunOutcome.INFRA_FAILED:
        return INFRA_ERROR
    return EVIDENCE_ERROR


def _load_manifest(path: Path, common_root: Path) -> BinaryManifest:
    if path.is_symlink():
        raise TerminalBenchRunError("binary manifest must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        root = common_root.resolve(strict=True)
    except OSError as exc:
        raise TerminalBenchRunError("binary manifest is unavailable") from exc
    expected_root = root / "eval-data" / "bin"
    if not resolved.is_relative_to(expected_root):
        raise TerminalBenchRunError("binary manifest is outside eval-data/bin")
    try:
        value = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TerminalBenchRunError("binary manifest is unreadable") from exc
    expected = {
        "path",
        "sha256",
        "source_commit",
        "source_dirty",
        "rust_toolchain",
        "build_command",
        "workspace_lock_normalization",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise TerminalBenchRunError("binary manifest schema differs from v1")
    build_command = value["build_command"]
    if not isinstance(build_command, list) or not all(isinstance(item, str) for item in build_command):
        raise TerminalBenchRunError("binary manifest build command is invalid")
    manifest = BinaryManifest(
        path=value["path"],
        sha256=value["sha256"],
        source_commit=value["source_commit"],
        source_dirty=value["source_dirty"],
        rust_toolchain=value["rust_toolchain"],
        build_command=tuple(build_command),
        workspace_lock_normalization=value["workspace_lock_normalization"],
    )
    manifest.validate()
    if manifest.source_dirty or not Path(manifest.path).resolve(strict=True).is_relative_to(expected_root):
        raise TerminalBenchRunError("binary manifest does not describe a clean eval-data binary")
    return manifest


if __name__ == "__main__":
    sys.exit(main())
