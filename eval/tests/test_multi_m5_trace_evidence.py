"""Adversarial tests for the gate 1 code-mode evidence path.

The gate must be unfoolable by a model that controls its own JavaScript. These
cases are the concrete ways it could try: print a convincing dump without
calling anything, call the tool in a branch that never runs, call a look-alike
tool, or supply a trace from some other run.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rondo_eval.multi_m5.collect import EvidenceError, collect_gate1_evidence
from rondo_eval.multi_m5.predicates import evaluate_collaboration
from rondo_eval.multi_m5.trace import (
    TraceError,
    find_trace_bundle,
    load_rollout_trace,
)


ROLLOUT = "rollout-1"
THREAD = "thread-root"
CELL_JS = 'const r = await tools.collaboration__team_inspect({"action":"dump"}); text(JSON.stringify(r));'
DUMP = {
    "action": "dump",
    "entries": [
        {"entry": "participant", "label": "/root", "role": "root"},
        {"entry": "participant", "label": "/root/worker", "role": "member"},
    ],
}


class TraceBundleBuilder:
    """Write a minimal but structurally faithful trace bundle."""

    def __init__(self, root: Path, *, rollout_id: str = ROLLOUT) -> None:
        self.dir = root
        self.payloads = root / "payloads"
        self.payloads.mkdir(parents=True)
        self.rollout_id = rollout_id
        self.seq = 0
        self.ordinal = 0
        self.events: list[dict] = []
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "trace_id": "trace-1",
                    "rollout_id": rollout_id,
                    "root_thread_id": THREAD,
                    "started_at_unix_ms": 0,
                    "raw_event_log": "trace.jsonl",
                    "payloads_dir": "payloads",
                }
            ),
            encoding="utf-8",
        )

    def payload(self, kind: str, value: object) -> dict:
        self.ordinal += 1
        (self.payloads / f"{self.ordinal}.json").write_text(
            json.dumps(value), encoding="utf-8"
        )
        return {
            "raw_payload_id": f"raw_payload:{self.ordinal}",
            "kind": {"type": kind},
            "path": f"payloads/{self.ordinal}.json",
        }

    def event(self, payload: dict, *, thread_id: str = THREAD, seq: int | None = None):
        self.seq = seq if seq is not None else self.seq + 1
        self.events.append(
            {
                "schema_version": 1,
                "seq": self.seq,
                "wall_time_unix_ms": 0,
                "rollout_id": self.rollout_id,
                "thread_id": thread_id,
                "codex_turn_id": "turn-1",
                "payload": payload,
            }
        )

    def cell(self, cell_id: str, call_id: str, source: str, *, thread_id: str = THREAD):
        self.event(
            {
                "type": "code_cell_started",
                "runtime_cell_id": cell_id,
                "model_visible_call_id": call_id,
                "source_js": source,
            },
            thread_id=thread_id,
        )

    def nested(
        self,
        tool_call_id: str,
        *,
        name: str,
        namespace: str | None,
        cell_id: str,
        arguments: object,
        result: object,
        status: str = "completed",
        thread_id: str = THREAD,
        end: bool = True,
    ):
        invocation = self.payload(
            "tool_invocation",
            {"tool_name": name, "tool_namespace": namespace, "payload": arguments},
        )
        self.event(
            {
                "type": "tool_call_started",
                "tool_call_id": tool_call_id,
                "model_visible_call_id": None,
                "code_mode_runtime_tool_id": "rt-1",
                "requester": {"type": "code_cell", "runtime_cell_id": cell_id},
                "kind": {"type": "other", "name": name},
                "summary": {"type": "generic", "label": name},
                "invocation_payload": invocation,
            },
            thread_id=thread_id,
        )
        if not end:
            return
        result_ref = self.payload(
            "tool_result", {"type": "code_mode_response", "value": result}
        )
        self.event(
            {
                "type": "tool_call_ended",
                "tool_call_id": tool_call_id,
                "status": {"type": status},
                "result_payload": result_ref,
            },
            thread_id=thread_id,
        )

    def write(self) -> Path:
        (self.dir / "trace.jsonl").write_text(
            "".join(json.dumps(event) + "\n" for event in self.events),
            encoding="utf-8",
        )
        return self.dir


def capture(call_id: str, source: str) -> str:
    return json.dumps(
        {
            "model": "gpt-5.6-terra",
            "input": [
                {
                    "type": "custom_tool_call",
                    "call_id": call_id,
                    "name": "exec",
                    "input": source,
                }
            ],
        }
    )


class CodeModeEvidenceTest(unittest.TestCase):
    def test_dispatched_inspect_yields_dump_rows(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=DUMP,
            )
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", CELL_JS), trace)
        self.assertEqual(len(dump["entries"]), 2)
        self.assertEqual(dump["unattributed"], [])

    def test_script_printed_dump_is_not_evidence(self):
        """A cell that only *prints* a dump dispatched nothing, so nothing counts."""

        source = f'text({json.dumps(json.dumps(DUMP))});'
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", source)
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", source), trace)
        self.assertEqual(dump["entries"], [])
        self.assertEqual(dump["log"], [])
        self.assertEqual(dump["jsonl_signals"], [])

    def test_dead_branch_call_leaves_no_dispatch(self):
        """`if (false) { ... }` never reaches the registry, so it never traces."""

        source = f"if (false) {{ {CELL_JS} }} text('done');"
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", source)
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", source), trace)
        self.assertEqual(dump["entries"], [])
        self.assertEqual(dump["nested_calls"], 0)

    def test_wrong_namespace_is_not_team_inspect(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="impostor",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=DUMP,
            )
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", CELL_JS), trace)
        self.assertEqual(dump["entries"], [])
        self.assertEqual(dump["unattributed"], ["impostor.team_inspect"])

    def test_other_tool_echoing_a_dump_is_unattributed(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="shell_command",
                namespace=None,
                cell_id="cell-1",
                arguments={"type": "function", "arguments": "{}"},
                result=DUMP,
            )
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", CELL_JS), trace)
        self.assertEqual(dump["entries"], [])
        self.assertEqual(dump["unattributed"], ["shell_command"])

    def test_failed_required_inspect_is_refused(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=DUMP,
                status="failed",
            )
            trace = load_rollout_trace(builder.write())
            with self.assertRaisesRegex(EvidenceError, "did not complete"):
                collect_gate1_evidence(
                    capture("call-1", CELL_JS),
                    trace,
                    required_inspect_actions=("dump",),
                )

    def test_failed_optional_stats_does_not_poison_complete_required_inspects(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "stats-failed",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"stats"}'},
                result={"error": "optional stats unavailable"},
                status="failed",
            )
            builder.nested(
                "dump-ok",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result={
                    "action": "dump",
                    "entries": DUMP["entries"],
                    "next_cursor": None,
                    "total_entries": len(DUMP["entries"]),
                },
            )
            builder.nested(
                "log-ok",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"log"}'},
                result={
                    "action": "log",
                    "entries": [{"entry": "event_created"}],
                    "next_offset": None,
                    "total_entries": 1,
                },
            )
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(
                capture("call-1", CELL_JS),
                trace,
                required_inspect_actions=("dump", "log"),
            )
        self.assertEqual(dump["inspect_actions"], ["dump", "log"])
        self.assertEqual(len(dump["entries"]), 2)
        self.assertEqual(len(dump["log"]), 1)

    def test_trace_from_another_run_is_refused(self):
        """The cell must correspond to a call this capture actually contains."""

        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "other-call", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=DUMP,
            )
            trace = load_rollout_trace(builder.write())
            with self.assertRaises(EvidenceError):
                collect_gate1_evidence(capture("call-1", CELL_JS), trace)

    def test_source_mismatch_is_refused(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            trace = load_rollout_trace(builder.write())
            with self.assertRaises(EvidenceError):
                collect_gate1_evidence(capture("call-1", "text('something else');"), trace)

    def test_orphan_nested_call_is_refused(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="ghost-cell",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=DUMP,
            )
            trace = load_rollout_trace(builder.write())
            with self.assertRaises(EvidenceError):
                collect_gate1_evidence(capture("call-1", CELL_JS), trace)

    def test_same_cell_id_in_two_threads_is_not_a_collision(self):
        """Root and its members share a bundle; cell ids are per-thread."""

        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("1", "call-1", CELL_JS)
            builder.cell("1", "call-2", CELL_JS, thread_id="thread-member")
            trace = load_rollout_trace(builder.write())
        self.assertEqual(len(trace.cells), 2)

    def test_repeated_cell_id_in_one_thread_is_refused(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("1", "call-1", CELL_JS)
            builder.cell("1", "call-2", CELL_JS)
            with self.assertRaises(TraceError):
                load_rollout_trace(builder.write())

    def test_duplicate_sequence_number_is_refused(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.event(
                {
                    "type": "code_cell_started",
                    "runtime_cell_id": "cell-2",
                    "model_visible_call_id": "call-2",
                    "source_js": CELL_JS,
                },
                seq=1,
            )
            with self.assertRaises(TraceError):
                load_rollout_trace(builder.write())

    def test_unfinished_dispatch_is_refused(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": "{}"},
                result=DUMP,
                end=False,
            )
            with self.assertRaises(TraceError):
                load_rollout_trace(builder.write())

    def test_payload_escaping_the_bundle_is_refused(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.event(
                {
                    "type": "tool_call_started",
                    "tool_call_id": "exec-1",
                    "model_visible_call_id": None,
                    "code_mode_runtime_tool_id": "rt-1",
                    "requester": {"type": "code_cell", "runtime_cell_id": "cell-1"},
                    "kind": {"type": "other", "name": "team_inspect"},
                    "summary": {"type": "generic", "label": "team_inspect"},
                    "invocation_payload": {
                        "raw_payload_id": "raw_payload:9",
                        "kind": {"type": "tool_invocation"},
                        "path": "../escape.json",
                    },
                },
            )
            with self.assertRaises(TraceError):
                load_rollout_trace(builder.write())

    def test_missing_bundle_is_refused(self):
        with TemporaryDirectory() as raw:
            with self.assertRaises(TraceError):
                find_trace_bundle(Path(raw))

    def test_two_bundles_are_refused(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for name in ("trace-a", "trace-b"):
                TraceBundleBuilder(root / name).write()
            with self.assertRaises(TraceError):
                find_trace_bundle(root)

    def test_dump_pages_with_a_cursor_concatenate(self):
        """A cursor page continues the same snapshot, so its rows are added."""

        page_one = {
            "action": "dump",
            "entries": [{"entry": "event", "event_id": "e1"}],
            "next_cursor": "c1",
            "total_entries": 2,
        }
        page_two = {
            "action": "dump",
            "entries": [{"entry": "version", "author": "/root/worker"}],
            "next_cursor": None,
            "total_entries": 2,
        }
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=page_one,
            )
            builder.nested(
                "exec-2",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={
                    "type": "function",
                    "arguments": '{"action":"dump","cursor":"c1"}',
                },
                result=page_two,
            )
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", CELL_JS), trace)
        self.assertEqual(len(dump["entries"]), 2)

    def test_dump_with_an_unconsumed_cursor_is_refused(self):
        page_one = {
            "action": "dump",
            "entries": [{"entry": "event", "event_id": "e1"}],
            "next_cursor": "c1",
            "total_entries": 2,
        }
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=page_one,
            )
            trace = load_rollout_trace(builder.write())
            with self.assertRaisesRegex(EvidenceError, "before the final page"):
                collect_gate1_evidence(capture("call-1", CELL_JS), trace)

    def test_missing_required_log_inspection_is_refused(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result={
                    "action": "dump",
                    "entries": [],
                    "next_cursor": None,
                    "total_entries": 0,
                },
            )
            trace = load_rollout_trace(builder.write())
            with self.assertRaisesRegex(EvidenceError, "log"):
                collect_gate1_evidence(
                    capture("call-1", CELL_JS),
                    trace,
                    required_inspect_actions=("dump", "log"),
                )

    def test_required_dump_must_cover_its_reported_total(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result={
                    "action": "dump",
                    "entries": [{"entry": "event", "event_id": "e1"}],
                    "next_cursor": None,
                    "total_entries": 2,
                },
            )
            trace = load_rollout_trace(builder.write())
            with self.assertRaisesRegex(EvidenceError, "does not cover"):
                collect_gate1_evidence(
                    capture("call-1", CELL_JS),
                    trace,
                    required_inspect_actions=("dump",),
                )

    def test_dump_with_the_wrong_continuation_cursor_is_refused(self):
        page_one = {
            "action": "dump",
            "entries": [{"entry": "event", "event_id": "e1"}],
            "next_cursor": "c1",
            "total_entries": 2,
        }
        page_two = {
            "action": "dump",
            "entries": [{"entry": "version", "author": "/root/worker"}],
            "next_cursor": None,
            "total_entries": 2,
        }
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=page_one,
            )
            builder.nested(
                "exec-2",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={
                    "type": "function",
                    "arguments": '{"action":"dump","cursor":"wrong"}',
                },
                result=page_two,
            )
            trace = load_rollout_trace(builder.write())
            with self.assertRaisesRegex(EvidenceError, "does not continue"):
                collect_gate1_evidence(capture("call-1", CELL_JS), trace)

    def test_dump_continuation_cannot_change_the_snapshot_total(self):
        page_one = {
            "action": "dump",
            "entries": [{"entry": "event", "event_id": "e1"}],
            "next_cursor": "c1",
            "total_entries": 2,
        }
        page_two = {
            "action": "dump",
            "entries": [{"entry": "version", "version_id": "v1"}],
            "next_cursor": None,
            "total_entries": 3,
        }
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=page_one,
            )
            builder.nested(
                "exec-2",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={
                    "type": "function",
                    "arguments": '{"action":"dump","cursor":"c1"}',
                },
                result=page_two,
            )
            trace = load_rollout_trace(builder.write())
            with self.assertRaisesRegex(EvidenceError, "changed between pages"):
                collect_gate1_evidence(capture("call-1", CELL_JS), trace)

    def test_inspect_result_action_must_match_the_invocation(self):
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result={
                    "action": "log",
                    "entries": [],
                    "next_offset": None,
                    "total_entries": 0,
                },
            )
            trace = load_rollout_trace(builder.write())
            with self.assertRaisesRegex(EvidenceError, "differs from its invocation"):
                collect_gate1_evidence(capture("call-1", CELL_JS), trace)

    def test_a_later_cursorless_dump_replaces_stale_pages(self):
        """A fresh page is a new snapshot, so it must not be merged with the old."""

        stale = {
            "action": "dump",
            "entries": [{"entry": "event", "event_id": "old"}],
            "next_cursor": None,
            "total_entries": 1,
        }
        fresh = {
            "action": "dump",
            "entries": [
                {"entry": "event", "event_id": "new"},
                {"entry": "version", "version_id": "new-version"},
            ],
            "next_cursor": None,
            "total_entries": 2,
        }
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=stale,
            )
            builder.nested(
                "exec-2",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"dump"}'},
                result=fresh,
            )
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", CELL_JS), trace)
        self.assertEqual(dump["entries"], fresh["entries"])

    def test_a_later_zero_offset_log_replaces_a_completed_page_set(self):
        """A fresh log read may observe a larger total after the team changes."""

        stale = {
            "action": "log",
            "entries": [{"kind": "publish", "revision": 1}],
            "next_offset": None,
            "total_entries": 1,
        }
        fresh = {
            "action": "log",
            "entries": [
                {"kind": "publish", "revision": 1},
                {"kind": "resolve", "revision": 2},
            ],
            "next_offset": None,
            "total_entries": 2,
        }
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": '{"action":"log"}'},
                result=stale,
            )
            builder.nested(
                "exec-2",
                name="team_inspect",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={
                    "type": "function",
                    "arguments": '{"action":"log","offset":0}',
                },
                result=fresh,
            )
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", CELL_JS), trace)
        self.assertEqual(dump["log"], fresh["entries"])

    def test_wait_signal_requires_a_dispatched_wait(self):
        mark = (
            "Wait completed: the team world state changed. "
            "The current active view is in this request."
        )
        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="wait_agent",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": "{}"},
                result={"message": mark},
            )
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", CELL_JS), trace)
        self.assertEqual(dump["jsonl_signals"], [mark])

    def test_plain_wait_completion_is_not_a_team_wake(self):
        """A mailbox wait returns without the TeamActivity mark, so it is not a wake."""

        with TemporaryDirectory() as raw:
            builder = TraceBundleBuilder(Path(raw) / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            builder.nested(
                "exec-1",
                name="wait_agent",
                namespace="collaboration",
                cell_id="cell-1",
                arguments={"type": "function", "arguments": "{}"},
                result={"message": "Wait completed.", "timed_out": False},
            )
            trace = load_rollout_trace(builder.write())
            dump = collect_gate1_evidence(capture("call-1", CELL_JS), trace)
        self.assertEqual(dump["jsonl_signals"], [])

    def test_verdict_uses_trace_not_caller_dump(self):
        """A caller-supplied dump cannot smuggle a collaboration past the judge."""

        with TemporaryDirectory() as raw:
            root = Path(raw)
            builder = TraceBundleBuilder(root / "trace-1-thread-root")
            builder.cell("cell-1", "call-1", CELL_JS)
            trace = load_rollout_trace(builder.write())
            workspace = root / "workspace"
            workspace.mkdir()
            with self.assertRaisesRegex(EvidenceError, "required team_inspect actions"):
                evaluate_collaboration(
                    {"entries": DUMP["entries"], "log": [], "jsonl_signals": []},
                    workspace=workspace,
                    finding_line="X",
                    jsonl=capture("call-1", CELL_JS),
                    trace=trace,
                )


if __name__ == "__main__":
    unittest.main()
