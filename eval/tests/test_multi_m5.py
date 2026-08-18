from __future__ import annotations

import json
import sys
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import (  # noqa: E402
    Product,
    Side,
    TEAM_CAPABILITY_MULTI_TOML,
    team_capability_override_items,
)
from rondo_eval.multi_m5.archive import archive_record, required_archive_fields  # noqa: E402
from rondo_eval.multi_m5.load import (  # noqa: E402
    M5ContractError,
    load_nondegradation_contract,
    load_runtime_identity,
    load_workflow_contract,
)
from rondo_eval.multi_m5.loopback import (  # noqa: E402
    LOOPBACK_BEARER,
    LOOPBACK_CALL_ID,
    LOOPBACK_MODEL,
    REQUIRED_TOOL_NAMES,
    TeamPublishFakeServer,
    build_loopback_command,
    collect_code_mode_tool_names,
    collect_registered_tool_names,
    collect_tool_names,
    team_capability_command_fragment,
)
from rondo_eval.multi_m5.collect import collect_gate1_evidence  # noqa: E402
from rondo_eval.multi_m5.predicates import evaluate_collaboration  # noqa: E402
from rondo_eval.multi_m5.schedule import (  # noqa: E402
    base_slots,
    conditional_slots,
    degradation_on_task,
)


FINDING = "M5-COLLAB-FINDING: orders.legacy_total is dropped by migration 0042"


class MultiM5ContractTests(unittest.TestCase):
    def test_workflow_lock_matches_fixtures_and_adapter_override(self) -> None:
        contract = load_workflow_contract()
        self.assertFalse(contract.docker)
        self.assertEqual(contract.finding_line, FINDING)
        self.assertEqual(contract.override_toml, TEAM_CAPABILITY_MULTI_TOML)
        self.assertEqual(
            contract.predicate_ids,
            (
                "spawn_member",
                "event_with_two_versions",
                "two_authors",
                "team_route",
                "team_evidence",
                "root_resolved",
                "root_woken",
            ),
        )
        self.assertEqual(
            team_capability_override_items(Product.RONDO_MULTI),
            (
                f"features.multi_agent_v2={TEAM_CAPABILITY_MULTI_TOML}",
                'agents.default_subagent_model="gpt-5.6-sol"',
                'agents.default_subagent_reasoning_effort="medium"',
            ),
        )
        self.assertEqual(team_capability_override_items(Product.RONDO_LOCAL), ())
        self.assertEqual(team_capability_override_items(None), ())

    def test_nondegradation_lock_is_task_major_codex_then_multi(self) -> None:
        contract = load_nondegradation_contract()
        slots = base_slots(contract)
        self.assertEqual(len(slots), 20)
        self.assertEqual(slots[0].side, Side.CODEX)
        self.assertIsNone(slots[0].product)
        self.assertEqual(slots[1].side, Side.RONDO)
        self.assertEqual(slots[1].product, Product.RONDO_MULTI)
        self.assertEqual(contract.max_effective_runs, 60)
        self.assertEqual(contract.hard_cap_usd, "120.00")
        self.assertEqual(len(contract.docker_images), 10)
        extra = conditional_slots(
            contract,
            {
                contract.tasks[0]: {
                    "codex": "completed",
                    "rondo-multi": "agent_failed",
                }
            },
        )
        self.assertEqual(len(extra), 4)
        self.assertEqual(extra[0].kind, "conditional")
        self.assertEqual(
            len(
                conditional_slots(
                    contract,
                    {
                        contract.tasks[0]: {
                            "codex": "completed",
                            "rondo-multi": "budget_stopped",
                        }
                    },
                )
            ),
            4,
        )
        self.assertEqual(
            conditional_slots(contract, {contract.tasks[0]: {"codex": "completed", "rondo-multi": "completed"}}),
            (),
        )

    def test_runtime_lock_is_pending_until_the_bundle_is_frozen(self) -> None:
        identity = load_runtime_identity()
        self.assertEqual(identity.source_commit, "7a2ff684c504c7530660f9a33a372daa949bdb00")
        self.assertTrue(
            identity.bundle_relpath.endswith(
                "7a2ff684c504c7530660f9a33a372daa949bdb00-x86_64-unknown-linux-musl-runtime-bundle"
            )
        )
        if identity.status == "pending_freeze":
            self.assertFalse(identity.frozen)
            with self.assertRaises(M5ContractError):
                load_runtime_identity(require_frozen=True, common_root=Path("/tmp"))
        else:
            self.assertTrue(identity.frozen)
            self.assertRegex(identity.codex_sha256 or "", r"^[0-9a-f]{64}$")


