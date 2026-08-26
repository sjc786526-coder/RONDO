"""Prepare and verify the exact, portable Plan 060 upload bundle."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import os
from pathlib import Path
import shutil
import stat
import tarfile
import uuid
from typing import Any

from ..training_data import validate_train_only_smoke_bundle, verify_freeze_manifest
from ..training_data.input_identity import load_plan054_training_input
from .contract import (
    BUNDLE_SCHEMA,
    FullModelTrainingError,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    PORTABLE_INPUT_SCHEMA,
    SMOKE_BUNDLE_SHA256,
    SOURCE_FILES,
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


PLAN059_MANIFEST_SHA256 = (
    "bad48a77b27aaa40c4a47226cf3aa546cddd7028888bc7c1144a34e308b03127"
)
PLAN054_FREEZE_SHA256 = (
    "2a8081d3700f4209f5ac3cd7dabb7f6d31d0cb0b0ea0e9e8c639c8f10dbebfeb"
)
MODEL_LOCK_RELATIVE = (
    "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json"
)
TEMPLATE_FILES = (
    "eval/templates/publication-critic/input-contract-v2.md",
    "eval/templates/publication-critic/qualification-rubric-v1.md",
    "eval/templates/publication-critic/product-packet-limits-v1.json",
    "eval/templates/publication-critic/render-contract-v3.json",
)
DATA_RELATIVE = "data/train-only-smoke-bundle.json"
PORTABLE_RELATIVE = "contracts/portable-input-v1.json"
MANIFEST_RELATIVE = "bundle-manifest.json"
FORBIDDEN_PATH_TERMS = (
    "validation",
    "unseen-test",
    "unseen_test",
    ".env.local",
    "rondo.local.toml",
    "model.safetensors",
)
FORBIDDEN_ASSET_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pth", ".bin")


def prepare_bundle(repo_root: Path, output_root: Path) -> dict[str, Any]:
    """Build a portable code/config + train-only bundle after full local gates."""

    root = safe_directory(Path(repo_root))
    destination = Path(output_root)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("bundle_output_already_exists")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    staging.mkdir(mode=0o700)
    try:
        portable, smoke_raw = _local_readiness(root)
        sources = _portable_sources(root)
        sources[DATA_RELATIVE] = smoke_raw
        sources[PORTABLE_RELATIVE] = pretty_json_bytes(portable)
        files: dict[str, dict[str, Any]] = {}
        for relative, raw in sorted(sources.items()):
            pure = safe_relative(relative)
            target = staging.joinpath(*pure.parts)
            write_exclusive(target, raw)
            files[relative] = {
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
                "role": _role(relative),
                "contains_train_body": relative == DATA_RELATIVE,
            }
        manifest_core = {
            "schema": BUNDLE_SCHEMA,
            "created_at": utc_now(),
            "source": {
                "plan054_measurement_freeze_sha256": PLAN054_FREEZE_SHA256,
                "plan059_manifest_sha256": PLAN059_MANIFEST_SHA256,
                "train_only_smoke_bundle_sha256": SMOKE_BUNDLE_SHA256,
                "dataset_revision": "v7",
            },
            "boundaries": {
                "train_body_files": 1,
                "validation_files": 0,
                "unseen_test_files": 0,
                "model_weight_files": 0,
                "secret_files": 0,
            },
            "files": files,
        }
        manifest = {
            **manifest_core,
            "content_sha256": sha256_bytes(canonical_json_bytes(manifest_core)),
        }
        write_exclusive(staging / MANIFEST_RELATIVE, pretty_json_bytes(manifest))
        result = verify_bundle(staging)
        os.replace(staging, destination)
        return result
    except BaseException:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)
        raise


def verify_bundle(bundle_root: Path) -> dict[str, Any]:
    root = safe_directory(Path(bundle_root))
    manifest_path = root / MANIFEST_RELATIVE
    manifest = read_json(manifest_path)
    if isinstance(manifest, Mapping) and manifest.get("schema") == (
        "rondo-publication-critic-plan066-bundle-v1"
    ):
        from .plan066_bundle import verify_plan066_bundle

        return verify_plan066_bundle(root)
    expected_keys = {
        "schema",
        "created_at",
        "source",
        "boundaries",
        "files",
        "content_sha256",
    }
    if (
        not isinstance(manifest, Mapping)
        or set(manifest) != expected_keys
        or manifest.get("schema") != BUNDLE_SCHEMA
    ):
        raise FullModelTrainingError("bundle_manifest_invalid")
    core = {key: value for key, value in manifest.items() if key != "content_sha256"}
    if sha256_bytes(canonical_json_bytes(core)) != manifest["content_sha256"]:
        raise FullModelTrainingError("bundle_manifest_content_mismatch")
    source = manifest.get("source")
    if source != {
        "plan054_measurement_freeze_sha256": PLAN054_FREEZE_SHA256,
        "plan059_manifest_sha256": PLAN059_MANIFEST_SHA256,
        "train_only_smoke_bundle_sha256": SMOKE_BUNDLE_SHA256,
        "dataset_revision": "v7",
    }:
        raise FullModelTrainingError("bundle_source_identity_invalid")
    if manifest.get("boundaries") != {
        "train_body_files": 1,
        "validation_files": 0,
        "unseen_test_files": 0,
        "model_weight_files": 0,
        "secret_files": 0,
    }:
        raise FullModelTrainingError("bundle_boundaries_invalid")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or not files:
        raise FullModelTrainingError("bundle_file_manifest_invalid")
    actual: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("bundle_non_regular_entry")
        actual.add(relative)
    expected = set(files) | {MANIFEST_RELATIVE}
    if actual != expected:
        raise FullModelTrainingError("bundle_file_set_mismatch")
    train_bodies = 0
    for relative, metadata in files.items():
        safe_relative(str(relative))
        if _forbidden_bundle_path(str(relative)):
            raise FullModelTrainingError("bundle_forbidden_path")
        if (
            not isinstance(metadata, Mapping)
            or set(metadata) != {"bytes", "sha256", "role", "contains_train_body"}
            or not isinstance(metadata["bytes"], int)
            or isinstance(metadata["bytes"], bool)
            or metadata["bytes"] < 0
            or not isinstance(metadata["sha256"], str)
            or not isinstance(metadata["role"], str)
            or not isinstance(metadata["contains_train_body"], bool)
        ):
            raise FullModelTrainingError("bundle_file_metadata_invalid")
        file_path = root.joinpath(*safe_relative(str(relative)).parts)
        if file_path.stat().st_size != metadata["bytes"]:
            raise FullModelTrainingError("bundle_file_size_mismatch")
        if sha256_file(file_path) != metadata["sha256"]:
            raise FullModelTrainingError("bundle_file_hash_mismatch")
        train_bodies += int(metadata["contains_train_body"])
    if (
        train_bodies != 1
        or files.get(DATA_RELATIVE, {}).get("contains_train_body") is not True
    ):
        raise FullModelTrainingError("bundle_train_body_boundary_invalid")
    if PORTABLE_RELATIVE not in files:
        raise FullModelTrainingError("bundle_portable_contract_missing")
    from .data import load_portable_dataset

    dataset = load_portable_dataset(root)
    return {
        "schema": BUNDLE_SCHEMA,
        "status": "verified",
        "bundle_manifest_sha256": sha256_file(manifest_path),
        "content_sha256": manifest["content_sha256"],
        "file_count": len(files) + 1,
        "dataset_revision": dataset.dataset_revision,
        "binary_count": len(dataset.supervision),
        "pair_count": len(dataset.pairs),
        "stage_pair_counts": {
            stage: len(dataset.stage(stage).pair_ids) for stage in ("C1", "C2", "C3")
        },
    }


def create_deterministic_archive(
    bundle_root: Path, archive_path: Path
) -> dict[str, Any]:
    return create_verified_archive(bundle_root, archive_path, verifier=verify_bundle)


def create_verified_archive(
    bundle_root: Path,
    archive_path: Path,
    *,
    verifier: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    """Create the shared deterministic tar format after a task verifier passes."""

    root = safe_directory(Path(bundle_root))
    bundle = verifier(root)
    destination = Path(archive_path)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("bundle_archive_already_exists")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    try:
        with tarfile.open(temporary, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                if path.is_symlink():
                    raise FullModelTrainingError("bundle_non_regular_entry")
                relative = path.relative_to(root).as_posix()
                info = tarfile.TarInfo(relative)
                info.size = path.stat().st_size
                info.mode = 0o600
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                with path.open("rb") as handle:
                    archive.addfile(info, handle)
        os.replace(temporary, destination)
        destination.chmod(0o600)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {
        **bundle,
        "archive_sha256": sha256_file(destination),
        "archive_bytes": destination.stat().st_size,
    }


def extract_verified_archive(
    archive_path: Path,
    output_root: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    return extract_archive_with_verifier(
        archive_path,
        output_root,
        expected_sha256=expected_sha256,
        verifier=verify_bundle,
    )


def extract_archive_with_verifier(
    archive_path: Path,
    output_root: Path,
    *,
    expected_sha256: str,
    verifier: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    """Safely extract the shared tar format and run a task-specific verifier."""

    source = regular_file(Path(archive_path), maximum_bytes=512 * 1024 * 1024)
    if sha256_file(source) != expected_sha256:
        raise FullModelTrainingError("bundle_archive_hash_mismatch")
    destination = Path(output_root)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("bundle_extract_output_exists")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    staging.mkdir(mode=0o700)
    seen: set[str] = set()
    try:
        with tarfile.open(source, mode="r:") as archive:
            members = archive.getmembers()
            if not members:
                raise FullModelTrainingError("bundle_archive_empty")
            for member in members:
                pure = safe_relative(member.name)
                if member.name in seen:
                    raise FullModelTrainingError("bundle_archive_member_invalid")
                seen.add(member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise FullModelTrainingError("bundle_archive_member_invalid")
                if member.size < 0 or member.size > 64 * 1024 * 1024:
                    raise FullModelTrainingError("bundle_archive_member_too_large")
                handle = archive.extractfile(member)
                if handle is None:
                    raise FullModelTrainingError("bundle_archive_member_invalid")
                raw = handle.read(member.size + 1)
                if len(raw) != member.size:
                    raise FullModelTrainingError("bundle_archive_member_size_mismatch")
                write_exclusive(staging.joinpath(*pure.parts), raw)
        result = verifier(staging)
        os.replace(staging, destination)
        return result
    except (tarfile.TarError, OSError) as exc:
        raise FullModelTrainingError("bundle_archive_invalid") from exc
    finally:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)


def _local_readiness(repo_root: Path) -> tuple[dict[str, Any], bytes]:
    frozen_root = repo_root / "training/publication-critic-v7"
    smoke_path = frozen_root / "train-only-smoke-bundle.json"
    manifest_path = frozen_root / "manifest.json"
    if sha256_file(smoke_path, maximum_bytes=32 * 1024 * 1024) != SMOKE_BUNDLE_SHA256:
        raise FullModelTrainingError("local_smoke_bundle_hash_mismatch")
    if sha256_file(manifest_path) != PLAN059_MANIFEST_SHA256:
        raise FullModelTrainingError("local_plan059_manifest_hash_mismatch")
    verified_input = load_plan054_training_input(repo_root)
    smoke = read_json(smoke_path, maximum_bytes=32 * 1024 * 1024)
    try:
        validate_train_only_smoke_bundle(smoke, repo_root=repo_root)
    except Exception as exc:
        raise FullModelTrainingError("local_public_smoke_verifier_failed") from exc
    manifest = read_json(manifest_path)
    try:
        verify_freeze_manifest(
            frozen_root,
            manifest,
            expected_input_identity=verified_input.input_identity,
        )
    except Exception as exc:
        raise FullModelTrainingError("local_plan059_freeze_verifier_failed") from exc
    source_hashes = smoke.get("source_hashes")
    if not isinstance(source_hashes, Mapping) or set(source_hashes) != set(
        SOURCE_FILES
    ):
        raise FullModelTrainingError("local_source_hashes_invalid")
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, Mapping):
        raise FullModelTrainingError("local_manifest_files_invalid")
    for relative in SOURCE_FILES:
        actual = sha256_file(frozen_root / relative)
        entry = manifest_files.get(relative)
        if (
            source_hashes.get(relative) != actual
            or not isinstance(entry, Mapping)
            or entry.get("sha256") != actual
        ):
            raise FullModelTrainingError("local_smoke_source_mismatch")
    bundle_entry = manifest_files.get("train-only-smoke-bundle.json")
    if (
        not isinstance(bundle_entry, Mapping)
        or bundle_entry.get("sha256") != SMOKE_BUNDLE_SHA256
    ):
        raise FullModelTrainingError("local_smoke_manifest_entry_mismatch")
    freeze_path = (
        repo_root / "eval/manifests/publication-critic/measurement-freeze-v4.json"
    )
    if sha256_file(freeze_path) != PLAN054_FREEZE_SHA256:
        raise FullModelTrainingError("local_plan054_freeze_hash_mismatch")
    model_lock_path = repo_root / MODEL_LOCK_RELATIVE
    model_lock = read_json(model_lock_path)
    model = model_lock.get("model", {})
    configuration = model_lock.get("configuration", {})
    weights = model_lock.get("weights", {})
    tokenizer_hashes = dict(verified_input.tokenizer_file_sha256)
    if (
        model.get("repository") != MODEL_REPOSITORY
        or model.get("revision") != MODEL_REVISION
        or configuration.get("architectures") != ["Qwen3ForSequenceClassification"]
        or configuration.get("num_labels") != 1
        or weights.get("parameter_count") != 1_720_577_024
        or weights.get("storage_dtype") != "BF16"
    ):
        raise FullModelTrainingError("local_model_lock_invalid")
    portable = {
        "schema": PORTABLE_INPUT_SCHEMA,
        "dataset_revision": "v7",
        "smoke_bundle_sha256": SMOKE_BUNDLE_SHA256,
        "source_sha256": dict(sorted(source_hashes.items())),
        "input_identity": dict(verified_input.input_identity),
        "qualification_rubric_sha256": sha256_file(
            repo_root / "eval/templates/publication-critic/qualification-rubric-v1.md"
        ),
        "render_contract_sha256": sha256_file(
            repo_root / "eval/templates/publication-critic/render-contract-v3.json"
        ),
        "product_packet_limits_sha256": sha256_file(
            repo_root
            / "eval/templates/publication-critic/product-packet-limits-v1.json"
        ),
        "model_lock_sha256": sha256_file(model_lock_path),
        "model": {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "class": "Qwen3ForSequenceClassification",
            "num_labels": 1,
            "parameter_count": 1_720_577_024,
            "weight_file": "model.safetensors",
            "weight_sha256": model_lock["files"]["model.safetensors"],
            "config_file": "config.json",
            "config_sha256": model_lock["files"]["config.json"],
            "pad_token_id": 151654,
            "max_position_embeddings": 40960,
        },
        "tokenizer_file_sha256": tokenizer_hashes,
    }
    return portable, regular_file(smoke_path).read_bytes()


def _portable_sources(repo_root: Path) -> dict[str, bytes]:
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
    training_contract_root = repo_root / "training/publication-critic-plan060"
    if not training_contract_root.is_dir() or training_contract_root.is_symlink():
        raise FullModelTrainingError("plan060_training_contracts_missing")
    for path in training_contract_root.rglob("*"):
        if path.is_dir() and not path.is_symlink():
            continue
        relative_paths.add(path.relative_to(repo_root).as_posix())
    result: dict[str, bytes] = {}
    for relative in sorted(relative_paths):
        path = regular_file(repo_root / relative, maximum_bytes=16 * 1024 * 1024)
        result[relative] = path.read_bytes()
    return result


def _role(relative: str) -> str:
    if relative == DATA_RELATIVE:
        return "plan059_v7_train_only_smoke"
    if relative == PORTABLE_RELATIVE:
        return "portable_verified_input_identity"
    if relative.startswith("eval/rondo_eval/"):
        return "python_source"
    if relative.startswith("eval/templates/") or relative == MODEL_LOCK_RELATIVE:
        return "frozen_input_config"
    if relative.startswith("training/publication-critic-plan060/"):
        return "plan060_training_contract"
    raise FullModelTrainingError("bundle_file_role_unknown")


def _forbidden_bundle_path(relative: str) -> bool:
    folded = relative.casefold()
    name = safe_relative(relative).name.casefold()
    return any(term in folded for term in FORBIDDEN_PATH_TERMS) or name.endswith(
        FORBIDDEN_ASSET_SUFFIXES
    )
