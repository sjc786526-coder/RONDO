"""Scripted Root + member model for the gate 1 offline dress rehearsal.

The frozen Multi binary runs for real. This stub only replaces the model: it
issues the tool calls, the CLI executes them against canonical team state, and
the harness-captured Responses bodies are what the predicates judge.

Collaboration turns are emitted the way a `code_mode_only` model emits them: a
single `custom_tool_call` named `exec` whose input is JavaScript calling the
tool. The rehearsal therefore drives the code-mode host, the nested dispatch
path, and the rollout-trace evidence the paid gate reads -- not a shape only the
stub uses.

The shell call also goes through the code-mode host. Its nested result is folded
into the retained outer cell output; that all-text output is the evidence fact
the member's next publish attaches. This is the shape a real `code_mode_only`
model can actually produce.

Sequence (one Event):
  spawn_agent → member exec (read NOTES) → member team_publish → Root wait wakes
  → Root team_publish on that Event (two authors) → team_route → member
  team_evidence → member appends a second Version → Root team_update resolved
  → team_inspect dump/log → write TEAM_REPORT.md

Root's extra publish is required by the frozen two_authors predicate. The
predicates themselves are not relaxed.
"""

from __future__ import annotations

import json
import re
import shlex
import threading
from typing import Any, Mapping

from .capture import CaptureError

COLLAB_NAMESPACE = "collaboration"
_OUTPUT_TYPES = {"function_call_output", "custom_tool_call_output"}
MEMBER_TASK = (
    "M5-COLLAB-MEMBER: read NOTES.md with a non-team tool; create one Event with "
    "team_publish and keep your non-empty evidence_refs; after Root routes that Event "
    "back, call team_evidence on one of those member-produced fact IDs and append a "
    "second Version to the same Event"
)
# Product tests and the V2 default both use 30s. A longer wait still fits the
# 180s rehearsal cap, but 30s matches the proven protocol and fails faster.
WAIT_MS = 30_000
MAX_INSPECT_PAGES = 16
# Deliberately smaller than every realistic M-5 dump/log. The dress rehearsal
# is also the pagination rehearsal: both inspect actions must execute at least
# one continuation request and reach a null continuation marker. Keeping this
# explicit prevents a smaller, cleaner state from making the collector's
# continuation path silently untested.
INSPECT_PAGE_LIMIT = 3
_EVENT_ID = re.compile(r"evt-\d+-[0-9a-f]{32}")
_VERSION_ID = re.compile(r"ver-\d+\.\d+-[0-9a-f]{32}")
_FACT_ID = re.compile(r"fct-\d+-[0-9a-f]{32}")
_MEMBER_VERSION = re.compile(
    r"(ver-\d+\.\d+-[0-9a-f]{32}) by (/root/\S+) producer=\S+ root=pending"
)


class RehearsalError(CaptureError):
    """The scripted collaboration could not choose a valid next tool call."""