class MultiM5PredicateTests(unittest.TestCase):
    def _dump(self) -> dict[str, object]:
        return {
            "entries": [
                {"entry": "participant", "label": "/root", "role": "root"},
                {"entry": "participant", "label": "/root/worker", "role": "member"},
                {"entry": "event", "event_id": "e1", "version_count": 2, "route_count": 1},
                {
                    "entry": "version",
                    "version_id": "v1",
                    "author": "/root/worker",
                    "root_state": "resolved",
                    "fact_ref_count": 1,
                },
                {
                    "entry": "version",
                    "version_id": "v2",
                    "author": "/root",
                    "root_state": "tracking",
                    "fact_ref_count": 0,
                },
                {"entry": "route", "route_id": "r1", "event_id": "e1", "target": "/root/worker"},
                {"entry": "version_fact", "version_id": "v1", "fact_id": "f1"},
            ],
            "log": [
                {
                    "kind": "publish",
                    "actor": "/root/worker",
                    "target": "e1",
                    "wake": {
                        "decision": "signalled",
                        "target": "/root",
                        "rule": "member_publish",
                    },
                }
            ],
        }

    def test_complete_dump_and_report_pass(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(
                self._dump(), workspace=workspace, finding_line=FINDING
            )
        self.assertTrue(verdict.passed)
        self.assertTrue(all(verdict.predicates.values()))

    def test_solo_root_fails_even_with_a_perfect_report(self) -> None:
        dump = {
            "entries": [
                {"entry": "participant", "label": "/root", "role": "root"},
                {
                    "entry": "version",
                    "version_id": "v1",
                    "author": "/root",
                    "root_state": "resolved",
                    "fact_ref_count": 1,
                },
            ]
        }
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(dump, workspace=workspace, finding_line=FINDING)
        self.assertFalse(verdict.passed)
        self.assertIn("predicate:spawn_member", verdict.reasons)
        self.assertIn("predicate:two_authors", verdict.reasons)
        self.assertIn("predicate:team_route", verdict.reasons)

    def test_two_members_fail_the_spawn_cap(self) -> None:
        dump = self._dump()
        assert isinstance(dump["entries"], list)
        dump["entries"].append(
            {"entry": "participant", "label": "/root/extra", "role": "member"}
        )
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(
                dump, workspace=workspace, finding_line=FINDING, max_members=1
            )
        self.assertFalse(verdict.passed)
        self.assertFalse(verdict.predicates["spawn_member"])
        self.assertIn("predicate:spawn_member", verdict.reasons)

    def test_two_singleton_events_are_not_a_shared_chain(self) -> None:
        # Real dumps have no event_id on Version. Grouping follows dump order:
        # Event, its Versions/VersionFacts, its Routes, then the next Event.
        dump = {
            "entries": [
                {"entry": "participant", "label": "/root", "role": "root"},
                {"entry": "participant", "label": "/root/worker", "role": "member"},
                {"entry": "event", "event_id": "e1", "version_count": 1, "route_count": 1},
                {
                    "entry": "version",
                    "version_id": "v1",
                    "author": "/root/worker",
                    "root_state": "resolved",
                    "fact_ref_count": 1,
                },
                {"entry": "version_fact", "version_id": "v1", "fact_id": "f1"},
                {"entry": "route", "route_id": "r1", "event_id": "e1", "target": "/root/worker"},
                {"entry": "event", "event_id": "e2", "version_count": 1, "route_count": 0},
                {
                    "entry": "version",
                    "version_id": "v2",
                    "author": "/root",
                    "root_state": "tracking",
                    "fact_ref_count": 0,
                },
            ]
        }
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(dump, workspace=workspace, finding_line=FINDING)
        self.assertFalse(verdict.passed)
        self.assertFalse(verdict.predicates["event_with_two_versions"])
        self.assertIn("predicate:event_with_two_versions", verdict.reasons)

    def test_root_solo_event_plus_stray_member_event_fails(self) -> None:
        dump = {
            "entries": [
                {"entry": "participant", "label": "/root", "role": "root"},
                {"entry": "participant", "label": "/root/worker", "role": "member"},
                {"entry": "event", "event_id": "e1", "version_count": 2, "route_count": 0},
                {
                    "entry": "version",
                    "version_id": "v1",
                    "author": "/root",
                    "root_state": "resolved",
                    "fact_ref_count": 1,
                },
                {
                    "entry": "version",
                    "version_id": "v2",
                    "author": "/root",
                    "root_state": "tracking",
                    "fact_ref_count": 0,
                },
                {"entry": "event", "event_id": "e2", "version_count": 1, "route_count": 1},
                {
                    "entry": "version",
                    "version_id": "v3",
                    "author": "/root/worker",
                    "root_state": "pending",
                    "fact_ref_count": 0,
                },
                {"entry": "route", "route_id": "r1", "event_id": "e2", "target": "/root/worker"},
            ],
            "log": [
                {
                    "kind": "publish",
                    "wake": {"decision": "signalled", "target": "/root"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(dump, workspace=workspace, finding_line=FINDING)
        self.assertFalse(verdict.passed)
        self.assertFalse(verdict.predicates["two_authors"])
        self.assertFalse(verdict.predicates["team_route"])
        self.assertFalse(verdict.predicates["root_resolved"])

    def test_resolving_a_root_version_does_not_count_as_root_resolved(self) -> None:
        dump = self._dump()
        assert isinstance(dump["entries"], list)
        dump["entries"][3]["root_state"] = "tracking"
        dump["entries"][4]["root_state"] = "resolved"
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(dump, workspace=workspace, finding_line=FINDING)
        self.assertFalse(verdict.passed)
        self.assertFalse(verdict.predicates["root_resolved"])
        self.assertIn("predicate:root_resolved", verdict.reasons)

    def test_complete_dump_without_root_wake_fails(self) -> None:
        dump = self._dump()
        dump["log"] = []
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(dump, workspace=workspace, finding_line=FINDING)
        self.assertFalse(verdict.passed)
        self.assertFalse(verdict.predicates["root_woken"])
        self.assertIn("predicate:root_woken", verdict.reasons)

    def test_mailbox_wait_is_not_team_wake(self) -> None:
        dump_payload = self._dump()
        dump_payload["log"] = []
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "type": "function_call",
                        "name": "team_inspect",
                        "call_id": "dump-1",
                        "arguments": '{"action":"dump"}',
                    }
                ),
                json.dumps(
                    {
                        "type": "function_call_output",
                        "call_id": "dump-1",
                        "output": json.dumps(
                            {"action": "dump", "entries": dump_payload["entries"]}
                        ),
                    }
                ),
                json.dumps(
                    {
                        "type": "function_call_output",
                        "call_id": "wait-1",
                        "output": json.dumps(
                            {"message": "Wait completed.", "timed_out": False}
                        ),
                    }
                ),
            ]
        )
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(
                {}, workspace=workspace, finding_line=FINDING, jsonl=jsonl
            )
        self.assertFalse(verdict.passed)
        self.assertFalse(verdict.predicates["root_woken"])

    def test_jsonl_does_not_keep_a_caller_dump_when_inspect_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(
                self._dump(),
                workspace=workspace,
                finding_line=FINDING,
                jsonl="{}\n",
            )
        self.assertFalse(verdict.passed)
        self.assertFalse(verdict.predicates["spawn_member"])
        self.assertFalse(verdict.predicates["event_with_two_versions"])

    def test_jsonl_wait_and_inspect_are_harness_owned(self) -> None:
        dump = {
            "entries": [
                {"entry": "participant", "label": "/root", "role": "root"},
                {"entry": "participant", "label": "/root/worker", "role": "member"},
            ]
        }
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "function_call",
                            "name": "team_inspect",
                            "call_id": "dump-1",
                            "arguments": '{"action":"dump"}',
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "function_call_output",
                            "call_id": "dump-1",
                            "output": json.dumps(
                                {
                                    "action": "dump",
                                    "entries": self._dump()["entries"],
                                }
                            ),
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "function_call",
                            "name": "wait_agent",
                            "call_id": "wait-1",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "function_call_output",
                            "call_id": "wait-1",
                            "output": json.dumps(
                                {
                                    "message": (
                                        "Wait completed: the team world state changed. "
                                        "The current active view is in this request."
                                    ),
                                    "timed_out": False,
                                }
                            ),
                        },
                    }
                ),
            ]
        )
        collected = collect_gate1_evidence(jsonl)
        self.assertEqual(collected["entries"][2]["event_id"], "e1")
        self.assertTrue(any("team world state changed" in item for item in collected["jsonl_signals"]))
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "TEAM_REPORT.md").write_text(f"finding: {FINDING}\n", encoding="utf-8")
            verdict = evaluate_collaboration(
                dump, workspace=workspace, finding_line=FINDING, jsonl=jsonl
            )
        self.assertTrue(verdict.passed)
        self.assertTrue(verdict.predicates["root_woken"])

    def test_responses_input_order_collects_inspect_dump(self) -> None:
        jsonl = json.dumps(
            {
                "model": "gpt-5.6-sol",
                "input": [
                    {
                        "type": "function_call",
                        "name": "team_inspect",
                        "call_id": "dump-1",
                        "arguments": '{"action":"dump"}',
                    },
                    {
                        "type": "function_call_output",
                        "call_id": "dump-1",
                        "output": json.dumps(
                            {"action": "dump", "entries": self._dump()["entries"]}
                        ),
                    },
                ],
            }
        )
        collected = collect_gate1_evidence(jsonl)
        self.assertEqual(collected["entries"][2]["event_id"], "e1")

    def test_dump_pages_with_a_cursor_concatenate(self) -> None:
        first = [
            {"entry": "participant", "label": "/root", "role": "root"},
            {"entry": "event", "event_id": "e1", "version_count": 1, "route_count": 0},
            {"entry": "version", "version_id": "v1", "author": "/root/worker"},
        ]
        second = [
            {"entry": "version", "version_id": "v2", "author": "/root"},
            {"entry": "route", "route_id": "r1", "event_id": "e1", "target": "/root/worker"},
        ]
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "type": "function_call",
                        "name": "team_inspect",
                        "call_id": "p1",
                        "arguments": '{"action":"dump"}',
                    }
                ),
                json.dumps(
                    {
                        "type": "function_call_output",
                        "call_id": "p1",
                        "output": json.dumps({"action": "dump", "entries": first}),
                    }
                ),
                json.dumps(
                    {
                        "type": "function_call",
                        "name": "team_inspect",
                        "call_id": "p2",
                        "arguments": '{"action":"dump","cursor":"page-2"}',
                    }
                ),
                json.dumps(
                    {
                        "type": "function_call_output",
                        "call_id": "p2",
                        "output": json.dumps({"action": "dump", "entries": second}),
                    }
                ),
            ]
        )
        collected = collect_gate1_evidence(jsonl)
        kinds = [row["entry"] for row in collected["entries"]]
        self.assertEqual(kinds, ["participant", "event", "version", "version", "route"])

    def test_a_later_dump_without_cursor_replaces_stale_pages(self) -> None:
        jsonl = "\n".join(
            [
                json.dumps(
                    {
                        "type": "function_call",
                        "name": "team_inspect",
                        "call_id": "early",
                        "arguments": '{"action":"dump"}',
                    }
                ),
                json.dumps(
                    {
                        "type": "function_call_output",
                        "call_id": "early",
                        "output": json.dumps(
                            {
                                "action": "dump",
                                "entries": [{"entry": "event", "event_id": "stale"}],
                            }
                        ),
                    }
                ),
                json.dumps(
                    {
                        "type": "function_call",
                        "name": "team_inspect",
                        "call_id": "final",
                        "arguments": '{"action":"dump"}',
                    }
                ),
                json.dumps(
                    {
                        "type": "function_call_output",
                        "call_id": "final",
                        "output": json.dumps(
                            {
                                "action": "dump",
                                "entries": [{"entry": "event", "event_id": "fresh"}],
                            }
                        ),
                    }
                ),
            ]
        )
        collected = collect_gate1_evidence(jsonl)
        self.assertEqual(collected["entries"][0]["event_id"], "fresh")

    def test_nested_tool_specs_do_not_steal_a_dump_call(self) -> None:
        jsonl = json.dumps(
            {
                "tools": [{"type": "function", "name": "shell", "call_id": "dump-1"}],
                "input": [
                    {
                        "type": "function_call",
                        "name": "team_inspect",
                        "call_id": "dump-1",
                        "arguments": '{"action":"dump"}',
                    },
                    {
                        "type": "function_call_output",
                        "call_id": "dump-1",
                        "output": json.dumps(
                            {
                                "action": "dump",
                                "entries": [{"entry": "event", "event_id": "kept"}],
                            }
                        ),
                    },
                ],
            }
        )
        collected = collect_gate1_evidence(jsonl)
        self.assertEqual(collected["entries"][0]["event_id"], "kept")


