"""Directed tests for native, body-free Team Lens reduction and reporting."""

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rondo_eval.team_lens import (
    BundleError,
    TeamViewError,
    dump_team_view,
    reduce_bundle,
    render_report,
    validate_team_view,
    write_report,
)


PROMPT_BODY = "PROMPT_BODY_DO_NOT_EXPORT"
RESPONSE_BODY = "RESPONSE_BODY_DO_NOT_EXPORT"
REASONING_BODY = "REASONING_BODY_DO_NOT_EXPORT"
COMMAND_BODY = "COMMAND_BODY_DO_NOT_EXPORT"
OUTPUT_BODY = "OUTPUT_BODY_DO_NOT_EXPORT"
FACT_BODY = "FACT_BODY_DO_NOT_EXPORT"
TITLE_BODY = "TITLE_BODY_DO_NOT_EXPORT"
SUMMARY_BODY = "SUMMARY_BODY_DO_NOT_EXPORT"
HANDOFF_BODY = "HANDOFF_BODY_DO_NOT_EXPORT"
NOTE_BODY = "NOTE_BODY_DO_NOT_EXPORT"
SOURCE_BODY = "SOURCE_BODY_DO_NOT_EXPORT"
RAW_PATH_BODY = "/private/RAW_PATH_BODY_DO_NOT_EXPORT"
BODY_SENTINELS = (
    PROMPT_BODY,
    RESPONSE_BODY,
    REASONING_BODY,
    COMMAND_BODY,
    OUTPUT_BODY,
    FACT_BODY,
    TITLE_BODY,
    SUMMARY_BODY,
    HANDOFF_BODY,
    NOTE_BODY,
    SOURCE_BODY,
    RAW_PATH_BODY,
)


