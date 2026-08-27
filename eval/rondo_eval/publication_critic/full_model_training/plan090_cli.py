"""Narrow local/cloud command surface for Plan 090 confirmation."""

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
from .plan081_contract import (
    ComparisonPolicy,
    ControlPlan,
    TrainableScope,
    load_route_contract,
)
from .plan081_observation import (
    build_training_observation,
    build_validation_observation,
    training_identity_sha256,
    validation_identity_sha256,
)
from .plan082_adapter import verify_snapshot
from .plan082_controller import validate_process_identity
from .plan082_environment import (
    _publish_identical,
    observe_environment,
    publish_bootstrap_ready_receipt,
)
from .plan087_handoff import (
    create_small_handoff_manifest,
    stage_small_handoff,
    validate_small_handoff_manifest,
    verify_small_handoff,
)
from .plan090_adapter import Plan090TorchTrainingAdapter
from .plan090_artifacts import Plan090ArtifactStore
from .plan090_bundle import (
    create_data_archive,
    create_source_archive,
    extract_data_archive,
    extract_source_archive,
    prepare_data_bundle,
    verify_data_bundle,
    verify_source_archive,
)
from .plan090_contract import (
    DATA_BUNDLE_CONTENT_SHA256,
    TRAINING_RUNS,
    freeze_sha256,
    frozen_contract,
    materialize_run_spec,
    validate_budget_snapshot,
    validate_freeze,
    validate_run_spec,
)
from .plan090_controller import (
    Plan090ConfirmationController,
    build_objective_diagnostic,
    validate_runtime_identity,
)
from .plan090_finalize import (
    RECOVERY_RECEIPT_SCHEMA,
    finalize_run,
    finalize_terminal,
    next_action,
)

PROCESS_RECEIPT_SCHEMA = "rondo-publication-critic-plan090-process-receipt-v1"
DIAGNOSTIC_SCHEMA = "rondo-publication-critic-plan090-no-update-diagnostic-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publication-critic-plan090")
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

    freeze = commands.add_parser("validate-freeze")
    freeze.add_argument("--freeze", type=Path, required=True)
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
    inventory.add_argument("--run-id", choices=TRAINING_RUNS, required=True)
    materialize = commands.add_parser("materialize-run-spec")
    materialize.add_argument("--freeze", type=Path, required=True)
    materialize.add_argument("--run-id", choices=TRAINING_RUNS, required=True)
    materialize.add_argument("--inventory", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)

    diagnose = commands.add_parser("diagnose")
    _add_model_arguments(diagnose)
    diagnose.add_argument("--run-spec", type=Path, required=True)
    diagnose.add_argument(
        "--role", choices=("exact_base", "legacy_route_o"), required=True
    )
    diagnose.add_argument("--legacy-checkpoint", type=Path)
    diagnose.add_argument("--output", type=Path, required=True)

    for name in ("start", "verify-recovery"):
        run = commands.add_parser(name)
        _add_run_arguments(run)
        run.add_argument("--budget-snapshot", type=Path, required=True)
        if name == "start":
            run.add_argument(
                "--prior-run-result", type=Path, action="append", default=[]
            )
        if name == "verify-recovery":
            run.add_argument("--checkpoint-id", required=True)
            run.add_argument("--source-process-receipt", type=Path, required=True)
            run.add_argument("--recovery-receipt-output", type=Path, required=True)

    finish = commands.add_parser("finalize-run")
    finish.add_argument("--freeze", type=Path, required=True)
    finish.add_argument("--controller-state", type=Path, required=True)
    finish.add_argument("--artifact-root", type=Path, required=True)
    finish.add_argument("--selected-checkpoint-id", required=True)
    finish.add_argument("--recovery-receipt", type=Path)
    finish.add_argument("--output", type=Path, required=True)

    branch = commands.add_parser("next-action")
    branch.add_argument("--freeze", type=Path, required=True)
    branch.add_argument("--run-result", type=Path, action="append", default=[])
    branch.add_argument("--fp32-budget", type=Path)
    terminal = commands.add_parser("finalize-terminal")
    terminal.add_argument("--freeze", type=Path, required=True)
    terminal.add_argument("--run-result", type=Path, action="append", default=[])
    terminal.add_argument("--outcome", required=True)
    terminal.add_argument("--reason", required=True)
    terminal.add_argument("--resource-state", type=Path, required=True)
    terminal.add_argument("--terminal-budget", type=Path, required=True)
    terminal.add_argument("--fp32-budget", type=Path)
    terminal.add_argument("--output", type=Path, required=True)

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


