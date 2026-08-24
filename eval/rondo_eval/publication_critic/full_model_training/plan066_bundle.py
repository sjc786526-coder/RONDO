"""Prepare and verify the bounded Plan 066 train/validation upload bundle."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import shutil
import stat
import subprocess
import uuid
from typing import Any

from .bundle import (
    MANIFEST_RELATIVE,
    MODEL_LOCK_RELATIVE,
    TEMPLATE_FILES,
    _local_readiness,
)
from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    regular_file,
    safe_directory,
    safe_relative,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_exclusive,
)
from .plan066_data import (
    PLAN066_DATA_RELATIVE,
    PLAN066_PORTABLE_RELATIVE,
    V8_CONTENT_SHA256,
    V8_MANIFEST_SHA256,
    V8_SOURCE_SHA256,
    build_plan066_export,
    load_plan066_datasets,
)


PLAN066_BUNDLE_SCHEMA = "rondo-publication-critic-plan066-bundle-v1"
PLAN066_MODEL_CONTRACT_RELATIVE = (
    "training/publication-critic-plan066/model-contract-v1.json"
)
PLAN066_RECIPE_RELATIVE = "training/publication-critic-plan066/recipe-v1.json"


def prepare_plan066_bundle(repo_root: Path, output_root: Path) -> dict[str, Any]:
    root = safe_directory(Path(repo_root))
    destination = Path(output_root)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("plan066_bundle_output_already_exists")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    staging.mkdir(mode=0o700)
    try:
        legacy_portable, _ = _local_readiness(root)
        data = build_plan066_export(root)
        portable = _plan066_portable(legacy_portable)
        sources = _plan066_sources(root)
        sources[PLAN066_DATA_RELATIVE] = pretty_json_bytes(data)
        sources[PLAN066_PORTABLE_RELATIVE] = pretty_json_bytes(portable)
        files: dict[str, dict[str, Any]] = {}
        for relative, raw in sorted(sources.items()):
            target = staging.joinpath(*safe_relative(relative).parts)
            write_exclusive(target, raw)
            files[relative] = {
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
                "role": _role(relative),
                "contains_train_body": relative == PLAN066_DATA_RELATIVE,
                "contains_validation_body": relative == PLAN066_DATA_RELATIVE,
            }
        core = {
            "schema": PLAN066_BUNDLE_SCHEMA,
            "created_at": utc_now(),
            "source": {
                "dataset_revision": "v8",
                "v8_manifest_file_sha256": V8_MANIFEST_SHA256,
                "v8_manifest_content_sha256": V8_CONTENT_SHA256,
                "v8_source_sha256": dict(sorted(V8_SOURCE_SHA256.items())),
                "source_commit": _source_commit(root),
            },
            "boundaries": {
                "data_body_files": 1,
                "train_candidates": 128,
                "train_pairs": 58,
                "validation_candidates": 55,
                "validation_pairs": 26,
                "unseen_test_body_files": 0,
                "unseen_test_rows": 0,
                "model_weight_files": 0,
                "secret_files": 0,
            },
            "files": files,
        }
        manifest = {
            **core,
            "content_sha256": sha256_bytes(canonical_json_bytes(core)),
        }
        write_exclusive(staging / MANIFEST_RELATIVE, pretty_json_bytes(manifest))
        result = verify_plan066_bundle(staging)
        os.replace(staging, destination)
        return result
    except BaseException:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def verify_plan066_bundle(bundle_root: Path) -> dict[str, Any]:
    root = safe_directory(Path(bundle_root))
    manifest_path = root / MANIFEST_RELATIVE
    manifest = read_json(manifest_path)
    expected = {"schema", "created_at", "source", "boundaries", "files", "content_sha256"}
    if (
        not isinstance(manifest, Mapping)
        or set(manifest) != expected
        or manifest.get("schema") != PLAN066_BUNDLE_SCHEMA
    ):
        raise FullModelTrainingError("plan066_bundle_manifest_invalid")
    core = {key: value for key, value in manifest.items() if key != "content_sha256"}
    if sha256_bytes(canonical_json_bytes(core)) != manifest.get("content_sha256"):
        raise FullModelTrainingError("plan066_bundle_manifest_content_mismatch")
    source = manifest.get("source")
    if (
        not isinstance(source, Mapping)
        or set(source)
        != {
            "dataset_revision",
            "v8_manifest_file_sha256",
            "v8_manifest_content_sha256",
            "v8_source_sha256",
            "source_commit",
        }
        or source.get("dataset_revision") != "v8"
        or source.get("v8_manifest_file_sha256") != V8_MANIFEST_SHA256
        or source.get("v8_manifest_content_sha256") != V8_CONTENT_SHA256
        or source.get("v8_source_sha256") != dict(sorted(V8_SOURCE_SHA256.items()))
        or not isinstance(source.get("source_commit"), str)
        or len(source["source_commit"]) != 40
        or any(character not in "0123456789abcdef" for character in source["source_commit"])
    ):
        raise FullModelTrainingError("plan066_bundle_source_invalid")
    if manifest.get("boundaries") != {
        "data_body_files": 1,
        "train_candidates": 128,
        "train_pairs": 58,
        "validation_candidates": 55,
        "validation_pairs": 26,
        "unseen_test_body_files": 0,
        "unseen_test_rows": 0,
        "model_weight_files": 0,
        "secret_files": 0,
    }:
        raise FullModelTrainingError("plan066_bundle_boundaries_invalid")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or not files:
        raise FullModelTrainingError("plan066_bundle_files_invalid")
    actual: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan066_bundle_non_regular_entry")
        actual.add(relative)
    if actual != set(files) | {MANIFEST_RELATIVE}:
        raise FullModelTrainingError("plan066_bundle_file_set_mismatch")
    train_bodies = 0
    validation_bodies = 0
    for relative, metadata in files.items():
        safe_relative(str(relative))
        if _forbidden_path(str(relative)):
            raise FullModelTrainingError("plan066_bundle_forbidden_path")
        if (
            not isinstance(metadata, Mapping)
            or set(metadata)
            != {"bytes", "sha256", "role", "contains_train_body", "contains_validation_body"}
            or not isinstance(metadata["bytes"], int)
            or isinstance(metadata["bytes"], bool)
            or metadata["bytes"] < 0
            or not isinstance(metadata["sha256"], str)
            or not isinstance(metadata["role"], str)
            or not isinstance(metadata["contains_train_body"], bool)
            or not isinstance(metadata["contains_validation_body"], bool)
        ):
            raise FullModelTrainingError("plan066_bundle_file_metadata_invalid")
        path = root.joinpath(*safe_relative(str(relative)).parts)
        if path.stat().st_size != metadata["bytes"] or sha256_file(path) != metadata["sha256"]:
            raise FullModelTrainingError("plan066_bundle_file_identity_mismatch")
        train_bodies += int(metadata["contains_train_body"])
        validation_bodies += int(metadata["contains_validation_body"])
    if (
        train_bodies != 1
        or validation_bodies != 1
        or files.get(PLAN066_DATA_RELATIVE, {}).get("contains_train_body") is not True
        or files.get(PLAN066_DATA_RELATIVE, {}).get("contains_validation_body") is not True
        or PLAN066_PORTABLE_RELATIVE not in files
        or PLAN066_MODEL_CONTRACT_RELATIVE not in files
        or PLAN066_RECIPE_RELATIVE not in files
    ):
        raise FullModelTrainingError("plan066_bundle_body_boundary_invalid")
    datasets = load_plan066_datasets(root)
    return {
        "schema": PLAN066_BUNDLE_SCHEMA,
        "status": "verified",
        "bundle_manifest_sha256": sha256_file(manifest_path),
        "content_sha256": manifest["content_sha256"],
        "source_commit": source["source_commit"],
        "file_count": len(files) + 1,
        "dataset_revision": "v8",
        "train_candidate_count": len(datasets.train.supervision),
        "train_pair_count": len(datasets.train.pairs),
        "validation_candidate_count": len(datasets.validation.supervision),
        "validation_pair_count": len(datasets.validation.pairs),
        "commissioning_candidate_count": len(datasets.commissioning.supervision),
        "commissioning_pair_count": len(datasets.commissioning.pairs),
        "unseen_test_rows": 0,
    }


def _plan066_portable(legacy: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": "rondo-publication-critic-plan066-input-v1",
        "dataset_revision": "v8",
        "v8_manifest_file_sha256": V8_MANIFEST_SHA256,
        "v8_manifest_content_sha256": V8_CONTENT_SHA256,
        "input_identity": legacy["input_identity"],
        "qualification_rubric_sha256": legacy["qualification_rubric_sha256"],
        "render_contract_sha256": legacy["render_contract_sha256"],
        "product_packet_limits_sha256": legacy["product_packet_limits_sha256"],
        "model_lock_sha256": legacy["model_lock_sha256"],
        "model": legacy["model"],
        "tokenizer_file_sha256": legacy["tokenizer_file_sha256"],
        "holdout_policy": {
            "validation_gradient_access": False,
            "unseen_test_exported": False,
        },
    }


def _plan066_sources(repo_root: Path) -> dict[str, bytes]:
    relative_paths: set[str] = {
        "eval/rondo_eval/__init__.py",
        "eval/rondo_eval/budget_policy.py",
        "eval/rondo_eval/contracts.py",
        "eval/rondo_eval/evidence.py",
        "eval/rondo_eval/exit_codes.py",
        "eval/rondo_eval/runtime_bridge.py",
        MODEL_LOCK_RELATIVE,
        *TEMPLATE_FILES,
    }
    publication_root = repo_root / "eval/rondo_eval/publication_critic"
    for path in publication_root.rglob("*.py"):
        if "__pycache__" not in path.parts:
            relative_paths.add(path.relative_to(repo_root).as_posix())
    contract_root = repo_root / "training/publication-critic-plan066"
    if not contract_root.is_dir() or contract_root.is_symlink():
        raise FullModelTrainingError("plan066_training_contracts_missing")
    for path in contract_root.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            continue
        relative_paths.add(path.relative_to(repo_root).as_posix())
    result: dict[str, bytes] = {}
    for relative in sorted(relative_paths):
        result[relative] = regular_file(
            repo_root / relative, maximum_bytes=16 * 1024 * 1024
        ).read_bytes()
    return result


def _role(relative: str) -> str:
    if relative == PLAN066_DATA_RELATIVE:
        return "plan064_v8_train_and_validation"
    if relative == PLAN066_PORTABLE_RELATIVE:
        return "plan066_verified_input_identity"
    if relative.startswith("eval/rondo_eval/"):
        return "python_source"
    if relative.startswith("eval/templates/") or relative == MODEL_LOCK_RELATIVE:
        return "frozen_input_config"
    if relative.startswith("training/publication-critic-plan066/"):
        return "plan066_training_contract"
    raise FullModelTrainingError("plan066_bundle_file_role_unknown")


def _forbidden_path(relative: str) -> bool:
    folded = relative.casefold()
    name = safe_relative(relative).name.casefold()
    forbidden_terms = ("unseen-test", "unseen_test", ".env.local", "rondo.local.toml")
    forbidden_suffixes = (".safetensors", ".ckpt", ".pt", ".pth", ".bin")
    return any(term in folded for term in forbidden_terms) or name.endswith(forbidden_suffixes)


def _source_commit(repo_root: Path) -> str:
    source_paths = (
        "eval/rondo_eval",
        "eval/model-locks/publication-critic",
        "eval/templates/publication-critic",
        "training/publication-critic-plan066",
    )
    try:
        status = subprocess.run(
            [
                "git", "status", "--porcelain", "--untracked-files=all", "--",
                *source_paths,
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FullModelTrainingError("plan066_source_commit_unavailable") from exc
    if status.stdout:
        raise FullModelTrainingError("plan066_source_tree_dirty")
    commit = completed.stdout.strip()
    if (
        len(commit) != 40
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise FullModelTrainingError("plan066_source_commit_invalid")
    return commit
