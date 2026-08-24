"""Authorized single-GPU BF16/FlashAdamW qualification runner.

This module remains importable without the ML stack. Heavy dependencies are
loaded only after a training command has verified its portable bundle and
frozen run contracts.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import stat
import time
from typing import Any

from ..tokenization import ExactTokenizer
from .bundle import verify_bundle
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
    DEPENDENCY_SCHEMA,
    FullModelTrainingError,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    STAGES,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    resume_receipt_evidence_matches_coverage,
    sha256_bytes,
    sha256_file,
    start_receipt_evidence_matches_coverage,
    utc_now,
    validate_dependency_identity,
    validate_formal_pending_receipt,
    validate_formal_start_receipt,
    valid_checkpoint_receipt,
    valid_full_parameter_coverage,
    valid_global_numerics_preflight,
    validate_recipe,
    valid_stage_receipt,
    write_exclusive,
)
from .data import PortableTrainingDataset, load_portable_dataset, tokenize_dataset
from .objective import binary_loss, extract_raw_scalar, pair_loss


MODEL_CONTRACT_RELATIVE = "training/publication-critic-plan060/model-contract-v1.json"
RECIPE_RELATIVE = "training/publication-critic-plan060/recipe-candidate-v1.json"
FORMAL_START_RECEIPT = "formal-start-receipt.json"
FORMAL_PENDING_RECEIPT = "formal-training-pending.json"
COMMISSIONING_START_RECEIPT = "commissioning-start-receipt.json"
COMMISSIONING_RESUME_RECEIPT = "commissioning-resume-receipt.json"
WINNER_LOCK_SCHEMA = "rondo-publication-critic-plan060-winner-lock-v1"
ALLOWED_H100_HARDWARE = (
    "NVIDIA H100 PCIe",
    "NVIDIA H100 80GB HBM3",
)


def capture_dependency_identity(
    *,
    container_image: str,
    status: str,
    model_contract: Mapping[str, Any],
    complete_freeze_sha256: str | None = None,
) -> dict[str, Any]:
    if status not in {"commissioning_observed", "formal_frozen"}:
        raise FullModelTrainingError("dependency_capture_status_invalid")
    optimizer = model_contract.get("optimizer")
    if not isinstance(optimizer, Mapping):
        raise FullModelTrainingError("model_contract_optimizer_invalid")
    packages: dict[str, str] = {}
    for distribution in (
        "torch",
        "transformers",
        "flashoptim",
        "safetensors",
        "triton",
        "tokenizers",
        "huggingface-hub",
        "numpy",
    ):
        try:
            packages[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            raise FullModelTrainingError("training_dependency_missing", distribution) from exc
    try:
        torch = importlib.import_module("torch")
        flash_module = importlib.import_module("flashoptim")
        flash_class = getattr(flash_module, "FlashAdamW")
    except (ImportError, AttributeError) as exc:
        raise FullModelTrainingError("flashadamw_runtime_missing") from exc
    cuda_version = str(getattr(torch.version, "cuda", None) or "")
    if not cuda_version or flash_class.__name__ != "FlashAdamW":
        raise FullModelTrainingError("training_dependency_environment_invalid")
    identity = {
        "schema": DEPENDENCY_SCHEMA,
        "status": status,
        "packages": packages,
        "python_version": platform.python_version(),
        "cuda_version": cuda_version,
        "container_image": container_image,
        "flashoptim": {
            "distribution": "flashoptim",
            "version": packages["flashoptim"],
            "import_path": "flashoptim.FlashAdamW",
            "defining_module": flash_class.__module__,
            "class": flash_class.__name__,
            "source_revision": str(optimizer.get("release_commit", "")),
        },
        "complete_freeze_sha256": complete_freeze_sha256,
    }
    observed = validate_dependency_identity(identity, require_frozen=status == "formal_frozen")
    if (
        observed["packages"]["flashoptim"] != optimizer.get("version")
        or observed["flashoptim"]["source_revision"] != optimizer.get("release_commit")
        or observed["flashoptim"]["import_path"] != "flashoptim.FlashAdamW"
        or observed["flashoptim"]["defining_module"] != "flashoptim.optimizers"
    ):
        raise FullModelTrainingError("flashadamw_runtime_identity_mismatch")
    return observed


def validate_optimizer_coverage(
    model: Any,
    optimizer: Any,
    *,
    expected_dtype: str = "torch.bfloat16",
    expected_device_type: str = "cuda",
    expected_device_index: int = 0,
) -> dict[str, Any]:
    named = list(model.named_parameters())
    if not named:
        raise FullModelTrainingError("model_parameters_missing")
    model_ids: list[int] = []
    parameter_count = 0
    floating_parameter_count = 0
    dtype_counts: dict[str, int] = {}
    device_counts: dict[str, int] = {}
    for name, parameter in named:
        del name
        if getattr(parameter, "requires_grad", None) is not True:
            raise FullModelTrainingError("model_parameter_frozen")
        identifier = id(parameter)
        if identifier in model_ids:
            raise FullModelTrainingError("model_parameter_duplicate")
        model_ids.append(identifier)
        count = int(parameter.numel())
        parameter_count += count
        dtype_name = str(parameter.dtype)
        device = parameter.device
        device_name = f"{device.type}:{device.index}"
        dtype_counts[dtype_name] = dtype_counts.get(dtype_name, 0) + count
        device_counts[device_name] = device_counts.get(device_name, 0) + count
        is_floating = bool(parameter.is_floating_point())
        if is_floating:
            floating_parameter_count += count
            if dtype_name not in {expected_dtype, expected_dtype.removeprefix("torch.")}:
                raise FullModelTrainingError("model_parameter_dtype_invalid")
        if device.type != expected_device_type or device.index != expected_device_index:
            raise FullModelTrainingError("model_parameter_device_invalid")
    optimizer_parameters = [
        parameter
        for group in getattr(optimizer, "param_groups", ())
        for parameter in group.get("params", ())
    ]
    optimizer_ids = [id(parameter) for parameter in optimizer_parameters]
    if len(optimizer_ids) != len(set(optimizer_ids)):
        raise FullModelTrainingError("optimizer_parameter_duplicate")
    if set(optimizer_ids) != set(model_ids) or len(optimizer_ids) != len(model_ids):
        raise FullModelTrainingError("optimizer_parameter_coverage_invalid")
    order = [
        {"name": name, "numel": int(parameter.numel())}
        for name, parameter in named
    ]
    return {
        "named_parameter_tensors": len(named),
        "parameter_count": parameter_count,
        "floating_parameter_count": floating_parameter_count,
        "trainable_parameter_count": parameter_count,
        "optimizer_parameter_tensors": len(optimizer_parameters),
        "optimizer_parameter_count": sum(int(item.numel()) for item in optimizer_parameters),
        "dtype_counts": dtype_counts,
        "device_counts": device_counts,
        "parameter_order_sha256": sha256_bytes(canonical_json_bytes(order)),
        "all_requires_grad": True,
        "optimizer_exact_coverage": True,
    }


def run_commissioning_start(
    *,
    bundle_root: Path,
    model_snapshot: Path,
    output_root: Path,
    recipe_path: Path,
    winner_lock_path: Path,
    container_image: str,
) -> dict[str, Any]:
    process_started = time.perf_counter()
    context = _prepare_run(
        bundle_root=bundle_root,
        model_snapshot=model_snapshot,
        recipe_path=recipe_path,
        winner_lock_path=winner_lock_path,
        dependency_identity_path=None,
        dependency_freeze_path=None,
        container_image=container_image,
        formal=False,
    )
    output = _new_output_root(output_root)
    process = current_process_identity()
    stages: list[dict[str, Any]] = []
    for global_step, stage in enumerate(STAGES, start=1):
        stages.append(_run_stage_update(context, stage, global_step=global_step))
    progress = _progress("C3", 3, list(STAGES), context.dataset.stage("C3"))
    optimizer_checkpoint, optimizer_state = _prepare_optimizer_for_checkpoint(
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
    checkpoint_save_seconds = time.perf_counter() - checkpoint_started
    receipt = {
        "schema": "rondo-publication-critic-commissioning-start-receipt-v1",
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
        "timing": _start_timing(
            process_started=process_started,
            context=context,
            stages=stages,
            checkpoint_save_seconds=checkpoint_save_seconds,
            optimizer_checkpoint=optimizer_checkpoint,
        ),
    }
    _validate_commissioning_start_receipt(receipt)
    write_exclusive(output / COMMISSIONING_START_RECEIPT, pretty_json_bytes(receipt))
    return receipt


def run_commissioning_resume(
    *,
    bundle_root: Path,
    model_snapshot: Path,
    output_root: Path,
    checkpoint_root: Path,
    recipe_path: Path,
    winner_lock_path: Path,
    container_image: str,
) -> dict[str, Any]:
    process_started = time.perf_counter()
    output = Path(output_root)
    if not output.is_dir() or output.is_symlink():
        raise FullModelTrainingError("commissioning_output_missing")
    if (output / COMMISSIONING_RESUME_RECEIPT).exists():
        raise FullModelTrainingError("commissioning_resume_already_completed")
    verify_started = time.perf_counter()
    checkpoint_verification = verify_checkpoint(checkpoint_root)
    checkpoint_verify_seconds = time.perf_counter() - verify_started
    metadata = read_checkpoint_metadata(checkpoint_root)
    resume_process = require_new_process(metadata)
    _require_expected_resume_progress(metadata, load_portable_dataset(bundle_root))
    context = _prepare_run(
        bundle_root=bundle_root,
        model_snapshot=model_snapshot,
        recipe_path=recipe_path,
        winner_lock_path=winner_lock_path,
        dependency_identity_path=None,
        dependency_freeze_path=None,
        container_image=container_image,
        formal=False,
        checkpoint_model_root=Path(checkpoint_root) / "full-model/model",
    )
    if metadata["identity"] != context.identity:
        raise FullModelTrainingError("commissioning_resume_identity_mismatch")
    state_load_started = time.perf_counter()
    training_state = load_training_state(
        checkpoint_root, verified_receipt=checkpoint_verification
    )
    checkpoint_state_load_seconds = time.perf_counter() - state_load_started
    restore_started = time.perf_counter()
    try:
        context.optimizer.load_state_dict(training_state["optimizer"])
        context.scheduler.load_state_dict(training_state["scheduler"])
    except Exception as exc:
        raise FullModelTrainingError("commissioning_flashadamw_restore_failed") from exc
    restored_optimizer_state = _validate_flashadamw_compressed_state_dict(
        training_state["optimizer"],
        expected_state_entries=int(context.coverage["optimizer_parameter_tensors"]),
        expected_step=3,
        optimizer=context.optimizer,
    )
    restored_optimizer_runtime = _validate_flashadamw_runtime_state(
        context.optimizer,
        expected_state_entries=int(context.coverage["optimizer_parameter_tensors"]),
        expected_step=3,
    )
    restore_rng_state(training_state["rng"])
    state_restore_seconds = time.perf_counter() - restore_started
    stage_receipt = _run_stage_update(context, "C3", global_step=4)
    receipt = {
        "schema": "rondo-publication-critic-commissioning-resume-receipt-v1",
        "status": "commissioning_only_complete_not_formal_evidence",
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
        "timing": _resume_timing(
            process_started=process_started,
            context=context,
            checkpoint_verify_seconds=checkpoint_verify_seconds,
            checkpoint_state_load_seconds=checkpoint_state_load_seconds,
            state_restore_seconds=state_restore_seconds,
            continued_stage=stage_receipt,
        ),
    }
    _validate_commissioning_resume_receipt(receipt)
    write_exclusive(output / COMMISSIONING_RESUME_RECEIPT, pretty_json_bytes(receipt))
    return receipt


def run_formal_start(
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
    context = _prepare_run(
        bundle_root=bundle_root,
        model_snapshot=model_snapshot,
        recipe_path=recipe_path,
        winner_lock_path=winner_lock_path,
        dependency_identity_path=dependency_identity_path,
        dependency_freeze_path=dependency_freeze_path,
        container_image=container_image,
        formal=True,
    )
    output = _new_output_root(output_root)
    process = current_process_identity()
    stages: list[dict[str, Any]] = []
    for global_step, stage in enumerate(STAGES, start=1):
        stages.append(_run_stage_update(context, stage, global_step=global_step))
    progress = _progress("C3", 3, list(STAGES), context.dataset.stage("C3"))
    optimizer_checkpoint, optimizer_state = _prepare_optimizer_for_checkpoint(
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
    checkpoint_save_seconds = time.perf_counter() - checkpoint_started
    receipt = {
        "schema": "rondo-publication-critic-formal-start-receipt-v1",
        "status": "pending_new_process_resume",
        "created_at": utc_now(),
        "process": process.as_dict(),
        "identity": context.identity,
        "coverage": context.coverage,
        "stages": stages,
        "checkpoint": checkpoint,
        "optimizer_pre_checkpoint": optimizer_checkpoint,
        "global_step": 3,
        "resume_required": {"stage": "C3", "updates": 1, "new_os_process": True},
        "timing": _start_timing(
            process_started=process_started,
            context=context,
            stages=stages,
            checkpoint_save_seconds=checkpoint_save_seconds,
            optimizer_checkpoint=optimizer_checkpoint,
        ),
    }
    _validate_winner_bound_receipt(receipt)
    validate_formal_start_receipt(receipt)
    write_exclusive(output / FORMAL_START_RECEIPT, pretty_json_bytes(receipt))
    return receipt


def run_formal_resume(
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
    process_started = time.perf_counter()
    output = Path(output_root)
    if not output.is_dir() or output.is_symlink():
        raise FullModelTrainingError("formal_output_missing")
    expected_checkpoint = output / "checkpoint-c3"
    try:
        if Path(checkpoint_root).resolve(strict=True) != expected_checkpoint.resolve(strict=True):
            raise FullModelTrainingError("formal_checkpoint_namespace_mismatch")
    except OSError as exc:
        raise FullModelTrainingError("formal_checkpoint_namespace_mismatch") from exc
    if (output / FORMAL_PENDING_RECEIPT).exists():
        raise FullModelTrainingError("formal_resume_already_completed")
    start_receipt_path = output / FORMAL_START_RECEIPT
    start_receipt = validate_formal_start_receipt(read_json(start_receipt_path))
    start_receipt_sha256 = sha256_file(start_receipt_path)
    verify_started = time.perf_counter()
    checkpoint_verification = verify_checkpoint(checkpoint_root)
    checkpoint_verify_seconds = time.perf_counter() - verify_started
    metadata = read_checkpoint_metadata(checkpoint_root)
    resume_process = require_new_process(metadata)
    _require_expected_resume_progress(metadata, load_portable_dataset(bundle_root))
    context = _prepare_run(
        bundle_root=bundle_root,
        model_snapshot=model_snapshot,
        recipe_path=recipe_path,
        winner_lock_path=winner_lock_path,
        dependency_identity_path=dependency_identity_path,
        dependency_freeze_path=dependency_freeze_path,
        container_image=container_image,
        formal=True,
        checkpoint_model_root=Path(checkpoint_root) / "full-model/model",
    )
    if metadata["identity"] != context.identity:
        raise FullModelTrainingError("formal_resume_identity_mismatch")
    if (
        start_receipt.get("identity") != context.identity
        or start_receipt.get("coverage") != context.coverage
        or start_receipt.get("process") != metadata.get("process")
        or start_receipt.get("checkpoint", {}).get("checkpoint_manifest_sha256")
        != checkpoint_verification.get("checkpoint_manifest_sha256")
    ):
        raise FullModelTrainingError("formal_start_checkpoint_binding_mismatch")
    state_load_started = time.perf_counter()
    training_state = load_training_state(
        checkpoint_root, verified_receipt=checkpoint_verification
    )
    checkpoint_state_load_seconds = time.perf_counter() - state_load_started
    restore_started = time.perf_counter()
    try:
        context.optimizer.load_state_dict(training_state["optimizer"])
        context.scheduler.load_state_dict(training_state["scheduler"])
    except Exception as exc:
        raise FullModelTrainingError("flashadamw_checkpoint_restore_failed") from exc
    restored_optimizer_state = _validate_flashadamw_compressed_state_dict(
        training_state["optimizer"],
        expected_state_entries=int(context.coverage["optimizer_parameter_tensors"]),
        expected_step=3,
        optimizer=context.optimizer,
    )
    restored_optimizer_runtime = _validate_flashadamw_runtime_state(
        context.optimizer,
        expected_state_entries=int(context.coverage["optimizer_parameter_tensors"]),
        expected_step=3,
    )
    restore_rng_state(training_state["rng"])
    state_restore_seconds = time.perf_counter() - restore_started
    stage_receipt = _run_stage_update(context, "C3", global_step=4)
    receipt = {
        "schema": "rondo-publication-critic-formal-training-pending-v1",
        "status": "pending_billing_and_resource_cleanup",
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
        "formal_start_receipt_sha256": start_receipt_sha256,
        "timing": _resume_timing(
            process_started=process_started,
            context=context,
            checkpoint_verify_seconds=checkpoint_verify_seconds,
            checkpoint_state_load_seconds=checkpoint_state_load_seconds,
            state_restore_seconds=state_restore_seconds,
            continued_stage=stage_receipt,
        ),
        "billing": None,
        "remote_resource_terminal_state": None,
        "qualification_conclusion": None,
    }
    _validate_winner_bound_receipt(receipt)
    validate_formal_pending_receipt(receipt)
    write_exclusive(output / FORMAL_PENDING_RECEIPT, pretty_json_bytes(receipt))
    return receipt


class _RunContext:
    def __init__(
        self,
        *,
        torch: Any,
        model: Any,
        tokenizer: Any,
        exact_tokenizer: ExactTokenizer,
        optimizer: Any,
        scheduler: Any,
        dataset: PortableTrainingDataset,
        tokenized: Mapping[str, Any],
        recipe: Mapping[str, Any],
        identity: Mapping[str, Any],
        coverage: Mapping[str, Any],
        device: Any,
        hardware: Mapping[str, Any],
        startup_timing: Mapping[str, Any],
        optimizer_contract: Mapping[str, Any],
    ) -> None:
        self.torch = torch
        self.model = model
        self.tokenizer = tokenizer
        self.exact_tokenizer = exact_tokenizer
        self.optimizer = optimizer
        self.scheduler = scheduler
        self.dataset = dataset
        self.tokenized = tokenized
        self.recipe = recipe
        self.identity = identity
        self.coverage = coverage
        self.device = device
        self.hardware = hardware
        self.startup_timing = startup_timing
        self.optimizer_contract = optimizer_contract


def _construct_flashadamw(
    optimizer_class: Any,
    parameters: Any,
    *,
    recipe: Mapping[str, Any],
    optimizer_contract: Mapping[str, Any],
) -> Any:
    """Construct the exact FlashOptim 0.1.4 route.

    ``gradient_release`` deliberately is not a constructor argument in the
    pinned wheel.  The disabled identity is established by never invoking the
    opt-in ``enable_gradient_release`` API.
    """

    return optimizer_class(
        parameters,
        lr=float(recipe["learning_rate"]),
        betas=tuple(float(item) for item in recipe["betas"]),
        eps=float(recipe["epsilon"]),
        weight_decay=float(recipe["weight_decay"]),
        quantize=bool(optimizer_contract["quantize"]),
        fused=bool(optimizer_contract["fused"]),
        decouple_lr=bool(optimizer_contract["decouple_lr"]),
        master_weight_bits=int(optimizer_contract["master_weight_bits"]),
        compress_state_dict=bool(optimizer_contract["compress_state_dict"]),
        check_numerics=bool(optimizer_contract["check_numerics"]),
    )


def _preflight_flashadamw_numerics(
    optimizer: Any,
    *,
    numerics_error_class: type[BaseException],
    check_numerics: bool,
    configured_learning_rate: float,
    expected_parameter_tensors: int,
) -> dict[str, Any]:
    """Validate the pinned FlashAdamW numerics gate across every parameter.

    FlashOptim 0.1.4 performs this check lazily and raises at the first
    parameter that fails.  A paid commissioning run would therefore discover
    successively larger parameter ranges one restart at a time.  The pinned
    optimizer already exposes the exact per-parameter checker and cached-stat
    refresh used by ``step``; exercise those same semantics for the complete
    parameter set before any objective or update.  If the configured LR fails,
    powers of two are probed without modifying optimizer state so the next
    bounded recipe candidate is reported in one run.
    """

    if not check_numerics:
        raise FullModelTrainingError("flashadamw_numerics_preflight_disabled")
    if (
        not isinstance(numerics_error_class, type)
        or not issubclass(numerics_error_class, RuntimeError)
        or numerics_error_class.__name__ != "NumericsError"
        or numerics_error_class.__module__ != "flashoptim.optimizers"
    ):
        raise FullModelTrainingError(
            "flashadamw_numerics_preflight_error_class_invalid"
        )
    recompute = getattr(optimizer, "recompute_param_stats", None)
    checker = getattr(optimizer, "_check_param_numerics", None)
    if not callable(recompute) or not callable(checker):
        raise FullModelTrainingError("flashadamw_numerics_preflight_api_missing")
    if (
        not math.isfinite(configured_learning_rate)
        or configured_learning_rate <= 0.0
        or expected_parameter_tensors <= 0
    ):
        raise FullModelTrainingError("flashadamw_numerics_preflight_contract_invalid")
    started = time.perf_counter()
    try:
        recompute()
    except Exception as exc:
        raise FullModelTrainingError(
            "flashadamw_numerics_preflight_stats_failed"
        ) from exc

    checked = 0
    failed = 0
    required_learning_rate = configured_learning_rate
    first_failure: str | None = None

    def passes(parameter: Any, *, learning_rate: float, master_bytewidth: int) -> bool:
        try:
            checker(
                parameter,
                lr=learning_rate,
                master_bytewidth=master_bytewidth,
            )
        except Exception as exc:
            if type(exc) is not numerics_error_class:
                raise FullModelTrainingError(
                    "flashadamw_numerics_preflight_check_failed"
                ) from exc
            nonlocal first_failure
            if first_failure is None:
                first_failure = str(exc)
            return False
        return True

    groups = getattr(optimizer, "param_groups", None)
    if not isinstance(groups, list) or not groups:
        raise FullModelTrainingError("flashadamw_numerics_preflight_groups_invalid")
    for group in groups:
        if not isinstance(group, Mapping):
            raise FullModelTrainingError("flashadamw_numerics_preflight_groups_invalid")
        try:
            group_learning_rate = float(group["lr"])
            master_bytewidth = int(group["master_bytewidth"])
        except (KeyError, TypeError, ValueError) as exc:
            raise FullModelTrainingError(
                "flashadamw_numerics_preflight_group_contract_invalid"
            ) from exc
        if (
            not math.isfinite(group_learning_rate)
            or group_learning_rate != configured_learning_rate
            or master_bytewidth <= 0
            or isinstance(group.get("master_bytewidth"), bool)
        ):
            raise FullModelTrainingError(
                "flashadamw_numerics_preflight_group_contract_invalid"
            )
        parameters = group.get("params")
        if not isinstance(parameters, list):
            raise FullModelTrainingError("flashadamw_numerics_preflight_groups_invalid")
        for parameter in parameters:
            checked += 1
            if passes(
                parameter,
                learning_rate=group_learning_rate,
                master_bytewidth=master_bytewidth,
            ):
                continue
            failed += 1
            candidate = group_learning_rate
            for _attempt in range(16):
                candidate *= 2.0
                if not math.isfinite(candidate):
                    break
                if passes(
                    parameter,
                    learning_rate=candidate,
                    master_bytewidth=master_bytewidth,
                ):
                    required_learning_rate = max(required_learning_rate, candidate)
                    break
            else:
                raise FullModelTrainingError(
                    "flashadamw_numerics_preflight_candidate_unbounded"
                )
            if not math.isfinite(candidate):
                raise FullModelTrainingError(
                    "flashadamw_numerics_preflight_candidate_unbounded"
                )
    if checked != expected_parameter_tensors:
        raise FullModelTrainingError(
            "flashadamw_numerics_preflight_coverage_mismatch"
        )
    evidence = {
        "schema": "rondo-flashadamw-global-numerics-preflight-v1",
        "check_numerics": True,
        "recompute_param_stats_called": True,
        "parameter_tensors_checked": checked,
        "configured_learning_rate": configured_learning_rate,
        "failed_parameter_tensors": failed,
        "required_power_of_two_learning_rate": required_learning_rate,
        "all_parameters_passed": failed == 0,
        "elapsed_seconds": time.perf_counter() - started,
    }
    if failed:
        detail = json.dumps(
            {
                "configured_learning_rate": configured_learning_rate,
                "failed_parameter_tensors": failed,
                "first_failure": first_failure,
                "parameter_tensors_checked": checked,
                "required_power_of_two_learning_rate": required_learning_rate,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        raise FullModelTrainingError(
            "flashadamw_global_numerics_preflight_failed", detail
        )
    return evidence


def _prepare_optimizer_for_checkpoint(
    optimizer: Any,
    *,
    check_numerics: bool,
    expected_state_entries: int,
    expected_step: int,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    started = time.perf_counter()
    recomputed = False
    if check_numerics:
        recompute = getattr(optimizer, "recompute_param_stats", None)
        if not callable(recompute):
            raise FullModelTrainingError("flashadamw_recompute_param_stats_missing")
        try:
            recompute()
        except Exception as exc:
            raise FullModelTrainingError("flashadamw_recompute_param_stats_failed") from exc
        recomputed = True
    state_evidence, state_dict = _export_and_validate_flashadamw_compressed_state(
        optimizer,
        expected_state_entries=expected_state_entries,
        expected_step=expected_step,
    )
    return (
        {
            "check_numerics": check_numerics,
            "recompute_param_stats_called": recomputed,
            "elapsed_seconds": time.perf_counter() - started,
            "compressed_state": state_evidence,
        },
        state_dict,
    )


def _export_and_validate_flashadamw_compressed_state(
    optimizer: Any,
    *,
    expected_state_entries: int,
    expected_step: int,
) -> tuple[dict[str, Any], Mapping[str, Any]]:
    try:
        state_dict = optimizer.state_dict()
    except Exception as exc:
        raise FullModelTrainingError("flashadamw_state_dict_failed") from exc
    return (
        _validate_flashadamw_compressed_state_dict(
            state_dict,
            expected_state_entries=expected_state_entries,
            expected_step=expected_step,
            optimizer=optimizer,
        ),
        state_dict,
    )


def _validate_flashadamw_compressed_state_dict(
    state_dict: Any,
    *,
    expected_state_entries: int,
    expected_step: int,
    optimizer: Any | None = None,
) -> dict[str, Any]:
    required_keys = {
        "step",
        "exp_avg::quantized",
        "exp_avg::scales",
        "exp_avg_sq::quantized",
        "exp_avg_sq::scales",
        "error_bits",
    }
    if expected_state_entries <= 0:
        raise FullModelTrainingError("flashadamw_expected_state_entries_invalid")
    state = state_dict.get("state") if isinstance(state_dict, Mapping) else None
    param_groups = state_dict.get("param_groups") if isinstance(state_dict, Mapping) else None
    if (
        not isinstance(state, Mapping)
        or len(state) != expected_state_entries
        or not isinstance(param_groups, list)
        or not param_groups
    ):
        raise FullModelTrainingError("flashadamw_compressed_state_coverage_invalid")
    parameter_references = [
        parameter
        for group in param_groups
        if isinstance(group, Mapping)
        for parameter in group.get("params", ())
    ]
    if len(parameter_references) != expected_state_entries:
        raise FullModelTrainingError("flashadamw_compressed_state_coverage_invalid")
    check_parameter_shapes = optimizer is not None and hasattr(optimizer, "param_groups")
    live_parameters = (
        [
            parameter
            for group in getattr(optimizer, "param_groups", ())
            for parameter in group.get("params", ())
        ]
        if check_parameter_shapes
        else []
    )
    if check_parameter_shapes and len(live_parameters) != expected_state_entries:
        raise FullModelTrainingError("flashadamw_compressed_state_coverage_invalid")
    referenced_parameters = dict(zip(parameter_references, live_parameters))
    key_counts = {key: 0 for key in sorted(required_keys)}
    dtype_counts: dict[str, dict[str, int]] = {key: {} for key in sorted(required_keys)}
    for reference, item in state.items():
        if not isinstance(item, Mapping) or not required_keys.issubset(item):
            raise FullModelTrainingError("flashadamw_compressed_state_shape_invalid")
        if _optimizer_step_value(item["step"]) != expected_step:
            raise FullModelTrainingError("flashadamw_compressed_state_step_invalid")
        parameter = referenced_parameters.get(reference) if check_parameter_shapes else None
        _validate_flashadamw_exported_tensor_state(item, parameter=parameter)
        for key in key_counts:
            key_counts[key] += int(key in item)
            dtype = str(getattr(item[key], "dtype", type(item[key]).__name__))
            dtype_counts[key][dtype] = dtype_counts[key].get(dtype, 0) + 1
    if any(count != expected_state_entries for count in key_counts.values()):
        raise FullModelTrainingError("flashadamw_compressed_state_shape_invalid")
    return {
        "state_entries": len(state),
        "expected_state_entries": expected_state_entries,
        "required_state_keys": sorted(required_keys),
        "required_key_counts": key_counts,
        "optimizer_parameter_references": len(parameter_references),
        "optimizer_step": expected_step,
        "state_dtype_counts": dtype_counts,
        "parameter_shapes_checked": check_parameter_shapes,
        "compressed_moment_state_complete": True,
    }


def _validate_flashadamw_exported_tensor_state(
    item: Mapping[str, Any], *, parameter: Any | None
) -> None:
    expected_dtypes = {
        "step": "torch.int64",
        "exp_avg::quantized": "torch.int8",
        "exp_avg_sq::quantized": "torch.uint8",
        "exp_avg::scales": "torch.bfloat16",
        "exp_avg_sq::scales": "torch.bfloat16",
        "error_bits": "torch.bfloat16",
    }
    for key, expected_dtype in expected_dtypes.items():
        value = item[key]
        if str(getattr(value, "dtype", "")) != expected_dtype:
            raise FullModelTrainingError("flashadamw_compressed_state_dtype_invalid")
    if parameter is None:
        return
    parameter_numel = int(parameter.numel())
    for key in ("exp_avg::quantized", "exp_avg_sq::quantized", "error_bits"):
        value = item[key]
        if int(value.numel()) != parameter_numel or tuple(value.shape) != tuple(parameter.shape):
            raise FullModelTrainingError("flashadamw_compressed_state_shape_invalid")
    for key in ("exp_avg::scales", "exp_avg_sq::scales"):
        count = int(item[key].numel())
        if count <= 0 or count > parameter_numel:
            raise FullModelTrainingError("flashadamw_compressed_state_shape_invalid")


def _optimizer_step_value(value: Any) -> int:
    if hasattr(value, "item") and callable(value.item):
        try:
            value = value.item()
        except Exception as exc:
            raise FullModelTrainingError("flashadamw_optimizer_step_invalid") from exc
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise FullModelTrainingError("flashadamw_optimizer_step_invalid")
    return value


def _validate_flashadamw_runtime_state(
    optimizer: Any, *, expected_state_entries: int, expected_step: int
) -> dict[str, Any]:
    state = getattr(optimizer, "state", None)
    parameters = [
        parameter
        for group in getattr(optimizer, "param_groups", ())
        for parameter in group.get("params", ())
    ]
    if (
        not isinstance(state, Mapping)
        or len(state) != expected_state_entries
        or len(parameters) != expected_state_entries
    ):
        raise FullModelTrainingError("flashadamw_runtime_state_coverage_invalid")
    for parameter in parameters:
        item = state.get(parameter)
        if not isinstance(item, Mapping) or not {
            "step", "exp_avg", "exp_avg_sq", "error_bits"
        }.issubset(item):
            raise FullModelTrainingError("flashadamw_runtime_state_shape_invalid")
        if _optimizer_step_value(item["step"]) != expected_step:
            raise FullModelTrainingError("flashadamw_runtime_state_step_invalid")
        if str(getattr(item["error_bits"], "dtype", "")) != "torch.int16":
            raise FullModelTrainingError("flashadamw_runtime_state_dtype_invalid")
        if int(item["error_bits"].numel()) != int(parameter.numel()):
            raise FullModelTrainingError("flashadamw_runtime_state_shape_invalid")
        for key in ("exp_avg", "exp_avg_sq"):
            if int(item[key].numel()) != int(parameter.numel()):
                raise FullModelTrainingError("flashadamw_runtime_state_shape_invalid")
    return {
        "state_entries": len(state),
        "expected_state_entries": expected_state_entries,
        "optimizer_step": expected_step,
        "error_bits_dtype": "torch.int16",
        "moment_and_error_shapes_match_parameters": True,
    }


def _start_timing(
    *,
    process_started: float,
    context: _RunContext,
    stages: Sequence[Mapping[str, Any]],
    checkpoint_save_seconds: float,
    optimizer_checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    by_stage = {str(item["stage"]): float(item["elapsed_seconds"]) for item in stages}
    return {
        "process_startup_seconds": float(context.startup_timing["runtime_prepare_seconds"]),
        "runtime_prepare": dict(context.startup_timing),
        "first_step_jit_cold_seconds": by_stage["C1"],
        "steady_stage_step_seconds": {"C2": by_stage["C2"], "C3": by_stage["C3"]},
        "optimizer_pre_checkpoint_seconds": float(optimizer_checkpoint["elapsed_seconds"]),
        "checkpoint_save_seconds": checkpoint_save_seconds,
        "process_elapsed_through_checkpoint_seconds": time.perf_counter() - process_started,
    }


def _resume_timing(
    *,
    process_started: float,
    context: _RunContext,
    checkpoint_verify_seconds: float,
    checkpoint_state_load_seconds: float,
    state_restore_seconds: float,
    continued_stage: Mapping[str, Any],
) -> dict[str, Any]:
    restore_total = (
        checkpoint_verify_seconds
        + float(context.startup_timing["runtime_prepare_seconds"])
        + checkpoint_state_load_seconds
        + state_restore_seconds
    )
    return {
        "process_startup_seconds": float(context.startup_timing["runtime_prepare_seconds"]),
        "runtime_prepare": dict(context.startup_timing),
        "checkpoint_verify_seconds": checkpoint_verify_seconds,
        "checkpoint_model_load_seconds": float(context.startup_timing["model_load_seconds"]),
        "checkpoint_state_load_seconds": checkpoint_state_load_seconds,
        "optimizer_scheduler_rng_restore_seconds": state_restore_seconds,
        "resume_verify_load_restore_seconds": restore_total,
        "continued_step_seconds": float(continued_stage["elapsed_seconds"]),
        "process_elapsed_through_continue_seconds": time.perf_counter() - process_started,
    }


def _validate_h100_hardware(torch: Any, *, selected_gpu: str) -> dict[str, Any]:
    try:
        device_count = int(torch.cuda.device_count())
        name = str(torch.cuda.get_device_name(0))
        properties = torch.cuda.get_device_properties(0)
        total_memory = int(properties.total_memory)
        capability_value = torch.cuda.get_device_capability(0)
        capability = (int(capability_value[0]), int(capability_value[1]))
    except (AttributeError, IndexError, TypeError, ValueError) as exc:
        raise FullModelTrainingError("cuda_hardware_facts_unavailable") from exc
    if (
        device_count != 1
        or selected_gpu not in ALLOWED_H100_HARDWARE
        or name != selected_gpu
        or total_memory < 79 * 1024**3
        or capability != (9, 0)
    ):
        raise FullModelTrainingError("winner_h100_80gb_hardware_mismatch")
    return {
        "device_count": device_count,
        "device_index": 0,
        "device_name": name,
        "selected_gpu": selected_gpu,
        "total_memory_bytes": total_memory,
        "compute_capability": [capability[0], capability[1]],
        "qualification": (
            "H100 PCIe 80GB"
            if selected_gpu == "NVIDIA H100 PCIe"
            else "H100 SXM 80GB"
        ),
    }


def _load_winner_lock(
    path: Path, *, model_contract: Mapping[str, Any]
) -> dict[str, Any]:
    """Read the external winner-lock replica once and bind its exact bytes.

    The controller-side authority is mode 0600.  A task-private RunPod Standard
    volume can normalize every regular file to 0666 even after a successful
    chmod, so POSIX mode is not a portable property of the remote replica.  Its
    boundary is instead no-follow regular-file access, a strict size/stability
    check, the frozen schema and the exact byte hash bound into every receipt.
    """

    file_path = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(file_path, flags)
    except OSError as exc:
        raise FullModelTrainingError("winner_lock_file_invalid") from exc
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > 64 * 1024
        ):
            raise FullModelTrainingError("winner_lock_file_invalid")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise FullModelTrainingError("winner_lock_file_changed")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise FullModelTrainingError("winner_lock_file_changed")
        before_identity = (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_uid,
            info.st_gid,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )
        after = os.fstat(descriptor)
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_mode,
            after.st_uid,
            after.st_gid,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if after_identity != before_identity:
            raise FullModelTrainingError("winner_lock_file_changed")
    except OSError as exc:
        raise FullModelTrainingError("winner_lock_file_invalid") from exc
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    try:
        value = json.loads(raw.decode("utf-8"))
        normalized = json.loads(json.dumps(value, allow_nan=False))
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FullModelTrainingError("winner_lock_json_invalid") from exc
    route = model_contract.get("route")
    allowed = route.get("allowed_hardware") if isinstance(route, Mapping) else None
    winner_pod = normalized.get("pod") if isinstance(normalized, Mapping) else None
    evidence = (
        normalized.get("evidence") if isinstance(normalized, Mapping) else None
    )
    if (
        not isinstance(normalized, Mapping)
        or normalized.get("schema") != WINNER_LOCK_SCHEMA
        or normalized.get("selected_gpu") not in ALLOWED_H100_HARDWARE
        or not isinstance(allowed, list)
        or normalized.get("selected_gpu") not in allowed
        or not isinstance(winner_pod, Mapping)
        or set(winner_pod) != {"id", "name"}
        or not isinstance(winner_pod.get("id"), str)
        or not winner_pod["id"].strip()
        or not isinstance(winner_pod.get("name"), str)
        or not winner_pod["name"].strip()
        or not isinstance(evidence, Mapping)
        or not isinstance(evidence.get("network_volume_id"), str)
        or not evidence["network_volume_id"].strip()
    ):
        raise FullModelTrainingError("winner_lock_identity_invalid")
    return {
        "value": normalized,
        "selected_gpu": normalized["selected_gpu"],
        "sha256": sha256_bytes(raw),
    }


def _validate_winner_bound_receipt(value: Any) -> None:
    identity = value.get("identity") if isinstance(value, Mapping) else None
    checkpoint = value.get("checkpoint") if isinstance(value, Mapping) else None
    winner_lock = identity.get("winner_lock") if isinstance(identity, Mapping) else None
    selected_gpu = identity.get("selected_gpu") if isinstance(identity, Mapping) else None
    hardware = identity.get("hardware") if isinstance(identity, Mapping) else None
    winner_sha256 = (
        identity.get("winner_lock_sha256") if isinstance(identity, Mapping) else None
    )
    if (
        not isinstance(identity, Mapping)
        or not isinstance(winner_lock, Mapping)
        or winner_lock.get("schema") != WINNER_LOCK_SCHEMA
        or winner_lock.get("selected_gpu") != selected_gpu
        or selected_gpu not in ALLOWED_H100_HARDWARE
        or not isinstance(winner_sha256, str)
        or len(winner_sha256) != 64
        or any(character not in "0123456789abcdef" for character in winner_sha256)
        or not isinstance(hardware, Mapping)
        or hardware.get("device_count") != 1
        or hardware.get("device_name") != selected_gpu
        or hardware.get("selected_gpu") != selected_gpu
        or not isinstance(checkpoint, Mapping)
        or checkpoint.get("identity_sha256")
        != sha256_bytes(canonical_json_bytes(identity))
    ):
        raise FullModelTrainingError("winner_lock_receipt_binding_invalid")


def _prepare_run(
    *,
    bundle_root: Path,
    model_snapshot: Path,
    recipe_path: Path,
    winner_lock_path: Path,
    dependency_identity_path: Path | None,
    dependency_freeze_path: Path | None,
    container_image: str,
    formal: bool,
    checkpoint_model_root: Path | None = None,
) -> _RunContext:
    startup_started = time.perf_counter()
    bundle_receipt = verify_bundle(bundle_root)
    dataset = load_portable_dataset(bundle_root)
    recipe = validate_recipe(read_json(recipe_path), require_frozen=formal)
    model_contract = _validate_model_contract(
        read_json(Path(bundle_root) / MODEL_CONTRACT_RELATIVE)
    )
    winner_lock = _load_winner_lock(winner_lock_path, model_contract=model_contract)
    if formal:
        if dependency_identity_path is None:
            raise FullModelTrainingError("formal_dependency_identity_required")
        dependency = validate_dependency_identity(
            read_json(dependency_identity_path), require_frozen=True
        )
        if (
            dependency_freeze_path is None
            or sha256_file(dependency_freeze_path)
            != dependency["complete_freeze_sha256"]
        ):
            raise FullModelTrainingError("dependency_complete_freeze_mismatch")
    else:
        dependency = capture_dependency_identity(
            container_image=container_image,
            status="commissioning_observed",
            model_contract=model_contract,
            complete_freeze_sha256=None,
        )
    observed = capture_dependency_identity(
        container_image=container_image,
        status="formal_frozen" if formal else "commissioning_observed",
        model_contract=model_contract,
        complete_freeze_sha256=dependency.get("complete_freeze_sha256"),
    )
    if dependency != observed:
        raise FullModelTrainingError("dependency_environment_mismatch")
    portable = read_json(Path(bundle_root) / "contracts/portable-input-v1.json")
    _verify_model_snapshot(model_snapshot, portable)
    heavy_import_started = time.perf_counter()
    torch, transformers = _heavy_dependencies()
    heavy_import_seconds = time.perf_counter() - heavy_import_started
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise FullModelTrainingError("single_cuda_gpu_required")
    hardware = _validate_h100_hardware(
        torch, selected_gpu=str(winner_lock["selected_gpu"])
    )
    torch.manual_seed(int(recipe["seed"]))
    torch.cuda.manual_seed_all(int(recipe["seed"]))
    device = torch.device("cuda:0")
    tokenizer_load_started = time.perf_counter()
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        model_snapshot,
        local_files_only=True,
        trust_remote_code=False,
        use_fast=True,
    )
    tokenizer_load_seconds = time.perf_counter() - tokenizer_load_started
    load_from = checkpoint_model_root if checkpoint_model_root is not None else model_snapshot
    model_load_started = time.perf_counter()
    try:
        model = transformers.AutoModelForSequenceClassification.from_pretrained(
            load_from,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=torch.bfloat16,
            attn_implementation=recipe["attention_backend"],
        )
    except Exception as exc:
        raise FullModelTrainingError("exact_model_load_failed") from exc
    model_load_seconds = time.perf_counter() - model_load_started
    _validate_loaded_model(model, model_contract)
    model.to(device)
    model.train()
    model.config.use_cache = False
    if recipe["activation_checkpointing"]:
        model.gradient_checkpointing_enable()
    exact_tokenizer = ExactTokenizer(tokenizer)
    data_tokenization_started = time.perf_counter()
    tokenized = tokenize_dataset(dataset, exact_tokenizer)
    data_tokenization_seconds = time.perf_counter() - data_tokenization_started
    flash_class = _flashadamw_class(model_contract)
    numerics_error_class = _flashadamw_numerics_error_class(model_contract)
    optimizer_contract = model_contract["optimizer"]
    optimizer_init_started = time.perf_counter()
    try:
        optimizer = _construct_flashadamw(
            flash_class,
            model.parameters(),
            recipe=recipe,
            optimizer_contract=optimizer_contract,
        )
    except Exception as exc:
        raise FullModelTrainingError("flashadamw_initialization_failed") from exc
    optimizer_init_seconds = time.perf_counter() - optimizer_init_started
    coverage = validate_optimizer_coverage(model, optimizer)
    numerics_preflight = _preflight_flashadamw_numerics(
        optimizer,
        numerics_error_class=numerics_error_class,
        check_numerics=bool(optimizer_contract["check_numerics"]),
        configured_learning_rate=float(recipe["learning_rate"]),
        expected_parameter_tensors=int(coverage["optimizer_parameter_tensors"]),
    )
    total_steps = 4
    if recipe["scheduler"] != "constant":
        raise FullModelTrainingError("scheduler_not_supported")
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda _step: 1.0)
    identity = {
        "schema": "rondo-publication-critic-formal-run-identity-v1",
        "bundle_manifest_sha256": bundle_receipt["bundle_manifest_sha256"],
        "portable_input_sha256": sha256_file(
            Path(bundle_root) / "contracts/portable-input-v1.json"
        ),
        "model_contract_sha256": sha256_file(
            Path(bundle_root) / MODEL_CONTRACT_RELATIVE
        ),
        "winner_lock_sha256": winner_lock["sha256"],
        "selected_gpu": winner_lock["selected_gpu"],
        "winner_lock": winner_lock["value"],
        "recipe_sha256": sha256_file(recipe_path),
        "dependency_identity_sha256": sha256_bytes(canonical_json_bytes(dependency)),
        "dependency_complete_freeze_sha256": dependency["complete_freeze_sha256"],
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "model_weight_sha256": portable["model"]["weight_sha256"],
        "model_config_sha256": portable["model"]["config_sha256"],
        "dataset_revision": "v7",
        "hardware": hardware,
        "parameter_order_sha256": coverage["parameter_order_sha256"],
        "optimizer_runtime_class": f"{type(optimizer).__module__}.{type(optimizer).__name__}",
        "optimizer_import_path": "flashoptim.FlashAdamW",
        "optimizer_runtime_config": {
            "quantize": True,
            "fused": True,
            "decouple_lr": False,
            "gradient_release": False,
            "gradient_release_api_called": False,
            "master_weight_bits": int(optimizer_contract["master_weight_bits"]),
            "compress_state_dict": bool(optimizer_contract["compress_state_dict"]),
            "check_numerics": bool(optimizer_contract["check_numerics"]),
            "global_numerics_preflight": bool(
                optimizer_contract["global_numerics_preflight"]
            ),
        },
        "scheduler": "constant",
        "planned_total_updates_including_resume": total_steps,
    }
    startup_timing = {
        "runtime_prepare_seconds": time.perf_counter() - startup_started,
        "heavy_import_seconds": heavy_import_seconds,
        "tokenizer_load_seconds": tokenizer_load_seconds,
        "model_load_seconds": model_load_seconds,
        "data_tokenization_seconds": data_tokenization_seconds,
        "optimizer_init_seconds": optimizer_init_seconds,
        "optimizer_numerics_preflight_seconds": float(
            numerics_preflight["elapsed_seconds"]
        ),
        "optimizer_numerics_preflight": numerics_preflight,
    }
    return _RunContext(
        torch=torch,
        model=model,
        tokenizer=tokenizer,
        exact_tokenizer=exact_tokenizer,
        optimizer=optimizer,
        scheduler=scheduler,
        dataset=dataset,
        tokenized=tokenized,
        recipe=recipe,
        identity=identity,
        coverage=coverage,
        device=device,
        hardware=hardware,
        startup_timing=startup_timing,
        optimizer_contract=optimizer_contract,
    )


def _run_stage_update(
    context: _RunContext,
    stage_name: str,
    *,
    global_step: int,
) -> dict[str, Any]:
    torch = context.torch
    stage = context.dataset.stage(stage_name)
    weights = context.recipe["component_weights"][stage_name]
    representatives = _representative_parameters(context.model)
    before_bf16 = {
        name: parameter.detach().float().cpu().clone()
        for name, parameter in representatives.items()
    }
    before_master = _representative_master_snapshots(context, representatives)
    context.optimizer.zero_grad(set_to_none=True)
    torch.cuda.reset_peak_memory_stats(context.device)
    started = time.perf_counter()
    component_loss_sums: dict[str, float] = {name: 0.0 for name in weights}
    component_items: dict[str, int] = {name: 0 for name in weights}
    component_gradients: dict[str, Any] = {}
    token_count = 0
    binary_ids = stage.binary_candidate_ids
    binary_batch = int(context.recipe["binary_micro_batch_size"])
    with _capture_component_gradients(representatives) as captured:
        for start in range(0, len(binary_ids), binary_batch):
            candidate_ids = binary_ids[start : start + binary_batch]
            scalars, tokens = _forward_candidates(context, candidate_ids)
            loss = binary_loss(
                scalars.float(),
                [context.dataset.label(candidate_id) for candidate_id in candidate_ids],
            )
            loss_value = _finite_loss_value(loss)
            scaled = loss * float(weights["binary"]) * (len(candidate_ids) / len(binary_ids))
            scaled.backward()
            component_loss_sums["binary"] += loss_value * len(candidate_ids)
            component_items["binary"] += len(candidate_ids)
            token_count += tokens
    component_gradients["binary"] = _component_gradient_evidence(
        context, representatives, captured=captured
    )
    pairs_by_kind: dict[str, list[Mapping[str, Any]]] = {
        kind: [] for kind in weights if kind != "binary"
    }
    for pair_id in stage.pair_ids:
        pair = context.dataset.pair(pair_id)
        pairs_by_kind[str(pair["kind"])].append(pair)
    for kind, pair_rows in pairs_by_kind.items():
        if not pair_rows:
            raise FullModelTrainingError("stage_component_not_consumed")
        with _capture_component_gradients(representatives) as captured:
            for pair in pair_rows:
                candidate_ids = (
                    str(pair["preferred_candidate_id"]),
                    str(pair["dispreferred_candidate_id"]),
                )
                scalars, tokens = _forward_candidates(context, candidate_ids)
                loss = pair_loss(
                    scalars[:1].float(),
                    scalars[1:].float(),
                    margin=0.0,
                    temperature=1.0,
                )
                loss_value = _finite_loss_value(loss)
                (loss * float(weights[kind]) / len(pair_rows)).backward()
                component_loss_sums[kind] += loss_value
                component_items[kind] += 1
                token_count += tokens
        component_gradients[kind] = _component_gradient_evidence(
            context, representatives, captured=captured
        )
    gradients = _gradient_evidence(context, representatives)
    max_norm = float(context.recipe["gradient_clip_norm"])
    try:
        clipped_norm = float(
            torch.nn.utils.clip_grad_norm_(
                context.model.parameters(),
                max_norm if max_norm > 0 else float("inf"),
                error_if_nonfinite=True,
            ).item()
        )
    except (RuntimeError, ValueError) as exc:
        raise FullModelTrainingError("gradient_clip_nonfinite") from exc
    if not math.isfinite(clipped_norm) or clipped_norm <= 0:
        raise FullModelTrainingError("gradient_clip_nonfinite")
    gradients["global_finite"] = True
    gradients["global_nonzero"] = True
    gradients["global_preclip_norm"] = clipped_norm
    _validate_flashadamw_fused_inputs(context.model)
    try:
        context.optimizer.step()
    except Exception as exc:
        raise FullModelTrainingError(
            "flashadamw_update_failed", _bounded_exception_detail(exc)
        ) from exc
    try:
        context.scheduler.step()
    except Exception as exc:
        raise FullModelTrainingError(
            "scheduler_update_failed", _bounded_exception_detail(exc)
        ) from exc
    torch.cuda.synchronize(context.device)
    elapsed = time.perf_counter() - started
    expected_state_entries = int(context.coverage["optimizer_parameter_tensors"])
    optimizer_runtime = _validate_flashadamw_runtime_state(
        context.optimizer,
        expected_state_entries=expected_state_entries,
        expected_step=global_step,
    )
    post_update_finiteness = _validate_post_update_finiteness(context)
    optimizer_state = context.optimizer.state
    after_master = _representative_master_snapshots(context, representatives)
    updates: dict[str, Any] = {}
    for name, parameter in representatives.items():
        bf16_changed = not bool(
            torch.equal(before_bf16[name], parameter.detach().float().cpu())
        )
        master_changed = not bool(torch.equal(before_master[name], after_master[name]))
        if not master_changed:
            raise FullModelTrainingError("representative_parameter_not_updated")
        updates[name] = {
            "effective_master_changed": True,
            "bf16_visible_changed": bf16_changed,
            "numel": int(parameter.numel()),
        }
    return {
        "stage": stage_name,
        "global_step": global_step,
        "optimizer_updates": 1,
        "component_items": component_items,
        "component_mean_loss": {
            name: component_loss_sums[name] / component_items[name]
            for name in component_items
        },
        "all_losses_finite": True,
        "gradient": gradients,
        "component_gradient_contributions": component_gradients,
        "gradient_clip_preclip_norm": clipped_norm,
        "representative_updates": updates,
        "optimizer_state_entries": len(optimizer_state),
        "optimizer_step_entries": sum(
            int("step" in item) for item in optimizer_state.values()
        ),
        "optimizer_step": optimizer_runtime["optimizer_step"],
        "post_update_finiteness": post_update_finiteness,
        "tokens": token_count,
        "elapsed_seconds": elapsed,
        "tokens_per_second": token_count / elapsed,
        "peak_cuda_allocated_bytes": int(torch.cuda.max_memory_allocated(context.device)),
        "peak_cuda_reserved_bytes": int(torch.cuda.max_memory_reserved(context.device)),
    }


def _finite_loss_value(loss: Any) -> float:
    try:
        value = float(loss.detach().item())
    except Exception as exc:
        raise FullModelTrainingError("training_loss_invalid") from exc
    if not math.isfinite(value):
        raise FullModelTrainingError("training_loss_nonfinite")
    return value


def _bounded_exception_detail(exc: BaseException) -> str:
    """Return a small optimizer-only diagnostic without training examples."""

    exception_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    message = " ".join(str(exc).split())
    if not message:
        return exception_type
    return f"{exception_type}: {message}"[:1024]


def _validate_flashadamw_fused_inputs(model: Any) -> None:
    """Fail before a fused step can partially update an incompatible model."""

    for name, parameter in model.named_parameters():
        is_contiguous = getattr(parameter, "is_contiguous", None)
        if not callable(is_contiguous) or is_contiguous() is not True:
            raise FullModelTrainingError(
                "flashadamw_parameter_noncontiguous",
                _tensor_layout_detail(name, parameter),
            )
        gradient = parameter.grad
        if gradient is None:
            continue
        gradient_contiguous = getattr(gradient, "is_contiguous", None)
        if not callable(gradient_contiguous) or gradient_contiguous() is not True:
            raise FullModelTrainingError(
                "flashadamw_gradient_noncontiguous",
                _tensor_layout_detail(name, gradient),
            )


def _tensor_layout_detail(name: str, tensor: Any) -> str:
    try:
        shape = tuple(int(item) for item in tensor.shape)
        stride = tuple(int(item) for item in tensor.stride())
    except Exception:
        shape = ()
        stride = ()
    return f"name={name};shape={shape};stride={stride}"[:1024]


def _forward_candidates(
    context: _RunContext,
    candidate_ids: Sequence[str],
) -> tuple[Any, int]:
    inputs = [context.tokenized[candidate_id] for candidate_id in candidate_ids]
    tokenizer = context.exact_tokenizer.tokenizer
    if tokenizer.padding_side != "right":
        raise FullModelTrainingError("training_padding_side_drifted")
    batch = tokenizer.pad(
        {"input_ids": [list(item.input_ids) for item in inputs]},
        padding=True,
        return_attention_mask=True,
        return_tensors="pt",
    )
    batch = {name: tensor.to(context.device) for name, tensor in batch.items()}
    output = context.model(**batch)
    scalars = extract_raw_scalar(output.logits)
    tokens = int(batch["attention_mask"].sum().item())
    return scalars, tokens


def _gradient_evidence(context: _RunContext, representatives: Mapping[str, Any]) -> dict[str, Any]:
    torch = context.torch
    gradient_tensors = 0
    gradient_elements = 0
    for parameter in context.model.parameters():
        gradient = parameter.grad
        if gradient is None:
            continue
        gradient_tensors += 1
        gradient_elements += int(gradient.numel())
    representative = {}
    for name, parameter in representatives.items():
        gradient = parameter.grad
        representative[name] = {
            "present": gradient is not None,
            "finite": gradient is not None and bool(torch.isfinite(gradient).all().item()),
            "nonzero": gradient is not None and bool(torch.count_nonzero(gradient).item()),
        }
    if gradient_tensors <= 0 or gradient_elements <= 0:
        raise FullModelTrainingError("gradient_evidence_invalid")
    if any(
        not item["present"] or not item["finite"] or not item["nonzero"]
        for item in representative.values()
    ):
        raise FullModelTrainingError("representative_gradient_invalid")
    return {
        "gradient_tensors": gradient_tensors,
        "gradient_elements": gradient_elements,
        "representative": representative,
    }


@contextmanager
def _capture_component_gradients(representatives: Mapping[str, Any]):
    """Capture each backward contribution before BF16 ``.grad`` accumulation."""

    captured: dict[str, list[Any]] = {}
    handles = []
    for name, parameter in representatives.items():
        def capture(gradient: Any, *, parameter_name: str = name) -> Any:
            contribution = gradient.detach().float()
            captured.setdefault(parameter_name, []).append(contribution.clone())
            return gradient

        handles.append(parameter.register_hook(capture))
    try:
        yield captured
    finally:
        for handle in handles:
            handle.remove()


def _component_gradient_evidence(
    context: _RunContext,
    representatives: Mapping[str, Any],
    *,
    captured: Mapping[str, Any],
) -> dict[str, Any]:
    torch = context.torch
    evidence: dict[str, Any] = {}
    for name in representatives:
        contributions = captured.get(name)
        if not contributions:
            raise FullModelTrainingError("component_representative_gradient_missing")
        finite = all(bool(torch.isfinite(item).all().item()) for item in contributions)
        nonzero_elements = max(
            int(torch.count_nonzero(item).item()) for item in contributions
        )
        if not finite or nonzero_elements <= 0:
            raise FullModelTrainingError("component_representative_gradient_invalid")
        evidence[name] = {
            "finite": True,
            "nonzero": True,
            "nonzero_elements": nonzero_elements,
            "numel": int(contributions[0].numel()),
            "backward_calls": len(contributions),
        }
    return evidence


def _validate_post_update_finiteness(context: _RunContext) -> dict[str, Any]:
    """Reject non-finite model, effective-master, optimizer, or scheduler state."""

    torch = context.torch
    try:
        reconstruct = getattr(importlib.import_module("flashoptim"), "reconstruct_fp32_param")
    except (ImportError, AttributeError) as exc:
        raise FullModelTrainingError("flashadamw_master_reconstruction_missing") from exc
    state = getattr(context.optimizer, "state", None)
    param_groups = getattr(context.optimizer, "param_groups", None)
    parameters = [
        parameter
        for group in param_groups or ()
        for parameter in group.get("params", ())
    ]
    if (
        not isinstance(state, Mapping)
        or not isinstance(param_groups, Sequence)
        or isinstance(param_groups, (str, bytes, bytearray))
        or not param_groups
        or not parameters
    ):
        raise FullModelTrainingError("post_update_finiteness_state_invalid")
    optimizer_learning_rates: list[float] = []
    for group in param_groups:
        if not isinstance(group, Mapping) or isinstance(group.get("lr"), bool):
            raise FullModelTrainingError("post_update_learning_rate_invalid")
        try:
            learning_rate = float(group["lr"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise FullModelTrainingError("post_update_learning_rate_invalid") from exc
        if not math.isfinite(learning_rate) or learning_rate < 0:
            raise FullModelTrainingError("post_update_learning_rate_nonfinite")
        optimizer_learning_rates.append(learning_rate)
    get_last_lr = getattr(context.scheduler, "get_last_lr", None)
    try:
        scheduler_learning_rates = [float(item) for item in get_last_lr()]
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise FullModelTrainingError("post_update_scheduler_state_invalid") from exc
    if (
        not callable(get_last_lr)
        or len(scheduler_learning_rates) != len(optimizer_learning_rates)
        or any(not math.isfinite(item) or item < 0 for item in scheduler_learning_rates)
    ):
        raise FullModelTrainingError("post_update_scheduler_learning_rate_nonfinite")
    if scheduler_learning_rates != optimizer_learning_rates:
        raise FullModelTrainingError("post_update_learning_rate_mismatch")
    floating_state_tensors = 0
    for parameter in parameters:
        if not bool(torch.isfinite(parameter.detach()).all().item()):
            raise FullModelTrainingError("post_update_model_nonfinite")
        item = state.get(parameter)
        if not isinstance(item, Mapping):
            raise FullModelTrainingError("post_update_finiteness_state_invalid")
        error_bits = item.get("error_bits")
        try:
            master = reconstruct(parameter.detach(), error_bits)
        except Exception as exc:
            raise FullModelTrainingError("flashadamw_master_reconstruction_failed") from exc
        if not bool(torch.isfinite(master).all().item()):
            raise FullModelTrainingError("post_update_effective_master_nonfinite")
        for key in ("exp_avg", "exp_avg_sq"):
            moment = item.get(key)
            is_quantized = getattr(moment, "is_quantized", None)
            try:
                if not callable(is_quantized) or is_quantized() is not True:
                    raise FullModelTrainingError("post_update_optimizer_state_not_quantized")
                tensor = moment.scales
                quantized = moment.quantized
            except (AttributeError, AssertionError) as exc:
                raise FullModelTrainingError("post_update_optimizer_state_invalid") from exc
            expected_quantized_dtype = "torch.int8" if key == "exp_avg" else "torch.uint8"
            if (
                str(getattr(quantized, "dtype", "")) != expected_quantized_dtype
                or tuple(quantized.shape) != tuple(parameter.shape)
                or int(quantized.numel()) != int(parameter.numel())
                or str(getattr(tensor, "dtype", "")) != "torch.float16"
                or not callable(getattr(tensor, "is_floating_point", None))
                or int(tensor.numel()) <= 0
                or int(tensor.numel()) > int(parameter.numel())
            ):
                raise FullModelTrainingError("post_update_optimizer_state_invalid")
            if not tensor.is_floating_point() or not bool(torch.isfinite(tensor).all().item()):
                raise FullModelTrainingError("post_update_optimizer_state_nonfinite")
            floating_state_tensors += 1
    if floating_state_tensors != 2 * len(parameters):
        raise FullModelTrainingError("post_update_optimizer_state_invalid")
    return {
        "all_finite": True,
        "model_parameter_tensors": len(parameters),
        "effective_master_tensors": len(parameters),
        "optimizer_floating_state_tensors": floating_state_tensors,
        "optimizer_param_groups": len(param_groups),
        "optimizer_learning_rates": optimizer_learning_rates,
        "scheduler_learning_rates": scheduler_learning_rates,
    }


def _representative_master_snapshots(
    context: _RunContext, representatives: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        reconstruct = getattr(importlib.import_module("flashoptim"), "reconstruct_fp32_param")
    except (ImportError, AttributeError) as exc:
        raise FullModelTrainingError("flashadamw_master_reconstruction_missing") from exc
    state = getattr(context.optimizer, "state", {})
    snapshots: dict[str, Any] = {}
    for name, parameter in representatives.items():
        item = state.get(parameter, {}) if isinstance(state, Mapping) else {}
        error_bits = item.get("error_bits") if isinstance(item, Mapping) else None
        try:
            master = (
                parameter.detach().float()
                if error_bits is None
                else reconstruct(parameter.detach(), error_bits)
            )
            snapshots[name] = master.detach().cpu().clone()
        except Exception as exc:
            raise FullModelTrainingError("flashadamw_master_reconstruction_failed") from exc
    return snapshots


def _representative_parameters(model: Any) -> dict[str, Any]:
    named = list(model.named_parameters())
    head = next(((name, value) for name, value in named if name.startswith("score.")), None)
    base_candidates = [
        (name, value)
        for name, value in named
        if not name.startswith("score.")
    ]
    compact_norms = [
        (name, value)
        for name, value in base_candidates
        if "norm" in name.casefold() and int(value.numel()) <= 65_536
    ]
    base = min(
        compact_norms or base_candidates,
        key=lambda item: (int(item[1].numel()), item[0]),
        default=None,
    )
    if head is None or base is None:
        raise FullModelTrainingError("representative_parameters_missing")
    return {base[0]: base[1], head[0]: head[1]}


def _progress(
    stage: str,
    global_step: int,
    completed: list[str],
    stage_data: Any,
) -> dict[str, Any]:
    return {
        "stage": stage,
        "global_step": global_step,
        "stage_update": 1,
        "completed_stages": completed,
        "data_cursor": {
            "stage_fully_consumed": True,
            "binary_candidate_ids": list(stage_data.binary_candidate_ids),
            "pair_ids": list(stage_data.pair_ids),
        },
    }


def _require_expected_resume_progress(
    metadata: Mapping[str, Any], dataset: PortableTrainingDataset
) -> None:
    expected = _progress("C3", 3, list(STAGES), dataset.stage("C3"))
    if metadata.get("progress") != expected:
        raise FullModelTrainingError("checkpoint_resume_progress_mismatch")


def _new_output_root(path: Path) -> Path:
    output = Path(path)
    if output.exists() or output.is_symlink():
        raise FullModelTrainingError("training_output_already_exists")
    output.mkdir(mode=0o700, parents=True)
    return output


def _validate_model_contract(value: Any) -> Mapping[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != "rondo-publication-critic-plan060-model-contract-v1"
        or not isinstance(value.get("model"), Mapping)
        or not isinstance(value.get("input"), Mapping)
        or not isinstance(value.get("training_data"), Mapping)
        or not isinstance(value.get("optimizer"), Mapping)
        or not isinstance(value.get("route"), Mapping)
    ):
        raise FullModelTrainingError("model_contract_invalid")
    model = value["model"]
    optimizer = value["optimizer"]
    route = value["route"]
    if (
        model.get("repository") != MODEL_REPOSITORY
        or model.get("revision") != MODEL_REVISION
        or model.get("class") != "Qwen3ForSequenceClassification"
        or model.get("parameter_count") != 1_720_577_024
        or model.get("training_dtype") != "bfloat16"
        or model.get("num_labels") != 1
        or optimizer.get("package") != "flashoptim"
        or optimizer.get("class") != "flashoptim.FlashAdamW"
        or optimizer.get("quantize") is not True
        or optimizer.get("fused") is not True
        or optimizer.get("decouple_lr") is not False
        or optimizer.get("gradient_release") is not False
        or optimizer.get("master_weight_bits") != 32
        or optimizer.get("compress_state_dict") is not True
        or optimizer.get("check_numerics") is not True
        or optimizer.get("global_numerics_preflight") is not True
        or route.get("allowed_hardware") != list(ALLOWED_H100_HARDWARE)
        or route.get("winner_lock_required") is not True
        or route.get("gpu_count") != 1
        or route.get("minimum_vram_gb") != 80
        or route.get("full_parameter_training") is not True
        or route.get("optimizer_fallback") is not False
    ):
        raise FullModelTrainingError("model_contract_identity_invalid")
    return value


def _validate_commissioning_start_receipt(value: Any) -> None:
    _validate_winner_bound_receipt(value)
    if (
        not isinstance(value, Mapping)
        or value.get("schema")
        != "rondo-publication-critic-commissioning-start-receipt-v1"
        or value.get("status") != "commissioning_only_pending_new_process_resume"
        or value.get("global_step") != 3
        or value.get("resume_required")
        != {"stage": "C3", "updates": 1, "new_os_process": True}
        or not valid_full_parameter_coverage(value.get("coverage"))
        or [item.get("stage") for item in value.get("stages", ())] != list(STAGES)
        or not _valid_stage_receipts_for_commissioning(value.get("stages"))
        or not start_receipt_evidence_matches_coverage(value)
        or not valid_checkpoint_receipt(
            value.get("checkpoint"), status="saved_manifest_built"
        )
        or value["checkpoint"].get("process") != value.get("process")
        or not _valid_optimizer_checkpoint_receipt(
            value.get("optimizer_pre_checkpoint")
        )
        or not _valid_start_timing_receipt(value.get("timing"))
    ):
        raise FullModelTrainingError("commissioning_start_receipt_invalid")


def _validate_commissioning_resume_receipt(value: Any) -> None:
    _validate_winner_bound_receipt(value)
    stage = value.get("continued_stage") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or value.get("schema")
        != "rondo-publication-critic-commissioning-resume-receipt-v1"
        or value.get("status") != "commissioning_only_complete_not_formal_evidence"
        or value.get("new_os_process_confirmed") is not True
        or value.get("restored_from_global_step") != 3
        or value.get("continued_global_step") != 4
        or not valid_full_parameter_coverage(value.get("coverage"))
        or not isinstance(stage, Mapping)
        or stage.get("stage") != "C3"
        or stage.get("component_items")
        != {"binary": 6, "boundary": 1, "within_pass": 1}
        or not valid_stage_receipt(
            stage,
            stage="C3",
            global_step=4,
            expected_components={"binary": 6, "boundary": 1, "within_pass": 1},
        )
        or not valid_checkpoint_receipt(value.get("checkpoint"), status="verified")
        or value["checkpoint"].get("process") != value.get("start_process")
        or not _valid_compressed_optimizer_state_receipt(
            value.get("restored_optimizer_state")
        )
        or not _valid_runtime_optimizer_state_receipt(
            value.get("restored_optimizer_runtime")
        )
        or not resume_receipt_evidence_matches_coverage(value)
        or not _valid_resume_timing_receipt(value.get("timing"))
    ):
        raise FullModelTrainingError("commissioning_resume_receipt_invalid")


def _is_nonnegative_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _valid_stage_receipts_for_commissioning(value: Any) -> bool:
    expected = {
        "C1": {"binary": 6},
        "C2": {"binary": 6, "boundary": 1},
        "C3": {"binary": 6, "boundary": 1, "within_pass": 1},
    }
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 3
        and all(
            valid_stage_receipt(
                item,
                stage=stage,
                global_step=index,
                expected_components=expected[stage],
            )
            for index, (stage, item) in enumerate(zip(STAGES, value), start=1)
        )
    )


def _valid_runtime_prepare_receipt(value: Any) -> bool:
    expected = {
        "runtime_prepare_seconds",
        "heavy_import_seconds",
        "tokenizer_load_seconds",
        "model_load_seconds",
        "data_tokenization_seconds",
        "optimizer_init_seconds",
        "optimizer_numerics_preflight_seconds",
        "optimizer_numerics_preflight",
    }
    return (
        isinstance(value, Mapping)
        and set(value) == expected
        and all(
            _is_nonnegative_finite(value[item])
            for item in expected - {"optimizer_numerics_preflight"}
        )
        and valid_global_numerics_preflight(
            value.get("optimizer_numerics_preflight")
        )
    )


def _valid_optimizer_checkpoint_receipt(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value)
        == {
            "check_numerics",
            "recompute_param_stats_called",
            "elapsed_seconds",
            "compressed_state",
        }
        and value.get("check_numerics") is True
        and value.get("recompute_param_stats_called") is True
        and _is_nonnegative_finite(value.get("elapsed_seconds"))
        and _valid_compressed_optimizer_state_receipt(value.get("compressed_state"))
    )


def _valid_compressed_optimizer_state_receipt(value: Any) -> bool:
    required = {
        "error_bits",
        "exp_avg::quantized",
        "exp_avg::scales",
        "exp_avg_sq::quantized",
        "exp_avg_sq::scales",
        "step",
    }
    return (
        isinstance(value, Mapping)
        and value.get("compressed_moment_state_complete") is True
        and isinstance(value.get("state_entries"), int)
        and not isinstance(value["state_entries"], bool)
        and value["state_entries"] > 0
        and value.get("expected_state_entries") == value["state_entries"]
        and value.get("optimizer_parameter_references") == value["state_entries"]
        and value.get("optimizer_step") == 3
        and value.get("parameter_shapes_checked") is True
        and isinstance(value.get("state_dtype_counts"), Mapping)
        and set(value.get("required_state_keys", ())) == required
        and isinstance(value.get("required_key_counts"), Mapping)
        and set(value["required_key_counts"]) == required
        and all(
            count == value["state_entries"]
            for count in value["required_key_counts"].values()
        )
    )


def _valid_runtime_optimizer_state_receipt(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("state_entries") == value.get("expected_state_entries")
        and isinstance(value.get("state_entries"), int)
        and not isinstance(value["state_entries"], bool)
        and value["state_entries"] > 0
        and value.get("optimizer_step") == 3
        and value.get("error_bits_dtype") == "torch.int16"
        and value.get("moment_and_error_shapes_match_parameters") is True
    )


def _valid_start_timing_receipt(value: Any) -> bool:
    expected = {
        "process_startup_seconds",
        "runtime_prepare",
        "first_step_jit_cold_seconds",
        "steady_stage_step_seconds",
        "optimizer_pre_checkpoint_seconds",
        "checkpoint_save_seconds",
        "process_elapsed_through_checkpoint_seconds",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        return False
    steady = value.get("steady_stage_step_seconds")
    return (
        _valid_runtime_prepare_receipt(value.get("runtime_prepare"))
        and isinstance(steady, Mapping)
        and set(steady) == {"C2", "C3"}
        and all(_is_nonnegative_finite(item) for item in steady.values())
        and all(
            _is_nonnegative_finite(value[field])
            for field in expected - {"runtime_prepare", "steady_stage_step_seconds"}
        )
    )


def _valid_resume_timing_receipt(value: Any) -> bool:
    expected = {
        "process_startup_seconds",
        "runtime_prepare",
        "checkpoint_verify_seconds",
        "checkpoint_model_load_seconds",
        "checkpoint_state_load_seconds",
        "optimizer_scheduler_rng_restore_seconds",
        "resume_verify_load_restore_seconds",
        "continued_step_seconds",
        "process_elapsed_through_continue_seconds",
    }
    return (
        isinstance(value, Mapping)
        and set(value) == expected
        and _valid_runtime_prepare_receipt(value.get("runtime_prepare"))
        and all(
            _is_nonnegative_finite(value[field])
            for field in expected - {"runtime_prepare"}
        )
    )


def _validate_loaded_model(model: Any, contract: Mapping[str, Any]) -> None:
    config = model.config
    expected = contract["model"]
    if (
        type(model).__name__ != expected["class"]
        or config.model_type != "qwen3"
        or config.num_labels != expected["num_labels"]
        or config.pad_token_id != expected["pad_token_id"]
        or config.eos_token_id != expected["eos_token_id"]
        or config.bos_token_id != expected["bos_token_id"]
    ):
        raise FullModelTrainingError("loaded_model_contract_invalid")
    actual_count = sum(int(parameter.numel()) for parameter in model.parameters())
    if actual_count != expected["parameter_count"]:
        raise FullModelTrainingError("loaded_model_parameter_count_invalid")
    for parameter in model.parameters():
        parameter.requires_grad_(True)


def _flashadamw_class(model_contract: Mapping[str, Any]) -> Any:
    optimizer = model_contract["optimizer"]
    try:
        module = importlib.import_module("flashoptim")
        cls = getattr(module, "FlashAdamW")
    except (ImportError, AttributeError) as exc:
        raise FullModelTrainingError("flashadamw_runtime_missing") from exc
    if (
        cls.__module__ != "flashoptim.optimizers"
        or cls.__name__ != "FlashAdamW"
        or importlib.metadata.version("flashoptim") != optimizer["version"]
    ):
        raise FullModelTrainingError("flashadamw_runtime_identity_mismatch")
    return cls


def _flashadamw_numerics_error_class(model_contract: Mapping[str, Any]) -> Any:
    optimizer = model_contract["optimizer"]
    try:
        public_module = importlib.import_module("flashoptim")
        defining_module = importlib.import_module("flashoptim.optimizers")
        public_error = getattr(public_module, "NumericsError")
        defining_error = getattr(defining_module, "NumericsError")
    except (ImportError, AttributeError) as exc:
        raise FullModelTrainingError("flashadamw_numerics_error_missing") from exc
    if (
        public_error is not defining_error
        or not isinstance(defining_error, type)
        or not issubclass(defining_error, RuntimeError)
        or defining_error.__module__ != "flashoptim.optimizers"
        or defining_error.__name__ != "NumericsError"
        or importlib.metadata.version("flashoptim") != optimizer["version"]
    ):
        raise FullModelTrainingError("flashadamw_numerics_error_identity_mismatch")
    return defining_error


def _verify_model_snapshot(snapshot: Path, portable: Mapping[str, Any]) -> None:
    root = Path(snapshot)
    if root.is_symlink() or not root.is_dir():
        raise FullModelTrainingError("model_snapshot_unsafe")
    resolved = root.resolve()
    try:
        cache_root = resolved.parent.parent.resolve(strict=True)
    except OSError as exc:
        raise FullModelTrainingError("model_snapshot_cache_missing") from exc
    expected = dict(portable["tokenizer_file_sha256"])
    expected[portable["model"]["weight_file"]] = portable["model"]["weight_sha256"]
    expected[portable["model"]["config_file"]] = portable["model"]["config_sha256"]
    for relative, digest in expected.items():
        logical = resolved / relative
        try:
            asset = logical.resolve(strict=True)
        except OSError as exc:
            raise FullModelTrainingError("model_snapshot_asset_missing") from exc
        if not asset.is_file() or not asset.is_relative_to(cache_root):
            raise FullModelTrainingError("model_snapshot_asset_unsafe")
        if sha256_file(asset) != digest:
            raise FullModelTrainingError("model_snapshot_asset_hash_mismatch")


def _heavy_dependencies() -> tuple[Any, Any]:
    try:
        torch = importlib.import_module("torch")
        transformers = importlib.import_module("transformers")
    except ImportError as exc:
        raise FullModelTrainingError("training_dependency_missing") from exc
    return torch, transformers
