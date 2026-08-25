"""Plan 079 write-once run namespaces with resumable commissioning rows."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..full_model_training.contract import pretty_json_bytes, read_json
from ..write_once import WriteOnceError, WriteOnceNamespace
from .contract import BaseQualityError, RUN_ID


class BaseQualityArchive:
    def __init__(self, runs_root: Path, run_id: str, mode: str) -> None:
        match = RUN_ID.fullmatch(run_id)
        if match is None or match.group(1) != mode:
            raise BaseQualityError("run_archive_identity_invalid")
        self.mode = mode
        try:
            self._archive = WriteOnceNamespace(
                runs_root,
                run_id,
                validate_run_id=lambda value: value == run_id,
            )
        except WriteOnceError as exc:
            raise BaseQualityError("run_archive_identity_invalid") from exc

    @property
    def path(self) -> Path:
        return self._archive.path

    def create(self) -> "BaseQualityArchive":
        try:
            self._archive.create(exist_ok=self.mode == "commissioning")
        except WriteOnceError as exc:
            code = (
                "formal_namespace_not_empty"
                if self.mode == "formal"
                else "commissioning_namespace_unsafe"
            )
            raise BaseQualityError(code) from exc
        return self

    def bind_json(self, name: str, value: Any) -> Path:
        """Write an identity once, or require its exact prior bytes on resume."""

        body = pretty_json_bytes(value)
        destination = self.path / name
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise BaseQualityError("commissioning_identity_unsafe")
            try:
                existing = destination.read_bytes()
            except OSError as exc:
                raise BaseQualityError("commissioning_identity_unreadable") from exc
            if existing != body:
                raise BaseQualityError("commissioning_identity_drifted")
            return destination
        return self.write_json(name, value)

    def load_json(self, name: str) -> dict[str, Any] | None:
        path = self.path / name
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise BaseQualityError("run_archive_entry_unsafe")
        try:
            value = read_json(path)
        except Exception as exc:  # noqa: BLE001 - normalize archive parse failures
            raise BaseQualityError("run_archive_entry_invalid") from exc
        if not isinstance(value, dict):
            raise BaseQualityError("run_archive_entry_invalid")
        return value

    def write_json(self, name: str, value: Any) -> Path:
        try:
            return self._archive.write_bytes(name, pretty_json_bytes(value))
        except (WriteOnceError, OSError) as exc:
            raise BaseQualityError("run_archive_write_failed") from exc

    def score_name(self, candidate_id: str) -> str:
        digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()
        return f"score-{digest}.json"

    def load_score(self, candidate_id: str) -> dict[str, Any] | None:
        path = self.path / self.score_name(candidate_id)
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise BaseQualityError("score_progress_unsafe")
        value = read_json(path)
        if not isinstance(value, dict) or value.get("candidate_id") != candidate_id:
            raise BaseQualityError("score_progress_identity_invalid")
        return value

    def write_score(self, candidate_id: str, value: Any) -> Path:
        return self.write_json(self.score_name(candidate_id), value)
