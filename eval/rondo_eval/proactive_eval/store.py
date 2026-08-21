"""Ignored, body-free rehearsal archive and idempotent resume state."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_TERMINAL_OUTCOMES = {"completed", "task_failed", "product_failed"}
_OUTCOMES = _TERMINAL_OUTCOMES | {"infra_failed"}
_RECORD_KEYS = {
    "schema_version",
    "evidence_kind",
    "identity_class",
    "lock_id",
    "lock_sha256",
    "policy_sha256",
    "taskset_sha256",
    "phase",
    "pair_id",
    "slot_id",
    "run_id",
    "attempt",
    "task_id",
    "side",
    "product",
    "outcome",
    "terminal",
    "counts_as_effective",
    "cost_usd",
    "trace_status",
    "team_view_sha256",
    "team_report_sha256",
    "reason_code",
}
_FORBIDDEN_KEYS = {
    "prompt",
    "response",
    "reasoning",
    "message",
    "command",
    "stdout",
    "stderr",
    "secret",
    "api_key",
    "raw_trace",
    "fact_body",
    "tool_body",
    "command_output",
    "tool_output",
}


class StoreError(ValueError):
    """Raised rather than guessing about an unsafe or drifting resume state."""


class RehearsalStore:
    def __init__(
        self,
        common_root: Path,
        namespace: str,
        *,
        ignored_root: str = "eval-data/plan-049",
        max_infra_attempts_per_slot: int | None = 5,
        max_infra_attempts_total: int | None = 40,
    ) -> None:
        if not _NAMESPACE.fullmatch(namespace):
            raise StoreError("Plan 049 namespace is invalid")
        common = Path(common_root).resolve()
        relative = Path(ignored_root)
        if (
            relative.is_absolute()
            or not relative.parts
            or relative.parts[0] != "eval-data"
            or ".." in relative.parts
        ):
            raise StoreError("campaign ignored root is invalid")
        for value, label in (
            (max_infra_attempts_per_slot, "slot infra attempt limit"),
            (max_infra_attempts_total, "global infra attempt limit"),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise StoreError(f"campaign {label} is invalid")
        self._max_infra_attempts_per_slot = max_infra_attempts_per_slot
        self._max_infra_attempts_total = max_infra_attempts_total
        self.root = common / relative / "rehearsal" / namespace
        self.archive_path = self.root / "records.jsonl"
        self.ledger_path = self.root / "rehearsal-ledger.json"
        self.aggregate_path = self.root / "aggregate.json"
        self.runs_root = self.root / "runs"
        self._prepare_root(common)

    def records(self) -> tuple[dict[str, Any], ...]:
        if not self.archive_path.exists():
            return ()
        _regular_file(self.archive_path, "archive")
        result: list[dict[str, Any]] = []
        try:
            lines = self.archive_path.read_text("utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise StoreError("Plan 049 archive is unreadable") from exc
        for line in lines:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise StoreError("Plan 049 archive is invalid JSONL") from exc
            validate_record(value)
            result.append(value)
        _validate_archive_uniqueness(result)
        return tuple(result)

    def terminal_slots(self) -> frozenset[str]:
        return frozenset(
            record["slot_id"] for record in self.records() if record["terminal"] is True
        )

    def claim(self, slot_id: str, run_id_for_attempt) -> tuple[int, str, str] | None:
        records = [record for record in self.records() if record["slot_id"] == slot_id]
        terminals = [record for record in records if record["terminal"] is True]
        if terminals:
            ledger = self._load_ledger()
            claim = ledger["claims"].get(slot_id)
            terminal = terminals[0]
            if (
                not isinstance(claim, dict)
                or claim.get("run_id") != terminal["run_id"]
                or claim.get("attempt") != terminal["attempt"]
            ):
                raise StoreError("terminal archive and rehearsal ledger disagree")
            if claim.get("status") in {"claimed", "executing"}:
                claim["status"] = "settled"
                claim["outcome"] = terminal["outcome"]
                self._write_json(self.ledger_path, ledger)
            elif claim.get("status") != "settled" or claim.get("outcome") != terminal["outcome"]:
                raise StoreError("terminal archive settlement differs")
            return None
        ledger = self._load_ledger()
        claim = ledger["claims"].get(slot_id)
        if isinstance(claim, dict) and claim.get("status") in {"claimed", "executing"}:
            return int(claim["attempt"]), str(claim["run_id"]), str(claim["status"])
        attempted = max((int(record["attempt"]) for record in records), default=0)
        if (
            self._max_infra_attempts_per_slot is not None
            and attempted >= self._max_infra_attempts_per_slot
        ):
            raise StoreError("Plan 049 slot exhausted its infra attempt limit")
        global_infra = sum(record["outcome"] == "infra_failed" for record in self.records())
        if (
            self._max_infra_attempts_total is not None
            and global_infra >= self._max_infra_attempts_total
        ):
            raise StoreError("Plan 049 exhausted its global infra attempt limit")
        attempt = attempted + 1
        run_id = run_id_for_attempt(attempt)
        ledger["claims"][slot_id] = {
            "attempt": attempt,
            "run_id": run_id,
            "status": "claimed",
            "cost_usd": "0.00",
        }
        self._write_json(self.ledger_path, ledger)
        return attempt, run_id, "claimed"

    def mark_execution_started(self, slot_id: str) -> None:
        ledger = self._load_ledger()
        claim = ledger["claims"].get(slot_id)
        if not isinstance(claim, dict) or claim.get("status") != "claimed":
            raise StoreError("Plan 049 slot cannot start execution")
        claim["status"] = "executing"
        self._write_json(self.ledger_path, ledger)

    def settle(self, slot_id: str, *, outcome: str) -> None:
        if outcome not in _OUTCOMES:
            raise StoreError("Plan 049 outcome is invalid")
        ledger = self._load_ledger()
        claim = ledger["claims"].get(slot_id)
        if not isinstance(claim, dict) or claim.get("status") not in {
            "claimed",
            "executing",
        }:
            raise StoreError("Plan 049 slot has no unsettled claim")
        claim["status"] = "settled"
        claim["outcome"] = outcome
        self._write_json(self.ledger_path, ledger)

    def append(self, record: Mapping[str, Any]) -> None:
        value = dict(record)
        validate_record(value)
        existing = self.records()
        for row in existing:
            if row["run_id"] == value["run_id"]:
                if row == value:
                    return
                raise StoreError("Plan 049 run identity drifted on resume")
        if value["terminal"] and any(
            row["slot_id"] == value["slot_id"] and row["terminal"] for row in existing
        ):
            raise StoreError("Plan 049 slot already has a trusted terminal record")
        payload = _canonical(value) + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.archive_path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def write_aggregate(self, value: Mapping[str, Any]) -> None:
        assert_body_free(value)
        self._write_json(self.aggregate_path, value)

    def _load_ledger(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return {
                "schema_version": 1,
                "evidence_kind": "rehearsal",
                "identity_class": "rehearsal",
                "cost_usd": "0.00",
                "claims": {},
            }
        _regular_file(self.ledger_path, "ledger")
        try:
            value = json.loads(self.ledger_path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise StoreError("Plan 049 rehearsal ledger is unreadable") from exc
        if (
            not isinstance(value, dict)
            or value.get("evidence_kind") != "rehearsal"
            or value.get("identity_class") != "rehearsal"
            or value.get("cost_usd") != "0.00"
            or not isinstance(value.get("claims"), dict)
        ):
            raise StoreError("Plan 049 rehearsal ledger identity differs")
        assert_body_free(value)
        return value

    def _write_json(self, path: Path, value: Mapping[str, Any]) -> None:
        assert_body_free(value)
        if path.exists():
            _regular_file(path, "state file")
        temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        if temporary.exists():
            raise StoreError("Plan 049 temporary state path already exists")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            os.write(descriptor, _canonical(dict(value)) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)

    def _prepare_root(self, common: Path) -> None:
        eval_data = common / "eval-data"
        if eval_data.exists() and (eval_data.is_symlink() or not eval_data.is_dir()):
            raise StoreError("common eval-data root is unsafe")
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.runs_root.mkdir(mode=0o700, exist_ok=True)
        if self.root.is_symlink() or not self.root.resolve().is_relative_to(eval_data.resolve()):
            raise StoreError("Plan 049 state escaped eval-data")


def validate_record(value: object) -> None:
    if not isinstance(value, dict) or set(value) != _RECORD_KEYS:
        raise StoreError("Plan 049 archive record has unknown or missing fields")
    assert_body_free(value)
    if (
        value.get("schema_version") != 1
        or value.get("evidence_kind") != "rehearsal"
        or value.get("identity_class") != "rehearsal"
        or value.get("cost_usd") != "0.00"
        or value.get("side") not in {"codex", "rondo"}
        or value.get("product") != (None if value.get("side") == "codex" else "rondo-multi")
        or value.get("outcome") not in _OUTCOMES
        or not isinstance(value.get("attempt"), int)
        or value["attempt"] < 1
    ):
        raise StoreError("Plan 049 archive record identity is invalid")
    terminal = value["outcome"] in _TERMINAL_OUTCOMES
    if value.get("terminal") is not terminal or value.get("counts_as_effective") is not terminal:
        raise StoreError("Plan 049 archive outcome classification differs")
    if terminal and value.get("trace_status") not in {
        "available",
        "partial",
        "synthetic_fixture",
    }:
        raise StoreError("valid terminal record lacks consumable trace evidence")
    if not terminal and value.get("trace_status") not in {"missing", "partial"}:
        raise StoreError("infra record has an invalid trace classification")


def assert_body_free(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower() if isinstance(key, str) else ""
            if not isinstance(key, str) or normalized in _FORBIDDEN_KEYS or normalized.endswith(
                ("_body", "_content", "_text", "_preview", "_message")
            ):
                raise StoreError("body-bearing field is forbidden")
            assert_body_free(item)
    elif isinstance(value, list):
        for item in value:
            assert_body_free(item)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise StoreError("body-free artifact contains an unsupported value")


def _validate_archive_uniqueness(records: list[dict[str, Any]]) -> None:
    run_ids: set[str] = set()
    terminal_slots: set[str] = set()
    for record in records:
        if record["run_id"] in run_ids:
            raise StoreError("Plan 049 archive repeats a run identity")
        run_ids.add(record["run_id"])
        if record["terminal"]:
            if record["slot_id"] in terminal_slots:
                raise StoreError("Plan 049 archive repeats a terminal slot")
            terminal_slots.add(record["slot_id"])


def _regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise StoreError(f"Plan 049 {label} is unsafe")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
