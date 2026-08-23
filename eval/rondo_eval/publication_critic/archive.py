"""Write-once ignored run archives for Publication Critic evaluation."""

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable


_RUN_ID = re.compile(r"plan054-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}\Z")


class ArchiveError(ValueError):
    """Raised when a Plan 054 archive would be ambiguous or overwrite data."""


class RunArchive:
    def __init__(self, runs_root: Path, run_id: str) -> None:
        if _RUN_ID.fullmatch(run_id) is None:
            raise ArchiveError("run id is invalid")
        self.runs_root = runs_root
        self.run_id = run_id
        self.path = runs_root / run_id

    def create(self) -> "RunArchive":
        self.runs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.runs_root.is_symlink() or not self.runs_root.is_dir():
            raise ArchiveError("runs root is unsafe")
        try:
            self.path.mkdir(mode=0o700)
        except FileExistsError as exc:
            raise ArchiveError("run archive already exists") from exc
        return self

    def write_json(self, name: str, value: Any) -> Path:
        return self.write_bytes(
            name,
            json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
            + b"\n",
        )

    def write_jsonl(self, name: str, rows: Iterable[Any]) -> Path:
        body = b"".join(
            json.dumps(row, ensure_ascii=False, allow_nan=False, sort_keys=True).encode("utf-8")
            + b"\n"
            for row in rows
        )
        return self.write_bytes(name, body)

    def write_bytes(self, name: str, value: bytes) -> Path:
        if not self.path.is_dir() or self.path.is_symlink():
            raise ArchiveError("run archive has not been safely created")
        relative = Path(name)
        if relative.is_absolute() or len(relative.parts) != 1 or relative.name in {"", ".", ".."}:
            raise ArchiveError("archive file name is invalid")
        destination = self.path / relative
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(destination, flags, 0o600)
        except OSError as exc:
            raise ArchiveError("archive file cannot be created without overwrite") from exc
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
