"""Collect gate 1 evidence from `codex exec --json` tool outputs.

The judge must not read a dump the model copied into a markdown file. Tool
outputs are written by the harness when `team_inspect` / `wait_agent` actually
ran.
"""

from __future__ import annotations

import json
from typing import Any, Mapping


WAIT_TEAM_ACTIVITY_MARK = (
    "Wait completed: the team world state changed. The current active view is in this request."
)
_INSPECT_NAMES = {"team_inspect", "collaboration.team_inspect"}


def collect_gate1_evidence(jsonl: str) -> dict[str, Any]:
    """Extract dump entries, change-log rows, and wait signals from JSONL."""

    calls: dict[str, dict[str, Any]] = {}
    outputs: dict[str, str] = {}
    orphan_outputs: list[str] = []
    for value in _iter_objects(jsonl):
        kind = str(value.get("type") or "")
        name = _tool_name(value)
        call_id = value.get("call_id")
        if kind in {"function_call", "custom_tool_call"} or name:
            if isinstance(call_id, str) and call_id:
                calls[call_id] = {
                    "name": name,
                    "arguments": _as_text(value.get("arguments")),
                }
        if kind in {"function_call_output", "custom_tool_call_output"} or "output" in value:
            text = _as_text(value.get("output"))
            if not text:
                continue
            if isinstance(call_id, str) and call_id:
                outputs[call_id] = text
            else:
                orphan_outputs.append(text)

    dump: dict[str, Any] = {"entries": [], "log": [], "jsonl_signals": []}
    for call_id, call in calls.items():
        name = call["name"]
        text = outputs.get(call_id, "")
        _absorb(dump, name, call["arguments"], text)
    for text in orphan_outputs:
        _absorb(dump, "", "", text)
    return dump


def merge_jsonl_into_dump(dump: Mapping[str, Any], jsonl: str) -> dict[str, Any]:
    collected = collect_gate1_evidence(jsonl)
    merged = dict(dump)
    if collected["entries"]:
        merged["entries"] = collected["entries"]
    if collected["log"]:
        merged["log"] = collected["log"]
    signals = list(dump.get("jsonl_signals") or [])
    signals.extend(collected["jsonl_signals"])
    merged["jsonl_signals"] = signals
    return merged


def _absorb(dump: dict[str, Any], name: str, arguments: str, text: str) -> None:
    payload = _parse_json(text)
    action = ""
    args = _parse_json(arguments)
    if isinstance(args, dict):
        action = str(args.get("action") or "")
    if isinstance(payload, dict):
        action = str(payload.get("action") or action)
        message = payload.get("message")
        if name in _INSPECT_NAMES or action in {"dump", "log"}:
            if action == "dump" and isinstance(payload.get("entries"), list):
                dump["entries"] = payload["entries"]
            if action == "log" and isinstance(payload.get("entries"), list):
                dump["log"] = payload["entries"]
        if isinstance(message, str):
            _record_wait_signal(dump, message)
    elif WAIT_TEAM_ACTIVITY_MARK in text:
        _record_wait_signal(dump, text)


def _record_wait_signal(dump: dict[str, Any], message: str) -> None:
    if WAIT_TEAM_ACTIVITY_MARK in message and message not in dump["jsonl_signals"]:
        dump["jsonl_signals"].append(message)


def _iter_objects(jsonl: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for line in jsonl.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        _walk(parsed, found)
    return found


def _walk(value: object, found: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        found.append(value)
        for item in value.values():
            _walk(item, found)
    elif isinstance(value, list):
        for item in value:
            _walk(item, found)


def _tool_name(value: Mapping[str, Any]) -> str:
    for key in ("name", "tool_name"):
        raw = value.get(key)
        if isinstance(raw, str) and raw:
            return raw.rsplit(".", 1)[-1] if raw.startswith("collaboration.") else raw
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
