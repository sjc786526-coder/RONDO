"""Strict body-free RONDO Local task observation and offline projection."""

from __future__ import annotations

import json
import re
import stat
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any

from .team_lens import BundleError
from .team_lens import NativeBundleReader
from .team_lens import TeamViewError
from .team_lens import reduce_bundle_with_root_session


OBSERVATION_FILE_NAME = "harness-observation.json"
LOCAL_ROLLOUT_TRACE_ROOT = "/logs/agent/rollout-trace"
_MAX_API_METADATA_BYTES = 8 * 1024 * 1024
_MAX_TRACE_BUNDLES = 64
_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "aborted"}
_AVAILABILITY = {"measured", "partial", "unmeasurable"}
_USAGE_KEYS = {
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
}
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_CONTEXT_ERROR_CODES = {
    "context_length_exceeded",
    "context_window_exceeded",
    "input_too_long",
}
_BUDGET_ERROR_CODES = {
    "billing_hard_limit_reached",
    "insufficient_quota",
    "rate_limit_exceeded",
    "usage_limit_reached",
}


class HarnessObservationError(ValueError):
    """Raised when a source or observation is not the exact safe contract."""


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
    """Validate and copy one exact schema-v2 body-free aggregate."""

    root = _object(
        value,
        {
            "schema_version",
            "kind",
            "scope",
            "source",
            "availability",
            "turn",
            "responses",
            "errors",
            "tools",
            "compactions",
        },
        "task observation",
    )
    if (
        root["schema_version"] != 2
        or root["kind"] != "rondo_local_harness_observation"
        or root["scope"] != "rondo_local_task"
    ):
        raise HarnessObservationError("task observation identity is invalid")

    source = _object(
        root["source"],
        {
            "product",
            "rollout_trace_manifest_schema_version",
            "rollout_trace_event_schema_versions",
            "api_metadata_schema_version",
            "guardian_trace_bundles",
        },
        "source",
    )
    if (
        source["product"] != "rondo-local"
        or source["rollout_trace_manifest_schema_version"] != 1
        or source["rollout_trace_event_schema_versions"] != [1]
        or source["api_metadata_schema_version"] != 1
    ):
        raise HarnessObservationError("observation source identity is invalid")
    _count(source["guardian_trace_bundles"], "source.guardian_trace_bundles")

    availability = _object(
        root["availability"],
        {
            "turn_lifecycle",
            "response_lifecycle",
            "response_usage",
            "tool_lifecycle",
            "command_output",
            "compactions",
            "guardian_details",
            "model_visible_output_truncation",
            "code_mode_runtime_output_truncation",
            "claim_verification_relation",
        },
        "availability",
    )
    if any(item not in _AVAILABILITY for item in availability.values()):
        raise HarnessObservationError("observation availability is invalid")
    for required in (
        "turn_lifecycle",
        "response_lifecycle",
        "tool_lifecycle",
        "command_output",
    ):
        if availability[required] != "measured":
            raise HarnessObservationError("required observation coverage is unavailable")
    for unavailable in (
        "compactions",
        "guardian_details",
        "claim_verification_relation",
    ):
        if availability[unavailable] != "unmeasurable":
            raise HarnessObservationError("unsupported observation coverage is overstated")

    turn = _object(root["turn"], {"status", "duration_ms"}, "turn")
    if turn["status"] not in _TERMINAL_STATUSES:
        raise HarnessObservationError("turn status is not terminal")
    _count(turn["duration_ms"], "turn.duration_ms")

    responses = _object(
        root["responses"],
        {
            "total",
            "main",
            "guardian",
            "terminal_completed",
            "terminal_failed",
            "terminal_incomplete",
            "terminal_error",
            "with_valid_usage",
            "missing_or_invalid_usage",
            "usage",
        },
        "responses",
    )
    for key in {
        "total",
        "main",
        "guardian",
        "terminal_completed",
        "terminal_failed",
        "terminal_incomplete",
        "terminal_error",
        "with_valid_usage",
        "missing_or_invalid_usage",
    }:
        _count(responses[key], f"responses.{key}")
    if responses["total"] == 0:
        raise HarnessObservationError("response population is empty")
    if responses["main"] + responses["guardian"] != responses["total"]:
        raise HarnessObservationError("response role counts are inconsistent")
    if (
        responses["terminal_completed"]
        + responses["terminal_failed"]
        + responses["terminal_incomplete"]
        + responses["terminal_error"]
        != responses["total"]
    ):
        raise HarnessObservationError("response terminal counts are inconsistent")
    if (
        responses["with_valid_usage"] + responses["missing_or_invalid_usage"]
        != responses["total"]
    ):
        raise HarnessObservationError("response usage coverage is inconsistent")
    usage = _counts(responses["usage"], _USAGE_KEYS, "responses.usage")
    if responses["with_valid_usage"] == 0 and any(usage.values()):
        raise HarnessObservationError("usage values lack measured responses")
    expected_usage_availability = (
        "measured" if responses["missing_or_invalid_usage"] == 0 else "unmeasurable"
    )
    if availability["response_usage"] != expected_usage_availability:
        raise HarnessObservationError("usage availability is inconsistent")

    errors = _counts(
        root["errors"],
        {
            "total",
            "retryable_status",
            "context_window_exceeded",
            "bad_request",
            "response_stream_failure",
            "budget_or_usage_limit",
            "other",
        },
        "errors",
    )
    if errors["total"] != responses["total"] - responses["terminal_completed"]:
        raise HarnessObservationError("error total disagrees with response lifecycle")
    if errors["retryable_status"] > errors["total"]:
        raise HarnessObservationError("retryable errors exceed total errors")
    if sum(
        errors[key]
        for key in {
            "context_window_exceeded",
            "bad_request",
            "response_stream_failure",
            "budget_or_usage_limit",
            "other",
        }
    ) != errors["total"]:
        raise HarnessObservationError("error categories are inconsistent")

    tools = _counts(
        root["tools"],
        {
            "total",
            "command",
            "mcp",
            "other",
            "total_lifecycle_duration_ms",
            "command_output_bytes",
            "max_command_output_bytes",
            "model_visible_output_deliveries",
            "model_visible_output_renders",
            "model_visible_output_render_missing",
            "model_visible_source_text_bytes",
            "model_visible_returned_text_bytes",
            "model_visible_presentation_truncations",
            "model_visible_collection_omission_events",
            "model_visible_collection_omitted_bytes",
            "code_mode_runtime_output_deliveries",
            "code_mode_runtime_output_renders",
            "code_mode_runtime_output_render_missing",
            "code_mode_runtime_source_text_bytes",
            "code_mode_runtime_returned_text_bytes",
            "code_mode_runtime_presentation_truncations",
            "code_mode_runtime_collection_omission_events",
            "code_mode_runtime_collection_omitted_bytes",
            "repeated_exact_commands",
            "repeated_exact_command_lifecycle_duration_ms",
            "repeated_after_failure",
        },
        "tools",
    )
    if tools["command"] + tools["mcp"] + tools["other"] != tools["total"]:
        raise HarnessObservationError("tool categories are inconsistent")
    if tools["repeated_after_failure"] > tools["repeated_exact_commands"]:
        raise HarnessObservationError("repeated command counts are inconsistent")
    if tools["repeated_exact_commands"] > tools["command"]:
        raise HarnessObservationError("repeated commands exceed command tools")
    if (
        tools["repeated_exact_command_lifecycle_duration_ms"]
        > tools["total_lifecycle_duration_ms"]
    ):
        raise HarnessObservationError("repeated command duration exceeds tool duration")
    if (
        tools["repeated_exact_commands"] == 0
        and tools["repeated_exact_command_lifecycle_duration_ms"] != 0
    ):
        raise HarnessObservationError("repeated command duration lacks repeated commands")
    if tools["command"] == 0 and any(
        tools[key]
        for key in {
            "command_output_bytes",
            "max_command_output_bytes",
            "repeated_exact_commands",
            "repeated_exact_command_lifecycle_duration_ms",
            "repeated_after_failure",
        }
    ):
        raise HarnessObservationError("command aggregates lack measured commands")
    if tools["max_command_output_bytes"] > tools["command_output_bytes"]:
        raise HarnessObservationError("maximum command output exceeds total output")
    for prefix in ("model_visible", "code_mode_runtime"):
        deliveries = tools[f"{prefix}_output_deliveries"]
        renders = tools[f"{prefix}_output_renders"]
        missing = tools[f"{prefix}_output_render_missing"]
        truncations = tools[f"{prefix}_presentation_truncations"]
        omission_events = tools[f"{prefix}_collection_omission_events"]
        omitted_bytes = tools[f"{prefix}_collection_omitted_bytes"]
        if renders + missing != deliveries:
            raise HarnessObservationError("output render coverage is inconsistent")
        if truncations > renders or omission_events > renders:
            raise HarnessObservationError("output render aggregates are inconsistent")
        if renders == 0 and any(
            tools[key]
            for key in {
                f"{prefix}_source_text_bytes",
                f"{prefix}_returned_text_bytes",
                f"{prefix}_presentation_truncations",
                f"{prefix}_collection_omission_events",
                f"{prefix}_collection_omitted_bytes",
            }
        ):
            raise HarnessObservationError("output render totals lack measured renders")
        if (omission_events == 0) != (omitted_bytes == 0):
            raise HarnessObservationError("output collection omission totals are inconsistent")
    for prefix, availability_key in (
        ("model_visible", "model_visible_output_truncation"),
        ("code_mode_runtime", "code_mode_runtime_output_truncation"),
    ):
        expected_output_availability = _surface_output_render_availability(
            tools, prefix
        )
        if availability[availability_key] != expected_output_availability:
            raise HarnessObservationError("output render availability is inconsistent")

    compactions = _object(root["compactions"], {"completed"}, "compactions")
    if _optional_count(compactions["completed"], "compactions.completed") is not None:
        raise HarnessObservationError("compaction count is not measurable")
    return deepcopy(root)


