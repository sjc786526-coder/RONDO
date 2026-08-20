"""Reduce native Codex rollout bundles into the body-free Team View schema."""

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .model import PRODUCTS, SCHEMA_VERSION, capability, dump_team_view, validate_team_view


MANIFEST_FILE = "manifest.json"
EVENT_LOG_FILE = "trace.jsonl"
PAYLOADS_DIR = "payloads"
MANIFEST_VERSION = 1
RAW_EVENT_VERSION = 1
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_EVENT_BYTES = 8 * 1024 * 1024
MAX_PAYLOAD_BYTES = 32 * 1024 * 1024

_KNOWN_EVENT_TYPES = {
    "rollout_started",
    "rollout_ended",
    "thread_started",
    "thread_ended",
    "codex_turn_started",
    "codex_turn_ended",
    "inference_started",
    "inference_completed",
    "inference_failed",
    "inference_cancelled",
    "tool_call_started",
    "mcp_tool_call_correlation_assigned",
    "tool_call_runtime_started",
    "tool_call_runtime_ended",
    "tool_call_ended",
    "code_cell_started",
    "code_cell_initial_response",
    "code_cell_ended",
    "compaction_request_started",
    "compaction_request_completed",
    "compaction_request_failed",
    "compaction_installed",
    "agent_result_observed",
    "protocol_event_observed",
}
_PAYLOAD_REF_FIELDS = {
    "thread_started": (("metadata_payload", False),),
    "inference_started": (("request_payload", True),),
    "inference_completed": (("response_payload", True),),
    "inference_failed": (("partial_response_payload", False),),
    "inference_cancelled": (("partial_response_payload", False),),
    "tool_call_started": (("invocation_payload", False),),
    "tool_call_runtime_started": (("runtime_payload", True),),
    "tool_call_runtime_ended": (("runtime_payload", True),),
    "tool_call_ended": (("result_payload", False),),
    "code_cell_initial_response": (("response_payload", False),),
    "code_cell_ended": (("response_payload", False),),
    "compaction_request_started": (("request_payload", True),),
    "compaction_request_completed": (("response_payload", True),),
    "compaction_installed": (("checkpoint_payload", True),),
    "agent_result_observed": (("carried_payload", False),),
    "protocol_event_observed": (("event_payload", True),),
}
_PAYLOAD_KINDS = {
    "inference_request",
    "inference_response",
    "compaction_request",
    "compaction_checkpoint",
    "compaction_response",
    "tool_invocation",
    "tool_result",
    "tool_runtime_event",
    "terminal_runtime_event",
    "protocol_event",
    "session_metadata",
    "agent_result",
}
_TERMINAL_KINDS = {"exec_command", "write_stdin"}
_INTERACTION_KINDS = {"spawn_agent", "assign_agent_task", "send_message", "close_agent"}
_USAGE_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
_PROJECTION_HEADER = re.compile(
    r"^team_instance=(\S+) revision=(\d+)(?: availability_epoch=\d+)? "
    r"you=\S+ role=(?:root|member)$"
)
_SAFE_REASON = re.compile(r"^[a-z0-9_:-]+$")
_ROLLOUT_STATUSES = {"running", "completed", "failed", "aborted"}
_EXECUTION_STATUSES = {"running", "completed", "failed", "cancelled", "aborted"}
_CODE_CELL_STATUSES = {"starting", "running", "yielded", "completed", "failed", "terminated"}


class BundleError(ValueError):
    """Raised when a native rollout bundle is malformed or unsupported."""


def _validate_raw_event_shape(event: dict[str, Any]) -> None:
    """Mirror the required fields of the frozen v1 Rust raw-event enum."""

    payload = event["payload"]
    kind = payload["type"]
    required_id_fields = {
        "rollout_started": ("trace_id", "root_thread_id"),
        "thread_started": ("thread_id", "agent_path"),
        "thread_ended": ("thread_id",),
        "codex_turn_started": ("codex_turn_id", "thread_id"),
        "codex_turn_ended": ("codex_turn_id",),
        "inference_started": (
            "inference_call_id",
            "thread_id",
            "codex_turn_id",
            "model",
            "provider_name",
        ),
        "inference_completed": ("inference_call_id",),
        "inference_failed": ("inference_call_id",),
        "inference_cancelled": ("inference_call_id",),
        "tool_call_started": ("tool_call_id",),
        "mcp_tool_call_correlation_assigned": ("tool_call_id", "mcp_call_id"),
        "tool_call_runtime_started": ("tool_call_id",),
        "tool_call_runtime_ended": ("tool_call_id",),
        "tool_call_ended": ("tool_call_id",),
        "code_cell_started": ("runtime_cell_id", "model_visible_call_id"),
        "code_cell_initial_response": ("runtime_cell_id",),
        "code_cell_ended": ("runtime_cell_id",),
        "compaction_request_started": (
            "compaction_id",
            "compaction_request_id",
            "thread_id",
            "codex_turn_id",
            "model",
            "provider_name",
        ),
        "compaction_request_completed": ("compaction_id", "compaction_request_id"),
        "compaction_request_failed": ("compaction_id", "compaction_request_id"),
        "compaction_installed": ("compaction_id",),
        "agent_result_observed": (
            "edge_id",
            "child_thread_id",
            "child_codex_turn_id",
            "parent_thread_id",
        ),
        "protocol_event_observed": ("event_type",),
    }
    for field in required_id_fields.get(kind, ()):
        if not _is_nonempty_string(payload.get(field)):
            raise BundleError("rollout trace event is missing a required identity")

    required_text_fields = {
        "inference_failed": ("error",),
        "inference_cancelled": ("reason",),
        "code_cell_started": ("source_js",),
        "compaction_request_failed": ("error",),
        "agent_result_observed": ("message",),
    }
    for field in required_text_fields.get(kind, ()):
        if not isinstance(payload.get(field), str):
            raise BundleError("rollout trace event is missing required text")

    optional_strings = {
        "inference_completed": ("response_id", "upstream_request_id"),
        "inference_failed": ("upstream_request_id",),
        "inference_cancelled": ("upstream_request_id",),
        "tool_call_started": ("model_visible_call_id", "code_mode_runtime_tool_id"),
    }
    for field in optional_strings.get(kind, ()):
        if payload.get(field) is not None and not isinstance(payload[field], str):
            raise BundleError("rollout trace event has invalid optional text")

    status_fields = {
        "rollout_ended": _ROLLOUT_STATUSES,
        "thread_ended": _ROLLOUT_STATUSES,
        "codex_turn_ended": _EXECUTION_STATUSES,
        "tool_call_runtime_ended": _EXECUTION_STATUSES,
        "tool_call_ended": _EXECUTION_STATUSES,
        "code_cell_initial_response": _CODE_CELL_STATUSES,
        "code_cell_ended": _CODE_CELL_STATUSES,
    }
    allowed_statuses = status_fields.get(kind)
    if allowed_statuses is not None and payload.get("status") not in allowed_statuses:
        raise BundleError("rollout trace event has an invalid native status")

    if kind == "tool_call_started":
        _validate_tool_start_shape(payload)

    payload_thread = payload.get("thread_id")
    if payload_thread is not None and event.get("thread_id") not in {None, payload_thread}:
        raise BundleError("rollout trace event envelope thread identity disagrees")
    payload_turn = payload.get("codex_turn_id")
    if payload_turn is not None and event.get("codex_turn_id") not in {None, payload_turn}:
        raise BundleError("rollout trace event envelope turn identity disagrees")


