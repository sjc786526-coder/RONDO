"""Blind Plan 100 batch runner, Rust adapter, recovery, and recomputation."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from ..identity import canonical_json_bytes, sha256_bytes
from .archive import (
    RECEIPT_SCHEMA,
    TERMINAL_SCHEMA,
    DiagnosticArchive,
)
from .contract import (
    DiagnosticTask,
    DirectOutput,
    OutputContractError,
    ScalarOutput,
    StructuredOutput,
    parse_output,
)
from .cost import (
    DiagnosticCostError,
    Plan100BudgetLedger,
    settle_attempt,
    task_budget_summary,
    worst_case_reservation_rmb,
)
from .freeze import (
    COMMISSIONING_BINDING_SCHEMA,
    COMMISSIONING_RESULT_SCHEMA,
    REQUESTED_MODEL,
    freeze_sha256,
    validate_freeze,
)
from .metrics import (
    decide_route_with_metadata,
    direct_metrics,
    scalar_metrics,
    structured_metrics,
)
from .release import PublicItem, ValidationRelease

RESULT_SCHEMA = "rondo-publication-critic-plan100-diagnostic-result@v1"
COMMISSIONING_SCHEMA = COMMISSIONING_RESULT_SCHEMA
TRACKED_RESULT_SCHEMA = "rondo-publication-critic-plan100-diagnostic-summary@v1"
DETAILED_RESULT_SCHEMA = "rondo-publication-critic-plan100-diagnostic-detail@v1"
_MAX_STDOUT_BYTES = 64 * 1024
_ATTEMPT_MARKER = re.compile(
    rb"publication_critic_cloud_attempt attempt=([0-9]+) requested_at_unix_ms=([0-9]+)(?:\s|$)"
)
_LEGACY_ATTEMPT_MARKER = re.compile(
    rb"publication_critic_cloud_attempt attempt=([0-9]+)(?:\s|$)"
)


class DiagnosticRunnerError(RuntimeError):
    """A runner, evaluator, archive, or recomputation invariant failed."""


class AmbiguousAttemptError(DiagnosticRunnerError):
    """A reserved action may have reached the provider but has no durable receipt."""


class DiagnosticEvaluator(Protocol):
    def evaluate(
        self, task: DiagnosticTask, packet: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Evaluate only one task and public packet; candidate identity stays local."""


class TokenRecounter(Protocol):
    def recount(
        self,
        task: DiagnosticTask,
        packet: Mapping[str, Any],
        response_text: str | None,
    ) -> Mapping[str, Any] | None:
        """Return a frozen token recount or None only after recount is actually unavailable."""