def _add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--data-bundle", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    _add_model_arguments(parser)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--run-spec", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--state-output", type=Path, required=True)
    parser.add_argument("--process-receipt-output", type=Path, required=True)


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
        return _record_optional_receipt(
            verify_data_bundle(args.bundle), args.receipt_output
        )
    if args.command == "create-data-archive":
        _require_task_owned_if_configured(args.output)
        return _record_optional_receipt(
            create_data_archive(args.bundle, args.output), args.receipt_output
        )
    if args.command == "extract-data-archive":
        _require_task_owned_if_configured(args.output)
        return extract_data_archive(
            args.archive, args.output, expected_sha256=args.expected_sha256
        )
    if args.command == "create-source-archive":
        _require_task_owned_if_configured(args.output)
        return _record_optional_receipt(
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
        _require_task_owned_if_configured(args.output)
        value = frozen_contract()
        write_exclusive(args.output, pretty_json_bytes(value))
        return value
    if args.command == "validate-budget":
        return validate_budget_snapshot(read_json(args.snapshot))
    if args.command == "verify-snapshot":
        return verify_snapshot(args.snapshot, args.model_lock)
    if args.command == "capture-environment":
        _require_task_owned_paths(args.output)
        value = observe_environment(
            image_identity=os.getenv("RONDO_PLAN090_IMAGE_IDENTITY")
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
    if args.command == "parameter-inventory":
        contract = validate_freeze(read_json(args.freeze))
        adapter = _new_adapter(
            args.snapshot, args.model_lock, contract["recipes"][args.run_id]
        )
        try:
            return adapter.parameter_inventory()
        finally:
            adapter.close()
    if args.command == "materialize-run-spec":
        _require_task_owned_if_configured(args.output)
        result = materialize_run_spec(
            read_json(args.freeze), args.run_id, read_json(args.inventory)
        )
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    if args.command == "diagnose":
        return _diagnose(args)
    if args.command in {"start", "verify-recovery"}:
        return _run(args, recovery=args.command == "verify-recovery")
    if args.command == "finalize-run":
        _require_task_owned_paths(args.artifact_root, args.output)
        result = finalize_run(
            freeze=read_json(args.freeze),
            controller_state=read_json(args.controller_state),
            artifact_root=args.artifact_root,
            selected_checkpoint_id=args.selected_checkpoint_id,
            recovery_receipt=(
                read_json(args.recovery_receipt)
                if args.recovery_receipt is not None
                else None
            ),
        )
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    if args.command == "next-action":
        return next_action(
            read_json(args.freeze),
            [read_json(path) for path in args.run_result],
            fp32_budget_snapshot=(
                read_json(args.fp32_budget) if args.fp32_budget is not None else None
            ),
        )
    if args.command == "finalize-terminal":
        _require_task_owned_paths(args.output)
        result = finalize_terminal(
            freeze=read_json(args.freeze),
            run_results=[read_json(path) for path in args.run_result],
            outcome=args.outcome,
            reason=args.reason,
            resource_state=read_json(args.resource_state),
            terminal_budget_snapshot=read_json(args.terminal_budget),
            fp32_budget_snapshot=(
                read_json(args.fp32_budget) if args.fp32_budget is not None else None
            ),
        )
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
    raise FullModelTrainingError("plan090_command_invalid")


def _diagnose(args: argparse.Namespace) -> dict[str, Any]:
    _require_task_owned_paths(args.output)
    contract = validate_freeze(read_json(args.freeze))
    spec = validate_run_spec(read_json(args.run_spec), freeze=contract)
    if spec["run_id"] != TRAINING_RUNS[0]:
        raise FullModelTrainingError("plan090_diagnostic_run_spec_invalid")
    data = verify_data_bundle(args.data_bundle)
    if data["content_sha256"] != DATA_BUNDLE_CONTENT_SHA256:
        raise FullModelTrainingError("plan090_data_identity_mismatch")
    datasets = load_plan066_datasets(args.data_bundle)
    adapter = _new_adapter(args.snapshot, args.model_lock, spec["recipe"])
    checkpoint = None
    try:
        if args.role == "legacy_route_o":
            if args.legacy_checkpoint is None:
                raise FullModelTrainingError("plan090_legacy_checkpoint_required")
            checkpoint_path = Path(args.legacy_checkpoint)
            if checkpoint_path.parent.name != "recovery-checkpoints":
                raise FullModelTrainingError(
                    "plan090_legacy_checkpoint_locator_invalid"
                )
            store = Plan090ArtifactStore(checkpoint_path.parents[1])
            checkpoint = store.verify_checkpoint(checkpoint_path.name)
            legacy = contract["legacy_checkpoint"]
            if (
                checkpoint_path.name != Path(legacy["relative_path"]).name
                or checkpoint["bytes"] != legacy["bytes"]
                or checkpoint["content_sha256"] != legacy["content_sha256"]
            ):
                raise FullModelTrainingError(
                    "plan090_legacy_checkpoint_identity_mismatch"
                )
            adapter.load_model(checkpoint_path / "payload")
        elif args.legacy_checkpoint is not None:
            raise FullModelTrainingError("plan090_legacy_checkpoint_unexpected")
        scope = TrainableScope.from_value(spec["scope"])
        adapter.configure_trainable_scope(scope)
        adapter.assert_trainable_scope(scope)
        runtime = validate_runtime_identity(
            adapter.plan090_runtime_identity(), run_spec=spec
        )
        validation, train = _build_no_update_diagnostics(
            adapter=adapter,
            datasets=datasets,
            spec=spec,
            scope=scope,
        )
        core = {
            "schema": DIAGNOSTIC_SCHEMA,
            "role": args.role,
            "freeze_sha256": freeze_sha256(contract),
            "run_spec": spec,
            "checkpoint": checkpoint,
            "runtime_identity": runtime,
            "validation_observation": validation,
            "train_observation": train,
            "no_update": True,
            "claims": {
                "diagnostic_only": True,
                "training_initialization": False,
                "unseen_evidence": False,
            },
        }
        result = {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}
        write_exclusive(args.output, pretty_json_bytes(result))
        return result
    finally:
        adapter.close()


def _build_no_update_diagnostics(
    *, adapter: Any, datasets: Any, spec: Mapping[str, Any], scope: TrainableScope
) -> tuple[dict[str, Any], dict[str, Any]]:
    policy = ComparisonPolicy.from_value(spec["comparison_policy"])
    weights = spec["recipe"]["objective"]["component_weights"]
    validation_receipt = _validate_no_update_receipt(
        adapter.evaluate_validation(datasets.validation),
        identity_field="validation_identity_sha256",
        expected_identity=validation_identity_sha256(datasets.validation),
    )
    training_receipt = _validate_no_update_receipt(
        adapter.evaluate_training(datasets.train),
        identity_field="training_identity_sha256",
        expected_identity=training_identity_sha256(datasets.train),
    )
    validation = build_validation_observation(
        datasets.validation,
        validation_receipt["raw_logits"],
        global_step=0,
        scope=scope,
        policy=policy,
        report_threshold=spec["report_threshold"],
    )
    train = build_training_observation(
        datasets.train,
        training_receipt["raw_logits"],
        global_step=0,
        scope=scope,
        policy=policy,
        report_threshold=spec["report_threshold"],
    )
    validation["objective_diagnostic"] = build_objective_diagnostic(
        datasets.validation, validation_receipt["raw_logits"], weights
    )
    train["objective_diagnostic"] = build_objective_diagnostic(
        datasets.train, training_receipt["raw_logits"], weights
    )
    return validation, train


def _validate_no_update_receipt(
    value: Any, *, identity_field: str, expected_identity: str
) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "raw_logits",
            "gradient_access",
            "training_state_unchanged",
            identity_field,
        }
        or not isinstance(value.get("raw_logits"), Mapping)
        or value.get("gradient_access") is not False
        or value.get("training_state_unchanged") is not True
        or value.get(identity_field) != expected_identity
    ):
        raise FullModelTrainingError("plan090_no_update_diagnostic_receipt_invalid")
    return value