def _validate_tool_start_shape(payload: dict[str, Any]) -> None:
    requester = payload.get("requester")
    if not isinstance(requester, dict) or requester.get("type") not in {"model", "code_cell"}:
        raise BundleError("tool requester is not a native variant")
    if requester["type"] == "code_cell" and not _is_nonempty_string(requester.get("runtime_cell_id")):
        raise BundleError("code-cell tool requester has no runtime identity")

    tool_kind = payload.get("kind")
    simple_kinds = {
        "exec_command",
        "write_stdin",
        "apply_patch",
        "web",
        "image_generation",
        "spawn_agent",
        "assign_agent_task",
        "send_message",
        "wait_agent",
        "close_agent",
    }
    if not isinstance(tool_kind, dict) or tool_kind.get("type") not in simple_kinds | {"mcp", "other"}:
        raise BundleError("tool kind is not a native variant")
    if tool_kind["type"] == "mcp" and not all(
        _is_nonempty_string(tool_kind.get(field)) for field in ("server", "tool")
    ):
        raise BundleError("MCP tool kind is missing identity")
    if tool_kind["type"] == "other" and not _is_nonempty_string(tool_kind.get("name")):
        raise BundleError("other tool kind is missing its name")

    summary = payload.get("summary")
    if not isinstance(summary, dict) or summary.get("type") not in {
        "terminal",
        "agent",
        "wait_agent",
        "generic",
    }:
        raise BundleError("tool summary is not a native variant")
    summary_type = summary["type"]
    if summary_type == "terminal" and not _is_nonempty_string(summary.get("operation_id")):
        raise BundleError("terminal tool summary is missing identity")
    if summary_type == "agent" and not all(
        isinstance(summary.get(field), str)
        for field in ("target_agent_path", "message_preview")
    ):
        raise BundleError("agent tool summary is missing required text")
    if summary_type == "agent" and summary.get("task_name") is not None and not isinstance(
        summary["task_name"], str
    ):
        raise BundleError("agent tool summary has an invalid task name")
    if summary_type == "wait_agent":
        if summary.get("target_agent_path") is not None and not isinstance(summary["target_agent_path"], str):
            raise BundleError("wait tool summary has an invalid target")
        timeout = summary.get("timeout_ms")
        if timeout is not None and (not _is_int(timeout) or timeout < 0):
            raise BundleError("wait tool summary has an invalid timeout")
    if summary_type == "generic":
        if not isinstance(summary.get("label"), str):
            raise BundleError("generic tool summary is missing its label")
        for field in ("input_preview", "output_preview"):
            if summary.get(field) is not None and not isinstance(summary[field], str):
                raise BundleError("generic tool summary has invalid preview text")


def reduce_bundle(bundle_dir: Path, product: str) -> dict[str, Any]:
    """Read one native bundle using an explicit product identity."""

    if product not in PRODUCTS:
        raise BundleError("unsupported product identity")
    reader = _BundleReader(bundle_dir)
    reducer = _Reducer(reader, product)
    return reducer.reduce()


def write_team_view(bundle_dir: Path, product: str, output_path: Path) -> dict[str, Any]:
    """Reduce a bundle and write deterministic JSON to a caller-selected path."""

    view = reduce_bundle(bundle_dir, product)
    target = Path(output_path)
    target.write_bytes(dump_team_view(view))
    return view