class MultiM5ScheduleTests(unittest.TestCase):
    def test_three_one_way_failures_are_stable_degradation(self) -> None:
        pair = {"codex": "completed", "rondo-multi": "agent_failed"}
        self.assertEqual(
            degradation_on_task((pair, pair, pair)),
            "stable_one_way_degradation",
        )

    def test_first_round_one_way_failure_is_uncertain_until_reruns(self) -> None:
        self.assertEqual(
            degradation_on_task(({"codex": "completed", "rondo-multi": "agent_failed"},)),
            "uncertain",
        )

    def test_mixed_results_are_not_degradation(self) -> None:
        self.assertEqual(
            degradation_on_task(
                (
                    {"codex": "completed", "rondo-multi": "agent_failed"},
                    {"codex": "completed", "rondo-multi": "completed"},
                    {"codex": "completed", "rondo-multi": "agent_failed"},
                )
            ),
            "no_stable_one_way_degradation",
        )


class MultiM5ArchiveTests(unittest.TestCase):
    def test_loopback_record_is_labelled_and_not_effective(self) -> None:
        record = archive_record(
            evidence_kind="loopback",
            gate=1,
            lock_id="multi-m5-runtime-v1",
            side=Side.RONDO,
            product=Product.RONDO_MULTI,
            source_commit="a" * 40,
            binary_sha256="b" * 64,
            outcome="completed",
            counts_as_effective=False,
        )
        for name in required_archive_fields():
            self.assertIn(name, record)
        self.assertEqual(record["evidence_kind"], "loopback")
        self.assertFalse(record["counts_as_effective"])
        self.assertEqual(record["team_capability_config"]["team_state_enabled"], True)
        with self.assertRaises(ValueError):
            archive_record(
                evidence_kind="paid",
                gate=1,
                lock_id="x",
                side=Side.RONDO,
                product=Product.RONDO_MULTI,
                source_commit="a" * 40,
                binary_sha256="b" * 64,
                outcome="completed",
                counts_as_effective=False,
            )