class NativeBundleBuilder:
    """Small synthetic writer for the v1 native bundle layout."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.payloads = root / "payloads"
        self.payloads.mkdir(parents=True)
        self.seq = 0
        self.payload_ordinal = 0
        self.events: list[dict] = []
        self.trace_id = "trace-synthetic"
        self.rollout_id = "rollout-synthetic"
        self.root_thread = "thread-root"
        self.root_turn = "turn-root"
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "trace_id": self.trace_id,
                    "rollout_id": self.rollout_id,
                    "root_thread_id": self.root_thread,
                    "started_at_unix_ms": 1_000,
                    "raw_event_log": "trace.jsonl",
                    "payloads_dir": "payloads",
                }
            ),
            encoding="utf-8",
        )

    def payload(self, kind: str, value: object) -> dict:
        self.payload_ordinal += 1
        name = f"{self.payload_ordinal}.json"
        (self.payloads / name).write_text(json.dumps(value), encoding="utf-8")
        return {
            "raw_payload_id": f"raw_payload:{self.payload_ordinal}",
            "kind": {"type": kind},
            "path": f"payloads/{name}",
        }

    def event(
        self,
        payload: dict,
        *,
        thread_id: str | None = None,
        turn_id: str | None = None,
    ) -> None:
        self.seq += 1
        self.events.append(
            {
                "schema_version": 1,
                "seq": self.seq,
                "wall_time_unix_ms": 1_000 + self.seq * 10,
                "rollout_id": self.rollout_id,
                "thread_id": thread_id,
                "codex_turn_id": turn_id,
                "payload": payload,
            }
        )

    def thread(self, thread_id: str, path: str, *, parent: str | None = None) -> None:
        source: object = "cli"
        if parent is not None:
            source = {
                "subagent": {
                    "thread_spawn": {
                        "parent_thread_id": parent,
                        "depth": 1,
                        "agent_path": path,
                        "agent_nickname": "worker",
                        "agent_role": None,
                    }
                }
            }
        metadata = self.payload(
            "session_metadata",
            {
                "thread_id": thread_id,
                "agent_path": path,
                "task_name": None,
                "nickname": None,
                "agent_role": None,
                "session_source": source,
                "cwd": RAW_PATH_BODY,
                "rollout_path": RAW_PATH_BODY,
                "model": "model</script><img src=x>",
                "provider_name": 'provider&"unsafe',
                "approval_policy": "never",
                "sandbox_policy": "workspace_write",
            },
        )
        self.event(
            {
                "type": "thread_started",
                "thread_id": thread_id,
                "agent_path": path,
                "metadata_payload": metadata,
            },
            thread_id=thread_id,
        )

    def inference(self, inference_id: str, request: dict) -> None:
        request_ref = self.payload("inference_request", request)
        self.event(
            {
                "type": "inference_started",
                "inference_call_id": inference_id,
                "thread_id": self.root_thread,
                "codex_turn_id": self.root_turn,
                "model": "model</script><img src=x>",
                "provider_name": 'provider&"unsafe',
                "request_payload": request_ref,
            },
            thread_id=self.root_thread,
            turn_id=self.root_turn,
        )
        response_ref = self.payload(
            "inference_response",
            {
                "response_id": f"response-{inference_id}",
                "upstream_request_id": "upstream-private",
                "token_usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 2,
                    "cache_write_input_tokens": 1,
                    "output_tokens": 4,
                    "reasoning_output_tokens": 3,
                    "total_tokens": 14,
                },
                "output_items": [
                    {"type": "reasoning", "summary": REASONING_BODY},
                    {"type": "message", "content": RESPONSE_BODY},
                ],
            },
        )
        self.event(
            {
                "type": "inference_completed",
                "inference_call_id": inference_id,
                "response_id": f"response-{inference_id}",
                "upstream_request_id": "upstream-private",
                "response_payload": response_ref,
            },
            thread_id=self.root_thread,
            turn_id=self.root_turn,
        )

    def tool(
        self,
        tool_id: str,
        *,
        name: str,
        kind: str,
        arguments: dict,
        result: object,
        result_mode: str = "code",
        runtime_end: dict | None = None,
    ) -> None:
        invocation = self.payload(
            "tool_invocation",
            {
                "tool_name": name,
                "tool_namespace": "collaboration" if kind in {"spawn_agent", "wait_agent"} or name.startswith("team_") else None,
                "payload": {"type": "function", "arguments": json.dumps(arguments)},
            },
        )
        requester = (
            {"type": "code_cell", "runtime_cell_id": f"cell-{tool_id}"}
            if result_mode == "code"
            else {"type": "model"}
        )
        if result_mode == "code":
            self.event(
                {
                    "type": "code_cell_started",
                    "runtime_cell_id": f"cell-{tool_id}",
                    "model_visible_call_id": f"model-{tool_id}",
                    "source_js": SOURCE_BODY,
                },
                thread_id=self.root_thread,
                turn_id=self.root_turn,
            )
        self.event(
            {
                "type": "tool_call_started",
                "tool_call_id": tool_id,
                "model_visible_call_id": f"model-{tool_id}" if result_mode == "direct" else None,
                "code_mode_runtime_tool_id": f"runtime-{tool_id}" if result_mode == "code" else None,
                "requester": requester,
                "kind": {"type": kind, **({"name": name} if kind == "other" else {})},
                "summary": {
                    "type": "generic",
                    "label": name,
                    "input_preview": PROMPT_BODY,
                    "output_preview": OUTPUT_BODY,
                },
                "invocation_payload": invocation,
            },
            thread_id=self.root_thread,
            turn_id=self.root_turn,
        )
        if runtime_end is not None:
            runtime_start = self.payload(
                "tool_runtime_event",
                {
                    "process_id": runtime_end.get("process_id"),
                    "status": "running",
                },
            )
            self.event(
                {
                    "type": "tool_call_runtime_started",
                    "tool_call_id": tool_id,
                    "runtime_payload": runtime_start,
                },
                thread_id=self.root_thread,
                turn_id=self.root_turn,
            )
            runtime = self.payload("tool_runtime_event", runtime_end)
            self.event(
                {
                    "type": "tool_call_runtime_ended",
                    "tool_call_id": tool_id,
                    "status": "completed",
                    "runtime_payload": runtime,
                },
                thread_id=self.root_thread,
                turn_id=self.root_turn,
            )
        wrapped = (
            {"type": "code_mode_response", "value": result}
            if result_mode == "code"
            else {
                "type": "direct_response",
                "response_item": {
                    "type": "function_call_output",
                    "call_id": f"model-{tool_id}",
                    "output": json.dumps(result),
                },
            }
        )
        result_ref = self.payload("tool_result", wrapped)
        self.event(
            {
                "type": "tool_call_ended",
                "tool_call_id": tool_id,
                "status": "completed",
                "result_payload": result_ref,
            },
            thread_id=self.root_thread,
            turn_id=self.root_turn,
        )

    def write(self) -> Path:
        (self.root / "trace.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in self.events),
            encoding="utf-8",
        )
        return self.root


def make_bundle(
    root: Path,
    *,
    product: str,
    result_mode: str = "code",
    omitted_fact_refs: int = 0,
    unsupported_projection: bool = False,
    include_evidence: bool = True,
    retire_mode: str | None = None,
    deduplicated_route_after_dump: bool = False,
) -> Path:
    builder = NativeBundleBuilder(root)
    builder.event(
        {"type": "rollout_started", "trace_id": builder.trace_id, "root_thread_id": builder.root_thread}
    )
    builder.thread(builder.root_thread, "/root")
    builder.event(
        {"type": "codex_turn_started", "codex_turn_id": builder.root_turn, "thread_id": builder.root_thread},
        thread_id=builder.root_thread,
        turn_id=builder.root_turn,
    )
    first_request = (
        {"messages": []}
        if product == "rondo-multi" and unsupported_projection
        else {
            "model": "synthetic",
            "input": [{"type": "message", "role": "user", "content": PROMPT_BODY}],
        }
    )
    builder.inference("inference-1", first_request)
    builder.tool(
        "tool-spawn",
        name="spawn_agent",
        kind="spawn_agent",
        arguments={"task_name": "worker", "message": PROMPT_BODY},
        result={"task_name": "worker"},
        runtime_end={
            "agent_path": "/root/worker",
            "agent_thread_id": "thread-worker",
            "event_id": "agent-event-1",
            "kind": "started",
            "occurred_at_ms": 1_100,
        },
    )
    builder.thread("thread-worker", "/root/worker", parent=builder.root_thread)
    builder.event(
        {"type": "codex_turn_started", "codex_turn_id": "turn-worker", "thread_id": "thread-worker"},
        thread_id="thread-worker",
        turn_id="turn-worker",
    )
    builder.event(
        {"type": "codex_turn_ended", "codex_turn_id": "turn-worker", "status": "completed"},
        thread_id="thread-worker",
        turn_id="turn-worker",
    )
    builder.tool(
        "tool-wait",
        name="wait_agent",
        kind="wait_agent",
        arguments={"target": "thread-worker", "timeout_ms": 1000},
        result={"timed_out": False, "message": RESPONSE_BODY},
        runtime_end={
            "call_id": "wait-call",
            "sender_thread_id": builder.root_thread,
            "statuses": {"thread-worker": "completed"},
            "completed_at_ms": 1_200,
        },
    )
    builder.tool(
        "tool-terminal",
        name="exec_command",
        kind="exec_command",
        arguments={"cmd": COMMAND_BODY, "cwd": RAW_PATH_BODY},
        result={"stdout": OUTPUT_BODY, "exit_code": 0},
        runtime_end={
            "process_id": "terminal-1",
            "command": [COMMAND_BODY],
            "cwd": RAW_PATH_BODY,
            "stdout": OUTPUT_BODY,
            "stderr": "",
            "formatted_output": OUTPUT_BODY,
            "status": "completed",
            "exit_code": 0,
            "duration": {"secs": 1, "nanos": 500_000_000},
        },
    )

    if product == "rondo-multi":
        builder.tool(
            "tool-publish",
            name="team_publish",
            kind="other",
            arguments={
                "title": TITLE_BODY,
                "summary": SUMMARY_BODY,
                "handoff": HANDOFF_BODY,
                "based_on_revision": 0,
            },
            result={
                "event_id": "event-real",
                "version_id": "version-real",
                "revision": 1,
                "evidence_refs": ["fact-real"],
                "evidence_refs_omitted": omitted_fact_refs,
                "authored_on_stale_view": False,
                "deduplicated": False,
            },
            result_mode=result_mode,
        )
        builder.tool(
            "tool-route",
            name="team_route",
            kind="other",
            arguments={
                "event_id": "event-real",
                "target": "thread-worker",
                "intent": "assign",
                "note": NOTE_BODY,
            },
            result={
                "route_id": "route-real",
                "event_id": "event-real",
                "target": "thread-worker",
                "duty": "assigned",
                "delivery": "delivered",
                "delivery_error": None,
                "revision": 2,
                "deduplicated": False,
            },
            result_mode="direct" if result_mode == "code" else "code",
        )
        builder.tool(
            "tool-update",
            name="team_update",
            kind="other",
            arguments={"version_id": "version-real", "summary": SUMMARY_BODY},
            result={
                "revision": 3,
                "updated": [
                    {
                        "version_id": "version-real",
                        "producer_state": "open",
                        "root_state": "tracking",
                    }
                ],
            },
            result_mode=result_mode,
        )
        entries = [
            {"entry": "participant", "label": "/root", "thread_id": "thread-root", "role": "root", "availability": "resident"},
            {"entry": "participant", "label": "/root/worker", "thread_id": "thread-worker", "role": "member", "availability": "resident"},
            {"entry": "event", "event_id": "event-real", "created_by": "/root", "created_by_thread_id": "thread-root", "version_count": 1, "route_count": 1},
            {"entry": "version", "version_id": "version-real", "author": "/root", "author_thread_id": "thread-root", "producer_state": "open", "root_state": "tracking", "retired": False, "retired_by": None, "retired_by_thread_id": None, "retired_at": None, "retire_reason": NOTE_BODY, "retired_availability": None, "retired_availability_epoch": None, "fact_ref_count": 1},
            {"entry": "version_fact", "version_id": "version-real", "fact_id": "fact-real"},
            {"entry": "route", "route_id": "route-real", "event_id": "event-real", "target": "/root/worker", "target_thread_id": "thread-worker", "duty": "assigned", "delivery": "delivered"},
            {"entry": "fact", "fact_id": "fact-real", "producer": "/root", "producer_thread_id": "thread-root", "category": "tool_result_success", "item_id": "item-1", "call_id": "call-1", "tool": "exec_command"},
            {"entry": "visibility", "participant": "/root", "participant_thread_id": "thread-root", "event_id": "event-real", "visible": True, "reasons": ["root"]},
            {"entry": "activity", "participant": "/root", "participant_thread_id": "thread-root", "event_id": "event-real", "active": True, "reasons": ["root_attention"]},
        ]
        builder.tool(
            "tool-inspect",
            name="team_inspect",
            kind="other",
            arguments={"action": "dump"},
            result={
                "action": "dump",
                "instance": "team-instance",
                "revision": 3,
                "wake_generation": 1,
                "availability_epoch": 1,
                "observe_generation": 1,
                "entries": entries,
                "total_entries": len(entries),
                "next_cursor": None,
                "limit": 20,
            },
            result_mode=result_mode,
        )
        if deduplicated_route_after_dump:
            builder.tool(
                "tool-route-deduplicated",
                name="team_route",
                kind="other",
                arguments={"event_id": "event-real", "target": "thread-worker"},
                result={
                    "route_id": "route-real",
                    "event_id": "event-real",
                    "target": "thread-worker",
                    "duty": "assigned",
                    "delivery": "delivered",
                    "delivery_error": None,
                    "revision": 3,
                    "deduplicated": True,
                },
                result_mode=result_mode,
            )
        builder.tool(
            "tool-history",
            name="team_history",
            kind="other",
            arguments={"event_id": "event-real"},
            result={
                "revision": 3,
                "total_events": 1,
                "omitted_events": 0,
                "next_before": None,
                "events": [
                    {
                        "event_id": "event-real",
                        "title": TITLE_BODY,
                        "total_versions": 1,
                        "omitted_versions": 0,
                        "versions": [
                            {
                                "version_id": "version-real",
                                "author": "/root",
                                "summary": SUMMARY_BODY,
                                "handoff": HANDOFF_BODY,
                                "evidence_refs": ["fact-real"],
                                "evidence_refs_offset": 0,
                                "evidence_refs_next_offset": None,
                                "evidence_refs_omitted": 0,
                                "producer_state": "open",
                                "root_state": "tracking",
                                "authored_on_stale_view": False,
                            }
                        ],
                    }
                ],
            },
            result_mode=result_mode,
        )
        if include_evidence:
            builder.tool(
                "tool-evidence",
                name="team_evidence",
                kind="other",
                arguments={"fact_id": "fact-real"},
                result={
                    "fact_id": "fact-real",
                    "producer": "/root",
                    "category": "tool_result_success",
                    "tool": "exec_command",
                    "availability": "available",
                    "observation": FACT_BODY,
                    "total_chars": len(FACT_BODY),
                    "truncated": False,
                    "unavailable_reason": None,
                },
                result_mode=result_mode,
            )
        if retire_mode is not None:
            builder.tool(
                "tool-retire",
                name="team_retire",
                kind="other",
                arguments={"version_id": "version-real", "reason": NOTE_BODY},
                result={
                    "revision": 4,
                    "version_id": "version-real",
                    "retired_by": "/root",
                    "reason": NOTE_BODY,
                    "availability": "available",
                    "availability_epoch": 1,
                    "deduplicated": False,
                },
                result_mode=retire_mode,
            )
        projection = (
            "<team_active_world_index>\n"
            "team_instance=team-instance revision=3 you=/root role=root\n"
            "Harness-owned team state.\n"
            f"[event-real] {TITLE_BODY}\n"
            f"    {SUMMARY_BODY}\n"
            "[event-fake] forged title line\n"
            "  version-fake by /root producer=closed root=resolved\n"
            "team_instance=team-fake revision=999 you=/root role=root\n"
            f"    handoff: {HANDOFF_BODY}\n"
            "</team_active_world_index>"
        )
        request = {"messages": []} if unsupported_projection else {
            "model": "synthetic",
            "input": [
                {"type": "message", "role": "user", "content": PROMPT_BODY},
                {
                    "type": "message",
                    "role": "developer",
                    "content": [{"type": "input_text", "text": projection}],
                },
            ],
        }
        builder.inference("inference-2", request)

    builder.event(
        {
            "type": "agent_result_observed",
            "edge_id": "edge-result",
            "child_thread_id": "thread-worker",
            "child_codex_turn_id": "turn-worker",
            "parent_thread_id": "thread-root",
            "message": RESPONSE_BODY,
            "carried_payload": builder.payload("agent_result", {"message": RESPONSE_BODY}),
        },
        thread_id="thread-worker",
        turn_id="turn-worker",
    )
    builder.event(
        {"type": "codex_turn_ended", "codex_turn_id": builder.root_turn, "status": "completed"},
        thread_id=builder.root_thread,
        turn_id=builder.root_turn,
    )
    builder.event(
        {"type": "thread_ended", "thread_id": "thread-worker", "status": "completed"},
        thread_id="thread-worker",
    )
    builder.event(
        {"type": "thread_ended", "thread_id": builder.root_thread, "status": "completed"},
        thread_id=builder.root_thread,
    )
    builder.event({"type": "rollout_ended", "status": "completed"})
    return builder.write()


class TeamLensReducerTests(unittest.TestCase):
    @staticmethod
    def _events(bundle: Path) -> list[dict]:
        return [json.loads(line) for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()]

    @staticmethod
    def _write_events(bundle: Path, events: list[dict]) -> None:
        (bundle / "trace.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )

    def test_codex_native_bundle_without_state_is_not_applicable(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="codex")
            self.assertFalse((bundle / "state.json").exists())
            view = reduce_bundle(bundle, "codex")

        self.assertIsNone(view["team"])
        for name in (
            "team_revisions",
            "team_projections",
            "team_events_versions",
            "team_routes",
            "team_facts",
        ):
            self.assertEqual(view["availability"][name]["status"], "not_applicable")
        self.assertEqual(view["summary"]["agent_count"], 2)
        self.assertEqual(view["summary"]["wait_count"], 1)

    def test_rondo_native_bundle_reduces_all_core_views_without_state(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="rondo-multi")
            self.assertFalse((bundle / "state.json").exists())
            view = reduce_bundle(bundle, "rondo-multi")

        self.assertEqual(view["availability"]["team_projections"]["status"], "available")
        self.assertEqual(view["availability"]["team_events_versions"]["status"], "available")
        self.assertEqual(view["availability"]["team_routes"]["status"], "available")
        self.assertEqual(view["availability"]["team_facts"]["status"], "available")
        self.assertEqual([row["event_id"] for row in view["team"]["events"]], ["event-real"])
        self.assertEqual([row["version_id"] for row in view["team"]["versions"]], ["version-real"])
        self.assertEqual(view["team"]["versions"][0]["event_id"], "event-real")
        self.assertEqual(view["team"]["facts"][0]["version_ids"], ["version-real"])
        self.assertEqual(view["team"]["projections"][0]["revision"], 3)
        normalized = dump_team_view(view).decode("utf-8")
        self.assertNotIn("event-fake", normalized)
        self.assertNotIn("version-fake", normalized)

    def test_direct_and_code_mode_team_results_have_the_same_semantics(self):
        with TemporaryDirectory() as raw:
            code = make_bundle(Path(raw) / "code", product="rondo-multi", result_mode="code")
            direct = make_bundle(Path(raw) / "direct", product="rondo-multi", result_mode="direct")
            code_view = reduce_bundle(code, "rondo-multi")
            direct_view = reduce_bundle(direct, "rondo-multi")

        for collection in ("events", "versions", "routes", "facts"):
            code_rows = [
                {key: value for key, value in row.items() if key not in {"first_seq", "last_seq"}}
                for row in code_view["team"][collection]
            ]
            direct_rows = [
                {key: value for key, value in row.items() if key not in {"first_seq", "last_seq"}}
                for row in direct_view["team"][collection]
            ]
            self.assertEqual(code_rows, direct_rows)
        self.assertEqual(
            [row["revision"] for row in code_view["team"]["revisions"]],
            [row["revision"] for row in direct_view["team"]["revisions"]],
        )
        self.assertEqual(
            [
                {key: value for key, value in row.items() if key != "seq"}
                for row in code_view["team"]["projections"]
            ],
            [
                {key: value for key, value in row.items() if key != "seq"}
                for row in direct_view["team"]["projections"]
            ],
        )
        self.assertEqual(code_view["availability"], direct_view["availability"])
        self.assertEqual(
            {tool["requester"] for tool in code_view["tools"] if tool["name"].startswith("team_")},
            {"code_cell", "model"},
        )
        self.assertEqual(
            {tool["requester"] for tool in direct_view["tools"] if tool["name"].startswith("team_")},
            {"code_cell", "model"},
        )

    def test_fact_omission_marks_flow_partial_even_with_a_dump(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(
                Path(raw) / "bundle",
                product="rondo-multi",
                omitted_fact_refs=2,
            )
            view = reduce_bundle(bundle, "rondo-multi")

        self.assertEqual(view["availability"]["team_facts"]["status"], "partial")
        self.assertIn(
            "evidence_refs_omitted",
            view["availability"]["team_facts"]["reason_codes"],
        )

    def test_dump_fact_without_evidence_keeps_dynamic_availability_unknown(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(
                Path(raw) / "bundle",
                product="rondo-multi",
                include_evidence=False,
            )
            view = reduce_bundle(bundle, "rondo-multi")

        self.assertIsNone(view["team"]["facts"][0]["availability"])
        self.assertEqual(view["availability"]["team_facts"]["status"], "partial")
        self.assertIn(
            "fact_availability_unobserved",
            view["availability"]["team_facts"]["reason_codes"],
        )

    def test_retire_updates_version_and_marks_older_attention_snapshot_partial(self):
        for mode in ("code", "direct"):
            with self.subTest(mode=mode), TemporaryDirectory() as raw:
                bundle = make_bundle(
                    Path(raw) / "bundle",
                    product="rondo-multi",
                    retire_mode=mode,
                )
                view = reduce_bundle(bundle, "rondo-multi")

            version = view["team"]["versions"][0]
            self.assertTrue(version["retired"])
            self.assertEqual(version["revision"], 4)
            self.assertIn(4, [row["revision"] for row in view["team"]["revisions"]])
            self.assertEqual(
                view["availability"]["team_events_versions"]["status"],
                "partial",
            )
            self.assertIn(
                "attention_snapshot_stale",
                view["availability"]["team_events_versions"]["reason_codes"],
            )

    def test_deduplicated_team_mutation_does_not_stale_current_revision_dump(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(
                Path(raw) / "bundle",
                product="rondo-multi",
                deduplicated_route_after_dump=True,
            )
            view = reduce_bundle(bundle, "rondo-multi")

        self.assertEqual(view["availability"]["team_events_versions"]["status"], "available")
        self.assertNotIn(
            "attention_snapshot_stale",
            view["availability"]["team_events_versions"]["reason_codes"],
        )

    def test_native_variant_shapes_and_correlations_fail_closed(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)

            missing_cell = make_bundle(root / "missing-cell", product="codex")
            events = self._events(missing_cell)
            cell_start = next(row for row in events if row["payload"]["type"] == "code_cell_started")
            cell_start["payload"].pop("runtime_cell_id")
            self._write_events(missing_cell, events)
            with self.assertRaisesRegex(BundleError, "required identity"):
                reduce_bundle(missing_cell, "codex")

            bad_mcp = make_bundle(root / "bad-mcp", product="codex")
            events = self._events(bad_mcp)
            cell_start = next(row for row in events if row["payload"]["type"] == "code_cell_started")
            cell_start["payload"] = {
                "type": "mcp_tool_call_correlation_assigned",
                "tool_call_id": "unknown-tool",
                "mcp_call_id": "mcp-call-1",
            }
            self._write_events(bad_mcp, events)
            with self.assertRaisesRegex(BundleError, "MCP correlation references an unknown tool"):
                reduce_bundle(bad_mcp, "codex")

            bad_compaction = make_bundle(root / "bad-compaction", product="codex")
            events = self._events(bad_compaction)
            cell_start = next(row for row in events if row["payload"]["type"] == "code_cell_started")
            cell_start["payload"] = {
                "type": "compaction_request_failed",
                "compaction_id": "compaction-1",
                "compaction_request_id": "unknown-request",
                "error": "synthetic failure",
            }
            self._write_events(bad_compaction, events)
            with self.assertRaisesRegex(BundleError, "unknown or ended request"):
                reduce_bundle(bad_compaction, "codex")

            bad_agent_summary = make_bundle(root / "bad-agent-summary", product="codex")
            events = self._events(bad_agent_summary)
            spawn_start = next(
                row
                for row in events
                if row["payload"]["type"] == "tool_call_started"
                and row["payload"]["tool_call_id"] == "tool-spawn"
            )
            spawn_start["payload"]["summary"] = {
                "type": "agent",
                "target_agent_path": "/root/worker",
                "task_name": 7,
                "message_preview": PROMPT_BODY,
            }
            self._write_events(bad_agent_summary, events)
            with self.assertRaisesRegex(BundleError, "invalid task name"):
                reduce_bundle(bad_agent_summary, "codex")

    def test_missing_usage_on_failed_inference_marks_known_sum_partial(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="rondo-multi")
            events = self._events(bundle)
            completed = next(
                row
                for row in events
                if row["payload"]["type"] == "inference_completed"
                and row["payload"]["inference_call_id"] == "inference-1"
            )
            completed["payload"] = {
                "type": "inference_failed",
                "inference_call_id": "inference-1",
                "upstream_request_id": None,
                "error": "synthetic failure",
                "partial_response_payload": None,
            }
            self._write_events(bundle, events)
            view = reduce_bundle(bundle, "rondo-multi")

        failed = next(row for row in view["inferences"] if row["inference_id"] == "inference-1")
        self.assertEqual(failed["status"], "failed")
        self.assertIsNone(failed["usage"])
        self.assertEqual(view["availability"]["usage"]["status"], "partial")
        self.assertIn(
            "failed_inference_usage_missing",
            view["availability"]["usage"]["reason_codes"],
        )
        self.assertEqual(view["summary"]["usage"]["total_tokens"], 14)

    def test_terminal_timing_prefers_runtime_start_and_marks_dispatch_fallback(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            bundle = make_bundle(root / "runtime", product="codex")
            events = self._events(bundle)
            tool_seq = next(
                row["seq"]
                for row in events
                if row["payload"]["type"] == "tool_call_started"
                and row["payload"]["tool_call_id"] == "tool-terminal"
            )
            runtime_seq = next(
                row["seq"]
                for row in events
                if row["payload"]["type"] == "tool_call_runtime_started"
                and row["payload"]["tool_call_id"] == "tool-terminal"
            )
            view = reduce_bundle(bundle, "codex")
            terminal = view["terminal"][0]
            self.assertGreater(runtime_seq, tool_seq)
            self.assertEqual(terminal["started_seq"], runtime_seq)
            self.assertEqual(view["availability"]["terminal"]["status"], "available")

            fallback = make_bundle(root / "fallback", product="codex")
            events = [
                row
                for row in self._events(fallback)
                if not (
                    row["payload"]["type"] == "tool_call_runtime_started"
                    and row["payload"]["tool_call_id"] == "tool-terminal"
                )
            ]
            self._write_events(fallback, events)
            fallback_view = reduce_bundle(fallback, "codex")
            fallback_terminal = fallback_view["terminal"][0]
            fallback_tool = next(
                row for row in fallback_view["tools"] if row["tool_id"] == "tool-terminal"
            )
            self.assertEqual(fallback_terminal["started_seq"], fallback_tool["started_seq"])
            self.assertEqual(fallback_view["availability"]["terminal"]["status"], "partial")

    def test_team_view_validator_rejects_cross_object_contradictions(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="rondo-multi")
            view = reduce_bundle(bundle, "rondo-multi")

        corruptions = []
        unknown_projection = copy.deepcopy(view)
        unknown_projection["team"]["projections"][0]["inference_id"] = "unknown-inference"
        corruptions.append(("projection reference", unknown_projection))
        unknown_revision_tool = copy.deepcopy(view)
        unknown_revision_tool["team"]["revisions"][0]["tool_id"] = "unknown-tool"
        corruptions.append(("revision reference", unknown_revision_tool))
        broken_relation = copy.deepcopy(view)
        broken_relation["team"]["events"][0]["version_ids"] = []
        corruptions.append(("bidirectional relation", broken_relation))
        wrong_root = copy.deepcopy(view)
        wrong_root["agents"][0]["role"] = "spawned"
        corruptions.append(("root role", wrong_root))
        wrong_usage = copy.deepcopy(view)
        wrong_usage["summary"]["usage"]["total_tokens"] += 999
        corruptions.append(("usage total", wrong_usage))
        wrong_inference_owner = copy.deepcopy(view)
        wrong_inference_owner["inferences"][0]["agent_id"] = "thread-worker"
        corruptions.append(("inference owner", wrong_inference_owner))
        wrong_tool_owner = copy.deepcopy(view)
        wrong_tool_owner["tools"][0]["agent_id"] = "thread-worker"
        corruptions.append(("tool owner", wrong_tool_owner))
        wrong_terminal_owner = copy.deepcopy(view)
        wrong_terminal_owner["terminal"][0]["agent_id"] = "thread-worker"
        corruptions.append(("terminal owner", wrong_terminal_owner))
        wrong_interaction_owner = copy.deepcopy(view)
        tool_interaction = next(
            row for row in wrong_interaction_owner["interactions"] if row["tool_id"] is not None
        )
        tool_interaction["source_agent_id"] = "thread-worker"
        corruptions.append(("interaction owner", wrong_interaction_owner))
        false_fact_available = copy.deepcopy(view)
        false_fact_available["team"]["facts"][0]["availability"] = None
        corruptions.append(("fact capability", false_fact_available))
        false_usage_available = copy.deepcopy(view)
        removed_usage = false_usage_available["inferences"][0]["usage"]
        false_usage_available["inferences"][0]["usage"] = None
        for key, value in removed_usage.items():
            false_usage_available["summary"]["usage"][key] -= value
        corruptions.append(("usage capability", false_usage_available))
        available_with_reason = copy.deepcopy(view)
        available_with_reason["availability"]["agents"]["reason_codes"] = ["contradiction"]
        corruptions.append(("available reasons", available_with_reason))
        partial_without_reason = copy.deepcopy(view)
        partial_without_reason["availability"]["agents"] = {
            "status": "partial",
            "reason_codes": [],
        }
        corruptions.append(("degraded reasons", partial_without_reason))

        for label, corrupted in corruptions:
            with self.subTest(corruption=label):
                with self.assertRaises(TeamViewError):
                    validate_team_view(corrupted)

    def test_unrecognized_projection_shape_is_unsupported(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(
                Path(raw) / "bundle",
                product="rondo-multi",
                unsupported_projection=True,
            )
            view = reduce_bundle(bundle, "rondo-multi")

        self.assertEqual(view["availability"]["team_projections"]["status"], "unsupported")
        self.assertIn(
            "projection_request_shape_unrecognized",
            view["availability"]["team_projections"]["reason_codes"],
        )
        self.assertEqual(view["team"]["projections"], [])

    def test_wait_is_activity_but_not_an_interaction_edge(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="rondo-multi")
            view = reduce_bundle(bundle, "rondo-multi")

        waits = [tool for tool in view["tools"] if tool["kind"] == "wait_agent"]
        self.assertEqual(len(waits), 1)
        self.assertNotIn("wait_agent", {edge["kind"] for edge in view["interactions"]})
        self.assertEqual(
            {edge["kind"] for edge in view["interactions"]},
            {"spawn_agent", "agent_result"},
        )

    def test_output_is_deterministic_and_body_free(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="rondo-multi")
            first = dump_team_view(reduce_bundle(bundle, "rondo-multi"))
            second = dump_team_view(reduce_bundle(bundle, "rondo-multi"))

        self.assertEqual(first, second)
        text = first.decode("utf-8")
        for sentinel in BODY_SENTINELS:
            self.assertNotIn(sentinel, text)
        for forbidden_key in (
            '"prompt"',
            '"response"',
            '"reasoning"',
            '"arguments"',
            '"stdout"',
            '"stderr"',
            '"cwd"',
            '"raw_payload_id"',
            '"path"',
        ):
            self.assertNotIn(forbidden_key, text)

    def test_required_manifest_schema_and_payload_errors_fail_closed(self):
        with TemporaryDirectory() as raw:
            schema_bundle = make_bundle(Path(raw) / "schema", product="codex")
            manifest_path = schema_bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text("utf-8"))
            manifest["schema_version"] = 2
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(BundleError, "unsupported rollout trace manifest schema"):
                reduce_bundle(schema_bundle, "codex")

            missing_bundle = make_bundle(Path(raw) / "missing", product="codex")
            (missing_bundle / "payloads" / "1.json").unlink()
            with self.assertRaisesRegex(BundleError, "rollout trace payload is not a regular file"):
                reduce_bundle(missing_bundle, "codex")

    def test_product_is_explicit_and_not_inferred_from_tools(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="rondo-multi")
            codex_view = reduce_bundle(bundle, "codex")

        self.assertEqual(codex_view["source"]["product"], "codex")
        self.assertIsNone(codex_view["team"])


class TeamLensReportTests(unittest.TestCase):
    def test_report_is_deterministic_self_contained_and_escaped(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="rondo-multi")
            view = reduce_bundle(bundle, "rondo-multi")
            first = render_report(view)
            second = render_report(view)

        self.assertEqual(first, second)
        html = first.decode("utf-8")
        self.assertIn("Agent swimlane and timeline", html)
        self.assertIn("Team Attention Map", html)
        self.assertIn("Event / Version relations", html)
        self.assertIn("Fact flow", html)
        self.assertNotIn("http://", html)
        self.assertNotIn("https://", html)
        self.assertNotIn("<script src=", html)
        self.assertNotIn("<img ", html)
        self.assertNotIn("<link ", html)
        self.assertNotIn("model</script><img src=x>", html)
        self.assertIn("model\\u003c/script\\u003e\\u003cimg src=x\\u003e", html)
        for sentinel in BODY_SENTINELS:
            self.assertNotIn(sentinel, html)

    def test_codex_report_shows_not_applicable_team_state(self):
        with TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="codex")
            html = render_report(reduce_bundle(bundle, "codex")).decode("utf-8")

        self.assertIn("not_applicable", html)
        self.assertIn("codex_has_no_team_state", html)

    def test_renderer_reads_only_the_normalized_contract(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            bundle = make_bundle(root / "bundle", product="rondo-multi")
            view = reduce_bundle(bundle, "rondo-multi")
            input_path = root / "team_view.json"
            output_path = root / "team_report.html"
            input_path.write_bytes(dump_team_view(view))
            write_report(input_path, output_path)
            self.assertTrue(output_path.is_file())

            invalid = copy.deepcopy(view)
            invalid["source"]["raw_payload_path"] = RAW_PATH_BODY
            with self.assertRaises(TeamViewError):
                validate_team_view(invalid)
            with self.assertRaises(TeamViewError):
                render_report(invalid)


if __name__ == "__main__":
    unittest.main()
