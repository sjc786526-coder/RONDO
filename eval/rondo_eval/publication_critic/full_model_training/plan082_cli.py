"""Command-line entrypoint for Plan 082 preparation, training, and handoff."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import os
from pathlib import Path
import socket
import sys
import uuid
from typing import Any

from ...config import ConfigError, RepoPaths
from ..local_deployment.handoff import HandoffError
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
from .plan082_adapter import TorchContinuousTrainingAdapter, verify_snapshot
from .plan082_bundle import (
    create_data_archive,
    create_source_archive,
    extract_data_archive,
    extract_source_archive,
    prepare_data_bundle,
    verify_data_bundle,
    verify_source_archive,
)
from .plan082_controller import (
    Plan082ContinuousTrainingController,
    validate_process_identity,
)
from .plan082_formal import (
    RECOVERY_SCHEMA,
    create_formal_freeze,
    finalize_formal_run,
    load_formal_freeze,
)
from .plan082_environment import (
    publish_bootstrap_ready_receipt,
    publish_environment_receipt,
)
from .plan082_handoff import (
    MAX_OBJECTS,
    MAX_TOTAL_BYTES,
    create_handoff_binding,
    create_handoff_client,
    create_retained_bootstrap_manifest,
    download,
    inventory,
    load_handoff,
    local_handoff_preflight,
)
from .plan082_run import run_scheduled, run_spec_objects, validate_run_spec


RUN_RECEIPT_SCHEMA = "rondo-publication-critic-plan082-process-receipt-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publication-critic-plan082")
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
    ready.add_argument("--source-receipt", type=Path, required=True)
    ready.add_argument("--data-receipt", type=Path, required=True)
    ready.add_argument("--snapshot-receipt", type=Path, required=True)
    ready.add_argument("--environment-receipt", type=Path, required=True)
    ready.add_argument("--source-root", type=Path, required=True)
    ready.add_argument("--data-root", type=Path, required=True)
    ready.add_argument("--model-root", type=Path, required=True)
    ready.add_argument("--output", type=Path, required=True)

    freeze = commands.add_parser("freeze-formal")
    freeze.add_argument("--run-id", required=True)
    freeze.add_argument("--formal-namespace", type=Path, required=True)
    freeze.add_argument("--source-receipt", type=Path, required=True)
    freeze.add_argument("--data-bundle", type=Path, required=True)
    freeze.add_argument("--route", type=Path, required=True)
    freeze.add_argument("--snapshot", type=Path, required=True)
    freeze.add_argument("--model-lock", type=Path, required=True)
    freeze.add_argument("--run-spec", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)

    for name in ("start", "resume"):
        run = commands.add_parser(name)
        _add_run_arguments(run)
        if name == "resume":
            run.add_argument("--checkpoint-id", required=True)
            run.add_argument("--source-process-receipt", type=Path, required=True)
            run.add_argument("--recovery-receipt-output", type=Path, required=True)

    finalize = commands.add_parser("finalize-formal")
    finalize.add_argument("--freeze", type=Path, required=True)
    finalize.add_argument("--controller-state", type=Path, required=True)
    finalize.add_argument("--recovery-receipt", type=Path, required=True)
    finalize.add_argument("--artifact-root", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)

    bootstrap_manifest = commands.add_parser("create-handoff-bootstrap")
    bootstrap_manifest.add_argument("--freeze-sha256", required=True)
    bootstrap_manifest.add_argument("--task-root", type=Path, required=True)
    bootstrap_manifest.add_argument("--artifact-root", type=Path, required=True)
    bootstrap_manifest.add_argument("--formal-result", type=Path, required=True)
    bootstrap_manifest.add_argument("--output", type=Path, required=True)

    handoff_binding = commands.add_parser("create-handoff-binding")
    handoff_binding.add_argument("--freeze-sha256", required=True)
    handoff_binding.add_argument("--volume-id", required=True)
    handoff_binding.add_argument("--region", required=True)
    handoff_binding.add_argument("--task-root", required=True)
    handoff_binding.add_argument("--allowed-prefix", action="append", required=True)
    handoff_binding.add_argument("--run-id", required=True)
    handoff_binding.add_argument("--bootstrap-key", required=True)
    handoff_binding.add_argument("--bootstrap", type=Path, required=True)
    handoff_binding.add_argument("--max-objects", type=int, default=MAX_OBJECTS)
    handoff_binding.add_argument("--max-total-bytes", type=int, default=MAX_TOTAL_BYTES)
    handoff_binding.add_argument("--output", type=Path, required=True)

    for name in ("handoff-inventory", "handoff-download"):
        handoff = commands.add_parser(name)
        handoff.add_argument("--binding", type=Path, required=True)
    handoff_preflight = commands.add_parser("handoff-preflight")
    handoff_preflight.add_argument(
        "--operation", choices=("inventory", "download"), required=True
    )
    handoff_preflight.add_argument("--binding", type=Path, required=True)
    handoff_preflight.add_argument("--requirements", type=Path, required=True)
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
    parser.add_argument("--formal-freeze", type=Path)
    parser.add_argument("--stop-after", type=int)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _dispatch(args)
    except (FullModelTrainingError, HandoffError, ConfigError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        print(
            json.dumps(
                {"status": "failed", "failure_kind": type(exc).__name__, "code": code},
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
        return extract_data_archive(
            args.archive,
            args.output,
            expected_sha256=args.expected_sha256,
        )
    if args.command == "create-source-archive":
        return create_source_archive(
            args.repo,
            args.output,
            source_commit=args.commit,
        )
    if args.command == "verify-source-archive":
        return verify_source_archive(
            args.archive,
            args.source_root,
            exact_tree=args.exact_tree,
            expected_commit=args.expected_commit,
        )
    if args.command == "extract-source-archive":
        return extract_source_archive(
            args.archive,
            args.output,
            expected_sha256=args.expected_sha256,
            expected_commit=args.expected_commit,
        )
    if args.command == "verify-snapshot":
        return verify_snapshot(args.snapshot, args.model_lock)
    if args.command == "capture-environment":
        return publish_environment_receipt(args.output)
    if args.command == "publish-bootstrap-ready":
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
    if args.command == "freeze-formal":
        run_spec = validate_run_spec(read_json(args.run_spec))
        adapter = TorchContinuousTrainingAdapter.from_snapshot(
            snapshot_root=args.snapshot,
            model_lock_path=args.model_lock,
            recipe=run_spec["recipe"],
        )
        try:
            return create_formal_freeze(
                args.output,
                run_id=args.run_id,
                formal_namespace=args.formal_namespace,
                source_receipt=read_json(args.source_receipt),
                data_bundle_root=args.data_bundle,
                route_contract=load_route_contract(args.route),
                runtime_identity=adapter.plan082_runtime_identity(),
                parameter_inventory=adapter.parameter_inventory(),
                run_spec=run_spec,
                retention=_retention_policy(),
            )
        finally:
            adapter.close()
    if args.command in {"start", "resume"}:
        return _run(args, resume=args.command == "resume")
    if args.command == "finalize-formal":
        artifact_root = safe_directory(args.artifact_root)
        result = finalize_formal_run(
            freeze=load_formal_freeze(args.freeze),
            controller_state=read_json(args.controller_state),
            recovery_receipt=read_json(args.recovery_receipt),
            artifact_store=Plan081ArtifactStore(artifact_root),
        )
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    if args.command == "create-handoff-bootstrap":
        return create_retained_bootstrap_manifest(
            args.output,
            freeze_sha256=args.freeze_sha256,
            task_root=args.task_root,
            artifact_root=args.artifact_root,
            formal_result=read_json(args.formal_result),
        )
    if args.command == "create-handoff-binding":
        return create_handoff_binding(
            args.output,
            freeze_sha256=args.freeze_sha256,
            volume_id=args.volume_id,
            region=args.region,
            task_root=args.task_root,
            allowed_prefixes=args.allowed_prefix,
            run_id=args.run_id,
            bootstrap_key=args.bootstrap_key,
            bootstrap_path=args.bootstrap,
            max_objects=args.max_objects,
            max_total_bytes=args.max_total_bytes,
        )
    if args.command in {"handoff-inventory", "handoff-download"}:
        binding = load_handoff(args.binding)
        paths = RepoPaths.discover(Path.cwd())
        destination = paths.common_root.joinpath(
            *Path(binding.destination_relative).parts
        )
        client = create_handoff_client(paths, binding)
        operation = inventory if args.command == "handoff-inventory" else download
        return {
            "operation": args.command,
            "destination": binding.destination_relative,
            "records": list(operation(client, binding, destination)),
        }
    if args.command == "handoff-preflight":
        paths = RepoPaths.discover(Path.cwd())
        binding = load_handoff(args.binding)
        destination = paths.common_root.joinpath(
            *Path(binding.destination_relative).parts
        )
        return local_handoff_preflight(
            binding,
            operation=args.operation,
            requirements_path=args.requirements,
            source_root=paths.worktree_root,
            destination_root=destination,
        )
    raise FullModelTrainingError("plan082_command_not_implemented")


def _run(args: argparse.Namespace, *, resume: bool) -> dict[str, Any]:
    _preflight_segment_outputs(args, resume=resume)
    source_receipt = _verify_executing_source(
        source_archive=args.source_archive,
        source_root=args.source_root,
        receipt_path=args.source_receipt,
    )
    route = load_route_contract(args.route)
    verify_data_bundle(args.data_bundle)
    datasets = load_plan066_datasets(args.data_bundle)
    run_spec = validate_run_spec(read_json(args.run_spec))
    recipe, initial_scope, control, comparison, threshold = run_spec_objects(run_spec)
    adapter = TorchContinuousTrainingAdapter.from_snapshot(
        snapshot_root=args.snapshot,
        model_lock_path=args.model_lock,
        recipe=recipe,
    )
    try:
        return _run_with_adapter(
            args,
            resume=resume,
            source_receipt=source_receipt,
            route=route,
            data_receipt=verify_data_bundle(args.data_bundle),
            datasets=datasets,
            run_spec=run_spec,
            initial_scope=initial_scope,
            control=control,
            comparison=comparison,
            threshold=threshold,
            adapter=adapter,
        )
    finally:
        adapter.close()


def _run_with_adapter(
    args: argparse.Namespace,
    *,
    resume: bool,
    source_receipt: dict[str, Any],
    route: dict[str, Any],
    data_receipt: dict[str, Any],
    datasets: Any,
    run_spec: dict[str, Any],
    initial_scope: Any,
    control: Any,
    comparison: Any,
    threshold: float,
    adapter: TorchContinuousTrainingAdapter,
) -> dict[str, Any]:
    _preflight_segment_outputs(args, resume=resume)
    freeze = (
        load_formal_freeze(args.formal_freeze)
        if args.formal_freeze is not None
        else None
    )
    _bind_optional_freeze(
        freeze,
        artifact_root=args.artifact_root,
        route=route,
        run_spec=run_spec,
        runtime_identity=adapter.plan082_runtime_identity(),
        data_receipt=data_receipt,
        source_receipt=source_receipt,
        resume=resume,
        stop_after=args.stop_after,
    )
    store = Plan081ArtifactStore(args.artifact_root)
    checkpoint_receipt: dict[str, Any] | None = None
    process_identity = _process_identity()
    if resume:
        source_process = _load_process_receipt(args.source_process_receipt)
        if source_process["source"] != source_receipt:
            raise FullModelTrainingError("plan082_process_source_mismatch")
        if source_process["runtime_identity_sha256"] != sha256_bytes(
            canonical_json_bytes(adapter.plan082_runtime_identity())
        ):
            raise FullModelTrainingError("plan082_process_runtime_mismatch")
        checkpoint = store.verify_checkpoint(args.checkpoint_id)
        controller = Plan082ContinuousTrainingController.resume(
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
        if controller.state["plan082"]["formal_freeze_sha256"] != (
            freeze["freeze_content_sha256"] if freeze is not None else None
        ):
            raise FullModelTrainingError("plan082_resume_freeze_binding_mismatch")
        if (
            controller.state["plan082"]["process_identity"]
            != source_process["process_identity"]
        ):
            raise FullModelTrainingError("plan082_checkpoint_source_process_mismatch")
        _require_new_process(source_process["process_identity"], process_identity)
        controller.begin_process(process_identity)
        controller.record_new_process_recovery(
            args.checkpoint_id,
            checkpoint["content_sha256"],
        )
        restored_step = int(controller.state["current_step"])
        if freeze is not None and restored_step != freeze["recovery_checkpoint_step"]:
            raise FullModelTrainingError("plan082_formal_recovery_step_mismatch")
    else:
        source_process = None
        checkpoint = None
        controller = Plan082ContinuousTrainingController(
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
        if freeze is not None:
            controller.bind_formal_freeze(freeze["freeze_content_sha256"])
        controller.initialize(adapter)
        restored_step = 0
    process_receipt = {
        "schema": RUN_RECEIPT_SCHEMA,
        "process_identity": process_identity,
        "status": "started",
        "global_step": restored_step,
        "runtime_identity_sha256": sha256_bytes(
            canonical_json_bytes(adapter.plan082_runtime_identity())
        ),
        "source": source_receipt,
    }
    write_exclusive(
        args.process_receipt_output,
        pretty_json_bytes(process_receipt),
    )
    summary = run_scheduled(
        controller,
        adapter,
        run_spec,
        stop_after=args.stop_after,
    )
    if resume:
        if int(controller.state["current_step"]) <= restored_step:
            raise FullModelTrainingError("plan082_recovery_probe_update_missing")
        checkpoint_receipt = {
            "schema": RECOVERY_SCHEMA,
            "checkpoint_id": args.checkpoint_id,
            "checkpoint_sha256": checkpoint["content_sha256"],
            "formal_freeze_sha256": (
                freeze["freeze_content_sha256"] if freeze is not None else None
            ),
            "run_id": freeze["run_id"] if freeze is not None else None,
            "formal_namespace": (
                freeze["formal_namespace"] if freeze is not None else None
            ),
            "runtime_identity_sha256": process_receipt["runtime_identity_sha256"],
            "source_process_id": source_process["process_identity"]["instance_id"],
            "recovery_process_id": process_identity["instance_id"],
            "fresh_adapter": True,
            "model_loaded": True,
            "optimizer_scheduler_rng_data_equal": True,
            "probe_update_completed": True,
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
    }


def _preflight_segment_outputs(args: argparse.Namespace, *, resume: bool) -> None:
    artifact = Path(args.artifact_root)
    if resume:
        if artifact.is_symlink() or not artifact.is_dir():
            raise FullModelTrainingError("plan082_segment_artifact_root_invalid")
    elif artifact.exists() or artifact.is_symlink():
        raise FullModelTrainingError("plan082_segment_artifact_root_conflict")
    outputs = [Path(args.state_output), Path(args.process_receipt_output)]
    if resume:
        outputs.append(Path(args.recovery_receipt_output))
    resolved_artifact = artifact.resolve(strict=False)
    resolved_outputs: list[Path] = []
    for output in outputs:
        if output.exists() or output.is_symlink():
            raise FullModelTrainingError("plan082_segment_output_conflict")
        resolved = output.resolve(strict=False)
        if _paths_alias(resolved, resolved_artifact):
            raise FullModelTrainingError("plan082_segment_output_alias_invalid")
        if any(_paths_alias(resolved, previous) for previous in resolved_outputs):
            raise FullModelTrainingError("plan082_segment_output_alias_invalid")
        resolved_outputs.append(resolved)


def _paths_alias(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _bind_optional_freeze(
    freeze: dict[str, Any] | None,
    *,
    artifact_root: Path,
    route: dict[str, Any],
    run_spec: dict[str, Any],
    runtime_identity: dict[str, Any],
    data_receipt: dict[str, Any],
    source_receipt: dict[str, Any],
    resume: bool,
    stop_after: int | None,
) -> None:
    if freeze is None:
        return
    artifact = Path(artifact_root).resolve()
    if (
        freeze["formal_namespace"] != str(artifact)
        or freeze["route_contract_sha256"] != sha256_bytes(canonical_json_bytes(route))
        or freeze["run_spec"] != run_spec
        or freeze["runtime_identity"] != runtime_identity
        or freeze["data"] != data_receipt
        or freeze["source"] != source_receipt
    ):
        raise FullModelTrainingError("plan082_formal_runtime_freeze_mismatch")
    if (not resume and (artifact.exists() or artifact.is_symlink())) or (
        resume and (not artifact.is_dir() or artifact.is_symlink())
    ):
        raise FullModelTrainingError("plan082_formal_namespace_state_invalid")
    maximum = freeze["run_spec"]["control_plan"]["maximum_updates"]
    expected_stop = maximum if resume else freeze["recovery_checkpoint_step"]
    if (maximum if stop_after is None else stop_after) != expected_stop:
        raise FullModelTrainingError("plan082_formal_stop_boundary_invalid")


def _load_process_receipt(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema",
            "process_identity",
            "status",
            "global_step",
            "runtime_identity_sha256",
            "source",
        }
        or value.get("schema") != RUN_RECEIPT_SCHEMA
        or value.get("status") != "started"
        or not isinstance(value.get("global_step"), int)
        or isinstance(value["global_step"], bool)
        or value["global_step"] < 0
    ):
        raise FullModelTrainingError("plan082_process_receipt_invalid")
    validate_process_identity(value.get("process_identity"))
    source = value.get("source")
    if not isinstance(source, dict):
        raise FullModelTrainingError("plan082_process_receipt_invalid")
    return value


def _verify_executing_source(
    *,
    source_archive: Path,
    source_root: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    expected = read_json(receipt_path)
    if not isinstance(expected, dict) or not isinstance(expected.get("commit"), str):
        raise FullModelTrainingError("plan082_source_receipt_invalid")
    try:
        root = Path(source_root).resolve(strict=True)
    except OSError as exc:
        raise FullModelTrainingError("plan082_source_root_unavailable") from exc
    executing_root = Path(__file__).resolve().parents[4]
    if root != executing_root:
        raise FullModelTrainingError("plan082_executing_source_root_mismatch")
    observed = verify_source_archive(
        source_archive,
        root,
        exact_tree=True,
        expected_commit=expected["commit"],
    )
    if observed != expected:
        raise FullModelTrainingError("plan082_source_receipt_mismatch")
    return observed


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
        raise FullModelTrainingError("plan082_recovery_process_not_new")


def _retention_policy() -> dict[str, Any]:
    return {
        "observations": "all_small_records",
        "snapshots": [
            "training_best",
            "latest",
            "turning_points",
            "best_checkpoint_observation",
        ],
        "checkpoints": [
            "latest",
            "best_checkpoint_observation",
            "turning_points",
            "recovery_proven",
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
