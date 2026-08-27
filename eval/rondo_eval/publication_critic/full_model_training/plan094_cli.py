"""Narrow local/cloud command surface for Plan 094 continuous training."""

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
from .plan081_contract import ComparisonPolicy, ControlPlan, TrainableScope, load_route_contract
from .plan082_adapter import verify_snapshot
from .plan082_environment import (
    _publish_identical,
    observe_environment,
    publish_bootstrap_ready_receipt,
)
from .plan090_artifacts import Plan090ArtifactStore
from .plan094_adapter import Plan094TorchTrainingAdapter
from .plan094_artifacts import Plan094ArtifactStore
from .plan094_bundle import (
    create_data_archive,
    create_source_archive,
    extract_data_archive,
    extract_source_archive,
    prepare_data_bundle,
    verify_data_bundle,
    verify_source_archive,
)
from .plan094_contract import (
    DATA_BUNDLE_CONTENT_SHA256,
    PLAN090_SOURCE_CHECKPOINT_PATH,
    freeze_sha256,
    frozen_contract,
    materialize_run_spec,
    validate_budget_snapshot,
    validate_freeze,
    validate_run_spec,
)
from .plan094_controller import Plan094ContinuousTrainingController, validate_runtime_identity
from .plan094_finalize import finalize_terminal

