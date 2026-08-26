"""Plan 087 source archive plus the frozen Plan 082 data projection reuse."""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from ..base_quality.source import verify_source_archive_tree
from .bundle import extract_archive_with_verifier
from .contract import FullModelTrainingError, safe_directory
from .plan082_bundle import (
    create_data_archive,
    extract_data_archive,
    prepare_data_bundle,
    verify_data_bundle,
)

SOURCE_BUNDLE_SCHEMA = "rondo-publication-critic-plan087-source-bundle-v1"
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
    "training/publication-critic-plan081/route-contract-v1.json",
    "training/publication-critic-plan087",
)
REQUIRED_SOURCE_MEMBERS = {
    "eval/rondo_eval/publication_critic/full_model_training/plan087_adapter.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan087_bundle.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan087_capacity.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan087_cli.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan087_contract.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan087_controller.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan087_finalize.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan087_handoff.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan087_run.py",
    "eval/rondo_eval/publication_critic/full_model_training/plan087_search.py",
    "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json",
    "training/publication-critic-plan081/route-contract-v1.json",
    "training/publication-critic-plan087/README.md",
    "training/publication-critic-plan087/runpod-create.py",
    "training/publication-critic-plan087/runpod-terminal.py",
}


def create_source_archive(
    repo_root: Path, output_path: Path, *, source_commit: str
) -> dict[str, Any]:
    root = safe_directory(Path(repo_root))
    destination = Path(output_path)
    if destination.exists() or destination.is_symlink():
        raise FullModelTrainingError("plan087_source_archive_exists")
    commit = _git(root, "rev-parse", "HEAD")
    if source_commit != commit or len(commit) != 40:
        raise FullModelTrainingError("plan087_source_commit_mismatch")
    dirty = _git(
        root, "status", "--porcelain", "--untracked-files=no", "--", *SOURCE_PATHS
    )
    if dirty:
        raise FullModelTrainingError("plan087_source_tree_dirty")
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
            destination, root, exact_tree=False, expected_commit=commit
        )
    except (OSError, subprocess.SubprocessError) as exc:
        destination.unlink(missing_ok=True)
        raise FullModelTrainingError("plan087_source_archive_create_failed") from exc
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
            archive_path, root, exact_tree=True, expected_commit=expected_commit
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
        raise FullModelTrainingError("plan087_source_commit_invalid")
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
                    raise FullModelTrainingError("plan087_source_member_invalid")
                members.add(relative)
    except FullModelTrainingError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise FullModelTrainingError("plan087_source_archive_invalid") from exc
    if not members >= REQUIRED_SOURCE_MEMBERS:
        raise FullModelTrainingError("plan087_source_members_missing")
    try:
        receipt = verify_source_archive_tree(
            archive_path, source_root, exact_tree=exact_tree
        )
    except Exception as exc:
        raise FullModelTrainingError("plan087_source_tree_identity_mismatch") from exc
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
        raise FullModelTrainingError("plan087_source_member_invalid")
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
        raise FullModelTrainingError("plan087_git_identity_unavailable") from exc
    return completed.stdout.strip()


__all__ = [
    "SOURCE_BUNDLE_SCHEMA",
    "SOURCE_PATHS",
    "create_data_archive",
    "create_source_archive",
    "extract_data_archive",
    "extract_source_archive",
    "prepare_data_bundle",
    "verify_data_bundle",
    "verify_source_archive",
]
