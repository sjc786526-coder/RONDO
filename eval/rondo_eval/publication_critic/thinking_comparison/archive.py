"""Write-once receipts and terminals for Plan 101. No route authority."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..write_once import WriteOnceError, WriteOnceNamespace

RECEIPT_SCHEMA = "rondo-publication-critic-plan101-attempt-receipt@v1"
TERMINAL_SCHEMA = "rondo-publication-critic-plan101-terminal-observation@v1"
RUN_ID = re.compile(
    r"plan101-(commissioning|formal)-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}\Z"
)
RUN_INDEX_NAME = "run-index.json"


class ComparisonArchiveError(RuntimeError):
    """The Plan 101 ignored namespace is unsafe, incomplete, or drifted."""


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
        raise ComparisonArchiveError("logical_key_invalid")
    return hashlib.sha256(logical_key.encode("utf-8")).hexdigest()


class ComparisonArchive:
    """One commissioning/formal run with resumable receipts and write-once terminals."""

    def __init__(self, runs_root: Path, run_id: str, mode: str) -> None:
        match = RUN_ID.fullmatch(run_id)
        if match is None or match.group(1) != mode:
            raise ComparisonArchiveError("run_identity_invalid")
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
            raise ComparisonArchiveError("run_identity_invalid") from exc

    @property
    def path(self) -> Path:
        return self._namespace.path

    def write_bytes(self, name: str, value: bytes) -> Path:
        try:
            return self._namespace.write_bytes(name, value)
        except WriteOnceError as exc:
            raise ComparisonArchiveError("write_failed") from exc

    def bind_json(self, name: str, value: Mapping[str, Any]) -> Path:
        body = _pretty(value)
        destination = self.path / name
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise ComparisonArchiveError("binding_unsafe")
            if destination.read_bytes() != body:
                raise ComparisonArchiveError("binding_drifted")
            return destination
        return self.write_bytes(name, body)

    def start(self, freeze: Mapping[str, Any]) -> "ComparisonArchive":
        try:
            self._namespace.create()
        except WriteOnceError as exc:
            raise ComparisonArchiveError("namespace_not_empty") from exc
        self.bind_json("freeze.json", freeze)
        return self

    def resume(self, freeze: Mapping[str, Any]) -> "ComparisonArchive":
        if (
            self.runs_root.is_symlink()
            or not self.runs_root.is_dir()
            or self.path.is_symlink()
            or not self.path.is_dir()
        ):
            raise ComparisonArchiveError("namespace_missing_or_unsafe")
        self.bind_json("freeze.json", freeze)
        return self

    def reopen_read_only(self, freeze: Mapping[str, Any]) -> "ComparisonArchive":
        freeze_path = self.path / "freeze.json"
        if (
            self.runs_root.is_symlink()
            or not self.runs_root.is_dir()
            or self.path.is_symlink()
            or not self.path.is_dir()
            or freeze_path.is_symlink()
            or not freeze_path.is_file()
        ):
            raise ComparisonArchiveError("namespace_missing_or_unsafe")
        try:
            existing = freeze_path.read_bytes()
        except OSError as exc:
            raise ComparisonArchiveError("binding_unreadable") from exc
        if existing != _pretty(freeze):
            raise ComparisonArchiveError("freeze_binding_drifted")
        return self

    def _receipt_paths(self, logical_key: str) -> list[Path]:
        digest = _logical_digest(logical_key)
        return sorted(
            path
            for path in self.path.glob(f"receipt-{digest}-*.json")
            if path.is_file() and not path.is_symlink()
        )

    def write_receipt(self, logical_key: str, value: Mapping[str, Any]) -> Path:
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != RECEIPT_SCHEMA
            or value.get("logical_key") != logical_key
        ):
            raise ComparisonArchiveError("receipt_invalid")
        ordinal = len(self._receipt_paths(logical_key)) + 1
        name = f"receipt-{_logical_digest(logical_key)}-{ordinal:04d}.json"
        return self.write_bytes(name, _pretty(value))

    def load_receipts(self, logical_key: str) -> tuple[dict[str, Any], ...]:
        rows: list[dict[str, Any]] = []
        for path in self._receipt_paths(logical_key):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ComparisonArchiveError("receipt_unreadable") from exc
            if (
                not isinstance(value, dict)
                or value.get("schema") != RECEIPT_SCHEMA
                or value.get("logical_key") != logical_key
            ):
                raise ComparisonArchiveError("receipt_invalid")
            rows.append(value)
        return tuple(rows)

    def _terminal_path(self, logical_key: str) -> Path:
        return self.path / f"terminal-{_logical_digest(logical_key)}.json"

    def load_terminal(self, logical_key: str) -> dict[str, Any] | None:
        path = self._terminal_path(logical_key)
        if not path.exists() and not path.is_symlink():
            return None
        if path.is_symlink() or not path.is_file():
            raise ComparisonArchiveError("terminal_unsafe")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ComparisonArchiveError("terminal_unreadable") from exc
        if (
            not isinstance(value, dict)
            or value.get("schema") != TERMINAL_SCHEMA
            or value.get("logical_key") != logical_key
        ):
            raise ComparisonArchiveError("terminal_invalid")
        return value

    def write_terminal(self, logical_key: str, value: Mapping[str, Any]) -> Path:
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != TERMINAL_SCHEMA
            or value.get("logical_key") != logical_key
        ):
            raise ComparisonArchiveError("terminal_invalid")
        path = self._terminal_path(logical_key)
        body = _pretty(value)
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise ComparisonArchiveError("terminal_unsafe")
            if path.read_bytes() != body:
                raise ComparisonArchiveError("terminal_drifted")
            return path
        return self.write_bytes(path.name, body)

    def list_run_ids(self) -> tuple[str, ...]:
        if self.runs_root.is_symlink() or not self.runs_root.is_dir():
            return ()
        return tuple(
            sorted(
                path.name
                for path in self.runs_root.iterdir()
                if path.is_dir()
                and not path.is_symlink()
                and RUN_ID.fullmatch(path.name)
            )
        )

    def record_run_index(self, entries: Mapping[str, Any]) -> Path:
        return self.bind_json(RUN_INDEX_NAME, entries)