PROCESS_RECEIPT_SCHEMA = "rondo-publication-critic-plan094-process-receipt-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publication-critic-plan094")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-data")
    prepare.add_argument("--canonical-plan066", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    verify_data = commands.add_parser("verify-data")
    verify_data.add_argument("--bundle", type=Path, required=True)
    verify_data.add_argument("--receipt-output", type=Path)
    archive = commands.add_parser("create-data-archive")
    archive.add_argument("--bundle", type=Path, required=True)
    archive.add_argument("--output", type=Path, required=True)
    archive.add_argument("--receipt-output", type=Path)
    extract = commands.add_parser("extract-data-archive")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--expected-sha256", required=True)
    extract.add_argument("--output", type=Path, required=True)

    source = commands.add_parser("create-source-archive")
    source.add_argument("--repo", type=Path, required=True)
    source.add_argument("--commit", required=True)
    source.add_argument("--output", type=Path, required=True)
    source.add_argument("--receipt-output", type=Path)
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

    validate_freeze_parser = commands.add_parser("validate-freeze")
    validate_freeze_parser.add_argument("--freeze", type=Path, required=True)
    write_freeze = commands.add_parser("write-freeze")
    write_freeze.add_argument("--output", type=Path, required=True)
    budget = commands.add_parser("validate-budget")
    budget.add_argument("--snapshot", type=Path, required=True)
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
    inventory = commands.add_parser("parameter-inventory")
    inventory.add_argument("--snapshot", type=Path, required=True)
    inventory.add_argument("--model-lock", type=Path, required=True)
    inventory.add_argument("--freeze", type=Path, required=True)
    materialize = commands.add_parser("materialize-run-spec")
    materialize.add_argument("--freeze", type=Path, required=True)
    materialize.add_argument("--run-kind", choices=("commissioning", "formal"), required=True)
    materialize.add_argument("--namespace", required=True)
    materialize.add_argument("--source-commit", required=True)
    materialize.add_argument("--source-archive-sha256", required=True)
    materialize.add_argument("--inventory", type=Path, required=True)
    materialize.add_argument(
        "--continuation-mode",
        choices=(
            "guarded_plan090_full_checkpoint_import",
            "exact_base_rebuild_of_route_o_step_1",
        ),
        required=True,
    )
    materialize.add_argument("--output", type=Path, required=True)

    start = commands.add_parser("start")
    _add_run_arguments(start)
    start.add_argument("--plan090-source-checkpoint", type=Path)
    resume = commands.add_parser("resume")
    _add_run_arguments(resume)
    resume.add_argument("--checkpoint-id", required=True)

    terminal = commands.add_parser("finalize-terminal")
    terminal.add_argument("--freeze", type=Path, required=True)
    terminal.add_argument("--controller-state", type=Path, required=True)
    terminal.add_argument("--artifact-root", type=Path, required=True)
    terminal.add_argument("--resource-state", type=Path, required=True)
    terminal.add_argument("--terminal-budget", type=Path, required=True)
    terminal.add_argument("--outcome")
    terminal.add_argument("--reason")
    terminal.add_argument("--output", type=Path, required=True)
    return parser


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--budget-snapshot", type=Path, required=True)
    parser.add_argument("--data-bundle", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--stop-after", type=int, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--process-receipt-output", type=Path, required=True)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _dispatch(args)
    except FullModelTrainingError as exc:
        print(
            json.dumps(
                {"status": "failed", "failure_kind": type(exc).__name__, "code": exc.code},
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
        return _record_optional(verify_data_bundle(args.bundle), args.receipt_output)
    if args.command == "create-data-archive":
        _require_task_owned_if_configured(args.output)
        return _record_optional(
            create_data_archive(args.bundle, args.output), args.receipt_output
        )
    if args.command == "extract-data-archive":
        _require_task_owned_if_configured(args.output)
        return extract_data_archive(
            args.archive, args.output, expected_sha256=args.expected_sha256
        )
    if args.command == "create-source-archive":
        _require_task_owned_if_configured(args.output)
        return _record_optional(
            create_source_archive(args.repo, args.output, source_commit=args.commit),
            args.receipt_output,
        )
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
    if args.command == "validate-freeze":
        return validate_freeze(read_json(args.freeze))
    if args.command == "write-freeze":
        value = frozen_contract()
        write_exclusive(args.output, pretty_json_bytes(value))
        return value
    if args.command == "validate-budget":
        return validate_budget_snapshot(read_json(args.snapshot))
    if args.command == "verify-snapshot":
        _require_paid_gate()
        return verify_snapshot(args.snapshot, args.model_lock)
    if args.command == "capture-environment":
        _require_paid_gate()
        _require_task_owned_paths(args.output)
        value = observe_environment(
            image_identity=os.getenv("RONDO_PLAN094_IMAGE_IDENTITY")
        )
        _publish_identical(args.output, pretty_json_bytes(value))
        return value
    if args.command == "publish-bootstrap-ready":
        _require_paid_gate()
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
    if args.command == "parameter-inventory":
        _require_paid_gate()
        contract = validate_freeze(read_json(args.freeze))
        adapter = _new_adapter(args.snapshot, args.model_lock, contract["recipe"])
        try:
            return adapter.parameter_inventory()
        finally:
            adapter.close()
    if args.command == "materialize-run-spec":
        result = materialize_run_spec(
            read_json(args.freeze),
            run_kind=args.run_kind,
            namespace=args.namespace,
            source_commit=args.source_commit,
            source_archive_sha256=args.source_archive_sha256,
            parameter_inventory=read_json(args.inventory),
            continuation_mode=args.continuation_mode,
        )
        _require_task_owned_if_configured(args.output)
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    if args.command in {"start", "resume"}:
        return _run(args, recovery=args.command == "resume")
    if args.command == "finalize-terminal":
        _require_task_owned_paths(args.output)
        result = finalize_terminal(
            freeze=read_json(args.freeze),
            controller_state=read_json(args.controller_state),
            artifact_root=args.artifact_root,
            resource_state=read_json(args.resource_state),
            terminal_budget_snapshot=read_json(args.terminal_budget),
            outcome=args.outcome,
            reason=args.reason,
        )
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    raise FullModelTrainingError("plan094_command_invalid")


def _run(args: argparse.Namespace, *, recovery: bool) -> dict[str, Any]:
    _require_paid_gate()
    contract = validate_freeze(read_json(args.freeze))
    spec = validate_run_spec(read_json(args.run_spec), freeze=contract)
    budget = validate_budget_snapshot(read_json(args.budget_snapshot))
    if budget["segment_authorized"] is not True or budget[
        "projected_segment_and_closure_usd"
    ] <= 0.0:
        raise FullModelTrainingError("plan094_run_budget_not_authorized")
    _preflight_outputs(args, recovery=recovery, run_spec=spec)
    source = _verify_executing_source(
        archive=args.source_archive,
        source_root=args.source_root,
        receipt_path=args.source_receipt,
    )
    if (
        source["commit"] != spec["source_commit"]
        or source["archive_sha256"] != spec["source_archive_sha256"]
    ):
        raise FullModelTrainingError("plan094_source_run_binding_invalid")
    data = verify_data_bundle(args.data_bundle)
    if data["content_sha256"] != DATA_BUNDLE_CONTENT_SHA256:
        raise FullModelTrainingError("plan094_data_identity_mismatch")
    datasets = load_plan066_datasets(args.data_bundle)
    route = load_route_contract(args.route)
    adapter = _new_adapter(args.snapshot, args.model_lock, spec["recipe"])
    try:
        store = Plan094ArtifactStore(args.artifact_root)
        process = _process_identity()
        runtime = validate_runtime_identity(
            adapter.plan094_runtime_identity(), run_spec=spec
        )
        if recovery:
            controller = Plan094ContinuousTrainingController.resume(
                freeze=contract,
                run_spec=spec,
                route_contract=route,
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=datasets.train,
                validation_dataset=datasets.validation,
                artifact_store=store,
                adapter=adapter,
                checkpoint_id=args.checkpoint_id,
                process_identity=process,
                budget_snapshot=budget,
                report_threshold=spec["report_threshold"],
            )
        else:
            controller = Plan094ContinuousTrainingController(
                freeze=contract,
                run_spec=spec,
                launch_budget_snapshot=budget,
                route_contract=route,
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                initial_scope=TrainableScope.from_value(spec["scope"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=datasets.train,
                validation_dataset=datasets.validation,
                artifact_store=store,
                report_threshold=spec["report_threshold"],
            )
            controller.begin_process(process)
            controller.initialize(adapter)
            if spec["continuation_mode"] == "guarded_plan090_full_checkpoint_import":
                source_checkpoint = args.plan090_source_checkpoint
                if (
                    source_checkpoint is None
                    or str(source_checkpoint) != PLAN090_SOURCE_CHECKPOINT_PATH
                ):
                    raise FullModelTrainingError(
                        "plan094_source_checkpoint_locator_invalid"
                    )
                controller.import_plan090_checkpoint(
                    adapter,
                    source_store=Plan090ArtifactStore(source_checkpoint.parents[1]),
                    checkpoint_id=source_checkpoint.name,
                )
            elif args.plan090_source_checkpoint is not None:
                raise FullModelTrainingError("plan094_source_checkpoint_unexpected")
        receipt = {
            "schema": PROCESS_RECEIPT_SCHEMA,
            "process_identity": process,
            "status": "started",
            "restored_global_step": controller.state["current_step"],
            "target_global_step": args.stop_after,
            "freeze_sha256": freeze_sha256(contract),
            "runtime_identity_sha256": sha256_bytes(canonical_json_bytes(runtime)),
            "source": source,
            "recovery_checkpoint_id": args.checkpoint_id if recovery else None,
        }
        write_exclusive(args.process_receipt_output, pretty_json_bytes(receipt))
        controller.run(adapter, stop_after=args.stop_after)
        write_exclusive(args.state_output, pretty_json_bytes(controller.state))
        return {
            "summary": controller.archive_summary(),
            "process_receipt": receipt,
            "data": data,
        }
    finally:
        adapter.close()


def _new_adapter(snapshot: Path, model_lock: Path, recipe: Mapping[str, Any]) -> Any:
    return Plan094TorchTrainingAdapter.from_snapshot(
        snapshot_root=snapshot, model_lock_path=model_lock, recipe=recipe
    )


def _verify_executing_source(
    *, archive: Path, source_root: Path, receipt_path: Path
) -> dict[str, Any]:
    expected = read_json(receipt_path)
    if not isinstance(expected, Mapping) or not isinstance(expected.get("commit"), str):
        raise FullModelTrainingError("plan094_source_receipt_invalid")
    root = Path(source_root).resolve(strict=True)
    if root != Path(__file__).resolve().parents[4]:
        raise FullModelTrainingError("plan094_executing_source_root_mismatch")
    observed = verify_source_archive(
        archive, root, exact_tree=True, expected_commit=expected["commit"]
    )
    if observed != expected:
        raise FullModelTrainingError("plan094_source_receipt_mismatch")
    return observed


def _preflight_outputs(
    args: argparse.Namespace, *, recovery: bool, run_spec: Mapping[str, Any]
) -> None:
    artifact = Path(args.artifact_root)
    if recovery:
        if artifact.is_symlink() or not artifact.is_dir():
            raise FullModelTrainingError("plan094_artifact_root_invalid")
    elif artifact.exists() or artifact.is_symlink():
        raise FullModelTrainingError("plan094_artifact_root_conflict")
    _require_task_owned_paths(artifact, args.state_output, args.process_receipt_output)
    expected = (
        _configured_task_root() / run_spec["artifact_namespace"] / "artifacts"
    ).resolve(strict=False)
    if artifact.resolve(strict=False) != expected:
        raise FullModelTrainingError("plan094_artifact_namespace_mismatch")
    for path in (args.state_output, args.process_receipt_output):
        if Path(path).exists() or Path(path).is_symlink():
            raise FullModelTrainingError("plan094_output_conflict")


def _record_optional(value: Any, output: Path | None) -> Any:
    if output is not None:
        _require_task_owned_if_configured(output)
        write_exclusive(output, pretty_json_bytes(value))
    return value


def _require_paid_gate() -> None:
    if os.getenv("RONDO_PLAN094_STAGE_B_APPROVED") != "1":
        raise FullModelTrainingError("plan094_stage_b_approval_required")


def _require_task_owned_if_configured(*paths: Path) -> None:
    if os.getenv("RONDO_PLAN094_TASK_ROOT"):
        _require_task_owned_paths(*paths)


def _require_task_owned_paths(*paths: Path) -> None:
    root = _configured_task_root()
    for path in paths:
        candidate = path if path.is_absolute() else Path.cwd() / path
        _reject_symlink_chain(candidate)
        resolved = candidate.resolve(strict=False)
        if resolved == root or not resolved.is_relative_to(root):
            raise FullModelTrainingError("plan094_task_owned_path_required")


def _configured_task_root() -> Path:
    raw = os.getenv("RONDO_PLAN094_TASK_ROOT")
    if not raw:
        raise FullModelTrainingError("plan094_task_root_required")
    _reject_symlink_chain(Path(raw))
    root = safe_directory(Path(raw))
    if not root.name.startswith("rondo-plan094-") or root.name == "rondo-plan094-":
        raise FullModelTrainingError("plan094_task_root_namespace_invalid")
    return root


def _reject_symlink_chain(path: Path) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise FullModelTrainingError("plan094_task_path_inspection_failed") from exc
        if stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan094_task_path_symlink_rejected")


def _process_identity() -> dict[str, Any]:
    return {
        "instance_id": uuid.uuid4().hex,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
