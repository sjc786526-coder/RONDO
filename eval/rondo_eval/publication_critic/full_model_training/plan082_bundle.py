"""Plan 082 source/data bundles built without reading the mixed v8 tree."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
from typing import Any
import uuid

from ..base_quality.source import verify_source_archive_tree
from .bundle import (
    MANIFEST_RELATIVE,
    create_verified_archive,
    extract_archive_with_verifier,
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
from .plan066_bundle import verify_plan066_bundle
from .plan066_data import (
    PLAN066_DATA_RELATIVE,
    PLAN066_PORTABLE_RELATIVE,
    load_plan066_datasets,
)


DATA_BUNDLE_SCHEMA = "rondo-publication-critic-plan082-data-bundle-v1"
SOURCE_BUNDLE_SCHEMA = "rondo-publication-critic-plan082-source-bundle-v1"
CANONICAL_PLAN066_MANIFEST_SHA256 = (
    "2970c693fa32d1118d3b8e949a04231970bf96dfc27f7c7d14a22f98a4ed2252"
)
CANONICAL_PLAN066_CONTENT_SHA256 = (
    "0c64317e3f4098172f25ad32de5fee0b3f62f198592a94bf7d4234828a28614f"
)
PLAN066_EXPORT_SHA256 = (
    "5b887f60ec803c29b7711b98614863876df4e60087e942b84f6bdc202af851cf"
)
PLAN066_PORTABLE_SHA256 = (
    "399b43a46598148d3ea16f3738b0281ae6bfc57e2c39e5975b370debd16bef73"
)
RUBRIC_RELATIVE = "eval/templates/publication-critic/qualification-rubric-v1.md"
RUBRIC_SHA256 = "cc15207b3c6e2482e56710f735d01893f8c8c020df35a18918e1a0a1be7f02e4"
MODEL_LOCK_SHA256 = "419facd8f97412b6e45e5eac35d638ed3d88a943e7c936fd6700911d0f0b441b"
DATA_MEMBERS = {
    PLAN066_DATA_RELATIVE: PLAN066_EXPORT_SHA256,
    PLAN066_PORTABLE_RELATIVE: PLAN066_PORTABLE_SHA256,
    RUBRIC_RELATIVE: RUBRIC_SHA256,
}
SOURCE_PATHS = (
    "eval/rondo_eval/__init__.py",
    "eval/rondo_eval/config.py",
    "eval/rondo_eval/contracts.py",
    "eval/rondo_eval/evidence.py",
    "eval/rondo_eval/exit_codes.py",
    "eval/rondo_eval/runtime_bridge.py",
    "eval/rondo_eval/publication_critic",
    "eval/templates/publication-critic/input-contract-v2.md",
    "eval/templates/publication-critic/qualification-rubric-v1.md",
    "eval/templates/publication-critic/product-packet-limits-v1.json",
    "eval/templates/publication-critic/render-contract-v3.json",
    "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json",
    "eval/pyproject.toml",
    "eval/uv.lock",
    "training/publication-critic-plan082",
)


def prepare_data_bundle(
    canonical_plan066_root: Path, output_root: Path
) -> dict[str, Any]:
    source = safe_directory(Path(canonical_plan066_root))
    canonical = verify_plan066_bundle(source)
    if (
        canonical.get("bundle_manifest_sha256") != CANONICAL_PLAN066_MANIFEST_SHA256
        or canonical.get("content_sha256") != CANONICAL_PLAN066_CONTENT_SHA256
        or canonical.get("unseen_test_rows") != 0
    ):
        raise FullModelTrainingError("plan082_canonical_bundle_identity_mismatch")
    destination = Path(output_root)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("plan082_data_bundle_output_exists")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    staging.mkdir(mode=0o700)
    try:
        files: dict[str, dict[str, Any]] = {}
        for relative, expected_sha256 in sorted(DATA_MEMBERS.items()):
            source_path = regular_file(
                source / relative, maximum_bytes=32 * 1024 * 1024
            )
            raw = source_path.read_bytes()
            if sha256_bytes(raw) != expected_sha256:
                raise FullModelTrainingError("plan082_data_member_identity_mismatch")
            write_exclusive(staging.joinpath(*safe_relative(relative).parts), raw)
            files[relative] = {
                "bytes": len(raw),
                "sha256": expected_sha256,
                "role": (
                    "train_validation_body"
                    if relative == PLAN066_DATA_RELATIVE
                    else "typed_input_contract"
                    if relative == PLAN066_PORTABLE_RELATIVE
                    else "qualification_rubric"
                ),
            }
        core = {
            "schema": DATA_BUNDLE_SCHEMA,
            "created_at": utc_now(),
            "canonical_plan066": {
                "bundle_manifest_sha256": CANONICAL_PLAN066_MANIFEST_SHA256,
                "content_sha256": CANONICAL_PLAN066_CONTENT_SHA256,
                "data_export_sha256": PLAN066_EXPORT_SHA256,
            },
            "model_lock_sha256": MODEL_LOCK_SHA256,
            "boundaries": {
                "train_candidates": 128,
                "train_pairs": 58,
                "validation_candidates": 55,
                "validation_pairs": 26,
                "commissioning_candidates": 6,
                "commissioning_pairs": 2,
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
        result = verify_data_bundle(staging)
        os.replace(staging, destination)
        return result
    finally:
        if staging.exists() and not staging.is_symlink():
            shutil.rmtree(staging)


def verify_data_bundle(bundle_root: Path) -> dict[str, Any]:
    root = safe_directory(Path(bundle_root))
    manifest_path = root / MANIFEST_RELATIVE
    manifest = read_json(manifest_path)
    if not isinstance(manifest, Mapping) or set(manifest) != {
        "schema",
        "created_at",
        "canonical_plan066",
        "model_lock_sha256",
        "boundaries",
        "files",
        "content_sha256",
    }:
        raise FullModelTrainingError("plan082_data_manifest_invalid")
    core = {key: value for key, value in manifest.items() if key != "content_sha256"}
    if (
        manifest.get("schema") != DATA_BUNDLE_SCHEMA
        or manifest.get("content_sha256") != sha256_bytes(canonical_json_bytes(core))
        or manifest.get("canonical_plan066")
        != {
            "bundle_manifest_sha256": CANONICAL_PLAN066_MANIFEST_SHA256,
            "content_sha256": CANONICAL_PLAN066_CONTENT_SHA256,
            "data_export_sha256": PLAN066_EXPORT_SHA256,
        }
        or manifest.get("model_lock_sha256") != MODEL_LOCK_SHA256
        or manifest.get("boundaries")
        != {
            "train_candidates": 128,
            "train_pairs": 58,
            "validation_candidates": 55,
            "validation_pairs": 26,
            "commissioning_candidates": 6,
            "commissioning_pairs": 2,
            "unseen_test_body_files": 0,
            "unseen_test_rows": 0,
            "model_weight_files": 0,
            "secret_files": 0,
        }
    ):
        raise FullModelTrainingError("plan082_data_manifest_identity_invalid")
    files = manifest.get("files")
    if not isinstance(files, Mapping) or set(files) != set(DATA_MEMBERS):
        raise FullModelTrainingError("plan082_data_members_invalid")
    actual: set[str] = set()
    for path in root.rglob("*"):
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan082_data_non_regular_entry")
        actual.add(path.relative_to(root).as_posix())
    if actual != set(DATA_MEMBERS) | {MANIFEST_RELATIVE}:
        raise FullModelTrainingError("plan082_data_file_set_mismatch")
    for relative, expected_sha256 in DATA_MEMBERS.items():
        metadata = files.get(relative)
        path = root.joinpath(*safe_relative(relative).parts)
        if (
            not isinstance(metadata, Mapping)
            or set(metadata) != {"bytes", "sha256", "role"}
            or metadata.get("sha256") != expected_sha256
            or type(metadata.get("bytes")) is not int
            or metadata["bytes"] != path.stat().st_size
            or sha256_file(path) != expected_sha256
        ):
            raise FullModelTrainingError("plan082_data_member_identity_mismatch")
    datasets = load_plan066_datasets(root)
    if (
        datasets.export_sha256 != PLAN066_EXPORT_SHA256
        or set(datasets.train.supervision) & set(datasets.validation.supervision)
        or len(datasets.train.supervision) != 128
        or len(datasets.train.pairs) != 58
        or len(datasets.validation.supervision) != 55
        or len(datasets.validation.pairs) != 26
        or len(datasets.commissioning.supervision) != 6
        or len(datasets.commissioning.pairs) != 2
    ):
        raise FullModelTrainingError("plan082_data_typed_boundary_invalid")
    return {
        "schema": DATA_BUNDLE_SCHEMA,
        "status": "verified",
        "bundle_manifest_sha256": sha256_file(manifest_path),
        "content_sha256": manifest["content_sha256"],
        "data_export_sha256": datasets.export_sha256,
        "file_count": len(actual),
        "train_candidate_count": len(datasets.train.supervision),
        "train_pair_count": len(datasets.train.pairs),
        "validation_candidate_count": len(datasets.validation.supervision),
        "validation_pair_count": len(datasets.validation.pairs),
        "commissioning_candidate_count": len(datasets.commissioning.supervision),
        "commissioning_pair_count": len(datasets.commissioning.pairs),
        "unseen_test_rows": 0,
    }


def create_data_archive(bundle_root: Path, archive_path: Path) -> dict[str, Any]:
    return create_verified_archive(
        bundle_root,
        archive_path,
        verifier=verify_data_bundle,
    )


def extract_data_archive(
    archive_path: Path,
    output_root: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    return extract_archive_with_verifier(
        archive_path,
        output_root,
        expected_sha256=expected_sha256,
        verifier=verify_data_bundle,
    )


def create_source_archive(
    repo_root: Path,
    output_path: Path,
    *,
    source_commit: str,
) -> dict[str, Any]:
    root = safe_directory(Path(repo_root))
    destination = Path(output_path)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("plan082_source_archive_exists")
    commit = _git(root, "rev-parse", "HEAD")
    if source_commit != commit or len(commit) != 40:
        raise FullModelTrainingError("plan082_source_commit_mismatch")
    dirty = _git(
        root, "status", "--porcelain", "--untracked-files=no", "--", *SOURCE_PATHS
    )
    if dirty:
        raise FullModelTrainingError("plan082_source_tree_dirty")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "archive",
                "--format=tar",
                f"--output={destination}",
                commit,
                "--",
                *SOURCE_PATHS,
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        destination.chmod(0o600)
        return verify_source_archive(
            destination,
            root,
            exact_tree=False,
            expected_commit=commit,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        destination.unlink(missing_ok=True)
        raise FullModelTrainingError("plan082_source_archive_create_failed") from exc
    except BaseException:
        destination.unlink(missing_ok=True)
        raise


def extract_source_archive(
    archive_path: Path,
    output_root: Path,
    *,
    expected_sha256: str,
    expected_commit: str,
) -> dict[str, Any]:
    return extract_archive_with_verifier(
        archive_path,
        output_root,
        expected_sha256=expected_sha256,
        verifier=lambda root: verify_source_archive(
            archive_path,
            root,
            exact_tree=True,
            expected_commit=expected_commit,
        ),
    )


def verify_source_archive(
    archive_path: Path,
    source_root: Path,
    *,
    exact_tree: bool,
    expected_commit: str,
) -> dict[str, Any]:
    if (
        not isinstance(expected_commit, str)
        or len(expected_commit) != 40
        or any(character not in "0123456789abcdef" for character in expected_commit)
    ):
        raise FullModelTrainingError("plan082_source_commit_invalid")
    members: set[str] = set()
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            for item in archive:
                if item.isdir():
                    continue
                relative = _safe_tar_member(item.name)
                if (
                    not item.isfile()
                    or relative in members
                    or not _allowed_source_member(relative)
                ):
                    raise FullModelTrainingError("plan082_source_member_invalid")
                members.add(relative)
    except FullModelTrainingError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise FullModelTrainingError("plan082_source_archive_invalid") from exc
    required = {
        "eval/rondo_eval/publication_critic/full_model_training/plan082_bundle.py",
        "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json",
        "training/publication-critic-plan082/README.md",
    }
    if not required <= members:
        raise FullModelTrainingError("plan082_source_members_missing")
    try:
        receipt = verify_source_archive_tree(
            archive_path,
            source_root,
            exact_tree=exact_tree,
        )
    except Exception as exc:
        raise FullModelTrainingError("plan082_source_tree_identity_mismatch") from exc
    return {
        "schema": SOURCE_BUNDLE_SCHEMA,
        "commit": expected_commit,
        "archive_bytes": Path(archive_path).stat().st_size,
        "archive_sha256": receipt["source_archive_sha256"],
        "source_content_sha256": receipt["source_content_sha256"],
        "file_count": receipt["file_count"],
        "directory_count": receipt["directory_count"],
    }


def _allowed_source_member(relative: str) -> bool:
    return any(
        relative == allowed or relative.startswith(allowed.rstrip("/") + "/")
        for allowed in SOURCE_PATHS
    )


def _safe_tar_member(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise FullModelTrainingError("plan082_source_member_invalid")
    return path.as_posix()


def _git(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FullModelTrainingError("plan082_git_identity_unavailable") from exc
    return completed.stdout.strip()
