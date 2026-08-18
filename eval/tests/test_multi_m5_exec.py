from __future__ import annotations

import json
import sys
import unittest
from decimal import Decimal
from http.client import HTTPConnection
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.api_budget_proxy import BudgetCapacityExhausted, Usage  # noqa: E402
from rondo_eval.config import RepoPaths  # noqa: E402
from rondo_eval.contracts import Product, Side  # noqa: E402
from rondo_eval.multi_m5.archive import archive_record  # noqa: E402
from rondo_eval.multi_m5.budget import HARD_CAP_USD, open_phase_b_ledger, phase_b_pricing  # noqa: E402
from rondo_eval.multi_m5.capture import CaptureProxy  # noqa: E402
from rondo_eval.multi_m5.command import build_multi_exec_command, team_capability_overrides  # noqa: E402
from rondo_eval.multi_m5.gate1 import run_gate1_rehearsal  # noqa: E402
from rondo_eval.multi_m5.gate2 import (  # noqa: E402
    DockerNotAuthorizedExecutor,
    Gate2Error,
    ScriptedSlotExecutor,
    run_light_interleaved,
)
from rondo_eval.multi_m5.load import (  # noqa: E402
    M5ContractError,
    load_nondegradation_contract,
    load_runtime_identity,
    load_workflow_contract,
)
from rondo_eval.multi_m5.loopback import (  # noqa: E402
    LOOPBACK_BEARER,
    LOOPBACK_MODEL,
    REQUIRED_TOOL_NAMES,
    TeamPublishFakeServer,
)
from rondo_eval.multi_m5.ready import readiness_report  # noqa: E402
from rondo_eval.multi_m5.rehearsal import MEMBER_TASK, CollaborationStub  # noqa: E402
from rondo_eval.multi_m5.store import (  # noqa: E402
    StoreError,
    load_archive_records,
    persist_archive_record,
    scratch_root,
)

FINDING = "M5-COLLAB-FINDING: orders.legacy_total is dropped by migration 0042"


def _common_root() -> Path:
    return RepoPaths.discover(Path.cwd()).common_root


class MultiM5CaptureTests(unittest.TestCase):
    def test_stub_and_forward_keep_the_full_request_body(self) -> None:
        bulky = {"model": LOOPBACK_MODEL, "stream": True, "prompt": "x" * 20_000}

        def handler(request: dict) -> bytes:
            self.assertEqual(request["prompt"], bulky["prompt"])
            return b"event: response.completed\ndata: {}\n\n"

        with CaptureProxy(mode="stub", handler=handler) as proxy:
            status, _payload = _post(int(proxy.base_url.rsplit(":", 1)[1].split("/")[0]), bulky)
            self.assertEqual(status, 200)
            self.assertEqual(len(proxy.bodies), 1)
            self.assertEqual(proxy.bodies[0]["prompt"], bulky["prompt"])
            self.assertIn(bulky["prompt"], proxy.jsonl())

        tools = [
            {
                "type": "namespace",
                "name": "collaboration",
                "tools": [{"type": "function", "name": name} for name in REQUIRED_TOOL_NAMES[:4]],
            },
            {"type": "function", "name": "spawn_agent"},
        ]
        first = {"model": LOOPBACK_MODEL, "stream": True, "tools": tools}
        with TeamPublishFakeServer() as upstream, CaptureProxy(
            mode="forward",
            upstream_base_url=upstream.base_url,
        ) as proxy:
            port = int(proxy.base_url.rsplit(":", 1)[1].split("/")[0])
            status, payload = _post(port, first)
            self.assertEqual(status, 200)
            self.assertIn(b"team_publish", payload)
            self.assertEqual(len(proxy.bodies), 1)
            self.assertEqual(len(upstream.bodies), 1)
            self.assertEqual(proxy.bodies[0]["tools"], first["tools"])

    def test_forward_rejects_a_non_loopback_upstream(self) -> None:
        with self.assertRaisesRegex(Exception, r"127\.0\.0\.1"):
            CaptureProxy(mode="forward", upstream_base_url="https://example.com/v1")


