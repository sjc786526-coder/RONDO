"""Narrow local/cloud command surface for the Plan 087 adaptive search."""

from __future__ import annotations

import argparse
import json
import os
import socket
import stat
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    safe_directory,
    sha256_bytes,
    write_exclusive,
)
from .plan066_data import load_plan066_datasets
from .plan081_artifacts import Plan081ArtifactStore
from .plan081_contract import load_route_contract
from .plan082_adapter import verify_snapshot
from .plan082_controller import validate_process_identity
from .plan082_environment import (
    _publish_identical,
    observe_environment,
    publish_bootstrap_ready_receipt,
)
from .plan087_adapter import Plan087TorchTrainingAdapter, validate_adaptive_recipe
from .plan087_bundle import (
    create_data_archive,
    create_source_archive,
    extract_data_archive,
    extract_source_archive,
    prepare_data_bundle,
    verify_data_bundle,
    verify_source_archive,
)
from .plan087_capacity import assess_checkpoint_capacity
from .plan087_contract import (
    PROCESS_RECEIPT_SCHEMA,
    RECOVERY_RECEIPT_SCHEMA,
    validate_cost_progression,
    validate_cost_snapshot,
    validate_process_receipt,
)
from .plan087_controller import Plan087AdaptiveTrainingController
from .plan087_finalize import finalize_route, finalize_search, summarize_route_result
from .plan087_handoff import (
    create_small_handoff_manifest,
    stage_small_handoff,
    validate_small_handoff_manifest,
    verify_small_handoff,
)
from .plan087_run import run_scheduled, run_spec_objects, validate_run_spec
from .plan087_search import (
    materialize_run_spec,
    resolve_scope,
    validate_route_candidate,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publication-critic-plan087")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare-data")
    prepare.add_argument("--canonical-plan066", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    verify_data = commands.add_parser("verify-data")
    verify_data.add_argument("--bundle", type=Path, required=True)
    archive = commands.add_parser("create-data-archive")
    archive.add_argument("--bundle", type=Path, required=True)
    archive.add_argument("--output", type=Path, required=True)
    extract = commands.add_parser("extract-data-archive")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--expected-sha256", required=True)
    extract.add_argument("--output", type=Path, required=True)

    source = commands.add_parser("create-source-archive")
    source.add_argument("--repo", type=Path, required=True)
    source.add_argument("--commit", required=True)
    source.add_argument("--output", type=Path, required=True)
    source_verify = commands.add_parser("verify-source-archive")
    source_verify.add_argument("--archive", type=Path, required=True)
    source_verify.add_argument("--source-root", type=Path, required=True)
    source_verify.add_argument("--expected-commit", required=True)
    source_verify.add_argument("--exact-tree", action="store_true")
    source_extract = commands.add_parser("extract-source-archive")
    source_extract.add_argument("--archive", type=Path, required=True)
    source_extract.add_argument("--expected-sha256", required=True)
    source_extract.add_argument("--expected-commit", required=True)
    source_extract.add_argument("--output", type=Path, required=True)

    snapshot = commands.add_parser("verify-snapshot")
    snapshot.add_argument("--snapshot", type=Path, required=True)
    snapshot.add_argument("--model-lock", type=Path, required=True)
    environment = commands.add_parser("capture-environment")
    environment.add_argument("--output", type=Path, required=True)
    ready = commands.add_parser("publish-bootstrap-ready")
    for name in (
        "source_receipt",
        "data_receipt",
        "snapshot_receipt",
        "environment_receipt",
        "source_root",
        "data_root",
        "model_root",
        "output",
    ):
        ready.add_argument(f"--{name.replace('_', '-')}", type=Path, required=True)

    recipe = commands.add_parser("validate-recipe")
    recipe.add_argument("--recipe", type=Path, required=True)
    spec = commands.add_parser("validate-run-spec")
    spec.add_argument("--run-spec", type=Path, required=True)
    cost = commands.add_parser("validate-cost-snapshot")
    cost.add_argument("--cost-snapshot", type=Path, required=True)
    cost.add_argument("--previous-cost-snapshot", type=Path)
    capacity = commands.add_parser("capacity-preflight")
    capacity.add_argument("--input", type=Path, required=True)
    candidate = commands.add_parser("validate-route-candidate")
    candidate.add_argument("--candidate", type=Path, required=True)
    scope = commands.add_parser("resolve-scope")
    scope.add_argument("--inventory", type=Path, required=True)
    scope.add_argument("--strategy", type=Path, required=True)
    materialize = commands.add_parser("materialize-run-spec")
    materialize.add_argument("--candidate", type=Path, required=True)
    materialize.add_argument("--route-context", type=Path, required=True)
    materialize.add_argument("--inventory", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    inventory = commands.add_parser("parameter-inventory")
    inventory.add_argument("--snapshot", type=Path, required=True)
    inventory.add_argument("--model-lock", type=Path, required=True)
    inventory.add_argument("--recipe", type=Path, required=True)

    for name in ("start", "resume", "verify-recovery"):
        run = commands.add_parser(name)
        _add_run_arguments(run)
        if name in {"resume", "verify-recovery"}:
            run.add_argument("--checkpoint-id", required=True)
            run.add_argument("--source-process-receipt", type=Path, required=True)
            run.add_argument("--recovery-receipt-output", type=Path, required=True)

    route = commands.add_parser("finalize-route")
    route.add_argument("--controller-state", type=Path, required=True)
    route.add_argument("--artifact-root", type=Path, required=True)
    route.add_argument("--selected-observation-id", required=True)
    route.add_argument("--selected-checkpoint-id", required=True)
    route.add_argument(
        "--operator-disposition", choices=("promising", "not_promising"), required=True
    )
    route.add_argument(
        "--recovery-role",
        choices=("none", "necessary_recovery_point", "promising_candidate"),
        required=True,
    )
    route.add_argument("--operator-reason", required=True)
    route.add_argument("--operator-assessment", type=Path, required=True)
    route.add_argument("--cost-snapshot", type=Path, action="append", required=True)
    route.add_argument("--process-receipt", type=Path)
    route.add_argument("--recovery-receipt", type=Path)
    route.add_argument("--output", type=Path, required=True)

    summarize = commands.add_parser("summarize-route")
    summarize.add_argument("--route-result", type=Path, required=True)
    summarize.add_argument("--output", type=Path, required=True)

    search = commands.add_parser("finalize-search")
    search.add_argument("--route-result", type=Path, action="append", default=[])
    search.add_argument(
        "--outcome",
        choices=(
            "PROMISING_CANDIDATE_RETAINED",
            "BUDGET_EXHAUSTED_NO_CANDIDATE",
            "INCONCLUSIVE_INFRASTRUCTURE",
        ),
        required=True,
    )
    search.add_argument("--reason", required=True)
    search.add_argument("--selected-route-id")
    search.add_argument(
        "--terminal-cost-snapshot", type=Path, action="append", required=True
    )
    search.add_argument("--resource-state", type=Path, required=True)
    search.add_argument("--output", type=Path, required=True)

    handoff = commands.add_parser("create-handoff-manifest")
    handoff.add_argument("--task-root", type=Path, required=True)
    handoff.add_argument("--entry", action="append", required=True)
    handoff.add_argument("--output", type=Path, required=True)
    stage = commands.add_parser("stage-handoff")
    stage.add_argument("--task-root", type=Path, required=True)
    stage.add_argument("--manifest", type=Path, required=True)
    stage.add_argument("--output", type=Path, required=True)
    verify_handoff = commands.add_parser("verify-handoff")
    verify_handoff.add_argument("--root", type=Path, required=True)
    verify_handoff.add_argument("--manifest", type=Path, required=True)
    verify_handoff.add_argument("--exact-tree", action="store_true")
    return parser


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--data-bundle", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--process-receipt-output", type=Path, required=True)
    parser.add_argument("--capacity-preflight", type=Path, required=True)
    parser.add_argument("--stop-after", type=int)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _dispatch(args)
    except FullModelTrainingError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "failure_kind": type(exc).__name__,
                    "code": exc.code,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "prepare-data":
        return prepare_data_bundle(args.canonical_plan066, args.output)
    if args.command == "verify-data":
        return verify_data_bundle(args.bundle)
    if args.command == "create-data-archive":
        return create_data_archive(args.bundle, args.output)
    if args.command == "extract-data-archive":
        _require_task_owned_if_configured(args.output)
        return extract_data_archive(
            args.archive, args.output, expected_sha256=args.expected_sha256
        )
    if args.command == "create-source-archive":
        return create_source_archive(args.repo, args.output, source_commit=args.commit)
    if args.command == "verify-source-archive":
        return verify_source_archive(
            args.archive,
            args.source_root,
            exact_tree=args.exact_tree,
            expected_commit=args.expected_commit,
        )
    if args.command == "extract-source-archive":
        _require_task_owned_if_configured(args.output)
        return extract_source_archive(
            args.archive,
            args.output,
            expected_sha256=args.expected_sha256,
            expected_commit=args.expected_commit,
        )
    if args.command == "verify-snapshot":
        return verify_snapshot(args.snapshot, args.model_lock)
    if args.command == "capture-environment":
        _require_task_owned_paths(args.output)
        value = observe_environment(
            image_identity=os.getenv("RONDO_PLAN087_IMAGE_IDENTITY")
        )
        _publish_identical(args.output, pretty_json_bytes(value))
        return value
    if args.command == "publish-bootstrap-ready":
        _require_task_owned_paths(args.output)
        return publish_bootstrap_ready_receipt(
            args.output,
            source_receipt=args.source_receipt,
            data_receipt=args.data_receipt,
            snapshot_receipt=args.snapshot_receipt,
            environment_receipt=args.environment_receipt,
            source_root=args.source_root,
            data_root=args.data_root,
            model_root=args.model_root,
        )
    if args.command == "validate-recipe":
        return validate_adaptive_recipe(read_json(args.recipe))
    if args.command == "validate-run-spec":
        return validate_run_spec(read_json(args.run_spec))
    if args.command == "validate-cost-snapshot":
        current = validate_cost_snapshot(read_json(args.cost_snapshot))
        if args.previous_cost_snapshot is None:
            if (
                current["snapshot_index"] != 0
                or current["previous_snapshot_content_sha256"] is not None
            ):
                raise FullModelTrainingError("plan087_cost_progression_invalid")
            return current
        return validate_cost_progression(
            read_json(args.previous_cost_snapshot), current
        )
    if args.command == "capacity-preflight":
        return assess_checkpoint_capacity(read_json(args.input))
    if args.command == "validate-route-candidate":
        return validate_route_candidate(read_json(args.candidate))
    if args.command == "resolve-scope":
        return resolve_scope(read_json(args.inventory), read_json(args.strategy))
    if args.command == "materialize-run-spec":
        _require_task_owned_paths(args.output)
        result = materialize_run_spec(
            read_json(args.candidate),
            route_context=read_json(args.route_context),
            parameter_inventory=read_json(args.inventory),
        )
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    if args.command == "parameter-inventory":
        adapter = Plan087TorchTrainingAdapter.from_snapshot(
            snapshot_root=args.snapshot,
            model_lock_path=args.model_lock,
            recipe=read_json(args.recipe),
        )
        try:
            return adapter.parameter_inventory()
        finally:
            adapter.close()
    if args.command in {"start", "resume", "verify-recovery"}:
        return _run(
            args,
            resume=args.command != "start",
            recovery_only=args.command == "verify-recovery",
        )
    if args.command == "finalize-route":
        _require_task_owned_paths(args.artifact_root, args.output)
        result = finalize_route(
            controller_state=read_json(args.controller_state),
            artifact_root=args.artifact_root,
            selected_observation_id=args.selected_observation_id,
            selected_checkpoint_id=args.selected_checkpoint_id,
            operator_disposition=args.operator_disposition,
            recovery_role=args.recovery_role,
            operator_reason=args.operator_reason,
            operator_assessment=read_json(args.operator_assessment),
            cost_snapshots=[read_json(path) for path in args.cost_snapshot],
            process_receipt=(
                read_json(args.process_receipt)
                if args.process_receipt is not None
                else None
            ),
            recovery_receipt=(
                read_json(args.recovery_receipt)
                if args.recovery_receipt is not None
                else None
            ),
        )
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    if args.command == "finalize-search":
        _require_task_owned_paths(args.output)
        result = finalize_search(
            route_results=[read_json(path) for path in args.route_result],
            outcome=args.outcome,
            reason=args.reason,
            selected_route_id=args.selected_route_id,
            terminal_cost_snapshots=[
                read_json(path) for path in args.terminal_cost_snapshot
            ],
            resource_state=read_json(args.resource_state),
        )
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    if args.command == "summarize-route":
        _require_task_owned_paths(args.output)
        result = summarize_route_result(read_json(args.route_result))
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    if args.command == "create-handoff-manifest":
        _require_configured_task_root(args.task_root)
        _require_task_owned_paths(args.output)
        result = create_small_handoff_manifest(
            args.task_root, [_parse_handoff_entry(item) for item in args.entry]
        )
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    if args.command == "stage-handoff":
        _require_configured_task_root(args.task_root)
        _require_task_owned_paths(args.output)
        return stage_small_handoff(
            args.task_root,
            validate_small_handoff_manifest(read_json(args.manifest)),
            args.output,
        )
    if args.command == "verify-handoff":
        return verify_small_handoff(
            args.root, args.manifest, exact_tree=args.exact_tree
        )
    raise FullModelTrainingError("plan087_command_invalid")


def _run(
    args: argparse.Namespace, *, resume: bool, recovery_only: bool
) -> dict[str, Any]:
    _preflight_segment_outputs(args, resume=resume)
    capacity = assess_checkpoint_capacity(read_json(args.capacity_preflight))
    if capacity["checkpoint_write_ready"] is not True:
        raise FullModelTrainingError("plan087_checkpoint_capacity_not_ready")
    source_receipt = _verify_executing_source(
        source_archive=args.source_archive,
        source_root=args.source_root,
        receipt_path=args.source_receipt,
    )
    route = load_route_contract(args.route)
    data_receipt = verify_data_bundle(args.data_bundle)
    datasets = load_plan066_datasets(args.data_bundle)
    run_spec = validate_run_spec(read_json(args.run_spec))
    route_context, recipe, initial_scope, control, comparison, threshold = (
        run_spec_objects(run_spec)
    )
    adapter = Plan087TorchTrainingAdapter.from_snapshot(
        snapshot_root=args.snapshot,
        model_lock_path=args.model_lock,
        recipe=recipe,
    )
    try:
        return _run_with_adapter(
            args,
            resume=resume,
            recovery_only=recovery_only,
            source_receipt=source_receipt,
            route=route,
            data_receipt=data_receipt,
            datasets=datasets,
            run_spec=run_spec,
            route_context=route_context,
            initial_scope=initial_scope,
            control=control,
            comparison=comparison,
            threshold=threshold,
            adapter=adapter,
            capacity=capacity,
        )
    finally:
        adapter.close()


def _run_with_adapter(
    args: argparse.Namespace,
    *,
    resume: bool,
    recovery_only: bool,
    source_receipt: dict[str, Any],
    route: dict[str, Any],
    data_receipt: dict[str, Any],
    datasets: Any,
    run_spec: dict[str, Any],
    route_context: dict[str, Any],
    initial_scope: Any,
    control: Any,
    comparison: Any,
    threshold: float,
    adapter: Plan087TorchTrainingAdapter,
    capacity: dict[str, Any],
) -> dict[str, Any]:
    store = Plan081ArtifactStore(args.artifact_root)
    process_identity = _process_identity()
    runtime_identity = adapter.plan087_runtime_identity()
    checkpoint_receipt: dict[str, Any] | None = None
    if resume:
        source_process = _load_process_receipt(args.source_process_receipt)
        if (
            source_process["source"] != source_receipt
            or source_process["runtime_identity_sha256"]
            != sha256_bytes(canonical_json_bytes(runtime_identity))
            or source_process["route_context_sha256"]
            != sha256_bytes(canonical_json_bytes(route_context))
        ):
            raise FullModelTrainingError("plan087_process_binding_mismatch")
        checkpoint = store.verify_checkpoint(args.checkpoint_id)
        controller = Plan087AdaptiveTrainingController.resume(
            route_contract=route,
            control_plan=control,
            comparison_policy=comparison,
            training_dataset=datasets.train,
            validation_dataset=datasets.validation,
            artifact_store=store,
            adapter=adapter,
            checkpoint_id=args.checkpoint_id,
            report_threshold=threshold,
        )
        if controller.state["plan087"]["route_context"] != route_context:
            raise FullModelTrainingError("plan087_resume_route_context_mismatch")
        _require_new_process(source_process["process_identity"], process_identity)
        controller.begin_process(process_identity)
        controller.record_new_process_recovery(
            args.checkpoint_id, checkpoint["content_sha256"]
        )
        restored_step = int(controller.state["current_step"])
    else:
        source_process = None
        checkpoint = None
        controller = Plan087AdaptiveTrainingController(
            route_context=route_context,
            run_spec=run_spec,
            route_contract=route,
            control_plan=control,
            initial_scope=initial_scope,
            comparison_policy=comparison,
            training_dataset=datasets.train,
            validation_dataset=datasets.validation,
            artifact_store=store,
            report_threshold=threshold,
        )
        controller.begin_process(process_identity)
        controller.initialize(adapter)
        restored_step = 0
    process_receipt = {
        "schema": PROCESS_RECEIPT_SCHEMA,
        "process_identity": process_identity,
        "source_process_id": (
            source_process["process_identity"]["instance_id"]
            if source_process is not None
            else None
        ),
        "status": "started",
        "global_step": restored_step,
        "runtime_identity_sha256": sha256_bytes(canonical_json_bytes(runtime_identity)),
        "route_context_sha256": sha256_bytes(canonical_json_bytes(route_context)),
        "source": source_receipt,
    }
    write_exclusive(args.process_receipt_output, pretty_json_bytes(process_receipt))
    summary = (
        controller.archive_summary()
        if recovery_only
        else run_scheduled(controller, adapter, run_spec, stop_after=args.stop_after)
    )
    if resume:
        if not recovery_only and int(controller.state["current_step"]) <= restored_step:
            raise FullModelTrainingError("plan087_recovery_probe_update_missing")
        checkpoint_receipt = {
            "schema": RECOVERY_RECEIPT_SCHEMA,
            "checkpoint_id": args.checkpoint_id,
            "checkpoint_sha256": checkpoint["content_sha256"],
            "runtime_identity_sha256": process_receipt["runtime_identity_sha256"],
            "route_context_sha256": process_receipt["route_context_sha256"],
            "source_process_id": source_process["process_identity"]["instance_id"],
            "recovery_process_id": process_identity["instance_id"],
            "fresh_adapter": True,
            "model_loaded": True,
            "optimizer_scheduler_rng_data_equal": True,
            "probe_update_completed": not recovery_only,
            "checkpoint_reuse_verified": True,
        }
    write_exclusive(args.state_output, pretty_json_bytes(controller.state))
    if checkpoint_receipt is not None:
        write_exclusive(
            args.recovery_receipt_output, pretty_json_bytes(checkpoint_receipt)
        )
    return {
        "summary": summary,
        "process_receipt": process_receipt,
        "recovery_receipt": checkpoint_receipt,
        "data": data_receipt,
        "capacity_preflight": capacity,
    }


def _preflight_segment_outputs(args: Any, *, resume: bool) -> None:
    artifact = Path(args.artifact_root)
    if resume:
        if artifact.is_symlink() or not artifact.is_dir():
            raise FullModelTrainingError("plan087_segment_artifact_root_invalid")
    elif artifact.exists() or artifact.is_symlink():
        raise FullModelTrainingError("plan087_segment_artifact_root_conflict")
    outputs = [Path(args.state_output), Path(args.process_receipt_output)]
    if resume:
        outputs.append(Path(args.recovery_receipt_output))
    _require_task_owned_paths(artifact, *outputs)
    resolved_artifact = artifact.resolve(strict=False)
    resolved_outputs: list[Path] = []
    for output in outputs:
        if output.exists() or output.is_symlink():
            raise FullModelTrainingError("plan087_segment_output_conflict")
        resolved = output.resolve(strict=False)
        if _paths_alias(resolved, resolved_artifact) or any(
            _paths_alias(resolved, previous) for previous in resolved_outputs
        ):
            raise FullModelTrainingError("plan087_segment_output_alias_invalid")
        resolved_outputs.append(resolved)


def _paths_alias(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _require_task_owned_if_configured(*paths: Path) -> None:
    if os.getenv("RONDO_PLAN087_TASK_ROOT"):
        _require_task_owned_paths(*paths)


def _require_task_owned_paths(*paths: Path) -> None:
    raw = os.getenv("RONDO_PLAN087_TASK_ROOT")
    if not raw:
        raise FullModelTrainingError("plan087_task_root_required")
    task_path = Path(raw)
    _reject_existing_symlink_chain(task_path)
    task_root = safe_directory(task_path)
    for path in paths:
        candidate = path if path.is_absolute() else Path.cwd() / path
        _reject_existing_symlink_chain(candidate)
        resolved = candidate.resolve(strict=False)
        if resolved == task_root or not resolved.is_relative_to(task_root):
            raise FullModelTrainingError("plan087_task_owned_path_required")


def _require_configured_task_root(path: Path) -> Path:
    raw = os.getenv("RONDO_PLAN087_TASK_ROOT")
    if not raw:
        raise FullModelTrainingError("plan087_task_root_required")
    _reject_existing_symlink_chain(Path(raw))
    configured = safe_directory(Path(raw))
    _reject_existing_symlink_chain(path)
    if safe_directory(path) != configured:
        raise FullModelTrainingError("plan087_task_root_mismatch")
    return configured


def _parse_handoff_entry(value: str) -> tuple[str, str]:
    role, separator, relative_path = value.partition("=")
    if not separator or not role or not relative_path:
        raise FullModelTrainingError("plan087_handoff_entry_invalid")
    return role, relative_path


def _reject_existing_symlink_chain(path: Path) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise FullModelTrainingError("plan087_task_path_inspection_failed") from exc
        if stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan087_task_path_symlink_rejected")


def _verify_executing_source(
    *, source_archive: Path, source_root: Path, receipt_path: Path
) -> dict[str, Any]:
    expected = read_json(receipt_path)
    if not isinstance(expected, dict) or not isinstance(expected.get("commit"), str):
        raise FullModelTrainingError("plan087_source_receipt_invalid")
    try:
        root = Path(source_root).resolve(strict=True)
    except OSError as exc:
        raise FullModelTrainingError("plan087_source_root_unavailable") from exc
    if root != Path(__file__).resolve().parents[4]:
        raise FullModelTrainingError("plan087_executing_source_root_mismatch")
    observed = verify_source_archive(
        source_archive,
        root,
        exact_tree=True,
        expected_commit=expected["commit"],
    )
    if observed != expected:
        raise FullModelTrainingError("plan087_source_receipt_mismatch")
    return observed


def _load_process_receipt(path: Path) -> dict[str, Any]:
    return validate_process_receipt(read_json(path))


def _process_identity() -> dict[str, Any]:
    return {
        "instance_id": uuid.uuid4().hex,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
    }


def _require_new_process(source: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    left = validate_process_identity(source)
    right = validate_process_identity(current)
    if left["instance_id"] == right["instance_id"] or (
        left["hostname"] == right["hostname"] and left["pid"] == right["pid"]
    ):
        raise FullModelTrainingError("plan087_recovery_process_not_new")


if __name__ == "__main__":
    raise SystemExit(main())
