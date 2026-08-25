"""Write-once Plan 073 run namespaces.

Same shape as the Plan 068/071 qualification archives, bound to Plan 073 run
identities: a run directory can only be created once and a file inside it can
only be written once, so a resumed campaign cannot quietly overwrite evidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..full_model_training.contract import pretty_json_bytes
from ..write_once import WriteOnceError, WriteOnceNamespace
from .contract import RUN_ID, SelectionError


class SelectionArchive:
    def __init__(self, runs_root: Path, run_id: str, mode: str) -> None:
        match = RUN_ID.fullmatch(run_id)
        if match is None or match.group(1) != mode:
            raise SelectionError("Plan 073 run identity is invalid")
        self.run_id = run_id
        self.mode = mode
        self._archive = WriteOnceNamespace(
            runs_root,
            run_id,
            validate_run_id=lambda value: value == run_id,
        )
        self.path = self._archive.path

    def create(self, *, exist_ok: bool = False) -> "SelectionArchive":
        try:
            self._archive.create(exist_ok=exist_ok)
        except WriteOnceError as exc:
            raise SelectionError(
                "Plan 073 run archive is unsafe or already exists"
            ) from exc
        return self

    def write_json(self, name: str, value: Any) -> Path:
        return self.write_bytes(name, pretty_json_bytes(value))

    def write_bytes(self, name: str, value: bytes) -> Path:
        try:
            return self._archive.write_bytes(name, value)
        except WriteOnceError as exc:
            raise SelectionError("Plan 073 archive file cannot be written") from exc
