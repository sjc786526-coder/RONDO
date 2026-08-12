"""Execute the one frozen P2 B7 canary-baseline campaign."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from ..api_budget_proxy import PersistentBudgetLedger
from ..artifacts import ArtifactWriter
from ..config import RepoPaths, load_provider_secret, load_runtime_config
from ..contracts import BinaryManifest, RunOutcome, Side
from ..docker_supervisor import DockerOperation, DockerTaskIdentity
from ..model_cli_diagnostic import run_campaign as run_model_cli_campaign
from ..runtime_bridge import (
    DockerCliCounter,
    PowerShellDockerDesktopHostProbe,
    SubprocessCommandExecutor,
    lease_from_watchdog,
)
from .__main__ import _exception_failure, _load_manifest, _outcome_exit_code
from .baseline import (
    CAMPAIGN_CAP_USD,
    CAMPAIGN_MAX_RUNS,
    RUN_CAP_USD,
    SOL_MAX_LEGAL_REQUEST_RESERVATION_USD,
    BaselineRun,
    BaselineAssessment,
    BaselineStatus,
    CampaignIdentity,
    CampaignSlotPlan,
    CampaignSlotStatus,
    CampaignStateLedger,
    ConditionalRun,
    assess_baseline,
    load_campaign_identity,
)
from .live import run_budgeted_terminal_bench
from .materialize import validate_frozen_task_source
from .metrics import RunnerMetricsTimer
from .pair import (
    CampaignPublicationContext,
    load_historical_pair_identity,
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
from .runner import HARBOR_EXECUTABLE, TerminalBenchRequest
from .runner import DockerSupervisedHostHarborExecutor
from .materialize import PinnedTaskMaterializer
from .scoring import (
    GuardianDecision,
    GuardianOutcome,
    TaskOutcome,
    TaskScoreInput,
    aggregate_scores,
    score_task,
)


_WINDOWS_C_FLOOR_BYTES = 80 * 1024**3
_DOCKER_WARN_GROWTH_BYTES = 40 * 1024**3
_DOCKER_STOP_GROWTH_BYTES = 60 * 1024**3


class CampaignExecutionError(RuntimeError):
    """Raised when the frozen B7 campaign cannot progress safely."""


@dataclass(frozen=True)
class ExecutedSlot:
    slot: CampaignSlotPlan
    outcome: RunOutcome
    task_outcome: TaskOutcome
    estimated_usd: Decimal


@dataclass(frozen=True)
class StorageBaseline:
    docker_total_bytes: int
    docker_desktop_vhdx_bytes: int
    windows_free_bytes: int


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rondo_eval.terminal_bench.baseline_cli")
    parser.add_argument("--docker-host-volume", required=True, type=Path)
    parser.add_argument("--results-worktree-root", required=True, type=Path)
    parser.add_argument("--rondo-measurement-worktree-root", required=True, type=Path)
    parser.add_argument("--codex-measurement-worktree-root", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = RepoPaths.discover(Path.cwd())
    identity = load_campaign_identity(paths)
    config = load_runtime_config(paths)
    provider = config.paid_provider_projection()
    identity.validate_provider(provider)
    source_checkout = (
        paths.common_root / "eval-data/sources/terminal-bench-2-1-ffccbe05"
    )
    for task in identity.catalog.tasks:
        validate_frozen_task_source(source_checkout, task)
    eval_harness_commit = validate_eval_harness_checkout(common_root=paths.common_root)
    results_root = validate_results_worktree(
        args.results_worktree_root,
        common_root=paths.common_root,
    )
    manifests = _load_and_validate_manifests(paths, identity)
    measurement_roots = {
        Side.RONDO: RepoPaths.discover(args.rondo_measurement_worktree_root),
        Side.CODEX: RepoPaths.discover(args.codex_measurement_worktree_root),
    }
    measurement_commits = {
        side: validate_measurement_checkout(
            measurement_roots[side], side=side, manifest=manifests[side]
        )
        for side in Side
    }
    validate_harbor_installation(
        load_historical_pair_identity(), executable=HARBOR_EXECUTABLE
    )
    seccomp_profile = identity.validate_runtime_seccomp(
        project_root=paths.worktree_root
    )
    proof = lease_from_watchdog()
    counter = DockerCliCounter(
        host_data_root=args.docker_host_volume,
        desktop_host_probe=PowerShellDockerDesktopHostProbe(),
    )
    storage_baseline = _sample_storage(counter, identity.slots[0].run_id)
    _validate_daemon_images(identity)
    campaign_root = (
        paths.common_root / "eval-data" / "campaigns" / identity.campaign_id
    )
    state_path = campaign_root / "state.json"
    budget_path = (
        paths.common_root / "eval-data" / "budgets" / f"{identity.batch_id}.json"
    )
    campaign_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _run_oracle_preflight(
        paths=paths,
        identity=identity,
        campaign_root=campaign_root,
        counter=counter,
        proof=proof,
        seccomp_profile=seccomp_profile,
        provider_api_key_env=provider.api_key_env,
    )
    with CampaignStateLedger(state_path, identity=identity) as state:
        if state.snapshot()["status"] != "running":
            raise CampaignExecutionError("campaign is already terminal")
        try:
            canary_cost = _execute_wire_canary(paths, identity, campaign_root, state)
        except CampaignExecutionError as exc:
            _skip_planned(state, identity, reason="wire_canary_failed")
            state.finalize(BaselineStatus.BLOCKED, reason=str(exc))
            return 3
        prior_cost = Decimal(identity.budget["prior_estimated_usd"])
        remaining_cap = CAMPAIGN_CAP_USD - prior_cost - canary_cost
        if remaining_cap < SOL_MAX_LEGAL_REQUEST_RESERVATION_USD:
            state.finalize(BaselineStatus.BLOCKED, reason="budget_after_wire_canary")
            return 3
        _secret_name, api_key = load_provider_secret(config)
        with PersistentBudgetLedger(
            budget_path,
            batch_id=identity.batch_id,
            total_cap_usd=remaining_cap,
            max_runs=CAMPAIGN_MAX_RUNS - 1,
            default_run_cap_usd=RUN_CAP_USD,
        ) as budget:
            try:
                base_runs = _execute_base_rounds(
                    paths=paths,
                    identity=identity,
                    state=state,
                    budget=budget,
                    config=config,
                    provider_key=api_key,
                    counter=counter,
                    proof=proof,
                    storage_baseline=storage_baseline,
                    results_root=results_root,
                    manifests=manifests,
                    measurement_roots=measurement_roots,
                    measurement_commits=measurement_commits,
                    eval_harness_commit=eval_harness_commit,
                    seccomp_profile=seccomp_profile,
                )
                _require_resolved_base_rounds(identity, base_runs)
                conditional_runs = _execute_conditionals(
                    paths=paths,
                    identity=identity,
                    state=state,
                    budget=budget,
                    config=config,
                    provider_key=api_key,
                    counter=counter,
                    proof=proof,
                    storage_baseline=storage_baseline,
                    results_root=results_root,
                    manifests=manifests,
                    measurement_roots=measurement_roots,
                    measurement_commits=measurement_commits,
                    eval_harness_commit=eval_harness_commit,
                    seccomp_profile=seccomp_profile,
                    base_runs=base_runs,
                )
                assessment = assess_baseline(
                    tuple(task.task_id for task in identity.catalog.tasks),
                    tuple(base_runs),
                    tuple(conditional_runs),
                )
            except CampaignExecutionError as exc:
                _skip_planned(state, identity, reason="campaign_stopped")
                state.finalize(BaselineStatus.BLOCKED, reason=str(exc))
                final_storage = _optional_final_storage(
                    counter,
                    identity.slots[0].run_id,
                    baseline=storage_baseline,
                )
                _write_aggregate(
                    campaign_root,
                    identity,
                    state,
                    budget.snapshot(),
                    canary_cost,
                    assessment=None,
                    results_root=results_root,
                    storage_baseline=storage_baseline,
                    final_storage=final_storage,
                )
                return 3
            _skip_planned(state, identity, reason="not_activated")
            state.finalize(assessment.status, reason=";".join(assessment.reasons) or None)
            final_storage = _sample_storage(
                counter,
                identity.slots[0].run_id,
                baseline=storage_baseline,
            )
            _write_aggregate(
                campaign_root,
                identity,
                state,
                budget.snapshot(),
                canary_cost,
                assessment=assessment,
                results_root=results_root,
                storage_baseline=storage_baseline,
                final_storage=final_storage,
            )
            return 0 if assessment.status is BaselineStatus.PASSED else 2


def _load_and_validate_manifests(
    paths: RepoPaths, identity: CampaignIdentity
) -> dict[Side, BinaryManifest]:
    values: dict[Side, BinaryManifest] = {}
    for side in Side:
        relative = identity.bundles[side.value]["manifest_path"]
        manifest_path = paths.common_root / relative
        manifest = _load_manifest(manifest_path, paths.common_root)
        identity.validate_manifest(
            common_root=paths.common_root,
            side=side,
            manifest_path=manifest_path,
            manifest=manifest,
        )
        values[side] = manifest
    return values


def _sample_storage(
    counter: DockerCliCounter,
    run_id: str,
    *,
    baseline: StorageBaseline | None = None,
) -> StorageBaseline:
    reading = counter.sample(
        identity=DockerTaskIdentity(run_id),
        operation=DockerOperation.HOST,
    )
    reading.validate()
    if reading.docker_desktop_vhdx_bytes is None:
        raise CampaignExecutionError("Docker Desktop VHDX counter is unavailable")
    current = StorageBaseline(
        docker_total_bytes=reading.docker_total_bytes,
        docker_desktop_vhdx_bytes=reading.docker_desktop_vhdx_bytes,
        windows_free_bytes=reading.data_root_filesystem_free_bytes,
    )
    if current.windows_free_bytes < _WINDOWS_C_FLOOR_BYTES:
        raise CampaignExecutionError("Windows C: free space is below the 80 GiB floor")
    if baseline is not None:
        docker_growth = current.docker_total_bytes - baseline.docker_total_bytes
        vhd_growth = (
            current.docker_desktop_vhdx_bytes
            - baseline.docker_desktop_vhdx_bytes
        )
        growth = max(docker_growth, vhd_growth)
        if growth >= _DOCKER_STOP_GROWTH_BYTES:
            raise CampaignExecutionError("campaign Docker growth reached 60 GiB")
        if growth >= _DOCKER_WARN_GROWTH_BYTES:
            # The warning is preserved in the final aggregate; execution remains bounded.
            pass
    return current


def _optional_final_storage(
    counter: DockerCliCounter,
    run_id: str,
    *,
    baseline: StorageBaseline,
) -> StorageBaseline | None:
    """Best-effort terminal sample after the campaign is already fail-closed."""

    try:
        return _sample_storage(counter, run_id, baseline=baseline)
    except CampaignExecutionError:
        return None


def _validate_daemon_images(identity: CampaignIdentity) -> None:
    executor = SubprocessCommandExecutor(timeout_seconds=15)
    for task in identity.catalog.tasks:
        output = executor.run(
            (
                "docker",
                "image",
                "inspect",
                "--format",
                "{{json .Id}}",
                task.image_ref,
            )
        ).stdout.strip()
        try:
            image_id = json.loads(output)
        except json.JSONDecodeError as exc:
            raise CampaignExecutionError("frozen Docker image identity is invalid") from exc
        if (
            not isinstance(image_id, str)
            or not image_id.startswith("sha256:")
            or len(image_id) != 71
        ):
            raise CampaignExecutionError("frozen Docker image is not daemon-resolved")
        workdir_output = executor.run(
            (
                "docker",
                "image",
                "inspect",
                "--format",
                "{{json .Config.WorkingDir}}",
                task.image_ref,
            )
        ).stdout.strip()
        try:
            workdir = json.loads(workdir_output)
        except json.JSONDecodeError as exc:
            raise CampaignExecutionError("frozen Docker workdir is invalid") from exc
        if workdir != task.workdir:
            raise CampaignExecutionError("frozen Docker workdir differs from the catalog")


def _run_oracle_preflight(
    *,
    paths: RepoPaths,
    identity: CampaignIdentity,
    campaign_root: Path,
    counter: DockerCliCounter,
    proof: object,
    seccomp_profile: Path,
    provider_api_key_env: str,
) -> None:
    receipt_path = campaign_root / "oracle-preflight.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise CampaignExecutionError("fresh oracle preflight output already exists")
    executor = DockerSupervisedHostHarborExecutor(
        counter=counter,
        lock_guard=proof.guard,
        lease=proof.lease,
    )
    source = paths.common_root / "eval-data/sources/terminal-bench-2-1-ffccbe05"
    root = (
        paths.common_root
        / "eval-data/work"
        / f"{identity.campaign_id}-oracle-preflight"
    )
    if root.exists() or root.is_symlink():
        raise CampaignExecutionError("fresh oracle preflight work already exists")
    results: list[dict[str, object]] = []
    for index, task in enumerate(identity.catalog.tasks, start=1):
        task_root = root / f"{index:02d}-{task.slug}"
        materialized = PinnedTaskMaterializer().materialize(
            source_checkout=source,
            staging_root=task_root,
            staging_name="task",
            image_digest=task.image_digest,
            task_label=f"dev.rondo.eval.task=p2-b7-oracle-{index:02d}-{task.slug}",
            memory_bytes=task.memory_mb * 1024**2,
            memory_swap_bytes=(task.memory_mb + 1024) * 1024**2,
            pids_limit=256,
            provider_api_key_env=provider_api_key_env,
            frozen_task=task,
            seccomp_profile=seccomp_profile,
            seccomp_profile_source_sha256=identity.no_api_seccomp["source_sha256"],
            seccomp_profile_effective_sha256=identity.no_api_seccomp["effective_sha256"],
        )
        harbor = asyncio.run(
            executor.run_oracle(materialized, timeout_seconds=task.timeout_seconds)
        )
        parsed = parse_single_task_result(
            harbor.jobs_dir,
            host_returncode=harbor.returncode,
            expected_task_id=task.task_id,
        )
        if (
            parsed.outcome is not RunOutcome.COMPLETED
            or parsed.task_outcome != "pass"
            or parsed.reward != 1.0
            or harbor.docker_evidence is None
        ):
            raise CampaignExecutionError(
                f"no-API oracle preflight failed for {task.task_id}"
            )
        results.append(
            {
                "task_id": task.task_id,
                "image_ref": task.image_ref,
                "source_digest": task.source_digest,
                "reward": parsed.reward,
                "docker_samples": len(harbor.docker_evidence.samples),
            }
        )
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "campaign_id": identity.campaign_id,
                "campaign_lock_sha256": identity.lock_sha256,
                "tasks": results,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    receipt_path.chmod(0o600)


def _execute_wire_canary(
    paths: RepoPaths,
    identity: CampaignIdentity,
    campaign_root: Path,
    state: CampaignStateLedger,
) -> Decimal:
    row = state.snapshot()["slots"][0]
    if row["status"] == CampaignSlotStatus.COMPLETED.value:
        return Decimal(row["estimated_usd"])
    if row["status"] != CampaignSlotStatus.PLANNED.value:
        raise CampaignExecutionError("wire canary is not safely resumable")
    state.claim("wire-canary")
    output_root = campaign_root / "wire-canary"
    receipt = run_model_cli_campaign(
        paths,
        output_root=output_root,
        main_model_alias="sol",
        guardian_model_alias="sol",
        max_retries=0,
        plan014_canary=True,
        p2_campaign_identity=identity,
    )
    spent = Decimal(str(receipt["estimated_spent_usd"]))
    receipt_path = output_root / "receipt.json"
    digest = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    completed = receipt.get("status") == "completed"
    state.finish(
        "wire-canary",
        status=(
            CampaignSlotStatus.COMPLETED
            if completed
            else CampaignSlotStatus.FAILED
        ),
        outcome=str(receipt.get("status")),
        estimated_usd=f"{spent:.6f}",
        artifact_path=receipt_path.relative_to(paths.common_root).as_posix(),
        result_record_sha256=digest,
        reason=None if completed else str(receipt.get("stopped_phase")),
    )
    if not completed:
        raise CampaignExecutionError("fresh exact-wire canary failed")
    return spent


def _execute_base_rounds(**kwargs: object) -> list[BaselineRun]:
    identity: CampaignIdentity = kwargs["identity"]
    state: CampaignStateLedger = kwargs["state"]
    values: list[BaselineRun] = []
    for round_id in ("aa-rondo-1", "aa-rondo-2", "ab-rondo-1", "ab-codex-1"):
        side = Side.CODEX if round_id == "ab-codex-1" else Side.RONDO
        first: list[ExecutedSlot] = []
        for task in identity.catalog.tasks:
            slot = identity.slot(f"base:{round_id}:{task.task_id}:a1")
            first.append(_execute_task_slot(slot=slot, task=task, **kwargs))
        infra = [item for item in first if item.task_outcome is TaskOutcome.INFRA]
        replace_ids = (
            {task.task_id for task in identity.catalog.tasks}
            if len(infra) > 2
            else {item.slot.task_id for item in infra}
        )
        effective: dict[str, ExecutedSlot] = {
            item.slot.task_id: item for item in first
        }
        for task in identity.catalog.tasks:
            slot = identity.slot(f"base:{round_id}:{task.task_id}:a2")
            if task.task_id in replace_ids:
                effective[task.task_id] = _execute_task_slot(
                    slot=slot, task=task, **kwargs
                )
            else:
                state.skip(slot.slot_id, reason="base_replacement_not_activated")
        for task in identity.catalog.tasks:
            item = effective[task.task_id]
            values.append(
                BaselineRun(
                    task.task_id,
                    round_id,
                    side,
                    item.slot.attempt,
                    item.task_outcome,
                    item.slot.run_id,
                )
            )
        # assess_baseline needs both attempts, not just the selected values.
        values.extend(
            BaselineRun(
                item.slot.task_id,
                round_id,
                side,
                1,
                item.task_outcome,
                item.slot.run_id,
            )
            for item in first
            if item.slot.task_id in replace_ids
        )
    return values


def _require_resolved_base_rounds(
    identity: CampaignIdentity,
    runs: list[BaselineRun],
) -> None:
    """Stop before conditionals when the single frozen infra replacement failed."""

    for round_id in ("aa-rondo-1", "aa-rondo-2", "ab-rondo-1", "ab-codex-1"):
        expected_side = Side.CODEX if round_id == "ab-codex-1" else Side.RONDO
        for task in identity.catalog.tasks:
            candidates = [
                run
                for run in runs
                if run.round_id == round_id and run.task_id == task.task_id
            ]
            if not candidates:
                raise CampaignExecutionError("base round result is incomplete")
            selected = max(candidates, key=lambda run: run.attempt)
            if selected.side is not expected_side:
                raise CampaignExecutionError("base round side is invalid")
            if selected.outcome is TaskOutcome.INFRA:
                raise CampaignExecutionError("base infra replacement was exhausted")


def _execute_conditionals(*, base_runs: list[BaselineRun], **kwargs: object) -> list[ConditionalRun]:
    identity: CampaignIdentity = kwargs["identity"]
    state: CampaignStateLedger = kwargs["state"]
    tasks = tuple(task.task_id for task in identity.catalog.tasks)
    by_round: dict[str, dict[str, TaskOutcome]] = {}
    for round_id in ("aa-rondo-1", "aa-rondo-2", "ab-rondo-1", "ab-codex-1"):
        candidates = [item for item in base_runs if item.round_id == round_id]
        by_round[round_id] = {
            task_id: sorted(
                (item for item in candidates if item.task_id == task_id),
                key=lambda item: item.attempt,
            )[-1].outcome
            for task_id in tasks
        }
    triggers = {
        task_id
        for task_id in tasks
        if by_round["ab-rondo-1"][task_id] is TaskOutcome.FAIL
        and by_round["ab-codex-1"][task_id] is TaskOutcome.PASS
    }
    values: list[ConditionalRun] = []
    for task in identity.catalog.tasks:
        for side in (Side.RONDO, Side.CODEX):
            for repeat in (1, 2):
                first = identity.slot(
                    f"conditional:{task.task_id}:{side.value}:repeat{repeat}:a1"
                )
                second = identity.slot(
                    f"conditional:{task.task_id}:{side.value}:repeat{repeat}:a2"
                )
                if task.task_id not in triggers:
                    state.skip(first.slot_id, reason="conditional_not_activated")
                    state.skip(second.slot_id, reason="conditional_not_activated")
                    continue
                executed = _execute_task_slot(slot=first, task=task, **kwargs)
                values.append(
                    ConditionalRun(
                        task.task_id,
                        side,
                        repeat,
                        1,
                        executed.task_outcome,
                        first.run_id,
                    )
                )
                if executed.task_outcome is TaskOutcome.INFRA:
                    replacement = _execute_task_slot(slot=second, task=task, **kwargs)
                    values.append(
                        ConditionalRun(
                            task.task_id,
                            side,
                            repeat,
                            2,
                            replacement.task_outcome,
                            second.run_id,
                        )
                    )
                else:
                    state.skip(second.slot_id, reason="conditional_replacement_not_activated")
    return values


def _execute_task_slot(
    *,
    slot: CampaignSlotPlan,
    task: object,
    paths: RepoPaths,
    identity: CampaignIdentity,
    state: CampaignStateLedger,
    budget: PersistentBudgetLedger,
    config: object,
    provider_key: str,
    counter: DockerCliCounter,
    proof: object,
    storage_baseline: StorageBaseline,
    results_root: Path,
    manifests: dict[Side, BinaryManifest],
    measurement_roots: dict[Side, RepoPaths],
    measurement_commits: dict[Side, str],
    eval_harness_commit: str,
    seccomp_profile: Path,
) -> ExecutedSlot:
    from .tasksets import FrozenTask

    if not isinstance(task, FrozenTask):
        raise CampaignExecutionError("campaign task projection is invalid")
    snapshot = budget.snapshot()
    if Decimal(snapshot["remaining_uncommitted_usd"]) < SOL_MAX_LEGAL_REQUEST_RESERVATION_USD:
        raise CampaignExecutionError("remaining campaign budget cannot fit the next request")
    _sample_storage(counter, slot.run_id, baseline=storage_baseline)
    identity.validate_provider(config.paid_provider_projection())
    if validate_eval_harness_checkout(common_root=paths.common_root) != eval_harness_commit:
        raise CampaignExecutionError("eval harness drifted during the campaign")
    if (
        validate_measurement_checkout(
            measurement_roots[slot.side],
            side=slot.side,
            manifest=manifests[slot.side],
        )
        != measurement_commits[slot.side]
    ):
        raise CampaignExecutionError("measurement checkout drifted during the campaign")
    state.claim(slot.slot_id)
    budget.claim_run(slot.run_id)
    work_root = paths.common_root / "eval-data" / "work" / slot.run_id
    if work_root.exists() or work_root.is_symlink():
        raise CampaignExecutionError("campaign work directory is already present")
    metadata_path = work_root / "api-metadata.json"
    request = TerminalBenchRequest(
        side=slot.side,
        batch_id=identity.batch_id,
        binary=manifests[slot.side],
        image_digest=task.image_digest,
        source_checkout=str(
            paths.common_root
            / "eval-data/sources/terminal-bench-2-1-ffccbe05"
        ),
        staging_root=str(work_root / "staging"),
        docker_task_id=slot.run_id,
        memory_bytes=task.memory_mb * 1024**2,
        memory_swap_bytes=(task.memory_mb + 1024) * 1024**2,
        pids_limit=256,
        provider_transport_base_url=None,
        timeout_seconds=task.timeout_seconds,
        max_retries=0,
        budget_usd=float(RUN_CAP_USD),
        seccomp_profile_path=str(seccomp_profile),
        seccomp_profile_source_sha256=identity.no_api_seccomp["source_sha256"],
        seccomp_profile_effective_sha256=identity.no_api_seccomp["effective_sha256"],
        require_container_metrics=True,
        frozen_task=task,
    )
    writer = ArtifactWriter(
        paths,
        slot.run_id,
        results_worktree_root=results_root,
    ).start()
    timer = RunnerMetricsTimer()
    publication = lambda exit_code: CampaignPublicationContext(
        campaign_id=identity.campaign_id,
        campaign_lock_sha256=identity.lock_sha256,
        campaign_slot_id=slot.slot_id,
        campaign_round_id=slot.round_id or slot.kind,
        campaign_attempt=slot.attempt,
        taskset_sha256=identity.taskset_sha256,
        canary_catalog_sha256=identity.canary_catalog_sha256,
        side=slot.side,
        metrics=timer.snapshot(exit_code=exit_code).to_dict(),
        selected_profile=identity.selected_profile,
    )
    try:
        live = asyncio.run(
            run_budgeted_terminal_bench(
                config,
                request,
                api_key=provider_key,
                ledger=budget,
                metadata_path=metadata_path,
                counter=counter,
                lock_guard=proof.guard,
                lease=proof.lease,
                campaign_identity=identity,
                campaign_slot=slot,
                campaign_task=task,
                campaign_seccomp_profile=seccomp_profile,
            )
        )
        parsed = parse_single_task_result(
            live.harbor.jobs_dir,
            host_returncode=live.harbor.returncode,
            expected_task_id=task.task_id,
        )
        parsed = classify_terminal_bench_result(live, parsed)
        artifact = publish_terminal_bench_result(
            paths,
            results_worktree_root=results_root,
            run_id=slot.run_id,
            side=slot.side,
            git_commit=measurement_commits[slot.side],
            eval_harness_commit=eval_harness_commit,
            live_result=live,
            parsed=parsed,
            metadata_path=metadata_path,
            publication=publication(_outcome_exit_code(parsed.outcome)),
            writer=writer,
        )
        outcome = parsed.outcome
        task_outcome = (
            TaskOutcome.INFRA
            if outcome not in {RunOutcome.COMPLETED, RunOutcome.AGENT_FAILED}
            else (TaskOutcome.PASS if parsed.task_outcome == "pass" else TaskOutcome.FAIL)
        )
        secrets = live.redaction_secrets
    except (Exception, KeyboardInterrupt, asyncio.CancelledError) as exc:
        if writer.publication_started():
            raise
        writer.abort()
        writer = ArtifactWriter(
            paths,
            slot.run_id,
            results_worktree_root=results_root,
        ).start()
        outcome, failure_stage, exit_code = _exception_failure(exc)
        artifact = publish_terminal_bench_failure(
            paths,
            writer=writer,
            run_id=slot.run_id,
            side=slot.side,
            git_commit=measurement_commits[slot.side],
            eval_harness_commit=eval_harness_commit,
            manifest=manifests[slot.side],
            provider=config.paid_provider_projection(),
            budget_snapshot=budget.snapshot(),
            metadata_path=metadata_path,
            outcome=outcome,
            failure_stage=failure_stage,
            publication=publication(exit_code),
            secrets=(provider_key,),
            task_id=task.task_id,
            task_image_digest=task.image_digest,
        )
        task_outcome = TaskOutcome.INFRA
        secrets = (provider_key,)
    del secrets
    run = budget.snapshot()["runs"][slot.run_id]
    spent = Decimal(run["spent_usd"])
    record_digest = _result_record_sha256(results_root, slot.run_id)
    state.finish(
        slot.slot_id,
        status=CampaignSlotStatus.COMPLETED,
        outcome=outcome.value,
        estimated_usd=f"{spent:.6f}",
        artifact_path=artifact.relative_to(paths.common_root).as_posix(),
        result_record_sha256=record_digest,
        reason=None,
    )
    _sample_storage(counter, slot.run_id, baseline=storage_baseline)
    return ExecutedSlot(slot, outcome, task_outcome, spent)


def _result_record_sha256(results_root: Path, run_id: str) -> str:
    rows = [
        line
        for line in (results_root / "eval/results/runs.jsonl").read_bytes().splitlines()
        if json.loads(line).get("run_id") == run_id
    ]
    if len(rows) != 1:
        raise CampaignExecutionError("published campaign result is not unique")
    return hashlib.sha256(rows[0]).hexdigest()


def _skip_planned(
    state: CampaignStateLedger, identity: CampaignIdentity, *, reason: str
) -> None:
    snapshot = state.snapshot()
    by_id = {row["slot_id"]: row for row in snapshot["slots"]}
    for slot in identity.slots:
        if by_id[slot.slot_id]["status"] == CampaignSlotStatus.PLANNED.value:
            state.skip(slot.slot_id, reason=reason)


def _write_aggregate(
    campaign_root: Path,
    identity: CampaignIdentity,
    state: CampaignStateLedger,
    budget: dict[str, object],
    canary_cost: Decimal,
    *,
    assessment: object | None,
    results_root: Path,
    storage_baseline: StorageBaseline,
    final_storage: StorageBaseline | None,
) -> None:
    prior_cost = Decimal(identity.budget["prior_estimated_usd"])
    spent = prior_cost + canary_cost + Decimal(budget["spent_usd"])
    records, record_digests = _campaign_records(results_root, identity)
    usage = _campaign_usage(campaign_root.parents[2], records)
    request_count = sum(
        len(run["requests"])
        for run in budget["runs"].values()
    )
    upstream_attempt_count = sum(
        request["attempt_count"]
        for run in budget["runs"].values()
        for request in run["requests"].values()
    )
    public_assessment = _public_assessment(assessment, records)
    value = {
        "schema_version": 1,
        "campaign_id": identity.campaign_id,
        "campaign_lock_sha256": identity.lock_sha256,
        "taskset_sha256": identity.taskset_sha256,
        "canary_catalog_sha256": identity.canary_catalog_sha256,
        "status": state.snapshot()["status"],
        "actual_usd": None,
        "estimated_usd": f"{spent:.6f}",
        "prior_estimated_usd": f"{prior_cost:.6f}",
        "wire_canary_usd": f"{canary_cost:.6f}",
        "budget": budget,
        "assessment": public_assessment,
        "request_count": request_count,
        "upstream_attempt_count": upstream_attempt_count,
        "usage": usage,
        "result_record_sha256": record_digests,
        "storage": _storage_projection(storage_baseline, final_storage),
    }
    path = campaign_root / "aggregate.json"
    temporary = path.with_name(".aggregate.json.tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)
    public = {
        key: value[key]
        for key in (
            "schema_version",
            "campaign_id",
            "campaign_lock_sha256",
            "taskset_sha256",
            "canary_catalog_sha256",
            "status",
            "actual_usd",
            "estimated_usd",
            "prior_estimated_usd",
            "wire_canary_usd",
            "assessment",
            "request_count",
            "upstream_attempt_count",
            "usage",
            "result_record_sha256",
            "storage",
        )
    }
    public["reserved_usd"] = budget["reserved_usd"]
    public["run_slots_used"] = budget["run_slots_used"]
    destination = (
        results_root
        / "eval/results/baselines"
        / f"{identity.campaign_id}.json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise CampaignExecutionError("tracked campaign aggregate already exists")
    tracked_temporary = destination.with_name(f".{destination.name}.tmp")
    tracked_temporary.write_text(
        json.dumps(public, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    tracked_temporary.replace(destination)


def _storage_projection(
    initial: StorageBaseline,
    final: StorageBaseline | None,
) -> dict[str, object]:
    initial_value = {
        "docker_total_bytes": initial.docker_total_bytes,
        "docker_desktop_vhdx_bytes": initial.docker_desktop_vhdx_bytes,
        "windows_free_bytes": initial.windows_free_bytes,
    }
    if final is None:
        return {"initial": initial_value, "final": None, "growth_bytes": None}
    final_value = {
        "docker_total_bytes": final.docker_total_bytes,
        "docker_desktop_vhdx_bytes": final.docker_desktop_vhdx_bytes,
        "windows_free_bytes": final.windows_free_bytes,
    }
    return {
        "initial": initial_value,
        "final": final_value,
        "growth_bytes": max(
            final.docker_total_bytes - initial.docker_total_bytes,
            final.docker_desktop_vhdx_bytes - initial.docker_desktop_vhdx_bytes,
        ),
    }


def _campaign_records(
    results_root: Path, identity: CampaignIdentity
) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    path = results_root / "eval/results/runs.jsonl"
    records: dict[str, dict[str, object]] = {}
    digests: dict[str, str] = {}
    for line in path.read_bytes().splitlines():
        record = json.loads(line)
        config = record.get("config") if isinstance(record, dict) else None
        if not isinstance(config, dict) or config.get("campaign_id") != identity.campaign_id:
            continue
        run_id = record.get("run_id")
        if not isinstance(run_id, str) or run_id in records:
            raise CampaignExecutionError("campaign result index is ambiguous")
        records[run_id] = record
        digests[run_id] = hashlib.sha256(line).hexdigest()
    return records, dict(sorted(digests.items()))


def _campaign_usage(
    common_root: Path, records: dict[str, dict[str, object]]
) -> dict[str, int]:
    totals = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "output_tokens": 0,
    }
    for record in records.values():
        artifact = record.get("artifacts")
        if not isinstance(artifact, str):
            raise CampaignExecutionError("campaign artifact projection is invalid")
        path = common_root / artifact / "api-metadata.json"
        if not path.exists():
            summary = record.get("summary")
            if isinstance(summary, dict) and summary.get("metadata_ready") is False:
                continue
            raise CampaignExecutionError("campaign API metadata is unavailable")
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignExecutionError("campaign API metadata is unavailable") from exc
        requests = metadata.get("requests") if isinstance(metadata, dict) else None
        if not isinstance(requests, list):
            raise CampaignExecutionError("campaign API metadata is invalid")
        for request in requests:
            usage = request.get("usage") if isinstance(request, dict) else None
            if usage is None:
                continue
            if not isinstance(usage, dict) or set(usage) != set(totals):
                raise CampaignExecutionError("campaign usage projection is invalid")
            for key in totals:
                value = usage[key]
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise CampaignExecutionError("campaign usage token count is invalid")
                totals[key] += value
    return totals


def _public_assessment(
    assessment: object | None,
    records: dict[str, dict[str, object]],
) -> dict[str, object] | None:
    if assessment is None:
        return None
    if not isinstance(assessment, BaselineAssessment):
        raise CampaignExecutionError("campaign assessment type is invalid")
    rounds: dict[str, object] = {}
    for round_id in ("aa-rondo-1", "aa-rondo-2", "ab-rondo-1", "ab-codex-1"):
        selected = tuple(
            item for item in assessment.effective_base_runs if item.round_id == round_id
        )
        scores = tuple(_score_record(records[item.run_id]) for item in selected)
        rounds[round_id] = aggregate_scores(scores, taskset="canary")
    conditionals = [
        {
            "run_id": item.run_id,
            "task_id": item.task_id,
            "side": item.side.value,
            "repeat": item.repeat,
            "score": _score_record(records[item.run_id]).outcome.value,
            "attribution": (
                _score_record(records[item.run_id]).attribution.value
                if _score_record(records[item.run_id]).attribution is not None
                else None
            ),
        }
        for item in assessment.effective_conditional_runs
    ]
    return {
        "status": assessment.status.value,
        "reasons": list(assessment.reasons),
        "sigma": assessment.sigma,
        "delta": assessment.delta,
        "conditional_tasks": list(assessment.conditional_tasks),
        "base_rounds": rounds,
        "conditional_runs": conditionals,
    }


def _score_record(record: dict[str, object]):
    tasks = record.get("tasks")
    summary = record.get("summary")
    if (
        not isinstance(tasks, list)
        or len(tasks) != 1
        or not isinstance(tasks[0], dict)
        or not isinstance(summary, dict)
    ):
        raise CampaignExecutionError("campaign result cannot be scored")
    task = tasks[0]
    raw_outcome = record.get("outcome")
    if raw_outcome in {
        RunOutcome.INFRA_FAILED.value,
        RunOutcome.BUDGET_STOPPED.value,
        RunOutcome.CANCELLED.value,
    }:
        outcome = TaskOutcome.INFRA
    else:
        outcome = TaskOutcome.PASS if task.get("outcome") == "pass" else TaskOutcome.FAIL
    evidence = summary.get("evidence", [])
    if not isinstance(evidence, list):
        raise CampaignExecutionError("campaign Guardian evidence is invalid")
    decisions: list[GuardianDecision] = []
    for item in evidence:
        if not isinstance(item, dict):
            raise CampaignExecutionError("campaign Guardian evidence is invalid")
        terminal = item.get("terminal_status")
        if terminal == "approved":
            guardian_outcome = GuardianOutcome.APPROVED
        elif terminal == "denied":
            guardian_outcome = GuardianOutcome.DENIED
        else:
            guardian_outcome = GuardianOutcome.TECHNICAL_FAILURE
        decisions.append(
            GuardianDecision(
                guardian_outcome,
                item.get("canonical_request_sha256"),
            )
        )
    return score_task(
        TaskScoreInput(task["task_id"], outcome, tuple(decisions)),
        deny_adjudications={},
    )


if __name__ == "__main__":
    raise SystemExit(main())
