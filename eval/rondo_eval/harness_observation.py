"""Versioned, body-free RONDO Local task observation contract."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


class HarnessObservationError(ValueError):
    """Raised when an observation is not the exact safe schema."""


_TURN_STATUSES = {"completed", "failed", "interrupted", "in_progress", "unknown"}
_ITEM_VIEWS = {"full", "summary", "not_loaded", "unavailable"}
_COVERAGE = {"measured", "partial", "unavailable"}


def _object(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise HarnessObservationError(f"{name} schema is invalid")
    return value


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarnessObservationError(f"{name} count is invalid")
    return value


def _optional_count(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _count(value, name)


def _counts(value: object, keys: set[str], name: str) -> dict[str, int]:
    item = _object(value, keys, name)
    return {key: _count(item[key], f"{name}.{key}") for key in keys}


def validate_task_observation(value: object) -> dict[str, Any]:
    """Validate and copy one schema-v1 aggregate without accepting extensions.

    The exact-key checks are deliberate: a producer cannot accidentally add an
    identifier or body field and have an older reader silently publish it.
    """

    root = _object(
        value,
        {
            "schema_version",
            "scope",
            "event_stream_complete",
            "turn",
            "responses",
            "errors",
            "tools",
            "compactions",
            "guardian",
            "unavailable",
        },
        "task observation",
    )
    if root["schema_version"] != 1 or root["scope"] != "rondo_local_task":
        raise HarnessObservationError("task observation identity is invalid")
    if not isinstance(root["event_stream_complete"], bool):
        raise HarnessObservationError("event stream coverage is invalid")

    turn = _object(root["turn"], {"status", "duration_ms", "items_view"}, "turn")
    if turn["status"] not in _TURN_STATUSES or turn["items_view"] not in _ITEM_VIEWS:
        raise HarnessObservationError("turn enum is invalid")
    _optional_count(turn["duration_ms"], "turn.duration_ms")

    responses = _object(
        root["responses"],
        {"completed", "with_valid_usage", "missing_usage", "invalid_usage", "usage"},
        "responses",
    )
    for key in {"completed", "with_valid_usage", "missing_usage", "invalid_usage"}:
        _count(responses[key], f"responses.{key}")
    if (
        responses["with_valid_usage"]
        + responses["missing_usage"]
        + responses["invalid_usage"]
        != responses["completed"]
    ):
        raise HarnessObservationError("response usage coverage is inconsistent")
    usage = _counts(
        responses["usage"],
        {
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        },
        "usage",
    )
    if responses["with_valid_usage"] == 0 and any(usage.values()):
        raise HarnessObservationError("usage values lack measured responses")

    _counts(
        root["errors"],
        {
            "total",
            "retryable",
            "context_window_exceeded",
            "bad_request",
            "response_stream_failure",
            "response_retry_limit",
            "budget_or_usage_limit",
            "other",
        },
        "errors",
    )
    errors = root["errors"]
    if sum(
        errors[key]
        for key in {
            "context_window_exceeded",
            "bad_request",
            "response_stream_failure",
            "response_retry_limit",
            "budget_or_usage_limit",
            "other",
        }
    ) != errors["total"]:
        raise HarnessObservationError("error categories are inconsistent")
    if errors["retryable"] > errors["total"]:
        raise HarnessObservationError("retryable errors exceed total errors")

    tools = _counts(
        root["tools"],
        {
            "command",
            "mcp",
            "dynamic",
            "with_valid_duration",
            "missing_or_invalid_duration",
            "total_duration_ms",
            "command_output_bytes",
            "max_command_output_bytes",
            "repeated_exact_commands",
            "repeated_after_failure",
        },
        "tools",
    )
    tool_count = tools["command"] + tools["mcp"] + tools["dynamic"]
    if tools["with_valid_duration"] + tools["missing_or_invalid_duration"] != tool_count:
        raise HarnessObservationError("tool duration coverage is inconsistent")
    if tools["repeated_after_failure"] > tools["repeated_exact_commands"]:
        raise HarnessObservationError("repeated command counts are inconsistent")
    if tools["with_valid_duration"] == 0 and tools["total_duration_ms"] != 0:
        raise HarnessObservationError("tool duration lacks measured values")
    if tools["command"] == 0 and any(
        tools[key]
        for key in {
            "command_output_bytes",
            "max_command_output_bytes",
            "repeated_exact_commands",
            "repeated_after_failure",
        }
    ):
        raise HarnessObservationError("command aggregates lack measured commands")

    compactions = _object(root["compactions"], {"completed", "coverage"}, "compactions")
    _count(compactions["completed"], "compactions.completed")
    if compactions["coverage"] not in _COVERAGE:
        raise HarnessObservationError("compaction coverage is invalid")
    if compactions["coverage"] != "measured" and compactions["completed"] != 0:
        raise HarnessObservationError("compaction count lacks measured coverage")

    guardian = _counts(
        root["guardian"],
        {
            "started",
            "completed",
            "with_valid_duration",
            "invalid_duration",
            "total_duration_ms",
            "approved",
            "denied",
            "timed_out",
            "aborted",
            "non_terminal",
        },
        "guardian",
    )
    if guardian["with_valid_duration"] + guardian["invalid_duration"] != guardian["completed"]:
        raise HarnessObservationError("Guardian duration coverage is inconsistent")
    if sum(
        guardian[key]
        for key in {"approved", "denied", "timed_out", "aborted", "non_terminal"}
    ) != guardian["completed"]:
        raise HarnessObservationError("Guardian status counts are inconsistent")
    if guardian["with_valid_duration"] == 0 and guardian["total_duration_ms"] != 0:
        raise HarnessObservationError("Guardian duration lacks measured values")

    unavailable = _object(
        root["unavailable"],
        {
            "turn_phase_profile",
            "model_visible_output_truncation",
            "compaction_reason_and_tokens",
            "direct_tool_dispatch_handler_split",
            "guardian_token_breakdown",
        },
        "unavailable",
    )
    if not all(isinstance(item, bool) for item in unavailable.values()):
        raise HarnessObservationError("unavailable field flags are invalid")
    return deepcopy(root)


_DELTA_PATHS = (
    ("turn", "duration_ms"),
    ("responses", "completed"),
    ("responses", "usage", "input_tokens"),
    ("responses", "usage", "cached_input_tokens"),
    ("responses", "usage", "output_tokens"),
    ("errors", "total"),
    ("tools", "command"),
    ("tools", "total_duration_ms"),
    ("tools", "command_output_bytes"),
    ("tools", "repeated_exact_commands"),
    ("compactions", "completed"),
    ("guardian", "completed"),
    ("guardian", "total_duration_ms"),
)


def compare_task_observations(left: object, right: object) -> dict[str, object]:
    """Return bounded numeric deltas for two same-schema task observations."""

    before = validate_task_observation(left)
    after = validate_task_observation(right)
    comparable = (
        before["event_stream_complete"]
        and after["event_stream_complete"]
        and before["turn"]["status"] in {"completed", "failed", "interrupted"}
        and after["turn"]["status"] in {"completed", "failed", "interrupted"}
        and before["turn"]["items_view"] == "full"
        and after["turn"]["items_view"] == "full"
        and before["turn"]["duration_ms"] is not None
        and after["turn"]["duration_ms"] is not None
        and before["responses"]["missing_usage"] == 0
        and after["responses"]["missing_usage"] == 0
        and before["responses"]["invalid_usage"] == 0
        and after["responses"]["invalid_usage"] == 0
        and before["tools"]["missing_or_invalid_duration"] == 0
        and after["tools"]["missing_or_invalid_duration"] == 0
        and before["compactions"]["coverage"] == "measured"
        and after["compactions"]["coverage"] == "measured"
        and before["guardian"]["invalid_duration"] == 0
        and after["guardian"]["invalid_duration"] == 0
        and before["guardian"]["non_terminal"] == 0
        and after["guardian"]["non_terminal"] == 0
        and before["guardian"]["started"] == before["guardian"]["completed"]
        and after["guardian"]["started"] == after["guardian"]["completed"]
    )
    deltas: dict[str, int | None] = {}
    for path in _DELTA_PATHS:
        left_value: object = before
        right_value: object = after
        for part in path:
            left_value = left_value[part]  # type: ignore[index]
            right_value = right_value[part]  # type: ignore[index]
        key = ".".join(path)
        deltas[key] = (
            right_value - left_value
            if comparable
            and isinstance(left_value, int)
            and not isinstance(left_value, bool)
            and isinstance(right_value, int)
            and not isinstance(right_value, bool)
            else None
        )
    return {
        "schema_version": 1,
        "kind": "rondo_local_task_observation_delta",
        "comparable": comparable,
        "deltas": deltas,
    }
