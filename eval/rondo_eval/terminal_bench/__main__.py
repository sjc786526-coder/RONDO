"""Command entrypoint for one budgeted, supervised Terminal-Bench side."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ..api_budget_proxy import BudgetStopped, PersistentBudgetLedger
from ..artifacts import ArtifactError, ArtifactWriter, validate_run_id
from ..config import (
    ConfigError,
    RepoPaths,
    RuntimeConfig,
    load_provider_secret,
    load_runtime_config,
)
from ..contracts import BinaryManifest, ProviderProjection, RunOutcome, Side
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
from .metrics import RunnerMetricsTimer
from .pair import (
    PairIdentity,
    PairIdentityError,
    PairSequenceLedger,
    load_pair_identity,
    publication_context,
    validate_harbor_installation,
)
from .results import (
    classify_terminal_bench_result,
    parse_single_task_result,
    publish_terminal_bench_failure,
    publish_terminal_bench_result,
    validate_eval_harness_checkout,
    validate_measurement_checkout,
    validate_results_worktree,
)
from .runner import HARBOR_EXECUTABLE, TerminalBenchRequest, TerminalBenchRunError


P1_BATCH_ID = "p1-fix-git-b4-m1-v2"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rondo_eval.terminal_bench")
    parser.add_argument("--side", required=True, choices=[side.value for side in Side])
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--binary-manifest", required=True, type=Path)
    parser.add_argument("--docker-host-volume", required=True, type=Path)
    parser.add_argument("--results-worktree-root", required=True, type=Path)
    parser.add_argument("--measurement-worktree-root", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        side = Side(args.side)
        validate_run_id(args.run_id, track="tb", side=side.value)
        paths = RepoPaths.discover(Path.cwd())
        measurement_paths = RepoPaths.discover(
            args.measurement_worktree_root or paths.worktree_root
        )
        if measurement_paths.common_root != paths.common_root:
            raise ConfigError("measurement worktree belongs to another repository")
        pair_identity = load_pair_identity()
        paid_mode = pair_identity.mode("paid")
        slot = pair_identity.slot_for(side)
        if args.batch_id != paid_mode.batch_id or args.run_id != slot.paid_run_id:
            raise ConfigError("run id or batch differs from the authorized paid pair")
        results_root = validate_results_worktree(
            args.results_worktree_root,
            common_root=paths.common_root,
        )
        sequence_path = (
            paths.common_root
            / "eval-data"
            / "pairs"
            / f"{pair_identity.pair_id}-paid.json"
        )
        config, provider = _load_selected_provider(paths, pair_identity)
        if _recover_prior_paid_publication(
            paths=paths,
            sequence_path=sequence_path,
            identity=pair_identity,
            run_id=args.run_id,
            results_root=results_root,
            provider=provider,
        ):
            print(
                json.dumps(
                    {
                        "schema_version": 1,
                        "run_id": args.run_id,
                        "side": args.side,
                        "outcome": RunOutcome.COMPLETED.value,
                        "status": "reconciled_without_reexecution",
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
        eval_harness_commit = validate_eval_harness_checkout(common_root=paths.common_root)
        manifest = _load_manifest(args.binary_manifest, paths.common_root)
        seccomp_profile = pair_identity.validate_runtime_seccomp(
            project_root=paths.worktree_root
        )
        pair_identity.validate_manifest(
            common_root=paths.common_root,
            side=side,
            manifest_path=args.binary_manifest,
            manifest=manifest,
        )
        validate_harbor_installation(pair_identity, executable=HARBOR_EXECUTABLE)
        git_commit = validate_measurement_checkout(
            measurement_paths,
            side=side,
            manifest=manifest,
        )
        _secret_name, api_key = load_provider_secret(config)
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
            seccomp_profile_path=str(seccomp_profile),
            seccomp_profile_source_sha256=pair_identity.no_api_seccomp.source_sha256,
            seccomp_profile_effective_sha256=pair_identity.no_api_seccomp.effective_sha256,
            require_container_metrics=True,
        )
        proof = lease_from_watchdog()
        counter = DockerCliCounter(
            host_data_root=args.docker_host_volume,
            desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        )
        ledger_path = paths.common_root / "eval-data" / "budgets" / f"{args.batch_id}.json"
        metadata_path = work_root / "api-metadata.json"
        writer: ArtifactWriter | None = None
        metrics_timer = RunnerMetricsTimer()
        claimed = False
        sequence = PairSequenceLedger(
            sequence_path,
            identity=pair_identity,
            mode="paid",
        )
        sequence.__enter__()
        sequence_active = False
        publication_staged = False
        try:
            sequence.claim(
                side=side,
                run_id=args.run_id,
                eval_harness_commit=eval_harness_commit,
                provider=provider,
            )
            sequence_active = True
            writer = ArtifactWriter(
                paths,
                results_worktree_root=results_root,
                run_id=args.run_id,
            ).start()
            with PersistentBudgetLedger(ledger_path, batch_id=args.batch_id) as ledger:
                try:
                    ledger.claim_run(args.run_id)
                    claimed = True
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
                            pair_identity=pair_identity,
                        )
                    )
                    parsed = parse_single_task_result(
                        result.harbor.jobs_dir,
                        host_returncode=result.harbor.returncode,
                    )
                    parsed = classify_terminal_bench_result(result, parsed)
                    if validate_measurement_checkout(
                        measurement_paths,
                        side=side,
                        manifest=manifest,
                    ) != git_commit:
                        raise TerminalBenchRunError("measurement commit changed during the run")
                    if (
                        validate_eval_harness_checkout(common_root=paths.common_root)
                        != eval_harness_commit
                    ):
                        raise TerminalBenchRunError("eval harness commit changed during the run")
                    container_metrics = _paid_container_metrics(result.harbor.docker_evidence)
                    if parsed.outcome is RunOutcome.COMPLETED:
                        _fresh_config, fresh_provider = _load_selected_provider(
                            paths, pair_identity
                        )
                        sequence.stage_paid_publication(
                            run_id=args.run_id,
                            eval_harness_commit=eval_harness_commit,
                            container_metrics=container_metrics,
                            provider=fresh_provider,
                        )
                        publication_staged = True
                    artifact_path = publish_terminal_bench_result(
                        paths,
                        results_worktree_root=results_root,
                        run_id=args.run_id,
                        side=side,
                        git_commit=git_commit,
                        eval_harness_commit=eval_harness_commit,
                        live_result=result,
                        parsed=parsed,
                        metadata_path=metadata_path,
                        publication=publication_context(
                            pair_identity,
                            side=side,
                            metrics=metrics_timer.snapshot(
                                exit_code=_outcome_exit_code(parsed.outcome)
                            ).to_dict(),
                        ),
                        writer=writer,
                    )
                except (Exception, KeyboardInterrupt, asyncio.CancelledError) as exc:
                    if publication_staged:
                        if writer is None or writer.publication_started():
                            raise
                        publication_staged = False
                    if not claimed:
                        raise
                    snapshot = ledger.snapshot()
                    outcome, failure_stage, exit_code = _exception_failure(exc)
                    try:
                        if writer is None:
                            raise ArtifactError("artifact writer was not initialized")
                        writer.abort()
                        writer = ArtifactWriter(
                            paths,
                            results_worktree_root=results_root,
                            run_id=args.run_id,
                        ).start()
                        artifact_path = publish_terminal_bench_failure(
                            paths,
                            writer=writer,
                            run_id=args.run_id,
                            side=side,
                            git_commit=git_commit,
                            eval_harness_commit=eval_harness_commit,
                            manifest=manifest,
                            provider=provider,
                            budget_snapshot=snapshot,
                            metadata_path=metadata_path,
                            outcome=outcome,
                            failure_stage=failure_stage,
                            publication=publication_context(
                                pair_identity,
                                side=side,
                                metrics=metrics_timer.snapshot(
                                    exit_code=exit_code
                                ).to_dict(),
                            ),
                            secrets=(api_key,),
                        )
                    except Exception:
                        return EVIDENCE_ERROR
                    sequence.finish(
                        run_id=args.run_id,
                        completed=False,
                        eval_harness_commit=eval_harness_commit,
                        provider=provider,
                    )
                    sequence_active = False
                    print(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "run_id": args.run_id,
                                "side": args.side,
                                "outcome": outcome.value,
                                "failure_stage": failure_stage,
                                "artifacts": artifact_path.relative_to(
                                    paths.common_root
                                ).as_posix(),
                                "budget": snapshot,
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                    )
                    return exit_code
            if parsed.outcome is RunOutcome.COMPLETED:
                _fresh_config, fresh_provider = _load_selected_provider(
                    paths, pair_identity
                )
                sequence.reconcile_paid_publication(
                    run_id=args.run_id,
                    eval_harness_commit=eval_harness_commit,
                    index_path=results_root / "eval" / "results" / "runs.jsonl",
                    provider=fresh_provider,
                )
            else:
                sequence.finish(
                    run_id=args.run_id,
                    completed=False,
                    eval_harness_commit=eval_harness_commit,
                    provider=_load_selected_provider(paths, pair_identity)[1],
                )
            sequence_active = False
        finally:
            if writer is not None:
                writer.abort()
            if sequence_active and not publication_staged:
                try:
                    sequence.finish(
                        run_id=args.run_id,
                        completed=False,
                        eval_harness_commit=eval_harness_commit,
                        provider=provider,
                    )
                except PairIdentityError:
                    pass
            sequence.__exit__(None, None, None)
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
                    "review_id": item.review_id,
                    "guardian_source_baseline": item.guardian_source_baseline,
                    "guardian_source_commit": item.guardian_source_commit,
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
    except (ConfigError, PairIdentityError):
        return CONFIG_ERROR
    except (DockerSupervisionError, RuntimeBridgeError):
        return INFRA_ERROR
    except (ArtifactError, TerminalBenchRunError, OSError, ValueError, json.JSONDecodeError):
        return EVIDENCE_ERROR


def _outcome_exit_code(outcome: RunOutcome) -> int:
    if outcome is RunOutcome.COMPLETED:
        return 0
    if outcome is RunOutcome.INFRA_FAILED:
        return INFRA_ERROR
    return EVIDENCE_ERROR


def _recover_prior_paid_publication(
    *,
    paths: RepoPaths,
    sequence_path: Path,
    identity: PairIdentity,
    run_id: str,
    results_root: Path,
    provider: ProviderProjection,
) -> bool:
    """Converge only an already-staged publication before normal preflight."""

    with PairSequenceLedger(
        sequence_path,
        identity=identity,
        mode="paid",
    ) as sequence:
        matches = [
            item
            for item in sequence.snapshot()["runs"]
            if item["run_id"] == run_id and item["status"] == "publishing"
        ]
        if not matches:
            return False
        if len(matches) != 1:
            raise PairIdentityError("paid publishing state is ambiguous")
        bound_commit = matches[0]["eval_harness_commit"]
        ArtifactWriter(
            paths,
            run_id,
            results_worktree_root=results_root,
        ).recover_only()
        sequence.reconcile_paid_publication(
            run_id=run_id,
            eval_harness_commit=bound_commit,
            index_path=results_root / "eval" / "results" / "runs.jsonl",
            provider=provider,
        )
        return True


def _load_selected_provider(
    paths: RepoPaths,
    identity: PairIdentity,
) -> tuple[RuntimeConfig, ProviderProjection]:
    config = load_runtime_config(paths)
    provider = config.paid_provider_projection()
    identity.validate_selected_profile(provider)
    return config, provider


def _paid_container_metrics(evidence: object) -> dict[str, object]:
    metrics = getattr(evidence, "container_metrics", None)
    if metrics is None:
        raise TerminalBenchRunError("paid run lacks supervised container metrics")
    try:
        metrics.validate()
        return {
            "container_id": metrics.container_id,
            "cpu_usage_seconds": metrics.cpu_usage_seconds,
            "peak_memory_bytes": metrics.peak_memory_bytes,
        }
    except (AttributeError, DockerSupervisionError) as exc:
        raise TerminalBenchRunError("paid container metrics are invalid") from exc


def _exception_failure(exc: BaseException) -> tuple[RunOutcome, str, int]:
    if isinstance(exc, (KeyboardInterrupt, asyncio.CancelledError)):
        return RunOutcome.CANCELLED, "interrupted", 130
    if isinstance(exc, BudgetStopped):
        return RunOutcome.BUDGET_STOPPED, "budget", BUDGET_STOPPED
    if isinstance(exc, DockerSupervisionError):
        return RunOutcome.INFRA_FAILED, "docker", INFRA_ERROR
    if isinstance(exc, RuntimeBridgeError):
        return RunOutcome.INFRA_FAILED, "runtime", INFRA_ERROR
    if isinstance(exc, ArtifactError):
        return RunOutcome.INFRA_FAILED, "publication", EVIDENCE_ERROR
    if isinstance(exc, ConfigError):
        return RunOutcome.INFRA_FAILED, "result", CONFIG_ERROR
    return RunOutcome.INFRA_FAILED, "result", EVIDENCE_ERROR


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
        "code_mode_host_path",
        "code_mode_host_sha256",
        "bwrap_path",
        "bwrap_sha256",
        "source_commit",
        "source_dirty",
        "rust_toolchain",
        "build_command",
        "code_mode_host_build_command",
        "bwrap_asset_url",
        "bwrap_archive_sha256",
        "bwrap_source_tree_sha256",
        "workspace_lock_normalization",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise TerminalBenchRunError("binary manifest schema differs from v1")
    build_command = value["build_command"]
    code_mode_host_build_command = value["code_mode_host_build_command"]
    if any(
        not isinstance(command, list)
        or not command
        or not all(isinstance(item, str) and item for item in command)
        for command in (
            build_command,
            code_mode_host_build_command,
        )
    ):
        raise TerminalBenchRunError("binary manifest build commands are invalid")
    manifest = BinaryManifest(
        path=value["path"],
        sha256=value["sha256"],
        code_mode_host_path=value["code_mode_host_path"],
        code_mode_host_sha256=value["code_mode_host_sha256"],
        bwrap_path=value["bwrap_path"],
        bwrap_sha256=value["bwrap_sha256"],
        bwrap_asset_url=value["bwrap_asset_url"],
        bwrap_archive_sha256=value["bwrap_archive_sha256"],
        bwrap_source_tree_sha256=value["bwrap_source_tree_sha256"],
        source_commit=value["source_commit"],
        source_dirty=value["source_dirty"],
        rust_toolchain=value["rust_toolchain"],
        build_command=tuple(build_command),
        code_mode_host_build_command=tuple(code_mode_host_build_command),
        workspace_lock_normalization=value["workspace_lock_normalization"],
    )
    manifest.validate()
    declared_paths = tuple(
        Path(binary_path)
        for binary_path in (
            manifest.path,
            manifest.code_mode_host_path,
            manifest.bwrap_path,
        )
    )
    try:
        binary_paths = tuple(path.resolve(strict=True) for path in declared_paths)
    except OSError as exc:
        raise TerminalBenchRunError("binary manifest bundle is unavailable") from exc
    bundle_root = resolved.parent
    expected_paths = (
        bundle_root / "codex",
        bundle_root / "codex-code-mode-host",
        bundle_root / "codex-resources" / "bwrap",
    )
    if (
        manifest.source_dirty
        or any(not path.is_absolute() or path.is_symlink() for path in declared_paths)
        or binary_paths != expected_paths
        or not bundle_root.is_relative_to(expected_root)
    ):
        raise TerminalBenchRunError("binary manifest does not describe a clean eval-data binary")
    return manifest


if __name__ == "__main__":
    sys.exit(main())
