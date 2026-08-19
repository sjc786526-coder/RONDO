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
    RUNTIME_LOCK_ID,
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
from rondo_eval.multi_m5.collect import (  # noqa: E402
    WAIT_TEAM_ACTIVITY_MARK,
    collect_gate1_evidence,
    member_message_delivery,
)
from rondo_eval.multi_m5.predicates import evaluate_collaboration  # noqa: E402
from rondo_eval.multi_m5.schedule import (  # noqa: E402
    base_slots,
    conditional_slots,
    degradation_on_task,
)


FINDING = "M5-COLLAB-FINDING: orders.legacy_total is dropped by migration 0042"
# The first Multi source that carries the code-mode plaintext fix. Runs frozen
# against the earlier bundle are v2 evidence and stay that way.
MULTI_SOURCE_COMMIT = "6fe1379e4a77a604407b335fd94b3cc81d53501a"


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
        # Unpinned, a Multi run inherits the machine-wide member default. That
        # default stays on the host's model so campaigns frozen before pinning
        # existed keep their identity; M-5 passes its own from the lock.
        self.assertEqual(
            team_capability_override_items(Product.RONDO_MULTI),
            (
                f"features.multi_agent_v2={TEAM_CAPABILITY_MULTI_TOML}",
                'agents.default_subagent_model="gpt-5.6-sol"',
                'agents.default_subagent_reasoning_effort="medium"',
            ),
        )
        self.assertEqual(
            team_capability_override_items(
                Product.RONDO_MULTI,
                subagent_model=contract.member_model,
                subagent_effort=contract.raw["member_effort"],
            ),
            (
                f"features.multi_agent_v2={TEAM_CAPABILITY_MULTI_TOML}",
                'agents.default_subagent_model="gpt-5.6-terra"',
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
        self.assertEqual(identity.source_commit, MULTI_SOURCE_COMMIT)
        self.assertTrue(
            identity.bundle_relpath.endswith(
                f"{MULTI_SOURCE_COMMIT}-x86_64-unknown-linux-musl-runtime-bundle"
            )
        )
        if identity.status == "pending_freeze":
            self.assertFalse(identity.frozen)
            with self.assertRaises(M5ContractError):
                load_runtime_identity(require_frozen=True, common_root=Path("/tmp"))
        else:
            self.assertTrue(identity.frozen)
            self.assertRegex(identity.codex_sha256 or "", r"^[0-9a-f]{64}$")


class MultiM5V4ContractTests(unittest.TestCase):
    """What v4 froze after the real code-mode evidence gap was observed."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def _mutated(self, name: str, **changes: object) -> Path:
        """Write a copy of a frozen lock with one field changed or removed."""

        document = json.loads((EVAL_ROOT / "locks" / f"{name}.json").read_text("utf-8"))
        for key, value in changes.items():
            if value is None:
                document.pop(key, None)
            else:
                document[key] = value
        target = Path(self.directory.name) / f"{name}.json"
        target.write_text(json.dumps(document), "utf-8")
        return target

    def test_both_gate_locks_name_the_new_runtime_bundle(self) -> None:
        self.assertEqual(load_workflow_contract().raw["runtime_lock_id"], RUNTIME_LOCK_ID)
        self.assertEqual(
            load_nondegradation_contract().raw["runtime_lock_id"], RUNTIME_LOCK_ID
        )

    def test_a_gate_lock_pointing_at_the_old_bundle_is_refused(self) -> None:
        # runtime-v2 delivers plaintext messages but cannot anchor a normal
        # completed code-mode cell. Accepting it here would make the member
        # evidence predicate structurally unreachable again.
        for name, loader in (
            ("multi-m5-workflow-v4", load_workflow_contract),
            ("multi-m5-nondegradation-v4", load_nondegradation_contract),
        ):
            with self.subTest(lock=name):
                path = self._mutated(name, runtime_lock_id="multi-m5-runtime-v2")
                with self.assertRaises(M5ContractError):
                    loader(path)
                path = self._mutated(name, runtime_lock_id=None)
                with self.assertRaises(M5ContractError):
                    loader(path)

    def test_gate1_taint_effect_is_frozen(self) -> None:
        self.assertEqual(load_workflow_contract().raw["infra_taint_effect"], "infra_failed")
        for value in ("ignored", "counts_as_pass", None):
            with self.subTest(value=value):
                path = self._mutated("multi-m5-workflow-v4", infra_taint_effect=value)
                with self.assertRaises(M5ContractError):
                    load_workflow_contract(path)

    def test_retry_backoff_comes_from_the_lock(self) -> None:
        contract = load_nondegradation_contract()
        self.assertEqual(contract.retry_backoff_seconds, 2.0)
        path = self._mutated("multi-m5-nondegradation-v4", provider_retry_backoff_seconds="5")
        self.assertEqual(load_nondegradation_contract(path).retry_backoff_seconds, 5.0)
        for value in ("0", "31", "", None):
            with self.subTest(value=value):
                path = self._mutated(
                    "multi-m5-nondegradation-v4", provider_retry_backoff_seconds=value
                )
                with self.assertRaises(M5ContractError):
                    load_nondegradation_contract(path)

    def test_unpriced_settlement_separates_stopping_from_counting(self) -> None:
        contract = load_nondegradation_contract()
        self.assertEqual(contract.unpriced_stop_threshold, 1)
        self.assertIs(
            contract.raw["unpriced_settlement"]["any_unpriced_invalidates_observation"],
            True,
        )
        block = dict(contract.raw["unpriced_settlement"])
        for change in (
            {"unpriced_stop_threshold": 2},
            {"any_unpriced_invalidates_observation": False},
            {"basis": "  "},
            {"note": "extra"},
        ):
            with self.subTest(change=change):
                path = self._mutated(
                    "multi-m5-nondegradation-v4", unpriced_settlement={**block, **change}
                )
                with self.assertRaises(M5ContractError):
                    load_nondegradation_contract(path)
        path = self._mutated("multi-m5-nondegradation-v4", unpriced_settlement=None)
        with self.assertRaises(M5ContractError):
            load_nondegradation_contract(path)


class MultiM5MemberDeliveryTests(unittest.TestCase):
    """Tell "the member never got a readable task" apart from "it ignored it".

    Both shapes below are the ones the frozen binaries actually emit: the
    encrypted one was taken from the cm4 capture on the pre-fix bundle, where
    the plaintext task text was labelled `encrypted_content` and the provider
    rejected all eight member requests.
    """

    @staticmethod
    def _capture(
        *parts: dict[str, object], author: str = "/root"
    ) -> str:
        body = {
            "input": [
                {"type": "message", "role": "user", "content": [{"text": "task"}]},
                {"type": "agent_message", "author": author, "content": list(parts)},
            ]
        }
        return json.dumps(body) + "\n"

    def test_plaintext_parts_are_reported_as_delivered(self) -> None:
        capture = self._capture(
            {"type": "input_text", "text": "Message Type: NEW_TASK"},
            {"type": "input_text", "text": "Read NOTES.md and publish the finding."},
        )
        self.assertEqual(
            member_message_delivery(capture),
            {
                "status": "plaintext",
                "plaintext_parts": 2,
                "encrypted_parts": 0,
                "unknown_parts": 0,
            },
        )

    def test_a_plaintext_task_labelled_encrypted_is_reported(self) -> None:
        capture = self._capture(
            {"type": "input_text", "text": "Message Type: NEW_TASK"},
            {
                "type": "encrypted_content",
                "encrypted_content": "Read NOTES.md and publish the finding.",
            },
        )
        self.assertEqual(
            member_message_delivery(capture),
            {
                "status": "encrypted",
                "plaintext_parts": 1,
                "encrypted_parts": 1,
                "unknown_parts": 0,
            },
        )

    def test_no_member_request_is_not_a_delivery_success(self) -> None:
        body = json.dumps({"input": [{"type": "message", "role": "user"}]}) + "\n"
        self.assertEqual(member_message_delivery(body)["status"], "absent")
        self.assertEqual(member_message_delivery("")["status"], "absent")
        # `include: ["reasoning.encrypted_content"]` is a request parameter, not
        # a message part; matching on the bare word would flag every request.
        parameterised = json.dumps(
            {"include": ["reasoning.encrypted_content"], "input": []}
        )
        self.assertEqual(member_message_delivery(parameterised)["status"], "absent")

    def test_unparsable_lines_do_not_mask_an_encrypted_part(self) -> None:
        capture = "not json\n" + self._capture(
            {"type": "encrypted_content", "encrypted_content": "plain text"}
        )
        self.assertEqual(member_message_delivery(capture)["status"], "encrypted")

    def test_a_member_reply_does_not_count_as_delivery_to_the_member(self) -> None:
        capture = self._capture(
            {"type": "input_text", "text": "I finished the task."},
            author="/root/worker",
        )
        self.assertEqual(
            member_message_delivery(capture),
            {
                "status": "absent",
                "plaintext_parts": 0,
                "encrypted_parts": 0,
                "unknown_parts": 0,
            },
        )

    def test_an_unknown_root_part_fails_closed_instead_of_counting_as_plaintext(self) -> None:
        capture = self._capture({"type": "image", "url": "https://invalid.example"})
        self.assertEqual(
            member_message_delivery(capture),
            {
                "status": "unknown",
                "plaintext_parts": 0,
                "encrypted_parts": 0,
                "unknown_parts": 1,
            },
        )

    def test_opposite_directions_do_not_pollute_root_to_member_delivery(self) -> None:
        capture = self._capture(
            {"type": "input_text", "text": "Read NOTES.md."}
        ) + self._capture(
            {
                "type": "encrypted_content",
                "encrypted_content": "member reply",
            },
            author="/root/worker",
        )
        self.assertEqual(
            member_message_delivery(capture),
            {
                "status": "plaintext",
                "plaintext_parts": 1,
                "encrypted_parts": 0,
                "unknown_parts": 0,
            },
        )


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

    # The Responses-wire evidence tests that lived here judged
    # `function_call_output` items. Under `tool_mode = code_mode_only` the frozen
    # binary never emits those for a team tool, so they exercised a shape the
    # product cannot produce. Their properties -- attribution, cursor paging,
    # wake signals only from a dispatched wait, and a caller dump never counting
    # -- are now asserted against the real code-mode path and the rollout-trace
    # evidence source in `test_multi_m5_trace_evidence.py`.



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
            subagent_model="gpt-5.6-terra",
            subagent_effort="medium",
        )
        for name in required_archive_fields():
            self.assertIn(name, record)
        self.assertEqual(record["evidence_kind"], "loopback")
        self.assertFalse(record["counts_as_effective"])
        self.assertEqual(record["team_capability_config"]["team_state_enabled"], True)
        # The row states the member the run configured, not the host default.
        self.assertEqual(
            record["team_capability_config"]["default_subagent_model"], "gpt-5.6-terra"
        )
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
                subagent_model="gpt-5.6-terra",
                subagent_effort="medium",
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
        self.assertIn('agents.default_subagent_model="gpt-5.6-terra"', joined)
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