_DELTA_PATHS = (
    ("turn", "duration_ms"),
    ("responses", "total"),
    ("responses", "main"),
    ("responses", "guardian"),
    ("responses", "terminal_completed"),
    ("responses", "usage", "input_tokens"),
    ("responses", "usage", "cached_input_tokens"),
    ("responses", "usage", "cache_write_input_tokens"),
    ("responses", "usage", "output_tokens"),
    ("errors", "total"),
    ("errors", "context_window_exceeded"),
    ("errors", "bad_request"),
    ("tools", "total"),
    ("tools", "command"),
    ("tools", "total_lifecycle_duration_ms"),
    ("tools", "command_output_bytes"),
    ("tools", "max_command_output_bytes"),
    ("tools", "model_visible_output_deliveries"),
    ("tools", "model_visible_output_renders"),
    ("tools", "model_visible_output_render_missing"),
    ("tools", "model_visible_source_text_bytes"),
    ("tools", "model_visible_returned_text_bytes"),
    ("tools", "model_visible_presentation_truncations"),
    ("tools", "model_visible_collection_omission_events"),
    ("tools", "model_visible_collection_omitted_bytes"),
    ("tools", "code_mode_runtime_output_deliveries"),
    ("tools", "code_mode_runtime_output_renders"),
    ("tools", "code_mode_runtime_output_render_missing"),
    ("tools", "code_mode_runtime_source_text_bytes"),
    ("tools", "code_mode_runtime_returned_text_bytes"),
    ("tools", "code_mode_runtime_presentation_truncations"),
    ("tools", "code_mode_runtime_collection_omission_events"),
    ("tools", "code_mode_runtime_collection_omitted_bytes"),
    ("tools", "repeated_exact_commands"),
    ("tools", "repeated_exact_command_lifecycle_duration_ms"),
    ("tools", "repeated_after_failure"),
)

