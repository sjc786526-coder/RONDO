"""Model-only stage candidates and no-gradient validation for Plan 066."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
import os
from pathlib import Path
import shutil
import stat
import time
import uuid
from typing import Any

from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    safe_directory,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_exclusive,
)
from .objective import binary_reference, extract_raw_scalar, pair_reference
from .plan066_data import ValidationDataset


CANDIDATE_SCHEMA = "rondo-publication-critic-plan066-candidate-v1"
CANDIDATE_MANIFEST = "candidate-manifest.json"


def save_stage_candidate(
    output_root: Path,
    *,
    model: Any,
    tokenizer: Any,
    stage: str,
    global_step: int,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    destination = Path(output_root)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("plan066_candidate_output_exists")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    staging.mkdir(mode=0o700)
    started = time.perf_counter()
    try:
        model.save_pretrained(
            staging,
            safe_serialization=True,
            max_shard_size="5GB",
        )
        tokenizer.save_pretrained(staging)
        files = _tree_manifest(staging)
        if (
            not any(name.endswith(".safetensors") for name in files)
            or "config.json" not in files
            or "tokenizer_config.json" not in files
            or any(name.endswith((".bin", ".pt", ".pth", ".ckpt")) for name in files)
        ):
            raise FullModelTrainingError("plan066_candidate_file_set_invalid")
        core = {
            "schema": CANDIDATE_SCHEMA,
            "created_at": utc_now(),
            "stage": stage,
            "global_step": global_step,
            "identity_sha256": sha256_bytes(canonical_json_bytes(identity)),
            "format": "transformers_model_only_safetensors",
            "files": files,
        }
        manifest = {
            **core,
            "content_sha256": sha256_bytes(canonical_json_bytes(core)),
        }
        write_exclusive(staging / CANDIDATE_MANIFEST, pretty_json_bytes(manifest))
        os.replace(staging, destination)
    except BaseException:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise
    receipt = verify_stage_candidate(destination, identity=identity)
    return {**receipt, "save_seconds": time.perf_counter() - started}


def verify_stage_candidate(
    candidate_root: Path, *, identity: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    root = safe_directory(Path(candidate_root))
    manifest_path = root / CANDIDATE_MANIFEST
    manifest = read_json(manifest_path)
    expected = {
        "schema", "created_at", "stage", "global_step", "identity_sha256",
        "format", "files", "content_sha256",
    }
    if (
        not isinstance(manifest, Mapping)
        or set(manifest) != expected
        or manifest.get("schema") != CANDIDATE_SCHEMA
        or manifest.get("stage") not in {"C1", "C2", "C3"}
        or manifest.get("global_step") != {"C1": 1, "C2": 2, "C3": 3}.get(manifest.get("stage"))
        or manifest.get("format") != "transformers_model_only_safetensors"
    ):
        raise FullModelTrainingError("plan066_candidate_manifest_invalid")
    core = {key: value for key, value in manifest.items() if key != "content_sha256"}
    if sha256_bytes(canonical_json_bytes(core)) != manifest.get("content_sha256"):
        raise FullModelTrainingError("plan066_candidate_content_mismatch")
    if identity is not None and manifest.get("identity_sha256") != sha256_bytes(
        canonical_json_bytes(identity)
    ):
        raise FullModelTrainingError("plan066_candidate_identity_mismatch")
    expected_files = manifest.get("files")
    if not isinstance(expected_files, Mapping) or not expected_files:
        raise FullModelTrainingError("plan066_candidate_files_invalid")
    actual_files = _tree_manifest(root, exclude={CANDIDATE_MANIFEST})
    if actual_files != expected_files:
        raise FullModelTrainingError("plan066_candidate_tree_mismatch")
    for relative in expected_files:
        if relative.endswith(".safetensors"):
            _validate_safetensors(root / relative)
    return {
        "schema": CANDIDATE_SCHEMA,
        "status": "verified",
        "stage": manifest["stage"],
        "global_step": manifest["global_step"],
        "candidate_manifest_sha256": sha256_file(manifest_path),
        "content_sha256": manifest["content_sha256"],
        "identity_sha256": manifest["identity_sha256"],
        "bytes": sum(int(item["bytes"]) for item in expected_files.values()),
        "file_count": len(expected_files) + 1,
    }


def run_validation(
    context: Any,
    dataset: ValidationDataset,
    tokenized: Mapping[str, Any],
    *,
    stage: str,
) -> dict[str, Any]:
    """Evaluate fixed validation rows once without mutating training state."""

    torch = context.torch
    context.optimizer.zero_grad(set_to_none=True)
    _require_no_gradients(context.model)
    optimizer_before = _optimizer_observation(context.optimizer)
    scheduler_before = repr(context.scheduler.state_dict())
    training_before = bool(context.model.training)
    scores: dict[str, float] = {}
    token_count = 0
    started = time.perf_counter()
    context.model.eval()
    try:
        with torch.inference_mode():
            for candidate_id in sorted(dataset.supervision):
                item = tokenized[candidate_id]
                tokenizer = context.exact_tokenizer.tokenizer
                if tokenizer.padding_side != "right":
                    raise FullModelTrainingError("plan066_validation_padding_drifted")
                batch = tokenizer.pad(
                    {"input_ids": [list(item.input_ids)]},
                    padding=True,
                    return_attention_mask=True,
                    return_tensors="pt",
                )
                batch = {name: tensor.to(context.device) for name, tensor in batch.items()}
                output = context.model(**batch)
                scalar = extract_raw_scalar(output.logits)
                score = float(scalar[0].float().item())
                if not math.isfinite(score):
                    raise FullModelTrainingError("plan066_validation_scalar_nonfinite")
                scores[candidate_id] = score
                token_count += int(batch["attention_mask"].sum().item())
        torch.cuda.synchronize(context.device)
    finally:
        if training_before:
            context.model.train()
    binary_losses: list[float] = []
    binary_correct = 0
    for candidate_id, row in dataset.supervision.items():
        score = scores[candidate_id]
        label = str(row["binary_label"])
        loss, _ = binary_reference(score, label)
        binary_losses.append(loss)
        binary_correct += int((score >= 0.0) == (label == "PASS"))
    pair_losses: dict[str, list[float]] = {"boundary": [], "within_pass": []}
    pair_wins: dict[str, int] = {"boundary": 0, "within_pass": 0}
    pair_ties: dict[str, int] = {"boundary": 0, "within_pass": 0}
    for pair in dataset.pairs.values():
        kind = str(pair["kind"])
        preferred = scores[str(pair["preferred_candidate_id"])]
        dispreferred = scores[str(pair["dispreferred_candidate_id"])]
        loss, _, _ = pair_reference(preferred, dispreferred)
        pair_losses[kind].append(loss)
        pair_wins[kind] += int(preferred > dispreferred)
        pair_ties[kind] += int(preferred == dispreferred)
    _require_no_gradients(context.model)
    optimizer_after = _optimizer_observation(context.optimizer)
    scheduler_after = repr(context.scheduler.state_dict())
    if optimizer_after != optimizer_before or scheduler_after != scheduler_before:
        raise FullModelTrainingError("plan066_validation_mutated_training_state")
    return {
        "schema": "rondo-publication-critic-plan066-validation-v1",
        "stage": stage,
        "gradient_access": False,
        "feeds_training_decisions": False,
        "candidate_count": len(scores),
        "token_count": token_count,
        "elapsed_seconds": time.perf_counter() - started,
        "binary": {
            "count": len(binary_losses),
            "mean_loss": sum(binary_losses) / len(binary_losses),
            "zero_threshold_correct": binary_correct,
            "zero_threshold_accuracy": binary_correct / len(binary_losses),
        },
        "pairs": {
            kind: {
                "count": len(losses),
                "mean_loss": sum(losses) / len(losses),
                "preferred_wins": pair_wins[kind],
                "ties": pair_ties[kind],
            }
            for kind, losses in pair_losses.items()
        },
        "optimizer_state_unchanged": True,
        "scheduler_state_unchanged": True,
        "all_parameter_grads_none": True,
    }


def _optimizer_observation(optimizer: Any) -> dict[str, Any]:
    steps: list[int] = []
    for state in optimizer.state.values():
        step = state.get("step") if isinstance(state, Mapping) else None
        if step is None:
            continue
        try:
            steps.append(int(step.item()))
        except AttributeError:
            steps.append(int(step))
    return {
        "state_entries": len(optimizer.state),
        "steps": sorted(steps),
        "learning_rates": [float(group["lr"]) for group in optimizer.param_groups],
    }


def _require_no_gradients(model: Any) -> None:
    if any(parameter.grad is not None for parameter in model.parameters()):
        raise FullModelTrainingError("plan066_validation_gradient_present")


def _tree_manifest(
    root: Path, *, exclude: set[str] | None = None
) -> dict[str, dict[str, Any]]:
    excluded = exclude or set()
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan066_candidate_non_regular_entry")
        if relative in excluded:
            continue
        files[relative] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    return files


def _validate_safetensors(path: Path) -> None:
    """Validate the bounded safetensors container without loading tensors."""

    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            raw_length = handle.read(8)
            if len(raw_length) != 8:
                raise ValueError("missing header length")
            header_length = int.from_bytes(raw_length, "little", signed=False)
            if header_length <= 1 or header_length > 16 * 1024 * 1024:
                raise ValueError("invalid header length")
            header_raw = handle.read(header_length)
            if len(header_raw) != header_length:
                raise ValueError("short header")
        header = json.loads(header_raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FullModelTrainingError("plan066_candidate_safetensors_invalid") from exc
    if not isinstance(header, Mapping):
        raise FullModelTrainingError("plan066_candidate_safetensors_invalid")
    tensors = [item for name, item in header.items() if name != "__metadata__"]
    data_bytes = size - 8 - header_length
    spans: list[tuple[int, int]] = []
    for item in tensors:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"dtype", "shape", "data_offsets"}
            or not isinstance(item.get("dtype"), str)
            or not isinstance(item.get("shape"), list)
            or any(not isinstance(part, int) or isinstance(part, bool) or part < 0 for part in item["shape"])
            or not isinstance(item.get("data_offsets"), list)
            or len(item["data_offsets"]) != 2
            or any(not isinstance(part, int) or isinstance(part, bool) for part in item["data_offsets"])
        ):
            raise FullModelTrainingError("plan066_candidate_safetensors_invalid")
        start, end = item["data_offsets"]
        if start < 0 or end < start or end > data_bytes:
            raise FullModelTrainingError("plan066_candidate_safetensors_invalid")
        spans.append((start, end))
    if not spans:
        raise FullModelTrainingError("plan066_candidate_safetensors_empty")
    previous = 0
    for start, end in sorted(spans):
        if start != previous:
            raise FullModelTrainingError("plan066_candidate_safetensors_invalid")
        previous = end
    if previous != data_bytes:
        raise FullModelTrainingError("plan066_candidate_safetensors_invalid")
