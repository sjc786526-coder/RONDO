"""Small, body-free contracts shared by the Plan 060 training facilities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Any, NoReturn


BUNDLE_SCHEMA = "rondo-publication-critic-full-model-bundle-v1"
PORTABLE_INPUT_SCHEMA = "rondo-publication-critic-portable-input-v1"
RECIPE_SCHEMA = "rondo-publication-critic-plan060-recipe-v1"
DEPENDENCY_SCHEMA = "rondo-publication-critic-full-model-dependencies-v1"
CHECKPOINT_SCHEMA = "rondo-publication-critic-full-model-checkpoint-v1"
SMOKE_BUNDLE_SHA256 = (
    "5aba49c0eb0cb01df02ff3eecbe527234c3af884331742507c56852ccd0e9839"
)
MODEL_REPOSITORY = "Skywork/Skywork-Reward-V2-Qwen3-1.7B"
MODEL_REVISION = "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc"
STAGES = ("C1", "C2", "C3")
SOURCE_FILES = (
    "membership.json",
    "packets.jsonl",
    "pairs.jsonl",
    "supervision.jsonl",
)


class FullModelTrainingError(RuntimeError):
    """A stable, body-free failure raised by the qualification runtime."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}: {detail}")


@dataclass(frozen=True)
class ProcessIdentity:
    instance_id: str
    pid: int
    parent_pid: int
    started_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "pid": self.pid,
            "parent_pid": self.parent_pid,
            "started_at": self.started_at,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise FullModelTrainingError("json_not_canonicalizable") from exc


def pretty_json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise FullModelTrainingError("json_not_serializable") from exc


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path, *, maximum_bytes: int | None = None) -> str:
    file_path = regular_file(path, maximum_bytes=maximum_bytes)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def regular_file(path: Path, *, maximum_bytes: int | None = None) -> Path:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise FullModelTrainingError("regular_file_missing") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise FullModelTrainingError("regular_file_required")
    if maximum_bytes is not None and info.st_size > maximum_bytes:
        raise FullModelTrainingError("regular_file_too_large")
    return path


def safe_directory(path: Path) -> Path:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise FullModelTrainingError("directory_missing") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise FullModelTrainingError("directory_unsafe")
    return path.resolve()


def safe_relative(value: str) -> PurePosixPath:
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise FullModelTrainingError("relative_path_unsafe")
    return pure


def read_json(path: Path, *, maximum_bytes: int = 16 * 1024 * 1024) -> Any:
    file_path = regular_file(path, maximum_bytes=maximum_bytes)
    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullModelTrainingError("json_file_invalid") from exc