_OUTPUT_RENDER_VALUE_AVAILABILITY = {
    "model_visible_source_text_bytes": "model_visible_output_truncation",
    "model_visible_returned_text_bytes": "model_visible_output_truncation",
    "model_visible_presentation_truncations": "model_visible_output_truncation",
    "model_visible_collection_omission_events": "model_visible_output_truncation",
    "model_visible_collection_omitted_bytes": "model_visible_output_truncation",
    "code_mode_runtime_source_text_bytes": "code_mode_runtime_output_truncation",
    "code_mode_runtime_returned_text_bytes": "code_mode_runtime_output_truncation",
    "code_mode_runtime_presentation_truncations": "code_mode_runtime_output_truncation",
    "code_mode_runtime_collection_omission_events": "code_mode_runtime_output_truncation",
    "code_mode_runtime_collection_omitted_bytes": "code_mode_runtime_output_truncation",
}


def compare_task_observations(left: object, right: object) -> dict[str, object]:
    """Return bounded numeric deltas for two same-source task observations."""

    before = validate_task_observation(left)
    after = validate_task_observation(right)
    comparable = all(
        before["source"][key] == after["source"][key]
        for key in {
            "product",
            "rollout_trace_manifest_schema_version",
            "rollout_trace_event_schema_versions",
            "api_metadata_schema_version",
        }
    )
    deltas: dict[str, int | None] = {}
    for path in _DELTA_PATHS:
        left_value: object = before
        right_value: object = after
        for part in path:
            left_value = left_value[part]  # type: ignore[index]
            right_value = right_value[part]  # type: ignore[index]
        usage_path = len(path) > 1 and path[1] == "usage"
        output_availability = (
            _OUTPUT_RENDER_VALUE_AVAILABILITY.get(path[1])
            if len(path) > 1
            else None
        )
        measured = (
            not usage_path
            or (
                before["availability"]["response_usage"] == "measured"
                and after["availability"]["response_usage"] == "measured"
            )
        ) and (
            output_availability is None
            or (
                before["availability"][output_availability] == "measured"
                and after["availability"][output_availability] == "measured"
            )
        )
        key = ".".join(path)
        deltas[key] = (
            right_value - left_value
            if comparable
            and measured
            and isinstance(left_value, int)
            and not isinstance(left_value, bool)
            and isinstance(right_value, int)
            and not isinstance(right_value, bool)
            else None
        )
    return {
        "schema_version": 2,
        "kind": "rondo_local_harness_observation_delta",
        "comparable": comparable,
        "deltas": deltas,
    }


