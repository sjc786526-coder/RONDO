import json
from dataclasses import replace
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.multi_m5.collect import WAIT_TEAM_ACTIVITY_MARK  # noqa: E402
from rondo_eval.multi_m5.command import (  # noqa: E402
    build_multi_exec_command,
)
from rondo_eval.multi_m5.trace import (  # noqa: E402
    CodeCell,
    NestedToolCall,
    RolloutTrace,
)
from rondo_eval.publication_critic.engineering.producer_runtime import (  # noqa: E402
    FIXED_FEEDBACK_V1,
    INITIAL_SYNTHETIC_DRAFT,
    PRODUCER_FORMAL_PROMPT,
    PRODUCER_MEMBER_PROMPT,
    ProducerEvidenceError,
    build_producer_command,
    evaluate_producer_evidence,
    project_producer_attempts,
)


ROOT = "thread-root"
PRODUCER = "thread-producer"
ROOT_SOURCE = "spawn producer; wait_agent; inspect dump; inspect log"
PRODUCER_SOURCE = "publish initial; consume feedback; publish autonomous revision"
REVISED_DRAFT = "A bounded migration was attempted and its result was checked."
EVENT_ID = "evt-1"
VERSION_ID = "ver-1"


def _call(
    call_id: str,
    *,
    name: str,
    thread_id: str,
    cell_id: str,
    arguments: dict[str, object],
    result: object,
    seq: int,
    end_seq: int,
) -> NestedToolCall:
    return NestedToolCall(
        tool_call_id=call_id,
        tool_name=name,
        tool_namespace="collaboration",
        requester="code_cell",
        thread_id=thread_id,
        runtime_cell_id=cell_id,
        model_visible_call_id=None,
        arguments=arguments,
        result=result,
        status="completed",
        seq=seq,
        end_seq=end_seq,
    )


