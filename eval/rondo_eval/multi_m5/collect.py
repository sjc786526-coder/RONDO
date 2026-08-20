"""Collect gate 1 evidence from the frozen binary's own tool-dispatch record.

Gate 1 asks whether the team machinery actually fired. Under
`tool_mode = code_mode_only` the answer is not visible on the Responses wire:
the model emits one `custom_tool_call` named `exec` carrying JavaScript, and
every team tool is invoked from inside that script. What comes back on the wire
is only what the script printed, so a model could call nothing and print a
convincing dump, or call everything and print nothing. Neither the call nor the
result is harness-owned there.

The rollout trace is. Its `ToolCallStarted` / `ToolCallEnded` pairs are written
by the Rust dispatch path with the registry's own view of the tool name, its
namespace, the arguments it received, and the value its handler returned. That
is the same kind of evidence the old `function_call_output` was, and it is the
part of the flow the model cannot author.

The Responses capture is still required, but for a different job: it proves the
model really emitted the cells the trace attributes work to. Every judged call
must belong to a code cell whose `model_visible_call_id` appears as a
`custom_tool_call` in the capture and whose recorded source matches that call's
input. A trace row with no matching cell, or a cell with no matching wire call,
is refused rather than believed -- otherwise the trace alone could be replayed
from a different run.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from .trace import NestedToolCall, RolloutTrace, TraceError


WAIT_TEAM_ACTIVITY_MARK = (
    "Wait completed: the team world state changed. The current active view is in this request."
)
#: `(namespace, name)` as the frozen binary's registry reports them. The team
#: world-state tools and the multi-agent v2 tools go through the same namespace
#: override, so both are dispatched under `collaboration` even though their
#: handlers declare a plain name. Verified against the frozen binary by the
#: offline rehearsal rather than inferred from the handler source.
INSPECT_TOOL = ("collaboration", "team_inspect")
WAIT_TOOL = ("collaboration", "wait_agent")
EVIDENCE_TOOL = ("collaboration", "team_evidence")
PUBLISH_TOOL = ("collaboration", "team_publish")
ROUTE_TOOL = ("collaboration", "team_route")
UPDATE_TOOL = ("collaboration", "team_update")
_DEFAULT_NAMESPACES = {None, "", "functions"}
_CALL_TYPES = {"function_call", "custom_tool_call"}
_ITEM_EVENTS = {"item.completed", "item.started", "item.updated"}


class EvidenceError(ValueError):
    """Raised when captured evidence cannot be bound to the run under judgement."""


def collect_gate1_evidence(
    jsonl: str,
    trace: RolloutTrace,
    *,
    required_inspect_actions: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Extract dump entries, change-log rows, and wake signals from the trace.

    Rows are attributed to the tool the registry actually dispatched. Only a
    `team_inspect` result can contribute dump or change-log rows and only a
    `wait_agent` result can contribute a wake signal, so a team-shaped payload
    produced by any other tool -- an `exec_command` echoing a crafted blob, a
    script printing a fabricated dump -- lands in `unattributed` and is never
    judged.
    """

    wire_calls = _wire_calls(jsonl)
    dump: dict[str, Any] = {
        "root_thread_id": trace.root_thread_id,
        "entries": [],
        "log": [],
        "jsonl_signals": [],
        "wait_calls": [],
        "unattributed": [],
        "inspect_actions": [],
        "team_evidence_calls": [],
        "team_publish_calls": [],
        "team_route_calls": [],
        "team_update_calls": [],
        "cells": len(trace.cells),
        "nested_calls": len(trace.calls),
    }
    pagination: dict[str, dict[str, Any] | None] = {"dump": None, "log": None}
    _require_bound_cells(trace, wire_calls)
    for call in sorted(trace.calls, key=lambda item: item.seq):
        _require_bound_call(call, trace, wire_calls)
        _absorb(dump, pagination, call, required_inspect_actions)
    for action, state in pagination.items():
        if state is not None and state.get("next") is not None:
            raise EvidenceError(
                f"team_inspect {action} pagination ended before the final page"
            )
    missing = [
        action
        for action in required_inspect_actions
        if action not in dump["inspect_actions"]
    ]
    if missing:
        raise EvidenceError(
            f"required team_inspect actions were not captured: {','.join(missing)}"
        )
    for action in required_inspect_actions:
        if action not in pagination:
            continue
        state = pagination[action]
        if (
            state is None
            or not isinstance(state.get("total"), int)
            or isinstance(state.get("total"), bool)
            or state["total"] < 0
            or state.get("seen") != state["total"]
        ):
            raise EvidenceError(
                f"team_inspect {action} page set does not cover total_entries"
            )
    return dump


