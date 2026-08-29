"""Commit-bound source and physically development-only v10 archives for Plan 099."""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from ..base_quality.source import verify_source_archive_tree
from .bundle import extract_archive_with_verifier
from .contract import FullModelTrainingError, safe_directory, sha256_file
from .plan099_contract import (
    V10_MANIFEST_SHA256,
    V10_TRAIN_CANDIDATES_SHA256,
    V10_TRAIN_PAIRS_SHA256,
    V10_VALIDATION_CANDIDATES_SHA256,
    V10_VALIDATION_PAIRS_SHA256,
    freeze_sha256,
    load_freeze,
)

SOURCE_BUNDLE_SCHEMA = "rondo-publication-critic-plan099-source-bundle-v1"
DATA_BUNDLE_SCHEMA = "rondo-publication-critic-plan099-data-bundle-v1"
SOURCE_PATHS = (
    "doc/rondo-multi-publication-critic-task-contract-v2.md",
    "doc/rondo-multi-publication-critic-decision-contract-v1.md",
    "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json",
    "eval/pyproject.toml",
    "eval/uv.lock",
    "eval/rondo_eval",
    "eval/templates/publication-critic",
    "training/publication-critic-plan087/runpod-terminal.py",
    "training/publication-critic-plan094/runpod-lifecycle-guard.py",
    "training/publication-critic-plan099",
)
DATA_PATHS = (
    "training/publication-critic-v10/DATA_CARD.md",
    "training/publication-critic-v10/design-lock.json",
    "training/publication-critic-v10/generation-config.json",
    "training/publication-critic-v10/manifest.json",
    "training/publication-critic-v10/module-freeze/continuity-context/patch.json",
    "training/publication-critic-v10/module-freeze/continuity-context/review.json",
    "training/publication-critic-v10/module-freeze/hard-boundaries/patch.json",
    "training/publication-critic-v10/module-freeze/hard-boundaries/review.json",
    "training/publication-critic-v10/module-freeze/soft-combinations/patch.json",
    "training/publication-critic-v10/module-freeze/soft-combinations/review.json",
    "training/publication-critic-v10/patch-records.json",
    "training/publication-critic-v10/release-identity.json",
    "training/publication-critic-v10/shortcut-diagnostics.json",
    "training/publication-critic-v10/splits/train/candidates.jsonl",
    "training/publication-critic-v10/splits/train/pairs.jsonl",
    "training/publication-critic-v10/splits/validation/candidates.jsonl",
    "training/publication-critic-v10/splits/validation/pairs.jsonl",
)
REQUIRED_SOURCE_MEMBERS = {
    "eval/rondo_eval/publication_critic/full_model_training/plan099_artifacts.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan099_bundle.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan099_cli.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan099_contract.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan099_data.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan099_model.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan099_objective.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan099_training.py",
    "training/publication-critic-plan099/freeze-lock-v1.json",
    "training/publication-critic-plan099/runbook.md",
    "training/publication-critic-plan099/runpod-bootstrap.sh",
    "training/publication-critic-plan099/runpod-release.py",
    "training/publication-critic-plan099/runpod-worker.sh",
    "training/publication-critic-plan094/runpod-lifecycle-guard.py",
}


def create_source_archive(
    repo_root: Path, output_path: Path, *, source_commit: str
) -> dict[str, Any]:
    root = safe_directory(Path(repo_root))
    _require_clean_commit(root, source_commit, SOURCE_PATHS)
    _git_archive(root, output_path, source_commit, SOURCE_PATHS)
    return verify_source_archive(
        output_path, root, expected_commit=source_commit, exact_tree=False
    )


def create_data_archive(
    repo_root: Path, output_path: Path, *, source_commit: str
) -> dict[str, Any]:
    root = safe_directory(Path(repo_root))
    _require_clean_commit(root, source_commit, DATA_PATHS)
    _git_archive(root, output_path, source_commit, DATA_PATHS)
    return verify_data_archive(
        output_path, root, expected_commit=source_commit, exact_tree=False
    )


def verify_source_archive(
    archive_path: Path,
    source_root: Path,
    *,
    expected_commit: str,
    exact_tree: bool,
) -> dict[str, Any]:
    members = _archive_members(archive_path)
    if not REQUIRED_SOURCE_MEMBERS <= members or any(
        not _allowed(relative, SOURCE_PATHS) for relative in members
    ):
        raise FullModelTrainingError("plan099_source_archive_members_invalid")
    receipt = _verify_tree(archive_path, source_root, exact_tree=exact_tree)
    return {
        "schema": SOURCE_BUNDLE_SCHEMA,
        "commit": _commit(expected_commit),
        "archive_bytes": Path(archive_path).stat().st_size,
        "archive_sha256": sha256_file(archive_path),
        "source_content_sha256": receipt["source_content_sha256"],
        "file_count": receipt["file_count"],
        "directory_count": receipt["directory_count"],
    }


