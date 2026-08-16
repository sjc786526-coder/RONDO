#!/usr/bin/env python3
"""Prepare and verify the body-free Plan 037 b10333 conversion tool bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


CONTRACT_VERSION = "rondo_local_approval_l6_b10333_conversion_tools_v1"
MANIFEST_VERSION = "rondo_local_approval_l6_conversion_tool_bundle_v1"
CONTRACT_NAME = "conversion-tool-contract-v1.json"
DEPENDENCIES_NAME = "conversion-dependencies-v1.txt"
MANIFEST_NAME = "conversion-tool-bundle-manifest.json"
MERGE_NAME = "merge_adapter.py"
OPERATIONS_NAME = "conversion-operations.json"
OPERATIONS_VERSION = "rondo_local_approval_l6_conversion_operations_v1"
TRAIN_SHA256 = "1e66c06e9357a3b6e14aedd193c5405ad2c18924e57da6a3a209f079b80c110a"
TRAIN_PROJECTION_SHA256 = (
    "0026cddd2a80771039c6644378120793d98310abdf66f01e7475416f23b2cc14"
)
DATASET_MANIFEST_SHA256 = (
    "dbf5fffe1f26d7746acf43fdcd092ff3e9cd64ea1f40046cd3b7219a15107190"
)
EXPECTED_TRAIN_RECORDS = 470
_HEX64 = __import__("re").compile(r"[0-9a-f]{64}\Z")


class ConversionToolError(RuntimeError):
    """Stable fail-closed conversion-tool preparation error."""


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
        raise ConversionToolError("json_canonicalization_failed") from exc


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
        raise ConversionToolError("json_serialization_failed") from exc


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _safe_regular_bytes(
    path: Path,
    *,
    limit: int = 16 * 1024 * 1024,
    allow_empty: bool = False,
) -> bytes:
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise ConversionToolError("required_file_missing") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or (before.st_size == 0 and not allow_empty)
        or before.st_size > limit
    ):
        raise ConversionToolError("required_file_invalid")
    try:
        raw = path.read_bytes()
        after = os.lstat(path)
    except OSError as exc:
        raise ConversionToolError("required_file_read_failed") from exc
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
    )
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise ConversionToolError("required_file_changed")
    return raw


def _identity(path: Path) -> dict[str, Any]:
    raw = _safe_regular_bytes(
        path, limit=256 * 1024 * 1024, allow_empty=True
    )
    return {"size_bytes": len(raw), "sha256": _sha256(raw)}


def _stream_identity(path: Path) -> dict[str, Any]:
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise ConversionToolError("deployment_file_missing") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ConversionToolError("deployment_file_invalid")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
            opened = os.fstat(handle.fileno())
        after = os.lstat(path)
    except OSError as exc:
        raise ConversionToolError("deployment_file_read_failed") from exc
    identity = lambda value: (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
    )
    if identity(before) != identity(opened) or identity(before) != identity(after):
        raise ConversionToolError("deployment_file_changed")
    return {"size_bytes": before.st_size, "sha256": digest.hexdigest()}


def _require_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ConversionToolError("required_directory_missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ConversionToolError("required_directory_invalid")


def _relative_path(value: str) -> Path:
    relative = Path(value)
    if (
        not value
        or "\\" in value
        or relative.is_absolute()
        or relative == Path(".")
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ConversionToolError("relative_path_invalid")
    return relative


def _tree_entries(root: Path) -> list[dict[str, Any]]:
    _require_directory(root)
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise ConversionToolError("tree_entry_missing") from exc
        if stat.S_ISDIR(info.st_mode):
            continue
        if stat.S_ISLNK(info.st_mode):
            entries.append(
                {"relative_path": relative, "symlink_target": os.readlink(path)}
            )
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ConversionToolError("tree_entry_invalid")
        identity = _identity(path)
        entries.append({"relative_path": relative, **identity})
    return entries


def _tree_identity(root: Path) -> dict[str, Any]:
    entries = _tree_entries(root)
    return {
        "entries": len(entries),
        "size_bytes": sum(item.get("size_bytes", 0) for item in entries),
        "sha256": _sha256(_canonical_bytes(entries)),
    }


def _load_contract(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = _safe_regular_bytes(path)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConversionToolError("conversion_contract_invalid") from exc
    expected_fields = {
        "schema_version",
        "contract_version",
        "base_model",
        "boundaries",
        "bundle_builder",
        "conversion_environment",
        "conversion_dependencies",
        "formal_training",
        "llama_cpp_source",
        "local_inference_runtime",
        "merge_builder",
        "output_allowlists",
        "quantizer_runtime",
        "routes",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_fields
        or value.get("schema_version") != 1
        or value.get("contract_version") != CONTRACT_VERSION
        or value.get("routes") != ["adapter_on_off", "paired_gguf"]
        or not isinstance(value.get("boundaries"), dict)
        or any(value["boundaries"].values())
        or set(value.get("output_allowlists", {})) != set(value["routes"])
    ):
        raise ConversionToolError("conversion_contract_invalid")
    return value, raw


def _require_expected_identity(path: Path, expected: Mapping[str, Any]) -> None:
    if (
        not isinstance(expected, Mapping)
        or set(expected) != {"size_bytes", "sha256"}
        or not isinstance(expected.get("size_bytes"), int)
        or expected["size_bytes"] <= 0
        or not isinstance(expected.get("sha256"), str)
        or _HEX64.fullmatch(expected["sha256"]) is None
        or _identity(path) != dict(expected)
    ):
        raise ConversionToolError("source_identity_mismatch")


def verify_sources(
    contract_path: Path, source_root: Path, quantizer_root: Path
) -> dict[str, Any]:
    contract, contract_raw = _load_contract(contract_path)
    _require_directory(source_root)
    _require_directory(quantizer_root)
    source = contract["llama_cpp_source"]
    for relative_name, expected in source["top_level_files"].items():
        _require_expected_identity(source_root / _relative_path(relative_name), expected)
    for relative_name, expected in source["trees"].items():
        if _tree_identity(source_root / _relative_path(relative_name)) != expected:
            raise ConversionToolError("source_tree_identity_mismatch")

    runtime = contract["quantizer_runtime"]
    selected: list[dict[str, Any]] = []
    for relative_name, expected in sorted(runtime["regular_files"].items()):
        path = quantizer_root / _relative_path(relative_name)
        _require_expected_identity(path, expected)
        selected.append({"relative_path": relative_name, **dict(expected)})
    for relative_name, target in sorted(runtime["symlinks"].items()):
        path = quantizer_root / _relative_path(relative_name)
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise ConversionToolError("quantizer_symlink_missing") from exc
        if not stat.S_ISLNK(info.st_mode) or os.readlink(path) != target:
            raise ConversionToolError("quantizer_symlink_mismatch")
        selected.append({"relative_path": relative_name, "symlink_target": target})
    selected.sort(key=lambda item: item["relative_path"])
    if _sha256(_canonical_bytes(selected)) != runtime[
        "canonical_selected_tree_sha256"
    ]:
        raise ConversionToolError("quantizer_selected_tree_mismatch")

    dependencies_path = contract_path.parent / DEPENDENCIES_NAME
    _require_expected_identity(
        dependencies_path,
        {
            "size_bytes": contract["conversion_dependencies"]["size_bytes"],
            "sha256": contract["conversion_dependencies"]["sha256"],
        },
    )
    return {
        "status": "verified",
        "contract_sha256": _sha256(contract_raw),
        "source_commit": source["commit"],
        "quantizer_release": runtime["lock_sha256"],
    }


def _copy_regular(source: Path, target: Path) -> None:
    _safe_regular_bytes(
        source, limit=256 * 1024 * 1024, allow_empty=True
    )
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copy2(source, target, follow_symlinks=False)


def _copy_tree(source: Path, target: Path) -> None:
    entries = _tree_entries(source)
    if any("symlink_target" in item for item in entries):
        raise ConversionToolError("converter_source_symlink_forbidden")
    for item in entries:
        relative = _relative_path(item["relative_path"])
        _copy_regular(source / relative, target / relative)


def _package_entries(root: Path) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for item in _tree_entries(root):
        relative_name = item["relative_path"]
        if relative_name == MANIFEST_NAME:
            continue
        if "symlink_target" in item:
            entries[relative_name] = {
                "kind": "symlink",
                "symlink_target": item["symlink_target"],
            }
        else:
            entries[relative_name] = {
                "kind": "regular_file",
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
            }
    return entries


def verify_package(root: Path) -> dict[str, Any]:
    _require_directory(root)
    manifest_raw = _safe_regular_bytes(root / MANIFEST_NAME)
    try:
        manifest = json.loads(manifest_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConversionToolError("tool_bundle_manifest_invalid") from exc
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {
            "schema_version",
            "version",
            "contract_sha256",
            "files",
        }
        or manifest.get("schema_version") != 1
        or manifest.get("version") != MANIFEST_VERSION
        or not isinstance(manifest.get("contract_sha256"), str)
        or _HEX64.fullmatch(manifest["contract_sha256"]) is None
        or not isinstance(manifest.get("files"), dict)
    ):
        raise ConversionToolError("tool_bundle_manifest_mismatch")
    package_entries = _package_entries(root)
    if manifest["files"] != package_entries:
        raise ConversionToolError("tool_bundle_manifest_mismatch")
    contract_path = root / "contracts" / CONTRACT_NAME
    contract_raw = _safe_regular_bytes(contract_path)
    if _sha256(contract_raw) != manifest["contract_sha256"]:
        raise ConversionToolError("tool_bundle_contract_mismatch")
    contract, _raw = _load_contract(contract_path)
    _require_expected_identity(
        root / "bin" / "conversion_tooling.py",
        {
            "size_bytes": contract["bundle_builder"]["size_bytes"],
            "sha256": contract["bundle_builder"]["sha256"],
        },
    )
    _require_expected_identity(
        root / "bin" / MERGE_NAME,
        {
            "size_bytes": contract["merge_builder"]["size_bytes"],
            "sha256": contract["merge_builder"]["sha256"],
        },
    )
    verify_sources(
        contract_path,
        root / "tools" / "llama.cpp",
        root / "tools" / "llama-b10333-cpu",
    )

    expected_paths = {
        "bin/conversion_tooling.py",
        f"bin/{MERGE_NAME}",
        f"contracts/{CONTRACT_NAME}",
        f"contracts/{DEPENDENCIES_NAME}",
    }
    source = contract["llama_cpp_source"]
    expected_paths.update(
        f"tools/llama.cpp/{name}" for name in source["top_level_files"]
    )
    for tree_name in source["trees"]:
        tree_root = root / "tools" / "llama.cpp" / _relative_path(tree_name)
        expected_paths.update(
            f"tools/llama.cpp/{tree_name}/{item['relative_path']}"
            for item in _tree_entries(tree_root)
        )
    runtime = contract["quantizer_runtime"]
    expected_paths.update(
        f"tools/llama-b10333-cpu/{name}"
        for name in (*runtime["regular_files"], *runtime["symlinks"])
    )
    if set(package_entries) != expected_paths:
        raise ConversionToolError("tool_bundle_allowlist_mismatch")
    return {
        "status": "verified",
        "files": len(manifest["files"]),
        "manifest_sha256": _sha256(manifest_raw),
        "contract_sha256": manifest["contract_sha256"],
    }


def _load_json_file(path: Path, *, limit: int = 16 * 1024 * 1024) -> tuple[Any, bytes]:
    raw = _safe_regular_bytes(path, limit=limit)
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ConversionToolError("json_file_invalid") from exc


def _dependency_pins(path: Path) -> dict[str, str]:
    raw = _safe_regular_bytes(path)
    pins: dict[str, str] = {}
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ConversionToolError("conversion_dependencies_invalid") from exc
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if value.count("==") != 1:
            raise ConversionToolError("conversion_dependencies_invalid")
        name, version = value.split("==")
        if not name or not version or name in pins:
            raise ConversionToolError("conversion_dependencies_invalid")
        pins[name] = version
    if not pins:
        raise ConversionToolError("conversion_dependencies_invalid")
    return pins


def _validate_formal_training_receipt(
    training: Any, contract: Mapping[str, Any]
) -> str:
    expected_fields = {
        "schema_version",
        "version",
        "status",
        "run_kind",
        "base",
        "train",
        "token_census",
        "recipe_sha256",
        "dependencies",
        "cost",
        "provider",
        "persistence",
        "reload_receipt_sha256",
        "hardware",
        "metrics",
        "output_paths",
        "artifacts",
        "bundle_manifest_sha256",
    }
    if not isinstance(training, dict):
        raise ConversionToolError("formal_training_receipt_invalid")

    def mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, dict) else {}

    formal = contract["formal_training"]
    base = mapping(training.get("base"))
    base_model = mapping(base.get("base"))
    base_tokenizer = mapping(base.get("tokenizer"))
    base_template = mapping(base.get("chat_template"))
    train = mapping(training.get("train"))
    census = mapping(training.get("token_census"))
    census_tokenizer = mapping(census.get("tokenizer"))
    tokens = mapping(census.get("sequence_tokens"))
    completion = mapping(census.get("completion_only"))
    dependencies = mapping(training.get("dependencies"))
    dependency_identity = mapping(dependencies.get("identity"))
    provider = mapping(training.get("provider"))
    cost = mapping(training.get("cost"))
    artifacts = mapping(training.get("artifacts"))
    training_dependency_fields = {
        "schema_version",
        "status",
        "packages",
        "python_version",
        "cuda_version",
        "container_image",
    }
    adapter_tree = (
        mapping(artifacts.get("adapter")).get("tree_sha256")
    )
    adapter = mapping(artifacts.get("adapter"))
    adapter_files = adapter.get("files", {})
    try:
        actual_cost = Decimal(str(cost.get("actual_usd")))
    except (InvalidOperation, ValueError):
        actual_cost = Decimal("NaN")
    if (
        set(training) != expected_fields
        or training.get("schema_version") != 1
        or training.get("version")
        != "rondo_local_approval_l6_training_receipt_v1"
        or training.get("status") != "completed"
        or training.get("run_kind") != "formal"
        or provider.get("name") != "runpod"
        or cost.get("provider") != "runpod"
        or not actual_cost.is_finite()
        or actual_cost < 0
        or training.get("output_paths")
        != {"adapter": "adapter-final", "checkpoints": "checkpoints"}
        or base_model
        != {
            "repo": contract["base_model"]["repo_id"],
            "revision": contract["base_model"]["revision"],
        }
        or base_tokenizer.get("repo") != formal["tokenizer_repo"]
        or base_tokenizer.get("revision") != formal["tokenizer_revision"]
        or base_template.get("sha256") != formal["chat_template_sha256"]
        or train
        != {
            "records": EXPECTED_TRAIN_RECORDS,
            "source_train_jsonl_sha256": TRAIN_SHA256,
            "source_dataset_manifest_sha256": DATASET_MANIFEST_SHA256,
            "projection_sha256": TRAIN_PROJECTION_SHA256,
            "completion_only": True,
        }
        or census.get("status") != "complete"
        or census.get("exact") is not True
        or census.get("records") != EXPECTED_TRAIN_RECORDS
        or census.get("projection_sha256") != TRAIN_PROJECTION_SHA256
        or census.get("truncation") is not False
        or census.get("packing") is not False
        or census_tokenizer.get("repo") != formal["tokenizer_repo"]
        or census_tokenizer.get("revision") != formal["tokenizer_revision"]
        or census_tokenizer.get("chat_template_sha256")
        != formal["chat_template_sha256"]
        or tokens.get("limit") != formal["sequence_limit"]
        or tokens.get("over_limit") != 0
        or completion.get("records_with_all_prompt_labels_masked")
        != EXPECTED_TRAIN_RECORDS
        or completion.get("records_with_unmasked_completion")
        != EXPECTED_TRAIN_RECORDS
        or not isinstance(dependencies, dict)
        or set(dependencies) != {"identity", "identity_sha256"}
        or not isinstance(dependency_identity, dict)
        or set(dependency_identity) != training_dependency_fields
        or dependency_identity.get("schema_version") != 1
        or dependency_identity.get("status") != "stage2_final_frozen"
        or set(dependency_identity.get("packages", {}))
        != {
            "torch",
            "transformers",
            "peft",
            "trl",
            "accelerate",
            "bitsandbytes",
            "safetensors",
        }
        or any(
            not isinstance(version, str) or not version or version == "missing"
            for version in dependency_identity.get("packages", {}).values()
        )
        or any(
            not isinstance(dependency_identity.get(field), str)
            or not dependency_identity[field]
            for field in ("python_version", "cuda_version", "container_image")
        )
        or dependency_identity.get("container_image")
        != contract["conversion_environment"]["container_image"]
        or dependencies.get("identity_sha256")
        != _sha256(_pretty_bytes(dependency_identity))
        or not isinstance(training.get("recipe_sha256"), str)
        or _HEX64.fullmatch(training["recipe_sha256"]) is None
        or not isinstance(adapter_tree, str)
        or _HEX64.fullmatch(adapter_tree) is None
        or not isinstance(adapter_files, dict)
        or not adapter_files
        or any(
            not isinstance(name, str)
            or not name
            or not isinstance(identity, dict)
            or set(identity) != {"bytes", "sha256"}
            or not isinstance(identity.get("bytes"), int)
            or identity["bytes"] <= 0
            or not isinstance(identity.get("sha256"), str)
            or _HEX64.fullmatch(identity["sha256"]) is None
            for name, identity in adapter_files.items()
        )
        or adapter_tree != _sha256(_canonical_bytes(adapter_files))
    ):
        raise ConversionToolError("formal_training_receipt_invalid")
    return adapter_tree


def _tool_specs(route: str) -> tuple[tuple[str, str, str], ...]:
    common = (
        (
            "convert_hf_to_gguf",
            "tools/llama.cpp/convert_hf_to_gguf.py",
            "tooling/convert_hf_to_gguf.py",
        ),
        (
            "llama_quantize",
            "tools/llama-b10333-cpu/llama-quantize",
            "tooling/llama-quantize",
        ),
    )
    if route == "adapter_on_off":
        return common + (
            (
                "convert_lora_to_gguf",
                "tools/llama.cpp/convert_lora_to_gguf.py",
                "tooling/convert_lora_to_gguf.py",
            ),
        )
    if route == "paired_gguf":
        return common + (
            ("merge_adapter", f"bin/{MERGE_NAME}", f"tooling/{MERGE_NAME}"),
        )
    raise ConversionToolError("conversion_route_invalid")


def _operation_tools(
    route: str, tool_bundle: Path, deployment: Path
) -> dict[str, dict[str, Any]]:
    tools: dict[str, dict[str, Any]] = {}
    for role, bundle_relative, deployment_relative in _tool_specs(route):
        bundled = _stream_identity(tool_bundle / _relative_path(bundle_relative))
        deployed = _stream_identity(deployment / _relative_path(deployment_relative))
        if bundled != deployed:
            raise ConversionToolError("conversion_tool_identity_mismatch")
        tools[role] = {
            "bundle_relative_path": bundle_relative,
            "deployment_relative_path": deployment_relative,
            **bundled,
        }
    return tools


def _steps_for_operations(
    route: str,
    *,
    tool_bundle: str,
    deployment: str,
    base_snapshot: str,
    formal_output: str,
    conversion_python: str,
    training_python: str,
) -> list[dict[str, Any]]:
    converter = f"{tool_bundle}/tools/llama.cpp"
    quantizer = f"{tool_bundle}/tools/llama-b10333-cpu/llama-quantize"
    steps = [
        {
            "name": "base_hf_to_f16",
            "tool": "convert_hf_to_gguf",
            "argv": [
                conversion_python,
                f"{converter}/convert_hf_to_gguf.py",
                "--outfile",
                f"{deployment}/work/base-f16.gguf",
                "--outtype",
                "f16",
                "--use-temp-file",
                base_snapshot,
            ],
        },
        {
            "name": "base_quantize_q4_k_m",
            "tool": "llama_quantize",
            "argv": [
                quantizer,
                f"{deployment}/work/base-f16.gguf",
                f"{deployment}/base-q4_k_m.gguf",
                "Q4_K_M",
            ],
        },
    ]
    if route == "adapter_on_off":
        steps.append(
            {
                "name": "adapter_to_f16",
                "tool": "convert_lora_to_gguf",
                "argv": [
                    conversion_python,
                    f"{converter}/convert_lora_to_gguf.py",
                    "--base",
                    base_snapshot,
                    "--outfile",
                    f"{deployment}/adapter-f16.gguf",
                    "--outtype",
                    "f16",
                    f"{formal_output}/adapter-final",
                ],
            }
        )
    else:
        steps.extend(
            [
                {
                    "name": "merge_adapter_into_base",
                    "tool": "merge_adapter",
                    "argv": [
                        training_python,
                        f"{deployment}/tooling/{MERGE_NAME}",
                        "--base",
                        base_snapshot,
                        "--adapter",
                        f"{formal_output}/adapter-final",
                        "--output",
                        f"{deployment}/work/merged-hf",
                    ],
                },
                {
                    "name": "finetuned_hf_to_f16",
                    "tool": "convert_hf_to_gguf",
                    "argv": [
                        conversion_python,
                        f"{converter}/convert_hf_to_gguf.py",
                        "--outfile",
                        f"{deployment}/work/finetuned-f16.gguf",
                        "--outtype",
                        "f16",
                        "--use-temp-file",
                        f"{deployment}/work/merged-hf",
                    ],
                },
                {
                    "name": "finetuned_quantize_q4_k_m",
                    "tool": "llama_quantize",
                    "argv": [
                        quantizer,
                        f"{deployment}/work/finetuned-f16.gguf",
                        f"{deployment}/finetuned-q4_k_m.gguf",
                        "Q4_K_M",
                    ],
                },
            ]
        )
    return steps


def write_operations(
    contract_path: Path,
    tool_bundle: Path,
    output: Path,
    training_receipt_path: Path,
    *,
    route: str,
    base_snapshot: Path,
    formal_output: Path,
    conversion_python: Path,
    training_python: Path,
) -> dict[str, Any]:
    package = verify_package(tool_bundle)
    contract, contract_raw = _load_contract(contract_path)
    embedded_raw = _safe_regular_bytes(tool_bundle / "contracts" / CONTRACT_NAME)
    if contract_raw != embedded_raw or route not in contract["routes"]:
        raise ConversionToolError("tool_bundle_contract_mismatch")
    _require_directory(output)
    training, training_raw = _load_json_file(training_receipt_path)
    _validate_formal_training_receipt(training, contract)
    operations_path = output / OPERATIONS_NAME
    if operations_path.exists() or operations_path.is_symlink():
        raise ConversionToolError("conversion_operations_exists")
    path_roles = {
        "tool_bundle": str(tool_bundle),
        "deployment": str(output),
        "base_snapshot": str(base_snapshot),
        "formal_output": str(formal_output),
        "conversion_python": str(conversion_python),
        "training_python": str(training_python),
    }
    if any(not value.startswith("/") for value in path_roles.values()):
        raise ConversionToolError("conversion_operations_path_invalid")
    value = {
        "schema_version": 1,
        "version": OPERATIONS_VERSION,
        "route": route,
        "base_model": contract["base_model"],
        "quantization": "Q4_K_M",
        "training_receipt_sha256": _sha256(training_raw),
        "tool_bundle_manifest_sha256": package["manifest_sha256"],
        "path_roles": path_roles,
        "tools": _operation_tools(route, tool_bundle, output),
        "steps": _steps_for_operations(route, **path_roles),
    }
    operations_path.write_bytes(_pretty_bytes(value))
    return value


def _validate_operations(
    raw: bytes,
    value: Any,
    *,
    route: str,
    contract: Mapping[str, Any],
    tool_bundle: Path,
    output: Path,
    training_sha256: str,
    tool_manifest_sha256: str,
) -> None:
    expected_fields = {
        "schema_version",
        "version",
        "route",
        "base_model",
        "quantization",
        "training_receipt_sha256",
        "tool_bundle_manifest_sha256",
        "path_roles",
        "tools",
        "steps",
    }
    path_roles = value.get("path_roles", {}) if isinstance(value, dict) else {}
    if (
        not isinstance(value, dict)
        or raw != _pretty_bytes(value)
        or set(value) != expected_fields
        or value.get("schema_version") != 1
        or value.get("version") != OPERATIONS_VERSION
        or value.get("route") != route
        or value.get("base_model") != contract["base_model"]
        or value.get("quantization") != "Q4_K_M"
        or value.get("training_receipt_sha256") != training_sha256
        or value.get("tool_bundle_manifest_sha256") != tool_manifest_sha256
        or not isinstance(path_roles, dict)
        or set(path_roles)
        != {
            "tool_bundle",
            "deployment",
            "base_snapshot",
            "formal_output",
            "conversion_python",
            "training_python",
        }
        or any(
            not isinstance(item, str) or not item.startswith("/")
            for item in path_roles.values()
        )
        or value.get("tools") != _operation_tools(route, tool_bundle, output)
        or value.get("steps") != _steps_for_operations(route, **path_roles)
    ):
        raise ConversionToolError("conversion_operations_invalid")


def _validate_conversion_dependency_identity(
    raw: bytes,
    value: Any,
    *,
    route: str,
    contract: Mapping[str, Any],
    tool_bundle: Path,
) -> None:
    environment = contract["conversion_environment"]
    expected_fields = {
        "schema_version",
        "version",
        "packages",
        "python",
        "torch",
        "cuda",
        "container_image",
        "route",
    }
    if (
        not isinstance(value, dict)
        or raw != _pretty_bytes(value)
        or set(value) != expected_fields
        or value.get("schema_version") != 1
        or value.get("version")
        != "rondo_local_approval_l6_conversion_dependency_identity_v1"
        or value.get("packages")
        != _dependency_pins(tool_bundle / "contracts" / DEPENDENCIES_NAME)
        or not isinstance(value.get("python"), str)
        or not value["python"].startswith(environment["python_prefix"])
        or not isinstance(value.get("torch"), str)
        or value["torch"].split("+", 1)[0] != environment["torch"]
        or value.get("cuda") != environment["cuda"]
        or value.get("container_image") != environment["container_image"]
        or value.get("route") != route
    ):
        raise ConversionToolError("conversion_dependency_identity_invalid")


def verify_output(
    contract_path: Path,
    output: Path,
    training_receipt_path: Path,
    tool_bundle: Path,
) -> dict[str, Any]:
    package = verify_package(tool_bundle)
    contract, contract_raw = _load_contract(contract_path)
    if contract_raw != _safe_regular_bytes(tool_bundle / "contracts" / CONTRACT_NAME):
        raise ConversionToolError("tool_bundle_contract_mismatch")
    _require_directory(output)
    training, training_raw = _load_json_file(training_receipt_path)
    adapter_tree = _validate_formal_training_receipt(training, contract)
    manifest, manifest_raw = _load_json_file(
        output / "conversion-files-manifest.json"
    )
    receipt, receipt_raw = _load_json_file(output / "conversion-receipt.json")
    route = receipt.get("route") if isinstance(receipt, dict) else None
    if (
        route not in contract["routes"]
        or not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "version", "route", "files"}
        or manifest.get("schema_version") != 1
        or manifest.get("version")
        != "rondo_local_approval_l6_conversion_files_v1"
        or manifest.get("route") != route
        or not isinstance(manifest.get("files"), dict)
    ):
        raise ConversionToolError("deployment_receipt_invalid")
    allowed = set(contract["output_allowlists"][route])
    observed: set[str] = set()
    for path in output.rglob("*"):
        try:
            info = os.lstat(path)
        except OSError as exc:
            raise ConversionToolError("deployment_file_missing") from exc
        if stat.S_ISDIR(info.st_mode):
            continue
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ConversionToolError("deployment_file_invalid")
        observed.add(path.relative_to(output).as_posix())
    if observed != allowed:
        raise ConversionToolError("deployment_output_allowlist_mismatch")
    body_paths = allowed - {
        "conversion-files-manifest.json",
        "conversion-receipt.json",
    }
    if set(manifest["files"]) != body_paths:
        raise ConversionToolError("deployment_files_manifest_mismatch")
    actual_files = {
        name: _stream_identity(output / _relative_path(name))
        for name in sorted(body_paths)
    }
    if manifest["files"] != actual_files:
        raise ConversionToolError("deployment_files_manifest_mismatch")

    operations, operations_raw = _load_json_file(output / OPERATIONS_NAME)
    _validate_operations(
        operations_raw,
        operations,
        route=route,
        contract=contract,
        tool_bundle=tool_bundle,
        output=output,
        training_sha256=_sha256(training_raw),
        tool_manifest_sha256=package["manifest_sha256"],
    )
    dependency_identity, dependency_raw = _load_json_file(
        output / "conversion-dependency-identity.json"
    )
    _validate_conversion_dependency_identity(
        dependency_raw,
        dependency_identity,
        route=route,
        contract=contract,
        tool_bundle=tool_bundle,
    )

    expected_receipt_fields = {
        "schema_version",
        "version",
        "status",
        "route",
        "base_model",
        "quantization",
        "source_adapter_tree_sha256",
        "training_receipt_sha256",
        "conversion_contract_sha256",
        "tool_bundle_manifest_sha256",
        "dependency_identity_sha256",
        "operations_sha256",
        "files_manifest_sha256",
        "deployed_outputs",
        "temporary_f16_and_merged_hf_removed",
    }
    deployed = {
        name: actual_files[name]
        for name in sorted(actual_files)
        if name.endswith(".gguf")
    }
    if (
        not isinstance(receipt, dict)
        or set(receipt) != expected_receipt_fields
        or receipt.get("schema_version") != 1
        or receipt.get("version")
        != "rondo_local_approval_l6_conversion_receipt_v1"
        or receipt.get("status") != "completed"
        or receipt.get("base_model") != contract["base_model"]
        or receipt.get("quantization") != "Q4_K_M"
        or receipt.get("source_adapter_tree_sha256") != adapter_tree
        or receipt.get("training_receipt_sha256") != _sha256(training_raw)
        or receipt.get("conversion_contract_sha256") != _sha256(contract_raw)
        or receipt.get("tool_bundle_manifest_sha256")
        != package["manifest_sha256"]
        or receipt.get("dependency_identity_sha256") != _sha256(dependency_raw)
        or receipt.get("operations_sha256") != _sha256(operations_raw)
        or receipt.get("files_manifest_sha256") != _sha256(manifest_raw)
        or receipt.get("deployed_outputs") != deployed
        or receipt.get("temporary_f16_and_merged_hf_removed") is not True
    ):
        raise ConversionToolError("deployment_receipt_mismatch")
    return {
        "status": "verified",
        "route": route,
        "files": len(observed),
        "receipt_sha256": _sha256(receipt_raw),
        "operations_sha256": _sha256(operations_raw),
        "files_manifest_sha256": _sha256(manifest_raw),
        "training_receipt_sha256": _sha256(training_raw),
    }


def prepare_package(
    contract_path: Path,
    source_root: Path,
    quantizer_root: Path,
    output: Path,
) -> dict[str, Any]:
    source_result = verify_sources(contract_path, source_root, quantizer_root)
    if output.exists() or output.is_symlink():
        raise ConversionToolError("tool_bundle_output_exists")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    contract, contract_raw = _load_contract(contract_path)

    _copy_regular(Path(__file__), output / "bin" / "conversion_tooling.py")
    _copy_regular(
        Path(__file__).with_name(MERGE_NAME), output / "bin" / MERGE_NAME
    )
    _copy_regular(contract_path, output / "contracts" / CONTRACT_NAME)
    _copy_regular(
        contract_path.parent / DEPENDENCIES_NAME,
        output / "contracts" / DEPENDENCIES_NAME,
    )
    source_output = output / "tools" / "llama.cpp"
    for relative_name in contract["llama_cpp_source"]["top_level_files"]:
        relative = _relative_path(relative_name)
        _copy_regular(source_root / relative, source_output / relative)
    for relative_name in contract["llama_cpp_source"]["trees"]:
        relative = _relative_path(relative_name)
        _copy_tree(source_root / relative, source_output / relative)

    quantizer_output = output / "tools" / "llama-b10333-cpu"
    for relative_name in contract["quantizer_runtime"]["regular_files"]:
        relative = _relative_path(relative_name)
        _copy_regular(quantizer_root / relative, quantizer_output / relative)
    for relative_name, target in contract["quantizer_runtime"]["symlinks"].items():
        relative = _relative_path(relative_name)
        destination = quantizer_output / relative
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.symlink(target, destination)

    manifest = {
        "schema_version": 1,
        "version": MANIFEST_VERSION,
        "contract_sha256": _sha256(contract_raw),
        "files": _package_entries(output),
    }
    (output / MANIFEST_NAME).write_bytes(_pretty_bytes(manifest))
    result = verify_package(output)
    result["source"] = source_result
    return result


def _print_result(value: Mapping[str, Any]) -> None:
    print(json.dumps(dict(value), ensure_ascii=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conversion_tooling.py")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--contract", type=Path, required=True)
    prepare.add_argument("--source-root", type=Path, required=True)
    prepare.add_argument("--quantizer-root", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--bundle", type=Path, required=True)
    write_operations_parser = commands.add_parser("write-operations")
    write_operations_parser.add_argument("--contract", type=Path, required=True)
    write_operations_parser.add_argument("--tool-bundle", type=Path, required=True)
    write_operations_parser.add_argument("--output", type=Path, required=True)
    write_operations_parser.add_argument(
        "--training-receipt", type=Path, required=True
    )
    write_operations_parser.add_argument(
        "--route", choices=("adapter_on_off", "paired_gguf"), required=True
    )
    write_operations_parser.add_argument("--base-snapshot", type=Path, required=True)
    write_operations_parser.add_argument("--formal-output", type=Path, required=True)
    write_operations_parser.add_argument(
        "--conversion-python", type=Path, required=True
    )
    write_operations_parser.add_argument(
        "--training-python", type=Path, required=True
    )
    verify_output_parser = commands.add_parser("verify-output")
    verify_output_parser.add_argument("--contract", type=Path, required=True)
    verify_output_parser.add_argument("--tool-bundle", type=Path, required=True)
    verify_output_parser.add_argument("--output", type=Path, required=True)
    verify_output_parser.add_argument(
        "--training-receipt", type=Path, required=True
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_package(
                args.contract, args.source_root, args.quantizer_root, args.output
            )
        elif args.command == "verify":
            result = verify_package(args.bundle)
        elif args.command == "write-operations":
            result = write_operations(
                args.contract,
                args.tool_bundle,
                args.output,
                args.training_receipt,
                route=args.route,
                base_snapshot=args.base_snapshot,
                formal_output=args.formal_output,
                conversion_python=args.conversion_python,
                training_python=args.training_python,
            )
        else:
            result = verify_output(
                args.contract,
                args.output,
                args.training_receipt,
                args.tool_bundle,
            )
        _print_result(result)
        return 0
    except (ConversionToolError, OSError) as exc:
        _print_result({"status": "not_ready", "blocker": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
