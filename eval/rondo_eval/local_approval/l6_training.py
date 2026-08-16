"""Plan 037 train-only projection, token census, and LoRA runner.

This file deliberately stays importable with the Python standard library.  The
heavy training dependencies are imported only by the ``train`` and
``reload-adapter`` commands.  Preparing or checking a bundle cannot load a
model, contact the Hub, or inspect validation/holdout data.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import inspect
import json
import math
import os
import platform
import re
import shutil
import stat
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


TRAIN_SHA256 = "1e66c06e9357a3b6e14aedd193c5405ad2c18924e57da6a3a209f079b80c110a"
TRAIN_PROJECTION_SHA256 = (
    "0026cddd2a80771039c6644378120793d98310abdf66f01e7475416f23b2cc14"
)
DATASET_MANIFEST_SHA256 = (
    "dbf5fffe1f26d7746acf43fdcd092ff3e9cd64ea1f40046cd3b7219a15107190"
)
EXPECTED_TRAIN_RECORDS = 470
PROJECTION_SCHEMA_VERSION = 1
BUNDLE_MANIFEST_SCHEMA_VERSION = 1
TOKEN_CENSUS_SCHEMA_VERSION = 1
MODEL_CONTRACT_RELATIVE_PATH = "training/local-approval-l6/model-contract-v1.json"
RECIPE_RELATIVE_PATH = "training/local-approval-l6/recipe-candidate-v1.json"
ALLOWLIST_RELATIVE_PATH = "training/local-approval-l6/bundle-allowlist-v1.json"
ARTIFACT_ALLOWLIST_RELATIVE_PATH = (
    "training/local-approval-l6/artifact-export-allowlist-v1.json"
)
BUNDLE_ALLOWLIST_SHA256 = (
    "c9dda999cb4c0115a899742425e2cc6880e7bb3fcb7efd57f762b7d0c9fde016"
)
ARTIFACT_ALLOWLIST_SHA256 = (
    "ee7f8510d82f6798d2725c98e64afb02416dc3460438413f7bb9107ef25308f6"
)
DIRECT_DEPENDENCIES = frozenset(
    {
        "torch",
        "transformers",
        "peft",
        "trl",
        "accelerate",
        "bitsandbytes",
        "safetensors",
    }
)
LORA_TARGET_MODULE_PATTERN = (
    r"^model\.language_model\.layers\.\d+\."
    r"(?:self_attn\.(?:q_proj|k_proj|v_proj|o_proj)|"
    r"mlp\.(?:gate_proj|up_proj|down_proj))$"
)
TRAIN_RELATIVE_PATH = "training/local-approval-synthetic-v1/train.jsonl"
DATASET_MANIFEST_RELATIVE_PATH = "training/local-approval-synthetic-v1/manifest.json"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_FINAL_SOURCE_FIELDS = {
    "schema_version",
    "batch_id",
    "origin",
    "generator_model",
    "generated_date",
    "prompt_version",
    "prompt_sha256",
    "group_id",
    "category",
    "sample_id",
    "payload_sha256",
    "input",
    "target",
    "split_group_id",
    "split",
}
_PROJECTION_FIELDS = {
    "schema_version",
    "source_sample_id",
    "source_split_group_id",
    "source_payload_sha256",
    "messages",
    "completion",
    "projection_sha256",
}


class L6TrainingError(RuntimeError):
    """A fail-closed error whose message never contains dataset bodies."""

    def __init__(self, code: str, facts: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.facts = dict(facts or {})


@dataclass(frozen=True)
class TokenizedTrainingRow:
    input_ids: list[int]
    attention_mask: list[int]
    labels: list[int]
    prompt_tokens: int
    completion_tokens: int


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise L6TrainingError("json_canonicalization_failed") from exc


def _pretty_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise L6TrainingError("json_serialization_failed") from exc


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(_canonical_bytes(value))


def _regular_file(path: Path, *, maximum_bytes: int = 64 * 1024 * 1024) -> bytes:
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise L6TrainingError("required_file_missing") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_size <= 0
        or before.st_size > maximum_bytes
    ):
        raise L6TrainingError("file_contract_invalid")
    try:
        raw = path.read_bytes()
        after = os.lstat(path)
    except OSError as exc:
        raise L6TrainingError("file_read_failed") from exc
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise L6TrainingError("file_changed_while_reading")
    return raw


def _load_json(path: Path) -> tuple[Any, bytes]:
    raw = _regular_file(path)
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise L6TrainingError("json_file_invalid") from exc


def _load_jsonl(path: Path) -> tuple[list[Any], bytes]:
    raw = _regular_file(path)
    try:
        lines = raw.decode("utf-8").splitlines()
        if not lines or any(not line.strip() for line in lines):
            raise L6TrainingError("jsonl_shape_invalid")
        return [json.loads(line) for line in lines], raw
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise L6TrainingError("jsonl_invalid") from exc


def _jsonl_bytes(rows: Iterable[Any]) -> bytes:
    return b"".join(_canonical_bytes(row) + b"\n" for row in rows)


def _write_exclusive(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    if path.exists() or path.is_symlink():
        raise L6TrainingError("output_already_exists")
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


def _validate_target(target: Any) -> dict[str, Any]:
    if not isinstance(target, dict) or set(target) != {
        "outcome",
        "rationale",
        "risk_tags",
    }:
        raise L6TrainingError("target_contract_invalid")
    if (
        target["outcome"] not in {"allow", "deny"}
        or not isinstance(target["rationale"], str)
        or not target["rationale"]
        or not isinstance(target["risk_tags"], list)
        or len(target["risk_tags"]) > 16
        or any(not isinstance(tag, str) for tag in target["risk_tags"])
        or len(set(target["risk_tags"])) != len(target["risk_tags"])
    ):
        raise L6TrainingError("target_contract_invalid")
    return copy.deepcopy(target)


def _content_for_template(item: Any) -> list[dict[str, str]]:
    if not isinstance(item, dict) or set(item) != {"type", "role", "content"}:
        raise L6TrainingError("source_message_invalid")
    if item["type"] != "message" or item["role"] not in {"user", "assistant"}:
        raise L6TrainingError("source_message_invalid")
    expected_part_type = "input_text" if item["role"] == "user" else "output_text"
    if not isinstance(item["content"], list) or not item["content"]:
        raise L6TrainingError("source_message_invalid")
    converted: list[dict[str, str]] = []
    for part in item["content"]:
        if (
            not isinstance(part, dict)
            or set(part) != {"type", "text"}
            or part["type"] != expected_part_type
            or not isinstance(part["text"], str)
            or not part["text"]
        ):
            raise L6TrainingError("source_message_invalid")
        converted.append({"type": "text", "text": part["text"]})
    return converted


def project_source_row(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != _FINAL_SOURCE_FIELDS:
        raise L6TrainingError("source_row_fields_invalid")
    if (
        row.get("split") != "train"
        or row.get("origin") != "synthetic"
        or not isinstance(row.get("sample_id"), str)
        or _HEX64.fullmatch(row["sample_id"]) is None
        or not isinstance(row.get("split_group_id"), str)
        or _HEX64.fullmatch(row["split_group_id"]) is None
        or not isinstance(row.get("payload_sha256"), str)
        or _HEX64.fullmatch(row["payload_sha256"]) is None
        or not isinstance(row.get("input"), dict)
    ):
        raise L6TrainingError("source_row_binding_invalid")
    logical = row["input"]
    if (
        logical.get("schema_version") != 3
        or not isinstance(logical.get("guardian_policy"), str)
        or not logical["guardian_policy"]
        or not isinstance(logical.get("input"), list)
        or _canonical_sha256(logical) != row["payload_sha256"]
    ):
        raise L6TrainingError("source_payload_invalid")
    messages = [{"role": "system", "content": logical["guardian_policy"]}]
    for item in logical["input"]:
        messages.append(
            {"role": item["role"], "content": _content_for_template(item)}
        )
    completion = _canonical_bytes(_validate_target(row["target"])).decode("utf-8")
    identity = {
        "source_sample_id": row["sample_id"],
        "source_split_group_id": row["split_group_id"],
        "source_payload_sha256": row["payload_sha256"],
        "messages": messages,
        "completion": completion,
    }
    return {
        "schema_version": PROJECTION_SCHEMA_VERSION,
        **identity,
        "projection_sha256": _canonical_sha256(identity),
    }


def validate_projection_row(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict) or set(row) != _PROJECTION_FIELDS:
        raise L6TrainingError("projection_fields_invalid")
    identity = {key: row[key] for key in row if key not in {"schema_version", "projection_sha256"}}
    if (
        row["schema_version"] != PROJECTION_SCHEMA_VERSION
        or any(
            not isinstance(row[name], str) or _HEX64.fullmatch(row[name]) is None
            for name in (
                "source_sample_id",
                "source_split_group_id",
                "source_payload_sha256",
                "projection_sha256",
            )
        )
        or not isinstance(row["messages"], list)
        or len(row["messages"]) < 2
        or row["messages"][0].get("role") != "system"
        or not isinstance(row["completion"], str)
        or not row["completion"]
        or _canonical_sha256(identity) != row["projection_sha256"]
    ):
        raise L6TrainingError("projection_binding_invalid")
    try:
        _validate_target(json.loads(row["completion"]))
    except json.JSONDecodeError as exc:
        raise L6TrainingError("projection_completion_invalid") from exc
    return row


def build_training_projection(repo_root: Path) -> tuple[list[dict[str, Any]], bytes]:
    root = repo_root.resolve(strict=True)
    train_path = root / TRAIN_RELATIVE_PATH
    manifest_path = root / DATASET_MANIFEST_RELATIVE_PATH
    manifest, manifest_raw = _load_json(manifest_path)
    rows, train_raw = _load_jsonl(train_path)
    if _sha256(train_raw) != TRAIN_SHA256 or _sha256(manifest_raw) != DATASET_MANIFEST_SHA256:
        raise L6TrainingError("frozen_dataset_hash_mismatch")
    if (
        not isinstance(manifest, dict)
        or manifest.get("status") != "ready_for_l6"
        or manifest.get("statistics", {}).get("splits", {}).get("train")
        != EXPECTED_TRAIN_RECORDS
        or manifest.get("files", {}).get("train.jsonl", {}).get("sha256")
        != TRAIN_SHA256
        or len(rows) != EXPECTED_TRAIN_RECORDS
    ):
        raise L6TrainingError("frozen_dataset_manifest_invalid")
    projection = [project_source_row(row) for row in rows]
    sample_ids = {row["source_sample_id"] for row in projection}
    projection_ids = {row["projection_sha256"] for row in projection}
    if len(sample_ids) != EXPECTED_TRAIN_RECORDS or len(projection_ids) != EXPECTED_TRAIN_RECORDS:
        raise L6TrainingError("projection_identity_not_unique")
    projection_raw = _jsonl_bytes(projection)
    if _sha256(projection_raw) != TRAIN_PROJECTION_SHA256:
        raise L6TrainingError("frozen_train_projection_hash_mismatch")
    return projection, projection_raw


def _load_allowlist(repo_root: Path) -> tuple[dict[str, Any], bytes]:
    value, raw = _load_json(repo_root / ALLOWLIST_RELATIVE_PATH)
    if (
        _sha256(raw) != BUNDLE_ALLOWLIST_SHA256
        or
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("files"), list)
        or not isinstance(value.get("forbidden_path_terms"), list)
    ):
        raise L6TrainingError("bundle_allowlist_invalid")
    paths = [entry.get("bundle_path") for entry in value["files"] if isinstance(entry, dict)]
    if len(paths) != len(value["files"]) or len(set(paths)) != len(paths):
        raise L6TrainingError("bundle_allowlist_invalid")
    for path in paths:
        candidate = Path(path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise L6TrainingError("bundle_allowlist_invalid")
    if sum(bool(entry.get("contains_train_body")) for entry in value["files"]) != 1:
        raise L6TrainingError("bundle_allowlist_invalid")
    return value, raw


def _load_artifact_allowlist(repo_root: Path) -> tuple[dict[str, Any], bytes]:
    value, raw = _load_json(repo_root / ARTIFACT_ALLOWLIST_RELATIVE_PATH)
    if (
        _sha256(raw) != ARTIFACT_ALLOWLIST_SHA256
        or not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("allowed_prefixes"), list)
        or not isinstance(value.get("allowed_root_files"), list)
        or not isinstance(value.get("forbidden_path_terms"), list)
        or value.get("boundaries", {}).get("dataset_body_allowed") is not False
        or value.get("boundaries", {}).get("training_projection_allowed") is not False
        or value.get("boundaries", {}).get("per_sample_validation_output_allowed")
        is not False
    ):
        raise L6TrainingError("artifact_allowlist_invalid")
    return value, raw


def prepare_bundle(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    root = repo_root.resolve(strict=True)
    if output_dir.exists() or output_dir.is_symlink():
        raise L6TrainingError("bundle_output_already_exists")
    projection, projection_raw = build_training_projection(root)
    allowlist, allowlist_raw = _load_allowlist(root)
    _load_artifact_allowlist(root)
    output_dir.mkdir(mode=0o700, parents=True)
    files: dict[str, dict[str, Any]] = {}
    try:
        for entry in allowlist["files"]:
            bundle_path = entry["bundle_path"]
            target = output_dir / bundle_path
            if entry.get("generated"):
                raw = projection_raw
            else:
                source = root / entry["source_relative_path"]
                raw = _regular_file(source)
                if bundle_path == "contracts/bundle-allowlist-v1.json" and raw != allowlist_raw:
                    raise L6TrainingError("bundle_allowlist_changed")
            _write_exclusive(target, raw)
            files[bundle_path] = {
                "bytes": len(raw),
                "contains_train_body": bool(entry.get("contains_train_body")),
                "sha256": _sha256(raw),
            }
        manifest = {
            "schema_version": BUNDLE_MANIFEST_SCHEMA_VERSION,
            "version": "rondo_local_approval_l6_train_only_bundle_v1",
            "status": "stage1_candidate_ready",
            "source": {
                "dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
                "train_jsonl_sha256": TRAIN_SHA256,
                "train_records": EXPECTED_TRAIN_RECORDS,
                "validation_records": 0,
                "holdout_records": 0,
                "real_e_final_records": 0,
            },
            "projection": {
                "records": len(projection),
                "sha256": _sha256(projection_raw),
                "sample_set_sha256": _canonical_sha256(
                    sorted(row["source_sample_id"] for row in projection)
                ),
                "body_published_in_manifest": False,
            },
            "files": dict(sorted(files.items())),
        }
        manifest_raw = _pretty_bytes(manifest)
        _write_exclusive(output_dir / "bundle-manifest.json", manifest_raw)
        result = verify_bundle(output_dir)
        return {**result, "bundle_manifest_sha256": _sha256(manifest_raw)}
    except BaseException:
        # The caller selected a new task-only directory.  A failed preparation
        # leaves it in place for diagnosis and never overwrites another bundle.
        raise


def verify_bundle(bundle_root: Path) -> dict[str, Any]:
    try:
        root_info = os.lstat(bundle_root)
    except OSError as exc:
        raise L6TrainingError("bundle_missing") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise L6TrainingError("bundle_root_invalid")
    manifest, manifest_raw = _load_json(bundle_root / "bundle-manifest.json")
    allowlist, allowlist_raw = _load_json(
        bundle_root / "contracts/bundle-allowlist-v1.json"
    )
    if _sha256(allowlist_raw) != BUNDLE_ALLOWLIST_SHA256:
        raise L6TrainingError("bundle_allowlist_hash_mismatch")
    _artifact_allowlist_from_bundle(bundle_root)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != BUNDLE_MANIFEST_SCHEMA_VERSION
        or manifest.get("source", {}).get("train_records") != EXPECTED_TRAIN_RECORDS
        or manifest.get("source", {}).get("validation_records") != 0
        or manifest.get("source", {}).get("holdout_records") != 0
        or manifest.get("source", {}).get("real_e_final_records") != 0
    ):
        raise L6TrainingError("bundle_manifest_invalid")
    expected = {entry["bundle_path"] for entry in allowlist.get("files", [])}
    expected.add("bundle-manifest.json")
    actual: set[str] = set()
    forbidden = tuple(str(term).casefold() for term in allowlist.get("forbidden_path_terms", []))
    for path in bundle_root.rglob("*"):
        relative = path.relative_to(bundle_root).as_posix()
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise L6TrainingError("bundle_non_regular_entry")
        if relative != "bundle-manifest.json" and any(term in relative.casefold() for term in forbidden):
            raise L6TrainingError("bundle_forbidden_path")
        actual.add(relative)
    if actual != expected:
        raise L6TrainingError("bundle_file_set_mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != expected - {"bundle-manifest.json"}:
        raise L6TrainingError("bundle_manifest_file_set_mismatch")
    for relative, identity in files.items():
        raw = _regular_file(bundle_root / relative)
        if (
            not isinstance(identity, dict)
            or identity.get("bytes") != len(raw)
            or identity.get("sha256") != _sha256(raw)
        ):
            raise L6TrainingError("bundle_file_hash_mismatch")
    projection, projection_raw = _load_jsonl(bundle_root / "data/train-projection.jsonl")
    if len(projection) != EXPECTED_TRAIN_RECORDS:
        raise L6TrainingError("bundle_projection_count_invalid")
    validated = [validate_projection_row(row) for row in projection]
    if len({row["source_sample_id"] for row in validated}) != EXPECTED_TRAIN_RECORDS:
        raise L6TrainingError("bundle_projection_identity_invalid")
    if (
        _sha256(projection_raw) != TRAIN_PROJECTION_SHA256
        or manifest.get("projection", {}).get("sha256") != TRAIN_PROJECTION_SHA256
    ):
        raise L6TrainingError("bundle_projection_hash_mismatch")
    return {
        "status": "ready",
        "train_records": len(validated),
        "files": len(actual),
        "bundle_manifest_sha256": _sha256(manifest_raw),
        "projection_sha256": _sha256(projection_raw),
    }


def verify_model_contract(repo_root: Path, tokenizer_dir: Path) -> dict[str, Any]:
    contract, contract_raw = _load_json(repo_root / MODEL_CONTRACT_RELATIVE_PATH)
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        raise L6TrainingError("model_contract_invalid")
    files = contract.get("tokenizer", {}).get("files")
    if not isinstance(files, dict) or set(files) != {
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
    }:
        raise L6TrainingError("tokenizer_contract_invalid")
    for name, identity in files.items():
        raw = _regular_file(tokenizer_dir / name)
        if identity.get("bytes") != len(raw) or identity.get("sha256") != _sha256(raw):
            raise L6TrainingError("tokenizer_file_hash_mismatch")
    template = contract.get("chat_template", {})
    template_raw = _regular_file(repo_root / template.get("tracked_relative_path", ""))
    if template.get("sha256") != _sha256(template_raw):
        raise L6TrainingError("chat_template_hash_mismatch")
    return {
        "contract": contract,
        "contract_sha256": _sha256(contract_raw),
        "chat_template": template_raw.decode("utf-8"),
    }


def _token_ids(value: Any) -> list[int]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, dict):
        value = value.get("input_ids")
    if (
        not isinstance(value, list)
        or not value
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
    ):
        raise L6TrainingError("tokenizer_result_invalid")
    if value and isinstance(value[0], list):
        if len(value) != 1:
            raise L6TrainingError("tokenizer_result_invalid")
        value = value[0]
    return list(value)


def tokenize_completion_only(tokenizer: Any, row: Mapping[str, Any]) -> TokenizedTrainingRow:
    validate_projection_row(row)
    prompt_messages = copy.deepcopy(row["messages"])
    full_messages = prompt_messages + [
        {"role": "assistant", "content": row["completion"]}
    ]
    try:
        prompt_ids = _token_ids(
            tokenizer.apply_chat_template(
                prompt_messages,
                tokenize=True,
                add_generation_prompt=True,
            )
        )
        full_ids = _token_ids(
            tokenizer.apply_chat_template(
                full_messages,
                tokenize=True,
                add_generation_prompt=False,
            )
        )
    except L6TrainingError:
        raise
    except Exception as exc:
        raise L6TrainingError("chat_template_tokenization_failed") from exc
    if len(full_ids) <= len(prompt_ids) or full_ids[: len(prompt_ids)] != prompt_ids:
        raise L6TrainingError("completion_boundary_not_prefix_safe")
    labels = [-100] * len(prompt_ids) + full_ids[len(prompt_ids) :]
    completion_tokens = len(full_ids) - len(prompt_ids)
    if (
        any(label != -100 for label in labels[: len(prompt_ids)])
        or any(label == -100 for label in labels[len(prompt_ids) :])
        or completion_tokens <= 0
        or all(label == -100 for label in labels)
    ):
        raise L6TrainingError("completion_only_mask_invalid")
    return TokenizedTrainingRow(
        input_ids=full_ids,
        attention_mask=[1] * len(full_ids),
        labels=labels,
        prompt_tokens=len(prompt_ids),
        completion_tokens=completion_tokens,
    )


def _nearest_rank(values: Sequence[int], percentile: int) -> int:
    ordered = sorted(values)
    if not ordered:
        raise L6TrainingError("token_census_empty")
    index = max(1, min(math.ceil(percentile / 100 * len(ordered)), len(ordered)))
    return ordered[index - 1]


def build_token_census(
    tokenizer: Any,
    projection: Sequence[Mapping[str, Any]],
    *,
    sequence_limit: int,
    tokenizer_identity: Mapping[str, Any],
) -> tuple[dict[str, Any], list[TokenizedTrainingRow]]:
    if len(projection) != EXPECTED_TRAIN_RECORDS or sequence_limit <= 0:
        raise L6TrainingError("token_census_input_invalid")
    tokenized = [tokenize_completion_only(tokenizer, row) for row in projection]
    lengths = [len(row.input_ids) for row in tokenized]
    over_limit = sum(length > sequence_limit for length in lengths)
    receipt = {
        "schema_version": TOKEN_CENSUS_SCHEMA_VERSION,
        "version": "rondo_local_approval_l6_exact_token_census_v1",
        "status": "complete" if over_limit == 0 else "over_limit",
        "exact": True,
        "records": len(tokenized),
        "projection_sha256": _sha256(_jsonl_bytes(projection)),
        "tokenizer": dict(tokenizer_identity),
        "chat_template_applied": True,
        "truncation": False,
        "packing": False,
        "sequence_tokens": {
            "min": min(lengths),
            "p50": _nearest_rank(lengths, 50),
            "p95": _nearest_rank(lengths, 95),
            "max": max(lengths),
            "total": sum(lengths),
            "limit": sequence_limit,
            "over_limit": over_limit,
        },
        "completion_only": {
            "prompt_tokens_total": sum(row.prompt_tokens for row in tokenized),
            "completion_tokens_total": sum(
                row.completion_tokens for row in tokenized
            ),
            "records_with_all_prompt_labels_masked": sum(
                all(label == -100 for label in row.labels[: row.prompt_tokens])
                for row in tokenized
            ),
            "records_with_unmasked_completion": sum(
                row.completion_tokens > 0
                and any(label != -100 for label in row.labels[row.prompt_tokens :])
                for row in tokenized
            ),
            "records_with_nonempty_completion": sum(
                row.completion_tokens > 0 for row in tokenized
            ),
        },
    }
    return receipt, tokenized


class FixtureTokenizer:
    """Deterministic byte tokenizer used only by the explicit mock dry-run."""

    @staticmethod
    def apply_chat_template(
        messages: Sequence[Mapping[str, Any]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> list[int]:
        if not tokenize:
            raise ValueError("fixture tokenizer only supports tokenize=True")
        rendered = bytearray(b"<bos>")
        for message in messages:
            rendered.extend(f"<{message['role']}>".encode())
            rendered.extend(_canonical_bytes(message["content"]))
        if add_generation_prompt:
            rendered.extend(b"<assistant>")
        elif messages and messages[-1].get("role") == "assistant":
            rendered.extend(b"<eos>")
        return list(rendered)


class FrozenFastTokenizer:
    """Small offline equivalent of the HF chat-template/tokenizer path.

    It uses the same frozen tokenizer.json and the same Jinja whitespace
    settings as ``apply_chat_template``.  This keeps the stage-1 census local
    when the large Transformers training stack is intentionally absent.
    """

    def __init__(self, tokenizer_dir: Path, chat_template: str) -> None:
        try:
            from jinja2 import StrictUndefined
            from jinja2.sandbox import ImmutableSandboxedEnvironment
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise L6TrainingError("tokenizer_runtime_dependency_missing") from exc
        config, _ = _load_json(tokenizer_dir / "tokenizer_config.json")
        if not isinstance(config, dict):
            raise L6TrainingError("tokenizer_config_invalid")
        self._bos_token = config.get("bos_token")
        self._eos_token = config.get("eos_token")
        self._pad_token = config.get("pad_token")
        if not all(
            isinstance(token, str) and token
            for token in (self._bos_token, self._eos_token, self._pad_token)
        ):
            raise L6TrainingError("tokenizer_special_tokens_invalid")
        try:
            self._tokenizer = Tokenizer.from_file(str(tokenizer_dir / "tokenizer.json"))
        except Exception as exc:
            raise L6TrainingError("tokenizer_load_failed") from exc
        self.pad_token_id = self._tokenizer.token_to_id(self._pad_token)
        if self.pad_token_id is None:
            raise L6TrainingError("tokenizer_pad_token_missing")
        environment = ImmutableSandboxedEnvironment(
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )

        def raise_exception(message: str) -> None:
            raise L6TrainingError("chat_template_rejected_messages")

        environment.globals["raise_exception"] = raise_exception
        environment.filters["tojson"] = lambda value: json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            self._template = environment.from_string(chat_template)
        except Exception as exc:
            raise L6TrainingError("chat_template_compile_failed") from exc

    def apply_chat_template(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> list[int]:
        if not tokenize:
            raise L6TrainingError("tokenizer_result_invalid")
        try:
            rendered = self._template.render(
                messages=messages,
                tools=None,
                bos_token=self._bos_token,
                eos_token=self._eos_token,
                pad_token=self._pad_token,
                add_generation_prompt=add_generation_prompt,
            )
            return list(self._tokenizer.encode(rendered, add_special_tokens=False).ids)
        except L6TrainingError:
            raise
        except Exception as exc:
            raise L6TrainingError("chat_template_tokenization_failed") from exc


def mock_dry_run(repo_root: Path, *, records: int = 6) -> dict[str, Any]:
    projection, _ = build_training_projection(repo_root)
    selected = projection[:records]
    tokenized = [tokenize_completion_only(FixtureTokenizer(), row) for row in selected]
    return {
        "status": "mock_pipeline_complete",
        "mock_only": True,
        "real_model_loaded": False,
        "optimizer_steps": 0,
        "records": len(tokenized),
        "prompt_labels_all_masked": all(
            all(label == -100 for label in row.labels[: row.prompt_tokens])
            for row in tokenized
        ),
        "completion_labels_present": all(
            any(label != -100 for label in row.labels[row.prompt_tokens :])
            for row in tokenized
        ),
    }


def _load_hf_tokenizer(tokenizer_dir: Path, chat_template: str) -> Any:
    try:
        from transformers import AutoTokenizer
    except ImportError:
        return FrozenFastTokenizer(tokenizer_dir, chat_template)
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            tokenizer_dir,
            local_files_only=True,
            trust_remote_code=False,
            use_fast=True,
        )
    except Exception as exc:
        raise L6TrainingError("tokenizer_load_failed") from exc
    tokenizer.chat_template = chat_template
    if tokenizer.pad_token_id is None:
        raise L6TrainingError("tokenizer_pad_token_missing")
    return tokenizer


def run_exact_census(
    repo_root: Path,
    tokenizer_dir: Path,
    output_path: Path,
    *,
    sequence_limit: int,
) -> dict[str, Any]:
    verified = verify_model_contract(repo_root, tokenizer_dir)
    projection, _ = build_training_projection(repo_root)
    tokenizer = _load_hf_tokenizer(tokenizer_dir, verified["chat_template"])
    contract = verified["contract"]
    receipt, _ = build_token_census(
        tokenizer,
        projection,
        sequence_limit=sequence_limit,
        tokenizer_identity={
            "repo": contract["tokenizer"]["repo"],
            "revision": contract["tokenizer"]["revision"],
            "model_contract_sha256": verified["contract_sha256"],
            "chat_template_sha256": contract["chat_template"]["sha256"],
            "files": contract["tokenizer"]["files"],
        },
    )
    _write_exclusive(output_path, _pretty_bytes(receipt))
    if receipt["sequence_tokens"]["over_limit"]:
        raise L6TrainingError("training_sequences_over_limit", receipt["sequence_tokens"])
    return receipt


def _dependency_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for distribution in sorted(DIRECT_DEPENDENCIES):
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = "missing"
    return versions


def _validate_dependency_identity(
    identity: Any,
    recipe: Mapping[str, Any],
    *,
    required_status: str,
    installed_packages: Mapping[str, str] | None = None,
    installed_python: str | None = None,
    installed_cuda: str | None = None,
) -> dict[str, Any]:
    expected_fields = {
        "schema_version",
        "status",
        "packages",
        "python_version",
        "cuda_version",
        "container_image",
    }
    if (
        not isinstance(identity, dict)
        or set(identity) != expected_fields
        or identity.get("schema_version") != 1
        or identity.get("status") != required_status
        or not isinstance(identity.get("packages"), dict)
        or set(identity["packages"]) != DIRECT_DEPENDENCIES
        or any(
            not isinstance(version, str) or not version or version == "missing"
            for version in identity["packages"].values()
        )
        or any(
            not isinstance(identity.get(field), str) or not identity[field]
            for field in ("python_version", "cuda_version", "container_image")
        )
        or identity["container_image"] != recipe.get("container", {}).get("image")
    ):
        raise L6TrainingError("formal_dependency_identity_invalid")
    if installed_packages is not None and dict(identity["packages"]) != dict(
        installed_packages
    ):
        raise L6TrainingError("formal_dependency_environment_mismatch")
    if installed_python is not None and identity["python_version"] != installed_python:
        raise L6TrainingError("formal_dependency_environment_mismatch")
    if installed_cuda is not None and identity["cuda_version"] != installed_cuda:
        raise L6TrainingError("formal_dependency_environment_mismatch")
    return copy.deepcopy(identity)


def _changed_recipe_paths(
    candidate: Any, final: Any, prefix: str = ""
) -> set[str]:
    if isinstance(candidate, dict) and isinstance(final, dict):
        changed: set[str] = set()
        for key in set(candidate) | set(final):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in candidate or key not in final:
                changed.add(path)
            else:
                changed.update(_changed_recipe_paths(candidate[key], final[key], path))
        return changed
    return set() if candidate == final else {prefix}


def resolve_run_contract(
    candidate_recipe: Mapping[str, Any],
    *,
    run_kind: str,
    final_recipe_path: Path | None,
    dependency_identity_path: Path | None,
) -> tuple[dict[str, Any], bytes, dict[str, Any] | None, str | None]:
    """Resolve smoke/formal without allowing an implicit mode transition."""

    if candidate_recipe.get("lora", {}).get("target_modules") != (
        LORA_TARGET_MODULE_PATTERN
    ):
        raise L6TrainingError("candidate_lora_target_pattern_invalid")
    if run_kind == "smoke":
        if final_recipe_path is not None or dependency_identity_path is not None:
            raise L6TrainingError("smoke_final_contract_not_allowed")
        recipe = copy.deepcopy(dict(candidate_recipe))
        recipe["candidate_status"] = "stage2_optimizer_smoke_only"
        recipe["optimizer"]["max_steps"] = 1
        recipe["optimizer"]["num_train_epochs"] = 1
        return recipe, _pretty_bytes(recipe), None, None
    if run_kind != "formal":
        raise L6TrainingError("run_kind_invalid")
    if final_recipe_path is None or dependency_identity_path is None:
        raise L6TrainingError("formal_frozen_contract_required")
    recipe, recipe_raw = _load_json(final_recipe_path)
    identity, identity_raw = _load_json(dependency_identity_path)
    adjustable = candidate_recipe.get("smoke_adjustable_once", [])
    changed_paths = _changed_recipe_paths(candidate_recipe, recipe)
    if (
        not isinstance(recipe, dict)
        or recipe.get("candidate_status") != "stage2_final_frozen"
        or recipe.get("schema_version") != 1
        or recipe.get("data", {}).get("expected_train_records")
        != EXPECTED_TRAIN_RECORDS
        or recipe.get("data", {}).get("completion_only") is not True
        or recipe.get("data", {}).get("truncation") is not False
        or recipe.get("data", {}).get("packing") is not False
        or recipe.get("quantization") != candidate_recipe.get("quantization")
        or recipe.get("lora", {}).get("target_modules")
        != LORA_TARGET_MODULE_PATTERN
        or recipe.get("optimizer", {}).get("max_steps") == 1
        or not isinstance(adjustable, list)
        or any(not isinstance(path, str) or not path for path in adjustable)
        or not changed_paths.issubset(set(adjustable) | {"candidate_status"})
    ):
        raise L6TrainingError("formal_recipe_invalid")
    verified_identity = _validate_dependency_identity(
        identity,
        recipe,
        required_status="stage2_final_frozen",
    )
    return dict(recipe), recipe_raw, verified_identity, _sha256(identity_raw)


def _hash_tree(path: Path) -> dict[str, Any]:
    try:
        root_info = os.lstat(path)
    except OSError as exc:
        raise L6TrainingError("artifact_tree_missing") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise L6TrainingError("artifact_tree_invalid")
    files: dict[str, dict[str, Any]] = {}
    for item in sorted(path.rglob("*")):
        if item.is_dir() and not item.is_symlink():
            continue
        raw = _regular_file(item, maximum_bytes=32 * 1024 * 1024 * 1024)
        files[item.relative_to(path).as_posix()] = {
            "bytes": len(raw),
            "sha256": _sha256(raw),
        }
    return {"files": files, "tree_sha256": _canonical_sha256(files)}


def validate_lora_injection(
    model: Any, target_module_pattern: str
) -> dict[str, Any]:
    """Fail closed on the concrete PEFT injection and trainable parameter set."""

    if target_module_pattern != LORA_TARGET_MODULE_PATTERN:
        raise L6TrainingError("lora_target_pattern_invalid")
    try:
        pattern = re.compile(target_module_pattern)
    except re.error as exc:
        raise L6TrainingError("lora_target_pattern_invalid") from exc
    targeted_value = getattr(model, "targeted_module_names", None)
    if (
        not isinstance(targeted_value, (list, tuple, set, frozenset))
        or not targeted_value
        or any(not isinstance(name, str) or not name for name in targeted_value)
    ):
        raise L6TrainingError("lora_targeted_modules_missing")
    targeted = tuple(sorted(set(targeted_value)))
    forbidden_markers = ("vision", "multi_modal_projector", "lm_head")
    if (
        len(targeted) != len(targeted_value)
        or any(pattern.fullmatch(name) is None for name in targeted)
        or any(marker in name for marker in forbidden_markers for name in targeted)
    ):
        raise L6TrainingError("lora_targeted_module_scope_invalid")
    trainable = tuple(
        name
        for name, parameter in model.named_parameters()
        if getattr(parameter, "requires_grad", False)
    )
    if not trainable:
        raise L6TrainingError("lora_trainable_scope_invalid")
    owners: set[str] = set()
    for parameter_name in trainable:
        matches = tuple(
            target
            for target in targeted
            if f".{target}." in f".{parameter_name}."
        )
        if (
            ".lora_" not in parameter_name
            or len(matches) != 1
            or pattern.fullmatch(matches[0]) is None
            or any(marker in parameter_name for marker in forbidden_markers)
        ):
            raise L6TrainingError("lora_trainable_scope_invalid")
        owners.add(matches[0])
    if owners != set(targeted):
        raise L6TrainingError("lora_trainable_scope_invalid")
    return {
        "target_pattern": target_module_pattern,
        "targeted_modules": len(targeted),
        "trainable_parameters": len(trainable),
        "vision_projector_lm_head_hits": 0,
    }


def _run_contract(
    *,
    run_id: str,
    run_kind: str,
    hardware_name: str,
    bundle: Mapping[str, Any],
    recipe_raw: bytes,
    dependency_identity_raw: bytes,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "version": "rondo_local_approval_l6_run_contract_v1",
        "run_id": run_id,
        "run_kind": run_kind,
        "hardware_name": hardware_name,
        "bundle_manifest_sha256": bundle["bundle_manifest_sha256"],
        "projection_sha256": bundle["projection_sha256"],
        "recipe_sha256": _sha256(recipe_raw),
        "dependency_identity_sha256": _sha256(dependency_identity_raw),
    }


def _checkpoint_for_resume(output_root: Path, resume_from: Path) -> Path:
    try:
        root_info = os.lstat(output_root)
    except OSError as exc:
        raise L6TrainingError("resume_output_missing") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise L6TrainingError("resume_output_invalid")
    root_absolute = Path(os.path.abspath(output_root))
    checkpoint_root = root_absolute / "checkpoints"
    candidate = Path(os.path.abspath(resume_from))
    try:
        relative = candidate.relative_to(checkpoint_root)
    except ValueError as exc:
        raise L6TrainingError("resume_checkpoint_outside_output") from exc
    if (
        relative.parent != Path(".")
        or re.fullmatch(r"checkpoint-[0-9]+", relative.name) is None
    ):
        raise L6TrainingError("resume_checkpoint_path_invalid")
    current = root_absolute
    for part in ("checkpoints", relative.name):
        current /= part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise L6TrainingError("resume_checkpoint_missing") from exc
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise L6TrainingError("resume_checkpoint_invalid")
    return candidate


def _prepare_training_output(
    output_root: Path,
    *,
    expected_contract: Mapping[str, Any],
    recipe_raw: bytes,
    dependency_identity_raw: bytes,
    resume_from_checkpoint: Path | None,
) -> str | None:
    if resume_from_checkpoint is None:
        if output_root.exists() or output_root.is_symlink():
            raise L6TrainingError("training_output_already_exists")
        output_root.mkdir(mode=0o700, parents=True)
        _write_exclusive(
            output_root / "run-contract.json", _pretty_bytes(expected_contract)
        )
        _write_exclusive(output_root / "actual-recipe.json", recipe_raw)
        _write_exclusive(
            output_root / "dependency-identity.json", dependency_identity_raw
        )
        return None
    checkpoint = _checkpoint_for_resume(output_root, resume_from_checkpoint)
    for completed_name in (
        "training-pending.json",
        "adapter-reload-receipt.json",
        "training-receipt.json",
    ):
        if (output_root / completed_name).exists() or (
            output_root / completed_name
        ).is_symlink():
            raise L6TrainingError("resume_after_training_completion_forbidden")
    if (output_root / "adapter-final").exists() or (
        output_root / "adapter-final"
    ).is_symlink():
        raise L6TrainingError("resume_after_adapter_save_forbidden")
    actual_contract, _ = _load_json(output_root / "run-contract.json")
    if actual_contract != dict(expected_contract):
        raise L6TrainingError("resume_run_contract_mismatch")
    actual_recipe_raw = _regular_file(output_root / "actual-recipe.json")
    actual_dependency_raw = _regular_file(output_root / "dependency-identity.json")
    if (
        _sha256(actual_recipe_raw) != _sha256(recipe_raw)
        or _sha256(actual_dependency_raw) != _sha256(dependency_identity_raw)
    ):
        raise L6TrainingError("resume_run_contract_mismatch")
    return str(checkpoint)


def _run_training(
    bundle_root: Path,
    output_root: Path,
    *,
    run_id: str,
    provider_job_id: str,
    hardware_name: str,
    run_kind: str,
    final_recipe_path: Path | None,
    dependency_identity_path: Path | None,
    resume_from_checkpoint: Path | None,
) -> dict[str, Any]:
    """Run the candidate QLoRA recipe.  Intended only for authorized stage 2."""

    bundle = verify_bundle(bundle_root)
    candidate_recipe, _ = _load_json(bundle_root / "contracts/recipe-candidate-v1.json")
    recipe, recipe_raw, dependency_identity, _ = resolve_run_contract(
        candidate_recipe,
        run_kind=run_kind,
        final_recipe_path=final_recipe_path,
        dependency_identity_path=dependency_identity_path,
    )
    model_contract, _ = _load_json(bundle_root / "contracts/model-contract-v1.json")
    projection, _ = _load_jsonl(bundle_root / "data/train-projection.jsonl")
    template_raw = _regular_file(bundle_root / "contracts/chat-template.jinja")
    if _sha256(template_raw) != model_contract["chat_template"]["sha256"]:
        raise L6TrainingError("chat_template_hash_mismatch")
    try:
        import torch
        import transformers
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        from transformers import BitsAndBytesConfig, Trainer, TrainingArguments
    except ImportError as exc:
        raise L6TrainingError("training_dependency_missing") from exc
    installed_dependencies = _dependency_versions()
    cuda_version = str(torch.version.cuda or "")
    if not cuda_version or any(
        value == "missing" for value in installed_dependencies.values()
    ):
        raise L6TrainingError("training_dependency_environment_incomplete")
    if dependency_identity is None:
        dependency_identity = {
            "schema_version": 1,
            "status": "stage2_smoke_observed",
            "packages": installed_dependencies,
            "python_version": platform.python_version(),
            "cuda_version": cuda_version,
            "container_image": recipe["container"]["image"],
        }
    else:
        dependency_identity = _validate_dependency_identity(
            dependency_identity,
            recipe,
            required_status="stage2_final_frozen",
            installed_packages=installed_dependencies,
            installed_python=platform.python_version(),
            installed_cuda=cuda_version,
        )
    dependency_identity_raw = _pretty_bytes(dependency_identity)
    expected_run_contract = _run_contract(
        run_id=run_id,
        run_kind=run_kind,
        hardware_name=hardware_name,
        bundle=bundle,
        recipe_raw=recipe_raw,
        dependency_identity_raw=dependency_identity_raw,
    )
    resume_checkpoint = _prepare_training_output(
        output_root,
        expected_contract=expected_run_contract,
        recipe_raw=recipe_raw,
        dependency_identity_raw=dependency_identity_raw,
        resume_from_checkpoint=resume_from_checkpoint,
    )
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        model_contract["tokenizer"]["repo"],
        revision=model_contract["tokenizer"]["revision"],
        trust_remote_code=False,
        use_fast=True,
    )
    tokenizer.chat_template = template_raw.decode("utf-8")
    census, tokenized = build_token_census(
        tokenizer,
        projection,
        sequence_limit=recipe["data"]["max_sequence_length"],
        tokenizer_identity={
            "repo": model_contract["tokenizer"]["repo"],
            "revision": model_contract["tokenizer"]["revision"],
            "chat_template_sha256": model_contract["chat_template"]["sha256"],
        },
    )
    if census["sequence_tokens"]["over_limit"]:
        raise L6TrainingError("training_sequences_over_limit")
    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type=recipe["quantization"]["bnb_4bit_quant_type"],
        bnb_4bit_use_double_quant=recipe["quantization"]["bnb_4bit_use_double_quant"],
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_quant_storage=torch.bfloat16,
    )
    loader_name = recipe["model"]["loader_class"]
    loader = getattr(transformers, loader_name, None)
    if loader is None:
        raise L6TrainingError("model_loader_class_unavailable")
    model = loader.from_pretrained(
        model_contract["base"]["repo"],
        revision=model_contract["base"]["revision"],
        quantization_config=quantization,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        attn_implementation=recipe["model"]["attention_implementation"],
        trust_remote_code=False,
    )
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=recipe["model"]["gradient_checkpointing"],
    )
    lora_kwargs = {
        "r": recipe["lora"]["rank"],
        "lora_alpha": recipe["lora"]["alpha"],
        "lora_dropout": recipe["lora"]["dropout"],
        "bias": recipe["lora"]["bias"],
        "target_modules": recipe["lora"]["target_modules"],
        "task_type": recipe["lora"]["task_type"],
    }
    if "exclude_modules" in inspect.signature(LoraConfig).parameters:
        lora_kwargs["exclude_modules"] = recipe["lora"]["exclude_modules"]
    model = get_peft_model(model, LoraConfig(**lora_kwargs))
    lora_injection = validate_lora_injection(
        model, recipe["lora"]["target_modules"]
    )

    class Dataset(torch.utils.data.Dataset):
        def __len__(self) -> int:
            return len(tokenized)

        def __getitem__(self, index: int) -> dict[str, list[int]]:
            row = tokenized[index]
            return {
                "input_ids": row.input_ids,
                "attention_mask": row.attention_mask,
                "labels": row.labels,
            }

    def collate(features: Sequence[Mapping[str, Sequence[int]]]) -> dict[str, Any]:
        maximum = max(len(item["input_ids"]) for item in features)
        pad = tokenizer.pad_token_id
        return {
            "input_ids": torch.tensor(
                [list(item["input_ids"]) + [pad] * (maximum - len(item["input_ids"])) for item in features],
                dtype=torch.long,
            ),
            "attention_mask": torch.tensor(
                [list(item["attention_mask"]) + [0] * (maximum - len(item["attention_mask"])) for item in features],
                dtype=torch.long,
            ),
            "labels": torch.tensor(
                [list(item["labels"]) + [-100] * (maximum - len(item["labels"])) for item in features],
                dtype=torch.long,
            ),
        }

    checkpoint_dir = output_root / "checkpoints"
    adapter_dir = output_root / "adapter-final"
    optimizer = recipe["optimizer"]
    arguments = TrainingArguments(
        output_dir=str(checkpoint_dir),
        per_device_train_batch_size=optimizer["per_device_train_batch_size"],
        gradient_accumulation_steps=optimizer["gradient_accumulation_steps"],
        learning_rate=optimizer["learning_rate"],
        num_train_epochs=optimizer["num_train_epochs"],
        max_steps=optimizer["max_steps"] if optimizer["max_steps"] is not None else -1,
        warmup_ratio=optimizer["warmup_ratio"],
        lr_scheduler_type=optimizer["lr_scheduler_type"],
        weight_decay=optimizer["weight_decay"],
        max_grad_norm=optimizer["max_grad_norm"],
        optim=optimizer["optim"],
        bf16=optimizer["bf16"],
        logging_steps=optimizer["logging_steps"],
        save_steps=recipe["checkpoint"]["save_steps"],
        save_total_limit=recipe["checkpoint"]["save_total_limit"],
        report_to="none",
        remove_unused_columns=False,
        seed=optimizer["seed"],
        data_seed=optimizer["seed"],
    )
    trainer = Trainer(
        model=model,
        args=arguments,
        train_dataset=Dataset(),
        data_collator=collate,
    )
    result = trainer.train(resume_from_checkpoint=resume_checkpoint)
    if run_kind == "smoke" and trainer.state.global_step != 1:
        raise L6TrainingError("smoke_step_contract_failed")
    if (
        isinstance(trainer.state.global_step, bool)
        or not isinstance(trainer.state.global_step, int)
        or trainer.state.global_step <= 0
        or not isinstance(trainer.state.epoch, (int, float))
        or isinstance(trainer.state.epoch, bool)
        or not isinstance(result.metrics.get("train_loss"), (int, float))
        or isinstance(result.metrics.get("train_loss"), bool)
    ):
        raise L6TrainingError("trainer_completion_metrics_missing")
    model.save_pretrained(adapter_dir, safe_serialization=True)
    tokenizer.save_pretrained(adapter_dir)
    trainer.save_state()
    artifacts = {
        "adapter": _hash_tree(adapter_dir),
        "checkpoints": _hash_tree(checkpoint_dir),
    }
    metrics = {
        "trainer_metrics": dict(result.metrics),
        "global_step": int(trainer.state.global_step),
        "actual_epochs": trainer.state.epoch,
        "train_loss": result.metrics.get("train_loss"),
        "lora_injection": lora_injection,
    }
    pending = {
        "schema_version": 1,
        "version": "rondo_local_approval_l6_training_pending_v1",
        "status": "pending_adapter_reload_and_finalize",
        "run_kind": run_kind,
        "base": model_contract,
        "train": {
            "records": EXPECTED_TRAIN_RECORDS,
            "source_train_jsonl_sha256": TRAIN_SHA256,
            "source_dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
            "projection_sha256": bundle["projection_sha256"],
            "completion_only": True,
        },
        "token_census": census,
        "recipe_sha256": _sha256(recipe_raw),
        "dependencies": {
            "identity": dependency_identity,
            "identity_sha256": _sha256(dependency_identity_raw),
        },
        "provider": {"name": "runpod", "job_id": provider_job_id, "run_id": run_id},
        "hardware": {"name": hardware_name, "cuda": cuda_version},
        "metrics": metrics,
        "output_paths": {"adapter": "adapter-final", "checkpoints": "checkpoints"},
        "artifacts": artifacts,
        "bundle_manifest_sha256": bundle["bundle_manifest_sha256"],
    }
    _write_exclusive(output_root / "training-pending.json", _pretty_bytes(pending))
    return pending


def _reload_adapter(bundle_root: Path, output_root: Path) -> dict[str, Any]:
    """Reload an adapter in a separate command/process for the stage-2 smoke."""

    bundle = verify_bundle(bundle_root)
    contract, _ = _load_json(bundle_root / "contracts/model-contract-v1.json")
    pending, pending_raw = _load_json(output_root / "training-pending.json")
    recipe, recipe_raw = _load_json(output_root / "actual-recipe.json")
    dependency_identity, dependency_identity_raw = _load_json(
        output_root / "dependency-identity.json"
    )
    adapter_dir = output_root / "adapter-final"
    expected = _hash_tree(adapter_dir)
    if (
        not isinstance(pending, dict)
        or pending.get("status") != "pending_adapter_reload_and_finalize"
        or pending.get("bundle_manifest_sha256")
        != bundle["bundle_manifest_sha256"]
        or pending.get("recipe_sha256") != _sha256(recipe_raw)
        or pending.get("dependencies", {}).get("identity_sha256")
        != _sha256(dependency_identity_raw)
        or pending.get("artifacts", {}).get("adapter") != expected
    ):
        raise L6TrainingError("reload_pending_contract_mismatch")
    try:
        import torch
        import transformers
        from peft import PeftModel
    except ImportError as exc:
        raise L6TrainingError("training_dependency_missing") from exc
    loader_name = recipe.get("model", {}).get("loader_class")
    loader = getattr(transformers, loader_name, None)
    if loader is None:
        raise L6TrainingError("model_loader_class_unavailable")
    quantization = recipe.get("quantization", {})
    quantization_config = transformers.BitsAndBytesConfig(
        load_in_4bit=quantization.get("load_in_4bit"),
        bnb_4bit_quant_type=quantization.get("bnb_4bit_quant_type"),
        bnb_4bit_use_double_quant=quantization.get("bnb_4bit_use_double_quant"),
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_quant_storage=torch.bfloat16,
    )
    base = loader.from_pretrained(
        contract["base"]["repo"],
        revision=contract["base"]["revision"],
        quantization_config=quantization_config,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation=recipe["model"]["attention_implementation"],
        trust_remote_code=False,
    )
    PeftModel.from_pretrained(base, adapter_dir, is_trainable=False)
    receipt = {
        "schema_version": 1,
        "version": "rondo_local_approval_l6_adapter_reload_receipt_v1",
        "status": "adapter_reloaded",
        "separate_command": True,
        "pending_receipt_sha256": _sha256(pending_raw),
        "recipe_sha256": _sha256(recipe_raw),
        "dependency_identity_sha256": _sha256(dependency_identity_raw),
        "loader_class": loader_name,
        "attention_implementation": recipe["model"]["attention_implementation"],
        "adapter_tree_sha256": expected["tree_sha256"],
    }
    _write_exclusive(
        output_root / "adapter-reload-receipt.json", _pretty_bytes(receipt)
    )
    return receipt


def _artifact_allowlist_from_bundle(
    bundle_root: Path,
) -> tuple[dict[str, Any], bytes]:
    value, raw = _load_json(
        bundle_root / "contracts/artifact-export-allowlist-v1.json"
    )
    if (
        _sha256(raw) != ARTIFACT_ALLOWLIST_SHA256
        or not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("allowed_prefixes"), list)
        or not isinstance(value.get("allowed_root_files"), list)
        or not isinstance(value.get("forbidden_path_terms"), list)
        or value.get("boundaries", {}).get("dataset_body_allowed") is not False
        or value.get("boundaries", {}).get("training_projection_allowed") is not False
        or value.get("boundaries", {}).get("per_sample_validation_output_allowed")
        is not False
    ):
        raise L6TrainingError("artifact_allowlist_invalid")
    return value, raw


def _enumerate_export_artifacts(
    output_root: Path, allowlist: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    try:
        root_info = os.lstat(output_root)
    except OSError as exc:
        raise L6TrainingError("artifact_output_missing") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise L6TrainingError("artifact_output_invalid")
    allowed_roots = set(allowlist["allowed_root_files"])
    allowed_prefixes = tuple(allowlist["allowed_prefixes"])
    forbidden_terms = tuple(
        str(term).casefold() for term in allowlist["forbidden_path_terms"]
    )
    files: dict[str, dict[str, Any]] = {}
    for item in sorted(output_root.rglob("*")):
        info = os.lstat(item)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise L6TrainingError("artifact_non_regular_entry")
        relative = item.relative_to(output_root).as_posix()
        if relative == "artifact-manifest.json":
            continue
        if relative not in allowed_roots and not any(
            relative.startswith(prefix) for prefix in allowed_prefixes
        ):
            raise L6TrainingError("artifact_path_not_allowlisted")
        if any(term in relative.casefold() for term in forbidden_terms):
            raise L6TrainingError("artifact_forbidden_path")
        raw = _regular_file(item, maximum_bytes=32 * 1024 * 1024 * 1024)
        files[relative] = {
            "bytes": len(raw),
            "sha256": _sha256(raw),
        }
    return files


def _artifact_manifest_value(
    bundle: Mapping[str, Any],
    allowlist_raw: bytes,
    files: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "version": "rondo_local_approval_l6_artifact_manifest_v1",
        "status": "ready_for_private_persistence",
        "bundle_manifest_sha256": bundle["bundle_manifest_sha256"],
        "artifact_allowlist_sha256": _sha256(allowlist_raw),
        "files": dict(sorted(files.items())),
    }


def write_artifact_manifest(bundle_root: Path, output_root: Path) -> dict[str, Any]:
    bundle = verify_bundle(bundle_root)
    allowlist, allowlist_raw = _artifact_allowlist_from_bundle(bundle_root)
    completed, completed_raw = _load_json(output_root / "training-receipt.json")
    if completed.get("status") != "completed":
        raise L6TrainingError("completed_receipt_required_for_export")
    files = _enumerate_export_artifacts(output_root, allowlist)
    if files.get("training-receipt.json", {}).get("sha256") != _sha256(
        completed_raw
    ):
        raise L6TrainingError("completed_receipt_export_mismatch")
    manifest = _artifact_manifest_value(bundle, allowlist_raw, files)
    raw = _pretty_bytes(manifest)
    _write_exclusive(output_root / "artifact-manifest.json", raw)
    return {**manifest, "manifest_sha256": _sha256(raw)}


def verify_artifact_manifest(bundle_root: Path, output_root: Path) -> dict[str, Any]:
    bundle = verify_bundle(bundle_root)
    allowlist, allowlist_raw = _artifact_allowlist_from_bundle(bundle_root)
    manifest, manifest_raw = _load_json(output_root / "artifact-manifest.json")
    actual = _enumerate_export_artifacts(output_root, allowlist)
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "schema_version",
            "version",
            "status",
            "bundle_manifest_sha256",
            "artifact_allowlist_sha256",
            "files",
        }
        or manifest.get("schema_version") != 1
        or manifest.get("version")
        != "rondo_local_approval_l6_artifact_manifest_v1"
        or manifest.get("status") != "ready_for_private_persistence"
        or manifest.get("bundle_manifest_sha256")
        != bundle["bundle_manifest_sha256"]
        or manifest.get("artifact_allowlist_sha256") != _sha256(allowlist_raw)
        or manifest.get("files") != actual
    ):
        raise L6TrainingError("artifact_manifest_verification_failed")
    return {
        "status": "verified",
        "files": len(actual),
        "manifest_sha256": _sha256(manifest_raw),
    }


def _validate_completed_receipt_schema(
    receipt: Mapping[str, Any], schema: Mapping[str, Any]
) -> None:
    properties = schema.get("properties")
    required = schema.get("required")
    if (
        schema.get("additionalProperties") is not False
        or not isinstance(properties, dict)
        or not isinstance(required, list)
        or set(properties) != set(required)
        or set(receipt) != set(required)
    ):
        raise L6TrainingError("training_receipt_schema_mismatch")
    for name, rule in properties.items():
        if "const" in rule and receipt[name] != rule["const"]:
            raise L6TrainingError("training_receipt_schema_mismatch")
        if "enum" in rule and receipt[name] not in rule["enum"]:
            raise L6TrainingError("training_receipt_schema_mismatch")
        if "pattern" in rule and (
            not isinstance(receipt[name], str)
            or re.fullmatch(rule["pattern"], receipt[name]) is None
        ):
            raise L6TrainingError("training_receipt_schema_mismatch")


def finalize_training_receipt(
    bundle_root: Path,
    output_root: Path,
    *,
    actual_runpod_cost_usd: str,
    persistence_kind: str,
    persistence_revision: str,
) -> dict[str, Any]:
    bundle = verify_bundle(bundle_root)
    if persistence_kind not in {
        "pod_volume",
        "network_volume",
        "private_hf_repo",
        "local_download",
    } or not persistence_revision:
        raise L6TrainingError("persistence_identity_invalid")
    try:
        cost = Decimal(actual_runpod_cost_usd)
    except InvalidOperation as exc:
        raise L6TrainingError("actual_runpod_cost_invalid") from exc
    if not cost.is_finite() or cost < 0:
        raise L6TrainingError("actual_runpod_cost_invalid")
    pending, pending_raw = _load_json(output_root / "training-pending.json")
    reload_receipt, reload_raw = _load_json(
        output_root / "adapter-reload-receipt.json"
    )
    recipe, recipe_raw = _load_json(output_root / "actual-recipe.json")
    dependency_identity, dependency_raw = _load_json(
        output_root / "dependency-identity.json"
    )
    run_contract, _ = _load_json(output_root / "run-contract.json")
    candidate_recipe, _ = _load_json(
        bundle_root / "contracts/recipe-candidate-v1.json"
    )
    model_contract, _ = _load_json(bundle_root / "contracts/model-contract-v1.json")
    adapter = _hash_tree(output_root / "adapter-final")
    checkpoints = _hash_tree(output_root / "checkpoints")
    run_kind = pending.get("run_kind") if isinstance(pending, dict) else None
    if run_kind == "formal":
        resolve_run_contract(
            candidate_recipe,
            run_kind="formal",
            final_recipe_path=output_root / "actual-recipe.json",
            dependency_identity_path=output_root / "dependency-identity.json",
        )
    elif run_kind == "smoke":
        if (
            not isinstance(recipe, dict)
            or recipe.get("candidate_status") != "stage2_optimizer_smoke_only"
            or recipe.get("optimizer", {}).get("max_steps") != 1
            or recipe.get("data", {}).get("packing") is not False
            or recipe.get("quantization") != candidate_recipe.get("quantization")
        ):
            raise L6TrainingError("finalize_contract_mismatch")
        _validate_dependency_identity(
            dependency_identity,
            recipe,
            required_status="stage2_smoke_observed",
        )
    else:
        raise L6TrainingError("finalize_contract_mismatch")
    metrics = pending.get("metrics", {}) if isinstance(pending, dict) else {}
    train = pending.get("train", {}) if isinstance(pending, dict) else {}
    if (
        not isinstance(pending, dict)
        or pending.get("status") != "pending_adapter_reload_and_finalize"
        or pending.get("bundle_manifest_sha256")
        != bundle["bundle_manifest_sha256"]
        or pending.get("base") != model_contract
        or train.get("records") != EXPECTED_TRAIN_RECORDS
        or train.get("source_train_jsonl_sha256") != TRAIN_SHA256
        or train.get("source_dataset_manifest_sha256") != DATASET_MANIFEST_SHA256
        or train.get("projection_sha256") != TRAIN_PROJECTION_SHA256
        or train.get("completion_only") is not True
        or isinstance(metrics.get("global_step"), bool)
        or not isinstance(metrics.get("global_step"), int)
        or metrics["global_step"] <= 0
        or not isinstance(metrics.get("actual_epochs"), (int, float))
        or isinstance(metrics.get("actual_epochs"), bool)
        or not isinstance(metrics.get("train_loss"), (int, float))
        or isinstance(metrics.get("train_loss"), bool)
        or pending.get("recipe_sha256") != _sha256(recipe_raw)
        or pending.get("dependencies", {}).get("identity_sha256")
        != _sha256(dependency_raw)
        or pending.get("artifacts")
        != {"adapter": adapter, "checkpoints": checkpoints}
        or reload_receipt.get("status") != "adapter_reloaded"
        or reload_receipt.get("pending_receipt_sha256") != _sha256(pending_raw)
        or reload_receipt.get("recipe_sha256") != _sha256(recipe_raw)
        or reload_receipt.get("dependency_identity_sha256")
        != _sha256(dependency_raw)
        or reload_receipt.get("adapter_tree_sha256") != adapter["tree_sha256"]
        or run_contract.get("recipe_sha256") != _sha256(recipe_raw)
        or run_contract.get("dependency_identity_sha256")
        != _sha256(dependency_raw)
        or run_contract.get("bundle_manifest_sha256")
        != bundle["bundle_manifest_sha256"]
        or run_contract.get("projection_sha256") != TRAIN_PROJECTION_SHA256
        or run_contract.get("run_kind") != run_kind
        or run_contract.get("run_id") != pending.get("provider", {}).get("run_id")
        or run_contract.get("hardware_name") != pending.get("hardware", {}).get("name")
        or pending.get("output_paths")
        != {"adapter": "adapter-final", "checkpoints": "checkpoints"}
    ):
        raise L6TrainingError("finalize_contract_mismatch")
    receipt = {
        "schema_version": 1,
        "version": "rondo_local_approval_l6_training_receipt_v1",
        "status": "completed",
        "run_kind": pending["run_kind"],
        "base": pending["base"],
        "train": pending["train"],
        "token_census": pending["token_census"],
        "recipe_sha256": _sha256(recipe_raw),
        "dependencies": {
            "identity": dependency_identity,
            "identity_sha256": _sha256(dependency_raw),
        },
        "cost": {
            "provider": "runpod",
            "actual_usd": format(cost, "f"),
        },
        "provider": pending["provider"],
        "persistence": {
            "kind": persistence_kind,
            "revision": persistence_revision,
        },
        "reload_receipt_sha256": _sha256(reload_raw),
        "hardware": pending["hardware"],
        "metrics": pending["metrics"],
        "output_paths": pending["output_paths"],
        "artifacts": {"adapter": adapter, "checkpoints": checkpoints},
        "bundle_manifest_sha256": bundle["bundle_manifest_sha256"],
    }
    schema, _ = _load_json(
        bundle_root / "contracts/training-receipt-v1.schema.json"
    )
    _validate_completed_receipt_schema(receipt, schema)
    receipt_raw = _pretty_bytes(receipt)
    manifest_path = output_root / "artifact-manifest.json"
    receipt_path = output_root / "training-receipt.json"
    if (
        receipt_path.exists()
        or receipt_path.is_symlink()
        or manifest_path.is_symlink()
    ):
        raise L6TrainingError("output_already_exists")
    allowlist, allowlist_raw = _artifact_allowlist_from_bundle(bundle_root)
    export_files = _enumerate_export_artifacts(output_root, allowlist)
    export_files["training-receipt.json"] = {
        "bytes": len(receipt_raw),
        "sha256": _sha256(receipt_raw),
    }
    manifest = _artifact_manifest_value(bundle, allowlist_raw, export_files)
    manifest_raw = _pretty_bytes(manifest)
    if manifest_path.exists():
        if _regular_file(manifest_path) != manifest_raw:
            raise L6TrainingError("output_already_exists")
    else:
        _write_exclusive(manifest_path, manifest_raw)
    # The completed receipt is intentionally the final write in the state
    # transition. If any earlier recomputation fails, only pending evidence
    # remains and no failure can be mistaken for completed training.
    _write_exclusive(receipt_path, receipt_raw)
    return {
        "status": "completed",
        "training_receipt_sha256": _sha256(receipt_raw),
        "artifact_manifest_sha256": _sha256(manifest_raw),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan 037 train-only L6 tooling")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare-bundle")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser("verify-bundle")
    verify.add_argument("--bundle", type=Path, required=True)
    dry = subparsers.add_parser("mock-dry-run")
    dry.add_argument("--repo", type=Path, required=True)
    dry.add_argument("--records", type=int, default=6)
    census = subparsers.add_parser("census")
    census.add_argument("--repo", type=Path, required=True)
    census.add_argument("--tokenizer-dir", type=Path, required=True)
    census.add_argument("--output", type=Path, required=True)
    census.add_argument("--sequence-limit", type=int, required=True)
    train = subparsers.add_parser("train")
    train.add_argument("--bundle", type=Path, required=True)
    train.add_argument("--output", type=Path, required=True)
    train.add_argument("--run-id", required=True)
    train.add_argument("--provider-job-id", required=True)
    train.add_argument("--hardware-name", required=True)
    train.add_argument("--run-kind", choices=("smoke", "formal"), required=True)
    train.add_argument("--final-recipe", type=Path)
    train.add_argument("--dependency-identity", type=Path)
    train.add_argument("--resume-from-checkpoint", type=Path)
    reload_parser = subparsers.add_parser("reload-adapter")
    reload_parser.add_argument("--bundle", type=Path, required=True)
    reload_parser.add_argument("--output", type=Path, required=True)
    finalize = subparsers.add_parser("finalize-receipt")
    finalize.add_argument("--bundle", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    finalize.add_argument("--actual-runpod-cost-usd", required=True)
    finalize.add_argument(
        "--persistence-kind",
        choices=(
            "pod_volume",
            "network_volume",
            "private_hf_repo",
            "local_download",
        ),
        required=True,
    )
    finalize.add_argument("--persistence-revision", required=True)
    artifact = subparsers.add_parser("artifact-manifest")
    artifact.add_argument("--bundle", type=Path, required=True)
    artifact.add_argument("--output", type=Path, required=True)
    verify_artifact = subparsers.add_parser("verify-artifacts")
    verify_artifact.add_argument("--bundle", type=Path, required=True)
    verify_artifact.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare-bundle":
            result = prepare_bundle(args.repo, args.output)
        elif args.command == "verify-bundle":
            result = verify_bundle(args.bundle)
        elif args.command == "mock-dry-run":
            result = mock_dry_run(args.repo, records=args.records)
        elif args.command == "census":
            result = run_exact_census(
                args.repo,
                args.tokenizer_dir,
                args.output,
                sequence_limit=args.sequence_limit,
            )
        elif args.command == "train":
            result = _run_training(
                args.bundle,
                args.output,
                run_id=args.run_id,
                provider_job_id=args.provider_job_id,
                hardware_name=args.hardware_name,
                run_kind=args.run_kind,
                final_recipe_path=args.final_recipe,
                dependency_identity_path=args.dependency_identity,
                resume_from_checkpoint=args.resume_from_checkpoint,
            )
        elif args.command == "reload-adapter":
            result = _reload_adapter(args.bundle, args.output)
        elif args.command == "finalize-receipt":
            result = finalize_training_receipt(
                args.bundle,
                args.output,
                actual_runpod_cost_usd=args.actual_runpod_cost_usd,
                persistence_kind=args.persistence_kind,
                persistence_revision=args.persistence_revision,
            )
        elif args.command == "artifact-manifest":
            result = write_artifact_manifest(args.bundle, args.output)
        else:
            result = verify_artifact_manifest(args.bundle, args.output)
    except L6TrainingError as exc:
        print(json.dumps({"status": "failed", "code": exc.code, "facts": exc.facts}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