class CollaborationStub:
    """Play Root and the one member. Shared state is locked per request."""

    def __init__(self, *, finding_line: str) -> None:
        self.finding_line = finding_line
        self._lock = threading.Lock()
        self.errors: list[str] = []
        self.event_id: str | None = None
        self.member_version_1: str | None = None
        self.member_version_2: str | None = None
        self.fact_id: str | None = None
        self.revision: int | None = None
        self.dump_pages = 0
        self.log_pages = 0
        self.notes_read = False
        self.evidenced = False
        self.finished = False

    def __call__(self, request: Mapping[str, Any]) -> bytes:
        with self._lock:
            try:
                return self._next(dict(request))
            except RehearsalError as exc:
                self.errors.append(str(exc))
                return _say("rehearsal-abort", f"rehearsal cannot continue: {exc}")

    def _next(self, request: dict[str, Any]) -> bytes:
        if _is_member(request):
            return self._member(request)
        return self._root(request)

    def _root(self, request: dict[str, Any]) -> bytes:
        if not _has_output(request, "spawn-1"):
            return _team_call(
                "spawn-1",
                "spawn_agent",
                {"message": MEMBER_TASK, "task_name": "worker"},
            )
        if not _has_output(request, "wait-1"):
            return _team_call("wait-1", "wait_agent", {"timeout_ms": WAIT_MS})
        if not _has_output(request, "root-pub-1"):
            event_id = self._require_event_id(request)
            return _team_call(
                "root-pub-1",
                "team_publish",
                {
                    "event_id": event_id,
                    "summary": "Root records the same finding on the member's Event",
                    **self._revision_arg(),
                },
            )
        if not _has_output(request, "route-1"):
            self._absorb_publish(request, "root-pub-1")
            event_id = self._require_event_id(request)
            return _team_call(
                "route-1",
                "team_route",
                {
                    "event_id": event_id,
                    "target": "worker",
                    "intent": "assign",
                    "note": "attach evidence and append a second Version",
                    **self._revision_arg(),
                },
            )
        if not _has_output(request, "wait-2"):
            return _team_call("wait-2", "wait_agent", {"timeout_ms": WAIT_MS})
        if not _has_output(request, "resolve-1"):
            version_id = self._require_member_version(request)
            return _team_call(
                "resolve-1",
                "team_update",
                {
                    "targets": [
                        {
                            "version_id": version_id,
                            "expect_producer_state": "open",
                            "expect_root_state": "pending",
                            "set_root_state": "resolved",
                        }
                    ]
                },
            )
        continuation = self._continue_inspect(request, "dump")
        if continuation is not None:
            return continuation
        continuation = self._continue_inspect(request, "log")
        if continuation is not None:
            return continuation
        if not _has_output(request, "write-report"):
            return _shell_call(request, "write-report", self._report_command(request))
        self.finished = True
        return _say("root-done", "collaboration protocol finished")

    def _continue_inspect(self, request: dict[str, Any], action: str) -> bytes | None:
        """Page dump/log from the latest page's cursor/offset, never from page 0 again."""

        prefix = "inspect-dump" if action == "dump" else "inspect-log"
        pages = _outputs_with_prefix(request, prefix)
        if not pages:
            args: dict[str, Any] = {
                "action": action,
                "limit": INSPECT_PAGE_LIMIT,
            }
            return _team_call(prefix, "team_inspect", args)
        _call_id, payload = pages[-1]
        if not isinstance(payload, dict):
            raise RehearsalError(
                f"{prefix} did not return a JSON page; inspection cannot be completed"
            )
        if action == "dump":
            cursor = payload.get("next_cursor")
            if cursor:
                if len(pages) >= MAX_INSPECT_PAGES:
                    raise RehearsalError(
                        "team_inspect dump exceeded the bounded page limit before next_cursor became null"
                    )
                self.dump_pages = len(pages)
                return _team_call(
                    f"{prefix}-{len(pages)}",
                    "team_inspect",
                    {
                        "action": "dump",
                        "cursor": cursor,
                        "limit": INSPECT_PAGE_LIMIT,
                    },
                )
            self.dump_pages = len(pages)
            return None
        offset = payload.get("next_offset")
        if offset not in {None, 0, "0"}:
            if len(pages) >= MAX_INSPECT_PAGES:
                raise RehearsalError(
                    "team_inspect log exceeded the bounded page limit before next_offset became null"
                )
            self.log_pages = len(pages)
            return _team_call(
                f"{prefix}-{len(pages)}",
                "team_inspect",
                {
                    "action": "log",
                    "offset": offset,
                    "limit": INSPECT_PAGE_LIMIT,
                },
            )
        self.log_pages = len(pages)
        return None

    def _member(self, request: dict[str, Any]) -> bytes:
        # Instance flags survive a fresh routed turn. A wait_agent here would
        # deadlock with Root's wait: both sides sitting in wait for the other.
        # Product tests send the member idle after the first publish, then let
        # an assign route start the second turn.
        if not self.notes_read:
            if not _has_output(request, "member-sh-1"):
                return _shell_call(request, "member-sh-1", "cat NOTES.md")
            self.notes_read = True
        if self.member_version_1 is None:
            if not _has_output(request, "member-pub-1"):
                return _team_call(
                    "member-pub-1",
                    "team_publish",
                    {
                        "title": "migration drops a column the report still reads",
                        "summary": self.finding_line,
                        "handoff": "Root should route this Event back for evidence",
                    },
                )
            self._absorb_publish(request, "member-pub-1")
            if self.member_version_1 is None:
                raise RehearsalError("member publish did not yield a Version")
            return _say("member-idle-1", "published the finding")
        if not self.evidenced:
            if not _has_output(request, "member-ev-1"):
                fact_id = self.fact_id or _first(_FACT_ID, request)
                if not fact_id:
                    raise RehearsalError("member publish did not yield an evidence fact")
                self.fact_id = fact_id
                return _team_call("member-ev-1", "team_evidence", {"fact_id": fact_id})
            self.evidenced = True
        if self.member_version_2 is None:
            if not _has_output(request, "member-pub-2"):
                event_id = self._require_event_id(request)
                return _team_call(
                    "member-pub-2",
                    "team_publish",
                    {
                        "event_id": event_id,
                        "summary": (
                            "the report also joins on that column, so dropping "
                            "it breaks two queries"
                        ),
                        **self._revision_arg(),
                    },
                )
            self._absorb_publish(request, "member-pub-2")
            version = _output_json(request, "member-pub-2")
            if isinstance(version, dict) and version.get("version_id"):
                self.member_version_2 = str(version["version_id"])
            if self.member_version_2 is None:
                raise RehearsalError("member second publish did not yield a Version")
        return _say("member-done", "published, evidenced, and appended")

    def _absorb_publish(self, request: Mapping[str, Any], call_id: str) -> None:
        payload = _output_json(request, call_id)
        if not isinstance(payload, dict):
            return
        event_id = payload.get("event_id")
        version_id = payload.get("version_id")
        revision = payload.get("revision")
        refs = payload.get("evidence_refs")
        if isinstance(event_id, str) and event_id:
            self.event_id = event_id
        if isinstance(revision, int):
            self.revision = revision
        if call_id == "member-pub-1" and isinstance(version_id, str) and version_id:
            self.member_version_1 = version_id
        if call_id == "member-pub-2" and isinstance(version_id, str) and version_id:
            self.member_version_2 = version_id
        if isinstance(refs, list) and refs and self.fact_id is None:
            fact = refs[0]
            if isinstance(fact, str) and fact:
                self.fact_id = fact

    def _require_event_id(self, request: Mapping[str, Any]) -> str:
        if self.event_id:
            return self.event_id
        found = _first(_EVENT_ID, request)
        if not found:
            raise RehearsalError("no Event id after member publish")
        self.event_id = found
        return found

    def _require_member_version(self, request: Mapping[str, Any]) -> str:
        if self.member_version_1:
            return self.member_version_1
        text = _blob(request)
        match = _MEMBER_VERSION.search(text)
        if match and match.group(2) not in {"/root", "root"}:
            self.member_version_1 = match.group(1)
            return match.group(1)
        found = _first(_VERSION_ID, request)
        if not found:
            raise RehearsalError("no member Version id to resolve")
        return found

    def _revision_arg(self) -> dict[str, int]:
        if self.revision is None:
            return {}
        return {"based_on_revision": self.revision}

    def _report_command(self, request: Mapping[str, Any]) -> str:
        event_id = self.event_id or _first(_EVENT_ID, request) or "unknown"
        versions = []
        if self.member_version_1:
            versions.append(self.member_version_1)
        if self.member_version_2:
            versions.append(self.member_version_2)
        if not versions:
            versions = _VERSION_ID.findall(_blob(request))[:4]
        lines = (
            f"finding: {self.finding_line}",
            f"event_id: {event_id}",
            f"version_ids: {','.join(versions)}",
            "evidence: attached",
            "root_state: resolved",
        )
        quoted = " ".join(shlex.quote(line) for line in lines)
        return f"printf '%s\\n' {quoted} > TEAM_REPORT.md"


