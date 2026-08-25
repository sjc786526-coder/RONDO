"""Exact two-shard snapshot verification for the Plan 079 4B base."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import stat
from typing import Any

from ..full_model_training.contract import (
    canonical_json_bytes,
    read_json,
    sha256_bytes,
    sha256_file,
)
from .contract import BaseQualityError, MODEL_REPOSITORY, MODEL_REVISION, require_sha256


MODEL_LOCK_SCHEMA = "rondo-publication-critic-plan079-model-lock-v1"
SNAPSHOT_RECEIPT_SCHEMA = "rondo-publication-critic-plan079-snapshot-receipt-v1"


def load_model_lock(path: Path) -> dict[str, Any]:
    try:
        value = read_json(path)
    except Exception as exc:  # noqa: BLE001 - normalized to a Plan 079 code
        raise BaseQualityError("model_lock_invalid") from exc
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "repository",
        "revision",
        "license",
        "library_name",
        "pipeline_tag",
        "parameters",
        "expected_config",
        "weight_index",
        "files",
    }:
        raise BaseQualityError("model_lock_fields_invalid")
    if (
        value.get("schema") != MODEL_LOCK_SCHEMA
        or value.get("repository") != MODEL_REPOSITORY
        or value.get("revision") != MODEL_REVISION
        or value.get("license") != "apache-2.0"
        or value.get("library_name") != "transformers"
        or value.get("pipeline_tag") != "text-classification"
        or value.get("parameters") != {"count": 4_022_470_656, "dtype": "BF16"}
        or value.get("expected_config")
        != {
            "architecture": "Qwen3ForSequenceClassification",
            "model_type": "qwen3",
            "num_labels": 1,
            "pad_token_id": 151654,
            "eos_token_id": 151645,
            "max_position_embeddings": 40960,
            "torch_dtype": "bfloat16",
        }
        or value.get("weight_index")
        != {
            "filename": "model.safetensors.index.json",
            "total_size": 8_044_941_312,
            "tensor_count": 399,
            "shards": [
                "model-00001-of-00002.safetensors",
                "model-00002-of-00002.safetensors",
            ],
        }
    ):
        raise BaseQualityError("model_lock_identity_invalid")
    files = value.get("files")
    if not isinstance(files, Mapping) or set(files) != {
        ".gitattributes",
        "README.md",
        "added_tokens.json",
        "assets/skywork_logo.png",
        "chat_template.jinja",
        "config.json",
        "merges.txt",
        "model-00001-of-00002.safetensors",
        "model-00002-of-00002.safetensors",
        "model.safetensors.index.json",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
    }:
        raise BaseQualityError("model_lock_file_set_invalid")
    for relative, metadata in files.items():
        pure = Path(str(relative))
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or not isinstance(metadata, Mapping)
            or set(metadata) != {"bytes", "sha256"}
        ):
            raise BaseQualityError("model_lock_file_entry_invalid")
        if type(metadata.get("bytes")) is not int or metadata["bytes"] < 0:
            raise BaseQualityError("model_lock_file_size_invalid")
        require_sha256(metadata.get("sha256"), "model_lock_file_sha256_invalid")
    return dict(value)


def _regular_tree(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise BaseQualityError("snapshot_root_unsafe")
    result: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        info = os.lstat(path)
        if relative.parts and relative.parts[0] == ".cache":
            if stat.S_ISLNK(info.st_mode):
                raise BaseQualityError("snapshot_entry_unsafe")
            continue
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise BaseQualityError("snapshot_entry_unsafe")
        result.add(relative.as_posix())
    return result


def _json_file(path: Path, code: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BaseQualityError(code) from exc
    if not isinstance(value, Mapping):
        raise BaseQualityError(code)
    return value


def verify_snapshot(snapshot: Path, model_lock_path: Path) -> dict[str, Any]:
    lock = load_model_lock(model_lock_path)
    if snapshot.is_symlink():
        raise BaseQualityError("snapshot_root_unsafe")
    try:
        root = snapshot.resolve(strict=True)
    except OSError as exc:
        raise BaseQualityError("snapshot_root_unsafe") from exc
    expected = set(lock["files"])
    if _regular_tree(root) != expected:
        raise BaseQualityError("snapshot_file_set_mismatch")
    observed: dict[str, dict[str, Any]] = {}
    for relative, metadata in sorted(lock["files"].items()):
        path = root.joinpath(*Path(relative).parts)
        info = os.lstat(path)
        if info.st_size != metadata["bytes"] or sha256_file(path) != metadata["sha256"]:
            raise BaseQualityError("snapshot_file_identity_mismatch")
        observed[relative] = {"bytes": info.st_size, "sha256": metadata["sha256"]}

    config = _json_file(root / "config.json", "snapshot_config_invalid")
    architecture = config.get("architectures")
    if (
        architecture != [lock["expected_config"]["architecture"]]
        or config.get("model_type") != "qwen3"
        or config.get("pad_token_id") != 151654
        or config.get("eos_token_id") != 151645
        or config.get("max_position_embeddings") != 40960
        or config.get("torch_dtype") != "bfloat16"
        or config.get("id2label") != {"0": "LABEL_0"}
    ):
        raise BaseQualityError("snapshot_config_identity_mismatch")

    index = _json_file(root / "model.safetensors.index.json", "snapshot_index_invalid")
    weight_map = index.get("weight_map")
    metadata = index.get("metadata")
    shards = sorted(set(weight_map.values())) if isinstance(weight_map, Mapping) else []
    if (
        not isinstance(weight_map, Mapping)
        or len(weight_map) != lock["weight_index"]["tensor_count"]
        or metadata != {"total_size": lock["weight_index"]["total_size"]}
        or shards != lock["weight_index"]["shards"]
    ):
        raise BaseQualityError("snapshot_index_identity_mismatch")

    content_sha256 = sha256_bytes(canonical_json_bytes(observed))
    return {
        "schema": SNAPSHOT_RECEIPT_SCHEMA,
        "repository": MODEL_REPOSITORY,
        "revision": MODEL_REVISION,
        "model_lock_sha256": sha256_file(model_lock_path),
        "snapshot_content_sha256": content_sha256,
        "license": lock["license"],
        "library_name": lock["library_name"],
        "pipeline_tag": lock["pipeline_tag"],
        "parameters": dict(lock["parameters"]),
        "model_class": lock["expected_config"]["architecture"],
        "weight_index": dict(lock["weight_index"]),
        "files": observed,
    }


def validate_snapshot_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "repository",
        "revision",
        "model_lock_sha256",
        "snapshot_content_sha256",
        "license",
        "library_name",
        "pipeline_tag",
        "parameters",
        "model_class",
        "weight_index",
        "files",
    }:
        raise BaseQualityError("snapshot_receipt_fields_invalid")
    if value.get("schema") != SNAPSHOT_RECEIPT_SCHEMA:
        raise BaseQualityError("snapshot_receipt_schema_invalid")
    # A second verification of the receipt's declarative fields is cheap and
    # prevents a self-reported digest from standing in for the frozen lock.
    if (
        value.get("repository") != MODEL_REPOSITORY
        or value.get("revision") != MODEL_REVISION
        or value.get("license") != "apache-2.0"
        or value.get("library_name") != "transformers"
        or value.get("pipeline_tag") != "text-classification"
        or value.get("parameters") != {"count": 4_022_470_656, "dtype": "BF16"}
        or value.get("model_class") != "Qwen3ForSequenceClassification"
    ):
        raise BaseQualityError("snapshot_receipt_identity_invalid")
    require_sha256(value.get("model_lock_sha256"), "snapshot_receipt_lock_invalid")
    require_sha256(
        value.get("snapshot_content_sha256"), "snapshot_receipt_content_invalid"
    )
    return dict(value)