class _BundleReader:
    def __init__(self, bundle_dir: Path) -> None:
        supplied = Path(bundle_dir)
        if supplied.is_symlink() or not supplied.is_dir():
            raise BundleError("rollout trace bundle is not a regular directory")
        self.bundle = supplied.resolve()
        self.payloads: dict[str, tuple[dict[str, Any], object]] = {}
        self.events: list[dict[str, Any]] = []
        self.raw_event_versions: set[int] = set()
        self.manifest = self._read_manifest()
        self._read_events()

    def _read_manifest(self) -> dict[str, Any]:
        manifest = self._read_json_object(
            self.bundle / MANIFEST_FILE,
            label="rollout trace manifest",
            limit=MAX_MANIFEST_BYTES,
        )
        if manifest.get("schema_version") != MANIFEST_VERSION:
            raise BundleError("unsupported rollout trace manifest schema")
        for key in ("trace_id", "rollout_id", "root_thread_id"):
            if not _is_nonempty_string(manifest.get(key)):
                raise BundleError("rollout trace manifest is missing required identity")
        if not _is_int(manifest.get("started_at_unix_ms")):
            raise BundleError("rollout trace manifest has an invalid start time")
        if manifest.get("raw_event_log") != EVENT_LOG_FILE:
            raise BundleError("rollout trace manifest names an unexpected event log")
        if manifest.get("payloads_dir") != PAYLOADS_DIR:
            raise BundleError("rollout trace manifest names an unexpected payload directory")
        return manifest

    def _read_events(self) -> None:
        event_log = self.bundle / EVENT_LOG_FILE
        if event_log.is_symlink() or not event_log.is_file():
            raise BundleError("rollout trace event log is missing")
        try:
            lines = event_log.read_text("utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise BundleError("rollout trace event log is unreadable") from exc

        seen_seq: set[int] = set()
        previous_seq = 0
        for line in lines:
            if not line.strip():
                continue
            if len(line.encode("utf-8")) > MAX_EVENT_BYTES:
                raise BundleError("rollout trace event is implausibly large")
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BundleError("rollout trace event is not JSON") from exc
            if not isinstance(event, dict):
                raise BundleError("rollout trace event is not an object")
            if event.get("schema_version") != RAW_EVENT_VERSION:
                raise BundleError("unsupported rollout trace event schema")
            seq = event.get("seq")
            if not _is_int(seq) or seq < 1 or seq in seen_seq or seq <= previous_seq:
                raise BundleError("rollout trace event sequence is invalid")
            seen_seq.add(seq)
            previous_seq = seq
            self.raw_event_versions.add(RAW_EVENT_VERSION)
            if event.get("rollout_id") != self.manifest["rollout_id"]:
                raise BundleError("rollout trace event belongs to another rollout")
            if not _is_int(event.get("wall_time_unix_ms")):
                raise BundleError("rollout trace event has an invalid timestamp")
            for identity in (event.get("thread_id"), event.get("codex_turn_id")):
                if identity is not None and not _is_nonempty_string(identity):
                    raise BundleError("rollout trace event has an invalid identity")
            payload = event.get("payload")
            if not isinstance(payload, dict):
                raise BundleError("rollout trace event has no payload")
            kind = payload.get("type")
            if kind == "other" or kind not in _KNOWN_EVENT_TYPES:
                raise BundleError("unsupported rollout trace event type")
            _validate_raw_event_shape(event)
            for field, required in _PAYLOAD_REF_FIELDS.get(kind, ()):
                ref = payload.get(field)
                if ref is None:
                    if required:
                        raise BundleError("rollout trace event is missing a required payload")
                    continue
                self._register_payload(ref)
            self.events.append(event)
        if not self.events:
            raise BundleError("rollout trace event log is empty")

    def _register_payload(self, ref: object) -> None:
        if not isinstance(ref, dict):
            raise BundleError("raw payload reference is not an object")
        raw_id = ref.get("raw_payload_id")
        relative = ref.get("path")
        kind = ref.get("kind")
        if not _is_nonempty_string(raw_id) or not _is_nonempty_string(relative):
            raise BundleError("raw payload reference is missing identity")
        if not isinstance(kind, dict) or kind.get("type") not in _PAYLOAD_KINDS:
            raise BundleError("raw payload reference has an unsupported kind")
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise BundleError("raw payload reference escapes the bundle")
        if not relative_path.parts or relative_path.parts[0] != PAYLOADS_DIR:
            raise BundleError("raw payload reference is outside the payload directory")
        target = (self.bundle / relative_path).resolve()
        if not target.is_relative_to(self.bundle):
            raise BundleError("raw payload reference escapes the bundle")
        prior = self.payloads.get(raw_id)
        canonical_ref = {
            "raw_payload_id": raw_id,
            "kind": {"type": kind["type"]},
            "path": relative_path.as_posix(),
        }
        if prior is not None:
            if prior[0] != canonical_ref:
                raise BundleError("raw payload identity is reused inconsistently")
            return
        value = self._read_json_value(target, label="rollout trace payload", limit=MAX_PAYLOAD_BYTES)
        self.payloads[raw_id] = (canonical_ref, value)

    def load_ref(self, ref: object) -> object:
        if ref is None:
            return None
        if not isinstance(ref, dict) or not _is_nonempty_string(ref.get("raw_payload_id")):
            raise BundleError("raw payload reference is invalid")
        stored = self.payloads.get(ref["raw_payload_id"])
        if stored is None:
            raise BundleError("raw payload reference was not registered")
        return stored[1]

    @staticmethod
    def _read_json_object(path: Path, *, label: str, limit: int) -> dict[str, Any]:
        value = _BundleReader._read_json_value(path, label=label, limit=limit)
        if not isinstance(value, dict):
            raise BundleError(f"{label} is not an object")
        return value

    @staticmethod
    def _read_json_value(path: Path, *, label: str, limit: int) -> object:
        if path.is_symlink() or not path.is_file():
            raise BundleError(f"{label} is not a regular file")
        if path.stat().st_size > limit:
            raise BundleError(f"{label} is implausibly large")
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise BundleError(f"{label} is unreadable") from exc


class _Reducer:
    def __init__(self, reader: _BundleReader, product: str) -> None:
        self.reader = reader
        self.product = product
        self.agents: dict[str, dict[str, Any]] = {}
        self.turns: dict[str, dict[str, Any]] = {}
        self.inferences: dict[str, dict[str, Any]] = {}
        self.tools: dict[str, dict[str, Any]] = {}
        self.terminal: dict[str, dict[str, Any]] = {}
        self.interactions: dict[str, dict[str, Any]] = {}
        self.tool_invocations: dict[str, dict[str, Any] | None] = {}
        self.projections: list[dict[str, Any]] = []
        self.projection_shape_supported = 0
        self.projection_shape_unsupported = 0
        self.team = _TeamAccumulator() if product == "rondo-multi" else None
        self.rollout_started = False
        self.rollout_ended = False
        self.rollout_status = "running"
        self.rollout_ended_at: int | None = None
        self.tool_name_missing = False
        self.terminal_runtime_missing = False
        self.terminal_runtime_started: set[str] = set()
        self.mcp_correlations: set[str] = set()
        self.code_cells: dict[tuple[str, str], dict[str, Any]] = {}
        self.compaction_requests: dict[str, dict[str, Any]] = {}
        self.compaction_installs: set[str] = set()

    def reduce(self) -> dict[str, Any]:
        for event in self.reader.events:
            self._apply(event)
        self._validate_references()
        return self._build_view()

    def _apply(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        kind = payload["type"]
        seq = event["seq"]
        timestamp = event["wall_time_unix_ms"]
        if kind == "rollout_started":
            if self.rollout_started:
                raise BundleError("rollout trace starts more than once")
            if (
                payload.get("trace_id") != self.reader.manifest["trace_id"]
                or payload.get("root_thread_id") != self.reader.manifest["root_thread_id"]
            ):
                raise BundleError("rollout start identity disagrees with the manifest")
            self.rollout_started = True
        elif kind == "rollout_ended":
            if self.rollout_ended:
                raise BundleError("rollout trace ends more than once")
            self.rollout_ended = True
            self.rollout_status = _execution_status(payload.get("status"))
            self.rollout_ended_at = timestamp
        elif kind == "thread_started":
            self._start_thread(event)
        elif kind == "thread_ended":
            self._end_window(self.agents, payload.get("thread_id"), seq, timestamp, payload.get("status"), "thread")
        elif kind == "codex_turn_started":
            self._start_turn(event)
        elif kind == "codex_turn_ended":
            self._end_window(self.turns, payload.get("codex_turn_id"), seq, timestamp, payload.get("status"), "turn")
        elif kind == "inference_started":
            self._start_inference(event)
        elif kind in {"inference_completed", "inference_failed", "inference_cancelled"}:
            self._end_inference(event)
        elif kind == "tool_call_started":
            self._start_tool(event)
        elif kind == "mcp_tool_call_correlation_assigned":
            self._mcp_correlation(event)
        elif kind in {"tool_call_runtime_started", "tool_call_runtime_ended"}:
            self._tool_runtime(event)
        elif kind == "tool_call_ended":
            self._end_tool(event)
        elif kind in {"code_cell_started", "code_cell_initial_response", "code_cell_ended"}:
            self._code_cell_lifecycle(event)
        elif kind.startswith("compaction_"):
            self._compaction_lifecycle(event)
        elif kind == "agent_result_observed":
            self._agent_result(event)

    def _start_thread(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        thread_id = payload.get("thread_id")
        if not _is_nonempty_string(thread_id) or thread_id in self.agents:
            raise BundleError("thread start identity is invalid or duplicated")
        if event.get("thread_id") not in {None, thread_id}:
            raise BundleError("thread start envelope identity disagrees")
        agent_path = payload.get("agent_path")
        if not _is_nonempty_string(agent_path):
            raise BundleError("thread start has no stable agent path")
        parent: str | None = None
        metadata = self.reader.load_ref(payload.get("metadata_payload"))
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise BundleError("thread metadata is not an object")
            if metadata.get("thread_id") != thread_id or metadata.get("agent_path") != agent_path:
                raise BundleError("thread metadata identity disagrees")
            parent = _parent_thread_id(metadata.get("session_source"))
        root = thread_id == self.reader.manifest["root_thread_id"]
        if root and parent is not None:
            raise BundleError("root thread names a parent")
        self.agents[thread_id] = {
            "agent_id": thread_id,
            "agent_path": agent_path,
            "parent_agent_id": parent,
            "role": "root" if root else "spawned",
            "started_seq": event["seq"],
            "started_at_unix_ms": event["wall_time_unix_ms"],
            "ended_seq": None,
            "ended_at_unix_ms": None,
            "status": "running",
        }

    def _start_turn(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        turn_id = payload.get("codex_turn_id")
        agent_id = payload.get("thread_id")
        if not _is_nonempty_string(turn_id) or turn_id in self.turns or not _is_nonempty_string(agent_id):
            raise BundleError("turn start identity is invalid or duplicated")
        self.turns[turn_id] = {
            "turn_id": turn_id,
            "agent_id": agent_id,
            "started_seq": event["seq"],
            "started_at_unix_ms": event["wall_time_unix_ms"],
            "ended_seq": None,
            "ended_at_unix_ms": None,
            "status": "running",
        }

    def _start_inference(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        inference_id = payload.get("inference_call_id")
        agent_id = payload.get("thread_id")
        turn_id = payload.get("codex_turn_id")
        if (
            not _is_nonempty_string(inference_id)
            or inference_id in self.inferences
            or not _is_nonempty_string(agent_id)
            or not _is_nonempty_string(turn_id)
            or not _is_nonempty_string(payload.get("model"))
            or not _is_nonempty_string(payload.get("provider_name"))
        ):
            raise BundleError("inference start identity is invalid or duplicated")
        self.inferences[inference_id] = {
            "inference_id": inference_id,
            "agent_id": agent_id,
            "turn_id": turn_id,
            "model": payload["model"],
            "provider": payload["provider_name"],
            "started_seq": event["seq"],
            "started_at_unix_ms": event["wall_time_unix_ms"],
            "ended_seq": None,
            "ended_at_unix_ms": None,
            "status": "running",
            "usage": None,
        }
        request = self.reader.load_ref(payload.get("request_payload"))
        supported, projection = _extract_projection(request, inference_id, event["seq"])
        if supported:
            self.projection_shape_supported += 1
        else:
            self.projection_shape_unsupported += 1
        if projection is not None:
            self.projections.append(projection)

    def _end_inference(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        inference_id = payload.get("inference_call_id")
        if inference_id not in self.inferences:
            raise BundleError("inference terminal event references an unknown inference")
        row = self.inferences[inference_id]
        if row["ended_seq"] is not None:
            raise BundleError("inference has more than one terminal event")
        if event.get("thread_id") not in {None, row["agent_id"]} or event.get("codex_turn_id") not in {None, row["turn_id"]}:
            raise BundleError("inference terminal envelope identity disagrees")
        row["ended_seq"] = event["seq"]
        row["ended_at_unix_ms"] = event["wall_time_unix_ms"]
        row["status"] = {
            "inference_completed": "completed",
            "inference_failed": "failed",
            "inference_cancelled": "cancelled",
        }[payload["type"]]
        response_ref = payload.get("response_payload") or payload.get("partial_response_payload")
        response = self.reader.load_ref(response_ref)
        if isinstance(response, dict):
            row["usage"] = _extract_usage(response.get("token_usage"))

    def _start_tool(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        tool_id = payload.get("tool_call_id")
        if not _is_nonempty_string(tool_id) or tool_id in self.tools:
            raise BundleError("tool start identity is invalid or duplicated")
        agent_id = event.get("thread_id")
        if not _is_nonempty_string(agent_id):
            raise BundleError("tool start has no thread identity")
        invocation = self.reader.load_ref(payload.get("invocation_payload"))
        if invocation is not None and not isinstance(invocation, dict):
            raise BundleError("tool invocation payload is not an object")
        name = invocation.get("tool_name") if isinstance(invocation, dict) else None
        namespace = invocation.get("tool_namespace") if isinstance(invocation, dict) else None
        kind = _tag(payload.get("kind"))
        if not _is_nonempty_string(name):
            name = kind
            self.tool_name_missing = True
        if namespace is not None and not isinstance(namespace, str):
            raise BundleError("tool namespace is invalid")
        requester = _tag(payload.get("requester"))
        if requester not in {"model", "code_cell"}:
            raise BundleError("tool requester is unsupported")
        if requester == "code_cell":
            runtime_id = payload["requester"]["runtime_cell_id"]
            if (agent_id, runtime_id) not in self.code_cells:
                raise BundleError("code-cell tool references an unknown runtime cell")
        self.tool_invocations[tool_id] = invocation
        self.tools[tool_id] = {
            "tool_id": tool_id,
            "agent_id": agent_id,
            "turn_id": event.get("codex_turn_id"),
            "name": name,
            "namespace": namespace,
            "requester": requester,
            "kind": kind,
            "started_seq": event["seq"],
            "started_at_unix_ms": event["wall_time_unix_ms"],
            "ended_seq": None,
            "ended_at_unix_ms": None,
            "status": "running",
        }
        if kind in _TERMINAL_KINDS:
            operation_id = f"terminal:{tool_id}"
            self.terminal[tool_id] = {
                "operation_id": operation_id,
                "terminal_id": None,
                "tool_id": tool_id,
                "agent_id": agent_id,
                "kind": kind,
                "started_seq": event["seq"],
                "started_at_unix_ms": event["wall_time_unix_ms"],
                "ended_seq": None,
                "ended_at_unix_ms": None,
                "status": "running",
                "exit_code": None,
                "duration_ms": None,
            }

    def _tool_runtime(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        tool_id = payload.get("tool_call_id")
        tool = self.tools.get(tool_id)
        if tool is None:
            raise BundleError("tool runtime event references an unknown tool")
        if event.get("thread_id") not in {None, tool["agent_id"]} or event.get("codex_turn_id") not in {None, tool["turn_id"]}:
            raise BundleError("tool runtime envelope identity disagrees")
        runtime = self.reader.load_ref(payload.get("runtime_payload"))
        if not isinstance(runtime, dict):
            raise BundleError("tool runtime payload is not an object")
        if tool["kind"] in _TERMINAL_KINDS:
            terminal = self.terminal[tool_id]
            if payload["type"] == "tool_call_runtime_started":
                if tool_id in self.terminal_runtime_started:
                    raise BundleError("terminal tool has more than one runtime start")
                self.terminal_runtime_started.add(tool_id)
                terminal["started_seq"] = event["seq"]
                terminal["started_at_unix_ms"] = event["wall_time_unix_ms"]
            terminal_id = runtime.get("process_id")
            if _is_nonempty_string(terminal_id):
                terminal["terminal_id"] = terminal_id
            if payload["type"] == "tool_call_runtime_ended":
                if tool_id not in self.terminal_runtime_started:
                    self.terminal_runtime_missing = True
                terminal["ended_seq"] = event["seq"]
                terminal["ended_at_unix_ms"] = event["wall_time_unix_ms"]
                terminal["status"] = _execution_status(runtime.get("status"))
                terminal["exit_code"] = runtime.get("exit_code") if _is_int(runtime.get("exit_code")) else None
                terminal["duration_ms"] = _duration_ms(runtime.get("duration"))
        if payload["type"] == "tool_call_runtime_ended" and tool["kind"] in _INTERACTION_KINDS:
            target = runtime.get("agent_thread_id")
            if target is None:
                target = runtime.get("receiver_thread_id") or runtime.get("new_thread_id")
            if _is_nonempty_string(target):
                interaction_id = f"edge:tool:{tool_id}"
                self.interactions[interaction_id] = {
                    "interaction_id": interaction_id,
                    "kind": tool["kind"],
                    "source_agent_id": tool["agent_id"],
                    "target_agent_id": target,
                    "tool_id": tool_id,
                    "started_seq": tool["started_seq"],
                    "started_at_unix_ms": tool["started_at_unix_ms"],
                    "ended_seq": event["seq"],
                    "ended_at_unix_ms": event["wall_time_unix_ms"],
                    "status": "completed",
                }

    def _mcp_correlation(self, event: dict[str, Any]) -> None:
        tool_id = event["payload"]["tool_call_id"]
        if tool_id not in self.tools:
            raise BundleError("MCP correlation references an unknown tool")
        if tool_id in self.mcp_correlations:
            raise BundleError("tool has more than one MCP correlation")
        self.mcp_correlations.add(tool_id)

    def _code_cell_lifecycle(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        runtime_id = payload["runtime_cell_id"]
        thread_id = event.get("thread_id")
        turn_id = event.get("codex_turn_id")
        if not _is_nonempty_string(thread_id) or not _is_nonempty_string(turn_id):
            raise BundleError("code cell event is missing its envelope identity")
        turn = self.turns.get(turn_id)
        if thread_id not in self.agents or turn is None or turn["agent_id"] != thread_id:
            raise BundleError("code cell event references an unknown thread or turn")
        key = (thread_id, runtime_id)
        kind = payload["type"]
        if kind == "code_cell_started":
            if key in self.code_cells:
                raise BundleError("code cell start identity is duplicated")
            self.code_cells[key] = {"initial": False, "ended": False, "turn_id": turn_id}
            return
        cell = self.code_cells.get(key)
        if cell is None or cell["turn_id"] != turn_id:
            raise BundleError("code cell lifecycle references an unknown cell")
        if kind == "code_cell_initial_response":
            if cell["initial"] or cell["ended"]:
                raise BundleError("code cell initial response is duplicated or late")
            cell["initial"] = True
        else:
            if cell["ended"]:
                raise BundleError("code cell end is duplicated")
            cell["ended"] = True

    def _compaction_lifecycle(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        kind = payload["type"]
        if kind == "compaction_request_started":
            request_id = payload["compaction_request_id"]
            thread_id = payload["thread_id"]
            turn_id = payload["codex_turn_id"]
            turn = self.turns.get(turn_id)
            if thread_id not in self.agents or turn is None or turn["agent_id"] != thread_id:
                raise BundleError("compaction request references an unknown thread or turn")
            if event.get("thread_id") not in {None, thread_id} or event.get("codex_turn_id") not in {None, turn_id}:
                raise BundleError("compaction request envelope identity disagrees")
            if request_id in self.compaction_requests:
                raise BundleError("compaction request start identity is duplicated")
            self.compaction_requests[request_id] = {
                "compaction_id": payload["compaction_id"],
                "ended": False,
            }
            return
        if kind in {"compaction_request_completed", "compaction_request_failed"}:
            request = self.compaction_requests.get(payload["compaction_request_id"])
            if request is None or request["ended"]:
                raise BundleError("compaction completion references an unknown or ended request")
            if request["compaction_id"] != payload["compaction_id"]:
                raise BundleError("compaction completion identity disagrees")
            request["ended"] = True
            return
        compaction_id = payload["compaction_id"]
        thread_id = event.get("thread_id")
        turn_id = event.get("codex_turn_id")
        turn = self.turns.get(turn_id) if isinstance(turn_id, str) else None
        if not _is_nonempty_string(thread_id) or turn is None or turn["agent_id"] != thread_id:
            raise BundleError("compaction install references an unknown thread or turn")
        if compaction_id in self.compaction_installs:
            raise BundleError("compaction install identity is duplicated")
        self.compaction_installs.add(compaction_id)

    def _end_tool(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        tool_id = payload.get("tool_call_id")
        tool = self.tools.get(tool_id)
        if tool is None:
            raise BundleError("tool terminal event references an unknown tool")
        if tool["ended_seq"] is not None:
            raise BundleError("tool has more than one terminal event")
        if event.get("thread_id") not in {None, tool["agent_id"]} or event.get("codex_turn_id") not in {None, tool["turn_id"]}:
            raise BundleError("tool terminal envelope identity disagrees")
        tool["ended_seq"] = event["seq"]
        tool["ended_at_unix_ms"] = event["wall_time_unix_ms"]
        tool["status"] = _execution_status(payload.get("status"))
        terminal = self.terminal.get(tool_id)
        if terminal is not None and tool_id not in self.terminal_runtime_started:
            self.terminal_runtime_missing = True
        if terminal is not None and terminal["ended_seq"] is None:
            terminal["ended_seq"] = event["seq"]
            terminal["ended_at_unix_ms"] = event["wall_time_unix_ms"]
            terminal["status"] = tool["status"]
            self.terminal_runtime_missing = True
        if self.team is not None and tool["name"].startswith("team_"):
            result_payload = self.reader.load_ref(payload.get("result_payload"))
            result = _unwrap_tool_result(result_payload)
            self.team.observe_tool(
                tool,
                self.tool_invocations.get(tool_id),
                result,
                event["seq"],
            )

    def _agent_result(self, event: dict[str, Any]) -> None:
        payload = event["payload"]
        edge_id = payload.get("edge_id")
        child = payload.get("child_thread_id")
        child_turn = payload.get("child_codex_turn_id")
        parent = payload.get("parent_thread_id")
        if not all(_is_nonempty_string(value) for value in (edge_id, child, child_turn, parent)):
            raise BundleError("agent result edge has invalid identity")
        if event.get("thread_id") not in {None, child} or event.get("codex_turn_id") not in {None, child_turn}:
            raise BundleError("agent result envelope identity disagrees")
        turn = self.turns.get(child_turn)
        if turn is None or turn["agent_id"] != child:
            raise BundleError("agent result references an unknown child turn")
        if edge_id in self.interactions:
            raise BundleError("agent interaction identity is duplicated")
        self.interactions[edge_id] = {
            "interaction_id": edge_id,
            "kind": "agent_result",
            "source_agent_id": child,
            "target_agent_id": parent,
            "tool_id": None,
            "started_seq": event["seq"],
            "started_at_unix_ms": event["wall_time_unix_ms"],
            "ended_seq": event["seq"],
            "ended_at_unix_ms": event["wall_time_unix_ms"],
            "status": "completed",
        }

    @staticmethod
    def _end_window(
        rows: dict[str, dict[str, Any]],
        identity: object,
        seq: int,
        timestamp: int,
        status: object,
        label: str,
    ) -> None:
        row = rows.get(identity) if isinstance(identity, str) else None
        if row is None or row["ended_seq"] is not None:
            raise BundleError(f"{label} terminal event has invalid identity")
        row["ended_seq"] = seq
        row["ended_at_unix_ms"] = timestamp
        row["status"] = _execution_status(status)

    def _validate_references(self) -> None:
        root = self.reader.manifest["root_thread_id"]
        if not self.rollout_started or root not in self.agents:
            raise BundleError("rollout trace is missing its root thread")
        for agent in self.agents.values():
            parent = agent["parent_agent_id"]
            if parent is not None and parent not in self.agents:
                raise BundleError("thread metadata references an unknown parent")
        for turn in self.turns.values():
            if turn["agent_id"] not in self.agents:
                raise BundleError("turn references an unknown thread")
        for inference in self.inferences.values():
            if inference["agent_id"] not in self.agents or inference["turn_id"] not in self.turns:
                raise BundleError("inference references an unknown thread or turn")
        for tool in self.tools.values():
            if tool["agent_id"] not in self.agents:
                raise BundleError("tool references an unknown thread")
            if tool["turn_id"] is not None and tool["turn_id"] not in self.turns:
                raise BundleError("tool references an unknown turn")
        for edge in self.interactions.values():
            if edge["source_agent_id"] not in self.agents or edge["target_agent_id"] not in self.agents:
                raise BundleError("interaction references an unknown thread")

    def _build_view(self) -> dict[str, Any]:
        agents = _sort_rows(self.agents.values(), "started_seq", "agent_id")
        turns = _sort_rows(self.turns.values(), "started_seq", "turn_id")
        inferences = _sort_rows(self.inferences.values(), "started_seq", "inference_id")
        tools = _sort_rows(self.tools.values(), "started_seq", "tool_id")
        terminal = _sort_rows(self.terminal.values(), "started_seq", "operation_id")
        interactions = _sort_rows(self.interactions.values(), "started_seq", "interaction_id")
        team_view, team_availability = self._team_view()
        availability = self._common_availability(tools, terminal, interactions)
        availability.update(team_availability)
        usage = _sum_usage(inferences)
        start = self.reader.manifest["started_at_unix_ms"]
        end = self.rollout_ended_at
        summary = {
            "agent_count": len(agents),
            "turn_count": len(turns),
            "inference_count": len(inferences),
            "tool_count": len(tools),
            "terminal_count": len(terminal),
            "interaction_count": len(interactions),
            "wait_count": sum(tool["kind"] == "wait_agent" for tool in tools),
            "team_event_count": len(team_view["events"]) if team_view is not None else 0,
            "team_version_count": len(team_view["versions"]) if team_view is not None else 0,
            "team_route_count": len(team_view["routes"]) if team_view is not None else 0,
            "team_fact_count": len(team_view["facts"]) if team_view is not None else 0,
            "started_at_unix_ms": start,
            "ended_at_unix_ms": end,
            "duration_ms": max(0, end - start) if end is not None else None,
            "usage": usage,
        }
        view = {
            "schema_version": SCHEMA_VERSION,
            "source": {
                "product": self.product,
                "trace_schema": {
                    "manifest_version": self.reader.manifest["schema_version"],
                    "raw_event_versions": sorted(self.reader.raw_event_versions),
                    "reduced_state_version": None,
                },
                "trace_id": self.reader.manifest["trace_id"],
                "rollout_id": self.reader.manifest["rollout_id"],
                "root_thread_id": self.reader.manifest["root_thread_id"],
            },
            "availability": availability,
            "agents": agents,
            "turns": turns,
            "inferences": inferences,
            "tools": tools,
            "terminal": terminal,
            "interactions": interactions,
            "team": team_view,
            "summary": summary,
        }
        validate_team_view(view)
        return view

    def _common_availability(
        self,
        tools: list[dict[str, Any]],
        terminal: list[dict[str, Any]],
        interactions: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        usage_reasons = {
            f"{inference['status']}_inference_usage_missing"
            for inference in self.inferences.values()
            if inference["usage"] is None
        }
        expected_edges = {
            tool["tool_id"]
            for tool in tools
            if tool["kind"] in _INTERACTION_KINDS and tool["status"] == "completed"
        }
        observed_edges = {edge["tool_id"] for edge in interactions if edge["tool_id"] is not None}
        return {
            "agents": capability("available"),
            "turns": capability("available"),
            "inferences": capability("available"),
            "usage": capability("partial", *usage_reasons)
            if usage_reasons
            else capability("available"),
            "tools": capability("partial", "tool_invocation_name_missing")
            if self.tool_name_missing
            else capability("available"),
            "terminal": capability("partial", "terminal_runtime_metadata_missing")
            if terminal and self.terminal_runtime_missing
            else capability("available"),
            "interactions": capability("partial", "agent_interaction_target_missing")
            if expected_edges - observed_edges
            else capability("available"),
            "timing": capability("available"),
        }

    def _team_view(self) -> tuple[dict[str, Any] | None, dict[str, dict[str, Any]]]:
        if self.team is None:
            rows = {
                name: capability("not_applicable", "codex_has_no_team_state")
                for name in (
                    "team_revisions",
                    "team_projections",
                    "team_events_versions",
                    "team_routes",
                    "team_facts",
                )
            }
            return None, rows
        self.team.projections = sorted(
            self.projections,
            key=lambda row: (row["seq"], row["inference_id"]),
        )
        return self.team.finish(
            projection_supported=self.projection_shape_supported,
            projection_unsupported=self.projection_shape_unsupported,
        )


class _TeamAccumulator:
    def __init__(self) -> None:
        self.revisions: list[dict[str, Any]] = []
        self.projections: list[dict[str, Any]] = []
        self.events: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, dict[str, Any]] = {}
        self.routes: dict[str, dict[str, Any]] = {}
        self.facts: dict[str, dict[str, Any]] = {}
        self.dump_groups: dict[tuple[object, ...], dict[str, Any]] = {}
        self.team_tool_seen = False
        self.team_result_missing = False
        self.fact_refs_omitted = False
        self.dump_conflict = False
        self.state_change_revisions: list[int] = []

    def observe_tool(
        self,
        tool: dict[str, Any],
        invocation: dict[str, Any] | None,
        result: dict[str, Any] | None,
        seq: int,
    ) -> None:
        self.team_tool_seen = True
        if tool["status"] != "completed" or result is None:
            self.team_result_missing = True
            return
        revision = result.get("revision")
        if _is_int(revision) and revision >= 0:
            self.revisions.append({"revision": revision, "tool_id": tool["tool_id"], "seq": seq})
        name = tool["name"]
        if (
            name in {"team_publish", "team_update", "team_route", "team_route_update", "team_retire"}
            and result.get("deduplicated") is not True
        ):
            if _is_int(revision) and revision >= 0:
                self.state_change_revisions.append(revision)
            else:
                self.team_result_missing = True
        if name == "team_publish":
            self._publish(tool, result, seq)
        elif name == "team_update":
            self._update(result, seq)
        elif name in {"team_route", "team_route_update"}:
            self._route(result, seq)
        elif name == "team_history":
            self._history(result, seq)
        elif name == "team_inspect":
            self._inspect(result, seq)
        elif name == "team_evidence":
            self._evidence(result, seq)
        elif name == "team_retire":
            self._retire(result, seq)
        del invocation

    def _publish(self, tool: dict[str, Any], result: dict[str, Any], seq: int) -> None:
        event_id = result.get("event_id")
        version_id = result.get("version_id")
        if not _is_nonempty_string(event_id) or not _is_nonempty_string(version_id):
            self.team_result_missing = True
            return
        event = self._event(event_id, seq)
        version = self._version(version_id, seq)
        version["event_id"] = event_id
        version["author_agent_id"] = tool["agent_id"]
        version["revision"] = result.get("revision") if _is_int(result.get("revision")) else version["revision"]
        version["authored_on_stale_view"] = result.get("authored_on_stale_view") if isinstance(result.get("authored_on_stale_view"), bool) else None
        _append_unique(event["version_ids"], version_id)
        refs = result.get("evidence_refs")
        if isinstance(refs, list):
            for fact_id in refs:
                if _is_nonempty_string(fact_id):
                    self._link_fact(version_id, fact_id, seq)
        omitted = result.get("evidence_refs_omitted")
        if _is_int(omitted) and omitted > 0:
            self.fact_refs_omitted = True
        self._touch(event, seq)
        self._touch(version, seq)

    def _update(self, result: dict[str, Any], seq: int) -> None:
        updated = result.get("updated")
        if not isinstance(updated, list):
            self.team_result_missing = True
            return
        for row in updated:
            if not isinstance(row, dict) or not _is_nonempty_string(row.get("version_id")):
                self.team_result_missing = True
                continue
            version = self._version(row["version_id"], seq)
            version["revision"] = result.get("revision") if _is_int(result.get("revision")) else version["revision"]
            version["producer_state"] = _safe_enum(row.get("producer_state"))
            version["root_state"] = _safe_enum(row.get("root_state"))
            self._touch(version, seq)

    def _route(self, result: dict[str, Any], seq: int) -> None:
        route_id = result.get("route_id")
        event_id = result.get("event_id")
        if not _is_nonempty_string(route_id) or not _is_nonempty_string(event_id):
            self.team_result_missing = True
            return
        route = self._route_row(route_id, seq)
        route["event_id"] = event_id
        route["target_agent_id"] = result.get("target") if _is_nonempty_string(result.get("target")) else route["target_agent_id"]
        route["duty"] = _safe_enum(result.get("duty"))
        route["delivery"] = _safe_enum(result.get("delivery"))
        route["revision"] = result.get("revision") if _is_int(result.get("revision")) else route["revision"]
        event = self._event(event_id, seq)
        _append_unique(event["route_ids"], route_id)
        self._touch(route, seq)
        self._touch(event, seq)

    def _retire(self, result: dict[str, Any], seq: int) -> None:
        version_id = result.get("version_id")
        if not _is_nonempty_string(version_id):
            self.team_result_missing = True
            return
        version = self._version(version_id, seq)
        version["retired"] = True
        if _is_int(result.get("revision")):
            version["revision"] = result["revision"]
        self._touch(version, seq)

    def _history(self, result: dict[str, Any], seq: int) -> None:
        if _positive_int(result.get("omitted_events")):
            self.team_result_missing = True
        events = result.get("events")
        if not isinstance(events, list):
            self.team_result_missing = True
            return
        for source_event in events:
            if not isinstance(source_event, dict) or not _is_nonempty_string(source_event.get("event_id")):
                self.team_result_missing = True
                continue
            event_id = source_event["event_id"]
            event = self._event(event_id, seq)
            if _positive_int(source_event.get("omitted_versions")):
                self.team_result_missing = True
            versions = source_event.get("versions")
            if not isinstance(versions, list):
                self.team_result_missing = True
                continue
            for source_version in versions:
                if not isinstance(source_version, dict) or not _is_nonempty_string(source_version.get("version_id")):
                    self.team_result_missing = True
                    continue
                version_id = source_version["version_id"]
                version = self._version(version_id, seq)
                version["event_id"] = event_id
                version["revision"] = result.get("revision") if _is_int(result.get("revision")) else version["revision"]
                version["producer_state"] = _safe_enum(source_version.get("producer_state"))
                version["root_state"] = _safe_enum(source_version.get("root_state"))
                version["authored_on_stale_view"] = source_version.get("authored_on_stale_view") if isinstance(source_version.get("authored_on_stale_view"), bool) else version["authored_on_stale_view"]
                refs = source_version.get("evidence_refs")
                if isinstance(refs, list):
                    for fact_id in refs:
                        if _is_nonempty_string(fact_id):
                            self._link_fact(version_id, fact_id, seq)
                if _positive_int(source_version.get("evidence_refs_omitted")):
                    self.fact_refs_omitted = True
                _append_unique(event["version_ids"], version_id)
                self._touch(version, seq)
            self._touch(event, seq)

    def _inspect(self, result: dict[str, Any], seq: int) -> None:
        action = result.get("action")
        if action != "dump":
            return
        required = ("instance", "revision", "availability_epoch", "observe_generation", "total_entries")
        if (
            not _is_nonempty_string(result.get("instance"))
            or not all(_is_int(result.get(key)) and result[key] >= 0 for key in required[1:])
            or not isinstance(result.get("entries"), list)
        ):
            self.team_result_missing = True
            return
        group_key = tuple(result.get(key) for key in required[:-1])
        group = self.dump_groups.setdefault(
            group_key,
            {"revision": result.get("revision"), "seq": seq, "total": result.get("total_entries"), "rows": {}},
        )
        if group["total"] != result.get("total_entries"):
            self.dump_conflict = True
        group["seq"] = max(group["seq"], seq)
        for entry in result["entries"]:
            if not isinstance(entry, dict):
                self.dump_conflict = True
                continue
            key = _dump_entry_key(entry)
            if key is None:
                continue
            sanitized = _sanitize_dump_entry(entry)
            prior = group["rows"].get(key)
            if prior is not None and prior != sanitized:
                self.dump_conflict = True
            group["rows"][key] = sanitized
            self._absorb_dump_entry(sanitized, seq)

    def _absorb_dump_entry(self, entry: dict[str, Any], seq: int) -> None:
        kind = entry.get("entry")
        if kind == "event" and _is_nonempty_string(entry.get("event_id")):
            event = self._event(entry["event_id"], seq)
            event["created_by_agent_id"] = entry.get("created_by_thread_id") if _is_nonempty_string(entry.get("created_by_thread_id")) else event["created_by_agent_id"]
            self._touch(event, seq)
        elif kind == "version" and _is_nonempty_string(entry.get("version_id")):
            version = self._version(entry["version_id"], seq)
            version["author_agent_id"] = entry.get("author_thread_id") if _is_nonempty_string(entry.get("author_thread_id")) else version["author_agent_id"]
            version["producer_state"] = _safe_enum(entry.get("producer_state"))
            version["root_state"] = _safe_enum(entry.get("root_state"))
            version["retired"] = entry.get("retired") if isinstance(entry.get("retired"), bool) else version["retired"]
            if _is_int(entry.get("fact_ref_count")):
                version["fact_ref_count"] = entry["fact_ref_count"]
            self._touch(version, seq)
        elif kind == "version_fact" and all(_is_nonempty_string(entry.get(key)) for key in ("version_id", "fact_id")):
            self._link_fact(entry["version_id"], entry["fact_id"], seq)
        elif kind == "route" and all(_is_nonempty_string(entry.get(key)) for key in ("route_id", "event_id")):
            route = self._route_row(entry["route_id"], seq)
            route["event_id"] = entry["event_id"]
            route["target_agent_id"] = entry.get("target_thread_id") if _is_nonempty_string(entry.get("target_thread_id")) else route["target_agent_id"]
            route["duty"] = _safe_enum(entry.get("duty"))
            route["delivery"] = _safe_enum(entry.get("delivery"))
            event = self._event(entry["event_id"], seq)
            _append_unique(event["route_ids"], entry["route_id"])
            self._touch(route, seq)
            self._touch(event, seq)
        elif kind == "fact" and _is_nonempty_string(entry.get("fact_id")):
            fact = self._fact(entry["fact_id"], seq)
            fact["producer_agent_id"] = entry.get("producer_thread_id") if _is_nonempty_string(entry.get("producer_thread_id")) else fact["producer_agent_id"]
            fact["category"] = _safe_enum(entry.get("category"))
            fact["tool"] = entry.get("tool") if _is_nonempty_string(entry.get("tool")) else fact["tool"]
            self._touch(fact, seq)

    def _evidence(self, result: dict[str, Any], seq: int) -> None:
        fact_id = result.get("fact_id")
        if not _is_nonempty_string(fact_id):
            self.team_result_missing = True
            return
        fact = self._fact(fact_id, seq)
        # The evidence response exposes a presentation label, not the stable
        # thread identity. Only a typed dump Fact row may fill producer_agent_id.
        fact["category"] = _safe_enum(result.get("category"))
        fact["tool"] = result.get("tool") if _is_nonempty_string(result.get("tool")) else fact["tool"]
        fact["availability"] = _safe_enum(result.get("availability"))
        self._touch(fact, seq)

    def _event(self, event_id: str, seq: int) -> dict[str, Any]:
        return self.events.setdefault(
            event_id,
            {
                "event_id": event_id,
                "created_by_agent_id": None,
                "version_ids": [],
                "route_ids": [],
                "first_seq": seq,
                "last_seq": seq,
            },
        )

    def _version(self, version_id: str, seq: int) -> dict[str, Any]:
        return self.versions.setdefault(
            version_id,
            {
                "version_id": version_id,
                "event_id": None,
                "author_agent_id": None,
                "revision": None,
                "producer_state": None,
                "root_state": None,
                "retired": None,
                "authored_on_stale_view": None,
                "fact_ids": [],
                "fact_ref_count": 0,
                "first_seq": seq,
                "last_seq": seq,
            },
        )

    def _route_row(self, route_id: str, seq: int) -> dict[str, Any]:
        return self.routes.setdefault(
            route_id,
            {
                "route_id": route_id,
                "event_id": None,
                "target_agent_id": None,
                "duty": None,
                "delivery": None,
                "revision": None,
                "first_seq": seq,
                "last_seq": seq,
            },
        )

    def _fact(self, fact_id: str, seq: int) -> dict[str, Any]:
        return self.facts.setdefault(
            fact_id,
            {
                "fact_id": fact_id,
                "producer_agent_id": None,
                "category": None,
                "tool": None,
                "availability": None,
                "version_ids": [],
                "first_seq": seq,
                "last_seq": seq,
            },
        )

    def _link_fact(self, version_id: str, fact_id: str, seq: int) -> None:
        version = self._version(version_id, seq)
        fact = self._fact(fact_id, seq)
        _append_unique(version["fact_ids"], fact_id)
        version["fact_ref_count"] = max(version["fact_ref_count"], len(version["fact_ids"]))
        _append_unique(fact["version_ids"], version_id)
        self._touch(version, seq)
        self._touch(fact, seq)

    @staticmethod
    def _touch(row: dict[str, Any], seq: int) -> None:
        row["first_seq"] = min(row["first_seq"], seq)
        row["last_seq"] = max(row["last_seq"], seq)

    def finish(
        self,
        *,
        projection_supported: int,
        projection_unsupported: int,
    ) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        complete_groups = [
            group
            for group in self.dump_groups.values()
            if _is_int(group["total"]) and len(group["rows"]) == group["total"]
        ]
        complete_dump = bool(complete_groups) and not self.dump_conflict
        latest_complete_dump = (
            max(complete_groups, key=lambda group: (group["revision"], group["seq"]))
            if complete_groups
            else None
        )
        snapshot_stale = bool(
            latest_complete_dump is not None
            and self.state_change_revisions
            and max(self.state_change_revisions) > latest_complete_dump["revision"]
        )
        attention: list[dict[str, Any]] = []
        if latest_complete_dump is not None:
            latest = latest_complete_dump
            pairs: dict[tuple[str, str], dict[str, Any]] = {}
            for entry in latest["rows"].values():
                kind = entry.get("entry")
                if kind not in {"visibility", "activity"}:
                    continue
                agent_id = entry.get("participant_thread_id")
                event_id = entry.get("event_id")
                if not _is_nonempty_string(agent_id) or not _is_nonempty_string(event_id):
                    continue
                row = pairs.setdefault(
                    (agent_id, event_id),
                    {
                        "agent_id": agent_id,
                        "event_id": event_id,
                        "visible": None,
                        "active": None,
                        "reasons": [],
                        "revision": latest["revision"],
                        "seq": latest["seq"],
                    },
                )
                if kind == "visibility" and isinstance(entry.get("visible"), bool):
                    row["visible"] = entry["visible"]
                if kind == "activity" and isinstance(entry.get("active"), bool):
                    row["active"] = entry["active"]
                reasons = entry.get("reasons")
                if isinstance(reasons, list):
                    row["reasons"] = sorted(
                        set(row["reasons"]) | {_safe_enum(reason) for reason in reasons if _safe_enum(reason) is not None}
                    )
            attention = sorted(pairs.values(), key=lambda row: (row["agent_id"], row["event_id"]))

        for event in self.events.values():
            event["version_ids"].sort()
            event["route_ids"].sort()
        for version in self.versions.values():
            version["fact_ids"].sort()
        for fact in self.facts.values():
            fact["version_ids"].sort()

        missing_version_relation = any(version["event_id"] is None for version in self.versions.values())
        missing_route_relation = any(
            route["event_id"] is None or route["target_agent_id"] is None
            for route in self.routes.values()
        )
        missing_fact_metadata = any(
            fact["producer_agent_id"] is None or fact["category"] is None
            for fact in self.facts.values()
        )
        missing_fact_availability = any(
            fact["availability"] is None for fact in self.facts.values()
        )
        availability: dict[str, dict[str, Any]] = {}
        availability["team_revisions"] = (
            capability("available")
            if self.revisions
            else capability("partial", "no_team_revision_observed")
        )
        if projection_unsupported and not projection_supported:
            availability["team_projections"] = capability(
                "unsupported", "projection_request_shape_unrecognized"
            )
        elif projection_unsupported:
            availability["team_projections"] = capability(
                "partial", "some_projection_request_shapes_unrecognized"
            )
        elif projection_supported:
            availability["team_projections"] = capability("available")
        else:
            availability["team_projections"] = capability(
                "partial", "no_inference_request_observed"
            )

        event_reasons = []
        if self.team_result_missing:
            event_reasons.append("team_tool_result_missing")
        if missing_version_relation:
            event_reasons.append("version_event_relation_missing")
        if not complete_dump:
            event_reasons.append("attention_snapshot_incomplete")
        elif snapshot_stale:
            event_reasons.append("attention_snapshot_stale")
        availability["team_events_versions"] = (
            capability("partial", *event_reasons)
            if event_reasons
            else capability("available")
        )
        route_reasons = []
        if missing_route_relation:
            route_reasons.append("route_relation_missing")
        if not self.routes and not complete_dump:
            route_reasons.append("route_observation_missing")
        availability["team_routes"] = (
            capability("partial", *route_reasons)
            if route_reasons
            else capability("available")
        )
        fact_reasons = []
        if self.fact_refs_omitted:
            fact_reasons.append("evidence_refs_omitted")
        if missing_fact_metadata:
            fact_reasons.append("fact_metadata_missing")
        if missing_fact_availability:
            fact_reasons.append("fact_availability_unobserved")
        if not complete_dump:
            fact_reasons.append("canonical_dump_incomplete")
        availability["team_facts"] = (
            capability("partial", *fact_reasons) if fact_reasons else capability("available")
        )

        view = {
            "revisions": sorted(
                self.revisions,
                key=lambda row: (row["seq"], row["revision"], row["tool_id"]),
            ),
            "projections": self.projections,
            "events": sorted(self.events.values(), key=lambda row: row["event_id"]),
            "versions": sorted(self.versions.values(), key=lambda row: row["version_id"]),
            "routes": sorted(self.routes.values(), key=lambda row: row["route_id"]),
            "facts": sorted(self.facts.values(), key=lambda row: row["fact_id"]),
            "attention": attention,
        }
        return view, availability


def _extract_projection(
    request: object, inference_id: str, seq: int
) -> tuple[bool, dict[str, Any] | None]:
    if not isinstance(request, dict) or not isinstance(request.get("input"), list):
        return False, None
    items = request["input"]
    if not items:
        return True, None
    item = items[-1]
    if not isinstance(item, dict):
        return False, None
    if item.get("type") != "message" or item.get("role") != "developer":
        return True, None
    content = item.get("content")
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict):
        return True, None
    part = content[0]
    text = part.get("text")
    if part.get("type") != "input_text" or not isinstance(text, str):
        return True, None
    if not text.startswith("<team_active_world_index>\n") or not text.endswith(
        "</team_active_world_index>"
    ):
        return True, None
    lines = text.splitlines()
    if len(lines) < 3 or lines[0] != "<team_active_world_index>":
        return True, None
    match = _PROJECTION_HEADER.fullmatch(lines[1])
    if match is None:
        return True, None
    return True, {
        "inference_id": inference_id,
        "team_instance": match.group(1),
        "revision": int(match.group(2)),
        "seq": seq,
    }


def _unwrap_tool_result(payload: object) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    if kind == "code_mode_response":
        return payload.get("value") if isinstance(payload.get("value"), dict) else None
    if kind != "direct_response":
        return None
    response_item = payload.get("response_item")
    if not isinstance(response_item, dict):
        return None
    output = response_item.get("output")
    if isinstance(output, dict):
        return output
    if isinstance(output, str):
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _extract_usage(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    usage: dict[str, int] = {}
    for key in _USAGE_KEYS:
        number = value.get(key)
        if not _is_int(number) or number < 0:
            return None
        usage[key] = number
    return usage


def _sum_usage(inferences: list[dict[str, Any]]) -> dict[str, int]:
    total = {key: 0 for key in _USAGE_KEYS}
    for inference in inferences:
        usage = inference["usage"]
        if usage is None:
            continue
        for key in _USAGE_KEYS:
            total[key] += usage[key]
    return total


def _parent_thread_id(source: object) -> str | None:
    if isinstance(source, str):
        return None
    if not isinstance(source, dict):
        raise BundleError("thread session source is unsupported")
    subagent = source.get("subagent")
    spawn = subagent.get("thread_spawn") if isinstance(subagent, dict) else None
    parent = spawn.get("parent_thread_id") if isinstance(spawn, dict) else None
    if not _is_nonempty_string(parent):
        raise BundleError("spawned thread metadata has no parent identity")
    return parent


def _dump_entry_key(entry: dict[str, Any]) -> tuple[object, ...] | None:
    kind = entry.get("entry")
    fields = {
        "participant": ("thread_id",),
        "event": ("event_id",),
        "version": ("version_id",),
        "version_fact": ("version_id", "fact_id"),
        "route": ("route_id",),
        "fact": ("fact_id",),
        "visibility": ("participant_thread_id", "event_id"),
        "activity": ("participant_thread_id", "event_id"),
        "publication": ("thread_id",),
    }.get(kind)
    if fields is None:
        return None
    values = tuple(entry.get(field) for field in fields)
    if not all(_is_nonempty_string(value) for value in values):
        return None
    return (kind, *values)


def _sanitize_dump_entry(entry: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "participant": {"entry", "thread_id", "role", "availability"},
        "event": {"entry", "event_id", "created_by_thread_id", "version_count", "route_count"},
        "version": {
            "entry",
            "version_id",
            "author_thread_id",
            "producer_state",
            "root_state",
            "retired",
            "fact_ref_count",
        },
        "version_fact": {"entry", "version_id", "fact_id"},
        "route": {
            "entry",
            "route_id",
            "event_id",
            "target_thread_id",
            "duty",
            "delivery",
        },
        "fact": {
            "entry",
            "fact_id",
            "producer_thread_id",
            "category",
            "item_id",
            "call_id",
            "tool",
        },
        "visibility": {"entry", "participant_thread_id", "event_id", "visible", "reasons"},
        "activity": {"entry", "participant_thread_id", "event_id", "active", "reasons"},
        "publication": {"entry", "thread_id", "version_count", "authored_chars", "fact_ref_count"},
    }.get(entry.get("entry"), {"entry"})
    return {key: entry.get(key) for key in sorted(allowed)}


def _tag(value: object) -> str:
    if isinstance(value, dict) and _is_nonempty_string(value.get("type")):
        return value["type"]
    if _is_nonempty_string(value):
        return value
    return "unknown"


def _execution_status(value: object) -> str:
    status = _tag(value)
    return status if status in {"running", "completed", "failed", "cancelled", "aborted"} else "unknown"


def _safe_enum(value: object) -> str | None:
    if isinstance(value, str) and _SAFE_REASON.fullmatch(value):
        return value
    return None


def _duration_ms(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    secs = value.get("secs")
    nanos = value.get("nanos")
    if not _is_int(secs) or not _is_int(nanos) or secs < 0 or nanos < 0:
        return None
    return secs * 1000 + nanos // 1_000_000


def _sort_rows(rows: object, seq_key: str, id_key: str) -> list[dict[str, Any]]:
    return sorted((dict(row) for row in rows), key=lambda row: (row[seq_key], row[id_key]))


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _positive_int(value: object) -> bool:
    return _is_int(value) and value > 0


def _is_nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