def verify_data_archive(
    archive_path: Path,
    source_root: Path,
    *,
    expected_commit: str,
    exact_tree: bool,
) -> dict[str, Any]:
    root = Path(source_root)
    members = _archive_members(archive_path)
    if members != set(DATA_PATHS):
        raise FullModelTrainingError("plan099_data_archive_members_invalid")
    receipt = _verify_tree(archive_path, root, exact_tree=exact_tree)
    return {
        "schema": DATA_BUNDLE_SCHEMA,
        "commit": _commit(expected_commit),
        "archive_bytes": Path(archive_path).stat().st_size,
        "archive_sha256": sha256_file(archive_path),
        "source_content_sha256": receipt["source_content_sha256"],
        "file_count": receipt["file_count"],
        "directory_count": receipt["directory_count"],
        "development_revision": "publication-critic-v10",
        "manifest_sha256": V10_MANIFEST_SHA256,
        "train_candidates_sha256": V10_TRAIN_CANDIDATES_SHA256,
        "train_pairs_sha256": V10_TRAIN_PAIRS_SHA256,
        "validation_candidates_sha256": V10_VALIDATION_CANDIDATES_SHA256,
        "validation_pairs_sha256": V10_VALIDATION_PAIRS_SHA256,
        "test_body_files": 0,
        "qualification_body_files": 0,
    }


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
            archive_path, root, expected_commit=expected_commit, exact_tree=True
        ),
    )


def extract_data_archive(
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
        verifier=lambda root: verify_data_archive(
            archive_path, root, expected_commit=expected_commit, exact_tree=True
        ),
    )


def assemble_execution_root(
    source_archive: Path,
    data_archive: Path,
    output_root: Path,
    *,
    source_sha256: str,
    data_sha256: str,
    expected_commit: str,
) -> dict[str, Any]:
    """Verify independently, merge into a new task tree, then validate the freeze."""

    destination = Path(output_root)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("plan099_execution_root_exists")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    nonce = uuid.uuid4().hex
    source_root = destination.with_name(f".{destination.name}.source-{nonce}")
    data_root = destination.with_name(f".{destination.name}.data-{nonce}")
    staging = destination.with_name(f".{destination.name}.assemble-{nonce}")
    try:
        source_receipt = extract_source_archive(
            source_archive,
            source_root,
            expected_sha256=source_sha256,
            expected_commit=expected_commit,
        )
        data_receipt = extract_data_archive(
            data_archive,
            data_root,
            expected_sha256=data_sha256,
            expected_commit=expected_commit,
        )
        shutil.copytree(source_root, staging, symlinks=False)
        for child in data_root.iterdir():
            shutil.copytree(child, staging / child.name, dirs_exist_ok=True)
        load_freeze(staging)
        os.replace(staging, destination)
        return {
            "schema": "rondo-publication-critic-plan099-execution-root-v1",
            "commit": expected_commit,
            "freeze_sha256": freeze_sha256(destination),
            "source_archive_sha256": source_receipt["archive_sha256"],
            "data_archive_sha256": data_receipt["archive_sha256"],
        }
    finally:
        for path in (source_root, data_root, staging):
            if path.exists() and not path.is_symlink():
                shutil.rmtree(path)


def _archive_members(archive_path: Path) -> set[str]:
    result = set()
    try:
        with tarfile.open(archive_path, mode="r:") as archive:
            for item in archive:
                if item.isdir():
                    continue
                relative = _safe_member(item.name)
                if not item.isfile() or relative in result:
                    raise FullModelTrainingError("plan099_archive_member_invalid")
                result.add(relative)
    except FullModelTrainingError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise FullModelTrainingError("plan099_archive_invalid") from exc
    return result


def _verify_tree(
    archive_path: Path, source_root: Path, *, exact_tree: bool
) -> dict[str, Any]:
    try:
        return verify_source_archive_tree(
            archive_path, source_root, exact_tree=exact_tree
        )
    except Exception as exc:
        raise FullModelTrainingError("plan099_archive_tree_identity_mismatch") from exc


def _require_clean_commit(root: Path, commit: str, paths: tuple[str, ...]) -> None:
    expected = _commit(commit)
    if _git(root, "rev-parse", "HEAD") != expected:
        raise FullModelTrainingError("plan099_source_commit_mismatch")
    if _git(root, "status", "--porcelain", "--untracked-files=no", "--", *paths):
        raise FullModelTrainingError("plan099_source_tree_dirty")


def _git_archive(
    root: Path, output_path: Path, commit: str, paths: tuple[str, ...]
) -> None:
    destination = Path(output_path)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("plan099_archive_exists")
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
                *paths,
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        destination.chmod(0o600)
    except (OSError, subprocess.SubprocessError) as exc:
        destination.unlink(missing_ok=True)
        raise FullModelTrainingError("plan099_archive_create_failed") from exc


def _allowed(relative: str, paths: tuple[str, ...]) -> bool:
    return any(
        relative == allowed or relative.startswith(allowed.rstrip("/") + "/")
        for allowed in paths
    )


def _safe_member(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or value.startswith("/")
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise FullModelTrainingError("plan099_archive_member_invalid")
    return path.as_posix()


def _commit(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FullModelTrainingError("plan099_source_commit_invalid")
    return value


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
        raise FullModelTrainingError("plan099_git_identity_unavailable") from exc
    return completed.stdout.strip()


__all__ = [
    "assemble_execution_root",
    "create_data_archive",
    "create_source_archive",
    "extract_data_archive",
    "extract_source_archive",
    "verify_data_archive",
    "verify_source_archive",
]
