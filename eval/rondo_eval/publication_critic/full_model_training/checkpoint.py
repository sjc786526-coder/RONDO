"""Full-model checkpoint, identity, and independent-process resume helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import random
import shutil
import stat
from typing import Any
import uuid

from .contract import (
    CHECKPOINT_SCHEMA,
    FullModelTrainingError,
    ProcessIdentity,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    safe_directory,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_exclusive,
)


METADATA_NAME = "checkpoint-metadata.json"
STATE_NAME = "training-state.pt"
MANIFEST_NAME = "checkpoint-manifest.json"


def current_process_identity() -> ProcessIdentity:
    return ProcessIdentity(
        instance_id=str(uuid.uuid4()),
        pid=os.getpid(),
        parent_pid=os.getppid(),
        started_at=utc_now(),
    )


def save_full_checkpoint(
    checkpoint_root: Path,
    *,
    model: Any,
    tokenizer: Any,
    optimizer: Any,
    scheduler: Any,
    progress: Mapping[str, Any],
    identity: Mapping[str, Any],
    process_identity: ProcessIdentity,
    optimizer_state: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    saved_optimizer_state = (
        optimizer.state_dict() if optimizer_state is None else optimizer_state
    )
    scheduler_state = scheduler.state_dict()
    rng_state = collect_rng_state()

    def save_model(model_root: Path) -> None:
        model_dir = model_root / "model"
        tokenizer_dir = model_root / "tokenizer"
        model.save_pretrained(model_dir, safe_serialization=True)
        tokenizer.save_pretrained(tokenizer_dir)

    return write_checkpoint(
        checkpoint_root,
        model_saver=save_model,
        optimizer_state=saved_optimizer_state,
        scheduler_state=scheduler_state,
        rng_state=rng_state,
        progress=progress,
        identity=identity,
        process_identity=process_identity,
    )


def write_checkpoint(
    checkpoint_root: Path,
    *,
    model_saver: Callable[[Path], None],
    optimizer_state: Mapping[str, Any],
    scheduler_state: Mapping[str, Any],
    rng_state: Mapping[str, Any],
    progress: Mapping[str, Any],
    identity: Mapping[str, Any],
    process_identity: ProcessIdentity,
    state_encoder: Callable[[Path, Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    destination = Path(checkpoint_root)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("checkpoint_output_already_exists")
    if (
        not isinstance(optimizer_state, Mapping)
        or not optimizer_state.get("state")
        or not isinstance(optimizer_state.get("param_groups"), list)
        or not optimizer_state["param_groups"]
    ):
        raise FullModelTrainingError("checkpoint_optimizer_state_empty")
    if not isinstance(scheduler_state, Mapping) or not scheduler_state:
        raise FullModelTrainingError("checkpoint_scheduler_state_empty")
    _validate_progress(progress)
    if not isinstance(identity, Mapping) or not identity:
        raise FullModelTrainingError("checkpoint_identity_empty")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    staging.mkdir(mode=0o700)
    try:
        model_root = staging / "full-model"
        model_root.mkdir(mode=0o700)
        model_saver(model_root)
        if not _regular_tree_files(model_root):
            raise FullModelTrainingError("checkpoint_full_model_empty")
        state = {
            "optimizer": dict(optimizer_state),
            "scheduler": dict(scheduler_state),
            "rng": dict(rng_state),
        }
        state_path = staging / STATE_NAME
        if state_encoder is None:
            _torch_save(state_path, state)
        else:
            state_encoder(state_path, state)
        if not state_path.is_file() or state_path.is_symlink():
            raise FullModelTrainingError("checkpoint_state_not_written")
        identity_value = json.loads(json.dumps(identity))
        metadata = {
            "schema": CHECKPOINT_SCHEMA,
            "created_at": utc_now(),
            "process": process_identity.as_dict(),
            "identity": identity_value,
            "identity_sha256": sha256_bytes(canonical_json_bytes(identity_value)),
            "progress": json.loads(json.dumps(progress)),
            "full_model_relative": "full-model/model",
            "tokenizer_relative": "full-model/tokenizer",
            "training_state_relative": STATE_NAME,
        }
        write_exclusive(staging / METADATA_NAME, pretty_json_bytes(metadata))
        files = _tree_manifest(staging, exclude={MANIFEST_NAME})
        manifest_core = {
            "schema": "rondo-publication-critic-full-model-checkpoint-manifest-v1",
            "files": files,
        }
        manifest = {
            **manifest_core,
            "content_sha256": sha256_bytes(canonical_json_bytes(manifest_core)),
        }
        write_exclusive(staging / MANIFEST_NAME, pretty_json_bytes(manifest))
        result = {
            "schema": CHECKPOINT_SCHEMA,
            "status": "saved_manifest_built",
            "checkpoint_manifest_sha256": sha256_file(staging / MANIFEST_NAME),
            "identity_sha256": metadata["identity_sha256"],
            "global_step": metadata["progress"]["global_step"],
            "stage": metadata["progress"]["stage"],
            "process": metadata["process"],
            "bytes": sum(item["bytes"] for item in files.values()),
            "file_count": len(files) + 1,
        }
        os.replace(staging, destination)
        return result
    except BaseException:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def verify_checkpoint(checkpoint_root: Path) -> dict[str, Any]:
    root = safe_directory(Path(checkpoint_root))
    metadata = read_checkpoint_metadata(root)
    manifest = read_json(root / MANIFEST_NAME)
    if (
        not isinstance(manifest, Mapping)
        or set(manifest) != {"schema", "files", "content_sha256"}
        or manifest.get("schema")
        != "rondo-publication-critic-full-model-checkpoint-manifest-v1"
        or not isinstance(manifest.get("files"), Mapping)
    ):
        raise FullModelTrainingError("checkpoint_manifest_invalid")
    core = {"schema": manifest["schema"], "files": manifest["files"]}
    if sha256_bytes(canonical_json_bytes(core)) != manifest["content_sha256"]:
        raise FullModelTrainingError("checkpoint_manifest_content_mismatch")
    actual = _tree_manifest(root, exclude={MANIFEST_NAME})
    if actual != manifest["files"]:
        raise FullModelTrainingError("checkpoint_file_identity_mismatch")
    model_relative = metadata["full_model_relative"]
    model_root = root / model_relative
    if not model_root.is_dir() or model_root.is_symlink() or not _regular_tree_files(model_root):
        raise FullModelTrainingError("checkpoint_full_model_missing")
    state_path = root / metadata["training_state_relative"]
    if not state_path.is_file() or state_path.is_symlink():
        raise FullModelTrainingError("checkpoint_training_state_missing")
    return {
        "schema": CHECKPOINT_SCHEMA,
        "status": "verified",
        "checkpoint_manifest_sha256": sha256_file(root / MANIFEST_NAME),
        "identity_sha256": metadata["identity_sha256"],
        "global_step": metadata["progress"]["global_step"],
        "stage": metadata["progress"]["stage"],
        "process": metadata["process"],
        "bytes": sum(item["bytes"] for item in actual.values()),
        "file_count": len(actual) + 1,
    }


def read_checkpoint_metadata(checkpoint_root: Path) -> Mapping[str, Any]:
    root = safe_directory(Path(checkpoint_root))
    metadata = read_json(root / METADATA_NAME)
    expected = {
        "schema",
        "created_at",
        "process",
        "identity",
        "identity_sha256",
        "progress",
        "full_model_relative",
        "tokenizer_relative",
        "training_state_relative",
    }
    if (
        not isinstance(metadata, Mapping)
        or set(metadata) != expected
        or metadata.get("schema") != CHECKPOINT_SCHEMA
        or metadata.get("full_model_relative") != "full-model/model"
        or metadata.get("tokenizer_relative") != "full-model/tokenizer"
        or metadata.get("training_state_relative") != STATE_NAME
        or sha256_bytes(canonical_json_bytes(metadata.get("identity")))
        != metadata.get("identity_sha256")
    ):
        raise FullModelTrainingError("checkpoint_metadata_invalid")
    process = metadata.get("process")
    if (
        not isinstance(process, Mapping)
        or set(process) != {"instance_id", "pid", "parent_pid", "started_at"}
        or not isinstance(process["instance_id"], str)
        or not process["instance_id"]
        or not isinstance(process["pid"], int)
        or isinstance(process["pid"], bool)
        or process["pid"] <= 0
    ):
        raise FullModelTrainingError("checkpoint_process_identity_invalid")
    _validate_progress(metadata.get("progress"))
    return metadata


def require_new_process(metadata: Mapping[str, Any]) -> ProcessIdentity:
    saved = metadata.get("process")
    if not isinstance(saved, Mapping):
        raise FullModelTrainingError("checkpoint_process_identity_invalid")
    current = current_process_identity()
    if saved.get("pid") == current.pid or saved.get("instance_id") == current.instance_id:
        raise FullModelTrainingError("checkpoint_resume_requires_new_process")
    return current


def load_training_state(
    checkpoint_root: Path,
    *,
    state_decoder: Callable[[Path], Mapping[str, Any]] | None = None,
    verified_receipt: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    root = safe_directory(Path(checkpoint_root))
    if verified_receipt is None:
        verify_checkpoint(root)
    else:
        _accept_verified_receipt(root, verified_receipt)
    path = root / STATE_NAME
    value = _torch_load(path) if state_decoder is None else state_decoder(path)
    if not isinstance(value, Mapping) or set(value) != {"optimizer", "scheduler", "rng"}:
        raise FullModelTrainingError("checkpoint_training_state_invalid")
    if not isinstance(value["optimizer"], Mapping) or not value["optimizer"].get("state"):
        raise FullModelTrainingError("checkpoint_optimizer_state_empty")
    if not isinstance(value["scheduler"], Mapping) or not value["scheduler"]:
        raise FullModelTrainingError("checkpoint_scheduler_state_empty")
    if not isinstance(value["rng"], Mapping):
        raise FullModelTrainingError("checkpoint_rng_state_invalid")
    return value


def _accept_verified_receipt(root: Path, value: Mapping[str, Any]) -> None:
    metadata = read_checkpoint_metadata(root)
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != CHECKPOINT_SCHEMA
        or value.get("status") != "verified"
        or value.get("checkpoint_manifest_sha256")
        != sha256_file(root / MANIFEST_NAME)
        or value.get("identity_sha256") != metadata["identity_sha256"]
        or value.get("global_step") != metadata["progress"]["global_step"]
        or value.get("stage") != metadata["progress"]["stage"]
    ):
        raise FullModelTrainingError("checkpoint_verified_receipt_invalid")


def collect_rng_state() -> dict[str, Any]:
    torch = _torch()
    result: dict[str, Any] = {
        "python": random.getstate(),
        "torch_cpu": torch.get_rng_state(),
        "torch_cuda": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
    }
    try:
        import numpy

        result["numpy"] = numpy.random.get_state()
    except ImportError:
        result["numpy"] = None
    return result


def restore_rng_state(value: Mapping[str, Any]) -> None:
    torch = _torch()
    try:
        random.setstate(value["python"])
        torch.set_rng_state(value["torch_cpu"])
        if torch.cuda.is_available():
            torch.cuda.set_rng_state_all(value["torch_cuda"])
        if value.get("numpy") is not None:
            import numpy

            numpy.random.set_state(value["numpy"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FullModelTrainingError("checkpoint_rng_restore_failed") from exc


def _validate_progress(value: Any) -> None:
    cursor = value.get("data_cursor") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {"stage", "global_step", "stage_update", "completed_stages", "data_cursor"}
        or value.get("stage") != "C3"
        or value.get("global_step") != 3
        or value.get("stage_update") != 1
        or value.get("completed_stages") != ["C1", "C2", "C3"]
        or not isinstance(cursor, Mapping)
        or set(cursor) != {"stage_fully_consumed", "binary_candidate_ids", "pair_ids"}
        or cursor.get("stage_fully_consumed") is not True
        or not _valid_consumed_ids(cursor.get("binary_candidate_ids"), expected_count=6)
        or not _valid_consumed_ids(cursor.get("pair_ids"), expected_count=2)
    ):
        raise FullModelTrainingError("checkpoint_progress_invalid")


def _valid_consumed_ids(value: Any, *, expected_count: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == expected_count
        and all(isinstance(item, str) and bool(item) for item in value)
        and len(set(value)) == expected_count
    )


def _tree_manifest(root: Path, *, exclude: set[str]) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("checkpoint_non_regular_entry")
        if relative in exclude:
            continue
        files[relative] = {
            "bytes": info.st_size,
            "sha256": sha256_file(path),
        }
    return files


def _regular_tree_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("checkpoint_non_regular_entry")
        files.append(path)
    return files


def _torch_save(path: Path, value: Mapping[str, Any]) -> None:
    torch = _torch()
    try:
        torch.save(value, path)
    except Exception as exc:
        raise FullModelTrainingError("checkpoint_state_save_failed") from exc


def _torch_load(path: Path) -> Mapping[str, Any]:
    torch = _torch()
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except Exception as exc:
        raise FullModelTrainingError("checkpoint_state_load_failed") from exc


def _torch() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise FullModelTrainingError("torch_dependency_missing") from exc
    return torch
