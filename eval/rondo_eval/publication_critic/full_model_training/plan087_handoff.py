"""Manifest-driven small-result handoff for Plan 087."""

from __future__ import annotations

import json
import os
import shutil
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    regular_file,
    safe_directory,
    safe_relative,
    sha256_bytes,
    sha256_file,
    write_exclusive,
)

HANDOFF_SCHEMA = "rondo-publication-critic-plan087-small-handoff-v1"
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
ALLOWED_ROLES = frozenset(
    {
        "route_result",
        "terminal_result",
        "validation_metrics",
        "pair_margins",
        "cost_snapshot",
        "resource_snapshot",
        "checkpoint_manifest",
        "receipt",
        "log",
    }
)
_ALLOWED_PREFIXES = (
    PurePosixPath("receipts"),
    PurePosixPath("logs"),
    PurePosixPath("cost"),
    PurePosixPath("resources"),
    PurePosixPath("formal-search/results"),
    PurePosixPath("formal-search/manifests"),
    PurePosixPath("debug/results"),
    PurePosixPath("debug/manifests"),
)
_BANNED_SEGMENTS = frozenset(
    {
        "checkpoints",
        "snapshots",
        "venv",
        "hf-home",
        "hub",
        "cache",
        "optimizer",
        "training-state",
    }
)
_BANNED_SUFFIXES = frozenset(
    {".bin", ".ckpt", ".onnx", ".pt", ".pth", ".safetensors", ".tar", ".zip"}
)


def create_small_handoff_manifest(
    task_root: Path, entries: Sequence[tuple[str, str]]
) -> dict[str, Any]:
    root = safe_directory(Path(task_root))
    if not entries:
        raise FullModelTrainingError("plan087_handoff_entries_required")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for role, relative_value in entries:
        relative = _validate_relative_member(relative_value, role)
        relative_text = relative.as_posix()
        if relative_text in seen:
            raise FullModelTrainingError("plan087_handoff_member_duplicate")
        path = _regular_task_member(root, relative)
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise FullModelTrainingError("plan087_handoff_file_too_large")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise FullModelTrainingError("plan087_handoff_total_too_large")
        seen.add(relative_text)
        rows.append(
            {
                "relative_path": relative_text,
                "role": role,
                "bytes": size,
                "sha256": sha256_file(path),
            }
        )
    core = {
        "schema": HANDOFF_SCHEMA,
        "entries": sorted(rows, key=lambda row: row["relative_path"]),
        "file_count": len(rows),
        "total_bytes": total,
        "maximum_file_bytes": MAX_FILE_BYTES,
        "maximum_total_bytes": MAX_TOTAL_BYTES,
        "exact_tree_required": True,
    }
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def validate_small_handoff_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "entries",
        "file_count",
        "total_bytes",
        "maximum_file_bytes",
        "maximum_total_bytes",
        "exact_tree_required",
        "content_sha256",
    }:
        raise FullModelTrainingError("plan087_handoff_manifest_invalid")
    entries = value.get("entries")
    if (
        value.get("schema") != HANDOFF_SCHEMA
        or not isinstance(entries, Sequence)
        or isinstance(entries, (str, bytes, bytearray))
        or not entries
        or value.get("maximum_file_bytes") != MAX_FILE_BYTES
        or value.get("maximum_total_bytes") != MAX_TOTAL_BYTES
        or value.get("exact_tree_required") is not True
    ):
        raise FullModelTrainingError("plan087_handoff_manifest_invalid")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for row in entries:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"relative_path", "role", "bytes", "sha256"}
            or not isinstance(row.get("bytes"), int)
            or isinstance(row["bytes"], bool)
            or not 0 <= row["bytes"] <= MAX_FILE_BYTES
            or not _sha256(row.get("sha256"))
        ):
            raise FullModelTrainingError("plan087_handoff_manifest_invalid")
        relative = _validate_relative_member(row.get("relative_path"), row.get("role"))
        relative_text = relative.as_posix()
        if relative_text in seen:
            raise FullModelTrainingError("plan087_handoff_manifest_invalid")
        seen.add(relative_text)
        total += row["bytes"]
        normalized.append(dict(row))
    if (
        normalized != sorted(normalized, key=lambda row: row["relative_path"])
        or value.get("file_count") != len(normalized)
        or value.get("total_bytes") != total
        or total > MAX_TOTAL_BYTES
    ):
        raise FullModelTrainingError("plan087_handoff_manifest_invalid")
    core = {key: value[key] for key in value if key != "content_sha256"}
    if value.get("content_sha256") != sha256_bytes(canonical_json_bytes(core)):
        raise FullModelTrainingError("plan087_handoff_manifest_invalid")
    return json.loads(json.dumps(value))