@dataclass(frozen=True)
class CommandTokenRecounter:
    """Bounded offline adapter for the B1-calibrated official token counter."""

    command: tuple[str, ...]
    identity_sha256: str
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        if (
            not self.command
            or len(self.identity_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.identity_sha256
            )
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise DiagnosticRunnerError("recount_configuration_invalid")

    def recount(
        self,
        task: DiagnosticTask,
        packet: Mapping[str, Any],
        response_text: str | None,
    ) -> Mapping[str, Any] | None:
        request = {
            "schema": "rondo-publication-critic-plan100-token-recount-request@v1",
            "task": task.value,
            "packet": dict(packet),
            "response_text": response_text,
        }
        try:
            completed = subprocess.run(
                self.command,
                input=canonical_json_bytes(request),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=self.timeout_seconds,
                check=False,
                env={
                    name: os.environ[name]
                    for name in ("PATH", "LANG", "LC_ALL")
                    if name in os.environ
                },
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0 or len(completed.stdout) > 4096:
            return None
        try:
            value = _strict_json(completed.stdout)
        except DiagnosticRunnerError:
            return None
        if set(value) != {"prompt_tokens", "completion_tokens", "method"}:
            return None
        prompt = value.get("prompt_tokens")
        completion = value.get("completion_tokens")
        method = value.get("method")
        if (
            type(prompt) is not int
            or prompt < 0
            or type(completion) is not int
            or completion < 0
            or not isinstance(method, str)
            or not method
        ):
            return None
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "method": method,
            "identity_sha256": self.identity_sha256,
        }


@dataclass(frozen=True)
class RustSubprocessEvaluator:
    """One-shot Rust adapter. Only the selected task and packet enter the child."""

    executable: Path
    arguments: tuple[str, ...]
    credential_env: Mapping[str, str]
    timeout_seconds: float
    recounter: TokenRecounter

    _SYSTEM_ENV = (
        "PATH",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    )

    def __post_init__(self) -> None:
        if (
            self.executable.is_symlink()
            or not self.executable.is_file()
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or self.recounter is None
        ):
            raise DiagnosticRunnerError("subprocess_configuration_invalid")

    def _environment(self) -> dict[str, str]:
        environment = {
            name: os.environ[name] for name in self._SYSTEM_ENV if os.environ.get(name)
        }
        for name, value in self.credential_env.items():
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(value, str)
                or not value
            ):
                raise DiagnosticRunnerError("subprocess_credential_invalid")
            environment[name] = value
        return environment

    def evaluate(
        self, task: DiagnosticTask, packet: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        started_wall = datetime.now(timezone.utc)
        started = time.perf_counter()
        command = [
            str(self.executable),
            *self.arguments,
            "--task",
            {
                DiagnosticTask.SCALAR: "scalar",
                DiagnosticTask.DIRECT: "direct-gate",
                DiagnosticTask.STRUCTURED: "five-dimension",
            }[task],
        ]
        try:
            completed = subprocess.run(
                command,
                input=canonical_json_bytes(dict(packet)),
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                env=self._environment(),
            )
        except subprocess.TimeoutExpired as exc:
            stderr = _body_bytes(exc.stderr)
            times = _attempt_times(stderr, started_wall, minimum_one=True)
            return _adapter_failure(
                task,
                packet,
                self.recounter,
                times,
                "subprocess_timeout",
                time.perf_counter() - started,
            )
        stderr = completed.stderr
        times = _attempt_times(
            stderr, started_wall, minimum_one=completed.returncode != 0
        )
        if completed.returncode != 0 or len(completed.stdout) > _MAX_STDOUT_BYTES:
            return _adapter_failure(
                task,
                packet,
                self.recounter,
                times,
                "subprocess_failed",
                time.perf_counter() - started,
            )
        try:
            value = _strict_json(completed.stdout)
            return _normalize_rust_observation(task, packet, value, self.recounter)
        except DiagnosticRunnerError:
            return _adapter_failure(
                task,
                packet,
                self.recounter,
                times or [started_wall],
                "subprocess_output_invalid",
                time.perf_counter() - started,
            )


def _body_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    return value if isinstance(value, bytes) else value.encode("utf-8", errors="ignore")


def _attempt_times(
    stderr: bytes,
    started: datetime,
    *,
    minimum_one: bool,
) -> list[datetime]:
    exact = [
        (int(match.group(1)), int(match.group(2)))
        for match in _ATTEMPT_MARKER.finditer(stderr)
    ]
    if exact:
        if [number for number, _ in exact] != list(range(1, len(exact) + 1)):
            raise DiagnosticRunnerError("subprocess_attempt_markers_invalid")
        return [
            started
            if milliseconds <= 0
            else datetime.fromtimestamp(milliseconds / 1000, timezone.utc)
            for _, milliseconds in exact
        ]
    legacy = [int(match.group(1)) for match in _LEGACY_ATTEMPT_MARKER.finditer(stderr)]
    count = max(legacy, default=1 if minimum_one else 0)
    return [started for _ in range(count)]


def _adapter_failure(
    task: DiagnosticTask,
    packet: Mapping[str, Any],
    recounter: TokenRecounter,
    requested_at: Sequence[datetime],
    code: str,
    elapsed_seconds: float,
) -> dict[str, Any]:
    attempts = _settlement_attempts(task, packet, recounter, requested_at, None, None)
    return {
        "requested_model": REQUESTED_MODEL,
        "served_model": None,
        "response_text": None,
        "attempts": attempts,
        "elapsed_ms": max(0, round(elapsed_seconds * 1000)),
        "outcome": {"type": "technical_failure", "kind": code, "http_status": None},
    }


def _normalize_rust_observation(
    task: DiagnosticTask,
    packet: Mapping[str, Any],
    value: Mapping[str, Any],
    recounter: TokenRecounter,
) -> dict[str, Any]:
    expected = {
        "task",
        "requested_model",
        "served_model",
        "response_text",
        "output",
        "local_verdict",
        "attempts",
        "attempt_requested_at_unix_ms",
        "elapsed_ms",
        "usage",
        "outcome",
    }
    if set(value) != expected:
        raise DiagnosticRunnerError("subprocess_observation_fields_invalid")
    rust_task = {
        DiagnosticTask.SCALAR: "scalar",
        DiagnosticTask.DIRECT: "direct_gate",
        DiagnosticTask.STRUCTURED: "five_dimension",
    }[task]
    served = value.get("served_model")
    response_text = value.get("response_text")
    count = value.get("attempts")
    timestamps = value.get("attempt_requested_at_unix_ms")
    elapsed = value.get("elapsed_ms")
    if (
        value.get("task") != rust_task
        or value.get("requested_model") != REQUESTED_MODEL
        or (served is not None and not isinstance(served, str))
        or (response_text is not None and not isinstance(response_text, str))
        or type(count) is not int
        or not 1 <= count <= 2
        or not isinstance(timestamps, list)
        or len(timestamps) != count
        or any(type(item) is not int or item <= 0 for item in timestamps)
        or type(elapsed) is not int
        or elapsed < 0
    ):
        raise DiagnosticRunnerError("subprocess_observation_invalid")
    requested_at = [
        datetime.fromtimestamp(milliseconds / 1000, timezone.utc)
        for milliseconds in timestamps
    ]
    usage = _normalize_usage(value.get("usage"))
    outcome = value.get("outcome")
    if not isinstance(outcome, Mapping):
        raise DiagnosticRunnerError("subprocess_outcome_invalid")
    if outcome == {"type": "success"}:
        if response_text is None:
            raise DiagnosticRunnerError("subprocess_success_invalid")
        try:
            parsed = parse_output(task, response_text)
        except OutputContractError as exc:
            raise DiagnosticRunnerError("subprocess_success_contract_mismatch") from exc
        if value.get("output") != _rust_output(task, parsed):
            raise DiagnosticRunnerError("subprocess_projection_mismatch")
        expected_local = (
            parsed.verdict if isinstance(parsed, StructuredOutput) else None
        )
        if value.get("local_verdict") != expected_local:
            raise DiagnosticRunnerError("subprocess_local_gate_mismatch")
        normalized_outcome = {"type": "success"}
    elif (
        set(outcome) == {"type", "kind", "http_status"}
        and outcome.get("type") == "failure"
    ):
        kind = outcome.get("kind")
        status = outcome.get("http_status")
        if not isinstance(kind, str) or (
            status is not None and type(status) is not int
        ):
            raise DiagnosticRunnerError("subprocess_failure_invalid")
        if kind == "output_contract_violation":
            if response_text is None:
                raise DiagnosticRunnerError("subprocess_contract_failure_missing_body")
            try:
                parse_output(task, response_text)
            except OutputContractError:
                pass
            else:
                raise DiagnosticRunnerError("subprocess_contract_failure_mismatch")
            normalized_outcome = {
                "type": "output_contract_failure",
                "kind": kind,
                "http_status": status,
            }
        else:
            normalized_outcome = {
                "type": "technical_failure",
                "kind": kind,
                "http_status": status,
            }
        if value.get("output") is not None or value.get("local_verdict") is not None:
            raise DiagnosticRunnerError("subprocess_failure_projection_present")
    else:
        raise DiagnosticRunnerError("subprocess_outcome_invalid")
    attempts = _settlement_attempts(
        task,
        packet,
        recounter,
        requested_at,
        usage,
        response_text,
    )
    return {
        "requested_model": REQUESTED_MODEL,
        "served_model": served,
        "response_text": response_text,
        "attempts": attempts,
        "elapsed_ms": elapsed,
        "outcome": normalized_outcome,
    }


def _strict_json(body: bytes) -> Mapping[str, Any]:
    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise DiagnosticRunnerError("subprocess_duplicate_json_key")
            result[key] = value
        return result

    def reject(value: str) -> None:
        raise DiagnosticRunnerError(f"subprocess_non_finite_json:{value}")

    try:
        value = json.loads(body, object_pairs_hook=pairs, parse_constant=reject)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise DiagnosticRunnerError("subprocess_json_invalid") from exc
    if not isinstance(value, Mapping):
        raise DiagnosticRunnerError("subprocess_json_invalid")
    return value


def _normalize_usage(value: Any) -> dict[str, int | None] | None:
    if value is None:
        return None
    expected = {
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        return None
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    if (
        type(prompt) is not int
        or prompt < 0
        or type(completion) is not int
        or completion < 0
    ):
        return None
    result: dict[str, int | None] = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "prompt_cache_hit_tokens": value.get("prompt_cache_hit_tokens"),
        "prompt_cache_miss_tokens": value.get("prompt_cache_miss_tokens"),
    }
    for name in ("prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
        item = result[name]
        if item is not None and (type(item) is not int or item < 0):
            return None
    return result


def _settlement_attempts(
    task: DiagnosticTask,
    packet: Mapping[str, Any],
    recounter: TokenRecounter,
    requested_at: Sequence[datetime],
    final_usage: Mapping[str, Any] | None,
    response_text: str | None,
) -> list[dict[str, Any]]:
    attempts = []
    for index, instant in enumerate(requested_at, start=1):
        usage = final_usage if index == len(requested_at) else None
        attempt_response = response_text if index == len(requested_at) else None
        recount = (
            None
            if usage is not None or attempt_response is None
            else recounter.recount(
                task,
                packet,
                attempt_response,
            )
        )
        attempts.append(
            {
                "attempt": index,
                "requested_at": instant.isoformat(),
                "usage": None if usage is None else dict(usage),
                "recount": None if recount is None else dict(recount),
                "explicitly_unbilled": False,
            }
        )
    return attempts


def _rust_output(task: DiagnosticTask, parsed: Any) -> dict[str, Any]:
    if task is DiagnosticTask.SCALAR and isinstance(parsed, ScalarOutput):
        return {"type": "scalar", "quality": parsed.score}
    if task is DiagnosticTask.DIRECT and isinstance(parsed, DirectOutput):
        return {"type": "direct_gate", "verdict": parsed.verdict}
    if task is DiagnosticTask.STRUCTURED and isinstance(parsed, StructuredOutput):
        return {"type": "five_dimension", "decisions": dict(parsed.decisions)}
    raise DiagnosticRunnerError("subprocess_projection_task_mismatch")


def run_batch(
    freeze_value: Mapping[str, Any],
    items: Sequence[PublicItem],
    *,
    archive: DiagnosticArchive,
    ledger: Plan100BudgetLedger,
    evaluator: DiagnosticEvaluator,
    allow_technical_retry: bool = False,
) -> dict[str, Any]:
    """Run in arm-major order, resuming only durable work and never selecting replacements."""

    freeze = validate_freeze(freeze_value)
    if archive.mode != freeze["mode"] or archive.run_id != freeze["run_id"]:
        raise DiagnosticRunnerError("runner_freeze_archive_mismatch")
    expected_items = 3 if archive.mode == "commissioning" else 27
    if (
        len(items) != expected_items
        or len({item.candidate_id for item in items}) != expected_items
    ):
        raise DiagnosticRunnerError("runner_item_cohort_invalid")
    reserve = worst_case_reservation_rmb(
        max_attempts=freeze["request"]["max_attempts"],
        max_prompt_tokens=16_384,
        max_completion_tokens=freeze["request"]["max_output_tokens"],
    )
    completed: list[dict[str, Any]] = []
    stopped: dict[str, Any] | None = None
    for task in DiagnosticTask:
        for item in items:
            logical_key = f"{task.value}:{item.candidate_id}"
            terminal = archive.load_terminal(logical_key)
            if terminal is not None:
                _validate_terminal(terminal, freeze, item, task)
                completed.append(terminal)
                continue
            receipts = archive.load_receipts(logical_key)
            if receipts:
                for receipt in receipts:
                    _validate_receipt(receipt, freeze, item, task)
                    _settle_or_verify(ledger, receipt)
                prior = receipts[-1]
                if prior["observation"]["outcome"]["type"] != "technical_failure":
                    terminal = _terminal_from_receipt(prior)
                    archive.write_terminal(logical_key, terminal)
                    completed.append(terminal)
                    continue
                if not allow_technical_retry:
                    stopped = {
                        "reason": "technical_failure",
                        "logical_key": logical_key,
                    }
                    break
            ordinal = len(receipts) + 1
            budget_key = f"{archive.run_id}:{logical_key}:{ordinal}"
            _reserve_or_ambiguous(ledger, budget_key, reserve)
            # Materialize exclusively from the frozen public bytes. This both strips immutable
            # loader wrappers and makes it impossible for local supervision to enter the call.
            public_packet = json.loads(item.packet_bytes)
            observation = _normalize_evaluator_observation(
                task,
                evaluator.evaluate(task, public_packet),
            )
            receipt = {
                "schema": RECEIPT_SCHEMA,
                "logical_key": logical_key,
                "freeze_sha256": freeze_sha256(freeze),
                "arm": task.value,
                "candidate_id": item.candidate_id,
                "packet_sha256": sha256_bytes(item.packet_bytes),
                "budget_key": budget_key,
                "observation": observation,
            }
            archive.write_receipt(logical_key, receipt)
            ledger.settle(budget_key, observation["attempts"])
            if observation["outcome"]["type"] == "technical_failure":
                stopped = {"reason": "technical_failure", "logical_key": logical_key}
                break
            terminal = _terminal_from_receipt(receipt)
            archive.write_terminal(logical_key, terminal)
            completed.append(terminal)
        if stopped is not None:
            break
    successful = sum(row["status"] == "success" for row in completed)
    parse_failures = len(completed) - successful
    terminals_complete = len(completed) == expected_items * 3 and stopped is None
    return {
        "mode": archive.mode,
        "run_id": archive.run_id,
        "terminal_observation_count": len(completed),
        "expected_terminal_observation_count": expected_items * 3,
        "successful_terminal_observation_count": successful,
        "parse_failure_count": parse_failures,
        "complete": terminals_complete
        and (archive.mode == "formal" or parse_failures == 0),
        "stopped": stopped,
        "ledger": ledger.snapshot(),
    }


def _normalize_evaluator_observation(
    task: DiagnosticTask, value: Any
) -> dict[str, Any]:
    expected = {
        "requested_model",
        "served_model",
        "response_text",
        "attempts",
        "elapsed_ms",
        "outcome",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise DiagnosticRunnerError("evaluator_observation_fields_invalid")
    if value.get("requested_model") != REQUESTED_MODEL:
        raise DiagnosticRunnerError("evaluator_requested_model_invalid")
    served = value.get("served_model")
    response = value.get("response_text")
    attempts = value.get("attempts")
    elapsed = value.get("elapsed_ms")
    outcome = value.get("outcome")
    if (
        (served is not None and not isinstance(served, str))
        or (response is not None and not isinstance(response, str))
        or not isinstance(attempts, list)
        or not 1 <= len(attempts) <= 2
        or type(elapsed) is not int
        or elapsed < 0
        or not isinstance(outcome, Mapping)
    ):
        raise DiagnosticRunnerError("evaluator_observation_invalid")
    kind = outcome.get("type")
    parsed: Any = None
    parse_code: str | None = None
    if kind == "success":
        if (
            outcome != {"type": "success"}
            or response is None
            or served != REQUESTED_MODEL
        ):
            raise DiagnosticRunnerError("evaluator_success_invalid")
        try:
            parsed = parse_output(task, response)
        except OutputContractError as exc:
            raise DiagnosticRunnerError("evaluator_success_contract_mismatch") from exc
    elif kind == "output_contract_failure":
        if (
            set(outcome) != {"type", "kind", "http_status"}
            or outcome.get("kind") != "output_contract_violation"
            or outcome.get("http_status") is not None
            or response is None
            or served != REQUESTED_MODEL
        ):
            raise DiagnosticRunnerError("evaluator_contract_failure_invalid")
        try:
            parse_output(task, response)
        except OutputContractError as exc:
            parse_code = exc.code
        else:
            raise DiagnosticRunnerError("evaluator_contract_failure_mismatch")
    elif kind == "technical_failure":
        failure_kind = outcome.get("kind")
        http_status = outcome.get("http_status")
        if (
            set(outcome) != {"type", "kind", "http_status"}
            or not isinstance(failure_kind, str)
            or not failure_kind
            or len(failure_kind) > 128
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                for character in failure_kind
            )
            or (http_status is not None and type(http_status) is not int)
        ):
            raise DiagnosticRunnerError("evaluator_technical_failure_invalid")
    else:
        raise DiagnosticRunnerError("evaluator_outcome_invalid")
    normalized = {
        "requested_model": REQUESTED_MODEL,
        "served_model": served,
        "response_text": response,
        "attempts": [dict(item) for item in attempts],
        "elapsed_ms": elapsed,
        "outcome": dict(outcome),
        "parsed_output": _parsed_document(parsed),
        "parse_failure_code": parse_code,
    }
    _validate_stored_observation(task, normalized)
    return normalized


def _validate_stored_observation(task: DiagnosticTask, value: Any) -> None:
    expected = {
        "requested_model",
        "served_model",
        "response_text",
        "attempts",
        "elapsed_ms",
        "outcome",
        "parsed_output",
        "parse_failure_code",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise DiagnosticRunnerError("stored_observation_fields_invalid")
    served = value.get("served_model")
    response = value.get("response_text")
    elapsed = value.get("elapsed_ms")
    if (
        value.get("requested_model") != REQUESTED_MODEL
        or (served is not None and not isinstance(served, str))
        or (response is not None and not isinstance(response, str))
        or type(elapsed) is not int
        or elapsed < 0
    ):
        raise DiagnosticRunnerError("stored_observation_invalid")
    attempts = value.get("attempts")
    if not isinstance(attempts, list) or not 1 <= len(attempts) <= 2:
        raise DiagnosticRunnerError("stored_observation_attempts_invalid")
    try:
        settled = [settle_attempt(item) for item in attempts]
    except Exception as exc:  # normalize the separate cost contract at this boundary
        raise DiagnosticRunnerError("stored_observation_attempts_invalid") from exc
    if [item["attempt"] for item in settled] != list(range(1, len(settled) + 1)):
        raise DiagnosticRunnerError("stored_observation_attempts_invalid")
    outcome = value.get("outcome")
    if not isinstance(outcome, Mapping):
        raise DiagnosticRunnerError("stored_observation_outcome_invalid")
    parsed: Any = None
    parse_code: str | None = None
    if outcome.get("type") == "success":
        if (
            outcome != {"type": "success"}
            or not isinstance(response, str)
            or served != REQUESTED_MODEL
        ):
            raise DiagnosticRunnerError("stored_observation_success_invalid")
        try:
            parsed = parse_output(task, response)
        except OutputContractError as exc:
            raise DiagnosticRunnerError("stored_observation_success_invalid") from exc
    elif outcome.get("type") == "output_contract_failure":
        if (
            set(outcome) != {"type", "kind", "http_status"}
            or outcome.get("kind") != "output_contract_violation"
            or outcome.get("http_status") is not None
            or not isinstance(response, str)
            or served != REQUESTED_MODEL
        ):
            raise DiagnosticRunnerError("stored_observation_contract_failure_invalid")
        try:
            parse_output(task, response)
        except OutputContractError as exc:
            parse_code = exc.code
        else:
            raise DiagnosticRunnerError("stored_observation_contract_failure_invalid")
    elif outcome.get("type") == "technical_failure":
        failure_kind = outcome.get("kind")
        http_status = outcome.get("http_status")
        if (
            set(outcome) != {"type", "kind", "http_status"}
            or not isinstance(failure_kind, str)
            or not failure_kind
            or len(failure_kind) > 128
            or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_-"
                for character in failure_kind
            )
            or (http_status is not None and type(http_status) is not int)
        ):
            raise DiagnosticRunnerError("stored_observation_outcome_invalid")
    else:
        raise DiagnosticRunnerError("stored_observation_outcome_invalid")
    if (
        value.get("parsed_output") != _parsed_document(parsed)
        or value.get("parse_failure_code") != parse_code
    ):
        raise DiagnosticRunnerError("stored_observation_projection_invalid")


def _parsed_document(value: Any) -> dict[str, Any] | None:
    if isinstance(value, ScalarOutput):
        return {"quality": value.score}
    if isinstance(value, DirectOutput):
        return {"verdict": value.verdict}
    if isinstance(value, StructuredOutput):
        return {"decisions": dict(value.decisions), "local_verdict": value.verdict}
    return None


def _reserve_or_ambiguous(
    ledger: Plan100BudgetLedger,
    budget_key: str,
    reserve: Decimal,
) -> None:
    try:
        ledger.reserve(budget_key, reserve)
    except DiagnosticCostError as exc:
        if str(exc) == "logical_key_already_reserved":
            raise AmbiguousAttemptError(
                "reserved_action_has_no_durable_receipt"
            ) from exc
        raise


def _settle_or_verify(ledger: Plan100BudgetLedger, receipt: Mapping[str, Any]) -> None:
    key = receipt["budget_key"]
    matches = [
        row for row in ledger.snapshot()["reservations"] if row["logical_key"] == key
    ]
    if len(matches) != 1:
        raise DiagnosticRunnerError("receipt_budget_reservation_missing")
    if matches[0]["state"] == "reserved":
        ledger.settle(key, receipt["observation"]["attempts"])
    else:
        expected = [settle_attempt(item) for item in receipt["observation"]["attempts"]]
        if matches[0]["attempts"] != expected:
            raise DiagnosticRunnerError("receipt_budget_settlement_drifted")


def _validate_receipt(
    value: Mapping[str, Any],
    freeze: Mapping[str, Any],
    item: PublicItem,
    task: DiagnosticTask,
) -> None:
    expected = {
        "schema",
        "logical_key",
        "freeze_sha256",
        "arm",
        "candidate_id",
        "packet_sha256",
        "budget_key",
        "observation",
    }
    logical_key = f"{task.value}:{item.candidate_id}"
    if (
        set(value) != expected
        or value.get("schema") != RECEIPT_SCHEMA
        or value.get("logical_key") != logical_key
        or value.get("freeze_sha256") != freeze_sha256(freeze)
        or value.get("arm") != task.value
        or value.get("candidate_id") != item.candidate_id
        or value.get("packet_sha256") != sha256_bytes(item.packet_bytes)
        or not isinstance(value.get("budget_key"), str)
    ):
        raise DiagnosticRunnerError("receipt_identity_invalid")
    _validate_stored_observation(task, value.get("observation"))


def _terminal_from_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    observation = receipt["observation"]
    outcome = observation["outcome"]["type"]
    if outcome not in {"success", "output_contract_failure"}:
        raise DiagnosticRunnerError("technical_receipt_has_no_quality_terminal")
    return {
        "schema": TERMINAL_SCHEMA,
        "logical_key": receipt["logical_key"],
        "freeze_sha256": receipt["freeze_sha256"],
        "arm": receipt["arm"],
        "candidate_id": receipt["candidate_id"],
        "packet_sha256": receipt["packet_sha256"],
        "status": "success" if outcome == "success" else "parse_failure",
        "parsed_output": observation["parsed_output"],
        "parse_failure_code": observation["parse_failure_code"],
        "requested_model": observation["requested_model"],
        "served_model": observation["served_model"],
        "receipt_sha256": sha256_bytes(canonical_json_bytes(dict(receipt))),
    }


def _validate_terminal(
    value: Mapping[str, Any],
    freeze: Mapping[str, Any],
    item: PublicItem,
    task: DiagnosticTask,
) -> None:
    expected = {
        "schema",
        "logical_key",
        "freeze_sha256",
        "arm",
        "candidate_id",
        "packet_sha256",
        "status",
        "parsed_output",
        "parse_failure_code",
        "requested_model",
        "served_model",
        "receipt_sha256",
    }
    if (
        set(value) != expected
        or value.get("schema") != TERMINAL_SCHEMA
        or value.get("logical_key") != f"{task.value}:{item.candidate_id}"
        or value.get("freeze_sha256") != freeze_sha256(freeze)
        or value.get("arm") != task.value
        or value.get("candidate_id") != item.candidate_id
        or value.get("packet_sha256") != sha256_bytes(item.packet_bytes)
        or value.get("requested_model") != REQUESTED_MODEL
        or value.get("status") not in {"success", "parse_failure"}
    ):
        raise DiagnosticRunnerError("terminal_identity_invalid")


def recompute_commissioning(
    freeze_value: Mapping[str, Any],
    items: Sequence[PublicItem],
    archive: DiagnosticArchive,
    ledger: Plan100BudgetLedger,
    recounter: TokenRecounter,
) -> dict[str, Any]:
    """Prove 9/9 output success and calibrate the frozen counter on usage evidence."""

    freeze = validate_freeze(freeze_value)
    if (
        freeze["mode"] != "commissioning"
        or archive.mode != "commissioning"
        or len(items) != 3
    ):
        raise DiagnosticRunnerError("recompute_requires_commissioning")
    terminal_count = success_count = parse_failures = 0
    usage_present = calibrated = mismatches = unavailable = 0
    for task in DiagnosticTask:
        for item in items:
            logical_key = f"{task.value}:{item.candidate_id}"
            terminal = archive.load_terminal(logical_key)
            if terminal is None:
                continue
            _validate_terminal(terminal, freeze, item, task)
            terminal_count += 1
            if terminal["status"] != "success":
                parse_failures += 1
                continue
            success_count += 1
            matching_receipts = [
                receipt
                for receipt in archive.load_receipts(logical_key)
                if sha256_bytes(canonical_json_bytes(receipt))
                == terminal["receipt_sha256"]
            ]
            if len(matching_receipts) != 1:
                raise DiagnosticRunnerError("terminal_receipt_binding_invalid")
            receipt = matching_receipts[0]
            _validate_receipt(receipt, freeze, item, task)
            response_text = receipt["observation"]["response_text"]
            packet = json.loads(item.packet_bytes)
            for attempt in receipt["observation"]["attempts"]:
                usage = attempt["usage"]
                if usage is None:
                    continue
                usage_present += 1
                recount = recounter.recount(task, packet, response_text)
                if recount is None:
                    unavailable += 1
                elif (
                    recount.get("identity_sha256")
                    != freeze["source"]["token_recounter_sha256"]
                    or recount.get("prompt_tokens") != usage["prompt_tokens"]
                    or recount.get("completion_tokens") != usage["completion_tokens"]
                ):
                    mismatches += 1
                else:
                    calibrated += 1
    calibration_passed = (
        usage_present >= 1
        and calibrated == usage_present
        and mismatches == 0
        and unavailable == 0
    )
    task_budget = ledger.snapshot()
    complete = (
        terminal_count == 9
        and success_count == 9
        and parse_failures == 0
        and calibration_passed
        and task_budget["outstanding_reserved_rmb"] == "0"
    )
    if terminal_count != 9:
        stopped: dict[str, Any] | None = {"reason": "commissioning_incomplete"}
    elif parse_failures:
        stopped = {"reason": "output_contract_failure"}
    elif not calibration_passed:
        stopped = {"reason": "recount_calibration_failed"}
    elif task_budget["outstanding_reserved_rmb"] != "0":
        stopped = {"reason": "budget_reservation_outstanding"}
    else:
        stopped = None
    return {
        "schema": COMMISSIONING_SCHEMA,
        "freeze_sha256": freeze_sha256(freeze),
        "complete": complete,
        "terminal_observation_count": terminal_count,
        "expected_terminal_observation_count": 9,
        "successful_terminal_observation_count": success_count,
        "parse_failure_count": parse_failures,
        "stopped": stopped,
        "calibration": {
            "required": True,
            "usage_present_attempt_count": usage_present,
            "calibrated_attempt_count": calibrated,
            "mismatch_count": mismatches,
            "unavailable_count": unavailable,
            "token_recounter_sha256": freeze["source"]["token_recounter_sha256"],
            "passed": calibration_passed,
        },
        "task_budget": task_budget,
    }


def build_commissioning_binding(
    freeze_value: Mapping[str, Any], result_value: Mapping[str, Any]
) -> dict[str, Any]:
    """Embed the immutable B1 proof later validated against the final formal freeze."""

    freeze = validate_freeze(freeze_value)
    result = dict(result_value)
    if (
        freeze["mode"] != "commissioning"
        or result.get("schema") != COMMISSIONING_SCHEMA
        or result.get("freeze_sha256") != freeze_sha256(freeze)
        or result.get("complete") is not True
    ):
        raise DiagnosticRunnerError("commissioning_binding_requires_success")
    return {
        "schema": COMMISSIONING_BINDING_SCHEMA,
        "run_id": freeze["run_id"],
        "commissioning_freeze": freeze,
        "freeze_sha256": freeze_sha256(freeze),
        "commissioning_result": result,
        "result_sha256": sha256_bytes(canonical_json_bytes(result)),
    }


def recompute_formal(
    freeze_value: Mapping[str, Any],
    release: ValidationRelease,
    archive: DiagnosticArchive,
    ledger: Plan100BudgetLedger,
) -> dict[str, Any]:
    """Join local supervision only after all provider receipts are already immutable."""

    freeze = validate_freeze(freeze_value)
    if freeze["mode"] != "formal" or archive.mode != "formal":
        raise DiagnosticRunnerError("recompute_requires_formal")
    terminals: dict[str, list[dict[str, Any]]] = {
        task.value: [] for task in DiagnosticTask
    }
    formal_receipts: list[dict[str, Any]] = []
    for task in DiagnosticTask:
        for item in release.public_items:
            logical_key = f"{task.value}:{item.candidate_id}"
            terminal = archive.load_terminal(logical_key)
            if terminal is None:
                return _incomplete_result(
                    freeze, terminals, ledger, "formal_terminal_missing"
                )
            _validate_terminal(terminal, freeze, item, task)
            matching_receipts = [
                receipt
                for receipt in archive.load_receipts(logical_key)
                if sha256_bytes(canonical_json_bytes(receipt))
                == terminal["receipt_sha256"]
            ]
            if len(matching_receipts) != 1:
                raise DiagnosticRunnerError("terminal_receipt_binding_invalid")
            _validate_receipt(matching_receipts[0], freeze, item, task)
            formal_receipts.append(matching_receipts[0])
            terminals[task.value].append(terminal)
    supervision = release.supervision_by_id()
    ids = [item.candidate_id for item in release.public_items]
    gold_verdicts = [supervision[item_id].gold_verdict for item_id in ids]
    scalar = scalar_metrics(
        ids,
        gold_verdicts,
        [
            None
            if row["status"] == "parse_failure"
            else row["parsed_output"]["quality"]
            for row in terminals["A"]
        ],
        release.pair_supervision,
    )
    direct = direct_metrics(
        ids,
        gold_verdicts,
        [
            None
            if row["status"] == "parse_failure"
            else row["parsed_output"]["verdict"]
            for row in terminals["B"]
        ],
        release.pair_supervision,
    )
    structured = structured_metrics(
        ids,
        [supervision[item_id].labels for item_id in ids],
        [
            None
            if row["status"] == "parse_failure"
            else row["parsed_output"]["decisions"]
            for row in terminals["C"]
        ],
        release.pair_supervision,
    )
    route = decide_route_with_metadata(scalar, direct, structured, formal_valid=True)
    parse_failures = {
        arm: sum(row["status"] == "parse_failure" for row in rows)
        for arm, rows in terminals.items()
    }
    return {
        "schema": RESULT_SCHEMA,
        "freeze_sha256": freeze_sha256(freeze),
        "complete": True,
        "observations_complete": True,
        "terminal_observation_count": 81,
        "route_terminal": route["terminal"],
        "residual_mixed_signal": route["residual_mixed_signal"],
        "route_contract_gap": None,
        "parse_failure_count": parse_failures,
        "provider_identity": {
            "requested_model": REQUESTED_MODEL,
            "served_models": sorted(
                {
                    row["served_model"]
                    for rows in terminals.values()
                    for row in rows
                    if row["served_model"] is not None
                }
            ),
            "serving_revision": "provider-managed-unverifiable",
        },
        "usage_and_cost": _usage_and_cost(formal_receipts),
        "task_budget": ledger.snapshot(),
        "metrics": {"A": scalar, "B": direct, "C": structured},
    }


def _incomplete_result(
    freeze: Mapping[str, Any],
    terminals: Mapping[str, Sequence[Mapping[str, Any]]],
    ledger: Plan100BudgetLedger,
    reason: str,
) -> dict[str, Any]:
    count = sum(len(rows) for rows in terminals.values())
    return {
        "schema": RESULT_SCHEMA,
        "freeze_sha256": freeze_sha256(freeze),
        "complete": False,
        "observations_complete": False,
        "terminal_observation_count": count,
        "route_terminal": "INCONCLUSIVE_TECHNICAL_OR_BUDGET",
        "residual_mixed_signal": False,
        "route_contract_gap": reason,
        "parse_failure_count": None,
        "provider_identity": None,
        "usage_and_cost": None,
        "task_budget": ledger.snapshot(),
        "metrics": None,
    }


def tracked_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    """Produce a body-free aggregate without packet, supervision, or provider response text."""

    if result.get("schema") != RESULT_SCHEMA:
        raise DiagnosticRunnerError("tracked_result_invalid")
    metrics = result.get("metrics")
    aggregates = None
    if isinstance(metrics, Mapping):
        aggregates = {
            "A": {
                "auc": metrics["A"]["auc"],
                "meets_basic": metrics["A"]["meets_basic"],
                "meets_gate": metrics["A"]["meets_gate"],
                "selected_binary": _binary_aggregate(
                    metrics["A"]["selected_operating_point"]["binary"]
                ),
                "boundary_strict": {
                    name: metrics["A"]["boundary_strict"][name]
                    for name in ("total", "wins", "all_won")
                },
            },
            "B": {
                "binary": _binary_aggregate(metrics["B"]["binary"]),
                "pairs": _pair_aggregate(metrics["B"]["pairs"]),
                "meets_gate": metrics["B"]["meets_gate"],
            },
            "C": {
                "binary": _binary_aggregate(metrics["C"]["binary"]),
                "per_dimension": {
                    dimension: {
                        name: detail[name]
                        for name in (
                            "confusion",
                            "class_recall",
                            "failure_recall",
                            "predicted_classes",
                            "required_classes_covered",
                        )
                    }
                    for dimension, detail in metrics["C"]["per_dimension"].items()
                },
                "supported_class_macro_recall": metrics["C"][
                    "supported_class_macro_recall"
                ],
                "continuity_na_recall": metrics["C"]["continuity_na_recall"],
                "pairs": _pair_aggregate(metrics["C"]["pairs"]),
                "meets_gate": metrics["C"]["meets_gate"],
            },
        }
    return {
        "schema": TRACKED_RESULT_SCHEMA,
        "complete": result.get("complete"),
        "observations_complete": result.get("observations_complete"),
        "terminal_observation_count": result.get("terminal_observation_count"),
        "route_terminal": result.get("route_terminal"),
        "residual_mixed_signal": result.get("residual_mixed_signal"),
        "route_contract_gap": result.get("route_contract_gap"),
        "parse_failure_count": result.get("parse_failure_count"),
        "freeze_sha256": result.get("freeze_sha256"),
        "provider_identity": result.get("provider_identity"),
        "usage_and_cost": result.get("usage_and_cost"),
        "task_budget": task_budget_summary(result.get("task_budget")),
        "aggregate_metrics": aggregates,
    }


def detailed_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    """Return bounded final-report details without packet, response, or credential data."""

    summary = tracked_projection(result)
    metrics = result.get("metrics")
    detail = None
    if isinstance(metrics, Mapping):
        selected_a = metrics["A"]["selected_operating_point"]
        detail = {
            "A": {
                "full_operating_curve": [
                    {
                        "threshold": point["threshold"],
                        "binary": _binary_aggregate(point["binary"]),
                        "pairs": _pair_aggregate(point["pairs"]),
                    }
                    for point in metrics["A"]["curve"]
                ],
                "selected_candidate_errors": selected_a["binary"]["candidate_errors"],
                "selected_pair_rows": selected_a["pairs"]["pairs"],
                "boundary_strict": metrics["A"]["boundary_strict"],
            },
            "B": {
                "candidate_errors": metrics["B"]["binary"]["candidate_errors"],
                "pair_rows": metrics["B"]["pairs"]["pairs"],
            },
            "C": {
                "candidate_errors": metrics["C"]["binary"]["candidate_errors"],
                "pair_rows": metrics["C"]["pairs"]["pairs"],
                "per_dimension": metrics["C"]["per_dimension"],
                "failed_dimension_floors": metrics["C"]["failed_dimension_floors"],
            },
        }
    return {
        **summary,
        "schema": DETAILED_RESULT_SCHEMA,
        "quality_detail": detail,
    }


def _binary_aggregate(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: value[name]
        for name in (
            "total",
            "correct",
            "false_pass",
            "false_rewrite",
            "balanced_accuracy",
            "class_recall",
            "confusion",
            "typed_failures",
            "meets_candidate_gate",
        )
    }


def _pair_aggregate(value: Mapping[str, Any]) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != "pairs"}


def _usage_and_cost(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    attempts = prompt = completion = cache_hit = cache_miss = 0
    charge = Decimal(0)
    settlement_methods: dict[str, int] = {}
    for receipt in receipts:
        for raw_attempt in receipt["observation"]["attempts"]:
            settled = settle_attempt(raw_attempt)
            attempts += 1
            charge += Decimal(settled["charge_rmb"])
            method = settled["settlement_method"]
            settlement_methods[method] = settlement_methods.get(method, 0) + 1
            usage = settled["usage"]
            if usage is None:
                continue
            prompt += usage["prompt_tokens"]
            completion += usage["completion_tokens"]
            cache_hit += (
                usage.get("prompt_cache_hit_tokens", usage.get("cache_hit_tokens")) or 0
            )
            cache_miss += (
                usage.get("prompt_cache_miss_tokens", usage.get("cache_miss_tokens"))
                or 0
            )
    return {
        "logical_call_count": len(receipts),
        "http_attempt_count": attempts,
        "prompt_tokens_reported": prompt,
        "completion_tokens_reported": completion,
        "cache_hit_tokens_reported": cache_hit,
        "cache_miss_tokens_reported": cache_miss,
        "settlement_methods": dict(sorted(settlement_methods.items())),
        "settled_rmb": format(charge, "f"),
    }


__all__ = [
    "AmbiguousAttemptError",
    "CommandTokenRecounter",
    "DiagnosticEvaluator",
    "DiagnosticRunnerError",
    "RustSubprocessEvaluator",
    "TokenRecounter",
    "detailed_projection",
    "recompute_formal",
    "run_batch",
    "tracked_projection",
]
