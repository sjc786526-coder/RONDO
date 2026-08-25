"""Shared write-once filesystem namespace for post-Plan-054 eval runs."""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path


class WriteOnceError(ValueError):
    pass


class WriteOnceNamespace:
    def __init__(
        self,
        runs_root: Path,
        run_id: str,
        *,
        validate_run_id: Callable[[str], bool],
    ) -> None:
        if not validate_run_id(run_id):
            raise WriteOnceError("run_id_invalid")
        self.runs_root = runs_root
        self.run_id = run_id
        self.path = runs_root / run_id

    def create(self, *, exist_ok: bool = False) -> "WriteOnceNamespace":
        self.runs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.runs_root.is_symlink() or not self.runs_root.is_dir():
            raise WriteOnceError("runs_root_unsafe")
        try:
            self.path.mkdir(mode=0o700)
        except FileExistsError:
            if not exist_ok:
                raise WriteOnceError("namespace_exists") from None
            if self.path.is_symlink() or not self.path.is_dir():
                raise WriteOnceError("namespace_unsafe") from None
        return self

    def write_bytes(self, name: str, value: bytes) -> Path:
        if self.path.is_symlink() or not self.path.is_dir():
            raise WriteOnceError("namespace_not_created")
        relative = Path(name)
        if (
            relative.is_absolute()
            or len(relative.parts) != 1
            or relative.name
            in {
                "",
                ".",
                "..",
            }
        ):
            raise WriteOnceError("filename_invalid")
        destination = self.path / relative
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(destination, flags, 0o600)
        except OSError as exc:
            raise WriteOnceError("write_without_overwrite_failed") from exc
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