def stage_small_handoff(
    task_root: Path, manifest: Mapping[str, Any], destination: Path
) -> dict[str, Any]:
    root = safe_directory(Path(task_root))
    value = validate_small_handoff_manifest(manifest)
    output = _new_task_descendant(root, Path(destination))
    output.mkdir(mode=0o700)
    try:
        for row in value["entries"]:
            relative = safe_relative(row["relative_path"])
            source = _regular_task_member(root, relative)
            if (
                source.stat().st_size != row["bytes"]
                or sha256_file(source) != row["sha256"]
            ):
                raise FullModelTrainingError("plan087_handoff_source_drifted")
            target = output.joinpath(*relative.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            target.chmod(0o600)
        manifest_path = output / "handoff-manifest.json"
        write_exclusive(manifest_path, pretty_json_bytes(value))
        verify_small_handoff(output, manifest_path, exact_tree=True)
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return {
        "schema": HANDOFF_SCHEMA,
        "status": "staged",
        "manifest_content_sha256": value["content_sha256"],
        "file_count": value["file_count"],
        "total_bytes": value["total_bytes"],
        "staging_root": str(output),
    }


def verify_small_handoff(
    root: Path, manifest_path: Path, *, exact_tree: bool
) -> dict[str, Any]:
    handoff_root = safe_directory(Path(root))
    manifest_file = regular_file(Path(manifest_path), maximum_bytes=1024 * 1024)
    try:
        value = validate_small_handoff_manifest(
            json.loads(manifest_file.read_text(encoding="utf-8"))
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullModelTrainingError("plan087_handoff_manifest_invalid") from exc
    expected: set[str] = set()
    for row in value["entries"]:
        relative = safe_relative(row["relative_path"])
        path = _regular_task_member(handoff_root, relative)
        if path.stat().st_size != row["bytes"] or sha256_file(path) != row["sha256"]:
            raise FullModelTrainingError("plan087_handoff_member_invalid")
        expected.add(relative.as_posix())
    if exact_tree:
        observed = _regular_tree(handoff_root)
        try:
            manifest_relative = manifest_file.resolve(strict=True).relative_to(
                handoff_root
            )
        except ValueError as exc:
            raise FullModelTrainingError("plan087_handoff_manifest_outside_root") from exc
        expected.add(manifest_relative.as_posix())
        if observed != expected:
            raise FullModelTrainingError("plan087_handoff_exact_tree_invalid")
    return value


def _validate_relative_member(value: Any, role: Any) -> PurePosixPath:
    if role not in ALLOWED_ROLES or not isinstance(value, str):
        raise FullModelTrainingError("plan087_handoff_member_invalid")
    relative = safe_relative(value)
    lowered = [part.lower() for part in relative.parts]
    if (
        not any(relative.is_relative_to(prefix) for prefix in _ALLOWED_PREFIXES)
        or any(part in _BANNED_SEGMENTS or part.startswith("model-") for part in lowered)
        or relative.suffix.lower() in _BANNED_SUFFIXES
        or relative.suffix.lower() not in {".json", ".jsonl", ".log", ".md", ".txt"}
        or (role == "log" and relative.suffix.lower() not in {".jsonl", ".log", ".txt"})
        or (role != "log" and relative.suffix.lower() != ".json")
    ):
        raise FullModelTrainingError("plan087_handoff_member_invalid")
    return relative


def _regular_task_member(root: Path, relative: PurePosixPath) -> Path:
    path = root.joinpath(*relative.parts)
    _reject_symlink_chain(path)
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise FullModelTrainingError("plan087_handoff_member_invalid") from exc
    if not resolved.is_relative_to(root):
        raise FullModelTrainingError("plan087_handoff_member_invalid")
    return regular_file(resolved)


def _new_task_descendant(root: Path, destination: Path) -> Path:
    path = destination if destination.is_absolute() else Path.cwd() / destination
    _reject_symlink_chain(path)
    resolved = path.resolve(strict=False)
    if (
        resolved == root
        or not resolved.is_relative_to(root)
        or resolved.exists()
        or resolved.is_symlink()
    ):
        raise FullModelTrainingError("plan087_handoff_staging_invalid")
    return resolved


def _reject_symlink_chain(path: Path) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise FullModelTrainingError("plan087_handoff_path_invalid") from exc
        if stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan087_handoff_symlink_rejected")


def _regular_tree(root: Path) -> set[str]:
    observed: set[str] = set()
    for path in root.rglob("*"):
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not (
            stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
        ):
            raise FullModelTrainingError("plan087_handoff_tree_unsafe")
        if stat.S_ISREG(info.st_mode):
            observed.add(path.relative_to(root).as_posix())
    return observed


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "ALLOWED_ROLES",
    "HANDOFF_SCHEMA",
    "MAX_FILE_BYTES",
    "MAX_TOTAL_BYTES",
    "create_small_handoff_manifest",
    "stage_small_handoff",
    "validate_small_handoff_manifest",
    "verify_small_handoff",
]
