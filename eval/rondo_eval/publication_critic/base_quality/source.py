"""Bind a Plan 079 source archive to the tree that actually executes it."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from .contract import BaseQualityError


def _safe_member(name: str) -> PurePosixPath:
    member = PurePosixPath(name)
    if (
        not name
        or name.startswith("/")
        or member.is_absolute()
        or ".." in member.parts
        or any(part in {"", "."} for part in member.parts)
    ):
        raise BaseQualityError("source_archive_member_unsafe")
    return member


def verify_source_archive_tree(
    archive: Path,
    source_root: Path,
    *,
    exact_tree: bool,
) -> dict[str, Any]:
    """Verify every archived byte against the executing source tree.

    A local clean worktree may contain files outside the deliberately narrow
    source bundle, so freeze uses ``exact_tree=False``.  The extracted cloud
    source root is code-only and must contain exactly the archive's regular
    files; this prevents a new archive identity from being paired with a
    persistent root that still executes old code.
    """

    try:
        archive_info = os.lstat(archive)
        root_info = os.lstat(source_root)
    except OSError as exc:
        raise BaseQualityError("source_archive_or_root_unavailable") from exc
    if (
        not stat.S_ISREG(archive_info.st_mode)
        or stat.S_ISLNK(archive_info.st_mode)
        or not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
    ):
        raise BaseQualityError("source_archive_or_root_unsafe")

    observed: dict[str, dict[str, Any]] = {}
    directories: set[str] = set()
    seen: set[str] = set()
    try:
        with tarfile.open(archive, mode="r:") as handle:
            for entry in handle:
                relative = _safe_member(entry.name).as_posix()
                if relative in seen:
                    raise BaseQualityError("source_archive_member_duplicate")
                seen.add(relative)
                if entry.isdir():
                    directories.add(relative)
                    continue
                if not entry.isfile():
                    raise BaseQualityError("source_archive_member_unsafe")
                archived = handle.extractfile(entry)
                if archived is None:
                    raise BaseQualityError("source_archive_member_unreadable")
                archived_body = archived.read()
                if len(archived_body) != entry.size:
                    raise BaseQualityError("source_archive_member_unreadable")
                path = source_root.joinpath(*PurePosixPath(relative).parts)
                info = os.lstat(path)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or stat.S_ISLNK(info.st_mode)
                    or info.st_size != entry.size
                    or sha256_file(path) != sha256_bytes(archived_body)
                ):
                    raise BaseQualityError("source_tree_identity_mismatch")
                observed[relative] = {
                    "bytes": entry.size,
                    "sha256": sha256_bytes(archived_body),
                }
    except BaseQualityError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise BaseQualityError("source_archive_invalid") from exc
    if not observed:
        raise BaseQualityError("source_archive_empty")

    if exact_tree:
        actual: set[str] = set()
        for path in source_root.rglob("*"):
            relative = path.relative_to(source_root).as_posix()
            info = os.lstat(path)
            if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise BaseQualityError("source_tree_entry_unsafe")
            actual.add(relative)
        if actual != set(observed):
            raise BaseQualityError("source_tree_file_set_mismatch")

    return {
        "source_archive_sha256": sha256_file(archive),
        "source_content_sha256": sha256_bytes(canonical_json_bytes(observed)),
        "file_count": len(observed),
        "directory_count": len(directories),
    }
