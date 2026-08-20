from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import dataclass, replace
from decimal import Decimal
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

import rondo_eval.multi_m5.gate1  # noqa: E402
import rondo_eval.multi_m5.gate2  # noqa: E402

from rondo_eval.api_budget_proxy import (  # noqa: E402
    ApiBudgetProxyError,
    BudgetCapacityExhausted,
    BudgetStopped,
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    Usage,
    _UrllibTransport,
    exposure_summary,
    maximum_usage_cost,
    price_usage,
    stop_reason_class,
)
from rondo_eval.config import ConfigError, RepoPaths, load_runtime_config  # noqa: E402
from rondo_eval.docker_supervisor import (  # noqa: E402
    DATA_ROOT_FREE_STOP_BYTES,
    DOCKER_GROWTH_STOP_BYTES,
    DockerImageIdentity,
    DockerResourceStop,
)
from rondo_eval.contracts import BinaryManifest, Product, RunOutcome, Side  # noqa: E402
from rondo_eval.multi_m5.archive import archive_record  # noqa: E402
from rondo_eval.multi_m5.budget import (  # noqa: E402
    BATCH_ID,
    SMOKE_BATCH_ID,
    SMOKE_CAP_USD,
    SMOKE_LOCK_ID,
    SMOKE_MAX_RUNS,
    open_smoke_ledger,
    HARD_CAP_USD,
    REQUEST_LIMIT_STOP_REASON,
    SMOKE_UNPRICED_STOP_THRESHOLD,
    UNPRICED_STOP_THRESHOLD,
    default_run_cap_usd,
    gate1_run_cap_usd,
    gate2_run_cap_usd,
    max_concurrent_main,
    peak_reservation_usd,
    request_reservation_usd,
    retry_backoff_seconds,
    smoke_run_cap_usd,
    usage_envelope,
    RequestCappedLedger,
    open_phase_b_ledger,
    phase_b_pricing,
    require_frozen_provider,
    run_infra_taint,
    run_request_count,
    run_stop_reason,
)
from rondo_eval.multi_m5.capture import FORWARD_TIMEOUT_SECONDS, CaptureProxy  # noqa: E402
from rondo_eval.multi_m5.command import build_multi_exec_command, team_capability_overrides  # noqa: E402
from rondo_eval.multi_m5.gate1 import Gate1Error, run_gate1_paid, run_gate1_rehearsal  # noqa: E402
from rondo_eval.multi_m5.gate2 import (  # noqa: E402
    DockerNotAuthorizedExecutor,
    Gate2Error,
    ScriptedSlotExecutor,
    SlotResult,
    TerminalBenchSlotExecutor,
    docker_summary,
    gate2_passed,
    require_pinned_model,
    run_gate2_real,
    run_light_interleaved,
)
from rondo_eval.multi_m5.load import (  # noqa: E402
    NONDEGRADATION_LOCK_ID,
    WORKFLOW_LOCK_ID,
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
from rondo_eval.multi_m5.paid import (  # noqa: E402
    PAID_API_PHRASE,
    PAID_DOCKER_PHRASE,
    PaidAuthError,
    PaidAuthorization,
    authorization_from_phrases,
)
from rondo_eval.multi_m5.predicates import CollaborationVerdict  # noqa: E402
from rondo_eval.multi_m5.ready import readiness_report  # noqa: E402
from rondo_eval.multi_m5.rehearsal import (  # noqa: E402
    INSPECT_PAGE_LIMIT,
    MEMBER_TASK,
    CollaborationStub,
)
from rondo_eval.multi_m5.resume import (  # noqa: E402
    ResumeError,
    ensure_formal_receipt,
    formal_identity,
    require_formal_receipt,
    validate_gate1_resume_prefix,
)
from rondo_eval.multi_m5.gate2 import _record_for, _run_id  # noqa: E402
from rondo_eval.terminal_bench.runner import prepare_terminal_bench_run  # noqa: E402
from rondo_eval.multi_m5.schedule import (  # noqa: E402
    DIAGNOSTIC_ROUND_INDEX,
    DIAGNOSTIC_SLOT_KIND,
    base_slots,
    diagnostic_slots,
)
from rondo_eval.multi_m5.store import (  # noqa: E402
    archive_path,
    budget_ledger_path,
    smoke_archive_path,
    smoke_ledger_path,
    StoreError,
    load_archive_records,
    persist_archive_record,
    scratch_root,
)
from rondo_eval.terminal_bench.tasksets import FrozenCanaryCatalog, FrozenTask  # noqa: E402

FINDING = "M5-COLLAB-FINDING: orders.legacy_total is dropped by migration 0042"


def _common_root() -> Path:
    return RepoPaths.discover(Path.cwd()).common_root


def _isolated_capture_base(test: unittest.TestCase) -> Path:
    temporary = tempfile.TemporaryDirectory(
        prefix="m5-test-captures-",
        dir=scratch_root(_common_root()),
    )
    test.addCleanup(temporary.cleanup)
    return Path(temporary.name)


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
    def test_inspect_requests_keep_a_small_limit_until_each_chain_reaches_null(
        self,
    ) -> None:
        stub = CollaborationStub(finding_line=FINDING)

        def script(response: bytes) -> str:
            events = [
                json.loads(line.removeprefix("data: "))
                for line in response.decode("utf-8").splitlines()
                if line.startswith("data: ")
            ]
            output = next(
                event["item"]
                for event in events
                if event.get("type") == "response.output_item.done"
            )
            return output["input"]

        dump_first = stub._continue_inspect({}, "dump")
        self.assertIsNotNone(dump_first)
        self.assertIn(f'"limit":{INSPECT_PAGE_LIMIT}', script(dump_first))
        dump_request = {
            "input": [
                {
                    "type": "custom_tool_call_output",
                    "call_id": "inspect-dump",
                    "output": json.dumps({"next_cursor": "dump-cursor-1"}),
                }
            ]
        }
        dump_next = stub._continue_inspect(dump_request, "dump")
        self.assertIsNotNone(dump_next)
        dump_script = script(dump_next)
        self.assertIn('"cursor":"dump-cursor-1"', dump_script)
        self.assertIn(f'"limit":{INSPECT_PAGE_LIMIT}', dump_script)
        dump_request["input"].append(
            {
                "type": "custom_tool_call_output",
                "call_id": "inspect-dump-1",
                "output": json.dumps({"next_cursor": None}),
            }
        )
        self.assertIsNone(stub._continue_inspect(dump_request, "dump"))
        self.assertEqual(stub.dump_pages, 2)

        log_first = stub._continue_inspect({}, "log")
        self.assertIsNotNone(log_first)
        self.assertIn(f'"limit":{INSPECT_PAGE_LIMIT}', script(log_first))
        log_request = {
            "input": [
                {
                    "type": "custom_tool_call_output",
                    "call_id": "inspect-log",
                    "output": json.dumps({"next_offset": 3}),
                }
            ]
        }
        log_next = stub._continue_inspect(log_request, "log")
        self.assertIsNotNone(log_next)
        log_script = script(log_next)
        self.assertIn('"offset":3', log_script)
        self.assertIn(f'"limit":{INSPECT_PAGE_LIMIT}', log_script)
        log_request["input"].append(
            {
                "type": "custom_tool_call_output",
                "call_id": "inspect-log-1",
                "output": json.dumps({"next_offset": None}),
            }
        )
        self.assertIsNone(stub._continue_inspect(log_request, "log"))
        self.assertEqual(stub.log_pages, 2)

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
        self.assertIn('"type":"custom_tool_call"', payload)
        self.assertIn('"name":"exec"', payload)
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
                    "type": "custom_tool_call",
                    "call_id": "member-sh-1",
                    "name": "exec",
                    "input": "const r = await tools.exec_command({cmd:'cat NOTES.md'}); text(r.output);",
                },
                {
                    "type": "custom_tool_call_output",
                    "call_id": "member-sh-1",
                    "output": [
                        {"type": "input_text", "text": "Script completed"},
                        {"type": "input_text", "text": FINDING},
                    ],
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
            lock_id=WORKFLOW_LOCK_ID,
            side=Side.RONDO,
            product=Product.RONDO_MULTI,
            source_commit="7" * 40,
            binary_sha256="a" * 64,
            outcome="completed",
            counts_as_effective=False,
            subagent_model="gpt-5.6-terra",
            subagent_effort="medium",
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

            run_cap = default_run_cap_usd()
            self.assertEqual(Decimal(ledger.snapshot()["default_run_cap_usd"]), run_cap)
            # Derived from the lock: peak in-flight reservations plus the larger
            # gate's spend allowance. Asserted against the same program the
            # runners use, so a price change cannot silently loosen it.
            self.assertEqual(run_cap, Decimal("23.10"))
            ledger.ensure_run("m5-cap-a")
            with self.assertRaises(BudgetCapacityExhausted):
                ledger.reserve("m5-cap-a", "req-too-big", Decimal("40.00"))
            # Walk the batch toward $120 one full-cap run at a time. The point is
            # that the batch total accumulates across runs, so the exact per-run
            # figure is read from the lock rather than written in by hand.
            spent = Decimal("0")
            index = 0
            while spent + run_cap <= HARD_CAP_USD - Decimal("1.00"):
                run_id = f"m5-cap-{index}"
                ledger.ensure_run(run_id)
                ledger.reserve(run_id, f"req-{index}", run_cap)
                ledger.begin_attempt(run_id, f"req-{index}", max_attempts=5)
                ledger.settle(run_id, f"req-{index}", None, pricing=pricing)
                spent += run_cap
                index += 1
            remaining = Decimal(ledger.snapshot()["remaining_uncommitted_usd"])
            self.assertLessEqual(remaining, run_cap)
            self.assertGreater(remaining, 0)
            ledger.ensure_run("m5-cap-over")
            with self.assertRaises(BudgetCapacityExhausted):
                ledger.reserve("m5-cap-over", "req-over", run_cap)


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
        # The degraded task also drew its attribution diagnostic, which is an
        # extra archived row that is deliberately not an effective observation.
        self.assertEqual(result["diagnostic_slots"], 1)
        records = load_archive_records(archive)
        self.assertEqual(len(records), 25)
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

    def test_ready_fails_when_the_frozen_provider_projection_drifts(self) -> None:
        with patch(
            "rondo_eval.multi_m5.budget.require_frozen_provider",
            side_effect=M5ContractError("provider drift"),
        ):
            report = readiness_report(common_root=_common_root())
        self.assertFalse(report["checks"]["provider_frozen_projection"]["ok"])
        self.assertIn("provider_frozen_projection", report["missing"])

    def test_gate1_command_reuses_the_team_capability_items(self) -> None:
        workflow = load_workflow_contract()
        command = build_multi_exec_command(
            Path("/tmp/codex"),
            base_url="http://127.0.0.1:9/v1",
            instruction="hello",
            model=workflow.root_model,
            effort=workflow.root_effort,
            member_model=workflow.member_model,
            member_effort=workflow.raw["member_effort"],
        )
        joined = " ".join(command)
        self.assertEqual(joined.count("features.multi_agent_v2="), 1)
        for item in team_capability_overrides(
            member_model=workflow.member_model,
            member_effort=workflow.raw["member_effort"],
        ):
            self.assertIn(item, command)
        # The member model comes from the gate 1 lock, not the machine-wide
        # default. A member started on the host default is rejected by the
        # capture proxy before it sends anything and dies silently, which reads
        # as every collaboration predicate being false.
        self.assertIn(
            f'agents.default_subagent_model="{workflow.member_model}"', command
        )
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
    def test_nonpersistent_gate1_requires_an_isolated_capture_root(self) -> None:
        with self.assertRaisesRegex(Gate1Error, "isolated capture root"):
            run_gate1_rehearsal(common_root=_common_root(), persist=False)

    def test_frozen_binary_dress_rehearsal_passes(self) -> None:
        root = _common_root()
        try:
            load_runtime_identity(require_frozen=True, common_root=root)
        except M5ContractError as exc:
            self.skipTest(f"frozen Multi bundle is unavailable: {exc}")
        result = run_gate1_rehearsal(
            common_root=root,
            persist=False,
            capture_base=_isolated_capture_base(self),
        )
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
        self.assertGreaterEqual(result["inspect_pages"]["dump"], 2)
        self.assertGreaterEqual(result["inspect_pages"]["log"], 2)
        self.assertEqual(result["record"]["inspect_pages"], result["inspect_pages"])
        self.assertTrue(result["report_text"] and FINDING in result["report_text"])


class MultiM5PaidAuthAndCaptureTests(unittest.TestCase):
    def test_forward_keeps_user_agent_and_streams(self) -> None:
        self.assertEqual(FORWARD_TIMEOUT_SECONDS, 180.0)
        sink = _HeaderSink()
        sink.start()
        try:
            with CaptureProxy(mode="forward", upstream_base_url=sink.base_url) as proxy:
                port = int(proxy.base_url.rsplit(":", 1)[1].split("/")[0])
                status, payload = _post(
                    port,
                    {"model": LOOPBACK_MODEL, "stream": True, "prompt": "keep-me"},
                    extra_headers={
                        "User-Agent": "codex_cli_rs/0.147.0 (m5-capture)",
                        "originator": "codex_cli_rs",
                    },
                )
            self.assertEqual(status, 200)
            self.assertIn(b"keep-me", payload)
            self.assertEqual(sink.user_agent, "codex_cli_rs/0.147.0 (m5-capture)")
            self.assertEqual(sink.originator, "codex_cli_rs")
            self.assertGreaterEqual(sink.writes, 2)
        finally:
            sink.close()

    def test_capture_forwards_through_the_budget_proxy(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-capture-budget.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        workflow = load_workflow_contract()
        pricing = phase_b_pricing()
        upstream = _UsageUpstream()
        upstream.start()
        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                ledger.ensure_run("m5-g1-chain")
                metadata = scratch / "multi-m5-test-capture-budget-meta.json"
                budget = LoopbackResponsesProxy(
                    upstream_base_url="https://provider.example/v1",
                    api_key="sk-test-never-spend",
                    ledger=ledger,
                    run_id="m5-g1-chain",
                    metadata_path=metadata,
                    main_model=workflow.root_model,
                    main_effort=workflow.root_effort,
                    main_pricing=pricing,
                    guardian_model=workflow.root_model,
                    guardian_pricing=pricing,
                    guardian_effort=workflow.root_effort,
                    max_attempts=5,
                    retry_backoff_seconds=0.0,
                    unbilled_retry_statuses=(429, 500, 502, 503, 504),
                    request_reservation_usd="8.00",
                    timeout_seconds=FORWARD_TIMEOUT_SECONDS,
                    _transport=_UrllibTransport(endpoint_override=upstream.endpoint),
                )
                with budget, CaptureProxy(
                    mode="forward",
                    upstream_base_url=budget.base_url,
                    bearer=budget.downstream_api_key,
                    model=workflow.root_model,
                ) as capture:
                    port = int(capture.base_url.rsplit(":", 1)[1].split("/")[0])
                    status, payload = _post(
                        port,
                        {
                            "model": workflow.root_model,
                            "stream": True,
                            "reasoning": {"effort": workflow.root_effort},
                            "input": "budget-chain",
                        },
                        bearer=budget.downstream_api_key,
                        extra_headers={
                            "User-Agent": "codex_cli_rs/0.147.0 (m5-chain)",
                            "originator": "codex_cli_rs",
                        },
                    )
                    self.assertEqual(status, 200)
                    self.assertIn(b"response.completed", payload)
                    self.assertEqual(len(capture.bodies), 1)
                    self.assertEqual(capture.bodies[0]["input"], "budget-chain")
                    self.assertEqual(
                        upstream.user_agent, "codex_cli_rs/0.147.0 (m5-chain)"
                    )
                    self.assertEqual(upstream.originator, "codex_cli_rs")
                    spent = Decimal(ledger.snapshot()["spent_usd"])
                    self.assertGreater(spent, 0)
        finally:
            upstream.close()
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()

    def test_paid_functions_refuse_without_authorization(self) -> None:
        with self.assertRaises(PaidAuthError):
            authorization_from_phrases(api_phrase=None)
        with self.assertRaises(PaidAuthError):
            authorization_from_phrases(api_phrase="not-the-frozen-phrase")
        with self.assertRaises(PaidAuthError):
            authorization_from_phrases(
                api_phrase=PAID_API_PHRASE,
                docker_phrase="not-the-frozen-docker-phrase",
            )
        unlocked = authorization_from_phrases(api_phrase=PAID_API_PHRASE)
        self.assertTrue(unlocked.real_api)
        self.assertFalse(unlocked.docker)
        with self.assertRaises(PaidAuthError):
            run_gate1_paid(
                authorization=PaidAuthorization(real_api=False, docker=False),
                api_key="sk-test",
                upstream_base_url="https://provider.example/v1",
                ledger=object(),  # type: ignore[arg-type]
            )
        with self.assertRaises(PaidAuthError):
            run_gate2_real(
                authorization=PaidAuthorization(real_api=True, docker=False),
                api_key="sk-test",
                ledger=object(),  # type: ignore[arg-type]
                common_root=_common_root(),
                counter=object(),  # type: ignore[arg-type]
                lock_guard=object(),  # type: ignore[arg-type]
                lease=object(),  # type: ignore[arg-type]
            )

    def test_nonempty_paid_capture_is_refused_before_claim(self) -> None:
        class _Ledger:
            claims = 0

            def claim_run(self, *_args, **_kwargs):
                self.claims += 1

        ledger = _Ledger()
        capture_base = _isolated_capture_base(self)
        target = capture_base / "m5-g1-v6-paid-a1"
        target.mkdir()
        (target / "verdict.json").write_text("old\n", encoding="utf-8")
        with self.assertRaisesRegex(Gate1Error, "already holds artifacts"):
            run_gate1_paid(
                authorization=PaidAuthorization(real_api=True, docker=False),
                api_key="sk-test-never-spend",
                upstream_base_url="https://provider.example/v1",
                ledger=ledger,  # type: ignore[arg-type]
                common_root=_common_root(),
                persist=False,
                capture_base=capture_base,
            )
        self.assertEqual(ledger.claims, 0)

    def test_symlink_paid_capture_is_refused_before_claim(self) -> None:
        class _Ledger:
            claims = 0

            def claim_run(self, *_args, **_kwargs):
                self.claims += 1

        ledger = _Ledger()
        capture_base = _isolated_capture_base(self)
        target = capture_base / "m5-g1-v6-paid-a1"
        target.symlink_to(capture_base / "missing-target", target_is_directory=True)
        with self.assertRaisesRegex(Gate1Error, "capture path is unsafe"):
            run_gate1_paid(
                authorization=PaidAuthorization(real_api=True, docker=False),
                api_key="sk-test-never-spend",
                upstream_base_url="https://provider.example/v1",
                ledger=ledger,  # type: ignore[arg-type]
                common_root=_common_root(),
                persist=False,
                capture_base=capture_base,
            )
        self.assertEqual(ledger.claims, 0)

    def test_cli_paid_commands_exit_before_loading_secrets(self) -> None:
        from rondo_eval.multi_m5 import __main__ as m5_main

        justfile = RepoPaths.discover(Path.cwd()).worktree_root / "justfile"
        text = justfile.read_text("utf-8")
        self.assertNotIn(PAID_API_PHRASE, text)
        self.assertNotIn(PAID_DOCKER_PHRASE, text)
        with patch.object(
            m5_main,
            "load_provider_secret",
            side_effect=AssertionError("must not load secrets"),
        ):
            self.assertEqual(m5_main.main(["gate1-paid"]), 78)
            self.assertEqual(m5_main.main(["gate2-real"]), 78)
            self.assertEqual(
                m5_main.main(["gate1-paid", "--authorize-paid-api", "nope"]),
                78,
            )
        locked = subprocess.run(
            ["just", "eval-multi-m5-gate1-paid"],
            cwd=justfile.parent,
            capture_output=True,
            check=False,
        )
        self.assertEqual(locked.returncode, 78)
        locked = subprocess.run(
            ["just", "eval-multi-m5-gate2-real"],
            cwd=justfile.parent,
            capture_output=True,
            check=False,
        )
        self.assertEqual(locked.returncode, 78)

    def test_gate2_provider_drift_precedes_secret_and_ledger_open(self) -> None:
        from rondo_eval.multi_m5 import __main__ as m5_main

        with patch.object(
            m5_main,
            "require_frozen_provider",
            side_effect=M5ContractError("provider drift"),
        ), patch.object(
            m5_main,
            "load_provider_secret",
            side_effect=AssertionError("secret load must be later"),
        ), patch.object(m5_main, "open_phase_b_ledger") as open_ledger:
            returncode = m5_main.main(
                [
                    "gate2-real",
                    "--authorize-paid-api",
                    PAID_API_PHRASE,
                    "--authorize-docker",
                    PAID_DOCKER_PHRASE,
                ]
            )
        self.assertEqual(returncode, 78)
        open_ledger.assert_not_called()

    def test_gate1_paid_timeout_archives_infra_failure_as_real_api(self) -> None:
        root = _common_root()
        try:
            load_runtime_identity(require_frozen=True, common_root=root)
        except M5ContractError as exc:
            self.skipTest(f"frozen Multi bundle is unavailable: {exc}")
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-gate1-paid-timeout.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        upstream = _UsageUpstream()
        upstream.start()

        def boom(*_args: object, **_kwargs: object) -> object:
            raise subprocess.TimeoutExpired(cmd=["codex"], timeout=1)

        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                result = run_gate1_paid(
                    authorization=PaidAuthorization(real_api=True, docker=False),
                    api_key="sk-test-never-spend",
                    upstream_base_url="https://provider.example/v1",
                    ledger=ledger,
                    common_root=root,
                    persist=False,
                    capture_base=_isolated_capture_base(self),
                    transport=_UrllibTransport(endpoint_override=upstream.endpoint),
                    process_runner=boom,  # type: ignore[arg-type]
                )
            record = result["record"]
            self.assertEqual(record["evidence_kind"], "real_api")
            self.assertEqual(record["outcome"], "infra_failed")
            self.assertTrue(record["timed_out"])
            self.assertFalse(record["counts_as_effective"])
            self.assertFalse(record.get("rehearsal", False))
            self.assertEqual(upstream.hits, 0)
        finally:
            upstream.close()
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()

    def test_gate1_drains_a_trailing_terminal_error_before_building_its_record(self) -> None:
        """A late settlement must invalidate an otherwise passing Gate 1 run."""

        root = _common_root()
        try:
            load_runtime_identity(require_frozen=True, common_root=root)
        except M5ContractError as exc:
            self.skipTest(f"frozen Multi bundle is unavailable: {exc}")
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-gate1-tail-taint.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        workflow = load_workflow_contract()
        one_attempt_workflow = replace(workflow, max_attempts=1)
        upstream = _HeldTerminalErrorUpstream().start()
        client_threads: list[threading.Thread] = []
        real_proxy = rondo_eval.multi_m5.gate1.LoopbackResponsesProxy

        def proxy_factory(**kwargs):
            proxy = real_proxy(**kwargs)
            close = proxy.close

            def release_and_close() -> None:
                upstream.release.set()
                close()

            proxy.close = release_and_close  # type: ignore[method-assign]
            return proxy

        def finish_before_tail_settles(command, **kwargs):
            base_url = ""
            for index, item in enumerate(command[:-1]):
                if item == "-c" and ".base_url=" in command[index + 1]:
                    base_url = json.loads(command[index + 1].split("=", 1)[1])
                    break
            self.assertTrue(base_url)
            port = int(urlsplit(base_url).port or 0)
            bearer = kwargs["env"]["OPENAI_API_KEY"]

            def issue_tail_request() -> None:
                try:
                    _post(
                        port,
                        {
                            "model": workflow.root_model,
                            "stream": True,
                            "reasoning": {"effort": workflow.root_effort},
                            "input": "tail request",
                        },
                        bearer=bearer,
                        extra_headers={
                            "User-Agent": "codex_cli_rs/0.147.0 (m5-tail)",
                            "originator": "codex_cli_rs",
                        },
                    )
                except OSError:
                    # The capture listener is deliberately closing while this
                    # request is in flight. The budget-side settlement, not the
                    # caller's socket outcome, is the invariant under test.
                    pass

            thread = threading.Thread(target=issue_tail_request)
            thread.start()
            client_threads.append(thread)
            self.assertTrue(upstream.wait_for_started(len(client_threads), timeout=5))
            workspace = Path(kwargs["cwd"])
            (workspace / workflow.report_filename).write_text(
                f"finding: {workflow.finding_line}\n", encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, b"", b"")

        passing = CollaborationVerdict(
            passed=True,
            predicates={
                name: True
                for name in (
                    "spawn_member",
                    "event_with_two_versions",
                    "two_authors",
                    "team_route",
                    "team_evidence",
                    "root_resolved",
                    "root_woken",
                )
            },
            reasons=(),
            event_id="event-tail",
            ignored_evidence=(),
        )
        try:
            with open_phase_b_ledger(ledger_path) as ledger, patch.object(
                rondo_eval.multi_m5.gate1,
                "LoopbackResponsesProxy",
                side_effect=proxy_factory,
            ), patch.object(
                rondo_eval.multi_m5.gate1,
                "load_workflow_contract",
                return_value=one_attempt_workflow,
            ), patch.object(
                rondo_eval.multi_m5.gate1,
                "find_trace_bundle",
                return_value=Path("/unused/trace"),
            ), patch.object(
                rondo_eval.multi_m5.gate1,
                "load_rollout_trace",
                return_value=object(),
            ), patch.object(
                rondo_eval.multi_m5.gate1,
                "evaluate_collaboration",
                return_value=passing,
            ):
                result = run_gate1_paid(
                    authorization=PaidAuthorization(real_api=True, docker=False),
                    api_key="sk-test-never-spend",
                    upstream_base_url="https://provider.example/v1",
                    ledger=ledger,
                    common_root=root,
                    persist=False,
                    capture_base=_isolated_capture_base(self),
                    transport=_UrllibTransport(endpoint_override=upstream.endpoint),
                    process_runner=finish_before_tail_settles,  # type: ignore[arg-type]
                )
                final_exposure = exposure_summary(
                    ledger.snapshot(), "m5-g1-v6-paid-a1"
                )
            record = result["record"]
            self.assertEqual(record["outcome"], "infra_failed")
            self.assertFalse(record["passed"])
            self.assertTrue(all(record["predicates"].values()))
            self.assertEqual(
                record["infra_taint"],
                {"count": 1, "first_reason": "upstream_terminal_error"},
            )
            self.assertEqual(record["budget_exposure"], final_exposure)
            self.assertEqual(record["budget_exposure"]["settled_requests"], 1)
        finally:
            upstream.release.set()
            for thread in client_threads:
                thread.join(timeout=5)
            upstream.close()
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()


class MultiM5ConcurrentMainTests(unittest.TestCase):
    """Root and members call the model at the same time; the proxy must allow it.

    The budget proxy refused a second in-flight `main` request, which predates
    Multi. Found by the paid terra smoke run: the spawned member died with
    `request_rejected` before sending anything, so every collaboration predicate
    was false and gate 1 would have burned every attempt on a harness rule
    rather than on the product.
    """

    def _proxy(self, ledger, **kwargs):
        return LoopbackResponsesProxy(
            upstream_base_url="https://upstream.example/v1",
            api_key="sk-test-never-spend",
            ledger=ledger,
            run_id="m5-concurrent",
            metadata_path=scratch_root(_common_root()) / "m5-concurrent-meta.json",
            main_model="gpt-5.6-terra",
            main_effort="medium",
            main_pricing=phase_b_pricing(),
            guardian_model="gpt-5.6-terra",
            guardian_pricing=phase_b_pricing(),
            guardian_effort="medium",
            max_attempts=5,
            retry_backoff_seconds=0.0,
            unbilled_retry_statuses=(429, 500, 502, 503, 504),
            request_reservation_usd=Decimal("1.00"),
            **kwargs,
        )

    def _claim_twice(self, proxy):
        proxy._claim_and_reserve_logical_request("main", "sha-a", "req-a")
        proxy._claim_and_reserve_logical_request("main", "sha-b", "req-b")

    def test_the_single_main_rule_still_holds_by_default(self) -> None:
        scratch = scratch_root(_common_root())
        path = scratch / "m5-concurrent-default.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        try:
            with open_smoke_ledger(path) as ledger:
                ledger.ensure_run("m5-concurrent", cap_usd=gate1_run_cap_usd())
                proxy = self._proxy(ledger)
                with self.assertRaisesRegex(
                    ApiBudgetProxyError, "concurrent main requests exceed"
                ):
                    self._claim_twice(proxy)
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_multi_may_opt_in_and_both_reservations_are_still_metered(self) -> None:
        scratch = scratch_root(_common_root())
        path = scratch / "m5-concurrent-optin.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        try:
            with open_smoke_ledger(path) as ledger:
                ledger.ensure_run("m5-concurrent", cap_usd=gate1_run_cap_usd())
                proxy = self._proxy(ledger, max_concurrent_main=4)
                self._claim_twice(proxy)
                run = ledger.snapshot()["runs"]["m5-concurrent"]
                # Opting in relaxes ordering, never accounting: both concurrent
                # requests hold their own reservation against the same cap.
                self.assertEqual(len(run["requests"]), 2)
                self.assertGreater(Decimal(ledger.snapshot()["reserved_usd"]), 0)
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_the_multi_gates_opt_in(self) -> None:
        source = Path(rondo_eval.multi_m5.gate1.__file__).read_text("utf-8")
        self.assertEqual(source.count("max_concurrent_main=concurrent_main"), 1)
        self.assertEqual(source.count("max_concurrent_main=max_concurrent_main()"), 1)
        source = Path(rondo_eval.multi_m5.gate2.__file__).read_text("utf-8")
        self.assertEqual(source.count("max_concurrent_main=max_concurrent_main(contract)"), 1)
        # The frozen product default is Root plus three members. A per-run cap is
        # sized against this number, so it is asserted rather than assumed.
        self.assertEqual(max_concurrent_main(), 4)


class MultiM5SmokeIsolationTests(unittest.TestCase):
    """The separately authorized smoke run must stay outside the contract.

    It spends real money on the same model, so the danger is that its row later
    reads as gate 1 evidence, or that its cost quietly eats the $120 the two
    gates share.
    """

    def test_smoke_batch_cap_and_paths_are_separate_from_phase_b(self) -> None:
        self.assertEqual(SMOKE_BATCH_ID, "multi-m5-clean-smoke-v5")
        self.assertEqual(SMOKE_LOCK_ID, "multi-m5-clean-smoke-v5")
        self.assertNotEqual(SMOKE_BATCH_ID, BATCH_ID)
        self.assertNotEqual(SMOKE_LOCK_ID, "multi-m5-workflow-v1")
        self.assertLess(SMOKE_CAP_USD, HARD_CAP_USD)
        root = _common_root()
        self.assertTrue(
            str(smoke_ledger_path(root)).endswith("multi-m5-clean-smoke-v5.json")
        )
        self.assertTrue(
            str(smoke_archive_path(root)).endswith("clean-smoke-v5-records.jsonl")
        )
        self.assertNotEqual(smoke_ledger_path(root), budget_ledger_path(root))
        self.assertNotEqual(smoke_archive_path(root), archive_path(root))
        self.assertNotEqual(
            smoke_ledger_path(root),
            (root / "eval-data/budgets/multi-m5-clean-smoke.json").resolve(),
        )
        self.assertNotEqual(
            smoke_archive_path(root),
            (
                root
                / "eval-data/multi-m5/archives/code-mode-smoke-records.jsonl"
            ).resolve(),
        )

    def test_smoke_ledger_refuses_the_phase_b_batch(self) -> None:
        scratch = scratch_root(_common_root())
        path = scratch / "multi-m5-test-smoke-ledger.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        try:
            with open_smoke_ledger(path) as ledger:
                snapshot = ledger.snapshot()
                self.assertEqual(snapshot["batch_id"], SMOKE_BATCH_ID)
                self.assertEqual(Decimal(snapshot["total_cap_usd"]), SMOKE_CAP_USD)
                # Each corrected clean-smoke identity carries one validation
                # run; its cap is the mechanical product of that slot and the
                # per-run cap.
                self.assertEqual(SMOKE_MAX_RUNS, 1)
                self.assertEqual(SMOKE_CAP_USD, SMOKE_MAX_RUNS * smoke_run_cap_usd())
                self.assertEqual(snapshot["max_runs"], SMOKE_MAX_RUNS)
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_smoke_requires_authorization_and_never_loads_the_key(self) -> None:
        from rondo_eval.multi_m5.__main__ import main as m5_main

        # No phrase: exit 78 before any secret is read or any socket is opened.
        self.assertEqual(m5_main(["smoke", "--label", "probe1"]), 78)
        # A reused or missing label is refused before authorization is even
        # considered: two smoke runs sharing an id is how the first batch's
        # ledger got replaced by the second's.
        self.assertEqual(m5_main(["smoke"]), 2)


class MultiM5FrozenModelIsolationTests(unittest.TestCase):
    """M-5 runs gpt-5.6-terra without disturbing the sol campaigns on this host.

    `paid_eval.main_model` is a machine-wide alias. Flipping it to terra would
    have rewritten the provider identity of every frozen campaign sharing this
    config -- the P2/B7 baseline lock notices immediately. So M-5 resolves its
    model from its own lock instead.
    """

    def test_m5_pins_terra_while_the_host_alias_stays_sol(self) -> None:
        config = load_runtime_config(RepoPaths.discover(Path.cwd()))
        contract = load_nondegradation_contract()
        workflow = load_workflow_contract()
        self.assertEqual(contract.root_model, "gpt-5.6-terra")
        self.assertEqual(workflow.root_model, "gpt-5.6-terra")
        pinned = config.paid_provider_projection(model_id=contract.root_model)
        self.assertEqual(pinned.main_model, "gpt-5.6-terra")
        # The unpinned projection is what every other campaign resolves, and it
        # must be untouched by M-5's choice.
        self.assertNotEqual(
            config.paid_provider_projection().main_model, pinned.main_model
        )

    def test_the_retry_ladder_is_the_locks_and_not_this_machines(self) -> None:
        """Both gates retry on the frozen ladder, whatever the host file says.

        `paid_eval.retry_backoff_seconds` is machine-wide. Gate 2 was reading it
        while gate 1 used its own hard-coded 2s, so the two gates retried
        differently and neither value was frozen. Same isolation as the model id:
        M-5 reads its own lock and leaves the host alias to other campaigns.
        """

        contract = load_nondegradation_contract()
        self.assertEqual(retry_backoff_seconds(contract), 2.0)
        self.assertEqual(
            retry_backoff_seconds(replace(contract, retry_backoff_seconds=7.0)), 7.0
        )
        config = load_runtime_config(RepoPaths.discover(Path.cwd()))
        projection = config.paid_provider_projection(model_id=contract.root_model)
        # The host ladder is not compared against the lock, because M-5 never
        # sends it to the proxy: an unrelated edit must not fail an M-5 run.
        drifted = replace(projection, retry_backoff_seconds=29.0)
        require_frozen_provider(drifted, effort=contract.root_effort, contract=contract)
        self.assertEqual(retry_backoff_seconds(contract), 2.0)

    def test_prepared_gate2_runs_agree_with_the_lock_on_both_sides(self) -> None:
        """Spec, adapter, argv and proxy must all name the locked model.

        This is the check that was missing: the proxy resolved the campaign's
        own model while `make_run_spec` still inherited the machine-wide alias,
        so the adapter launched the binary on a model the proxy would reject.
        Nothing here spends money or starts Docker.
        """

        report = readiness_report(common_root=_common_root())
        projection = report["checks"]["gate2_model_projection"]
        self.assertTrue(projection.get("ok"), projection)
        contract = load_nondegradation_contract()
        for side, values in projection["sides"].items():
            with self.subTest(side=side):
                self.assertEqual(values["run_spec_main_model"], contract.root_model)
                self.assertEqual(values["adapter_model_name"], contract.root_model)
                self.assertEqual(values["main_effort"], contract.root_effort)
        # Only Multi carries a member model; the frozen upstream must not.
        self.assertEqual(
            projection["sides"]["rondo"]["adapter_subagent_model"],
            contract.member_model,
        )
        self.assertEqual(projection["sides"]["codex"]["adapter_subagent_model"], "")

    def test_a_mismatched_prepared_run_is_refused_before_docker(self) -> None:
        contract = load_nondegradation_contract()
        drifted = replace(contract, root_model="gpt-5.6-sol")
        paths = RepoPaths.discover(Path.cwd())
        config = load_runtime_config(paths)
        executor = TerminalBenchSlotExecutor(
            common_root=_common_root(), authorize_docker=False, paths=paths
        )
        slot = base_slots(contract)[0]
        with tempfile.TemporaryDirectory(dir=scratch_root(_common_root())) as raw:
            executor._work_root = Path(raw)
            request = executor.build_request(slot, attempt=1, run_id="m5-g2-mismatch")
            prepared = prepare_terminal_bench_run(config, request)
            with self.assertRaisesRegex(Gate2Error, "frozen model contract"):
                require_pinned_model(prepared, drifted)
            # The proxy disagreeing is caught too, even when the spec is right.
            with self.assertRaisesRegex(Gate2Error, "budget_proxy_model"):
                require_pinned_model(prepared, contract, proxy_model="gpt-5.6-sol")

    def test_the_budget_reservation_bounds_the_worst_legal_request(self) -> None:
        """The property that makes $120 an upper bound rather than an intention."""

        contract = load_nondegradation_contract()
        envelope = usage_envelope(contract)
        pricing = phase_b_pricing(contract)
        reservation = request_reservation_usd(contract)
        self.assertGreaterEqual(reservation, maximum_usage_cost(pricing, envelope))
        # Without the envelope the generic Usage contract admits a request that
        # costs far more than the reservation, which is exactly how a settled
        # charge could exceed what it held.
        self.assertGreater(maximum_usage_cost(pricing), reservation)
        # Every legal caller must fit under the per-run cap at once, or the
        # harness rejects a request the product is entitled to make.
        self.assertGreaterEqual(gate1_run_cap_usd(contract), peak_reservation_usd(contract))
        self.assertGreaterEqual(gate2_run_cap_usd(contract), peak_reservation_usd(contract))

    def test_usage_outside_the_envelope_is_refused_not_priced(self) -> None:
        scratch = scratch_root(_common_root())
        path = scratch / "m5-envelope-probe.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        contract = load_nondegradation_contract()
        pricing = phase_b_pricing(contract)
        envelope = usage_envelope(contract)
        try:
            with open_smoke_ledger(path) as ledger:
                ledger.ensure_run("m5-envelope", cap_usd=gate1_run_cap_usd())
                reserved = ledger.reserve(
                    "m5-envelope", "req-1", request_reservation_usd(contract)
                )
                ledger.begin_attempt("m5-envelope", "req-1", max_attempts=5)
                # One token past the frozen envelope: the charge falls back to
                # the reservation instead of being priced above it.
                settlement = ledger.settle(
                    "m5-envelope",
                    "req-1",
                    Usage(envelope.max_input_tokens + 1, 0, 0, 0),
                    pricing=pricing,
                )
                self.assertEqual(settlement.charged_usd, reserved)
                self.assertFalse(settlement.usage_valid)
                run = ledger.snapshot()["runs"]["m5-envelope"]
                self.assertEqual(run["stop_reason"], "usage_outside_frozen_envelope")
                self.assertEqual(
                    stop_reason_class(run["stop_reason"]), "infra"
                )
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_an_upstream_fault_taints_the_run_even_when_it_continues(self) -> None:
        """Continuing is a spending decision; being evidence is not.

        cm4 absorbed eight upstream terminal errors under the stop threshold and
        was archived as a clean `agent_failed` -- a verdict about the model that
        the run never earned. Taint is recorded on every conservative
        settlement, with or without a stop.
        """

        scratch = scratch_root(_common_root())
        path = scratch / "m5-taint-probe.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        contract = load_nondegradation_contract()
        pricing = phase_b_pricing(contract)
        reservation = request_reservation_usd(contract)
        try:
            with open_smoke_ledger(path) as ledger:
                ledger.ensure_run("m5-taint", cap_usd=gate1_run_cap_usd())
                self.assertIsNone(run_infra_taint(ledger, "m5-taint"))
                ledger.reserve("m5-taint", "req-1", reservation)
                ledger.begin_attempt("m5-taint", "req-1", max_attempts=5)
                ledger.settle(
                    "m5-taint",
                    "req-1",
                    None,
                    pricing=pricing,
                    stop_reason="upstream_terminal_error",
                )
                run = ledger.snapshot()["runs"]["m5-taint"]
                # Under the smoke threshold the run keeps going ...
                self.assertFalse(run["stopped"])
                self.assertIsNone(run["stop_reason"])
                # ... but the fault is on the record regardless.
                taint = run_infra_taint(ledger, "m5-taint")
                self.assertEqual(taint["count"], 1)
                self.assertEqual(taint["first_reason"], "upstream_terminal_error")
                ledger.reserve("m5-taint", "req-2", reservation)
                ledger.begin_attempt("m5-taint", "req-2", max_attempts=5)
                ledger.settle("m5-taint", "req-2", None, pricing=pricing)
                self.assertEqual(run_infra_taint(ledger, "m5-taint")["count"], 2)
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_gate1_reports_infra_failed_when_the_run_is_tainted(self) -> None:
        """A tainted gate 1 run is never `completed`, even with every predicate true."""

        import rondo_eval.multi_m5.gate1 as gate1_module

        original = gate1_module._run_gate1_once

        def _with_taint(**kwargs):
            kwargs["taint_probe"] = lambda: {
                "count": 8,
                "first_reason": "upstream_terminal_error",
            }
            return original(**kwargs)

        with patch.object(gate1_module, "_run_gate1_once", _with_taint):
            result = gate1_module.run_gate1_rehearsal(
                common_root=_common_root(),
                persist=False,
                capture_base=_isolated_capture_base(self),
            )
        record = result["record"]
        self.assertEqual(record["outcome"], "infra_failed")
        self.assertFalse(record["passed"])
        # The predicates were all satisfied; the run still cannot be a pass.
        self.assertTrue(all(record["predicates"].values()))
        self.assertEqual(record["infra_taint"]["count"], 8)
        self.assertIn("infra_taint:upstream_terminal_error", record["reasons"][0])

    def test_gate2_never_counts_a_tainted_slot_as_an_observation(self) -> None:
        """A slot that saw the upstream fail cannot feed the degradation verdict."""

        scratch = scratch_root(_common_root())
        path = scratch / "m5-gate2-taint.json"
        lock = path.with_name(f".{path.name}.lock")
        archive = scratch / "m5-gate2-taint-records.jsonl"
        for item in (path, lock, archive):
            if item.exists():
                item.unlink()
        try:
            with open_phase_b_ledger(path) as ledger:
                real_taint = rondo_eval.multi_m5.gate2.run_infra_taint

                def _tainted(led, run_id):
                    # Only the Multi side of the first task sees a fault.
                    if "db-wal-recovery-rondo" in run_id:
                        return {"count": 1, "first_reason": "upstream_terminal_error"}
                    return real_taint(led, run_id)

                with patch.object(
                    rondo_eval.multi_m5.gate2, "run_infra_taint", _tainted
                ):
                    result = run_light_interleaved(
                        executor=ScriptedSlotExecutor(),
                        common_root=_common_root(),
                        ledger=ledger,
                        persist=False,
                        charge_fake_usage=True,
                    )
        finally:
            for item in (path, lock, archive):
                if item.exists():
                    item.unlink()
        tainted = [
            row
            for row in result["records"]
            if "db-wal-recovery" in str(row.get("task_id"))
            and row.get("product") == Product.RONDO_MULTI.value
        ]
        self.assertTrue(tainted)
        for row in tainted:
            self.assertFalse(row["counts_as_effective"])
            self.assertEqual(row["outcome"], RunOutcome.INFRA_FAILED.value)
        # A fabricated one-way degradation must not appear on that task.
        self.assertNotEqual(
            result["verdicts"].get("terminal-bench/db-wal-recovery"),
            "stable_one_way_degradation",
        )

    def test_one_unpriced_response_does_not_destroy_the_run(self) -> None:
        """A single upstream glitch must not end a run that is still funded.

        The relay occasionally streams a terminal event with no usage. With the
        historical threshold of 1 the ledger stopped the run, so every later
        request was refused with HTTP 429 and the agent died -- two real smoke
        runs were lost that way, each to one hiccup. The charge does not soften:
        the request is still billed its full reservation.
        """

        scratch = scratch_root(_common_root())
        path = scratch / "m5-unpriced-probe.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        contract = load_nondegradation_contract()
        pricing = phase_b_pricing(contract)
        reservation = request_reservation_usd(contract)
        try:
            with open_smoke_ledger(path) as ledger:
                ledger.ensure_run("m5-unpriced", cap_usd=gate1_run_cap_usd())
                threshold = SMOKE_UNPRICED_STOP_THRESHOLD
                for index in range(threshold):
                    request_id = f"req-{index}"
                    ledger.reserve("m5-unpriced", request_id, reservation)
                    ledger.begin_attempt("m5-unpriced", request_id, max_attempts=5)
                    settlement = ledger.settle(
                        "m5-unpriced", request_id, None, pricing=pricing
                    )
                    # Accounting is unchanged at every step.
                    self.assertEqual(settlement.charged_usd, reservation)
                    self.assertFalse(settlement.usage_valid)
                    run = ledger.snapshot()["runs"]["m5-unpriced"]
                    expected_stop = index + 1 >= threshold
                    self.assertEqual(run["stopped"], expected_stop)
                self.assertEqual(
                    ledger.snapshot()["runs"]["m5-unpriced"]["stop_reason"],
                    "missing_or_invalid_usage",
                )
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_other_campaigns_still_stop_on_the_first_unpriced_response(self) -> None:
        """The relaxation is opt-in; every existing ledger keeps threshold 1."""

        scratch = scratch_root(_common_root())
        path = scratch / "m5-unpriced-default.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        pricing = phase_b_pricing()
        try:
            with PersistentBudgetLedger(
                path, batch_id="m5-default-probe", total_cap_usd=Decimal("10.00")
            ) as ledger:
                self.assertEqual(ledger.unpriced_stop_threshold, 1)
                ledger.ensure_run("run-a", cap_usd=Decimal("5.00"))
                ledger.reserve("run-a", "req-1", Decimal("1.00"))
                ledger.begin_attempt("run-a", "req-1", max_attempts=5)
                ledger.settle("run-a", "req-1", None, pricing=pricing)
                self.assertTrue(ledger.snapshot()["runs"]["run-a"]["stopped"])
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_an_out_of_envelope_response_still_stops_immediately(self) -> None:
        """A contract violation is not a glitch and is never absorbed."""

        scratch = scratch_root(_common_root())
        path = scratch / "m5-envelope-stop.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        contract = load_nondegradation_contract()
        pricing = phase_b_pricing(contract)
        envelope = usage_envelope(contract)
        try:
            with open_smoke_ledger(path) as ledger:
                ledger.ensure_run("m5-envelope", cap_usd=gate1_run_cap_usd())
                ledger.reserve(
                    "m5-envelope", "req-1", request_reservation_usd(contract)
                )
                ledger.begin_attempt("m5-envelope", "req-1", max_attempts=5)
                ledger.settle(
                    "m5-envelope",
                    "req-1",
                    Usage(envelope.max_input_tokens + 1, 0, 0, 0),
                    pricing=pricing,
                )
                run = ledger.snapshot()["runs"]["m5-envelope"]
                self.assertTrue(run["stopped"])
                self.assertEqual(run["stop_reason"], "usage_outside_frozen_envelope")
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_paid_run_ids_cannot_be_spent_twice(self) -> None:
        scratch = scratch_root(_common_root())
        path = scratch / "m5-claim-probe.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        try:
            with open_smoke_ledger(path) as ledger:
                ledger.claim_run("m5-g1-smoke-once", cap_usd=gate1_run_cap_usd())
                # A re-invoked CLI must not pay twice against a consumed slot.
                with self.assertRaises(BudgetStopped):
                    ledger.claim_run("m5-g1-smoke-once", cap_usd=gate1_run_cap_usd())
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_stop_reasons_separate_running_out_of_money_from_breaking(self) -> None:
        self.assertEqual(stop_reason_class("budget_capacity_exhausted"), "budget")
        self.assertEqual(stop_reason_class("usage_cost_exceeded_reservation"), "budget")
        self.assertEqual(stop_reason_class(REQUEST_LIMIT_STOP_REASON), "budget")
        # These are the upstream or the harness failing. The ledger still
        # debited a reservation, but nothing ran out: calling them budget stops
        # sent triage at the wrong thing and, in gate 2, would end the batch.
        self.assertEqual(stop_reason_class("upstream_terminal_failed"), "infra")
        self.assertEqual(stop_reason_class("missing_or_invalid_usage"), "infra")
        self.assertEqual(stop_reason_class("upstream_response_unavailable"), "infra")
        self.assertEqual(stop_reason_class(None), "none")
        # Never guessed.
        self.assertEqual(stop_reason_class("something_new"), "unknown")

    def test_exposure_separates_priced_spend_from_held_reservations(self) -> None:
        scratch = scratch_root(_common_root())
        path = scratch / "m5-exposure-probe.json"
        lock = path.with_name(f".{path.name}.lock")
        for item in (path, lock):
            if item.exists():
                item.unlink()
        contract = load_nondegradation_contract()
        pricing = phase_b_pricing(contract)
        try:
            with open_smoke_ledger(path) as ledger:
                ledger.ensure_run("m5-exposure", cap_usd=gate1_run_cap_usd())
                ledger.reserve("m5-exposure", "req-1", Decimal("1.00"))
                ledger.begin_attempt("m5-exposure", "req-1", max_attempts=5)
                ledger.settle(
                    "m5-exposure", "req-1", Usage(1000, 0, 0, 0), pricing=pricing
                )
                summary = exposure_summary(ledger.snapshot(), "m5-exposure")
                self.assertEqual(
                    Decimal(summary["conservative_exposure_usd"]), Decimal("0")
                )
                self.assertGreater(Decimal(summary["priced_usd"]), 0)
        finally:
            for item in (path, lock):
                if item.exists():
                    item.unlink()

    def test_the_pinned_projection_satisfies_the_frozen_contract(self) -> None:
        config = load_runtime_config(RepoPaths.discover(Path.cwd()))
        contract = load_nondegradation_contract()
        identity = require_frozen_provider(
            config.paid_provider_projection(model_id=contract.root_model),
            effort=contract.root_effort,
            contract=contract,
        )
        self.assertEqual(identity["main_model"], "gpt-5.6-terra")
        # Rates meter the $120 cap, so lock and machine config must agree
        # exactly; a mismatch is what `require_frozen_provider` exists to catch.
        self.assertEqual(
            identity["frozen_price_snapshot_date"],
            identity["effective_price_snapshot_date"],
        )

    def test_an_unmapped_model_fails_closed_instead_of_falling_back(self) -> None:
        config = load_runtime_config(RepoPaths.discover(Path.cwd()))
        with self.assertRaises(ConfigError):
            config.paid_provider_projection(model_id="gpt-5.6-does-not-exist")


class MultiM5AttributionDiagnosticTests(unittest.TestCase):
    """The lock's `diagnostic_v2_on_team_state_off` must be a real run.

    Before this it was a sentence the loader grepped for: nothing built the
    slot, nothing turned the team layer off, and a degradation could only ever
    be attributed by assertion.
    """

    def test_no_degradation_means_the_diagnostic_is_never_pre_run(self) -> None:
        result = run_light_interleaved(
            executor=ScriptedSlotExecutor(),
            common_root=_common_root(),
            persist=False,
        )
        self.assertEqual(result["diagnostic_slots"], 0)
        self.assertEqual(result["diagnostics"], {})
        self.assertTrue(result["passed"])
        self.assertFalse(
            any(row.get("slot_kind") == DIAGNOSTIC_SLOT_KIND for row in result["records"])
        )

    def test_degraded_task_draws_a_team_state_off_row_that_is_not_an_observation(self) -> None:
        contract = load_nondegradation_contract()
        first = contract.tasks[0]
        script = {
            (first, "rondo", round_index): ("agent_failed",)
            for round_index in (1, 2, 3)
        }
        result = run_light_interleaved(
            executor=ScriptedSlotExecutor(script),
            common_root=_common_root(),
            persist=False,
        )
        self.assertEqual(result["verdicts"][first], "stable_one_way_degradation")
        self.assertEqual(result["diagnostic_slots"], 1)
        self.assertEqual(result["diagnostics"], {first: "completed"})
        rows = [row for row in result["records"] if row.get("slot_kind") == DIAGNOSTIC_SLOT_KIND]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["task_id"], first)
        self.assertEqual(row["side"], Side.RONDO.value)
        self.assertEqual(row["product"], Product.RONDO_MULTI.value)
        self.assertEqual(row["round_index"], DIAGNOSTIC_ROUND_INDEX)
        # Attribution evidence, not a fourth observation: it must not enter the
        # effective count and must not soften the verdict.
        self.assertFalse(row["counts_as_effective"])
        self.assertEqual(result["effective_runs"], 24)
        self.assertFalse(result["passed"])
        # The row has to admit which configuration actually ran.
        self.assertTrue(row["team_capability_config"]["multi_agent_v2_enabled"])
        self.assertFalse(row["team_capability_config"]["team_state_enabled"])

    def test_diagnostic_slots_are_multi_only_and_one_per_degraded_task(self) -> None:
        contract = load_nondegradation_contract()
        degraded = {task_id: "no_stable_one_way_degradation" for task_id in contract.tasks}
        degraded[contract.tasks[0]] = "stable_one_way_degradation"
        degraded[contract.tasks[3]] = "stable_one_way_degradation"
        degraded[contract.tasks[5]] = "uncertain"
        slots = diagnostic_slots(contract, degraded)
        self.assertEqual(
            [slot.task_id for slot in slots], [contract.tasks[0], contract.tasks[3]]
        )
        self.assertTrue(all(slot.side is Side.RONDO for slot in slots))
        self.assertTrue(all(slot.product is Product.RONDO_MULTI for slot in slots))

    def test_diagnostic_request_switches_the_team_layer_off(self) -> None:
        contract = load_nondegradation_contract()
        executor = TerminalBenchSlotExecutor(
            common_root=_common_root(),
            catalog=_v4_catalog(),
            binaries={
                Side.CODEX: _dummy_binary(),
                Side.RONDO: _dummy_binary(product="rondo-multi"),
            },
            paths=RepoPaths.discover(Path.cwd()),
        )
        multi_slot = next(
            slot for slot in base_slots(contract) if slot.side is Side.RONDO
        )
        diagnostic = diagnostic_slots(
            contract, {multi_slot.task_id: "stable_one_way_degradation"}
        )[0]
        normal_request = executor.build_request(
            multi_slot, attempt=1, run_id=_run_id(multi_slot, 1)
        )
        diagnostic_request = executor.build_request(
            diagnostic, attempt=1, run_id=_run_id(diagnostic, 1)
        )
        self.assertTrue(normal_request.team_state_enabled)
        self.assertFalse(diagnostic_request.team_state_enabled)
        # Same task, same image, same product: only the team layer differs.
        self.assertEqual(diagnostic_request.product, Product.RONDO_MULTI)
        self.assertEqual(diagnostic_request.image_digest, normal_request.image_digest)
        self.assertEqual(diagnostic_request.timeout_seconds, normal_request.timeout_seconds)

    def test_a_degradation_diagnostic_still_obeys_the_batch_stop_lines(self) -> None:
        contract = load_nondegradation_contract()
        first = contract.tasks[0]
        script = {
            (first, "rondo", round_index): ("agent_failed",)
            for round_index in (1, 2, 3)
        }

        class _StoppingExecutor(ScriptedSlotExecutor):
            def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
                if slot.kind == DIAGNOSTIC_SLOT_KIND:
                    raise DockerResourceStop(
                        "host free space below the 80 GiB floor",
                        failed_probe="data_root_free",
                    )
                return super().execute(slot, attempt=attempt, run_id=run_id)

        result = run_light_interleaved(
            executor=_StoppingExecutor(script),
            common_root=_common_root(),
            persist=False,
        )
        # A capacity stop during the diagnostic ends the batch rather than
        # retrying: the diagnostic shares every stop line with the paid batch.
        self.assertTrue(result["stopped"])
        self.assertEqual(result["stop_reason"], "docker_resource_stop")
        self.assertEqual(result["verdicts"][first], "stable_one_way_degradation")
        self.assertFalse(result["passed"])

    def test_every_attempt_gets_its_own_staging_identity(self) -> None:
        """Retries and the round 2/3 reruns must be able to materialize at all.

        `PinnedTaskMaterializer` refuses to reuse a destination by design, so a
        staging name keyed only on batch/side/task made the second attempt on a
        slot fail before Docker. That is exactly the infra retry and the
        conditional rerun a degradation verdict depends on.
        """

        paths = RepoPaths.discover(Path.cwd())
        config = load_runtime_config(paths)
        contract = load_nondegradation_contract()
        slot = next(
            slot for slot in base_slots(contract) if slot.side is Side.RONDO
        )
        staged: set[str] = set()
        with tempfile.TemporaryDirectory(dir=scratch_root(_common_root())) as raw:
            executor = TerminalBenchSlotExecutor(
                common_root=_common_root(),
                authorize_docker=False,
                paths=paths,
                work_root=Path(raw),
            )
            for attempt in (1, 2, 3):
                run_id = _run_id(slot, attempt)
                request = executor.build_request(
                    slot, attempt=attempt, run_id=run_id
                )
                prepared = prepare_terminal_bench_run(config, request)
                staged.add(str(prepared.materialized_task.task_path))
        self.assertEqual(len(staged), 3)

    def test_a_stopped_gate1_run_cannot_archive_as_completed(self) -> None:
        """Stop lines are decided before the success branch.

        Evidence formed earlier in the run does not undo a stop: a run whose
        ledger hit capacity, or whose upstream failed, did not finish under the
        frozen contract. Archiving it as `completed/passed=true` would let gate
        1 pass after a stop line actually fired.
        """

        for reason, expected in (
            ("budget_capacity_exhausted", "budget_stopped"),
            ("upstream_terminal_failed", "infra_failed"),
            ("missing_or_invalid_usage", "infra_failed"),
        ):
            with self.subTest(stop_reason=reason):
                result = self._gate1_rehearsal_with_stop(reason)
                record = result["record"]
                self.assertEqual(record["outcome"], expected)
                self.assertFalse(record["passed"])
                self.assertEqual(record["stop_reason"], reason)
                # The predicates stay on the row so a near-miss is diagnosable.
                self.assertTrue(all(record["predicates"].values()))

    def _gate1_rehearsal_with_stop(self, reason: str) -> dict:
        import rondo_eval.multi_m5.gate1 as gate1_module

        original = gate1_module._run_gate1_once

        def _with_stop(**kwargs):
            kwargs["budget_probe"] = lambda: reason
            return original(**kwargs)

        with patch.object(gate1_module, "_run_gate1_once", _with_stop):
            return gate1_module.run_gate1_rehearsal(
                common_root=_common_root(),
                persist=False,
                capture_base=_isolated_capture_base(self),
            )

    def test_archived_rows_state_the_identity_the_run_actually_used(self) -> None:
        """A row must name the contract that governed it and the member it ran.

        Both drifted silently: `_record_for` hard-coded the v1 lock id while the
        loader read v2, and the team-capability projection fell back to the host
        default while the command line ran the pinned member model. A row that
        contradicts its own run cannot be evidence.
        """

        contract = load_nondegradation_contract()
        runtime = load_runtime_identity(
            require_frozen=True, common_root=_common_root()
        )
        for side_name in ("rondo", "codex"):
            slot = next(
                slot for slot in base_slots(contract) if slot.side.value == side_name
            )
            with self.subTest(side=side_name):
                row = _record_for(
                    slot,
                    runtime,
                    outcome="completed",
                    counts_as_effective=True,
                    extra={},
                    contract=contract,
                )
                self.assertEqual(row["lock_id"], contract.lock_id)
                self.assertEqual(row["lock_id"], NONDEGRADATION_LOCK_ID)
                config = row["team_capability_config"]
                if side_name == "rondo":
                    self.assertEqual(
                        config["default_subagent_model"], contract.member_model
                    )
                else:
                    # The frozen upstream has no members to configure.
                    self.assertIsNone(config)

    def test_a_multi_row_cannot_omit_its_member_identity(self) -> None:
        with self.assertRaises(ValueError):
            archive_record(
                evidence_kind="fake",
                gate=1,
                lock_id=WORKFLOW_LOCK_ID,
                side=Side.RONDO,
                product=Product.RONDO_MULTI,
                source_commit="0" * 40,
                binary_sha256="a" * 64,
                outcome="completed",
                counts_as_effective=False,
            )

    def test_the_lock_must_carry_an_executable_diagnostic_contract(self) -> None:
        """Drift in the diagnostic block must fail the loader, field by field.

        This test used to read the v1 file and hand variants to a loader that
        only accepts v2, so every case died on the lock id before reaching the
        field it meant to check -- green, but asserting nothing. It now reads
        the live contract and first proves an unmodified copy loads.
        """

        source = EVAL_ROOT / "locks" / f"{NONDEGRADATION_LOCK_ID}.json"
        raw = json.loads(source.read_text("utf-8"))
        self.assertEqual(raw["lock_id"], NONDEGRADATION_LOCK_ID)
        self.assertEqual(
            raw["attribution"]["diagnostic"]["id"], "diagnostic_v2_on_team_state_off"
        )

        def _write(document: dict, tmp: str) -> Path:
            path = Path(tmp) / f"{NONDEGRADATION_LOCK_ID}.json"
            path.write_text(json.dumps(document), "utf-8")
            return path

        # The control: an untouched copy must load, otherwise every rejection
        # below could be caused by the copy rather than by the mutation.
        with tempfile.TemporaryDirectory() as tmp:
            loaded = load_nondegradation_contract(_write(raw, tmp))
            self.assertEqual(loaded.lock_id, NONDEGRADATION_LOCK_ID)

        for mutation in (
            {"team_state_enabled": True},
            {"counts_as_effective": True},
            {"pre_run_forbidden": False},
            {"side": "codex"},
            {"shares_batch_budget": False},
            # When it may run and what it may change are what keep this an
            # attribution probe rather than a second chance at the verdict.
            {"runs_when": "before the first observation"},
            {"verdict_effect": "promotes the task to no_stable_one_way_degradation"},
            # An unknown key is either silently ignored or a second,
            # contradictory statement of one that is honoured.
            {"also_counts_as_effective": True},
        ):
            with self.subTest(mutation=mutation):
                broken = json.loads(json.dumps(raw))
                broken["attribution"]["diagnostic"].update(mutation)
                with tempfile.TemporaryDirectory() as tmp:
                    with self.assertRaises(M5ContractError):
                        load_nondegradation_contract(_write(broken, tmp))

        with tempfile.TemporaryDirectory() as tmp:
            broken = json.loads(json.dumps(raw))
            del broken["attribution"]["diagnostic"]
            with self.assertRaises(M5ContractError):
                load_nondegradation_contract(_write(broken, tmp))

        # The forecast is recomputed from the lock's own basis, so a hand-edited
        # total must be refused rather than believed.
        with tempfile.TemporaryDirectory() as tmp:
            broken = json.loads(json.dumps(raw))
            broken["cost_forecast"]["worst_schedule_shape_usd"] = "1.00"
            with self.assertRaises(M5ContractError):
                load_nondegradation_contract(_write(broken, tmp))

    def test_docker_is_required_and_requests_are_not_campaigns(self) -> None:
        root = _common_root()
        catalog = _v4_catalog()
        binaries = {
            Side.CODEX: _dummy_binary(),
            Side.RONDO: _dummy_binary(product="rondo-multi"),
        }
        executor = TerminalBenchSlotExecutor(
            common_root=root,
            catalog=catalog,
            binaries=binaries,
            paths=RepoPaths.discover(Path.cwd()),
        )
        slots = base_slots(load_nondegradation_contract())
        codex_slot = next(slot for slot in slots if slot.side is Side.CODEX)
        multi_slot = next(slot for slot in slots if slot.side is Side.RONDO)
        with self.assertRaisesRegex(Gate2Error, "not authorized"):
            executor.execute(codex_slot, attempt=1, run_id="m5-g2-fix-git-codex-r1-a1")
        codex_request = executor.build_request(
            codex_slot, attempt=1, run_id="m5-g2-fix-git-codex-r1-a1"
        )
        multi_request = executor.build_request(
            multi_slot, attempt=1, run_id="m5-g2-fix-git-rondo-r1-a1"
        )
        self.assertIsNone(codex_request.product)
        self.assertEqual(multi_request.product, Product.RONDO_MULTI)
        self.assertEqual(multi_request.batch_id, "multi-m5-phase-b-v6")
        self.assertFalse(hasattr(multi_request, "campaign_id"))
        self.assertIsNone(getattr(multi_request, "campaign_identity", None))
        self.assertIsNotNone(multi_request.frozen_task)

    def test_recording_subclass_can_write_real_api_rows(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-gate2-real-rows.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        requests: list[object] = []

        class RecordingExecutor(TerminalBenchSlotExecutor):
            def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
                requests.append(
                    self.build_request(slot, attempt=attempt, run_id=run_id)
                )
                return SlotResult(outcome="completed", extra={"executor": "recording"})

        executor = RecordingExecutor(
            common_root=root,
            catalog=_v4_catalog(),
            binaries={
                Side.CODEX: _dummy_binary(),
                Side.RONDO: _dummy_binary(product="rondo-multi"),
            },
            paths=RepoPaths.discover(Path.cwd()),
        )
        with open_phase_b_ledger(ledger_path) as ledger:
            result = run_light_interleaved(
                executor=executor,
                common_root=root,
                ledger=ledger,
                persist=False,
                charge_fake_usage=False,
                evidence_kind="real_api",
            )
            snapshot = ledger.snapshot()
        self.assertFalse(result["stopped"])
        self.assertEqual(result["effective_runs"], 20)
        self.assertTrue(all(row["evidence_kind"] == "real_api" for row in result["records"]))
        self.assertTrue(requests)
        self.assertTrue(
            all(
                Decimal(info["cap_usd"]) == gate2_run_cap_usd()
                for info in snapshot["runs"].values()
            )
        )
        self.assertTrue(any(req.product is Product.RONDO_MULTI for req in requests))
        self.assertTrue(any(req.product is None for req in requests))
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()

    def test_budget_proxy_keeps_the_gate2_eight_dollar_run_cap(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-gate2-run-cap.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        metadata = scratch / "multi-m5-test-gate2-run-cap-meta.json"
        for item in (ledger_path, lock_path, metadata):
            if item.exists():
                item.unlink()
        workflow = load_workflow_contract()
        pricing = phase_b_pricing()
        run_id = "m5-g2-fix-git-codex-r1-a1"
        kwargs = {
            "upstream_base_url": "https://provider.example/v1",
            "api_key": "sk-test-never-spend",
            "run_id": run_id,
            "metadata_path": metadata,
            "main_model": workflow.root_model,
            "main_effort": workflow.root_effort,
            "main_pricing": pricing,
            "guardian_model": workflow.root_model,
            "guardian_pricing": pricing,
            "guardian_effort": workflow.root_effort,
            "max_attempts": 5,
            "retry_backoff_seconds": 0.0,
            "unbilled_retry_statuses": (429, 500, 502, 503, 504),
            "request_reservation_usd": request_reservation_usd(),
            "timeout_seconds": FORWARD_TIMEOUT_SECONDS,
        }
        with open_phase_b_ledger(ledger_path) as ledger:
            ledger.ensure_run(run_id, cap_usd=gate2_run_cap_usd())
            with self.assertRaisesRegex(ApiBudgetProxyError, "existing run cap"):
                LoopbackResponsesProxy(ledger=ledger, **kwargs)
            proxy = LoopbackResponsesProxy(
                ledger=ledger,
                run_cap_usd=gate2_run_cap_usd(),
                **kwargs,
            )
            self.assertEqual(
                Decimal(ledger.snapshot()["runs"][run_id]["cap_usd"]),
                gate2_run_cap_usd(),
            )
            del proxy
            ledger.ensure_run("m5-g1-v6-paid-a1", cap_usd=gate1_run_cap_usd())
            gate1 = LoopbackResponsesProxy(
                ledger=ledger,
                run_id="m5-g1-v6-paid-a1",
                metadata_path=scratch / "multi-m5-test-gate1-run-cap-meta.json",
                run_cap_usd=gate1_run_cap_usd(),
                **{k: v for k, v in kwargs.items() if k not in {"run_id", "metadata_path"}},
            )
            self.assertEqual(
                Decimal(ledger.snapshot()["runs"]["m5-g1-v6-paid-a1"]["cap_usd"]),
                gate1_run_cap_usd(),
            )
            del gate1
        for item in (ledger_path, lock_path, metadata):
            if item.exists():
                item.unlink()


class MultiM5BudgetStopHonestyTests(unittest.TestCase):
    """A budget cut-off must never read as a product failure on either gate."""

    def test_gate1_reservation_leaves_room_above_the_frozen_point_estimate(self) -> None:
        # A reservation is checked twice: once for itself and once as Guardian
        # additional capacity. The usable spend is `cap - 2 * reservation`, so an
        # $8 reservation under a $24 cap stopped gate 1 at the $8 point estimate.
        pricing = phase_b_pricing()
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-gate1-headroom.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        # A heavy but realistic medium-effort turn on the frozen snapshot.
        usage = Usage(60_000, 0, 0, 3_000)
        spent = Decimal(0)
        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                ledger.ensure_run("m5-g1-v6-paid-a1", cap_usd=gate1_run_cap_usd())
                for index in range(1, 400):
                    try:
                        ledger.reserve(
                            "m5-g1-v6-paid-a1",
                            f"req-{index}",
                            amount_usd=request_reservation_usd(),
                            additional_capacity_usd=request_reservation_usd(),
                        )
                    except BudgetCapacityExhausted:
                        break
                    ledger.begin_attempt("m5-g1-v6-paid-a1", f"req-{index}", max_attempts=5)
                    ledger.settle("m5-g1-v6-paid-a1", f"req-{index}", usage, pricing=pricing)
                    spent = Decimal(
                        ledger.snapshot()["runs"]["m5-g1-v6-paid-a1"]["spent_usd"]
                    )
                else:  # pragma: no cover - the cap must bind well before this
                    self.fail("gate 1 run cap never bound")
        finally:
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()
        # Twice the frozen $8/attempt forecast, so a normal run is not truncated.
        self.assertGreaterEqual(spent, Decimal("16.00"))
        # The single-turn reservation still has to cover the worst realistic turn.
        self.assertGreaterEqual(
            request_reservation_usd(),
            price_usage(Usage(272_000, 0, 0, 32_000), pricing=pricing),
        )

    def test_phase_b_ledger_has_run_slots_for_both_gates(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-slot-count.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        contract = load_nondegradation_contract()
        workflow = load_workflow_contract()
        needed = (
            contract.max_effective_runs
            + contract.max_infra_attempts_total
            + workflow.max_attempts
            + len(contract.tasks)
        )
        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                # Gate 1 shares this ledger; omitting its own slots starved gate 2,
                # and leaving out the per-task attribution diagnostic would starve
                # the very run that has to explain a degradation.
                self.assertEqual(ledger.snapshot()["max_runs"], needed)
                self.assertEqual(needed, 116)
        finally:
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()

    def test_gate1_budget_stop_is_not_filed_as_an_agent_failure(self) -> None:
        root = _common_root()
        try:
            load_runtime_identity(require_frozen=True, common_root=root)
        except M5ContractError as exc:
            self.skipTest(f"frozen Multi bundle is unavailable: {exc}")
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-gate1-budget-stop.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        upstream = _UsageUpstream()
        upstream.start()
        workflow = load_workflow_contract()
        held: dict[str, object] = {}

        def exhaust_then_fail(command, **_kwargs: object) -> object:
            # One captured body, then the ledger stops the run exactly the way
            # the proxy does when a reservation no longer fits.
            base_url = _provider_base_url(command)
            _post_capture(base_url, workflow.root_model, str(held["bearer"]))
            ledger = held["ledger"]
            ledger.stop_run("m5-g1-v6-paid-a1", stop_reason="budget_capacity_exhausted")
            return subprocess.CompletedProcess(args=command, returncode=1, stdout=b"", stderr=b"")

        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                held["ledger"] = ledger
                original = LoopbackResponsesProxy.downstream_api_key

                def remember(self):  # type: ignore[no-untyped-def]
                    value = original.fget(self)  # type: ignore[union-attr]
                    held["bearer"] = value
                    return value

                with patch.object(
                    LoopbackResponsesProxy,
                    "downstream_api_key",
                    property(remember),
                ):
                    result = run_gate1_paid(
                        authorization=PaidAuthorization(real_api=True, docker=False),
                        api_key="sk-test-never-spend",
                        upstream_base_url="https://provider.example/v1",
                        ledger=ledger,
                        common_root=root,
                        persist=False,
                        capture_base=_isolated_capture_base(self),
                        transport=_UrllibTransport(endpoint_override=upstream.endpoint),
                        process_runner=exhaust_then_fail,  # type: ignore[arg-type]
                    )
            record = result["record"]
            self.assertEqual(record["evidence_kind"], "real_api")
            self.assertEqual(record["outcome"], "budget_stopped")
            self.assertNotEqual(record["outcome"], "agent_failed")
            self.assertEqual(record["stop_reason"], "budget_capacity_exhausted")
            self.assertFalse(record["passed"])
            self.assertFalse(record["counts_as_effective"])
            # One attempt only: retrying after a budget stop just spends more.
            self.assertEqual(record["attempt"], 1)
        finally:
            upstream.close()
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()

    def test_gate2_budget_stop_is_not_an_effective_multi_observation(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-gate2-budget-stop.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        archive_file = scratch / "multi-m5-test-gate2-budget-stop-records.jsonl"
        for item in (ledger_path, lock_path, archive_file):
            if item.exists():
                item.unlink()

        class _ExhaustOnFirstMulti:
            def __init__(self) -> None:
                self.ledger = None

            def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
                del attempt
                if slot.product is Product.RONDO_MULTI and self.ledger is not None:
                    # The proxy answers 429 in-band, so the agent merely looks
                    # like it gave up and Harbor reports a plain failure.
                    self.ledger.stop_run(run_id, stop_reason="budget_capacity_exhausted")
                    return SlotResult(outcome="agent_failed", extra={"executor": "probe"})
                return SlotResult(outcome="completed", extra={"executor": "probe"})

        executor = _ExhaustOnFirstMulti()
        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                executor.ledger = ledger
                result = run_light_interleaved(
                    executor=executor,
                    common_root=root,
                    ledger=ledger,
                    persist=True,
                    archive_file=archive_file,
                )
        finally:
            for item in (ledger_path, lock_path, archive_file):
                if item.exists():
                    item.unlink()
        multi_rows = [
            row
            for row in result["records"]
            if row.get("product") == Product.RONDO_MULTI.value
        ]
        self.assertTrue(multi_rows)
        stopped_row = multi_rows[-1]
        self.assertEqual(stopped_row["outcome"], "budget_stopped")
        self.assertFalse(stopped_row["counts_as_effective"])
        self.assertEqual(stopped_row["stop_reason"], "budget_capacity_exhausted")
        self.assertTrue(result["stopped"])
        # The stopped observation must not reach the degradation verdict.
        self.assertNotIn("stable_one_way_degradation", set(result["verdicts"].values()))


class _FakeTrial:
    """The parts of `parse_single_task_result` output a slot result reads."""

    outcome = RunOutcome.COMPLETED
    task_outcome = "pass"
    reward = 1.0
    duration_seconds = 12.5


class MultiM5PaidEntryHardeningTests(unittest.TestCase):
    """Gaps that only surface once the paid entries touch a real run."""

    def test_gate2_request_count_is_real_and_the_frozen_cap_binds(self) -> None:
        # A Terminal-Bench slot is one host process making many model calls, so
        # a hardcoded `request_count=1` both lies in the archive row and leaves
        # the frozen `max_requests_per_run` cap dead.
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-gate2-request-count.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        contract = load_nondegradation_contract()
        pricing = phase_b_pricing()
        over_cap = contract.max_requests_per_run + 1

        class _ChattyExecutor(TerminalBenchSlotExecutor):
            def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
                del slot, attempt
                assert self._ledger is not None
                for index in range(over_cap):
                    request_id = f"{run_id}-req-{index}"
                    self._ledger.reserve(run_id, request_id, Decimal("0.01"))
                    self._ledger.begin_attempt(run_id, request_id, max_attempts=5)
                    self._ledger.settle(
                        run_id, request_id, Usage(1, 0, 0, 0), pricing=pricing
                    )
                return SlotResult(
                    outcome="completed",
                    request_count=run_request_count(self._ledger, run_id),
                    extra={"executor": "chatty"},
                )

        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                executor = _ChattyExecutor(
                    common_root=root,
                    ledger=ledger,
                    catalog=_v4_catalog(),
                    binaries={
                        Side.CODEX: _dummy_binary(),
                        Side.RONDO: _dummy_binary(product="rondo-multi"),
                    },
                    paths=RepoPaths.discover(Path.cwd()),
                )
                first_run = _run_id(base_slots(contract)[0], 1)
                # The live Harbor path must read the same real count.
                ledger.ensure_run("m5-g2-live-probe", cap_usd=gate2_run_cap_usd())
                for index in range(3):
                    request_id = f"m5-g2-live-probe-req-{index}"
                    ledger.reserve("m5-g2-live-probe", request_id, Decimal("0.01"))
                    ledger.begin_attempt("m5-g2-live-probe", request_id, max_attempts=5)
                    ledger.settle(
                        "m5-g2-live-probe", request_id, Usage(1, 0, 0, 0), pricing=pricing
                    )
                live = executor._slot_result(_FakeTrial(), "m5-g2-live-probe")
                self.assertEqual(live.request_count, 3)
                self.assertEqual(live.outcome, "completed")
                result = run_light_interleaved(
                    executor=executor,
                    common_root=root,
                    ledger=ledger,
                    persist=False,
                    charge_fake_usage=False,
                    evidence_kind="real_api",
                )
                self.assertEqual(run_request_count(ledger, first_run), over_cap)
        finally:
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()
        rows = result["records"]
        self.assertTrue(rows)
        # Over the frozen cap the slot is infrastructure, never an effective
        # "incomplete" that the degradation verdict could consume.
        self.assertTrue(all(row["outcome"] == "infra_failed" for row in rows))
        self.assertTrue(all(row["counts_as_effective"] is False for row in rows))
        self.assertTrue(all(row["reason"] == "max_requests_per_run" for row in rows))
        self.assertEqual(result["effective_runs"], 0)
        self.assertNotIn("stable_one_way_degradation", set(result["verdicts"].values()))

    def test_loopback_transport_override_ignores_an_ambient_http_proxy(self) -> None:
        # Python's no_proxy matching does not understand the `127.*` glob local
        # proxy managers export, so without an empty ProxyHandler the offline
        # capture chain is silently routed through the user's real proxy.
        sink = _HeaderSink()
        sink.start()
        dead = "http://127.0.0.1:1/"
        try:
            with patch.dict(
                "os.environ",
                {"HTTP_PROXY": dead, "http_proxy": dead, "no_proxy": ""},
            ):
                transport = _UrllibTransport(
                    endpoint_override=f"{sink.base_url}/responses"
                )
                response = transport.open(
                    "https://provider.example/v1/responses",
                    body=b'{"model":"probe"}',
                    headers={"Content-Type": "application/json"},
                    timeout=10.0,
                )
                try:
                    self.assertEqual(int(response.status), 200)
                finally:
                    response.close()
            self.assertEqual(sink.writes and 1, 1)
        finally:
            sink.close()

    def test_real_api_rows_require_a_frozen_bundle_on_disk(self) -> None:
        # `require_frozen=False` let a paid batch write rows carrying an
        # unfrozen identity and only fail slot by slot, burning the infra
        # budget before saying why.
        started: list[str] = []

        class _NeverTouchesTheBundle(TerminalBenchSlotExecutor):
            def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
                del slot, attempt
                started.append(run_id)
                return SlotResult(outcome="completed", extra={"executor": "probe"})

        with tempfile.TemporaryDirectory(prefix="rondo-m5-unfrozen-") as raw:
            absent = Path(raw)
            with self.assertRaises(M5ContractError):
                run_light_interleaved(
                    executor=_NeverTouchesTheBundle(
                        common_root=absent,
                        paths=RepoPaths.discover(Path.cwd()),
                    ),
                    common_root=absent,
                    persist=False,
                    evidence_kind="real_api",
                )
            # It must fail before the first slot, not slot by slot.
            self.assertEqual(started, [])
            # The offline fake path must stay runnable without the bundle.
            fake = run_light_interleaved(
                executor=ScriptedSlotExecutor(),
                common_root=absent,
                persist=False,
                evidence_kind="fake",
            )
            self.assertTrue(fake["records"])


class MultiM5ResumeTests(unittest.TestCase):
    class _Executor(TerminalBenchSlotExecutor):
        def __init__(self, *, first_infra: bool = False) -> None:
            self.calls: list[str] = []
            self.first_infra = first_infra

        def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
            del slot
            self.calls.append(run_id)
            if self.first_infra and len(self.calls) == 1 and attempt == 1:
                return SlotResult(outcome="infra_failed", request_count=0)
            return SlotResult(outcome="completed", request_count=0)

    def _identity(self) -> tuple[object, dict[str, object]]:
        root = _common_root()
        contract = load_nondegradation_contract()
        provider = load_runtime_config(
            RepoPaths.discover(Path.cwd())
        ).paid_provider_projection(model_id=contract.root_model)
        provider_identity = require_frozen_provider(
            provider,
            effort=contract.root_effort,
            contract=contract,
        )
        runtime = load_runtime_identity(require_frozen=True, common_root=root)
        return runtime, formal_identity(provider_identity)

    def _gate1_record(
        self,
        runtime,
        identity_fields: dict[str, object],
        *,
        attempt: int,
        outcome: str = "completed",
        run_id: str | None = None,
    ) -> dict[str, object]:
        workflow = load_workflow_contract()
        return archive_record(
            evidence_kind="real_api",
            gate=1,
            lock_id=workflow.lock_id,
            side=Side.RONDO,
            product=Product.RONDO_MULTI,
            source_commit=runtime.source_commit,
            binary_sha256=str(runtime.codex_sha256),
            outcome=outcome,
            counts_as_effective=False,
            subagent_model=workflow.member_model,
            subagent_effort=str(workflow.raw["member_effort"]),
            extra={
                **identity_fields,
                "budget_run_id": run_id or f"m5-g1-v6-paid-a{attempt}",
                "attempt": attempt,
                "ignored_evidence": [],
                "passed": outcome == "completed",
            },
        )

    def test_batch_identity_receipt_is_idempotent_and_exact(self) -> None:
        _runtime, identity_fields = self._identity()
        with tempfile.TemporaryDirectory(
            prefix="m5-receipt-", dir=scratch_root(_common_root())
        ) as raw:
            path = Path(raw) / "identity.json"
            ensure_formal_receipt(path, identity_fields)
            ensure_formal_receipt(path, identity_fields)
            require_formal_receipt(path, identity_fields)
            changed = {**identity_fields, "runtime_lock_id": "wrong"}
            with self.assertRaisesRegex(ResumeError, "differs"):
                ensure_formal_receipt(path, changed)

    def test_gate1_prefix_rejects_future_wrong_and_interleaved_rows(self) -> None:
        runtime, identity_fields = self._identity()
        a1 = self._gate1_record(runtime, identity_fields, attempt=1)
        a2 = self._gate1_record(runtime, identity_fields, attempt=2)
        wrong = self._gate1_record(
            runtime,
            identity_fields,
            attempt=1,
            run_id="m5-g1-v6-paid-wrong",
        )
        gate2 = {"gate": 2}
        cases = {
            "future": ([a2], "contiguous prefix"),
            "wrong-run": ([wrong], "run id differs"),
            "after-terminal": ([a1, a2], "after a terminal row"),
            "gate2-before-pass": (
                [
                    self._gate1_record(
                        runtime, identity_fields, attempt=1, outcome="infra_failed"
                    ),
                    gate2,
                ],
                "before gate 1 completed",
            ),
            "gate1-after-gate2": ([a1, gate2, a2], "after gate 2 started"),
        }
        for name, (rows, message) in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(ResumeError, message):
                validate_gate1_resume_prefix(rows, maximum=6)

    def test_broken_formal_archive_symlink_is_refused_before_claim(self) -> None:
        root = _common_root()
        _runtime, identity_fields = self._identity()
        workflow = load_workflow_contract()
        provider = load_runtime_config(
            RepoPaths.discover(Path.cwd())
        ).paid_provider_projection(model_id=workflow.root_model)

        class NoClaimLedger:
            claims = 0

            def claim_run(self, *_args, **_kwargs):
                self.claims += 1

        with tempfile.TemporaryDirectory(
            prefix="m5-broken-formal-archive-", dir=scratch_root(root)
        ) as raw:
            directory = Path(raw)
            archive_file = directory / "records.jsonl"
            archive_file.symlink_to(directory / "missing.jsonl")
            receipt_file = directory / "identity.json"
            ensure_formal_receipt(receipt_file, identity_fields)
            ledger = NoClaimLedger()
            with self.assertRaisesRegex(Gate1Error, "archive path is unsafe"):
                run_gate1_paid(
                    authorization=PaidAuthorization(real_api=True, docker=False),
                    api_key="sk-test-never-spend",
                    upstream_base_url=provider.base_url,
                    ledger=ledger,  # type: ignore[arg-type]
                    common_root=root,
                    persist=True,
                    provider=provider,
                    archive_file=archive_file,
                    receipt_file=receipt_file,
                )
            self.assertEqual(ledger.claims, 0)

    def test_gate2_real_reuses_gate1_prefix_validation_before_executor(self) -> None:
        root = _common_root()
        runtime, identity_fields = self._identity()
        contract = load_nondegradation_contract()
        with tempfile.TemporaryDirectory(
            prefix="m5-gate2-gate1-prefix-", dir=scratch_root(root)
        ) as raw:
            directory = Path(raw)
            archive_file = directory / "records.jsonl"
            receipt_file = directory / "identity.json"
            ensure_formal_receipt(receipt_file, identity_fields)
            row = self._gate1_record(runtime, identity_fields, attempt=2)
            persist_archive_record(row, common_root=root, path=archive_file)
            with open_phase_b_ledger(directory / "ledger.json") as ledger:
                ledger.claim_run(
                    "m5-g1-v6-paid-a2", cap_usd=gate1_run_cap_usd(contract)
                )
                with patch.object(
                    rondo_eval.multi_m5.gate2,
                    "TerminalBenchSlotExecutor",
                    side_effect=AssertionError("executor must not start"),
                ), self.assertRaisesRegex(Gate2Error, "contiguous prefix"):
                    run_gate2_real(
                        authorization=PaidAuthorization(real_api=True, docker=True),
                        api_key="sk-test-never-spend",
                        ledger=ledger,
                        common_root=root,
                        counter=object(),  # type: ignore[arg-type]
                        lock_guard=object(),  # type: ignore[arg-type]
                        lease=object(),  # type: ignore[arg-type]
                        archive_file=archive_file,
                        receipt_file=receipt_file,
                    )

    def test_completed_archive_is_skipped_without_reexecution(self) -> None:
        root = _common_root()
        runtime, identity_fields = self._identity()
        with tempfile.TemporaryDirectory(
            prefix="m5-resume-complete-", dir=scratch_root(root)
        ) as raw:
            directory = Path(raw)
            archive_file = directory / "records.jsonl"
            ledger_file = directory / "ledger.json"
            executor = self._Executor()
            with open_phase_b_ledger(ledger_file) as ledger:
                first = run_light_interleaved(
                    executor=executor,
                    common_root=root,
                    ledger=ledger,
                    persist=True,
                    archive_file=archive_file,
                    identity=runtime,
                    evidence_kind="real_api",
                    resume_fields=identity_fields,
                )
                call_count = len(executor.calls)
                second = run_light_interleaved(
                    executor=executor,
                    common_root=root,
                    ledger=ledger,
                    persist=True,
                    archive_file=archive_file,
                    identity=runtime,
                    evidence_kind="real_api",
                    resume_fields=identity_fields,
                )
            self.assertEqual(call_count, 20)
            self.assertEqual(len(executor.calls), call_count)
            self.assertEqual(first["effective_runs"], 20)
            self.assertEqual(second["effective_runs"], 20)
            self.assertEqual(len(load_archive_records(archive_file)), 20)

    def test_pristine_claim_is_reused_with_the_same_run_id(self) -> None:
        root = _common_root()
        runtime, identity_fields = self._identity()
        contract = load_nondegradation_contract()
        first_slot = base_slots(contract)[0]
        first_run = _run_id(first_slot, 1)
        with tempfile.TemporaryDirectory(
            prefix="m5-resume-pristine-", dir=scratch_root(root)
        ) as raw:
            directory = Path(raw)
            executor = self._Executor()
            with open_phase_b_ledger(directory / "ledger.json") as ledger:
                ledger.claim_run(first_run, cap_usd=gate2_run_cap_usd(contract))
                result = run_light_interleaved(
                    executor=executor,
                    common_root=root,
                    ledger=ledger,
                    persist=True,
                    archive_file=directory / "records.jsonl",
                    identity=runtime,
                    evidence_kind="real_api",
                    resume_fields=identity_fields,
                )
                snapshot = ledger.snapshot()
            self.assertEqual(executor.calls[0], first_run)
            self.assertEqual(result["effective_runs"], 20)
            self.assertEqual(snapshot["run_slots_used"], 20)

    def test_requested_unarchived_run_is_abandoned_once(self) -> None:
        root = _common_root()
        runtime, identity_fields = self._identity()
        contract = load_nondegradation_contract()
        first_slot = base_slots(contract)[0]
        first_run = _run_id(first_slot, 1)
        with tempfile.TemporaryDirectory(
            prefix="m5-resume-abandoned-", dir=scratch_root(root)
        ) as raw:
            directory = Path(raw)
            archive_file = directory / "records.jsonl"
            ledger_file = directory / "ledger.json"
            executor = self._Executor()
            # Simulate process death after bytes could have left but before
            # settlement/archive. Reopening the ledger must first conservatively
            # settle the reservation, then resume records one abandonment.
            with open_phase_b_ledger(ledger_file) as ledger:
                ledger.claim_run(first_run, cap_usd=gate2_run_cap_usd(contract))
                ledger.reserve(first_run, "req-1", Decimal("0.01"))
                ledger.begin_attempt(first_run, "req-1", max_attempts=5)
            with open_phase_b_ledger(ledger_file) as ledger:
                recovered = ledger.snapshot()["runs"][first_run]
                self.assertEqual(recovered["requests"]["req-1"]["status"], "settled")
                self.assertEqual(recovered["stop_reason"], "interrupted_request")
                first = run_light_interleaved(
                    executor=executor,
                    common_root=root,
                    ledger=ledger,
                    persist=True,
                    archive_file=archive_file,
                    identity=runtime,
                    evidence_kind="real_api",
                    resume_fields=identity_fields,
                )
                call_count = len(executor.calls)
                second = run_light_interleaved(
                    executor=executor,
                    common_root=root,
                    ledger=ledger,
                    persist=True,
                    archive_file=archive_file,
                    identity=runtime,
                    evidence_kind="real_api",
                    resume_fields=identity_fields,
                )
            rows = load_archive_records(archive_file)
            abandoned = [row for row in rows if row.get("abandoned") is True]
            self.assertEqual(len(abandoned), 1)
            self.assertEqual(abandoned[0]["budget_run_id"], first_run)
            self.assertEqual(abandoned[0]["outcome"], "infra_failed")
            self.assertEqual(first["infra_used"], 1)
            self.assertEqual(second["infra_used"], 1)
            self.assertEqual(len(executor.calls), call_count)
            self.assertIn(_run_id(first_slot, 2), executor.calls)

    def test_infra_is_durable_before_the_next_requested_attempt(self) -> None:
        root = _common_root()
        runtime, identity_fields = self._identity()
        contract = load_nondegradation_contract()
        first_slot = base_slots(contract)[0]

        class CrashDuringSecondAttempt(TerminalBenchSlotExecutor):
            def __init__(self, ledger) -> None:
                self.ledger = ledger

            def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
                del slot
                if attempt == 1:
                    return SlotResult(outcome="infra_failed", request_count=0)
                self.ledger.reserve(run_id, "req-interrupted", Decimal("0.01"))
                self.ledger.begin_attempt(run_id, "req-interrupted", max_attempts=5)
                raise KeyboardInterrupt

        with tempfile.TemporaryDirectory(
            prefix="m5-resume-between-attempts-", dir=scratch_root(root)
        ) as raw:
            directory = Path(raw)
            archive_file = directory / "records.jsonl"
            ledger_file = directory / "ledger.json"
            with open_phase_b_ledger(ledger_file) as ledger:
                with self.assertRaises(KeyboardInterrupt):
                    run_light_interleaved(
                        executor=CrashDuringSecondAttempt(ledger),
                        common_root=root,
                        ledger=ledger,
                        persist=True,
                        archive_file=archive_file,
                        identity=runtime,
                        evidence_kind="real_api",
                        resume_fields=identity_fields,
                    )
            first_rows = load_archive_records(archive_file)
            self.assertEqual(len(first_rows), 1)
            self.assertEqual(first_rows[0]["budget_run_id"], _run_id(first_slot, 1))
            self.assertEqual(first_rows[0]["outcome"], "infra_failed")

            executor = self._Executor()
            with open_phase_b_ledger(ledger_file) as ledger:
                recovered = ledger.snapshot()["runs"][_run_id(first_slot, 2)]
                self.assertEqual(recovered["stop_reason"], "interrupted_request")
                result = run_light_interleaved(
                    executor=executor,
                    common_root=root,
                    ledger=ledger,
                    persist=True,
                    archive_file=archive_file,
                    identity=runtime,
                    evidence_kind="real_api",
                    resume_fields=identity_fields,
                )
            rows = load_archive_records(archive_file)
            abandoned = [row for row in rows if row.get("abandoned") is True]
            self.assertEqual(len(abandoned), 1)
            self.assertEqual(abandoned[0]["budget_run_id"], _run_id(first_slot, 2))
            self.assertIn(_run_id(first_slot, 3), executor.calls)
            self.assertEqual(result["infra_used"], 2)

    def test_future_attempt_archive_fails_closed(self) -> None:
        root = _common_root()
        runtime, identity_fields = self._identity()
        contract = load_nondegradation_contract()
        slot = base_slots(contract)[0]
        run_id = _run_id(slot, 2)
        with tempfile.TemporaryDirectory(
            prefix="m5-resume-future-", dir=scratch_root(root)
        ) as raw:
            directory = Path(raw)
            archive_file = directory / "records.jsonl"
            with open_phase_b_ledger(directory / "ledger.json") as ledger:
                ledger.claim_run(run_id, cap_usd=gate2_run_cap_usd(contract))
                row = _record_for(
                    slot,
                    runtime,
                    outcome="infra_failed",
                    counts_as_effective=False,
                    contract=contract,
                    evidence_kind="real_api",
                    extra={
                        **identity_fields,
                        "budget_run_id": run_id,
                        "attempt": 2,
                    },
                )
                persist_archive_record(row, common_root=root, path=archive_file)
                with self.assertRaisesRegex(Gate2Error, "contiguous prefix"):
                    run_light_interleaved(
                        executor=self._Executor(),
                        common_root=root,
                        ledger=ledger,
                        persist=True,
                        archive_file=archive_file,
                        identity=runtime,
                        evidence_kind="real_api",
                        resume_fields=identity_fields,
                    )

    def test_future_unarchived_claim_fails_before_execution(self) -> None:
        root = _common_root()
        runtime, identity_fields = self._identity()
        contract = load_nondegradation_contract()
        future = _run_id(base_slots(contract)[0], 2)
        executor = self._Executor()
        with tempfile.TemporaryDirectory(
            prefix="m5-resume-future-claim-", dir=scratch_root(root)
        ) as raw:
            directory = Path(raw)
            with open_phase_b_ledger(directory / "ledger.json") as ledger:
                ledger.claim_run(future, cap_usd=gate2_run_cap_usd(contract))
                with self.assertRaisesRegex(Gate2Error, "future or conflicting"):
                    run_light_interleaved(
                        executor=executor,
                        common_root=root,
                        ledger=ledger,
                        persist=True,
                        archive_file=directory / "records.jsonl",
                        identity=runtime,
                        evidence_kind="real_api",
                        resume_fields=identity_fields,
                    )
        self.assertEqual(executor.calls, [])

    def test_gate1_resume_skips_product_failure_and_abandons_once(self) -> None:
        root = _common_root()
        runtime, identity_fields = self._identity()
        workflow = load_workflow_contract()
        contract = load_nondegradation_contract()
        provider = load_runtime_config(
            RepoPaths.discover(Path.cwd())
        ).paid_provider_projection(model_id=workflow.root_model)
        pricing = phase_b_pricing(contract)
        with tempfile.TemporaryDirectory(
            prefix="m5-gate1-resume-", dir=scratch_root(root)
        ) as raw:
            directory = Path(raw)
            archive_file = directory / "records.jsonl"
            receipt_file = directory / "identity.json"
            ensure_formal_receipt(receipt_file, identity_fields)
            capture_base = directory / "captures"
            capture_base.mkdir()
            calls: list[str] = []
            with open_phase_b_ledger(directory / "ledger.json") as ledger:
                first_id = "m5-g1-v6-paid-a1"
                ledger.claim_run(first_id, cap_usd=gate1_run_cap_usd(contract))
                ledger.reserve(first_id, "req-a1", Decimal("0.01"))
                ledger.begin_attempt(first_id, "req-a1", max_attempts=5)
                ledger.settle(first_id, "req-a1", Usage(1, 0, 0, 0), pricing=pricing)
                first_row = archive_record(
                    evidence_kind="real_api",
                    gate=1,
                    lock_id=workflow.lock_id,
                    side=Side.RONDO,
                    product=Product.RONDO_MULTI,
                    source_commit=runtime.source_commit,
                    binary_sha256=str(runtime.codex_sha256),
                    outcome="agent_failed",
                    counts_as_effective=False,
                    subagent_model=workflow.member_model,
                    subagent_effort=str(workflow.raw["member_effort"]),
                    extra={
                        **identity_fields,
                        "budget_run_id": first_id,
                        "attempt": 1,
                        "ignored_evidence": [],
                        "passed": False,
                    },
                )
                persist_archive_record(first_row, common_root=root, path=archive_file)

                second_id = "m5-g1-v6-paid-a2"
                ledger.claim_run(second_id, cap_usd=gate1_run_cap_usd(contract))
                ledger.reserve(second_id, "req-a2", Decimal("0.01"))
                ledger.begin_attempt(second_id, "req-a2", max_attempts=5)
                ledger.settle(second_id, "req-a2", Usage(1, 0, 0, 0), pricing=pricing)

                def complete_third(**kwargs):
                    run_id = str(kwargs["run_id"])
                    calls.append(run_id)
                    row = archive_record(
                        evidence_kind="real_api",
                        gate=1,
                        lock_id=workflow.lock_id,
                        side=Side.RONDO,
                        product=Product.RONDO_MULTI,
                        source_commit=runtime.source_commit,
                        binary_sha256=str(runtime.codex_sha256),
                        outcome="completed",
                        counts_as_effective=False,
                        subagent_model=workflow.member_model,
                        subagent_effort=str(workflow.raw["member_effort"]),
                        extra={
                            **identity_fields,
                            "budget_run_id": run_id,
                            "attempt": 3,
                            "ignored_evidence": [],
                            "passed": True,
                        },
                    )
                    persist_archive_record(row, common_root=root, path=archive_file)
                    return {"record": row}

                with patch.object(
                    rondo_eval.multi_m5.gate1,
                    "_run_gate1_once",
                    side_effect=complete_third,
                ), patch.object(
                    rondo_eval.multi_m5.gate1,
                    "_capture_root",
                    side_effect=lambda _root, run_id, **_kwargs: capture_base / run_id,
                ):
                    first = run_gate1_paid(
                        authorization=PaidAuthorization(real_api=True, docker=False),
                        api_key="sk-test-never-spend",
                        upstream_base_url=provider.base_url,
                        ledger=ledger,
                        common_root=root,
                        persist=True,
                        provider=provider,
                        archive_file=archive_file,
                        receipt_file=receipt_file,
                    )
                    second = run_gate1_paid(
                        authorization=PaidAuthorization(real_api=True, docker=False),
                        api_key="sk-test-never-spend",
                        upstream_base_url=provider.base_url,
                        ledger=ledger,
                        common_root=root,
                        persist=True,
                        provider=provider,
                        archive_file=archive_file,
                        receipt_file=receipt_file,
                    )
            rows = load_archive_records(archive_file)
            self.assertEqual(calls, ["m5-g1-v6-paid-a3"])
            self.assertEqual(first["record"]["outcome"], "completed")
            self.assertEqual(second["record"]["outcome"], "completed")
            self.assertEqual(sum(row.get("abandoned") is True for row in rows), 1)
            self.assertEqual(rows[0]["outcome"], "agent_failed")


class MultiM5PaidBoundaryTests(unittest.TestCase):
    """Stop lines and verdict reporting that only bite once money is moving."""

    def test_gate2_success_status_requires_a_clean_complete_verdict(self) -> None:
        # Reporting success off `stopped` alone exits 0 on a batch that found
        # degradation, or on one whose evidence never completed.
        contract = load_nondegradation_contract()
        clean = {task: "no_stable_one_way_degradation" for task in contract.tasks}
        self.assertTrue(gate2_passed(contract, clean, stopped=False))
        self.assertFalse(gate2_passed(contract, clean, stopped=True))
        degraded = dict(clean)
        degraded[contract.tasks[0]] = "stable_one_way_degradation"
        self.assertFalse(gate2_passed(contract, degraded, stopped=False))
        unsure = dict(clean)
        unsure[contract.tasks[3]] = "uncertain"
        self.assertFalse(gate2_passed(contract, unsure, stopped=False))
        short = {task: "no_stable_one_way_degradation" for task in contract.tasks[:9]}
        self.assertFalse(gate2_passed(contract, short, stopped=False))

    def test_degraded_batch_leaves_the_cli_with_a_failure_status(self) -> None:
        root = _common_root()
        contract = load_nondegradation_contract()
        # Codex completes, Multi does not, on every round of one task.
        script = {
            (contract.tasks[0], Side.RONDO.value, index): ("agent_failed",)
            for index in (1, 2, 3)
        }
        result = run_light_interleaved(
            executor=ScriptedSlotExecutor(script),
            common_root=root,
            persist=False,
        )
        self.assertEqual(
            result["verdicts"][contract.tasks[0]], "stable_one_way_degradation"
        )
        self.assertFalse(result["stopped"])
        # The old exit rule keyed on `stopped` and would have reported success.
        self.assertFalse(result["passed"])

    def test_request_cap_stops_before_the_next_request_leaves(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-request-cap.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        pricing = phase_b_pricing()
        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                ledger.ensure_run("m5-g2-cap-probe", cap_usd=gate2_run_cap_usd())
                capped = RequestCappedLedger(ledger, max_requests_per_run=3)
                for index in range(3):
                    request_id = f"m5-g2-cap-probe-req-{index}"
                    capped.reserve("m5-g2-cap-probe", request_id, Decimal("0.01"))
                    capped.begin_attempt("m5-g2-cap-probe", request_id, max_attempts=5)
                    capped.settle(
                        "m5-g2-cap-probe", request_id, Usage(1, 0, 0, 0), pricing=pricing
                    )
                # A retry of a counted request id is still allowed.
                with self.assertRaises(BudgetStopped):
                    capped.reserve("m5-g2-cap-probe", "m5-g2-cap-probe-req-3", Decimal("0.01"))
                self.assertEqual(
                    run_stop_reason(ledger, "m5-g2-cap-probe"),
                    REQUEST_LIMIT_STOP_REASON,
                )
                self.assertEqual(run_request_count(ledger, "m5-g2-cap-probe"), 3)
        finally:
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()

    def test_request_cap_ends_the_slot_but_not_the_batch(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-cap-slot.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        contract = load_nondegradation_contract()
        first_task = contract.base_order[0]["task_id"]

        class _CapsFirstSlot:
            def __init__(self) -> None:
                self.ledger = None
                self.capped: list[str] = []

            def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
                if slot.task_id == first_task and slot.side is Side.CODEX:
                    # In-band: the proxy answered 429 and the agent gave up.
                    self.capped.append(run_id)
                    self.ledger.stop_run(run_id, stop_reason=REQUEST_LIMIT_STOP_REASON)
                    return SlotResult(outcome="agent_failed", extra={"executor": "probe"})
                return SlotResult(outcome="completed", extra={"executor": "probe"})

        executor = _CapsFirstSlot()
        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                executor.ledger = ledger
                result = run_light_interleaved(
                    executor=executor,
                    common_root=root,
                    ledger=ledger,
                    persist=False,
                )
        finally:
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()
        capped_rows = [
            row for row in result["records"]
            if row.get("stop_reason") == REQUEST_LIMIT_STOP_REASON
        ]
        self.assertTrue(capped_rows)
        # Per-run cap: infra, not a shared-dollar batch stop, and never effective.
        self.assertTrue(all(row["outcome"] == "infra_failed" for row in capped_rows))
        self.assertTrue(all(row["counts_as_effective"] is False for row in capped_rows))
        self.assertEqual(len(executor.capped), contract.max_slot_attempts)
        # The batch kept walking the other nine tasks.
        self.assertGreater(result["effective_runs"], 2)

    def test_docker_resource_stop_aborts_instead_of_retrying(self) -> None:
        root = _common_root()

        class _OutOfSpace:
            def __init__(self) -> None:
                self.calls = 0

            def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
                del slot, attempt, run_id
                self.calls += 1
                raise DockerResourceStop(
                    "Docker data-root filesystem has less than 80 GiB free"
                )

        executor = _OutOfSpace()
        result = run_light_interleaved(
            executor=executor,
            common_root=root,
            persist=False,
        )
        # A capacity stop line must not consume slot retries.
        self.assertEqual(executor.calls, 1)
        self.assertTrue(result["stopped"])
        self.assertEqual(result["stop_reason"], "docker_resource_stop")
        self.assertFalse(result["passed"])
        self.assertTrue(
            all(row["counts_as_effective"] is False for row in result["records"])
        )

    def test_frozen_provider_binding_rejects_config_drift(self) -> None:
        contract = load_nondegradation_contract()
        projection = load_runtime_config(
            RepoPaths.discover(Path.cwd())
        ).paid_provider_projection(model_id=contract.root_model)
        identity = require_frozen_provider(
            projection, effort=contract.root_effort, contract=contract
        )
        self.assertEqual(identity["provider_id"], contract.provider)
        self.assertEqual(identity["frozen_price_snapshot_date"], contract.price_date)
        # The proxy meters the $120 batch with these rates, so a cheaper-looking
        # config must not silently change what the approved cap buys.
        cheap = replace(
            projection,
            main_pricing=replace(
                projection.main_pricing, input_usd_per_million=Decimal("1")
            ),
        )
        with self.assertRaisesRegex(M5ContractError, "input_usd_per_million"):
            require_frozen_provider(cheap, effort=contract.root_effort, contract=contract)
        with self.assertRaisesRegex(M5ContractError, "main_effort"):
            require_frozen_provider(projection, effort="high", contract=contract)
        with self.assertRaisesRegex(M5ContractError, "provider_id"):
            require_frozen_provider(
                replace(projection, provider_id="openai_official"),
                effort=contract.root_effort,
                contract=contract,
            )
        with self.assertRaisesRegex(M5ContractError, "provider_max_attempts"):
            require_frozen_provider(
                replace(projection, max_attempts=2),
                effort=contract.root_effort,
                contract=contract,
            )

    def test_docker_evidence_and_identity_reach_the_slot_row(self) -> None:
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-docker-eviu.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                executor = TerminalBenchSlotExecutor(
                    common_root=root,
                    ledger=ledger,
                    catalog=_v4_catalog(),
                    paths=RepoPaths.discover(Path.cwd()),
                )
                ledger.ensure_run("m5-g2-evidence", cap_usd=gate2_run_cap_usd())
                result = executor._slot_result(
                    _FakeTrial(),
                    "m5-g2-evidence",
                    docker_evidence=_FakeDockerEvidence(),
                )
        finally:
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()
        evidence = result.extra["docker_evidence"]
        # The authorization asked for before/after df, host free space and the
        # 40/60 GB thresholds to be persisted, not just checked in flight.
        self.assertEqual([item["phase"] for item in evidence["samples"]], ["pre", "post"])
        self.assertEqual(evidence["warnings"], ["Docker storage growth reached the 40 GB warning threshold"])
        self.assertEqual(evidence["growth_stop_bytes"], DOCKER_GROWTH_STOP_BYTES)
        self.assertEqual(evidence["data_root_free_stop_bytes"], DATA_ROOT_FREE_STOP_BYTES)
        self.assertEqual(evidence["desktop_vhdx"]["peak_growth_bytes"], 7)
        self.assertIn(
            evidence["samples"][1]["data_root_filesystem_free_bytes"], (10**12,)
        )
        self.assertIn("harness_commit", result.extra)

    def test_gate1_cannot_pass_on_a_crashed_run(self) -> None:
        root = _common_root()
        try:
            load_runtime_identity(require_frozen=True, common_root=root)
        except M5ContractError as exc:
            self.skipTest(f"frozen Multi bundle is unavailable: {exc}")
        original = subprocess.run

        def crash_after_protocol(command, **kwargs):
            done = original(command, **kwargs)
            return subprocess.CompletedProcess(
                args=done.args, returncode=3, stdout=done.stdout, stderr=done.stderr
            )

        result = run_gate1_rehearsal(
            common_root=root,
            persist=False,
            process_runner=crash_after_protocol,
            capture_base=_isolated_capture_base(self),
        )
        record = result["record"]
        # Every predicate is green; the run still crashed, so it is not a pass.
        self.assertTrue(all(result["verdict"].predicates.values()))
        self.assertEqual(record["returncode"], 3)
        self.assertFalse(record["passed"])
        self.assertEqual(record["outcome"], "agent_failed")
        self.assertIn("nonzero exit rc=3", record["reasons"])

    def test_unreadable_member_delivery_cannot_pass_a_complete_protocol(self) -> None:
        root = _common_root()
        for status in ("encrypted", "unknown"):
            with self.subTest(status=status), patch.object(
                rondo_eval.multi_m5.gate1,
                "member_message_delivery",
                return_value={
                    "status": status,
                    "plaintext_parts": 1,
                    "encrypted_parts": int(status == "encrypted"),
                    "unknown_parts": int(status == "unknown"),
                },
            ):
                result = run_gate1_rehearsal(
                    common_root=root,
                    persist=False,
                    capture_base=_isolated_capture_base(self),
                    run_id=f"m5-g1-delivery-{status}",
                )
            self.assertTrue(all(result["verdict"].predicates.values()))
            record = result["record"]
            self.assertEqual(record["outcome"], "infra_failed")
            self.assertFalse(record["passed"])
            self.assertEqual(
                record["reasons"],
                [f"evidence:member_message_delivery:{status}"],
            )


class _SlowSnapshotLedger:
    """Delegating ledger whose `snapshot` is slow, to open the check/act window."""

    def __init__(self, ledger, *, delay_seconds: float) -> None:
        self._ledger = ledger
        self._delay = delay_seconds

    def __getattr__(self, name: str):
        return getattr(self._ledger, name)

    def snapshot(self):
        value = self._ledger.snapshot()
        time.sleep(self._delay)
        return value


class MultiM5ConcurrencyAndEndpointTests(unittest.TestCase):
    """The proxy is threaded and the endpoint decides where the key goes."""

    def test_request_cap_holds_under_concurrent_reservations(self) -> None:
        # The proxy serves on a threading HTTP server and Multi's Root and
        # members call concurrently. Reading the count and then reserving lets
        # two requests at the cap boundary both pass and land one over.
        root = _common_root()
        scratch = scratch_root(root)
        ledger_path = scratch / "multi-m5-test-cap-race.json"
        lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
        for item in (ledger_path, lock_path):
            if item.exists():
                item.unlink()
        cap = 8
        pricing = phase_b_pricing()
        run_id = "m5-g2-race-probe"
        errors: list[BaseException] = []
        try:
            with open_phase_b_ledger(ledger_path) as ledger:
                ledger.ensure_run(run_id, cap_usd=gate2_run_cap_usd())
                capped = RequestCappedLedger(ledger, max_requests_per_run=cap)
                # Fill to exactly one below the cap.
                for index in range(cap - 1):
                    request_id = f"{run_id}-warm-{index}"
                    capped.reserve(run_id, request_id, Decimal("0.01"))
                    capped.begin_attempt(run_id, request_id, max_attempts=5)
                    capped.settle(run_id, request_id, Usage(1, 0, 0, 0), pricing=pricing)
                self.assertEqual(run_request_count(ledger, run_id), cap - 1)

                # Widen the count-then-reserve window deterministically. Without
                # one critical section every racer reads `cap - 1` during this
                # sleep and then all of them reserve.
                capped._ledger = _SlowSnapshotLedger(ledger, delay_seconds=0.05)

                def racer(index: int) -> None:
                    request_id = f"{run_id}-race-{index}"
                    try:
                        capped.reserve(run_id, request_id, Decimal("0.01"))
                    except BudgetStopped:
                        return
                    except BaseException as exc:  # noqa: BLE001 - surfaced below
                        errors.append(exc)

                threads = [
                    threading.Thread(target=racer, args=(index,), daemon=True)
                    for index in range(6)
                ]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=30)
                    self.assertFalse(thread.is_alive())
                capped._ledger = ledger
                final = run_request_count(ledger, run_id)
                stop = run_stop_reason(ledger, run_id)
        finally:
            for item in (ledger_path, lock_path):
                if item.exists():
                    item.unlink()
        self.assertEqual(errors, [])
        # Exactly one racer may win the last slot; the cap is never exceeded.
        self.assertEqual(final, cap)
        self.assertEqual(stop, REQUEST_LIMIT_STOP_REASON)

    def test_frozen_provider_binding_pins_the_endpoint(self) -> None:
        contract = load_nondegradation_contract()
        projection = load_runtime_config(
            RepoPaths.discover(Path.cwd())
        ).paid_provider_projection(model_id=contract.root_model)
        identity = require_frozen_provider(
            projection, effort=contract.root_effort, contract=contract
        )
        self.assertEqual(
            identity["provider_base_url"].rstrip("/"),
            str(contract.raw["provider_base_url"]).rstrip("/"),
        )
        # Same provider name, different destination for the key and the data.
        moved = replace(projection, base_url="https://different-provider.example/v1")
        with self.assertRaisesRegex(M5ContractError, "provider_base_url"):
            require_frozen_provider(moved, effort=contract.root_effort, contract=contract)

    def test_gate1_refuses_an_upstream_that_is_not_the_frozen_endpoint(self) -> None:
        projection = load_runtime_config(
            RepoPaths.discover(Path.cwd())
        ).paid_provider_projection(model_id=load_workflow_contract().root_model)
        with self.assertRaisesRegex(Gate1Error, "frozen provider endpoint"):
            run_gate1_paid(
                authorization=PaidAuthorization(real_api=True, docker=False),
                api_key="sk-test-never-spend",
                upstream_base_url="https://different-provider.example/v1",
                ledger=object(),  # never reached
                provider=projection,
            )

    def test_capacity_stop_archives_the_samples_it_carried(self) -> None:
        root = _common_root()
        stop = DockerResourceStop(
            "Docker data-root filesystem has less than 80 GiB free",
            samples=(_FakeSample("pre", 10, 0, 0, 1, 0, "/var/lib/docker", 1024),),
            failed_probe="data_root_free",
        )

        class _OutOfSpace:
            def execute(self, slot, *, attempt: int, run_id: str) -> SlotResult:
                del slot, attempt, run_id
                raise stop

        result = run_light_interleaved(
            executor=_OutOfSpace(), common_root=root, persist=False
        )
        row = result["records"][-1]
        evidence = row["docker_evidence"]
        # The readings matter most exactly when a stop line is crossed.
        self.assertEqual([item["phase"] for item in evidence["samples"]], ["pre"])
        self.assertEqual(evidence["samples"][0]["data_root_filesystem_free_bytes"], 1024)
        self.assertEqual(evidence["failed_probe"], "data_root_free")
        self.assertEqual(evidence["data_root_free_stop_bytes"], DATA_ROOT_FREE_STOP_BYTES)

    def test_docker_image_identity_is_read_from_the_real_field(self) -> None:
        reference = "alexgshaw/fix-git@sha256:" + "d" * 64
        identity = DockerImageIdentity(image_reference=reference, image_id="sha256:" + "e" * 64)

        class _WithIdentity(_FakeDockerEvidence):
            image_identity = identity

        summary = docker_summary(_WithIdentity())
        # `reference` is not a field on DockerImageIdentity; it recorded null.
        self.assertEqual(summary["image_reference"], reference)
        self.assertEqual(summary["image_id"], identity.image_id)


@dataclass(frozen=True)
class _FakeSample:
    phase: str
    docker_total_bytes: int
    docker_growth_bytes: int
    task_growth_bytes: int
    docker_desktop_vhdx_bytes: int
    docker_desktop_vhdx_growth_bytes: int
    data_root: str
    data_root_filesystem_free_bytes: int


@dataclass(frozen=True)
class _FakeVhdx:
    baseline_bytes: int = 1
    peak_bytes: int = 8
    final_bytes: int = 2
    peak_growth_bytes: int = 7


class _FakeDockerEvidence:
    returncode = 0
    warnings = ("Docker storage growth reached the 40 GB warning threshold",)
    desktop_vhdx = _FakeVhdx()
    image_identity = None
    samples = (
        _FakeSample("pre", 10, 0, 0, 1, 0, "/var/lib/docker", 10**12),
        _FakeSample("post", 20, 10, 5, 8, 7, "/var/lib/docker", 10**12),
    )


def _provider_base_url(command) -> str:
    for index, value in enumerate(command):
        if value == "-c" and index + 1 < len(command):
            item = command[index + 1]
            if item.startswith("model_providers.rondo_eval_provider.base_url="):
                return json.loads(item.split("=", 1)[1])
    raise AssertionError("gate 1 argv carries no provider base url")


def _post_capture(base_url: str, model: str, bearer: str) -> None:
    body = json.dumps({"model": model, "input": [], "stream": True}).encode()
    parsed = urlsplit(base_url)
    connection = HTTPConnection("127.0.0.1", int(parsed.port or 0), timeout=30)
    try:
        connection.request(
            "POST",
            "/v1/responses",
            body=body,
            headers={
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        connection.getresponse().read()
    finally:
        connection.close()


def _v4_catalog() -> FrozenCanaryCatalog:
    path = EVAL_ROOT / "tasksets" / "p2-b7-canary-catalog-v4.json"
    raw = path.read_bytes()
    value = json.loads(raw)
    tasks = tuple(FrozenTask(**item) for item in value["tasks"])
    for task in tasks:
        task.validate()
    return FrozenCanaryCatalog(
        terminal_bench_commit=value["terminal_bench_commit"],
        taskset_sha256=value["taskset_sha256"],
        tasks=tasks,
        catalog_sha256=hashlib.sha256(raw).hexdigest(),
    )


def _dummy_binary(*, product: str | None = None) -> BinaryManifest:
    suffix = product or "codex"
    manifest = BinaryManifest(
        path=f"/tmp/rondo-m5-{suffix}/codex",
        sha256="a" * 64,
        code_mode_host_path=f"/tmp/rondo-m5-{suffix}/codex-code-mode-host",
        code_mode_host_sha256="b" * 64,
        bwrap_path=f"/tmp/rondo-m5-{suffix}/bwrap",
        bwrap_sha256="c" * 64,
        bwrap_asset_url=(
            "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
            "bwrap-x86_64-unknown-linux-musl.tar.gz"
        ),
        bwrap_archive_sha256="d" * 64,
        bwrap_source_tree_sha256="e" * 64,
        source_commit="a" * 40,
        source_dirty=False,
        rust_toolchain="rustc 1.95.0",
        build_command=("guarded-build", "codex"),
        code_mode_host_build_command=("guarded-build", "codex-code-mode-host"),
        product=product,
    )
    manifest.validate()
    return manifest


class _HeaderSink:
    def __init__(self) -> None:
        self.user_agent: str | None = None
        self.originator: str | None = None
        self.writes = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def start(self) -> "_HeaderSink":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                owner.user_agent = self.headers.get("User-Agent")
                owner.originator = self.headers.get("originator")
                payload = b"event: response.completed\ndata: " + body + b"\n\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(payload[:12])
                self.wfile.flush()
                owner.writes += 1
                self.wfile.write(payload[12:])
                self.wfile.flush()
                owner.writes += 1

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None


class _UsageUpstream:
    def __init__(self) -> None:
        self.user_agent: str | None = None
        self.originator: str | None = None
        self.hits = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1/responses"

    def start(self) -> "_UsageUpstream":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                owner.hits += 1
                owner.user_agent = self.headers.get("User-Agent")
                owner.originator = self.headers.get("originator")
                response = {
                    "type": "response.completed",
                    "response": {
                        "id": "fake-response",
                        "usage": {
                            "input_tokens": 2000,
                            "input_tokens_details": {"cached_tokens": 1000},
                            "output_tokens": 100,
                        },
                    },
                }
                encoded = (
                    b"event: response.completed\n"
                    + b"data: "
                    + json.dumps(response).encode()
                    + b"\n\n"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)
                self.wfile.flush()

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None


class _HeldTerminalErrorUpstream:
    """Hold an HTTP-200 stream error until Gate 1 begins proxy shutdown."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self._condition = threading.Condition()
        self._started_count = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def endpoint(self) -> str:
        assert self._server is not None
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1/responses"

    def start(self) -> "_HeldTerminalErrorUpstream":
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                with owner._condition:
                    owner._started_count += 1
                    owner._condition.notify_all()
                owner.release.wait(timeout=5)
                response = {
                    "type": "error",
                    "error": {
                        "code": "provider_stream_error",
                        "message": "tail error must not survive in metadata",
                    },
                }
                encoded = (
                    b"event: error\n"
                    + b"data: "
                    + json.dumps(response).encode()
                    + b"\n\n"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(encoded)
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def wait_for_started(self, count: int, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._started_count < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(timeout=remaining)
            return True

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None


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


def _post(
    port: int,
    payload: dict[str, object],
    *,
    bearer: str = LOOPBACK_BEARER,
    extra_headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    connection = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        if extra_headers:
            headers.update(extra_headers)
        connection.request(
            "POST",
            "/v1/responses",
            body=body,
            headers=headers,
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
