"""Collect gate 1 evidence from harness-captured tool outputs.

`codex exec --json` does not emit `team_inspect` payloads: exec maps a small
ThreadItem set and drops DynamicToolCall / plain function tools. The wait
item also omits the TeamActivity message. Real harness-owned evidence is the
`function_call_output` the CLI later puts on the Responses `input` list
(budget proxy / loopback request bodies). TEAM_REPORT is never a source.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


WAIT_TEAM_ACTIVITY_MARK = (
    "Wait completed: the team world state changed. The current active view is in this request."
)
_INSPECT_NAMES = {"team_inspect", "collaboration.team_inspect"}
_CALL_TYPES = {"function_call", "custom_tool_call"}
_OUTPUT_TYPES = {"function_call_output", "custom_tool_call_output"}
_ITEM_EVENTS = {"item.completed", "item.started", "item.updated"}


def collect_gate1_evidence(jsonl: str) -> dict[str, Any]:
    """Extract dump entries, change-log rows, and wait signals in document order."""

    calls: dict[str, dict[str, str]] = {}
    dump: dict[str, Any] = {"entries": [], "log": [], "jsonl_signals": []}
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
        for record in _ordered_records(parsed):
            _apply_record(dump, calls, record)
    return dump


def merge_jsonl_into_dump(dump: Mapping[str, Any], jsonl: str) -> dict[str, Any]:
    """JSONL is authoritative. Caller dump cannot leak a fabricated collaboration."""

    if not isinstance(dump, Mapping):
        raise TypeError("dump must be a mapping")
    return collect_gate1_evidence(jsonl)


def _ordered_records(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Walk Responses `input` items and exec `item.*` wrappers, not the whole tree."""

    kind = str(value.get("type") or "")
    records: list[dict[str, Any]] = []
    if kind in _CALL_TYPES or kind in _OUTPUT_TYPES:
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


def _apply_record(
    dump: dict[str, Any],
    calls: dict[str, dict[str, str]],
    record: Mapping[str, Any],
) -> None:
    kind = str(record.get("type") or "")
    call_id = record.get("call_id")
    if kind in _CALL_TYPES and isinstance(call_id, str) and call_id:
        calls[call_id] = {
            "name": _tool_name(record),
            "arguments": _as_text(record.get("arguments")),
        }
        return
    if kind not in _OUTPUT_TYPES:
        return
    text = _output_text(record.get("output"))
    if not text:
        return
    meta = calls.get(call_id, {}) if isinstance(call_id, str) else {}
    _absorb(dump, meta.get("name", ""), meta.get("arguments", ""), text)


def _absorb(dump: dict[str, Any], name: str, arguments: str, text: str) -> None:
    payload = _parse_json(text)
    args = _parse_json(arguments)
    action = ""
    if isinstance(args, dict):
        action = str(args.get("action") or "")
    if isinstance(payload, dict):
        action = str(payload.get("action") or action)
        message = payload.get("message")
        if name in _INSPECT_NAMES or action in {"dump", "log"}:
            entries = payload.get("entries")
            if action == "dump" and isinstance(entries, list):
                if isinstance(args, dict) and args.get("cursor"):
                    dump["entries"].extend(entries)
                else:
                    dump["entries"] = list(entries)
            if action == "log" and isinstance(entries, list):
                if isinstance(args, dict) and args.get("offset") not in {None, 0, "0"}:
                    dump["log"].extend(entries)
                else:
                    dump["log"] = list(entries)
        if isinstance(message, str):
            _record_wait_signal(dump, message)
    elif WAIT_TEAM_ACTIVITY_MARK in text:
        _record_wait_signal(dump, text)


def _record_wait_signal(dump: dict[str, Any], message: str) -> None:
    if WAIT_TEAM_ACTIVITY_MARK in message and message not in dump["jsonl_signals"]:
        dump["jsonl_signals"].append(message)


def _tool_name(value: Mapping[str, Any]) -> str:
    for key in ("name", "tool_name"):
        raw = value.get(key)
        if isinstance(raw, str) and raw:
            if raw.startswith("collaboration."):
                return raw.rsplit(".", 1)[-1]
            if raw.startswith("collaboration__"):
                return raw[len("collaboration__") :]
            return raw
    return ""


def _output_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        return json.dumps(value)
    return ""


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
