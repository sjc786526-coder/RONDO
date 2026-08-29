"""Narrow Phase-A/Phase-B command surface for Plan 099."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..tokenization import ExactTokenizer
from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    sha256_bytes,
    sha256_file,
)
from .plan082_adapter import verify_snapshot
from .plan099_artifacts import Plan099ArtifactStore
from .plan099_bundle import (
    assemble_execution_root,
    create_data_archive,
    create_source_archive,
)
from .plan099_contract import (
    MINIMUM_L40S_VISIBLE_MEMORY_BYTES,
    REPO_ROOT,
    authorize_paid_segment,
    authorize_pod_lifecycle,
    create_budget_snapshot,
    create_live_resource_receipt,
    freeze_sha256,
    load_freeze,
    validate_budget_snapshot,
    validate_namespace,
    validate_runtime_control_chain,
    validate_runtime_control_file,
    validate_source_identity,
)
from .plan099_data import (
    commissioning_dataset,
    load_train_dataset,
    load_validation_dataset,
    tokenize_dataset,
)
from .plan099_model import verify_inference_ready
from .plan099_training import (
    Plan099TorchAdapter,
    Plan099TrainingController,
    validate_terminal_candidate,
)

STAGE_B_APPROVAL_PHRASE = "Plan 099 阶段 A 验收通过，批准进入阶段 B"
CANDIDATE_MANIFEST_SCHEMA = "rondo-publication-critic-plan099-candidate-manifest-v1"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publication-critic-plan099")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("validate-freeze")
    assemble = commands.add_parser("assemble-execution-root")
    assemble.add_argument("--source-archive", type=Path, required=True)
    assemble.add_argument("--data-archive", type=Path, required=True)
    assemble.add_argument("--source-sha256", required=True)
    assemble.add_argument("--data-sha256", required=True)
    assemble.add_argument("--commit", required=True)
    assemble.add_argument("--output", type=Path, required=True)
    assemble.add_argument("--identity-output", type=Path, required=True)
    source = commands.add_parser("create-source-archive")
    source.add_argument("--repo", type=Path, required=True)
    source.add_argument("--commit", required=True)
    source.add_argument("--output", type=Path, required=True)
    source.add_argument("--receipt-output", type=Path, required=True)
    data = commands.add_parser("create-data-archive")
    data.add_argument("--repo", type=Path, required=True)
    data.add_argument("--commit", required=True)
    data.add_argument("--output", type=Path, required=True)
    data.add_argument("--receipt-output", type=Path, required=True)

    create_budget = commands.add_parser("create-budget-snapshot")
    create_budget.add_argument("--captured-at", required=True)
    create_budget.add_argument(
        "--baseline-available-balance-usd", type=float, required=True
    )
    create_budget.add_argument(
        "--baseline-known-unsettled-usd", type=float, required=True
    )
    create_budget.add_argument(
        "--baseline-volume-rate-usd-per-hour", type=float, required=True
    )
    create_budget.add_argument(
        "--current-available-balance-usd", type=float, required=True
    )
    create_budget.add_argument(
        "--current-known-unsettled-usd", type=float, required=True
    )
    create_budget.add_argument(
        "--current-volume-rate-usd-per-hour", type=float, required=True
    )
    create_budget.add_argument(
        "--conservative-task-cost-usd", type=float, required=True
    )
    create_budget.add_argument("--closure-reserve-usd", type=float, required=True)
    create_budget.add_argument("--next-action", required=True)
    create_budget.add_argument("--output", type=Path, required=True)
    resource = commands.add_parser("create-live-resource-receipt")
    resource.add_argument("--captured-at", required=True)
    resource.add_argument("--provider", required=True)
    resource.add_argument("--cloud-type", required=True)
    resource.add_argument("--data-center-id", required=True)
    resource.add_argument("--pod-id", required=True)
    resource.add_argument("--pod-name", required=True)
    resource.add_argument("--pod-started-at", required=True)
    resource.add_argument("--account-task-pod-count", type=int, required=True)
    resource.add_argument("--task-cumulative-pods-created", type=int, required=True)
    resource.add_argument("--task-prior-pod-wall-seconds", type=int, required=True)
    resource.add_argument("--gpu-name", required=True)
    resource.add_argument("--gpu-count", type=int, required=True)
    resource.add_argument("--gpu-total-memory-bytes", type=int, required=True)
    resource.add_argument("--compute-rate-usd-per-hour", type=float, required=True)
    resource.add_argument("--container-rate-usd-per-hour", type=float, required=True)
    resource.add_argument("--container-disk-gb", type=int, required=True)
    resource.add_argument("--image-identity", required=True)
    resource.add_argument("--volume-id", required=True)
    resource.add_argument("--volume-mount-path", required=True)
    resource.add_argument("--volume-size-gb", type=float, required=True)
    resource.add_argument("--output", type=Path, required=True)
    budget = commands.add_parser("validate-budget")
    budget.add_argument("--snapshot", type=Path, required=True)
    lifecycle = commands.add_parser("authorize-lifecycle")
    lifecycle.add_argument("--snapshot", type=Path, required=True)
    lifecycle.add_argument("--resource-receipt", type=Path, required=True)
    lifecycle.add_argument("--maximum-lifecycle-seconds", type=int, required=True)
    lifecycle.add_argument("--output", type=Path, required=True)
    segment = commands.add_parser("authorize-segment")
    segment.add_argument("--snapshot", type=Path, required=True)
    segment.add_argument("--lifecycle-authorization", type=Path, required=True)
    segment.add_argument("--maximum-seconds", type=int, required=True)
    segment.add_argument("--output", type=Path, required=True)
    runtime = commands.add_parser("validate-runtime-controls")
    _run_arguments(runtime)
    environment = commands.add_parser("capture-environment")
    _run_arguments(environment)
    environment.add_argument("--output", type=Path, required=True)

    start = commands.add_parser("start")
    _run_arguments(start)
    start.add_argument("--snapshot", type=Path, required=True)
    start.add_argument("--source-identity", type=Path, required=True)
    start.add_argument("--run-kind", choices=("commissioning", "formal"), required=True)
    start.add_argument("--namespace", required=True)
    start.add_argument("--artifact-root", type=Path, required=True)
    start.add_argument("--state-output", type=Path, required=True)
    start.add_argument("--stop-after", type=int)
    start.add_argument("--commissioning-state", type=Path)
    start.add_argument("--environment-receipt", type=Path, required=True)

    resume = commands.add_parser("resume")
    _run_arguments(resume)
    resume.add_argument("--controller-state", type=Path, required=True)
    resume.add_argument("--artifact-root", type=Path, required=True)
    resume.add_argument("--state-output", type=Path, required=True)
    resume.add_argument("--stop-after", type=int)
    resume.add_argument("--environment-receipt", type=Path, required=True)

    export = commands.add_parser("export-candidate")
    _run_arguments(export)
    export.add_argument("--controller-state", type=Path, required=True)
    export.add_argument("--artifact-root", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify-inference-ready")
    verify.add_argument("--root", type=Path, required=True)
    snapshot = commands.add_parser("verify-snapshot")
    snapshot.add_argument("--root", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    verify_candidate = commands.add_parser("verify-candidate")
    verify_candidate.add_argument("--root", type=Path, required=True)
    return parser


def _run_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--segment-authorization", type=Path, required=True)
    parser.add_argument("--resource-receipt", type=Path, required=True)
    parser.add_argument("--lifecycle-authorization", type=Path, required=True)
    parser.add_argument("--reviewer-approval-phrase", required=True)


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    args = _parser().parse_args(argv)
    try:
        result = _dispatch(args)
    except (FullModelTrainingError, OSError, ValueError, json.JSONDecodeError) as exc:
        code = (
            exc.code if isinstance(exc, FullModelTrainingError) else type(exc).__name__
        )
        print(json.dumps({"status": "failed", "code": code}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "validate-freeze":
        freeze = load_freeze(REPO_ROOT)
        return {
            "status": "verified",
            "freeze_sha256": sha256_bytes(canonical_json_bytes(freeze)),
        }
    if args.command == "assemble-execution-root":
        if args.identity_output.exists() or args.identity_output.is_symlink():
            raise FullModelTrainingError("plan099_output_exists")
        result = assemble_execution_root(
            args.source_archive,
            args.data_archive,
            args.output,
            source_sha256=args.source_sha256,
            data_sha256=args.data_sha256,
            expected_commit=args.commit,
        )
        identity = validate_source_identity(
            {
                "commit": result["commit"],
                "source_archive_sha256": result["source_archive_sha256"],
                "freeze_sha256": result["freeze_sha256"],
            }
        )
        _write_exclusive(args.identity_output, identity)
        return result
    if args.command == "create-source-archive":
        receipt = create_source_archive(
            args.repo, args.output, source_commit=args.commit
        )
        _write_exclusive(args.receipt_output, receipt)
        return receipt
    if args.command == "create-data-archive":
        receipt = create_data_archive(args.repo, args.output, source_commit=args.commit)
        _write_exclusive(args.receipt_output, receipt)
        return receipt
    if args.command == "validate-budget":
        return validate_budget_snapshot(read_json(args.snapshot))
    if args.command == "create-budget-snapshot":
        snapshot = create_budget_snapshot(
            captured_at=args.captured_at,
            stage_b_baseline_available_balance_usd=args.baseline_available_balance_usd,
            stage_b_baseline_known_unsettled_usd=args.baseline_known_unsettled_usd,
            stage_b_baseline_volume_rate_usd_per_hour=args.baseline_volume_rate_usd_per_hour,
            current_available_balance_usd=args.current_available_balance_usd,
            current_known_unsettled_usd=args.current_known_unsettled_usd,
            current_volume_rate_usd_per_hour=args.current_volume_rate_usd_per_hour,
            conservative_task_cost_usd=args.conservative_task_cost_usd,
            closure_reserve_usd=args.closure_reserve_usd,
            next_action=args.next_action,
        )
        _write_exclusive(args.output, snapshot)
        return snapshot
    if args.command == "create-live-resource-receipt":
        receipt = create_live_resource_receipt(
            captured_at=args.captured_at,
            provider=args.provider,
            cloud_type=args.cloud_type,
            data_center_id=args.data_center_id,
            pod_id=args.pod_id,
            pod_name=args.pod_name,
            pod_started_at=args.pod_started_at,
            account_task_pod_count=args.account_task_pod_count,
            task_cumulative_pods_created=args.task_cumulative_pods_created,
            task_prior_pod_wall_seconds=args.task_prior_pod_wall_seconds,
            gpu_name=args.gpu_name,
            gpu_count=args.gpu_count,
            gpu_total_memory_bytes=args.gpu_total_memory_bytes,
            compute_rate_usd_per_hour=args.compute_rate_usd_per_hour,
            container_rate_usd_per_hour=args.container_rate_usd_per_hour,
            container_disk_gb=args.container_disk_gb,
            image_identity=args.image_identity,
            volume_id=args.volume_id,
            volume_mount_path=args.volume_mount_path,
            volume_size_gb=args.volume_size_gb,
        )
        _write_exclusive(args.output, receipt)
        return receipt
    if args.command == "authorize-lifecycle":
        receipt = authorize_pod_lifecycle(
            read_json(args.snapshot),
            read_json(args.resource_receipt),
            maximum_lifecycle_seconds=args.maximum_lifecycle_seconds,
        )
        _write_exclusive(args.output, receipt)
        return receipt
    if args.command == "authorize-segment":
        receipt = authorize_paid_segment(
            read_json(args.snapshot),
            read_json(args.lifecycle_authorization),
            maximum_seconds=args.maximum_seconds,
        )
        _write_exclusive(args.output, receipt)
        return receipt
    if args.command == "validate-runtime-controls":
        authorization = _require_stage_b(args)
        return {
            "status": "verified",
            "live_resource_receipt_sha256": authorization["resource"]["content_sha256"],
            "pod_lifecycle_authorization_sha256": authorization["lifecycle"][
                "content_sha256"
            ],
            "paid_segment_authorization_sha256": authorization["segment"][
                "content_sha256"
            ],
        }
    if args.command == "capture-environment":
        authorization = _require_stage_b(args)
        _scoped_new_path(args.output, _task_root())
        result = _capture_environment(authorization["resource"])
        _write_exclusive(args.output, result)
        return result
    if args.command == "start":
        authorization = _require_stage_b(args)
        freeze = load_freeze(REPO_ROOT)
        source = validate_source_identity(read_json(args.source_identity))
        if source["freeze_sha256"] != freeze_sha256(REPO_ROOT):
            raise FullModelTrainingError("plan099_source_freeze_mismatch")
        validate_namespace(args.namespace, run_kind=args.run_kind)
        task_root = _task_root()
        for path in (args.snapshot, args.source_identity, args.environment_receipt):
            _scoped_path(path, task_root, require_existing=True)
        _scoped_new_path(args.artifact_root, task_root)
        _scoped_path(args.state_output, task_root, require_existing=False)
        _require_run_layout(
            task_root,
            run_kind=args.run_kind,
            namespace=args.namespace,
            artifact_root=args.artifact_root,
            state_path=args.state_output,
        )
        if args.run_kind == "formal":
            _scoped_path(args.commissioning_state, task_root, require_existing=True)
            _require_commissioning_pass(args.commissioning_state, freeze, source)
        elif args.commissioning_state is not None:
            raise FullModelTrainingError("plan099_commissioning_receipt_unexpected")
        _validate_environment_receipt(
            read_json(args.environment_receipt),
            expected_resource=authorization["resource"],
        )
        train_dataset = load_train_dataset(REPO_ROOT)
        validation_dataset = load_validation_dataset(REPO_ROOT)
        tokenizer = _tokenizer(args.snapshot)
        train = tokenize_dataset(
            train_dataset,
            ExactTokenizer(tokenizer),
            model_input_identity=freeze["model"]["input"],
        )
        validation = tokenize_dataset(
            validation_dataset,
            ExactTokenizer(tokenizer),
            model_input_identity=freeze["model"]["input"],
        )
        adapter = Plan099TorchAdapter.from_snapshot(
            snapshot_root=args.snapshot,
            freeze=freeze,
            source_commit=source["commit"],
            train=train,
            validation=validation,
        )
        store = Plan099ArtifactStore(args.artifact_root)
        controller = Plan099TrainingController(
            freeze=freeze,
            run_kind=args.run_kind,
            namespace=args.namespace,
            source_identity=source,
            artifact_store=store,
            state_publisher=lambda value: _write_state(args.state_output, value),
        )
        controller.initialize(adapter, validation_dataset)
        training = (
            commissioning_dataset(train_dataset)
            if args.run_kind == "commissioning"
            else train_dataset
        )
        result = controller.run(
            adapter,
            training=training,
            validation=validation_dataset,
            stop_after=args.stop_after,
        )
        _write_state(args.state_output, result)
        return _brief(result)
    if args.command == "resume":
        authorization = _require_stage_b(args)
        freeze = load_freeze(REPO_ROOT)
        task_root = _task_root()
        for path in (
            args.controller_state,
            args.artifact_root,
            args.environment_receipt,
        ):
            _scoped_path(path, task_root, require_existing=True)
        _scoped_path(args.state_output, task_root, require_existing=False)
        state = read_json(args.controller_state)
        _require_run_layout(
            task_root,
            run_kind=str(state.get("run_kind")),
            namespace=str(state.get("namespace")),
            artifact_root=args.artifact_root,
            state_path=args.controller_state,
        )
        _validate_environment_receipt(
            read_json(args.environment_receipt),
            expected_resource=authorization["resource"],
        )
        store = Plan099ArtifactStore(args.artifact_root)
        controller = Plan099TrainingController.from_state(
            freeze=freeze,
            artifact_store=store,
            value=state,
            state_publisher=lambda value: _write_state(args.state_output, value),
        )
        checkpoint_id, orphan = _resume_checkpoint(state, store)
        model_root = (
            args.artifact_root / "recovery-checkpoints" / checkpoint_id / "payload"
        )
        train_dataset = load_train_dataset(REPO_ROOT)
        validation_dataset = load_validation_dataset(REPO_ROOT)
        adapter = Plan099TorchAdapter.from_recovery_checkpoint(
            model_root=model_root,
            freeze=freeze,
            source_commit=state["source_identity"]["commit"],
            train_dataset=train_dataset,
            validation_dataset=validation_dataset,
        )
        if orphan:
            controller.adopt_orphan_checkpoint(
                adapter,
                checkpoint_id=checkpoint_id,
                validation=validation_dataset,
            )
        elif state["status"] == "evaluation_pending":
            controller.recover_pending_evaluation(
                adapter, validation=validation_dataset
            )
        elif state["status"] == "recovery_required":
            controller.resume_fresh_process(
                adapter,
                checkpoint_id=checkpoint_id,
                validation=validation_dataset,
            )
        elif state["status"] != "paused":
            raise FullModelTrainingError("plan099_controller_not_resumable")
        else:
            controller.recover_latest_for_continuation(
                adapter,
                checkpoint_id=checkpoint_id,
                validation=validation_dataset,
            )
        if controller.state["status"] == "paused":
            training = (
                commissioning_dataset(train_dataset)
                if state["run_kind"] == "commissioning"
                else train_dataset
            )
            controller.run(
                adapter,
                training=training,
                validation=validation_dataset,
                stop_after=args.stop_after,
            )
        result = controller.summary()
        _write_state(args.state_output, result)
        return _brief(result)
    if args.command == "export-candidate":
        _require_stage_b(args)
        task_root = _task_root()
        for path in (args.controller_state, args.artifact_root):
            _scoped_path(path, task_root, require_existing=True)
        _scoped_new_path(args.output, task_root)
        return _export_candidate(
            read_json(args.controller_state), args.artifact_root, args.output
        )
    if args.command == "verify-inference-ready":
        return verify_inference_ready(args.root)
    if args.command == "verify-snapshot":
        receipt = verify_snapshot(
            args.root,
            REPO_ROOT
            / "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json",
        )
        _write_exclusive(args.output, receipt)
        return receipt
    if args.command == "verify-candidate":
        return verify_candidate_handoff(args.root)
    raise AssertionError(args.command)


def _resume_checkpoint(
    state: Mapping[str, Any], store: Plan099ArtifactStore
) -> tuple[str, bool]:
    """Select exactly the checkpoint justified by durable controller state."""

    status = state.get("status")
    if status == "paused":
        current_step = int(state.get("current_step", -1))
        later = [
            checkpoint_id
            for checkpoint_id in store.verified_checkpoint_ids()
            if int(checkpoint_id.rsplit("-", 1)[1]) > current_step
        ]
        if later:
            return later[-1], True
        checkpoint_id = state.get("latest_checkpoint_id")
    elif status == "evaluation_pending":
        checkpoint_id = state.get("pending_checkpoint_id")
    elif status == "recovery_required":
        checkpoint_id = state.get("recovery_checkpoint_id")
    else:
        raise FullModelTrainingError("plan099_controller_not_resumable")
    if not isinstance(checkpoint_id, str) or not checkpoint_id:
        raise FullModelTrainingError("plan099_resume_checkpoint_missing")
    return checkpoint_id, False


def _export_candidate(
    state: Mapping[str, Any], artifact_root: Path, output: Path
) -> dict[str, Any]:
    store = Plan099ArtifactStore(artifact_root)
    accepted = validate_terminal_candidate(state, store)
    checkpoint_id = accepted["checkpoint_id"]
    checkpoint = store.verify_checkpoint(checkpoint_id)
    evaluation = accepted["evaluation"]
    source = artifact_root / "recovery-checkpoints" / checkpoint_id / "payload"
    verify_inference_ready(source)
    if output.exists() or output.is_symlink():
        raise FullModelTrainingError("plan099_candidate_output_exists")
    output.mkdir(mode=0o700, parents=True)
    try:
        shutil.copytree(source, output / "inference-ready")
        (output / "decision-config.json").write_bytes(
            pretty_json_bytes(evaluation["decision_config"])
        )
        (output / "development-assessment.json").write_bytes(
            pretty_json_bytes(evaluation["assessment"])
        )
        (output / "recovery-receipt.json").write_bytes(
            pretty_json_bytes(accepted["recovery"])
        )
        (output / "controller-state.json").write_bytes(pretty_json_bytes(state))
        files = _tree_manifest(output, exclude={"manifest.json"})
        core = {
            "schema": CANDIDATE_MANIFEST_SCHEMA,
            "checkpoint_id": checkpoint_id,
            "checkpoint_content_sha256": checkpoint["content_sha256"],
            "inference_ready": verify_inference_ready(output / "inference-ready"),
            "decision_config_sha256": sha256_file(output / "decision-config.json"),
            "assessment_sha256": sha256_file(output / "development-assessment.json"),
            "recovery_receipt_sha256": sha256_file(output / "recovery-receipt.json"),
            "controller_state_sha256": sha256_file(output / "controller-state.json"),
            "files": files,
            "exact_tree_sha256": sha256_bytes(canonical_json_bytes(files)),
            "development_only": True,
            "qualification_claim": False,
        }
        manifest = {
            **core,
            "content_sha256": sha256_bytes(canonical_json_bytes(core)),
        }
        (output / "manifest.json").write_bytes(pretty_json_bytes(manifest))
        verified = verify_candidate_handoff(output)
        return {**manifest, "verification": verified}
    except BaseException:
        shutil.rmtree(output)
        raise


def _require_stage_b(args: argparse.Namespace) -> dict[str, Any]:
    if (
        os.getenv("RONDO_PLAN099_STAGE_B_APPROVED") != "1"
        or args.reviewer_approval_phrase != STAGE_B_APPROVAL_PHRASE
    ):
        raise FullModelTrainingError("plan099_stage_b_approval_required")
    task_root = _task_root()
    for path in (
        args.resource_receipt,
        args.lifecycle_authorization,
        args.segment_authorization,
    ):
        _scoped_path(path, task_root, require_existing=True)
    resource = validate_runtime_control_file(
        "live-resource", args.resource_receipt, task_root
    )
    lifecycle = validate_runtime_control_file(
        "lifecycle", args.lifecycle_authorization, task_root
    )
    segment = validate_runtime_control_file(
        "segment", args.segment_authorization, task_root
    )
    authorization = validate_runtime_control_chain(resource, lifecycle, segment)
    now = datetime.now(timezone.utc)
    authorized = datetime.fromisoformat(segment["authorized_at"].replace("Z", "+00:00"))
    termination = datetime.fromisoformat(
        segment["termination_trigger_at"].replace("Z", "+00:00")
    )
    if (
        os.getenv("RONDO_PLAN099_MAX_SECONDS") != str(segment["maximum_seconds"])
        or not -30.0 <= (now - authorized).total_seconds() <= 300.0
        or now >= termination
    ):
        raise FullModelTrainingError("plan099_stage_b_authorization_mismatch")
    return authorization


def verify_candidate_handoff(root: Path) -> dict[str, Any]:
    path = Path(root)
    manifest_path = path / "manifest.json"
    if path.is_symlink() or not path.is_dir() or not manifest_path.is_file():
        raise FullModelTrainingError("plan099_candidate_invalid")
    manifest = read_json(manifest_path)
    core = {key: value for key, value in manifest.items() if key != "content_sha256"}
    if (
        manifest.get("schema") != CANDIDATE_MANIFEST_SCHEMA
        or manifest.get("content_sha256") != sha256_bytes(canonical_json_bytes(core))
        or manifest.get("development_only") is not True
        or manifest.get("qualification_claim") is not False
        or manifest.get("files") != _tree_manifest(path, exclude={"manifest.json"})
        or manifest.get("exact_tree_sha256")
        != sha256_bytes(canonical_json_bytes(manifest["files"]))
    ):
        raise FullModelTrainingError("plan099_candidate_invalid")
    inference = verify_inference_ready(path / "inference-ready")
    state = read_json(path / "controller-state.json")
    recovery = read_json(path / "recovery-receipt.json")
    identity = read_json(path / "inference-ready/rondo-plan099-model-identity.json")
    if (
        inference != manifest.get("inference_ready")
        or sha256_file(path / "decision-config.json")
        != manifest.get("decision_config_sha256")
        or sha256_file(path / "development-assessment.json")
        != manifest.get("assessment_sha256")
        or sha256_file(path / "recovery-receipt.json")
        != manifest.get("recovery_receipt_sha256")
        or sha256_file(path / "controller-state.json")
        != manifest.get("controller_state_sha256")
        or state.get("freeze_sha256") != identity.get("freeze_sha256")
        or identity.get("freeze_sha256") != freeze_sha256(REPO_ROOT)
        or state.get("source_identity", {}).get("commit")
        != identity.get("source_commit")
        or recovery.get("checkpoint_id") != manifest.get("checkpoint_id")
        or recovery.get("reproduced") is not True
    ):
        raise FullModelTrainingError("plan099_candidate_binding_invalid")
    return {
        "schema": CANDIDATE_MANIFEST_SCHEMA,
        "status": "verified",
        "file_count": len(manifest["files"]) + 1,
        "total_bytes": sum(row["bytes"] for row in manifest["files"].values())
        + manifest_path.stat().st_size,
        "exact_tree_sha256": manifest["exact_tree_sha256"],
        "manifest_sha256": sha256_file(manifest_path),
    }


def _tree_manifest(root: Path, *, exclude: set[str]) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan099_candidate_nonregular_entry")
        relative = path.relative_to(root).as_posix()
        if relative not in exclude:
            files[relative] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return files


def _task_root() -> Path:
    raw = os.getenv("RONDO_PLAN099_TASK_ROOT", "")
    root = Path(raw).resolve(strict=True) if raw else Path("/")
    if not str(root).startswith("/workspace/rondo-plan099-") or root.is_symlink():
        raise FullModelTrainingError("plan099_task_root_invalid")
    return root


def _scoped_path(path: Path, root: Path, *, require_existing: bool) -> Path:
    candidate = Path(path).resolve(strict=require_existing)
    if candidate == root or root not in candidate.parents:
        raise FullModelTrainingError("plan099_path_outside_task_root")
    return candidate


def _scoped_new_path(path: Path, root: Path) -> Path:
    candidate = _scoped_path(path, root, require_existing=False)
    if candidate.exists() or candidate.is_symlink():
        raise FullModelTrainingError("plan099_output_exists")
    return candidate


def _require_run_layout(
    root: Path,
    *,
    run_kind: str,
    namespace: str,
    artifact_root: Path,
    state_path: Path,
) -> None:
    validate_namespace(namespace, run_kind=run_kind)
    run_root = root / run_kind / namespace
    if (
        Path(artifact_root).resolve(strict=False) != run_root / "artifacts"
        or Path(state_path).resolve(strict=False) != run_root / "controller-state.json"
    ):
        raise FullModelTrainingError("plan099_run_layout_invalid")


def _require_commissioning_pass(
    path: Path | None, freeze: Mapping[str, Any], source: Mapping[str, Any]
) -> None:
    if path is None:
        raise FullModelTrainingError("plan099_commissioning_pass_required")
    state = read_json(path)
    if (
        state.get("run_kind") != "commissioning"
        or state.get("status") != "terminal"
        or state.get("terminal", {}).get("disposition") != "COMMISSIONING-PASS"
        or state.get("freeze_sha256") != freeze_sha256(REPO_ROOT)
        or state.get("source_identity") != source
    ):
        raise FullModelTrainingError("plan099_commissioning_pass_required")


def _validate_environment_receipt(
    value: Any, *, expected_resource: Mapping[str, Any]
) -> dict[str, Any]:
    required = {
        "schema",
        "python",
        "torch",
        "cuda",
        "transformers",
        "tokenizers",
        "huggingface_hub",
        "safetensors",
        "psutil",
        "gpu_name",
        "gpu_count",
        "gpu_total_memory_bytes",
        "image_identity",
        "live_resource_receipt_sha256",
        "pod_id",
        "pod_name",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise FullModelTrainingError("plan099_environment_receipt_invalid")
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    if (
        value.get("schema") != "rondo-publication-critic-plan099-environment-receipt-v1"
        or value.get("content_sha256") != sha256_bytes(canonical_json_bytes(core))
        or not str(value.get("python", "")).startswith("3.12.")
        or value.get("torch") != "2.8.0+cu128"
        or value.get("cuda") != "12.8"
        or value.get("transformers") != "4.52.3"
        or value.get("tokenizers") != "0.21.4"
        or value.get("huggingface_hub") != "0.36.2"
        or value.get("safetensors") != "0.5.3"
        or value.get("psutil") != "7.0.0"
        or value.get("gpu_name") != "NVIDIA L40S"
        or value.get("gpu_count") != 1
        or value.get("gpu_total_memory_bytes", 0) < MINIMUM_L40S_VISIBLE_MEMORY_BYTES
        or value.get("image_identity")
        != "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
        or value.get("live_resource_receipt_sha256")
        != expected_resource.get("content_sha256")
        or value.get("pod_id") != expected_resource.get("pod_id")
        or value.get("pod_name") != expected_resource.get("pod_name")
    ):
        raise FullModelTrainingError("plan099_environment_receipt_invalid")
    return json.loads(json.dumps(value))


def _tokenizer(snapshot: Path) -> Any:
    try:
        import transformers
    except ImportError as exc:
        raise FullModelTrainingError("plan099_transformers_dependency_missing") from exc
    return transformers.AutoTokenizer.from_pretrained(
        snapshot, local_files_only=True, trust_remote_code=False
    )


def _capture_environment(resource: Mapping[str, Any]) -> dict[str, Any]:
    import platform

    try:
        import huggingface_hub
        import psutil
        import safetensors
        import tokenizers
        import torch
        import transformers
    except ImportError as exc:
        raise FullModelTrainingError("plan099_training_dependency_missing") from exc
    if (
        not torch.cuda.is_available()
        or int(torch.cuda.device_count()) != 1
        or str(torch.cuda.get_device_name(0)) != "NVIDIA L40S"
    ):
        raise FullModelTrainingError("plan099_exact_gpu_required")
    expected_image = "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
    if os.getenv("RONDO_PLAN099_IMAGE_IDENTITY") != expected_image:
        raise FullModelTrainingError("plan099_image_identity_invalid")
    core = {
        "schema": "rondo-publication-critic-plan099-environment-receipt-v1",
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "cuda": str(torch.version.cuda),
        "transformers": str(transformers.__version__),
        "tokenizers": str(tokenizers.__version__),
        "huggingface_hub": str(huggingface_hub.__version__),
        "safetensors": str(safetensors.__version__),
        "psutil": str(psutil.__version__),
        "gpu_name": str(torch.cuda.get_device_name(0)),
        "gpu_count": int(torch.cuda.device_count()),
        "gpu_total_memory_bytes": int(torch.cuda.get_device_properties(0).total_memory),
        "image_identity": expected_image,
        "live_resource_receipt_sha256": resource["content_sha256"],
        "pod_id": resource["pod_id"],
        "pod_name": resource["pod_name"],
    }
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise FullModelTrainingError("plan099_output_exists")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(pretty_json_bytes(value))
    path.chmod(0o600)


def _write_state(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(pretty_json_bytes(value))
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _brief(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": value["schema"],
        "run_kind": value["run_kind"],
        "namespace": value["namespace"],
        "status": value["status"],
        "current_step": value["current_step"],
        "best_checkpoint_id": value["selection"]["best_checkpoint_id"],
        "recovery_checkpoint_id": value.get("recovery_checkpoint_id"),
        "terminal": value.get("terminal"),
    }


if __name__ == "__main__":
    raise SystemExit(main())
