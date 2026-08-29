"""Write-once receipts, terminal observations, and formal authority for Plan 100."""

import hashlib
import json
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from ..write_once import WriteOnceError, WriteOnceNamespace

RECEIPT_SCHEMA = "rondo-publication-critic-plan100-attempt-receipt@v1"
TERMINAL_SCHEMA = "rondo-publication-critic-plan100-terminal-observation@v1"
AUTHORITY_SCHEMA = "rondo-publication-critic-plan100-formal-authority@v1"
RUN_ID = re.compile(
    r"plan100-(commissioning|formal)-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}\Z"
)
AUTHORITY_TERMINALS = {
    "FIVE_DIMENSION_STRONGLY_SUPPORTED",
    "DISCRETE_SUPPORTED_FIVE_DIMENSION_INCREMENT_UNCONFIRMED",
    "CONSTRAINT_OR_DATA_ISSUE",
    "TASK_EXECUTABILITY_INSUFFICIENT",
}


class DiagnosticArchiveError(RuntimeError):
    """The Plan 100 ignored namespace is unsafe, incomplete, or drifted."""


def _sha(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(value)))


def _pretty(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _logical_digest(logical_key: str) -> str:
    if not isinstance(logical_key, str) or not logical_key or len(logical_key) > 256:
        raise DiagnosticArchiveError("logical_key_invalid")
    return hashlib.sha256(logical_key.encode("utf-8")).hexdigest()


class DiagnosticArchive:
    """One commissioning/formal run with resumable receipts and write-once terminals."""

    def __init__(self, runs_root: Path, run_id: str, mode: str) -> None:
        match = RUN_ID.fullmatch(run_id)
        if match is None or match.group(1) != mode:
            raise DiagnosticArchiveError("run_identity_invalid")
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
            raise DiagnosticArchiveError("run_identity_invalid") from exc

    @property
    def path(self) -> Path:
        return self._namespace.path

    @property
    def authority_path(self) -> Path:
        return self.runs_root / "formal-authority.json"

    def start(self, freeze: Mapping[str, Any]) -> "DiagnosticArchive":
        if self.mode == "formal":
            self.require_formal_unclaimed()
        try:
            self._namespace.create()
        except WriteOnceError as exc:
            raise DiagnosticArchiveError("namespace_not_empty") from exc
        self.bind_json("freeze.json", freeze)
        return self

    def resume(self, freeze: Mapping[str, Any]) -> "DiagnosticArchive":
        if self.mode == "formal":
            self.require_formal_unclaimed()
        if (
            self.runs_root.is_symlink()
            or not self.runs_root.is_dir()
            or self.path.is_symlink()
            or not self.path.is_dir()
        ):
            raise DiagnosticArchiveError("namespace_missing_or_unsafe")
        self.bind_json("freeze.json", freeze)
        return self

    def reopen_read_only(self, freeze: Mapping[str, Any]) -> "DiagnosticArchive":
        """Open immutable run evidence without authorizing any further provider work."""

        freeze_path = self.path / "freeze.json"
        if (
            self.runs_root.is_symlink()
            or not self.runs_root.is_dir()
            or self.path.is_symlink()
            or not self.path.is_dir()
            or freeze_path.is_symlink()
            or not freeze_path.is_file()
        ):
            raise DiagnosticArchiveError("namespace_missing_or_unsafe")
        try:
            existing = freeze_path.read_bytes()
        except OSError as exc:
            raise DiagnosticArchiveError("binding_unreadable") from exc
        if existing != _pretty(freeze):
            raise DiagnosticArchiveError("binding_drifted")
        return self

    def bind_json(self, name: str, value: Any) -> Path:
        body = _pretty(value)
        destination = self.path / name
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise DiagnosticArchiveError("binding_unsafe")
            try:
                existing = destination.read_bytes()
            except OSError as exc:
                raise DiagnosticArchiveError("binding_unreadable") from exc
            if existing != body:
                raise DiagnosticArchiveError("binding_drifted")
            return destination
        return self.write_bytes(name, body)

    def write_bytes(self, name: str, body: bytes) -> Path:
        try:
            return self._namespace.write_bytes(name, body)
        except (WriteOnceError, OSError) as exc:
            raise DiagnosticArchiveError("archive_write_failed") from exc

    def _receipt_paths(self, logical_key: str) -> list[Path]:
        digest = _logical_digest(logical_key)
        if not self.path.exists():
            return []
        return sorted(self.path.glob(f"receipt-{digest}-*.json"))

    def write_receipt(self, logical_key: str, value: Mapping[str, Any]) -> Path:
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != RECEIPT_SCHEMA
            or value.get("logical_key") != logical_key
        ):
            raise DiagnosticArchiveError("receipt_invalid")
        ordinal = len(self._receipt_paths(logical_key)) + 1
        name = f"receipt-{_logical_digest(logical_key)}-{ordinal:04d}.json"
        return self.write_bytes(name, _pretty(value))

    def load_receipts(self, logical_key: str) -> tuple[dict[str, Any], ...]:
        receipts = []
        for path in self._receipt_paths(logical_key):
            if path.is_symlink() or not path.is_file():
                raise DiagnosticArchiveError("receipt_unsafe")
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise DiagnosticArchiveError("receipt_invalid") from exc
            if (
                not isinstance(value, dict)
                or value.get("schema") != RECEIPT_SCHEMA
                or value.get("logical_key") != logical_key
            ):
                raise DiagnosticArchiveError("receipt_invalid")
            receipts.append(value)
        return tuple(receipts)

    def _terminal_path(self, logical_key: str) -> Path:
        return self.path / f"terminal-{_logical_digest(logical_key)}.json"

    def load_terminal(self, logical_key: str) -> dict[str, Any] | None:
        path = self._terminal_path(logical_key)
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise DiagnosticArchiveError("terminal_unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DiagnosticArchiveError("terminal_invalid") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema") != TERMINAL_SCHEMA
            or value.get("logical_key") != logical_key
        ):
            raise DiagnosticArchiveError("terminal_invalid")
        return value

    def write_terminal(self, logical_key: str, value: Mapping[str, Any]) -> Path:
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != TERMINAL_SCHEMA
            or value.get("logical_key") != logical_key
        ):
            raise DiagnosticArchiveError("terminal_invalid")
        path = self._terminal_path(logical_key)
        body = _pretty(value)
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise DiagnosticArchiveError("terminal_unsafe")
            if path.read_bytes() != body:
                raise DiagnosticArchiveError("terminal_drifted")
            return path
        return self.write_bytes(path.name, body)

    def load_authority(self) -> dict[str, Any] | None:
        path = self.authority_path
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise DiagnosticArchiveError("formal_authority_unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DiagnosticArchiveError("formal_authority_invalid") from exc
        match = (
            RUN_ID.fullmatch(str(value.get("run_id")))
            if isinstance(value, dict)
            else None
        )
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "schema",
                "run_id",
                "freeze_sha256",
                "result_sha256",
                "route_terminal",
            }
            or value.get("schema") != AUTHORITY_SCHEMA
            or match is None
            or match.group(1) != "formal"
            or value.get("route_terminal") not in AUTHORITY_TERMINALS
            or not _is_sha256(value.get("freeze_sha256"))
            or not _is_sha256(value.get("result_sha256"))
        ):
            raise DiagnosticArchiveError("formal_authority_invalid")
        return value

    def require_formal_unclaimed(self) -> None:
        if self.mode == "formal" and self.load_authority() is not None:
            raise DiagnosticArchiveError("formal_result_already_authoritative")

    def claim_formal_result(
        self, freeze: Mapping[str, Any], result: Mapping[str, Any]
    ) -> Path:
        if (
            self.mode != "formal"
            or result.get("complete") is not True
            or result.get("terminal_observation_count") != 81
            or result.get("route_terminal") not in AUTHORITY_TERMINALS
            or type(result.get("residual_mixed_signal")) is not bool
            or (
                result.get("residual_mixed_signal") is True
                and result.get("route_terminal") != "CONSTRAINT_OR_DATA_ISSUE"
            )
        ):
            raise DiagnosticArchiveError("formal_result_invalid")
        value = {
            "schema": AUTHORITY_SCHEMA,
            "run_id": self.run_id,
            "freeze_sha256": _sha(freeze),
            "result_sha256": _sha(result),
            "route_terminal": result["route_terminal"],
        }
        existing = self.load_authority()
        if existing is not None:
            if existing != value:
                raise DiagnosticArchiveError("formal_result_already_authoritative")
            return self.authority_path
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.authority_path, flags, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(_pretty(value))
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            if self.load_authority() != value:
                raise DiagnosticArchiveError(
                    "formal_result_already_authoritative"
                ) from exc
        return self.authority_path


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "AUTHORITY_SCHEMA",
    "RECEIPT_SCHEMA",
    "RUN_ID",
    "TERMINAL_SCHEMA",
    "DiagnosticArchive",
    "DiagnosticArchiveError",
]
