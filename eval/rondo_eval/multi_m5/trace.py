"""Read a frozen-binary rollout trace bundle as gate 1's evidence source.

Under `tool_mode = code_mode_only` the model never emits a top-level
`function_call` for a team tool. It emits one `custom_tool_call` named `exec`
whose input is JavaScript, and the code-mode host calls
`tools.team_inspect(...)` / `tools.collaboration__wait_agent(...)` from inside
that script. The only thing that reaches the Responses wire afterwards is
whatever the script chose to print, which means the model authors both the call
*and* the text describing its result. Judging gate 1 from that text would let a
model pass by printing a convincing string.

The frozen binary already records the honest version. With
`CODEX_ROLLOUT_TRACE_ROOT` set it writes a bundle whose `ToolCallStarted` /
`ToolCallEnded` events are emitted by the Rust dispatch path: the tool name, its
namespace, the arguments as the registry received them, and the value the
handler returned to JavaScript. That is harness-owned evidence in the same sense
the old `function_call_output` was, and it survives the shift to code mode.

Reading it is deliberately strict. A bundle that is missing, duplicated,
internally inconsistent, or that points outside itself is refused rather than
partially believed -- a gate that silently judges half the evidence is worse
than one that fails closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MANIFEST_FILE = "manifest.json"
EVENT_LOG_FILE = "trace.jsonl"
PAYLOADS_DIR = "payloads"
_MAX_PAYLOAD_BYTES = 32 * 1024 * 1024
_MAX_EVENT_BYTES = 8 * 1024 * 1024


class TraceError(ValueError):
    """Raised when a rollout trace bundle cannot be trusted as evidence."""


@dataclass(frozen=True)
class NestedToolCall:
    """One tool dispatch the frozen binary actually executed."""

    tool_call_id: str
    tool_name: str
    tool_namespace: str | None
    #: `code_cell` when model-authored JavaScript issued it, `model` when the
    #: model called the tool directly. Both are harness-recorded; neither is
    #: written by the model.
    requester: str
    #: Thread that issued the call. Part of a code cell's identity.
    thread_id: str
    #: Present only for code-cell calls: the runtime cell that issued it.
    runtime_cell_id: str | None
    #: Present only for direct model calls: the protocol call id.
    model_visible_call_id: str | None
    arguments: object
    result: object
    status: str
    #: Global rollout sequence of the matching ToolCallEnded event. Cross-thread
    #: protocol ordering cannot be proven from the start event alone.
    end_seq: int
    seq: int


@dataclass(frozen=True)
class CodeCell:
    """One model-authored `exec` cell, as recorded by the runtime.

    Identified by ``(thread_id, runtime_cell_id)``: the cell id is allocated by
    each thread's own code-mode runtime, and Root and its members share one
    bundle, so the ids collide across threads and mean nothing on their own.
    """

    thread_id: str
    runtime_cell_id: str
    model_visible_call_id: str
    source_js: str
    seq: int


@dataclass
class RolloutTrace:
    bundle_dir: Path
    trace_id: str
    rollout_id: str
    root_thread_id: str
    #: Keyed by ``(thread_id, runtime_cell_id)``.
    cells: dict[tuple[str, str], CodeCell] = field(default_factory=dict)
    calls: list[NestedToolCall] = field(default_factory=list)


def find_trace_bundle(trace_root: Path) -> Path:
    """Locate the single bundle a gate 1 run produced.

    Exactly one is expected because the run gets a fresh directory and spawned
    members share their root's writer. Zero means tracing never started and
    there is no evidence; more than one means two rollouts wrote here and no
    row can be attributed to the run under judgement.
    """

    root = Path(trace_root)
    if root.is_symlink() or not root.is_dir():
        raise TraceError("rollout trace root is not a regular directory")
    bundles = sorted(
        child
        for child in root.iterdir()
        if child.is_dir() and not child.is_symlink() and (child / MANIFEST_FILE).is_file()
    )
    if not bundles:
        raise TraceError("no rollout trace bundle was written")
    if len(bundles) > 1:
        raise TraceError("rollout trace root holds more than one bundle")
    return bundles[0]


def load_rollout_trace(bundle_dir: Path) -> RolloutTrace:
    """Parse one bundle into the cells and tool dispatches it recorded."""

    bundle = Path(bundle_dir).resolve()
    if bundle.is_symlink() or not bundle.is_dir():
        raise TraceError("rollout trace bundle is not a regular directory")
    manifest = _read_json_file(bundle / MANIFEST_FILE, bundle)
    for key in ("trace_id", "rollout_id", "root_thread_id"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise TraceError(f"rollout trace manifest is missing {key}")
    if manifest.get("raw_event_log") != EVENT_LOG_FILE:
        raise TraceError("rollout trace manifest names an unexpected event log")
    if manifest.get("payloads_dir") != PAYLOADS_DIR:
        raise TraceError("rollout trace manifest names an unexpected payload dir")

    trace = RolloutTrace(
        bundle_dir=bundle,
        trace_id=manifest["trace_id"],
        rollout_id=manifest["rollout_id"],
        root_thread_id=manifest["root_thread_id"],
    )
    log = bundle / EVENT_LOG_FILE
    if log.is_symlink() or not log.is_file():
        raise TraceError("rollout trace event log is missing")

    started: dict[str, dict[str, Any]] = {}
    seen_seq: set[int] = set()
    previous = 0
    for line in log.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if len(line) > _MAX_EVENT_BYTES:
            raise TraceError("rollout trace event is implausibly large")
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceError("rollout trace event is not JSON") from exc
        if not isinstance(event, dict):
            raise TraceError("rollout trace event is not an object")
        seq = event.get("seq")
        if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
            raise TraceError("rollout trace event has no usable sequence number")
        if seq in seen_seq:
            # The writer assigns these under one lock. A repeat means two
            # writers shared the file, so ordering and attribution are lost.
            raise TraceError("rollout trace event log has a duplicate sequence number")
        seen_seq.add(seq)
        if seq <= previous:
            raise TraceError("rollout trace event sequence is not strictly increasing")
        previous = seq
        if event.get("rollout_id") != trace.rollout_id:
            raise TraceError("rollout trace event belongs to a different rollout")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise TraceError("rollout trace event has no payload")
        thread_id = event.get("thread_id")
        if thread_id is not None and not isinstance(thread_id, str):
            raise TraceError("rollout trace event has an invalid thread id")
        kind = payload.get("type")
        if kind == "code_cell_started":
            _absorb_cell(trace, payload, seq, thread_id or "")
        elif kind == "tool_call_started":
            _absorb_started(started, payload, seq, bundle, thread_id or "")
        elif kind == "tool_call_ended":
            _absorb_ended(trace, started, payload, bundle, seq)
    if started:
        # A dispatch with no end never produced a result the run could rely on.
        # Treating it as evidence would credit a call whose outcome is unknown.
        raise TraceError("rollout trace has tool calls that never completed")
    return trace


def _absorb_cell(
    trace: RolloutTrace, payload: dict[str, Any], seq: int, thread_id: str
) -> None:
    cell_id = payload.get("runtime_cell_id")
    call_id = payload.get("model_visible_call_id")
    source = payload.get("source_js")
    if not isinstance(cell_id, str) or not cell_id:
        raise TraceError("code cell event has no runtime cell id")
    if not isinstance(call_id, str) or not call_id:
        raise TraceError("code cell event has no model-visible call id")
    if not isinstance(source, str):
        raise TraceError("code cell event has no source")
    key = (thread_id, cell_id)
    if key in trace.cells:
        raise TraceError("rollout trace reuses a runtime cell id within one thread")
    trace.cells[key] = CodeCell(
        thread_id=thread_id,
        runtime_cell_id=cell_id,
        model_visible_call_id=call_id,
        source_js=source,
        seq=seq,
    )


def _absorb_started(
    started: dict[str, dict[str, Any]],
    payload: dict[str, Any],
    seq: int,
    bundle: Path,
    thread_id: str,
) -> None:
    call_id = payload.get("tool_call_id")
    if not isinstance(call_id, str) or not call_id:
        raise TraceError("tool call event has no tool call id")
    if call_id in started:
        raise TraceError("rollout trace reuses a tool call id")
    requester = payload.get("requester")
    if not isinstance(requester, dict):
        raise TraceError("tool call event has no requester")
    requester_kind = requester.get("type")
    if requester_kind not in {"model", "code_cell"}:
        raise TraceError("tool call event has an unknown requester")
    runtime_cell_id = requester.get("runtime_cell_id")
    if requester_kind == "code_cell" and (
        not isinstance(runtime_cell_id, str) or not runtime_cell_id
    ):
        raise TraceError("code-cell tool call has no runtime cell id")
    invocation = _load_payload_ref(payload.get("invocation_payload"), bundle)
    if not isinstance(invocation, dict):
        raise TraceError("tool call event has no invocation payload")
    tool_name = invocation.get("tool_name")
    if not isinstance(tool_name, str) or not tool_name:
        raise TraceError("tool invocation payload has no tool name")
    namespace = invocation.get("tool_namespace")
    if namespace is not None and not isinstance(namespace, str):
        raise TraceError("tool invocation payload has an invalid namespace")
    started[call_id] = {
        "tool_name": tool_name,
        "tool_namespace": namespace,
        "requester": requester_kind,
        "thread_id": thread_id,
        "runtime_cell_id": runtime_cell_id if requester_kind == "code_cell" else None,
        "model_visible_call_id": (
            payload.get("model_visible_call_id") if requester_kind == "model" else None
        ),
        "arguments": invocation.get("payload"),
        "seq": seq,
    }


def _absorb_ended(
    trace: RolloutTrace,
    started: dict[str, dict[str, Any]],
    payload: dict[str, Any],
    bundle: Path,
    end_seq: int,
) -> None:
    call_id = payload.get("tool_call_id")
    if not isinstance(call_id, str) or call_id not in started:
        raise TraceError("tool call ended without a recorded start")
    opened = started.pop(call_id)
    if end_seq <= opened["seq"]:
        raise TraceError("tool call ended before its recorded start")
    status = payload.get("status")
    status_name = status.get("type") if isinstance(status, dict) else status
    result = _load_payload_ref(payload.get("result_payload"), bundle)
    value: object = None
    if isinstance(result, dict):
        if result.get("type") == "code_mode_response":
            value = result.get("value")
        elif result.get("type") == "direct_response":
            value = result.get("response_item")
        elif result.get("type") == "error":
            # Keep the typed dispatch error so a failed tool can be classified
            # without a structured handler result. Callers that publish evidence
            # must project this into a body-free code and must not copy `error`.
            error = result.get("error")
            value = {
                "type": "error",
                "error": error if isinstance(error, str) else None,
            }
    trace.calls.append(
        NestedToolCall(
            tool_call_id=call_id,
            tool_name=opened["tool_name"],
            tool_namespace=opened["tool_namespace"],
            requester=opened["requester"],
            thread_id=opened["thread_id"],
            runtime_cell_id=opened["runtime_cell_id"],
            model_visible_call_id=opened["model_visible_call_id"],
            arguments=opened["arguments"],
            result=value,
            status=str(status_name or "unknown"),
            end_seq=end_seq,
            seq=opened["seq"],
        )
    )


def _load_payload_ref(ref: object, bundle: Path) -> object:
    if ref is None:
        return None
    if not isinstance(ref, dict):
        raise TraceError("raw payload reference is not an object")
    relative = ref.get("path")
    if not isinstance(relative, str) or not relative:
        raise TraceError("raw payload reference has no path")
    if relative.startswith("/") or ".." in relative.split("/"):
        raise TraceError("raw payload reference escapes the bundle")
    target = (bundle / relative).resolve()
    if not target.is_relative_to(bundle):
        raise TraceError("raw payload reference escapes the bundle")
    return _read_json_file(target, bundle)


def _read_json_file(path: Path, bundle: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise TraceError(f"rollout trace file {path.name} is not a regular file")
    if path.stat().st_size > _MAX_PAYLOAD_BYTES:
        raise TraceError(f"rollout trace file {path.name} is implausibly large")
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TraceError(f"rollout trace file {path.name} is unreadable") from exc
    if not isinstance(value, dict):
        raise TraceError(f"rollout trace file {path.name} is not an object")
    del bundle
    return value