def _is_member(request: Mapping[str, Any]) -> bool:
    return MEMBER_TASK in _blob(request) and not _has_output(request, "spawn-1")


def _has_output(request: Mapping[str, Any], call_id: str) -> bool:
    for item in _input_items(request):
        if (
            isinstance(item, dict)
            and item.get("type") in _OUTPUT_TYPES
            and item.get("call_id") == call_id
        ):
            return True
    return False


def _output_json(request: Mapping[str, Any], call_id: str) -> dict[str, Any] | None:
    for item in _input_items(request):
        if not isinstance(item, dict):
            continue
        if item.get("type") not in _OUTPUT_TYPES or item.get("call_id") != call_id:
            continue
        return _decode_output(item.get("output"))
    return None


def _decode_output(raw: object) -> dict[str, Any] | None:
    """Read the tool result out of a code-mode cell's printed output.

    A code cell returns a status header followed by whatever the script printed,
    as separate text parts. The JSON the stub asked for is one of those parts,
    so each is tried rather than assuming the whole blob parses.
    """

    candidates: list[str] = []
    if isinstance(raw, str):
        candidates.append(raw)
    elif isinstance(raw, list):
        for part in raw:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                candidates.append(part["text"])
    for text in reversed(candidates):
        text = text.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _outputs_with_prefix(
    request: Mapping[str, Any], prefix: str
) -> list[tuple[str, dict[str, Any] | None]]:
    found: list[tuple[str, dict[str, Any] | None]] = []
    for item in _input_items(request):
        if not isinstance(item, dict):
            continue
        if item.get("type") not in _OUTPUT_TYPES:
            continue
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or not (
            call_id == prefix or call_id.startswith(f"{prefix}-")
        ):
            continue
        found.append((call_id, _output_json(request, call_id)))
    return found