def project_task_observation(trace_root: Path, api_metadata_path: Path) -> dict[str, Any]:
    """Project private trace/API sources into one strictly body-free aggregate.

    Raw prompt, command, output, identifiers, and paths are read only in memory.
    No source material is returned by this function.
    """

    try:
        bundle_dirs = _trace_bundle_dirs(Path(trace_root))
        bundles = [_read_complete_bundle(path) for path in bundle_dirs]
        exec_bundles = [item for item in bundles if item[0] == "exec"]
        guardian_bundles = [item for item in bundles if item[0] == "guardian"]
        if len(exec_bundles) != 1 or len(exec_bundles) + len(guardian_bundles) != len(bundles):
            raise HarnessObservationError("trace root session population is invalid")
        metadata = _read_api_metadata(Path(api_metadata_path))
        observation = _project_complete_sources(
            exec_bundles[0], guardian_bundles, metadata
        )
        return validate_task_observation(observation)
    except HarnessObservationError:
        raise
    except (BundleError, TeamViewError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessObservationError("private observation source is invalid") from exc


def _trace_bundle_dirs(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise HarnessObservationError("rollout trace root is unavailable")
    entries = sorted(root.iterdir(), key=lambda item: item.name)
    if not entries or len(entries) > _MAX_TRACE_BUNDLES:
        raise HarnessObservationError("rollout trace bundle population is invalid")
    if any(entry.is_symlink() or not entry.is_dir() for entry in entries):
        raise HarnessObservationError("rollout trace root contains an unsafe entry")
    return entries


def _read_complete_bundle(path: Path) -> tuple[str, dict[str, Any], NativeBundleReader]:
    reader = NativeBundleReader(path)
    capture_events = [
        event
        for event in reader.events
        if event["payload"]["type"] == "trace_capture_ended"
    ]
    if (
        len(capture_events) != 1
        or reader.events[-1] is not capture_events[0]
        or capture_events[0]["payload"].get("dropped_operations") != 0
        or len(reader.events) < 2
        or reader.events[-2]["payload"]["type"] != "rollout_ended"
    ):
        raise HarnessObservationError("rollout trace capture is incomplete")
    reduction = reduce_bundle_with_root_session(path, "rondo-local")
    view = reduction.view
    for capability_name in (
        "agents",
        "turns",
        "inferences",
        "tools",
        "terminal",
        "timing",
    ):
        if view["availability"][capability_name]["status"] != "available":
            raise HarnessObservationError("rollout trace lifecycle is incomplete")
    missing_usage = [
        inference for inference in view["inferences"] if inference["usage"] is None
    ]
    usage_capability = view["availability"]["usage"]
    if missing_usage:
        if any(inference["status"] == "completed" for inference in missing_usage):
            raise HarnessObservationError("completed inference usage is missing")
        expected_reasons = sorted(
            {
                f"{inference['status']}_inference_usage_missing"
                for inference in missing_usage
            }
        )
        if usage_capability != {
            "status": "partial",
            "reason_codes": expected_reasons,
        }:
            raise HarnessObservationError("rollout trace usage coverage is invalid")
    elif usage_capability != {"status": "available", "reason_codes": []}:
        raise HarnessObservationError("rollout trace usage coverage is invalid")
    turns = view["turns"]
    if (
        view["team"] is not None
        or len(view["agents"]) != 1
        or not turns
        or (reduction.root_session_kind == "exec" and len(turns) != 1)
        or view["summary"]["ended_at_unix_ms"] is None
        or view["summary"]["duration_ms"] is None
        or any(row["status"] not in _TERMINAL_STATUSES for row in view["agents"])
        or any(row["status"] not in _TERMINAL_STATUSES for row in turns)
        or any(row["status"] not in _TERMINAL_STATUSES for row in view["inferences"])
        or any(row["status"] not in _TERMINAL_STATUSES for row in view["tools"])
    ):
        raise HarnessObservationError("rollout trace terminal lifecycle is invalid")
    return reduction.root_session_kind, view, reader


def _read_api_metadata(path: Path) -> list[dict[str, Any]]:
    try:
        mode = path.lstat().st_mode
        size = path.stat().st_size
    except OSError as exc:
        raise HarnessObservationError("API metadata is unavailable") from exc
    if not stat.S_ISREG(mode) or size > _MAX_API_METADATA_BYTES:
        raise HarnessObservationError("API metadata is unsafe")
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessObservationError("API metadata is unreadable") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "requests"}
        or value.get("schema_version") != 1
        or not isinstance(value.get("requests"), list)
        or not value["requests"]
    ):
        raise HarnessObservationError("API metadata schema is invalid")
    requests: list[dict[str, Any]] = []
    request_ids: set[str] = set()
    for request in value["requests"]:
        if not isinstance(request, dict):
            raise HarnessObservationError("API request metadata is invalid")
        request_id = request.get("request_id")
        role = request.get("role")
        if (
            not isinstance(request_id, str)
            or not request_id
            or request_id in request_ids
            or role not in {"main", "guardian"}
            or request.get("role_provenance") != "declared"
            or request.get("declared_role") != role
            or request.get("inferred_role") != role
            or request.get("contract_match") is not True
        ):
            raise HarnessObservationError("API request identity is invalid")
        request_ids.add(request_id)
        usage_valid = request.get("usage_valid")
        usage = request.get("usage")
        if usage_valid is True:
            if (
                not isinstance(usage, dict)
                or set(usage) != _USAGE_KEYS
                or any(_safe_count(usage[key]) is None for key in _USAGE_KEYS)
            ):
                raise HarnessObservationError("API request usage is invalid")
        elif usage_valid is False:
            if usage is not None:
                raise HarnessObservationError("API request usage coverage is invalid")
        else:
            raise HarnessObservationError("API request is not terminally accounted")
        status = request.get("upstream_status")
        attempt_count = request.get("attempt_count")
        if (
            _safe_count(status) is None
            or status > 599
            or _safe_count(attempt_count) is None
            or attempt_count < 1
            or not isinstance(request.get("stream"), bool)
        ):
            raise HarnessObservationError("API request terminal metadata is invalid")
        if request["stream"]:
            if request.get("stream_end_kind") not in {
                "terminal",
                "clean_eof",
                "read_error",
                "size_limit",
            }:
                raise HarnessObservationError("API stream terminal metadata is invalid")
            if request.get("terminal_event_type") not in {
                None,
                "response.completed",
                "response.failed",
                "response.incomplete",
                "error",
            } or request.get("terminal_response_status") not in {
                None,
                "completed",
                "failed",
                "incomplete",
                "cancelled",
            }:
                raise HarnessObservationError("API stream terminal enum is invalid")
        error_code = request.get("terminal_error_code")
        if error_code is not None and (
            not isinstance(error_code, str)
            or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", error_code) is None
        ):
            raise HarnessObservationError("API terminal error code is invalid")
        if usage_valid is False and _api_terminal_kind(request) == "completed":
            raise HarnessObservationError("completed API response usage is missing")
        requests.append(request)
    return requests