def _run(args: argparse.Namespace, *, recovery: bool) -> dict[str, Any]:
    contract = validate_freeze(read_json(args.freeze))
    spec = validate_run_spec(read_json(args.run_spec), freeze=contract)
    budget = validate_budget_snapshot(read_json(args.budget_snapshot))
    _authorize_run_boundary(
        args, recovery=recovery, contract=contract, spec=spec, budget=budget
    )
    _preflight_run_outputs(args, recovery=recovery, run_spec=spec)
    source = _verify_executing_source(
        source_archive=args.source_archive,
        source_root=args.source_root,
        receipt_path=args.source_receipt,
    )
    data = verify_data_bundle(args.data_bundle)
    if data["content_sha256"] != DATA_BUNDLE_CONTENT_SHA256:
        raise FullModelTrainingError("plan090_data_identity_mismatch")
    datasets = load_plan066_datasets(args.data_bundle)
    route = load_route_contract(args.route)
    adapter = _new_adapter(args.snapshot, args.model_lock, spec["recipe"])
    try:
        return _run_with_adapter(
            args,
            recovery=recovery,
            source=source,
            contract=contract,
            spec=spec,
            data=data,
            datasets=datasets,
            route=route,
            adapter=adapter,
            budget=budget,
        )
    finally:
        adapter.close()