class MultiM5StubSequenceTests(unittest.TestCase):
    def test_root_starts_with_spawn_and_member_is_not_confused_for_root(self) -> None:
        stub = CollaborationStub(finding_line=FINDING)
        root_first = {
            "model": LOOPBACK_MODEL,
            "input": "You are Root of a two-agent team.",
            "tools": _team_tools(),
        }
        payload = stub(root_first).decode("utf-8")
        self.assertIn("spawn_agent", payload)
        self.assertIn(MEMBER_TASK, payload)
        self.assertNotIn("team_publish", payload.split("spawn_agent")[0])

        after_spawn = {
            "model": LOOPBACK_MODEL,
            "input": [
                {
                    "type": "function_call",
                    "call_id": "spawn-1",
                    "name": "spawn_agent",
                    "arguments": json.dumps({"message": MEMBER_TASK, "task_name": "worker"}),
                },
                {
                    "type": "function_call_output",
                    "call_id": "spawn-1",
                    "output": "{\"thread_id\":\"t1\"}",
                },
            ],
            "tools": _team_tools(),
        }
        payload = stub(after_spawn).decode("utf-8")
        self.assertIn("wait_agent", payload)

        member_first = {
            "model": LOOPBACK_MODEL,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": MEMBER_TASK}],
                }
            ],
            "tools": _team_tools() + [{"name": "exec_command"}],
        }
        payload = stub(member_first).decode("utf-8")
        self.assertIn("exec_command", payload)
        self.assertIn("NOTES.md", payload)

        after_notes = {
            "model": LOOPBACK_MODEL,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": MEMBER_TASK}],
                },
                {
                    "type": "function_call",
                    "call_id": "member-sh-1",
                    "name": "exec_command",
                    "arguments": '{"cmd":"cat NOTES.md"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "member-sh-1",
                    "output": FINDING,
                },
            ],
            "tools": _team_tools() + [{"name": "exec_command"}],
        }
        payload = stub(after_notes).decode("utf-8")
        self.assertIn("team_publish", payload)
        self.assertNotIn("wait_agent", payload)