def member_message_delivery(jsonl: str) -> dict[str, Any]:
    """How the team's `agent_message` items reached the member on the wire.

    A member request whose task text is labelled `encrypted_content` is the
    defect that made cm4 unreadable: the provider rejects it as
    `invalid_encrypted_content`, the member never completes a turn, and the
    resulting "no publish, no evidence" looks exactly like a model that ignored
    the protocol. Reading it off the capture keeps that distinction a measured
    fact rather than something someone has to remember to check by eye.

    `absent` is not `plaintext`: a run where no member request was ever built
    has not demonstrated anything about delivery.
    """

    plaintext = 0
    encrypted = 0
    unknown = 0
    for line in jsonl.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        for item in parsed.get("input") or ():
            if not isinstance(item, dict) or item.get("type") != "agent_message":
                continue
            # This carrier has one Root and one member. The member's task is the
            # `agent_message` authored by `/root`; replies authored by a member
            # appear in Root requests and do not demonstrate task delivery.
            if item.get("author") != "/root":
                continue
            content = item.get("content")
            if not isinstance(content, list) or not content:
                unknown += 1
                continue
            for part in content:
                if not isinstance(part, dict):
                    unknown += 1
                    continue
                if part.get("type") == "encrypted_content" or "encrypted_content" in part:
                    encrypted += 1
                elif (
                    part.get("type") == "input_text"
                    and isinstance(part.get("text"), str)
                    and bool(part["text"])
                ):
                    plaintext += 1
                else:
                    unknown += 1
    if encrypted:
        status = "encrypted"
    elif unknown:
        status = "unknown"
    elif plaintext:
        status = "plaintext"
    else:
        status = "absent"
    return {
        "status": status,
        "plaintext_parts": plaintext,
        "encrypted_parts": encrypted,
        "unknown_parts": unknown,
    }


def _wire_calls(jsonl: str) -> dict[str, str]:
    """Map every tool call the model emitted on the wire to its raw input."""

    calls: dict[str, str] = {}
    for line in jsonl.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            for record in _ordered_records(parsed):
                call_id = record.get("call_id")
                if isinstance(call_id, str) and call_id:
                    calls[call_id] = _as_text(
                        record.get("input")
                        if record.get("type") == "custom_tool_call"
                        else record.get("arguments")
                    )
    return calls


