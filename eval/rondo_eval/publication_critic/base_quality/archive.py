"""Plan 079 write-once run namespaces with resumable commissioning rows."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ..full_model_training.contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    sha256_bytes,
    write_exclusive,
)
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

    @property
    def _formal_authority_path(self) -> Path:
        return self._archive.runs_root / "formal-authority.json"

    def require_formal_unclaimed(self) -> None:
        """Reject a second formal run after the first complete valid result."""

        if self.mode != "formal":
            return
        marker = self._formal_authority_path
        if marker.exists() or marker.is_symlink():
            raise BaseQualityError("formal_result_already_authoritative")

    def claim_formal_result(self, result: Any) -> Path:
        """Make this campaign's first complete formal result authoritative."""

        if (
            self.mode != "formal"
            or not isinstance(result, dict)
            or result.get("valid_full_quality_run") is not True
            or result.get("terminal")
            not in {"4B_BASE_QUALITY_GO", "4B_BASE_QUALITY_NO_GO"}
        ):
            raise BaseQualityError("formal_authority_result_invalid")
        marker = self._formal_authority_path
        value = {
            "schema": "rondo-publication-critic-plan079-formal-authority-v1",
            "run_id": self._archive.run_id,
            "terminal": result["terminal"],
            "result_sha256": sha256_bytes(canonical_json_bytes(result)),
        }
        try:
            write_exclusive(marker, pretty_json_bytes(value))
        except (FullModelTrainingError, OSError) as exc:
            raise BaseQualityError("formal_result_already_authoritative") from exc
        return marker

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