def _run_with_adapter(
    args: argparse.Namespace,
    *,
    recovery: bool,
    source: Mapping[str, Any],
    contract: Mapping[str, Any],
    spec: Mapping[str, Any],
    data: Mapping[str, Any],
    datasets: Any,
    route: Mapping[str, Any],
    adapter: Any,
    budget: Mapping[str, Any],
) -> dict[str, Any]:
    store = Plan090ArtifactStore(args.artifact_root)
    process_identity = _process_identity()
    runtime = validate_runtime_identity(
        adapter.plan090_runtime_identity(), run_spec=spec
    )
    source_process = None
    checkpoint = None
    if recovery:
        source_process = validate_process_receipt(
            read_json(args.source_process_receipt)
        )
        if (
            source_process["source"] != source
            or source_process["run_id"] != spec["run_id"]
            or source_process["freeze_sha256"] != freeze_sha256(contract)
            or source_process["runtime_identity_sha256"]
            != sha256_bytes(canonical_json_bytes(runtime))
        ):
            raise FullModelTrainingError("plan090_process_binding_mismatch")
        checkpoint = store.verify_checkpoint(args.checkpoint_id)
        controller = Plan090ConfirmationController.resume(
            route_contract=route,
            control_plan=ControlPlan.from_value(spec["control_plan"]),
            comparison_policy=ComparisonPolicy.from_value(spec["comparison_policy"]),
            training_dataset=datasets.train,
            validation_dataset=datasets.validation,
            artifact_store=store,
            adapter=adapter,
            checkpoint_id=args.checkpoint_id,
            report_threshold=spec["report_threshold"],
        )
        _require_budget_continuity(
            controller.state["plan090"]["launch_budget_snapshot"], budget
        )
        if (
            controller.state["plan090"]["process_identity"]
            != source_process["process_identity"]
        ):
            raise FullModelTrainingError("plan090_process_binding_mismatch")
        _require_new_process(source_process["process_identity"], process_identity)
        controller.begin_process(process_identity)
        controller.record_new_process_recovery(
            args.checkpoint_id, checkpoint["content_sha256"]
        )
        restored_step = int(controller.state["current_step"])
    else:
        controller = Plan090ConfirmationController(
            freeze=contract,
            run_spec=spec,
            launch_budget_snapshot=budget,
            route_contract=route,
            control_plan=ControlPlan.from_value(spec["control_plan"]),
            initial_scope=TrainableScope.from_value(spec["scope"]),
            comparison_policy=ComparisonPolicy.from_value(spec["comparison_policy"]),
            training_dataset=datasets.train,
            validation_dataset=datasets.validation,
            artifact_store=store,
            report_threshold=spec["report_threshold"],
        )
        controller.begin_process(process_identity)
        controller.initialize(adapter)
        restored_step = 0
    process = {
        "schema": PROCESS_RECEIPT_SCHEMA,
        "process_identity": process_identity,
        "source_process_id": (
            source_process["process_identity"]["instance_id"]
            if source_process is not None
            else None
        ),
        "status": "started",
        "global_step": restored_step,
        "run_id": spec["run_id"],
        "freeze_sha256": freeze_sha256(contract),
        "runtime_identity_sha256": sha256_bytes(canonical_json_bytes(runtime)),
        "source": dict(source),
    }
    process = validate_process_receipt(process)
    write_exclusive(args.process_receipt_output, pretty_json_bytes(process))
    controller.run(adapter, stop_after=1)
    recovery_receipt = None
    if recovery:
        recovery_receipt = {
            "schema": RECOVERY_RECEIPT_SCHEMA,
            "run_id": spec["run_id"],
            "checkpoint_id": args.checkpoint_id,
            "checkpoint_sha256": checkpoint["content_sha256"],
            "freeze_sha256": freeze_sha256(contract),
            "source_process_id": source_process["process_identity"]["instance_id"],
            "recovery_process_id": process_identity["instance_id"],
            "fresh_adapter": True,
            "model_loaded": True,
            "optimizer_scheduler_rng_data_equal": True,
            "no_update": True,
            "checkpoint_reuse_verified": True,
        }
    write_exclusive(args.state_output, pretty_json_bytes(controller.state))
    if recovery_receipt is not None:
        write_exclusive(
            args.recovery_receipt_output, pretty_json_bytes(recovery_receipt)
        )
    return {
        "summary": controller.archive_summary(),
        "process_receipt": process,
        "recovery_receipt": recovery_receipt,
        "data": dict(data),
    }