class MultiM5LoopbackTests(unittest.TestCase):
    def test_command_contains_the_single_team_override(self) -> None:
        command = build_loopback_command(
            Path("/tmp/codex"),
            base_url="http://127.0.0.1:9/v1",
            instruction="publish",
        )
        fragment = team_capability_command_fragment()
        joined = " ".join(command)
        self.assertIn(fragment, command)
        self.assertEqual(joined.count("features.multi_agent_v2="), 1)
        self.assertIn('agents.default_subagent_model="gpt-5.6-sol"', joined)
        self.assertIn("expose_spawn_agent_model_overrides=false", joined)
        self.assertIn("features.code_mode_host=true", joined)
        self.assertNotIn("auto_review.model", joined)

    def test_fake_server_requires_team_tools_and_completes_a_round_trip(self) -> None:
        tools = [
            {"type": "namespace", "name": "collaboration", "tools": [
                {"type": "function", "name": name} for name in REQUIRED_TOOL_NAMES[:4]
            ]},
            {"type": "function", "name": "spawn_agent"},
        ]
        with TeamPublishFakeServer() as server:
            port = int(server.base_url.rsplit(":", 1)[1].split("/")[0])
            first = {
                "model": LOOPBACK_MODEL,
                "stream": True,
                "tools": tools,
            }
            status, payload = _post_responses(port, first)
            self.assertEqual(status, 200)
            self.assertIn("team_publish", payload.decode("utf-8"))
            second = {
                "model": LOOPBACK_MODEL,
                "stream": True,
                "input": [
                    {
                        "type": "function_call_output",
                        "call_id": LOOPBACK_CALL_ID,
                        "output": "{\"ok\":true}",
                    }
                ],
            }
            status, _payload = _post_responses(port, second)
            self.assertEqual(status, 200)
            self.assertTrue(server.tool_round_trip)
            self.assertEqual(server.missing_tools, ())
            self.assertGreaterEqual(collect_tool_names(tools), set(REQUIRED_TOOL_NAMES))

    def test_fake_server_rejects_a_session_without_team_tools(self) -> None:
        with TeamPublishFakeServer() as server:
            port = int(server.base_url.rsplit(":", 1)[1].split("/")[0])
            status, body = _post_responses(
                port,
                {"model": LOOPBACK_MODEL, "tools": [{"name": "shell"}]},
            )
            self.assertEqual(status, 400)
            self.assertIn(b"required team tools", body)
            self.assertFalse(server.tool_round_trip)

    def test_code_mode_metadata_counts_as_team_tool_registration(self) -> None:
        metadata = {
            "code_mode_tool_names": {
                f"collaboration__{name}": {"name": name, "namespace": "collaboration"}
                for name in REQUIRED_TOOL_NAMES
            }
        }
        request = {
            "client_metadata": {
                "x-codex-turn-metadata": json.dumps(metadata, separators=(",", ":")),
            }
        }
        self.assertEqual(collect_tool_names(request.get("tools")), set())
        self.assertGreaterEqual(collect_code_mode_tool_names(request), set(REQUIRED_TOOL_NAMES))
        self.assertGreaterEqual(collect_registered_tool_names(request), set(REQUIRED_TOOL_NAMES))
        with TeamPublishFakeServer() as server:
            port = int(server.base_url.rsplit(":", 1)[1].split("/")[0])
            status, payload = _post_responses(
                port,
                {"model": LOOPBACK_MODEL, "stream": True, **request},
            )
            self.assertEqual(status, 200)
            self.assertIn("team_publish", payload.decode("utf-8"))
            self.assertEqual(server.missing_tools, ())


def _post_responses(port: int, payload: dict[str, object]) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "POST",
            "/v1/responses",
            body=body,
            headers={
                "Authorization": f"Bearer {LOOPBACK_BEARER}",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