def _project_complete_sources(
    exec_bundle: tuple[str, dict[str, Any], NativeBundleReader],
    guardian_bundles: list[tuple[str, dict[str, Any], NativeBundleReader]],
    requests: list[dict[str, Any]],
) -> dict[str, Any]:
    _kind, exec_view, exec_reader = exec_bundle
    all_views = [exec_view, *(item[1] for item in guardian_bundles)]
    trace_main = len(exec_view["inferences"])
    trace_guardian = sum(len(view["inferences"]) for view in all_views[1:])
    api_main = sum(request["role"] == "main" for request in requests)
    api_guardian = len(requests) - api_main
    if (trace_main, trace_guardian) != (api_main, api_guardian):
        raise HarnessObservationError("trace and API response populations disagree")

    response_stats = _response_stats(requests)
    trace_completed = sum(
        inference["status"] == "completed"
        for view in all_views
        for inference in view["inferences"]
    )
    if trace_completed != response_stats["terminal_completed"]:
        raise HarnessObservationError("trace and API response terminals disagree")
    trace_missing_usage = (
        sum(inference["usage"] is None for inference in exec_view["inferences"]),
        sum(
            inference["usage"] is None
            for view in all_views[1:]
            for inference in view["inferences"]
        ),
    )
    api_missing_usage = (
        sum(
            request["role"] == "main" and request["usage_valid"] is False
            for request in requests
        ),
        sum(
            request["role"] == "guardian" and request["usage_valid"] is False
            for request in requests
        ),
    )
    if trace_missing_usage != api_missing_usage:
        raise HarnessObservationError("trace and API usage coverage disagree")
    for trace_views, role in (([exec_view], "main"), (all_views[1:], "guardian")):
        trace_usage = {
            key: sum(view["summary"]["usage"][key] for view in trace_views)
            for key in _USAGE_KEYS
        }
        api_usage = {
            key: sum(
                request["usage"][key]
                for request in requests
                if request["role"] == role and request["usage_valid"] is True
            )
            for key in _USAGE_KEYS
        }
        if trace_usage != api_usage:
            raise HarnessObservationError("trace and API usage totals disagree")

    tools = _tool_stats(exec_view, exec_reader)
    return {
        "schema_version": 2,
        "kind": "rondo_local_harness_observation",
        "scope": "rondo_local_task",
        "source": {
            "product": "rondo-local",
            "rollout_trace_manifest_schema_version": 1,
            "rollout_trace_event_schema_versions": [1],
            "api_metadata_schema_version": 1,
            "guardian_trace_bundles": len(guardian_bundles),
        },
        "availability": {
            "turn_lifecycle": "measured",
            "response_lifecycle": "measured",
            "response_usage": (
                "measured"
                if response_stats["missing_or_invalid_usage"] == 0
                else "unmeasurable"
            ),
            "tool_lifecycle": "measured",
            "command_output": "measured",
            "compactions": "unmeasurable",
            "guardian_details": "unmeasurable",
            "model_visible_output_truncation": _surface_output_render_availability(
                tools, "model_visible"
            ),
            "code_mode_runtime_output_truncation": _surface_output_render_availability(
                tools, "code_mode_runtime"
            ),
            "claim_verification_relation": "unmeasurable",
        },
        "turn": {
            "status": exec_view["turns"][0]["status"],
            "duration_ms": _turn_duration_ms(exec_view["turns"][0]),
        },
        "responses": response_stats,
        "errors": _error_stats(requests),
        "tools": tools,
        "compactions": {"completed": None},
    }