def validate_process_receipt(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema",
            "process_identity",
            "source_process_id",
            "status",
            "global_step",
            "run_id",
            "freeze_sha256",
            "runtime_identity_sha256",
            "source",
        }
        or value.get("schema") != PROCESS_RECEIPT_SCHEMA
        or value.get("status") != "started"
        or value.get("global_step") not in {0, 1}
        or value.get("run_id") not in TRAINING_RUNS
        or not _sha256(value.get("freeze_sha256"))
        or not _sha256(value.get("runtime_identity_sha256"))
        or not isinstance(value.get("source"), Mapping)
        or not _commit(value["source"].get("commit"))
        or (
            value.get("source_process_id") is not None
            and not _identifier(value["source_process_id"])
        )
    ):
        raise FullModelTrainingError("plan090_process_receipt_invalid")
    validate_process_identity(value.get("process_identity"))
    if (value["global_step"] == 0) != (value["source_process_id"] is None):
        raise FullModelTrainingError("plan090_process_receipt_invalid")
    return json.loads(json.dumps(value))


def _new_adapter(snapshot: Path, model_lock: Path, recipe: Mapping[str, Any]) -> Any:
    return Plan090TorchTrainingAdapter.from_snapshot(
        snapshot_root=snapshot, model_lock_path=model_lock, recipe=recipe
    )


def _authorize_run_boundary(
    args: Any,
    *,
    recovery: bool,
    contract: Mapping[str, Any],
    spec: Mapping[str, Any],
    budget: Mapping[str, Any],
) -> None:
    if (
        budget.get("complete_branch_authorized") is not True
        or budget.get("projected_complete_branch_usd", 0.0) <= 0.0
    ):
        raise FullModelTrainingError("plan090_run_budget_not_authorized")
    if recovery:
        return
    prior = [read_json(path) for path in args.prior_run_result]
    decision = next_action(
        contract,
        prior,
        fp32_budget_snapshot=(budget if len(prior) == 2 else None),
    )
    if decision.get("action") != "run" or decision.get("run_id") != spec["run_id"]:
        raise FullModelTrainingError("plan090_run_branch_not_authorized")
    prior_budgets = [
        validate_budget_snapshot(item.get("launch_budget_snapshot")) for item in prior
    ]
    for item in prior_budgets:
        _require_budget_continuity(item, budget)


def _require_budget_continuity(
    earlier: Mapping[str, Any], later: Mapping[str, Any]
) -> None:
    if (
        earlier["stage_b_baseline_balance_usd"] != later["stage_b_baseline_balance_usd"]
        or earlier["stage_b_baseline_known_unsettled_usd"]
        != later["stage_b_baseline_known_unsettled_usd"]
        or later["conservative_task_cost_usd"] + 1e-12
        < earlier["conservative_task_cost_usd"]
    ):
        raise FullModelTrainingError("plan090_run_budget_history_invalid")


