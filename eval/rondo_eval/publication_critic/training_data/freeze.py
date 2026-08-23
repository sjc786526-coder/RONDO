"""Content-addressed freeze manifest helpers for Plan 059 assets."""

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from .contract import TrainingDataError


_MANIFEST_KEYS = {
    "schema",
    "dataset_name",
    "dataset_revision",
    "input_identity",
    "design_lock_sha256",
    "generation_commit",
    "contracts",
    "files",
    "statistics",
    "content_sha256",
}


def build_freeze_manifest(
    root: Path,
    relative_paths: Sequence[str],
    *,
    dataset_revision: str,
    input_identity: Mapping[str, Any],
    design_lock_sha256: str,
    generation_commit: str,
    contracts: Mapping[str, Any],
    statistics: Mapping[str, Any],
) -> dict[str, Any]:
    safe_root = _safe_root(root)
    if not relative_paths:
        raise TrainingDataError("freeze manifest must bind at least one file")
    if len(relative_paths) != len(set(relative_paths)):
        raise TrainingDataError("freeze manifest relative paths must be unique")
    files: dict[str, dict[str, Any]] = {}
    for relative in sorted(relative_paths):
        path = _safe_file(safe_root, relative)
        files[relative] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    core = {
        "schema": "rondo-publication-critic-training-freeze-v1",
        "dataset_name": "rondo-publication-critic-training",
        "dataset_revision": _text(dataset_revision, "dataset_revision"),
        "input_identity": dict(input_identity),
        "design_lock_sha256": _digest(design_lock_sha256, "design_lock_sha256"),
        "generation_commit": _git_sha(generation_commit),
        "contracts": dict(contracts),
        "files": files,
        "statistics": dict(statistics),
    }
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def verify_freeze_manifest(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    expected_input_identity: Mapping[str, Any] | None = None,
) -> None:
    if set(manifest) != _MANIFEST_KEYS:
        raise TrainingDataError("freeze manifest keys differ")
    if manifest["schema"] != "rondo-publication-critic-training-freeze-v1":
        raise TrainingDataError("freeze manifest schema drifted")
    if manifest["dataset_name"] != "rondo-publication-critic-training":
        raise TrainingDataError("freeze manifest dataset name drifted")
    _text(manifest["dataset_revision"], "dataset_revision")
    if not isinstance(manifest["input_identity"], Mapping):
        raise TrainingDataError("freeze manifest input_identity must be an object")
    _digest(manifest["design_lock_sha256"], "design_lock_sha256")
    _git_sha(manifest["generation_commit"])
    if not isinstance(manifest["contracts"], Mapping) or not isinstance(manifest["statistics"], Mapping):
        raise TrainingDataError("freeze manifest contracts/statistics must be objects")
    if expected_input_identity is not None and manifest["input_identity"] != expected_input_identity:
        raise TrainingDataError("freeze manifest input identity drifted")
    expected_content = manifest["content_sha256"]
    core = {key: value for key, value in manifest.items() if key != "content_sha256"}
    if not isinstance(expected_content, str) or sha256_bytes(canonical_json_bytes(core)) != expected_content:
        raise TrainingDataError("freeze manifest content identity drifted")
    safe_root = _safe_root(root)
    files = manifest["files"]
    if not isinstance(files, Mapping) or not files:
        raise TrainingDataError("freeze manifest files must be a non-empty object")
    for relative, expected in files.items():
        if not isinstance(expected, Mapping) or set(expected) != {"bytes", "sha256"}:
            raise TrainingDataError(f"freeze file metadata is invalid: {relative}")
        path = _safe_file(safe_root, str(relative))
        byte_count = expected["bytes"]
        digest = expected["sha256"]
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 0:
            raise TrainingDataError(f"freeze file byte count is invalid: {relative}")
        _digest(digest, f"files.{relative}.sha256")
        if path.stat().st_size != byte_count or sha256_file(path) != digest:
            raise TrainingDataError(f"frozen file identity drifted: {relative}")


def _safe_root(root: Path) -> Path:
    if not root.is_dir() or root.is_symlink():
        raise TrainingDataError(f"freeze root is missing or unsafe: {root}")
    return root.resolve()


def _safe_file(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise TrainingDataError(f"freeze relative path is unsafe: {relative!r}")
    path = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise TrainingDataError(f"frozen path contains a symlink: {relative}")
    if not path.is_file():
        raise TrainingDataError(f"frozen file is missing: {relative}")
    return path


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrainingDataError(f"{where} must be a non-empty string")
    return value


def _digest(value: Any, where: str) -> str:
    text = _text(value, where)
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise TrainingDataError(f"{where} must be lowercase SHA-256")
    return text


def _git_sha(value: Any) -> str:
    text = _text(value, "generation_commit")
    if len(text) != 40 or any(character not in "0123456789abcdef" for character in text):
        raise TrainingDataError("generation_commit must be a full lowercase Git SHA")
    return text