def _response_stats(requests: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "total": len(requests),
        "main": 0,
        "guardian": 0,
        "terminal_completed": 0,
        "terminal_failed": 0,
        "terminal_incomplete": 0,
        "terminal_error": 0,
        "with_valid_usage": 0,
        "missing_or_invalid_usage": 0,
        "usage": {key: 0 for key in _USAGE_KEYS},
    }
    for request in requests:
        stats[request["role"]] += 1
        terminal = _api_terminal_kind(request)
        stats[f"terminal_{terminal}"] += 1
        if request["usage_valid"] is True:
            stats["with_valid_usage"] += 1
            for key in _USAGE_KEYS:
                stats["usage"][key] += request["usage"][key]
        else:
            stats["missing_or_invalid_usage"] += 1
    return stats


def _api_terminal_kind(request: Mapping[str, Any]) -> str:
    if request.get("stream") is False:
        return (
            "completed"
            if request.get("upstream_status") == 200 and request.get("usage_valid") is True
            else "error"
        )
    end_kind = request.get("stream_end_kind")
    event_type = request.get("terminal_event_type")
    response_status = request.get("terminal_response_status")
    if (
        end_kind == "terminal"
        and event_type == "response.completed"
        and response_status == "completed"
        and request.get("upstream_status") == 200
    ):
        return "completed"
    if event_type == "response.failed" or response_status == "failed":
        return "failed"
    if event_type == "response.incomplete" or response_status == "incomplete":
        return "incomplete"
    return "error"


def _error_stats(requests: list[dict[str, Any]]) -> dict[str, int]:
    stats = {
        "total": 0,
        "retryable_status": 0,
        "context_window_exceeded": 0,
        "bad_request": 0,
        "response_stream_failure": 0,
        "budget_or_usage_limit": 0,
        "other": 0,
    }
    for request in requests:
        if _api_terminal_kind(request) == "completed":
            continue
        stats["total"] += 1
        status = request.get("upstream_status")
        if status in _RETRYABLE_STATUSES:
            stats["retryable_status"] += 1
        code = request.get("terminal_error_code")
        if code in _CONTEXT_ERROR_CODES:
            category = "context_window_exceeded"
        elif status == 400:
            category = "bad_request"
        elif code in _BUDGET_ERROR_CODES:
            category = "budget_or_usage_limit"
        elif request.get("stream_end_kind") in {"clean_eof", "read_error", "size_limit"}:
            category = "response_stream_failure"
        else:
            category = "other"
        stats[category] += 1
    return stats


def _tool_stats(view: dict[str, Any], reader: NativeBundleReader) -> dict[str, int]:
    tools = view["tools"]
    command_tools = {
        tool["tool_id"]: tool
        for tool in tools
        if tool["kind"] in {"exec_command", "write_stdin"}
    }
    runtime_ends: dict[str, dict[str, Any]] = {}
    for event in reader.events:
        payload = event["payload"]
        if payload["type"] != "tool_call_runtime_ended":
            continue
        tool_id = payload["tool_call_id"]
        if tool_id not in command_tools:
            continue
        if tool_id in runtime_ends:
            raise HarnessObservationError("command runtime terminal is duplicated")
        runtime = reader.load_ref(payload["runtime_payload"])
        if not isinstance(runtime, dict):
            raise HarnessObservationError("command runtime payload is invalid")
        runtime_ends[tool_id] = runtime
    if set(runtime_ends) != set(command_tools):
        raise HarnessObservationError("command runtime terminal is incomplete")

    total_duration = 0
    tool_durations: dict[str, int] = {}
    for tool in tools:
        started = tool["started_at_unix_ms"]
        ended = tool["ended_at_unix_ms"]
        if _safe_count(started) is None or _safe_count(ended) is None or ended < started:
            raise HarnessObservationError("tool lifecycle duration is invalid")
        duration = ended - started
        total_duration += duration
        tool_durations[tool["tool_id"]] = duration

    output_total = 0
    output_max = 0
    repeated = 0
    repeated_duration = 0
    repeated_after_failure = 0
    commands_seen: dict[tuple[str, tuple[str, ...], str], int] = {}
    for tool_id, tool in command_tools.items():
        runtime = runtime_ends[tool_id]
        command = runtime.get("command")
        cwd = runtime.get("cwd")
        output = runtime.get("aggregated_output")
        exit_code = runtime.get("exit_code")
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) for part in command)
            or not isinstance(cwd, str)
            or not cwd
            or not isinstance(output, str)
            or isinstance(exit_code, bool)
            or not isinstance(exit_code, int)
        ):
            raise HarnessObservationError("command runtime aggregate is invalid")
        output_bytes = len(output.encode("utf-8"))
        output_total += output_bytes
        output_max = max(output_max, output_bytes)
        if tool["kind"] != "exec_command":
            continue
        identity = (tool["requester"], tuple(command), cwd)
        prior_exit_code = commands_seen.get(identity)
        if prior_exit_code is not None:
            repeated += 1
            repeated_duration += tool_durations[tool_id]
            if prior_exit_code != 0:
                repeated_after_failure += 1
        commands_seen[identity] = exit_code

    command_count = len(command_tools)
    mcp_count = sum(tool["kind"] == "mcp" for tool in tools)
    render_stats = _output_render_stats(view, reader)
    return {
        "total": len(tools),
        "command": command_count,
        "mcp": mcp_count,
        "other": len(tools) - command_count - mcp_count,
        "total_lifecycle_duration_ms": total_duration,
        "command_output_bytes": output_total,
        "max_command_output_bytes": output_max,
        **render_stats,
        "repeated_exact_commands": repeated,
        "repeated_exact_command_lifecycle_duration_ms": repeated_duration,
        "repeated_after_failure": repeated_after_failure,
    }