class MultiM5ArchiveBudgetTests(unittest.TestCase):
    def test_gate1_archive_requires_ignored_evidence_and_gate2_needs_slot_fields(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        path = scratch / "multi-m5-test-archive.jsonl"
        if path.exists():
            path.unlink()
        record = archive_record(
            evidence_kind="fake",
            gate=1,
            lock_id="multi-m5-workflow-v1",
            side=Side.RONDO,
            product=Product.RONDO_MULTI,
            source_commit="7" * 40,
            binary_sha256="a" * 64,
            outcome="completed",
            counts_as_effective=False,
        )
        with self.assertRaises(StoreError):
            persist_archive_record(record, common_root=root, path=path)
        record["ignored_evidence"] = []
        persist_archive_record(record, common_root=root, path=path)
        loaded = load_archive_records(path)
        self.assertEqual(loaded[0]["ignored_evidence"], [])
        path.unlink()

    def test_hard_cap_accumulates_approaches_and_rejects(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-ledger.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        pricing = phase_b_pricing()
        with open_phase_b_ledger(ledger_path) as ledger:
            self.assertEqual(Decimal(ledger.snapshot()["total_cap_usd"]), HARD_CAP_USD)
            ledger.ensure_run("m5-cap-normal")
            ledger.reserve("m5-cap-normal", "req-1", Decimal("1.00"))
            ledger.begin_attempt("m5-cap-normal", "req-1", max_attempts=5)
            ledger.settle("m5-cap-normal", "req-1", Usage(1000, 0, 0, 0), pricing=pricing)
            spent = Decimal(ledger.snapshot()["spent_usd"])
            self.assertGreater(spent, 0)
            self.assertLess(spent, Decimal("1.00"))

            ledger.ensure_run("m5-cap-a")
            ledger.reserve("m5-cap-a", "req-a", Decimal("40.00"))
            ledger.begin_attempt("m5-cap-a", "req-a", max_attempts=5)
            ledger.settle("m5-cap-a", "req-a", None, pricing=pricing)
            ledger.ensure_run("m5-cap-b")
            ledger.reserve("m5-cap-b", "req-b", Decimal("40.00"))
            ledger.begin_attempt("m5-cap-b", "req-b", max_attempts=5)
            ledger.settle("m5-cap-b", "req-b", None, pricing=pricing)
            ledger.ensure_run("m5-cap-c")
            ledger.reserve("m5-cap-c", "req-c", Decimal("39.00"))
            ledger.begin_attempt("m5-cap-c", "req-c", max_attempts=5)
            ledger.settle("m5-cap-c", "req-c", None, pricing=pricing)
            remaining = Decimal(ledger.snapshot()["remaining_uncommitted_usd"])
            self.assertLess(remaining, Decimal("2.00"))
            self.assertGreater(remaining, 0)
            ledger.ensure_run("m5-cap-over")
            with self.assertRaises(BudgetCapacityExhausted):
                ledger.reserve("m5-cap-over", "req-over", Decimal("40.00"))


class MultiM5Gate2FakeTests(unittest.TestCase):
    def test_scripted_interleave_archives_effective_slots_and_conditional_reruns(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        archive = scratch / "multi-m5-test-gate2.jsonl"
        if archive.exists():
            archive.unlink()
        contract = load_nondegradation_contract()
        first = contract.tasks[0]
        script = {
            (first, "rondo", 1): ("agent_failed",),
            (first, "rondo", 2): ("agent_failed",),
            (first, "rondo", 3): ("agent_failed",),
        }
        result = run_light_interleaved(
            executor=ScriptedSlotExecutor(script),
            common_root=root,
            persist=True,
            archive_file=archive,
        )
        self.assertEqual(result["effective_runs"], 24)
        self.assertEqual(result["conditional_slots"], 4)
        self.assertEqual(result["verdicts"][first], "stable_one_way_degradation")
        records = load_archive_records(archive)
        self.assertEqual(len(records), 24)
        self.assertTrue(all(row["evidence_kind"] == "fake" for row in records))
        self.assertTrue(all("task_id" in row and "round_index" in row for row in records))
        archive.unlink()

    def test_infra_then_success_is_not_effective_on_the_failed_attempt(self) -> None:
        root = _common_root()
        contract = load_nondegradation_contract()
        first = contract.tasks[0]
        script = {(first, "codex", 1): ("infra_failed", "completed")}
        result = run_light_interleaved(
            executor=ScriptedSlotExecutor(script),
            common_root=root,
            persist=False,
        )
        first_records = [row for row in result["records"] if row["task_id"] == first]
        self.assertEqual(first_records[0]["outcome"], "infra_failed")
        self.assertFalse(first_records[0]["counts_as_effective"])
        self.assertEqual(first_records[1]["outcome"], "completed")
        self.assertTrue(first_records[1]["counts_as_effective"])
        self.assertEqual(result["infra_used"], 1)

    def test_a_scripted_executor_cannot_claim_real_api_evidence(self) -> None:
        with self.assertRaises(Gate2Error):
            run_light_interleaved(
                executor=ScriptedSlotExecutor(),
                common_root=_common_root(),
                persist=False,
                evidence_kind="real_api",
            )

    def test_docker_executor_is_unauthorized(self) -> None:
        root = _common_root()
        result = run_light_interleaved(
            executor=DockerNotAuthorizedExecutor(),
            common_root=root,
            persist=False,
        )
        self.assertEqual(result["records"][0]["outcome"], "infra_failed")
        self.assertFalse(result["records"][0]["counts_as_effective"])


class MultiM5ReadyAndCommandTests(unittest.TestCase):
    def test_ready_report_does_not_embed_secret_values(self) -> None:
        report = readiness_report(common_root=_common_root())
        blob = json.dumps(report)
        self.assertNotIn("sk-", blob)
        self.assertIn("env_local", report["checks"])
        self.assertIn("required_names_present", report["checks"]["env_local"])
        self.assertEqual(report["checks"].get("docker_images_present"), "not_checked")

    def test_gate1_command_reuses_the_team_capability_items(self) -> None:
        workflow = load_workflow_contract()
        command = build_multi_exec_command(
            Path("/tmp/codex"),
            base_url="http://127.0.0.1:9/v1",
            instruction="hello",
            model=workflow.root_model,
            effort=workflow.root_effort,
        )
        joined = " ".join(command)
        self.assertEqual(joined.count("features.multi_agent_v2="), 1)
        for item in team_capability_overrides():
            self.assertIn(item, command)
        self.assertIn("--strict-config", command)


class MultiM5TemplateProtocolTests(unittest.TestCase):
    """The frozen template must be sufficient on its own.

    The rehearsal stub proves the product chain works, but it only proves it for
    the sequence the stub happens to issue. If the template omits a step the
    predicates need, a compliant paid run fails for a reason that is not a
    product defect -- and burns the frozen attempts finding out. This binds the
    two together: every team tool the stub's Root branch issues must appear in a
    numbered step, and `team_publish` must be demanded of Root specifically,
    because `team_update` never creates a Version and `two_authors` is otherwise
    unsatisfiable with one member.
    """

    def _steps(self) -> list[str]:
        text = load_workflow_contract().instruction_path.read_text("utf-8")
        protocol = text.split("## Required protocol", 1)[1].split("##", 1)[0]
        steps: list[str] = []
        for line in protocol.splitlines():
            if line[:1].isdigit() and "." in line[:3]:
                steps.append(line)
            elif steps and line.startswith("   "):
                steps[-1] += " " + line.strip()
        return steps

    def test_template_demands_every_tool_the_stub_issues(self) -> None:
        steps = self._steps()
        self.assertGreaterEqual(len(steps), 8)
        joined = " ".join(steps)
        for tool in (
            "spawn_agent",
            "wait_agent",
            "team_publish",
            "team_route",
            "team_update",
            "team_inspect",
        ):
            self.assertIn(tool, joined, f"frozen template never asks for {tool}")

    def test_template_requires_a_root_authored_version(self) -> None:
        root_publishes = [
            step
            for step in self._steps()
            if "team_publish" in step and "You, as Root" in step
        ]
        self.assertTrue(
            root_publishes,
            "no step tells Root to publish its own Version; two_authors would be "
            "unsatisfiable and every compliant run would fail",
        )


class MultiM5RehearsalTests(unittest.TestCase):
    def test_frozen_binary_dress_rehearsal_passes(self) -> None:
        root = _common_root()
        try:
            load_runtime_identity(require_frozen=True, common_root=root)
        except M5ContractError as exc:
            self.skipTest(f"frozen Multi bundle is unavailable: {exc}")
        result = run_gate1_rehearsal(common_root=root, persist=False)
        verdict = result["verdict"]
        if not verdict.passed:
            self.fail(
                "gate 1 rehearsal did not pass: "
                f"predicates={verdict.predicates} reasons={verdict.reasons} "
                f"ignored={verdict.ignored_evidence} event={verdict.event_id} "
                f"requests={result['request_count']} rc={result['returncode']} "
                f"stub_errors={result['stub_errors']} "
                f"stderr={result['stderr_tail'][-1500:]}"
            )
        self.assertTrue(all(verdict.predicates.values()))
        self.assertTrue(result["record"]["rehearsal"])
        self.assertEqual(result["record"]["evidence_kind"], "loopback")
        self.assertFalse(result["record"]["counts_as_effective"])
        self.assertIn("ignored_evidence", result["record"])
        self.assertEqual(result["record"]["tool_surface"], "non_code_mode_only=false")
        self.assertTrue(result["report_text"] and FINDING in result["report_text"])


def _team_tools() -> list[dict[str, str]]:
    names = (
        "spawn_agent",
        "wait_agent",
        "team_publish",
        "team_route",
        "team_update",
        "team_inspect",
        "team_evidence",
    )
    return [{"name": name} for name in names]


def _post(port: int, payload: dict[str, object]) -> tuple[int, bytes]:
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