def _fixture(
    *,
    final_cycle: str = "cycle-1",
    second_thread: str = PRODUCER,
    duplicate_log: bool = False,
) -> tuple[str, RolloutTrace]:
    dump_entries = [
        {"entry": "participant", "thread_id": ROOT, "role": "root"},
        {"entry": "participant", "thread_id": PRODUCER, "role": "member"},
        {
            "entry": "event",
            "event_id": EVENT_ID,
            "created_by_thread_id": PRODUCER,
            "version_count": 1,
        },
        {
            "entry": "version",
            "version_id": VERSION_ID,
            "author_thread_id": PRODUCER,
        },
    ]
    publish_mutation = {
        "revision": 1,
        "actor_thread_id": PRODUCER,
        "kind": "publish",
        "target": VERSION_ID,
        "wake": {
            "decision": "signalled",
            "target_thread_id": ROOT,
            "rule": "member_publish",
        },
    }
    log_entries = [publish_mutation]
    if duplicate_log:
        log_entries.append({**publish_mutation, "revision": 2})

    cells = {
        (ROOT, "root-cell"): CodeCell(
            thread_id=ROOT,
            runtime_cell_id="root-cell",
            model_visible_call_id="wire-root",
            source_js=ROOT_SOURCE,
            seq=1,
        ),
        (PRODUCER, "producer-cell"): CodeCell(
            thread_id=PRODUCER,
            runtime_cell_id="producer-cell",
            model_visible_call_id="wire-producer",
            source_js=PRODUCER_SOURCE,
            seq=5,
        ),
    }
    if second_thread != PRODUCER:
        cells[(second_thread, "other-cell")] = CodeCell(
            thread_id=second_thread,
            runtime_cell_id="other-cell",
            model_visible_call_id="wire-other",
            source_js=PRODUCER_SOURCE,
            seq=8,
        )

    calls = [
        _call(
            "spawn",
            name="spawn_agent",
            thread_id=ROOT,
            cell_id="root-cell",
            arguments={"task_name": "producer", "message": PRODUCER_MEMBER_PROMPT},
            result={"agent_id": PRODUCER},
            seq=2,
            end_seq=3,
        ),
        _call(
            "wait",
            name="wait_agent",
            thread_id=ROOT,
            cell_id="root-cell",
            arguments={"timeout_ms": 30_000},
            result={"message": WAIT_TEAM_ACTIVITY_MARK, "timed_out": False},
            seq=4,
            end_seq=10,
        ),
        _call(
            "publish-1",
            name="team_publish",
            thread_id=PRODUCER,
            cell_id="producer-cell",
            arguments={"title": "Synthetic migration", "summary": INITIAL_SYNTHETIC_DRAFT},
            result={
                "status": "rewrite_required",
                "feedback_version": "v1",
                "feedback": FIXED_FEEDBACK_V1,
                "review_cycle_id": "cycle-1",
                "review_attempt": 1,
                "blocking_rewrite_count": 1,
                "candidate": {
                    "title": "Synthetic migration",
                    "summary": INITIAL_SYNTHETIC_DRAFT,
                    "handoff": None,
                },
            },
            seq=6,
            end_seq=7,
        ),
        _call(
            "publish-2",
            name="team_publish",
            thread_id=second_thread,
            cell_id="producer-cell" if second_thread == PRODUCER else "other-cell",
            arguments={
                "title": "Synthetic migration",
                "summary": REVISED_DRAFT,
                "review_cycle_id": final_cycle,
            },
            result={
                "event_id": EVENT_ID,
                "version_id": VERSION_ID,
                "revision": 1,
                "evidence_refs": [],
                "evidence_refs_omitted": 0,
                "authored_on_stale_view": False,
                "deduplicated": False,
                "publication_review": {
                    "status": "pass",
                    "review_attempt": 2,
                    "blocking_rewrite_count": 1,
                    "failure_kind": None,
                },
            },
            seq=8,
            end_seq=9,
        ),
        _call(
            "inspect-dump",
            name="team_inspect",
            thread_id=ROOT,
            cell_id="root-cell",
            arguments={"action": "dump", "limit": 50},
            result={
                "action": "dump",
                "instance": "team-1",
                "revision": 1,
                "entries": dump_entries,
                "total_entries": len(dump_entries),
                "next_cursor": None,
            },
            seq=11,
            end_seq=12,
        ),
        _call(
            "inspect-log",
            name="team_inspect",
            thread_id=ROOT,
            cell_id="root-cell",
            arguments={"action": "log", "limit": 50},
            result={
                "action": "log",
                "instance": "team-1",
                "revision": 1,
                "entries": log_entries,
                "total_entries": len(log_entries),
                "next_offset": None,
            },
            seq=13,
            end_seq=14,
        ),
    ]
    trace = RolloutTrace(
        bundle_dir=Path("/unused"),
        trace_id="trace-1",
        rollout_id="rollout-1",
        root_thread_id=ROOT,
        cells=cells,
        calls=calls,
    )
    requests = [
        {
            "model": "luna",
            "input": [
                {
                    "type": "custom_tool_call",
                    "call_id": "wire-root",
                    "name": "exec",
                    "input": ROOT_SOURCE,
                }
            ],
        },
        {
            "model": "luna",
            "input": [
                {
                    "type": "custom_tool_call",
                    "call_id": "wire-producer",
                    "name": "exec",
                    "input": PRODUCER_SOURCE,
                }
            ],
        },
    ]
    if second_thread != PRODUCER:
        requests.append(
            {
                "model": "luna",
                "input": [
                    {
                        "type": "custom_tool_call",
                        "call_id": "wire-other",
                        "name": "exec",
                        "input": PRODUCER_SOURCE,
                    }
                ],
            }
        )
    return "".join(json.dumps(request) + "\n" for request in requests), trace


class ProducerCommandTests(unittest.TestCase):
    def test_extends_the_shared_strict_multi_command_with_full_critic_config(self) -> None:
        descriptor = {"limits": {"job_timeout_ms": 120_000}, "identity": {"revision": "v1"}}
        command = build_producer_command(
            Path("/runtime/codex"),
            base_url="http://127.0.0.1:41000/v1",
            endpoint="127.0.0.1:42000",
            expected_descriptor=descriptor,
            call_timeout_ms=150_000,
            startup_timeout_ms=30_000,
            model="luna",
            effort="low",
        )
        shared = build_multi_exec_command(
            Path("/runtime/codex"),
            base_url="http://127.0.0.1:41000/v1",
            instruction=PRODUCER_FORMAL_PROMPT,
            model="luna",
            effort="low",
        )
        separator = command.index("--")
        shared_separator = shared.index("--")
        self.assertEqual(command[:shared_separator], shared[:shared_separator])
        overrides = command[shared_separator:separator]
        self.assertEqual(
            overrides,
            [
                "-c",
                "features.multi_agent_v2.subagent_developer_instructions="
                + json.dumps(PRODUCER_MEMBER_PROMPT),
                "-c",
                'features.multi_agent_v2.publication_critic.endpoint="127.0.0.1:42000"',
                "-c",
                "features.multi_agent_v2.publication_critic.expected_descriptor_json="
                + json.dumps(json.dumps(descriptor, sort_keys=True, separators=(",", ":"))),
                "-c",
                "features.multi_agent_v2.publication_critic.call_timeout_ms=150000",
                "-c",
                "features.multi_agent_v2.publication_critic.startup_timeout_ms=30000",
            ],
        )
        self.assertEqual(command[separator:], ["--", PRODUCER_FORMAL_PROMPT])


