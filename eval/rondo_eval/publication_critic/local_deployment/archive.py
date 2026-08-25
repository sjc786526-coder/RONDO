"""Write-once Plan 068 commissioning and formal qualification archives."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


_RUN_ID = re.compile(
    r"plan068-(commissioning|formal)-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}\Z"
)


class QualificationArchiveError(ValueError):
    """Raised when a Plan 068 archive is unsafe, ambiguous, or mutable."""


class QualificationArchive:
    """A mode-bound namespace whose files can only be created once."""

    def __init__(self, runs_root: Path, run_id: str, mode: str) -> None:
        match = _RUN_ID.fullmatch(run_id)
        if match is None or match.group(1) != mode or mode not in {"commissioning", "formal"}:
            raise QualificationArchiveError("qualification run identity is invalid")
        self.runs_root = runs_root
        self.run_id = run_id
        self.mode = mode
        self.path = runs_root / run_id

    def create(self) -> "QualificationArchive":
        self.runs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.runs_root.is_symlink() or not self.runs_root.is_dir():
            raise QualificationArchiveError("qualification runs root is unsafe")
        try:
            self.path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise QualificationArchiveError("qualification run archive already exists") from exc
        return self

    def write_json(self, name: str, value: Any) -> Path:
        body = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8") + b"\n"
        return self.write_bytes(name, body)

    def write_bytes(self, name: str, value: bytes) -> Path:
        if self.path.is_symlink() or not self.path.is_dir():
            raise QualificationArchiveError("qualification archive was not safely created")
        relative = Path(name)
        if relative.is_absolute() or len(relative.parts) != 1 or relative.name in {"", ".", ".."}:
            raise QualificationArchiveError("qualification archive file name is invalid")
        destination = self.path / relative
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(destination, flags, 0o600)
        except OSError as exc:
            raise QualificationArchiveError(
                "qualification archive file cannot be created without overwrite"
            ) from exc
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            if destination.is_file() and not destination.is_symlink():
                destination.unlink()
            raise
        return destination
