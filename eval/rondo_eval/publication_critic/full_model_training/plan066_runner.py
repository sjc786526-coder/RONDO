"""Plan 066 orchestration on top of the qualified Plan 060 runtime."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from . import runner as common
from .checkpoint import (
    current_process_identity,
    load_training_state,
    read_checkpoint_metadata,
    require_new_process,
    restore_rng_state,
    save_full_checkpoint,
    verify_checkpoint,
)
from .contract import (
    FullModelTrainingError,
    STAGES,
    pretty_json_bytes,
    read_json,
    sha256_file,
    utc_now,
    write_exclusive,
)
from .plan066_artifacts import run_validation, save_stage_candidate
from .plan066_contract import (
    validate_plan066_resume_receipt,
    validate_plan066_start_receipt,
)
from .plan066_data import load_plan066_datasets, tokenize_validation


COMMISSIONING_START_RECEIPT = "plan066-commissioning-start.json"
COMMISSIONING_RESUME_RECEIPT = "plan066-commissioning-resume.json"
FORMAL_START_RECEIPT = "plan066-formal-start.json"
FORMAL_PENDING_RECEIPT = "plan066-formal-pending.json"


def run_plan066_commissioning_start(
    *,
    bundle_root: Path,
    model_snapshot: Path,
    output_root: Path,
    recipe_path: Path,
    winner_lock_path: Path,
    container_image: str,
) -> dict[str, Any]:
    process_started = time.perf_counter()
    context = common._prepare_run(
        bundle_root=bundle_root,
        model_snapshot=model_snapshot,
        recipe_path=recipe_path,
        winner_lock_path=winner_lock_path,
        dependency_identity_path=None,
        dependency_freeze_path=None,
        container_image=container_image,
        formal=False,
        profile="plan066",
        data_role="commissioning",
    )
    output = common._new_output_root(output_root)
    process = current_process_identity()
    stages = [
        common._run_stage_update(context, stage, global_step=index)
        for index, stage in enumerate(STAGES, start=1)
    ]
    progress = common._progress("C3", 3, list(STAGES), context.dataset.stage("C3"))
    optimizer_checkpoint, optimizer_state = common._prepare_optimizer_for_checkpoint(
        context.optimizer,
        check_numerics=bool(context.optimizer_contract["check_numerics"]),
        expected_state_entries=int(context.coverage["optimizer_parameter_tensors"]),
        expected_step=3,
    )
    checkpoint_started = time.perf_counter()
    checkpoint = save_full_checkpoint(
        output / "checkpoint-c3",
        model=context.model,
        tokenizer=context.tokenizer,
        optimizer=context.optimizer,
        scheduler=context.scheduler,
        progress=progress,
        identity=context.identity,
        process_identity=process,
        optimizer_state=optimizer_state,
    )
    checkpoint_seconds = time.perf_counter() - checkpoint_started
    receipt = {
        "schema": "rondo-publication-critic-plan066-commissioning-start-v1",
        "status": "commissioning_only_pending_new_process_resume",
        "created_at": utc_now(),
        "process": process.as_dict(),
        "identity": context.identity,
        "coverage": context.coverage,
        "stages": stages,
        "checkpoint": checkpoint,
        "optimizer_pre_checkpoint": optimizer_checkpoint,
        "global_step": 3,
        "resume_required": {"stage": "C3", "updates": 1, "new_os_process": True},
        "timing": common._start_timing(
            process_started=process_started,
            context=context,
            stages=stages,
            checkpoint_save_seconds=checkpoint_seconds,
            optimizer_checkpoint=optimizer_checkpoint,
        ),
    }
    common._validate_winner_bound_receipt(receipt)
    validate_plan066_start_receipt(receipt, formal=False)
    write_exclusive(output / COMMISSIONING_START_RECEIPT, pretty_json_bytes(receipt))
    return receipt


def run_plan066_commissioning_resume(
    *,
    bundle_root: Path,
    model_snapshot: Path,
    output_root: Path,
    checkpoint_root: Path,
    recipe_path: Path,
    winner_lock_path: Path,
    container_image: str,
) -> dict[str, Any]:
    return _run_resume(
        bundle_root=bundle_root,
        model_snapshot=model_snapshot,
        output_root=output_root,
        checkpoint_root=checkpoint_root,
        recipe_path=recipe_path,
        winner_lock_path=winner_lock_path,
        dependency_identity_path=None,
        dependency_freeze_path=None,
        container_image=container_image,
        formal=False,
    )


def run_plan066_formal_start(
    *,
    bundle_root: Path,
    model_snapshot: Path,
    output_root: Path,
    recipe_path: Path,
    winner_lock_path: Path,
    dependency_identity_path: Path,
    dependency_freeze_path: Path,
    container_image: str,
) -> dict[str, Any]:
    process_started = time.perf_counter()
    context = common._prepare_run(
        bundle_root=bundle_root,
        model_snapshot=model_snapshot,
        recipe_path=recipe_path,
        winner_lock_path=winner_lock_path,
        dependency_identity_path=dependency_identity_path,
        dependency_freeze_path=dependency_freeze_path,
        container_image=container_image,
        formal=True,
        profile="plan066",
        data_role="formal",
    )
    datasets = load_plan066_datasets(bundle_root)
    if context.identity.get("data_export_sha256") != datasets.export_sha256:
        raise FullModelTrainingError("plan066_formal_data_identity_mismatch")
    validation_tokenized = tokenize_validation(datasets.validation, context.exact_tokenizer)
    output = common._new_output_root(output_root)
    process = current_process_identity()
    stages: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    validations: list[dict[str, Any]] = []
    for global_step, stage in enumerate(STAGES, start=1):
        stages.append(common._run_stage_update(context, stage, global_step=global_step))
        candidates.append(
            save_stage_candidate(
                output / f"candidate-{stage.casefold()}",
                model=context.model,
                tokenizer=context.tokenizer,
                stage=stage,
                global_step=global_step,
                identity=context.identity,
            )
        )
        validations.append(
            run_validation(
                context,
                datasets.validation,
                validation_tokenized,
                stage=stage,
            )
        )
    progress = common._progress("C3", 3, list(STAGES), context.dataset.stage("C3"))
    optimizer_checkpoint, optimizer_state = common._prepare_optimizer_for_checkpoint(
        context.optimizer,
        check_numerics=bool(context.optimizer_contract["check_numerics"]),
        expected_state_entries=int(context.coverage["optimizer_parameter_tensors"]),
        expected_step=3,
    )
    checkpoint_started = time.perf_counter()
    checkpoint = save_full_checkpoint(
        output / "checkpoint-c3",
        model=context.model,
        tokenizer=context.tokenizer,
        optimizer=context.optimizer,
        scheduler=context.scheduler,
        progress=progress,
        identity=context.identity,
        process_identity=process,
        optimizer_state=optimizer_state,
    )
    checkpoint_seconds = time.perf_counter() - checkpoint_started
    timing = common._start_timing(
        process_started=process_started,
        context=context,
        stages=stages,
        checkpoint_save_seconds=checkpoint_seconds,
        optimizer_checkpoint=optimizer_checkpoint,
    )
    timing["candidate_save_seconds"] = {
        item["stage"]: float(item["save_seconds"]) for item in candidates
    }
    timing["validation_seconds"] = {
        item["stage"]: float(item["elapsed_seconds"]) for item in validations
    }
    receipt = {
        "schema": "rondo-publication-critic-plan066-formal-start-v1",
        "status": "pending_new_process_resume",
        "created_at": utc_now(),
        "process": process.as_dict(),
        "identity": context.identity,
        "coverage": context.coverage,
        "stages": stages,
        "candidates": candidates,
        "validation": validations,
        "holdout": {
            "validation_gradient_access": False,
            "validation_feeds_training_decisions": False,
            "unseen_test_exported": False,
            "unseen_test_run": False,
        },
        "checkpoint": checkpoint,
        "optimizer_pre_checkpoint": optimizer_checkpoint,
        "global_step": 3,
        "resume_required": {
            "stage": "C3",
            "updates": 1,
            "new_os_process": True,
            "data_role": "v8_commissioning_smoke",
            "does_not_replace_formal_candidate": True,
        },
        "timing": timing,
    }
    common._validate_winner_bound_receipt(receipt)
    validate_plan066_start_receipt(receipt, formal=True)
    write_exclusive(output / FORMAL_START_RECEIPT, pretty_json_bytes(receipt))
    return receipt


def run_plan066_formal_resume(
    *,
    bundle_root: Path,
    model_snapshot: Path,
    output_root: Path,
    checkpoint_root: Path,
    recipe_path: Path,
    winner_lock_path: Path,
    dependency_identity_path: Path,
    dependency_freeze_path: Path,
    container_image: str,
) -> dict[str, Any]:
    return _run_resume(
        bundle_root=bundle_root,
        model_snapshot=model_snapshot,
        output_root=output_root,
        checkpoint_root=checkpoint_root,
        recipe_path=recipe_path,
        winner_lock_path=winner_lock_path,
        dependency_identity_path=dependency_identity_path,
        dependency_freeze_path=dependency_freeze_path,
        container_image=container_image,
        formal=True,
    )


def _run_resume(
    *,
    bundle_root: Path,
    model_snapshot: Path,
    output_root: Path,
    checkpoint_root: Path,
    recipe_path: Path,
    winner_lock_path: Path,
    dependency_identity_path: Path | None,
    dependency_freeze_path: Path | None,
    container_image: str,
    formal: bool,
) -> dict[str, Any]:
    process_started = time.perf_counter()
    output = Path(output_root)
    if not output.is_dir() or output.is_symlink():
        raise FullModelTrainingError("plan066_output_missing")
    expected_checkpoint = output / "checkpoint-c3"
    try:
        if Path(checkpoint_root).resolve(strict=True) != expected_checkpoint.resolve(strict=True):
            raise FullModelTrainingError("plan066_checkpoint_namespace_mismatch")
    except OSError as exc:
        raise FullModelTrainingError("plan066_checkpoint_namespace_mismatch") from exc
    receipt_name = FORMAL_PENDING_RECEIPT if formal else COMMISSIONING_RESUME_RECEIPT
    if (output / receipt_name).exists():
        raise FullModelTrainingError("plan066_resume_already_completed")
    start_name = FORMAL_START_RECEIPT if formal else COMMISSIONING_START_RECEIPT
    start_path = output / start_name
    start_receipt = validate_plan066_start_receipt(read_json(start_path), formal=formal)
    start_sha256 = sha256_file(start_path)
    verify_started = time.perf_counter()
    checkpoint_verification = verify_checkpoint(checkpoint_root)
    checkpoint_verify_seconds = time.perf_counter() - verify_started
    metadata = read_checkpoint_metadata(checkpoint_root)
    resume_process = require_new_process(metadata)
    datasets = load_plan066_datasets(bundle_root)
    expected_dataset = datasets.train if formal else datasets.commissioning
    common._require_expected_resume_progress(metadata, expected_dataset)
    context = common._prepare_run(
        bundle_root=bundle_root,
        model_snapshot=model_snapshot,
        recipe_path=recipe_path,
        winner_lock_path=winner_lock_path,
        dependency_identity_path=dependency_identity_path,
        dependency_freeze_path=dependency_freeze_path,
        container_image=container_image,
        formal=formal,
        checkpoint_model_root=Path(checkpoint_root) / "full-model/model",
        profile="plan066",
        data_role="formal" if formal else "commissioning",
    )
    if metadata.get("identity") != context.identity:
        raise FullModelTrainingError("plan066_resume_identity_mismatch")
    if (
        start_receipt.get("identity") != context.identity
        or start_receipt.get("coverage") != context.coverage
        or start_receipt.get("process") != metadata.get("process")
        or start_receipt.get("checkpoint", {}).get("checkpoint_manifest_sha256")
        != checkpoint_verification.get("checkpoint_manifest_sha256")
    ):
        raise FullModelTrainingError("plan066_start_checkpoint_binding_mismatch")
    load_started = time.perf_counter()
    training_state = load_training_state(
        checkpoint_root, verified_receipt=checkpoint_verification
    )
    state_load_seconds = time.perf_counter() - load_started
    restore_started = time.perf_counter()
    try:
        context.optimizer.load_state_dict(training_state["optimizer"])
        context.scheduler.load_state_dict(training_state["scheduler"])
    except Exception as exc:
        raise FullModelTrainingError("plan066_flashadamw_restore_failed") from exc
    restored_optimizer_state = common._validate_flashadamw_compressed_state_dict(
        training_state["optimizer"],
        expected_state_entries=int(context.coverage["optimizer_parameter_tensors"]),
        expected_step=3,
        optimizer=context.optimizer,
    )
    restored_optimizer_runtime = common._validate_flashadamw_runtime_state(
        context.optimizer,
        expected_state_entries=int(context.coverage["optimizer_parameter_tensors"]),
        expected_step=3,
    )
    restore_rng_state(training_state["rng"])
    state_restore_seconds = time.perf_counter() - restore_started
    # Formal recovery is intentionally bounded to the frozen v8 6/2 smoke.
    # The checkpoint cursor was already matched against the full 128/58 run.
    if formal:
        from .data import tokenize_dataset

        context.dataset = datasets.commissioning
        context.tokenized = tokenize_dataset(datasets.commissioning, context.exact_tokenizer)
    stage_receipt = common._run_stage_update(context, "C3", global_step=4)
    timing = common._resume_timing(
        process_started=process_started,
        context=context,
        checkpoint_verify_seconds=checkpoint_verify_seconds,
        checkpoint_state_load_seconds=state_load_seconds,
        state_restore_seconds=state_restore_seconds,
        continued_stage=stage_receipt,
    )
    receipt: dict[str, Any] = {
        "schema": (
            "rondo-publication-critic-plan066-formal-pending-v1"
            if formal
            else "rondo-publication-critic-plan066-commissioning-resume-v1"
        ),
        "status": (
            "pending_billing_and_resource_cleanup"
            if formal
            else "commissioning_only_complete_not_formal_evidence"
        ),
        "created_at": utc_now(),
        "identity": context.identity,
        "start_process": metadata["process"],
        "resume_process": resume_process.as_dict(),
        "new_os_process_confirmed": metadata["process"]["pid"] != resume_process.pid,
        "restored_from_global_step": 3,
        "continued_global_step": 4,
        "continued_stage": stage_receipt,
        "coverage": context.coverage,
        "restored_optimizer_state": restored_optimizer_state,
        "restored_optimizer_runtime": restored_optimizer_runtime,
        "checkpoint": checkpoint_verification,
        "timing": timing,
    }
    if formal:
        receipt.update(
            {
                "continued_data": {
                    "data_role": "v8_commissioning_smoke",
                    "binary_candidates": 6,
                    "boundary_pairs": 1,
                    "within_pass_pairs": 1,
                    "does_not_replace_formal_candidate": True,
                    "membership_sha256": context.identity["resume_probe"][
                        "membership_sha256"
                    ],
                },
                "formal_start_receipt_sha256": start_sha256,
                "billing": None,
                "remote_resource_terminal_state": None,
                "qualification_conclusion": None,
            }
        )
    common._validate_winner_bound_receipt(receipt)
    validate_plan066_resume_receipt(receipt, formal=formal)
    write_exclusive(output / receipt_name, pretty_json_bytes(receipt))
    return receipt