class ProducerEvidenceTests(unittest.TestCase):
    def test_accepts_a_paraphrased_spawn_when_member_task_is_runtime_injected(self) -> None:
        jsonl, trace = _fixture()
        paraphrased_spawn = replace(
            trace.calls[0],
            arguments={"task_name": "producer", "message": "paraphrased task"},
        )
        paraphrased_trace = replace(
            trace, calls=[paraphrased_spawn, *trace.calls[1:]]
        )

        result = evaluate_producer_evidence(jsonl, paraphrased_trace)

        self.assertEqual(result["status"], "passed")

    def test_failure_projection_retains_control_flow_without_bodies_or_ids(self) -> None:
        jsonl, trace = _fixture()
        result = project_producer_attempts(jsonl, trace)

        self.assertEqual(result["publish_attempt_count"], 2)
        self.assertEqual(
            result["attempts"],
            [
                {
                    "thread_role": "member",
                    "dispatch_status": "completed",
                    "result_kind": "rewrite_required",
                    "review_status": None,
                    "review_cycle_present": False,
                    "result_cycle_present": True,
                    "event_id_present": False,
                    "result_fields": [
                        "blocking_rewrite_count",
                        "candidate",
                        "feedback",
                        "feedback_version",
                        "review_attempt",
                        "review_cycle_id",
                        "status",
                    ],
                },
                {
                    "thread_role": "member",
                    "dispatch_status": "completed",
                    "result_kind": "canonical_commit",
                    "review_status": "pass",
                    "review_cycle_present": True,
                    "result_cycle_present": False,
                    "event_id_present": False,
                    "result_fields": [
                        "authored_on_stale_view",
                        "deduplicated",
                        "event_id",
                        "evidence_refs",
                        "evidence_refs_omitted",
                        "publication_review",
                        "revision",
                        "version_id",
                    ],
                },
            ],
        )
        self.assertTrue(result["producer_task_named"])
        encoded = json.dumps(result)
        for private in (
            INITIAL_SYNTHETIC_DRAFT,
            REVISED_DRAFT,
            "cycle-1",
            EVENT_ID,
            VERSION_ID,
        ):
            self.assertNotIn(private, encoded)

    def test_projects_one_rewrite_and_one_canonical_publish_without_bodies(self) -> None:
        jsonl, trace = _fixture()
        result = evaluate_producer_evidence(jsonl, trace)
        self.assertEqual(
            result,
            {
                "schema_version": 1,
                "status": "passed",
                "root_thread_id": ROOT,
                "producer_thread_id": PRODUCER,
                "wire_request_count": 2,
                "trace_cell_count": 2,
                "trace_nested_call_count": 6,
                "publish_attempt_count": 2,
                "rewrite_count": 1,
                "cycle_hop_count": 1,
                "feedback_versions": ["v1"],
                "final_review_status": "pass",
                "canonical_commit_count": 1,
                "event_count": 1,
                "version_count": 1,
                "publish_mutation_count": 1,
                "revision": 1,
                "event_id": EVENT_ID,
                "version_id": VERSION_ID,
                "root_wake": True,
                "inspect_actions": ["dump", "log"],
            },
        )
        encoded = json.dumps(result)
        self.assertNotIn(INITIAL_SYNTHETIC_DRAFT, encoded)
        self.assertNotIn(REVISED_DRAFT, encoded)
        self.assertNotIn("cycle-1", encoded)

    def test_rejects_a_rewrite_from_another_thread(self) -> None:
        jsonl, trace = _fixture(second_thread="thread-other")
        with self.assertRaisesRegex(ProducerEvidenceError, "producer_thread_invalid"):
            evaluate_producer_evidence(jsonl, trace)

    def test_rejects_a_broken_cycle_chain(self) -> None:
        jsonl, trace = _fixture(final_cycle="wrong-cycle")
        with self.assertRaisesRegex(
            ProducerEvidenceError, "final_candidate_or_cycle_invalid"
        ):
            evaluate_producer_evidence(jsonl, trace)

    def test_rejects_more_than_one_canonical_publish_mutation(self) -> None:
        jsonl, trace = _fixture(duplicate_log=True)
        with self.assertRaisesRegex(
            ProducerEvidenceError, "publish_mutation_count_invalid"
        ):
            evaluate_producer_evidence(jsonl, trace)


if __name__ == "__main__":
    unittest.main()