def _output_render_stats(
    view: dict[str, Any], reader: NativeBundleReader
) -> dict[str, int]:
    tools = {tool["tool_id"]: tool for tool in view["tools"]}
    command_tools = {
        tool_id
        for tool_id, tool in tools.items()
        if tool["kind"] in {"exec_command", "write_stdin"}
    }
    tool_model_call_ids: dict[str, str] = {}
    code_cell_model_call_ids: dict[tuple[str, str, str], str] = {}
    for event in reader.events:
        payload = event["payload"]
        if payload["type"] == "tool_call_started":
            tool_id = payload["tool_call_id"]
            model_call_id = payload.get("model_visible_call_id")
            if tools[tool_id]["requester"] == "model":
                if not isinstance(model_call_id, str) or not model_call_id:
                    raise HarnessObservationError("model tool output identity is missing")
                tool_model_call_ids[tool_id] = model_call_id
        elif payload["type"] == "code_cell_started":
            runtime_cell_id = payload["runtime_cell_id"]
            model_call_id = payload.get("model_visible_call_id")
            thread_id = event.get("thread_id")
            turn_id = event.get("codex_turn_id")
            cell = (thread_id, turn_id, runtime_cell_id)
            if (
                not all(isinstance(item, str) and item for item in cell)
                or cell in code_cell_model_call_ids
                or not isinstance(model_call_id, str)
                or not model_call_id
            ):
                raise HarnessObservationError("code cell output identity is invalid")
            code_cell_model_call_ids[cell] = model_call_id

    deliveries: dict[tuple[str, str, str | None, str], str] = {}
    observations: dict[tuple[str, str, str | None, str], dict[str, Any]] = {}
    ended_tools: set[str] = set()
    for event in reader.events:
        payload = event["payload"]
        if payload["type"] != "tool_call_ended":
            continue
        tool_id = payload["tool_call_id"]
        if tool_id in ended_tools or tool_id not in tools:
            raise HarnessObservationError("tool output render terminal is invalid")
        ended_tools.add(tool_id)
        result = reader.load_ref(payload.get("result_payload"))
        if not isinstance(result, dict) or result.get("type") not in {
            "direct_response",
            "code_mode_response",
            "error",
        }:
            raise HarnessObservationError("tool output render payload is invalid")
        observation = result.get("output_render")
        surface = (
            "direct_model" if tools[tool_id]["requester"] == "model" else "code_mode_runtime"
        )
        delivery_id = (
            tool_model_call_ids[tool_id]
            if surface == "direct_model"
            else tool_id
        )
        delivery = (
            surface,
            tools[tool_id]["agent_id"],
            tools[tool_id]["turn_id"],
            delivery_id,
        )
        if delivery in deliveries:
            raise HarnessObservationError("tool output delivery identity is duplicated")
        deliveries[delivery] = surface
        if observation is None:
            if tool_id in command_tools and result["type"] != "error":
                raise HarnessObservationError("command output render observation is missing")
            continue
        observations[delivery] = _validate_output_render(observation, surface)
    if ended_tools != set(tools):
        raise HarnessObservationError("tool output render lifecycle is incomplete")

    public_exec_deliveries: dict[
        tuple[str, str, str, str], dict[str, Any] | None
    ] = {}
    for event in reader.events:
        payload = event["payload"]
        if payload["type"] != "code_mode_exec_output_delivered":
            continue
        thread_id = event.get("thread_id")
        turn_id = event.get("codex_turn_id")
        model_call_id = payload.get("model_visible_call_id")
        if not all(
            isinstance(item, str) and item
            for item in (thread_id, turn_id, model_call_id)
        ):
            raise HarnessObservationError("public exec output identity is invalid")
        delivery = ("direct_model", thread_id, turn_id, model_call_id)
        if delivery in public_exec_deliveries:
            raise HarnessObservationError("public exec output delivery is duplicated")
        raw_observation = payload.get("output_render")
        observation = (
            None
            if raw_observation is None
            else _validate_output_render(raw_observation, "direct_model")
        )
        public_exec_deliveries[delivery] = observation
        deliveries.setdefault(delivery, "direct_model")
        prior = observations.get(delivery)
        if observation is None:
            observations.pop(delivery, None)
        elif prior is not None and prior != observation:
            raise HarnessObservationError("correlated output render observations disagree")
        else:
            observations[delivery] = observation

    initial_cells = {
        (
            event.get("thread_id"),
            event.get("codex_turn_id"),
            event["payload"]["runtime_cell_id"],
        )
        for event in reader.events
        if event["payload"]["type"] == "code_cell_initial_response"
    }
    rendered_cells: set[tuple[object, object, object]] = set()
    for event in reader.events:
        payload = event["payload"]
        if payload["type"] != "code_cell_output_rendered":
            continue
        runtime_cell_id = payload["runtime_cell_id"]
        cell = (event.get("thread_id"), event.get("codex_turn_id"), runtime_cell_id)
        if cell in rendered_cells:
            raise HarnessObservationError("code cell output render is duplicated")
        rendered_cells.add(cell)
        model_call_id = code_cell_model_call_ids.get(cell)
        if model_call_id is None or cell not in initial_cells:
            raise HarnessObservationError("code cell output render identity is invalid")
        delivery = ("direct_model", cell[0], cell[1], model_call_id)
        if delivery not in public_exec_deliveries:
            raise HarnessObservationError("code cell output delivery is incomplete")
        legacy_observation = _validate_output_render(
            payload.get("observation"), "direct_model"
        )
        final_observation = public_exec_deliveries[delivery]
        if final_observation is not None and final_observation != legacy_observation:
            raise HarnessObservationError("correlated output render observations disagree")
    started_deliveries = {
        ("direct_model", cell[0], cell[1], code_cell_model_call_ids[cell])
        for cell in code_cell_model_call_ids
    }
    initial_deliveries = {
        ("direct_model", cell[0], cell[1], code_cell_model_call_ids[cell])
        for cell in initial_cells
        if cell in code_cell_model_call_ids
    }
    rendered_public_exec_deliveries = {
        delivery
        for delivery, observation in public_exec_deliveries.items()
        if observation is not None
    }
    if (
        len(started_deliveries) != len(code_cell_model_call_ids)
        or not started_deliveries.issubset(public_exec_deliveries)
    ):
        raise HarnessObservationError("code cell output delivery is incomplete")
    if (
        len(initial_deliveries) != len(initial_cells)
        or not rendered_public_exec_deliveries.issubset(initial_deliveries)
    ):
        raise HarnessObservationError("public exec output render lifecycle is invalid")

    stats: dict[str, int] = {}
    for surface, prefix in (
        ("direct_model", "model_visible"),
        ("code_mode_runtime", "code_mode_runtime"),
    ):
        surface_deliveries = {
            delivery for delivery, delivery_surface in deliveries.items() if delivery_surface == surface
        }
        selected = [
            observation
            for delivery, observation in observations.items()
            if delivery in surface_deliveries
        ]
        stats[f"{prefix}_output_deliveries"] = len(surface_deliveries)
        stats[f"{prefix}_output_renders"] = len(selected)
        stats[f"{prefix}_output_render_missing"] = len(surface_deliveries) - len(selected)
        stats[f"{prefix}_source_text_bytes"] = sum(
            item["source_text_bytes"] for item in selected
        )
        stats[f"{prefix}_returned_text_bytes"] = sum(
            item["returned_text_bytes"] for item in selected
        )
        stats[f"{prefix}_presentation_truncations"] = sum(
            item["presentation_truncated"] for item in selected
        )
        stats[f"{prefix}_collection_omission_events"] = sum(
            item["collection_omitted_bytes"] > 0 for item in selected
        )
        stats[f"{prefix}_collection_omitted_bytes"] = sum(
            item["collection_omitted_bytes"] for item in selected
        )
    return stats