def _preflight_run_outputs(
    args: Any, *, recovery: bool, run_spec: Mapping[str, Any]
) -> None:
    artifact = Path(args.artifact_root)
    if recovery:
        if artifact.is_symlink() or not artifact.is_dir():
            raise FullModelTrainingError("plan090_segment_artifact_root_invalid")
    elif artifact.exists() or artifact.is_symlink():
        raise FullModelTrainingError("plan090_segment_artifact_root_conflict")
    outputs = [Path(args.state_output), Path(args.process_receipt_output)]
    if recovery:
        outputs.append(Path(args.recovery_receipt_output))
    _require_task_owned_paths(artifact, *outputs)
    resolved_artifact = artifact.resolve(strict=False)
    configured_root = safe_directory(Path(os.environ["RONDO_PLAN090_TASK_ROOT"]))
    expected_artifact = (
        configured_root / run_spec["artifact_namespace"] / "artifacts"
    ).resolve(strict=False)
    if resolved_artifact != expected_artifact:
        raise FullModelTrainingError("plan090_artifact_namespace_mismatch")
    resolved_outputs: list[Path] = []
    for output in outputs:
        if output.exists() or output.is_symlink():
            raise FullModelTrainingError("plan090_segment_output_conflict")
        resolved = output.resolve(strict=False)
        if _paths_alias(resolved, resolved_artifact) or any(
            _paths_alias(resolved, previous) for previous in resolved_outputs
        ):
            raise FullModelTrainingError("plan090_segment_output_alias_invalid")
        resolved_outputs.append(resolved)


def _verify_executing_source(
    *, source_archive: Path, source_root: Path, receipt_path: Path
) -> dict[str, Any]:
    expected = read_json(receipt_path)
    if not isinstance(expected, dict) or not _commit(expected.get("commit")):
        raise FullModelTrainingError("plan090_source_receipt_invalid")
    try:
        root = Path(source_root).resolve(strict=True)
    except OSError as exc:
        raise FullModelTrainingError("plan090_source_root_unavailable") from exc
    if root != Path(__file__).resolve().parents[4]:
        raise FullModelTrainingError("plan090_executing_source_root_mismatch")
    observed = verify_source_archive(
        source_archive,
        root,
        exact_tree=True,
        expected_commit=expected["commit"],
    )
    if observed != expected:
        raise FullModelTrainingError("plan090_source_receipt_mismatch")
    return observed


def _require_task_owned_if_configured(*paths: Path) -> None:
    if os.getenv("RONDO_PLAN090_TASK_ROOT"):
        _require_task_owned_paths(*paths)


def _record_optional_receipt(value: Any, output: Path | None) -> Any:
    if output is not None:
        _require_task_owned_if_configured(output)
        write_exclusive(output, pretty_json_bytes(value))
    return value


def _require_task_owned_paths(*paths: Path) -> None:
    raw = os.getenv("RONDO_PLAN090_TASK_ROOT")
    if not raw:
        raise FullModelTrainingError("plan090_task_root_required")
    task_root = _validated_plan090_task_root(Path(raw))
    for path in paths:
        candidate = path if path.is_absolute() else Path.cwd() / path
        _reject_existing_symlink_chain(candidate)
        resolved = candidate.resolve(strict=False)
        if resolved == task_root or not resolved.is_relative_to(task_root):
            raise FullModelTrainingError("plan090_task_owned_path_required")


def _require_configured_task_root(path: Path) -> Path:
    raw = os.getenv("RONDO_PLAN090_TASK_ROOT")
    if not raw:
        raise FullModelTrainingError("plan090_task_root_required")
    configured = _validated_plan090_task_root(Path(raw))
    _reject_existing_symlink_chain(path)
    if safe_directory(path) != configured:
        raise FullModelTrainingError("plan090_task_root_mismatch")
    return configured


def _validated_plan090_task_root(path: Path) -> Path:
    _reject_existing_symlink_chain(path)
    root = safe_directory(path)
    prefix = "rondo-plan090-"
    if not root.name.startswith(prefix) or len(root.name) == len(prefix):
        raise FullModelTrainingError("plan090_task_root_namespace_invalid")
    return root


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
            raise FullModelTrainingError("plan090_task_path_inspection_failed") from exc
        if stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan090_task_path_symlink_rejected")


def _parse_handoff_entry(value: str) -> tuple[str, str]:
    role, separator, relative_path = value.partition("=")
    if not separator or not role or not relative_path:
        raise FullModelTrainingError("plan090_handoff_entry_invalid")
    return role, relative_path


def _paths_alias(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _process_identity() -> dict[str, Any]:
    return {
        "instance_id": uuid.uuid4().hex,
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
    }


def _require_new_process(source: Mapping[str, Any], current: Mapping[str, Any]) -> None:
    left = validate_process_identity(source)
    right = validate_process_identity(current)
    if (
        left["hostname"] != right["hostname"]
        or left["instance_id"] == right["instance_id"]
        or left["pid"] == right["pid"]
    ):
        raise FullModelTrainingError("plan090_recovery_process_not_new")


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _commit(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


if __name__ == "__main__":
    raise SystemExit(main())