def write_exclusive(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    if path.exists() or path.is_symlink():
        raise FullModelTrainingError("output_already_exists")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("write did not progress")
            view = view[written:]
        os.fsync(descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def require_sha256(value: Any, code: str = "sha256_invalid") -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FullModelTrainingError(code)
    return value


def require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FullModelTrainingError(code)
    return value


def require_positive_int(value: Any, code: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise FullModelTrainingError(code)
    return value


def require_nonnegative_number(value: Any, code: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise FullModelTrainingError(code)
    result = float(value)
    if result != result or result in {float("inf"), float("-inf")}:
        raise FullModelTrainingError(code)
    return result


def validate_recipe(value: Any, *, require_frozen: bool) -> dict[str, Any]:
    del require_frozen  # Formality is bound by the caller's frozen file hash.
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("recipe_not_object")
    required = {
        "schema",
        "seed",
        "stage_order",
        "updates_per_stage",
        "resume_stage",
        "resume_updates",
        "binary_micro_batch_size",
        "pair_micro_batch_size",
        "gradient_accumulation",
        "binary_loss",
        "pair_loss",
        "component_weights",
        "learning_rate",
        "weight_decay",
        "betas",
        "epsilon",
        "gradient_clip_norm",
        "scheduler",
        "activation_checkpointing",
        "attention_backend",
        "loader_workers",
        "checkpoint",
    }
    if set(value) != required or value.get("schema") != RECIPE_SCHEMA:
        raise FullModelTrainingError("recipe_contract_invalid")
    if (
        not isinstance(value.get("seed"), int)
        or isinstance(value["seed"], bool)
        or list(value.get("stage_order", ())) != list(STAGES)
        or value.get("updates_per_stage") != {"C1": 1, "C2": 1, "C3": 1}
        or value.get("resume_stage") != "C3"
        or value.get("resume_updates") != 1
        or value.get("gradient_accumulation")
        != "one_deterministic_full_stage_update"
        or value.get("binary_loss")
        != "softplus(-signed_target*logits[:,0])"
        or value.get("pair_loss") != "softplus(dispreferred-preferred)"
    ):
        raise FullModelTrainingError("recipe_stage_contract_invalid")
    require_positive_int(
        value["binary_micro_batch_size"], "recipe_binary_micro_batch_invalid"
    )
    if (
        value.get("pair_micro_batch_size") != 2
        or not isinstance(value.get("loader_workers"), int)
        or isinstance(value["loader_workers"], bool)
        or value["loader_workers"] < 0
        or not isinstance(value.get("activation_checkpointing"), bool)
        or not isinstance(value.get("attention_backend"), str)
        or not value["attention_backend"]
    ):
        raise FullModelTrainingError("recipe_runtime_invalid")
    weights = value.get("component_weights")
    if (
        not isinstance(weights, Mapping)
        or set(weights) != set(STAGES)
        or set(weights["C1"]) != {"binary"}
        or set(weights["C2"]) != {"binary", "boundary"}
        or set(weights["C3"]) != {"binary", "boundary", "within_pass"}
    ):
        raise FullModelTrainingError("recipe_component_weights_invalid")
    for stage_weights in weights.values():
        numbers = [
            require_nonnegative_number(item, "recipe_component_weight_invalid")
            for item in stage_weights.values()
        ]
        if any(item <= 0 for item in numbers) or abs(sum(numbers) - 1.0) > 1e-9:
            raise FullModelTrainingError("recipe_component_weights_invalid")
    learning_rate = require_nonnegative_number(
        value["learning_rate"], "recipe_learning_rate_invalid"
    )
    epsilon = require_nonnegative_number(value["epsilon"], "recipe_epsilon_invalid")
    if learning_rate <= 0 or epsilon <= 0:
        raise FullModelTrainingError("recipe_optimizer_hyperparameter_invalid")
    require_nonnegative_number(value["weight_decay"], "recipe_weight_decay_invalid")
    betas = value.get("betas")
    if (
        not isinstance(betas, Sequence)
        or isinstance(betas, (str, bytes, bytearray))
        or len(betas) != 2
        or any(
            require_nonnegative_number(beta, "recipe_betas_invalid") >= 1
            for beta in betas
        )
    ):
        raise FullModelTrainingError("recipe_betas_invalid")
    require_nonnegative_number(
        value["gradient_clip_norm"], "recipe_gradient_clip_invalid"
    )
    require_text(value["scheduler"], "recipe_scheduler_invalid")
    checkpoint = value.get("checkpoint")
    if (
        not isinstance(checkpoint, Mapping)
        or set(checkpoint)
        != {
            "model_state",
            "optimizer_state",
            "scheduler_state",
            "python_rng",
            "numpy_rng_if_loaded",
            "torch_cpu_rng",
            "torch_cuda_rng",
            "stage_and_cursor",
            "identity",
        }
        or checkpoint.get("model_state") != "bf16_full_state_dict"
        or checkpoint.get("optimizer_state")
        != "flashadamw_compressed_state_dict"
        or any(
            checkpoint.get(field) is not True
            for field in (
                "scheduler_state",
                "python_rng",
                "numpy_rng_if_loaded",
                "torch_cpu_rng",
                "torch_cuda_rng",
                "stage_and_cursor",
                "identity",
            )
        )
    ):
        raise FullModelTrainingError("recipe_checkpoint_invalid")
    return json.loads(json.dumps(value))


def validate_dependency_identity(value: Any, *, require_frozen: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("dependency_identity_not_object")
    expected = {
        "schema",
        "status",
        "packages",
        "python_version",
        "cuda_version",
        "container_image",
        "flashoptim",
        "complete_freeze_sha256",
    }
    expected_status = "formal_frozen" if require_frozen else "commissioning_observed"
    required_packages = {
        "torch",
        "transformers",
        "flashoptim",
        "safetensors",
        "triton",
        "tokenizers",
        "huggingface-hub",
        "numpy",
    }
    if (
        set(value) != expected
        or value.get("schema") != DEPENDENCY_SCHEMA
        or value.get("status") != expected_status
        or not isinstance(value.get("packages"), Mapping)
        or set(value["packages"]) != required_packages
        or any(
            not isinstance(name, str)
            or not name
            or not isinstance(version, str)
            or not version
            for name, version in value["packages"].items()
        )
    ):
        raise FullModelTrainingError("dependency_identity_invalid")
    for field in ("python_version", "cuda_version", "container_image"):
        require_text(value[field], "dependency_identity_invalid")
    complete_freeze = value["complete_freeze_sha256"]
    if require_frozen:
        require_sha256(complete_freeze, "dependency_complete_freeze_invalid")
    elif complete_freeze is not None:
        require_sha256(complete_freeze, "dependency_complete_freeze_invalid")
    flash = value["flashoptim"]
    if (
        not isinstance(flash, Mapping)
        or set(flash)
        != {
            "distribution",
            "version",
            "import_path",
            "defining_module",
            "class",
            "source_revision",
        }
        or flash.get("distribution") != "flashoptim"
        or flash.get("import_path") != "flashoptim.FlashAdamW"
        or flash.get("defining_module") != "flashoptim.optimizers"
        or flash.get("class") != "FlashAdamW"
        or flash.get("version") != value["packages"].get("flashoptim")
        or any(
            not isinstance(flash.get(field), str) or not flash[field]
            for field in (
                "distribution",
                "version",
                "import_path",
                "defining_module",
                "source_revision",
            )
        )
    ):
        raise FullModelTrainingError("dependency_flashoptim_invalid")
    return json.loads(json.dumps(value))


def validate_formal_start_receipt(value: Any) -> dict[str, Any]:
    expected = {
        "schema",
        "status",
        "created_at",
        "process",
        "identity",
        "coverage",
        "stages",
        "checkpoint",
        "optimizer_pre_checkpoint",
        "global_step",
        "resume_required",
        "timing",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("schema")
        != "rondo-publication-critic-formal-start-receipt-v1"
        or value.get("status") != "pending_new_process_resume"
        or value.get("global_step") != 3
        or value.get("resume_required")
        != {"stage": "C3", "updates": 1, "new_os_process": True}
        or not valid_full_parameter_coverage(value.get("coverage"))
        or not _valid_process_identity(value.get("process"))
        or not isinstance(value.get("stages"), Sequence)
        or [stage.get("stage") for stage in value["stages"] if isinstance(stage, Mapping)]
        != list(STAGES)
        or any(stage.get("optimizer_updates") != 1 for stage in value["stages"])
        or not _valid_stage_receipts(value.get("stages"))
        or not start_receipt_evidence_matches_coverage(value)
        or not valid_checkpoint_receipt(
            value.get("checkpoint"), status="saved_manifest_built"
        )
        or value["checkpoint"].get("process") != value.get("process")
        or not _valid_optimizer_checkpoint_evidence(
            value.get("optimizer_pre_checkpoint")
        )
        or not _valid_start_timing(value.get("timing"))
    ):
        raise FullModelTrainingError("formal_start_receipt_invalid")
    return json.loads(json.dumps(value))


def validate_formal_pending_receipt(value: Any) -> dict[str, Any]:
    expected = {
        "schema",
        "status",
        "created_at",
        "identity",
        "start_process",
        "resume_process",
        "new_os_process_confirmed",
        "restored_from_global_step",
        "continued_global_step",
        "continued_stage",
        "coverage",
        "restored_optimizer_state",
        "restored_optimizer_runtime",
        "checkpoint",
        "formal_start_receipt_sha256",
        "timing",
        "billing",
        "remote_resource_terminal_state",
        "qualification_conclusion",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("schema")
        != "rondo-publication-critic-formal-training-pending-v1"
        or value.get("status") != "pending_billing_and_resource_cleanup"
        or value.get("new_os_process_confirmed") is not True
        or value.get("restored_from_global_step") != 3
        or value.get("continued_global_step") != 4
        or value.get("billing") is not None
        or value.get("remote_resource_terminal_state") is not None
        or value.get("qualification_conclusion") is not None
        or not valid_full_parameter_coverage(value.get("coverage"))
        or not isinstance(value.get("formal_start_receipt_sha256"), str)
        or len(value["formal_start_receipt_sha256"]) != 64
        or not valid_checkpoint_receipt(value.get("checkpoint"), status="verified")
        or not _valid_compressed_optimizer_state(value.get("restored_optimizer_state"))
        or not _valid_runtime_optimizer_state(value.get("restored_optimizer_runtime"))
        or not resume_receipt_evidence_matches_coverage(value)
        or not _valid_resume_timing(value.get("timing"))
    ):
        raise FullModelTrainingError("formal_pending_receipt_invalid")
    start = value.get("start_process")
    resumed = value.get("resume_process")
    stage = value.get("continued_stage")
    if (
        not isinstance(start, Mapping)
        or not isinstance(resumed, Mapping)
        or not _valid_process_identity(start)
        or not _valid_process_identity(resumed)
        or start.get("pid") == resumed.get("pid")
        or start.get("instance_id") == resumed.get("instance_id")
        or not isinstance(stage, Mapping)
        or stage.get("stage") != "C3"
        or stage.get("global_step") != 4
        or stage.get("optimizer_updates") != 1
        or stage.get("component_items")
        != {"binary": 6, "boundary": 1, "within_pass": 1}
        or value["checkpoint"].get("process") != start
        or not valid_stage_receipt(
            stage,
            stage="C3",
            global_step=4,
            expected_components={"binary": 6, "boundary": 1, "within_pass": 1},
        )
    ):
        raise FullModelTrainingError("formal_pending_resume_evidence_invalid")
    return json.loads(json.dumps(value))


def valid_full_parameter_coverage(value: Any) -> bool:
    expected = {
        "named_parameter_tensors",
        "parameter_count",
        "floating_parameter_count",
        "trainable_parameter_count",
        "optimizer_parameter_tensors",
        "optimizer_parameter_count",
        "dtype_counts",
        "device_counts",
        "parameter_order_sha256",
        "all_requires_grad",
        "optimizer_exact_coverage",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        return False
    tensor_count = value.get("named_parameter_tensors")
    parameter_count = value.get("parameter_count")
    if (
        not isinstance(tensor_count, int)
        or isinstance(tensor_count, bool)
        or tensor_count <= 0
        or value.get("optimizer_parameter_tensors") != tensor_count
        or not isinstance(parameter_count, int)
        or isinstance(parameter_count, bool)
        or parameter_count != 1_720_577_024
        or value.get("floating_parameter_count") != parameter_count
        or value.get("trainable_parameter_count") != parameter_count
        or value.get("optimizer_parameter_count") != parameter_count
        or value.get("all_requires_grad") is not True
        or value.get("optimizer_exact_coverage") is not True
    ):
        return False
    dtype_counts = value.get("dtype_counts")
    device_counts = value.get("device_counts")
    return (
        dtype_counts == {"torch.bfloat16": parameter_count}
        and device_counts == {"cuda:0": parameter_count}
        and _is_sha256(value.get("parameter_order_sha256"))
    )


def valid_checkpoint_receipt(value: Any, *, status: str) -> bool:
    expected = {
        "schema",
        "status",
        "checkpoint_manifest_sha256",
        "identity_sha256",
        "global_step",
        "stage",
        "process",
        "bytes",
        "file_count",
    }
    return (
        status in {"saved_manifest_built", "verified"}
        and isinstance(value, Mapping)
        and set(value) == expected
        and value.get("schema") == CHECKPOINT_SCHEMA
        and value.get("status") == status
        and _is_sha256(value.get("checkpoint_manifest_sha256"))
        and _is_sha256(value.get("identity_sha256"))
        and value.get("global_step") == 3
        and value.get("stage") == "C3"
        and _valid_process_identity(value.get("process"))
        and isinstance(value.get("bytes"), int)
        and not isinstance(value["bytes"], bool)
        and value["bytes"] > 0
        and isinstance(value.get("file_count"), int)
        and not isinstance(value["file_count"], bool)
        and value["file_count"] > 0
    )


def start_receipt_evidence_matches_coverage(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    coverage = value.get("coverage")
    stages = value.get("stages")
    optimizer = value.get("optimizer_pre_checkpoint")
    if (
        not valid_full_parameter_coverage(coverage)
        or not isinstance(stages, Sequence)
        or isinstance(stages, (str, bytes, bytearray))
        or not isinstance(optimizer, Mapping)
        or not isinstance(optimizer.get("compressed_state"), Mapping)
    ):
        return False
    model_tensors = coverage["named_parameter_tensors"]
    optimizer_tensors = coverage["optimizer_parameter_tensors"]
    return (
        all(_stage_finiteness_count(item) == model_tensors for item in stages)
        and _numerics_preflight_matches_coverage_and_stages(
            value, coverage=coverage, stages=stages
        )
        and optimizer["compressed_state"].get("state_entries") == optimizer_tensors
        and optimizer["compressed_state"].get("expected_state_entries")
        == optimizer_tensors
    )


def resume_receipt_evidence_matches_coverage(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    coverage = value.get("coverage")
    compressed = value.get("restored_optimizer_state")
    runtime = value.get("restored_optimizer_runtime")
    if (
        not valid_full_parameter_coverage(coverage)
        or not isinstance(compressed, Mapping)
        or not isinstance(runtime, Mapping)
    ):
        return False
    optimizer_tensors = coverage["optimizer_parameter_tensors"]
    return (
        _stage_finiteness_count(value.get("continued_stage"))
        == coverage["named_parameter_tensors"]
        and _numerics_preflight_matches_coverage_and_stages(
            value, coverage=coverage, stages=[value.get("continued_stage")]
        )
        and compressed.get("state_entries") == optimizer_tensors
        and compressed.get("expected_state_entries") == optimizer_tensors
        and runtime.get("state_entries") == optimizer_tensors
        and runtime.get("expected_state_entries") == optimizer_tensors
    )


def _numerics_preflight_matches_coverage_and_stages(
    value: Mapping[str, Any],
    *,
    coverage: Mapping[str, Any],
    stages: Sequence[Any],
) -> bool:
    timing = value.get("timing")
    runtime_prepare = (
        timing.get("runtime_prepare") if isinstance(timing, Mapping) else None
    )
    preflight = (
        runtime_prepare.get("optimizer_numerics_preflight")
        if isinstance(runtime_prepare, Mapping)
        else None
    )
    if (
        not valid_global_numerics_preflight(preflight)
        or preflight.get("parameter_tensors_checked")
        != coverage.get("optimizer_parameter_tensors")
    ):
        return False
    configured = float(preflight["configured_learning_rate"])
    for stage in stages:
        finiteness = (
            stage.get("post_update_finiteness")
            if isinstance(stage, Mapping)
            else None
        )
        optimizer_lrs = (
            finiteness.get("optimizer_learning_rates")
            if isinstance(finiteness, Mapping)
            else None
        )
        scheduler_lrs = (
            finiteness.get("scheduler_learning_rates")
            if isinstance(finiteness, Mapping)
            else None
        )
        if (
            not isinstance(optimizer_lrs, list)
            or optimizer_lrs != [configured]
            or scheduler_lrs != [configured]
        ):
            return False
    return True


def _stage_finiteness_count(value: Any) -> int | None:
    if not isinstance(value, Mapping):
        return None
    finiteness = value.get("post_update_finiteness")
    if not isinstance(finiteness, Mapping):
        return None
    return finiteness.get("model_parameter_tensors")


def _valid_process_identity(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"instance_id", "pid", "parent_pid", "started_at"}
        and isinstance(value.get("instance_id"), str)
        and bool(value["instance_id"])
        and isinstance(value.get("pid"), int)
        and not isinstance(value["pid"], bool)
        and value["pid"] > 0
        and isinstance(value.get("parent_pid"), int)
        and not isinstance(value["parent_pid"], bool)
        and value["parent_pid"] >= 0
        and isinstance(value.get("started_at"), str)
        and bool(value["started_at"])
    )


def valid_distinct_process_identities(start: Any, resumed: Any) -> bool:
    """Return whether two well-formed process receipts prove a new process."""

    return (
        _valid_process_identity(start)
        and _valid_process_identity(resumed)
        and start.get("pid") != resumed.get("pid")
        and start.get("instance_id") != resumed.get("instance_id")
    )


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _finite_nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _valid_stage_receipts(value: Any) -> bool:
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


def valid_stage_receipt(
    value: Any,
    *,
    stage: str,
    global_step: int,
    expected_components: Mapping[str, int],
) -> bool:
    if (
        not isinstance(value, Mapping)
        or value.get("stage") != stage
        or value.get("global_step") != global_step
        or value.get("optimizer_updates") != 1
        or value.get("optimizer_step") != global_step
        or value.get("component_items") != dict(expected_components)
        or value.get("all_losses_finite") is not True
        or not _finite_nonnegative(value.get("elapsed_seconds"))
        or not _finite_nonnegative(value.get("tokens_per_second"))
        or not isinstance(value.get("tokens"), int)
        or isinstance(value["tokens"], bool)
        or value["tokens"] <= 0
    ):
        return False
    losses = value.get("component_mean_loss")
    contributions = value.get("component_gradient_contributions")
    updates = value.get("representative_updates")
    gradient = value.get("gradient")
    post_update = value.get("post_update_finiteness")
    if (
        not isinstance(losses, Mapping)
        or set(losses) != set(expected_components)
        or not all(_finite_number(item) for item in losses.values())
        or not isinstance(contributions, Mapping)
        or set(contributions) != set(expected_components)
        or not isinstance(updates, Mapping)
        or len(updates) != 2
        or not isinstance(gradient, Mapping)
        or gradient.get("global_finite") is not True
        or gradient.get("global_nonzero") is not True
        or not _valid_post_update_finiteness(post_update)
    ):
        return False
    representative_names = set(updates)
    if (
        sum(name.startswith("score.") for name in representative_names) != 1
        or sum(not name.startswith("score.") for name in representative_names) != 1
        or any(
            not isinstance(item, Mapping)
            or item.get("effective_master_changed") is not True
            or not isinstance(item.get("bf16_visible_changed"), bool)
            or not isinstance(item.get("numel"), int)
            or isinstance(item["numel"], bool)
            or item["numel"] <= 0
            for item in updates.values()
        )
    ):
        return False
    for component in expected_components:
        evidence = contributions[component]
        if (
            not isinstance(evidence, Mapping)
            or set(evidence) != representative_names
            or any(
                not isinstance(item, Mapping)
                or item.get("finite") is not True
                or item.get("nonzero") is not True
                or not isinstance(item.get("nonzero_elements"), int)
                or isinstance(item["nonzero_elements"], bool)
                or item["nonzero_elements"] <= 0
                or not isinstance(item.get("numel"), int)
                or isinstance(item["numel"], bool)
                or item["numel"] <= 0
                or not isinstance(item.get("backward_calls"), int)
                or isinstance(item["backward_calls"], bool)
                or item["backward_calls"] <= 0
                for item in evidence.values()
            )
        ):
            return False
    return True


def _valid_post_update_finiteness(value: Any) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "all_finite",
            "model_parameter_tensors",
            "effective_master_tensors",
            "optimizer_floating_state_tensors",
            "optimizer_param_groups",
            "optimizer_learning_rates",
            "scheduler_learning_rates",
        }
    ):
        return False
    tensors = value.get("model_parameter_tensors")
    param_groups = value.get("optimizer_param_groups")
    optimizer_learning_rates = value.get("optimizer_learning_rates")
    scheduler_learning_rates = value.get("scheduler_learning_rates")
    return (
        value.get("all_finite") is True
        and isinstance(tensors, int)
        and not isinstance(tensors, bool)
        and tensors > 0
        and value.get("effective_master_tensors") == tensors
        and value.get("optimizer_floating_state_tensors") == 2 * tensors
        and isinstance(param_groups, int)
        and not isinstance(param_groups, bool)
        and param_groups > 0
        and isinstance(optimizer_learning_rates, list)
        and len(optimizer_learning_rates) == param_groups
        and all(_finite_nonnegative(item) for item in optimizer_learning_rates)
        and scheduler_learning_rates == optimizer_learning_rates
    )


def _finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _valid_runtime_prepare(value: Any) -> bool:
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
            _finite_nonnegative(value[item])
            for item in expected - {"optimizer_numerics_preflight"}
        )
        and valid_global_numerics_preflight(
            value.get("optimizer_numerics_preflight")
        )
    )


def valid_global_numerics_preflight(value: Any) -> bool:
    expected = {
        "schema",
        "check_numerics",
        "recompute_param_stats_called",
        "parameter_tensors_checked",
        "configured_learning_rate",
        "failed_parameter_tensors",
        "required_power_of_two_learning_rate",
        "all_parameters_passed",
        "elapsed_seconds",
    }
    return (
        isinstance(value, Mapping)
        and set(value) == expected
        and value.get("schema") == "rondo-flashadamw-global-numerics-preflight-v1"
        and value.get("check_numerics") is True
        and value.get("recompute_param_stats_called") is True
        and isinstance(value.get("parameter_tensors_checked"), int)
        and not isinstance(value.get("parameter_tensors_checked"), bool)
        and value["parameter_tensors_checked"] > 0
        and value.get("failed_parameter_tensors") == 0
        and value.get("all_parameters_passed") is True
        and _finite_nonnegative(value.get("configured_learning_rate"))
        and float(value["configured_learning_rate"]) > 0
        and value.get("required_power_of_two_learning_rate")
        == value["configured_learning_rate"]
        and _finite_nonnegative(value.get("elapsed_seconds"))
    )


def _valid_optimizer_checkpoint_evidence(value: Any) -> bool:
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
        and _finite_nonnegative(value.get("elapsed_seconds"))
        and _valid_compressed_optimizer_state(value.get("compressed_state"))
    )


def _valid_compressed_optimizer_state(value: Any) -> bool:
    required_keys = {
        "error_bits",
        "exp_avg::quantized",
        "exp_avg::scales",
        "exp_avg_sq::quantized",
        "exp_avg_sq::scales",
        "step",
    }
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "state_entries",
            "expected_state_entries",
            "required_state_keys",
            "required_key_counts",
            "optimizer_parameter_references",
            "optimizer_step",
            "state_dtype_counts",
            "parameter_shapes_checked",
            "compressed_moment_state_complete",
        }
        or value.get("compressed_moment_state_complete") is not True
        or not isinstance(value.get("state_entries"), int)
        or isinstance(value["state_entries"], bool)
        or value["state_entries"] <= 0
        or value.get("expected_state_entries") != value["state_entries"]
        or value.get("optimizer_parameter_references") != value["state_entries"]
        or value.get("optimizer_step") != 3
        or value.get("parameter_shapes_checked") is not True
        or not isinstance(value.get("state_dtype_counts"), Mapping)
        or set(value.get("required_state_keys", ())) != required_keys
        or not isinstance(value.get("required_key_counts"), Mapping)
        or set(value["required_key_counts"]) != required_keys
        or any(
            count != value["state_entries"]
            for count in value["required_key_counts"].values()
        )
    ):
        return False
    return True