def _surface_output_render_availability(
    tools: Mapping[str, int], prefix: str
) -> str:
    deliveries = tools[f"{prefix}_output_deliveries"]
    renders = tools[f"{prefix}_output_renders"]
    missing = deliveries - renders
    if deliveries == 0 or missing == 0:
        return "measured"
    return "unmeasurable" if renders == 0 else "partial"


def _turn_duration_ms(turn: Mapping[str, Any]) -> int:
    started = turn.get("started_at_unix_ms")
    ended = turn.get("ended_at_unix_ms")
    if _safe_count(started) is None or _safe_count(ended) is None or ended < started:
        raise HarnessObservationError("turn lifecycle duration is invalid")
    return ended - started


def _validate_output_render(value: object, expected_surface: str) -> dict[str, Any]:
    observation = _object(
        value,
        {
            "surface",
            "source_text_bytes",
            "collection_omitted_bytes",
            "requested_max_output_tokens",
            "effective_max_output_tokens",
            "returned_text_bytes",
            "presentation_truncated",
        },
        "output render observation",
    )
    if observation["surface"] != expected_surface:
        raise HarnessObservationError("output render surface is invalid")
    for key in {
        "source_text_bytes",
        "collection_omitted_bytes",
        "returned_text_bytes",
    }:
        _count(observation[key], f"output render observation.{key}")
    for key in {"requested_max_output_tokens", "effective_max_output_tokens"}:
        _optional_count(observation[key], f"output render observation.{key}")
    if not isinstance(observation["presentation_truncated"], bool):
        raise HarnessObservationError("output render truncation state is invalid")
    if expected_surface == "direct_model" and observation["effective_max_output_tokens"] is None:
        raise HarnessObservationError("model-visible render lacks an effective output limit")
    return observation


def _safe_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
