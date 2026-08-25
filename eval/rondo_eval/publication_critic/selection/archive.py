"""Write-once Plan 073 run namespaces.

Same shape as the Plan 068/071 qualification archives, bound to Plan 073 run
identities: a run directory can only be created once and a file inside it can
only be written once, so a resumed campaign cannot quietly overwrite evidence.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .contract import RUN_ID, SelectionError


class SelectionArchive:
    def __init__(self, runs_root: Path, run_id: str, mode: str) -> None:
        match = RUN_ID.fullmatch(run_id)
        if match is None or match.group(1) != mode:
            raise SelectionError("Plan 073 run identity is invalid")
        self.runs_root = runs_root
        self.run_id = run_id
        self.mode = mode
        self.path = runs_root / run_id

    def create(self, *, exist_ok: bool = False) -> "SelectionArchive":
        self.runs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.runs_root.is_symlink() or not self.runs_root.is_dir():
            raise SelectionError("Plan 073 runs root is unsafe")
        try:
            self.path.mkdir(mode=0o700)
        except FileExistsError:
            # A campaign may be resumed inside the same frozen namespace, but
            # individual artifacts still cannot be overwritten.
            if not exist_ok:
                raise SelectionError("Plan 073 run archive already exists") from None
            if self.path.is_symlink() or not self.path.is_dir():
                raise SelectionError("Plan 073 run archive is unsafe") from None
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
            raise SelectionError("Plan 073 archive was not safely created")
        relative = Path(name)
        if relative.is_absolute() or len(relative.parts) != 1 or relative.name in {
            "",
            ".",
            "..",
        }:
            raise SelectionError("Plan 073 archive file name is invalid")
        destination = self.path / relative
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(destination, flags, 0o600)
        except OSError as exc:
            raise SelectionError(
                "Plan 073 archive file cannot be created without overwrite"
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