def _valid_runtime_optimizer_state(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value)
        == {
            "state_entries",
            "expected_state_entries",
            "optimizer_step",
            "error_bits_dtype",
            "moment_and_error_shapes_match_parameters",
        }
        and isinstance(value.get("state_entries"), int)
        and not isinstance(value["state_entries"], bool)
        and value["state_entries"] > 0
        and value.get("expected_state_entries") == value["state_entries"]
        and value.get("optimizer_step") == 3
        and value.get("error_bits_dtype") == "torch.int16"
        and value.get("moment_and_error_shapes_match_parameters") is True
    )


def _valid_start_timing(value: Any) -> bool:
    expected = {
        "process_startup_seconds",
        "runtime_prepare",
        "first_step_jit_cold_seconds",
        "steady_stage_step_seconds",
        "optimizer_pre_checkpoint_seconds",
        "checkpoint_save_seconds",
        "process_elapsed_through_checkpoint_seconds",
    }
    steady = value.get("steady_stage_step_seconds") if isinstance(value, Mapping) else None
    scalar_fields = expected - {"runtime_prepare", "steady_stage_step_seconds"}
    return (
        isinstance(value, Mapping)
        and set(value) == expected
        and all(_finite_nonnegative(value.get(field)) for field in scalar_fields)
        and _valid_runtime_prepare(value.get("runtime_prepare"))
        and isinstance(steady, Mapping)
        and set(steady) == {"C2", "C3"}
        and all(_finite_nonnegative(item) for item in steady.values())
    )


def _valid_resume_timing(value: Any) -> bool:
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
    scalar_fields = expected - {"runtime_prepare"}
    return (
        isinstance(value, Mapping)
        and set(value) == expected
        and all(_finite_nonnegative(value.get(field)) for field in scalar_fields)
        and _valid_runtime_prepare(value.get("runtime_prepare"))
    )


def exact_keys(value: Any, expected: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise FullModelTrainingError(code)
    return value


def fail(code: str) -> NoReturn:
    raise FullModelTrainingError(code)
