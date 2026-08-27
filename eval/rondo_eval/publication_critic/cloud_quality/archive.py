"""Write-once Plan 096 commissioning/formal namespaces and authority."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from ..write_once import WriteOnceError, WriteOnceNamespace
from .contract import (
    AUTHORITY_SCHEMA,
    CloudQualityError,
    RUN_ID,
    TERMINALS,
    freeze_sha256,
    require_sha256,
    validate_call_record,
    validate_freeze,
)


def _pretty_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


class CloudQualityArchive:
    """One mode-specific run; commissioning alone may append later logical calls."""

    def __init__(self, runs_root: Path, run_id: str, mode: str) -> None:
        match = RUN_ID.fullmatch(run_id)
        if match is None or match.group(1) != mode:
            raise CloudQualityError("archive_run_identity_invalid")
        self.runs_root = runs_root
        self.run_id = run_id
        self.mode = mode
        try:
            self._namespace = WriteOnceNamespace(
                runs_root,
                run_id,
                validate_run_id=lambda value: value == run_id,
            )
        except WriteOnceError as exc:
            raise CloudQualityError("archive_run_identity_invalid") from exc

    @property
    def path(self) -> Path:
        return self._namespace.path

    @property
    def authority_path(self) -> Path:
        return self.runs_root / "formal-authority.json"

    def create(self, freeze_value: Any) -> "CloudQualityArchive":
        freeze = validate_freeze(freeze_value)
        if (
            freeze["namespace"]["run_id"] != self.run_id
            or freeze["namespace"]["mode"] != self.mode
        ):
            raise CloudQualityError("archive_freeze_run_mismatch")
        try:
            self._namespace.create(exist_ok=self.mode == "commissioning")
        except WriteOnceError as exc:
            code = (
                "formal_namespace_not_empty"
                if self.mode == "formal"
                else "commissioning_namespace_unsafe"
            )
            raise CloudQualityError(code) from exc
        self.bind_json("freeze.json", freeze)
        return self

    def bind_json(self, name: str, value: Any) -> Path:
        body = _pretty_json_bytes(value)
        destination = self.path / name
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise CloudQualityError("archive_binding_unsafe")
            try:
                existing = destination.read_bytes()
            except OSError as exc:
                raise CloudQualityError("archive_binding_unreadable") from exc
            if existing != body:
                raise CloudQualityError("archive_binding_drifted")
            return destination
        return self.write_bytes(name, body)

    def write_json(self, name: str, value: Any) -> Path:
        return self.write_bytes(name, _pretty_json_bytes(value))

    def write_bytes(self, name: str, value: bytes) -> Path:
        try:
            return self._namespace.write_bytes(name, value)
        except (WriteOnceError, OSError) as exc:
            raise CloudQualityError("archive_write_failed") from exc

    @staticmethod
    def _candidate_digest(candidate_id: str) -> str:
        return hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()

    def _commissioning_call_paths(self, candidate_id: str) -> list[Path]:
        digest = self._candidate_digest(candidate_id)
        if not self.path.exists():
            return []
        return sorted(self.path.glob(f"call-{digest}-*.json"))

    def _formal_call_path(self, candidate_id: str) -> Path:
        return self.path / f"call-{self._candidate_digest(candidate_id)}.json"

    def load_success(
        self, candidate_id: str, *, expected_freeze_sha256: str
    ) -> dict[str, Any] | None:
        """Recover exactly one prior commissioning success under the same freeze."""

        require_sha256(expected_freeze_sha256, "archive_expected_freeze_invalid")
        paths = (
            self._commissioning_call_paths(candidate_id)
            if self.mode == "commissioning"
            else [self._formal_call_path(candidate_id)]
        )
        successes: list[dict[str, Any]] = []
        for path in paths:
            if not path.exists() and not path.is_symlink():
                continue
            if path.is_symlink() or not path.is_file():
                raise CloudQualityError("archive_call_unsafe")
            try:
                record = validate_call_record(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError) as exc:
                raise CloudQualityError("archive_call_invalid") from exc
            if (
                record["candidate_id"] != candidate_id
                or record["freeze_sha256"] != expected_freeze_sha256
            ):
                raise CloudQualityError("archive_call_identity_mismatch")
            if record["status"] == "success":
                successes.append(record)
        if len(successes) > 1:
            raise CloudQualityError("archive_duplicate_success")
        return successes[0] if successes else None

    def write_call(self, candidate_id: str, value: Any) -> Path:
        record = validate_call_record(value)
        if record["candidate_id"] != candidate_id:
            raise CloudQualityError("archive_call_identity_mismatch")
        if self.mode == "formal":
            destination = self._formal_call_path(candidate_id)
            return self.write_json(destination.name, record)
        ordinal = len(self._commissioning_call_paths(candidate_id)) + 1
        name = f"call-{self._candidate_digest(candidate_id)}-{ordinal:04d}.json"
        return self.write_json(name, record)

    def load_authority(self) -> dict[str, Any] | None:
        path = self.authority_path
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise CloudQualityError("formal_authority_unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CloudQualityError("formal_authority_invalid") from exc
        if (
            not isinstance(value, dict)
            or set(value)
            != {"schema", "run_id", "terminal", "result_sha256", "freeze_sha256"}
            or value.get("schema") != AUTHORITY_SCHEMA
            or value.get("terminal") not in TERMINALS
        ):
            raise CloudQualityError("formal_authority_invalid")
        match = RUN_ID.fullmatch(value.get("run_id", ""))
        if match is None or match.group(1) != "formal":
            raise CloudQualityError("formal_authority_invalid")
        require_sha256(value.get("result_sha256"), "formal_authority_invalid")
        require_sha256(value.get("freeze_sha256"), "formal_authority_invalid")
        return value

    def claim_formal_result(self, freeze_value: Any, result: Any) -> Path:
        freeze = validate_freeze(freeze_value)
        if (
            self.mode != "formal"
            or not isinstance(result, dict)
            or result.get("complete") is not True
            or result.get("terminal") not in TERMINALS
            or result.get("scored_count") != 55
            or result.get("typed_failure_count") != 0
        ):
            raise CloudQualityError("formal_authority_result_invalid")
        value = {
            "schema": AUTHORITY_SCHEMA,
            "run_id": self.run_id,
            "terminal": result["terminal"],
            "result_sha256": sha256_bytes(canonical_json_bytes(result)),
            "freeze_sha256": freeze_sha256(freeze),
        }
        existing = self.load_authority()
        if existing is not None:
            if existing != value:
                raise CloudQualityError("formal_result_already_authoritative")
            return self.authority_path
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.authority_path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_pretty_json_bytes(value))
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            existing = self.load_authority()
            if existing != value:
                raise CloudQualityError("formal_result_already_authoritative") from exc
        return self.authority_path