def _ordered_records(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Walk Responses `input` items and exec `item.*` wrappers, not the whole tree."""

    kind = str(value.get("type") or "")
    records: list[dict[str, Any]] = []
    if kind in _CALL_TYPES:
        records.append(dict(value))
    elif kind in _ITEM_EVENTS:
        item = value.get("item")
        if isinstance(item, dict):
            records.extend(_ordered_records(item))
    input_items = value.get("input")
    if isinstance(input_items, list):
        for item in input_items:
            if isinstance(item, dict):
                records.extend(_ordered_records(item))
    return records


def _require_bound_cells(trace: RolloutTrace, wire_calls: Mapping[str, str]) -> None:
    """Every recorded cell must be one the model demonstrably asked for.

    Without this the trace is an unanchored file: any bundle from any run would
    satisfy the predicates. Matching the recorded source against the captured
    `exec` input is what ties this trace to this conversation.
    """

    for cell in trace.cells.values():
        wire_input = wire_calls.get(cell.model_visible_call_id)
        if wire_input is None:
            raise EvidenceError(
                "rollout trace has a code cell with no captured model call"
            )
        source = cell.source_js.strip()
        if source and source not in wire_input:
            # The recorded source is the JS after the public `exec` wrapper is
            # parsed, so it is a substring of the captured input rather than
            # equal to it. A source the model never sent is a different run.
            raise EvidenceError("code cell source differs from the captured model call")


def _require_bound_call(
    call: NestedToolCall, trace: RolloutTrace, wire_calls: Mapping[str, str]
) -> None:
    if call.requester == "code_cell":
        if (call.thread_id, call.runtime_cell_id) not in trace.cells:
            raise EvidenceError("nested tool call belongs to no recorded code cell")
        return
    if call.requester == "model":
        # The frozen workflow is code_mode_only. A direct dispatch is product
        # or trace drift, even if its model-visible id exists on the wire; none
        # of its payload may enter the collaboration predicates.
        raise EvidenceError("direct model tool call is forbidden by the workflow")
    raise EvidenceError("nested tool call has an unknown requester")


def _absorb(
    dump: dict[str, Any],
    pagination: dict[str, dict[str, Any] | None],
    call: NestedToolCall,
    required_inspect_actions: tuple[str, ...],
) -> None:
    identity = (_namespace(call.tool_namespace), call.tool_name)
    if identity == EVIDENCE_TOOL:
        args = call.arguments if isinstance(call.arguments, dict) else {}
        dump["team_evidence_calls"].append(
            {
                "thread_id": call.thread_id,
                "seq": call.seq,
                "end_seq": call.end_seq,
                "status": call.status,
                "arguments": _arguments(args),
                "result": call.result,
            }
        )
        return
    if identity in {PUBLISH_TOOL, ROUTE_TOOL, UPDATE_TOOL}:
        key = {
            PUBLISH_TOOL: "team_publish_calls",
            ROUTE_TOOL: "team_route_calls",
            UPDATE_TOOL: "team_update_calls",
        }[identity]
        args = call.arguments if isinstance(call.arguments, dict) else {}
        dump[key].append(
            {
                "thread_id": call.thread_id,
                "seq": call.seq,
                "end_seq": call.end_seq,
                "status": call.status,
                "arguments": _arguments(args),
                "result": call.result,
            }
        )
        return
    if identity == WAIT_TOOL:
        dump["wait_calls"].append(
            {
                "thread_id": call.thread_id,
                "seq": call.seq,
                "end_seq": call.end_seq,
                "status": call.status,
                "result": call.result,
            }
        )
        if call.status == "completed":
            message = call.result.get("message") if isinstance(call.result, dict) else None
            if isinstance(message, str):
                _record_wait_signal(dump, message)
        return
    if identity == INSPECT_TOOL and call.status != "completed":
        args = call.arguments if isinstance(call.arguments, dict) else {}
        requested_action = str(_arguments(args).get("action") or "")
        if requested_action in required_inspect_actions:
            raise EvidenceError(
                f"required team_inspect {requested_action} dispatch did not complete"
            )
    if call.status != "completed":
        # A failed dispatch produced no result the run could act on.
        return
    if identity == INSPECT_TOOL:
        _absorb_inspect(dump, pagination, call)
        return
    if _looks_like_team_evidence(call.result):
        dump["unattributed"].append(_label(call))


def _absorb_inspect(
    dump: dict[str, Any],
    pagination: dict[str, dict[str, Any] | None],
    call: NestedToolCall,
) -> None:
    payload = call.result
    if not isinstance(payload, dict):
        raise EvidenceError("team_inspect completed without an object result")
    args = call.arguments if isinstance(call.arguments, dict) else {}
    args = _arguments(args)
    reported_action = str(payload.get("action") or "")
    requested_action = str(args.get("action") or "")
    if reported_action and requested_action and reported_action != requested_action:
        raise EvidenceError("team_inspect result action differs from its invocation")
    action = reported_action or requested_action
    if action == "stats":
        if action not in dump["inspect_actions"]:
            dump["inspect_actions"].append(action)
        return
    if action not in pagination:
        raise EvidenceError("team_inspect result has no recognised action")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise EvidenceError(f"team_inspect {action} result has no entries page")
    # A dump page continues only with a snapshot cursor, which the store refuses
    # across revisions, so cursor pages are same-snapshot by construction. A
    # cursor-less dump is a fresh page and replaces.
    if action == "dump":
        cursor = args.get("cursor")
        previous = pagination["dump"]
        continuation = bool(cursor)
        if cursor:
            if previous is None or previous.get("next") != cursor:
                raise EvidenceError(
                    "team_inspect dump cursor does not continue the prior page"
                )
            dump["entries"].extend(entries)
            seen = int(previous.get("seen") or 0) + len(entries)
        else:
            if previous is not None and previous.get("next") is not None:
                raise EvidenceError(
                    "team_inspect dump restarted before completing the prior snapshot"
                )
            dump["entries"] = list(entries)
            seen = len(entries)
        next_value = payload.get("next_cursor")
    elif action == "log":
        offset = args.get("offset")
        previous = pagination["log"]
        continuation = offset not in {None, 0, "0"}
        if offset not in {None, 0, "0"}:
            if previous is None or str(previous.get("next")) != str(offset):
                raise EvidenceError(
                    "team_inspect log offset does not continue the prior page"
                )
            dump["log"].extend(entries)
            seen = int(previous.get("seen") or 0) + len(entries)
        else:
            if previous is not None and previous.get("next") is not None:
                raise EvidenceError(
                    "team_inspect log restarted before completing the prior page set"
                )
            dump["log"] = list(entries)
            seen = len(entries)
        next_value = payload.get("next_offset")
        if next_value in {0, "0"}:
            next_value = None
    total = payload.get("total_entries")
    if continuation and previous is not None and previous.get("total") != total:
        raise EvidenceError(f"team_inspect {action} total_entries changed between pages")
    pagination[action] = {
        "next": next_value,
        "total": total,
        "seen": seen,
    }
    if action not in dump["inspect_actions"]:
        dump["inspect_actions"].append(action)


def _arguments(value: Mapping[str, Any]) -> dict[str, Any]:
    """Unwrap the dispatch payload envelope into the tool's own arguments."""

    kind = value.get("type")
    if kind == "function":
        parsed = _parse_json(str(value.get("arguments") or ""))
        return parsed if isinstance(parsed, dict) else {}
    if kind == "custom":
        parsed = _parse_json(str(value.get("input") or ""))
        return parsed if isinstance(parsed, dict) else {}
    return dict(value)


def _looks_like_team_evidence(payload: object) -> bool:
    if isinstance(payload, dict):
        if str(payload.get("action") or "") in {"dump", "log"} and isinstance(
            payload.get("entries"), list
        ):
            return True
        message = payload.get("message")
        return isinstance(message, str) and WAIT_TEAM_ACTIVITY_MARK in message
    return isinstance(payload, str) and WAIT_TEAM_ACTIVITY_MARK in payload


def _record_wait_signal(dump: dict[str, Any], message: str) -> None:
    if WAIT_TEAM_ACTIVITY_MARK in message and message not in dump["jsonl_signals"]:
        dump["jsonl_signals"].append(message)


def _namespace(value: str | None) -> str | None:
    return None if value in _DEFAULT_NAMESPACES else value


def _label(call: NestedToolCall) -> str:
    namespace = _namespace(call.tool_namespace)
    return f"{namespace}.{call.tool_name}" if namespace else call.tool_name


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return ""


def _parse_json(text: str) -> object:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


__all__ = [
    "EvidenceError",
    "INSPECT_TOOL",
    "WAIT_TOOL",
    "WAIT_TEAM_ACTIVITY_MARK",
    "TraceError",
    "collect_gate1_evidence",
    "member_message_delivery",
]