def _input_items(request: Mapping[str, Any]) -> list[Any]:
    value = request.get("input")
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        nested = value.get("input")
        if isinstance(nested, list):
            return list(nested)
    return []


def _blob(request: Mapping[str, Any]) -> str:
    return json.dumps(request, default=str)


def _first(pattern: re.Pattern[str], request: Mapping[str, Any]) -> str | None:
    match = pattern.search(_blob(request))
    return match.group(0) if match else None


def _shell_call(_request: Mapping[str, Any], call_id: str, command: str) -> bytes:
    """Run a shell command through the code-mode surface a real model sees."""

    encoded_command = json.dumps(command)
    source = (
        f"const command = {encoded_command}; "
        "let fn, args; "
        "if (typeof tools.exec_command === 'function') { "
        "fn = tools.exec_command; args = {cmd: command, yield_time_ms: 10000, "
        "max_output_tokens: 2000}; "
        "} else if (typeof tools.shell_command === 'function') { "
        "fn = tools.shell_command; args = {command, timeout_ms: 10000}; "
        "} else if (typeof tools.shell === 'function') { "
        "fn = tools.shell; args = {command, timeout_ms: 10000}; "
        "} else { throw new Error('no shell binding available: ' + "
        "Object.keys(tools).join(',')); } "
        "const r = await fn(args); text(JSON.stringify(r));"
    )
    return _exec_call(call_id, source)


def _team_call(call_id: str, name: str, arguments: Mapping[str, Any]) -> bytes:
    return _call(call_id, name, arguments)


def _call(call_id: str, name: str, arguments: Mapping[str, Any]) -> bytes:
    """Emit the call the way a `code_mode_only` model actually emits it.

    One `custom_tool_call` named `exec` whose input is JavaScript that awaits the
    tool. This is not cosmetic: it is the shape that makes the rehearsal exercise
    the code-mode host, the nested dispatch path, and the rollout-trace evidence
    the paid gate reads. The previous stub emitted a top-level `function_call`,
    which the binary happily executed -- and which is why a rehearsal could go
    green while the real wire shape had no evidence path at all.
    """

    return _exec_call(call_id, _tool_script(name, arguments))


def _tool_script(name: str, arguments: Mapping[str, Any]) -> str:
    payload = json.dumps(dict(arguments), separators=(",", ":"))
    # Resolve the binding at runtime rather than hard-coding one spelling. Which
    # namespace a tool ends up under is a registry decision, and guessing wrong
    # makes the stub fail in a way that reads as the product failing. Whichever
    # binding is picked, the judge still reads the dispatch the registry
    # recorded, so this cannot widen what counts as evidence.
    return _pick_script([f"{COLLAB_NAMESPACE}__{name}", name], payload)


def _pick_script(candidates: list[str], payload: str) -> str:
    names = json.dumps(candidates, separators=(",", ":"))
    return (
        f"const names = {names}; "
        "const fn = names.map(n => tools[n]).find(f => typeof f === 'function'); "
        "if (!fn) { throw new Error('no tool among ' + names.join(',') "
        "+ ' available: ' + Object.keys(tools).join(',')); } "
        f"const r = await fn({payload}); text(JSON.stringify(r));"
    )


def _exec_call(call_id: str, source: str) -> bytes:
    return _sse(
        call_id,
        {
            "type": "response.output_item.done",
            "item": {
                "type": "custom_tool_call",
                "call_id": call_id,
                "name": "exec",
                "input": source,
            },
        },
    )


def _say(item_id: str, message: str) -> bytes:
    return _sse(
        item_id,
        {
            "type": "response.output_item.done",
            "item": {
                "type": "message",
                "role": "assistant",
                "id": f"msg-{item_id}",
                "content": [{"type": "output_text", "text": message}],
            },
        },
    )


def _sse(response_id: str, item: Mapping[str, Any]) -> bytes:
    events = (
        {"type": "response.created", "response": {"id": f"resp-{response_id}"}},
        dict(item),
        {
            "type": "response.completed",
            "response": {
                "id": f"resp-{response_id}",
                "usage": {
                    "input_tokens": 0,
                    "input_tokens_details": None,
                    "output_tokens": 0,
                    "output_tokens_details": None,
                    "total_tokens": 0,
                },
            },
        },
    )
    text = "".join(
        f"event: {event['type']}\ndata: "
        f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n\n"
        for event in events
    )
    return text.encode("utf-8")
