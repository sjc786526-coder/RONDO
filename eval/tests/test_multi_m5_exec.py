from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import unittest
from decimal import Decimal
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.api_budget_proxy import (  # noqa: E402
    ApiBudgetProxyError,
    BudgetCapacityExhausted,
    LoopbackResponsesProxy,
    Usage,
    _UrllibTransport,
)
from rondo_eval.config import RepoPaths  # noqa: E402
from rondo_eval.contracts import BinaryManifest, Product, Side  # noqa: E402
from rondo_eval.multi_m5.archive import archive_record  # noqa: E402
from rondo_eval.multi_m5.budget import (  # noqa: E402
    GATE1_RUN_CAP_USD,
    GATE2_REQUEST_RESERVATION_USD,
    GATE2_RUN_CAP_USD,
    HARD_CAP_USD,
    RUN_CAP_USD,
    open_phase_b_ledger,
    phase_b_pricing,
)
from rondo_eval.multi_m5.capture import FORWARD_TIMEOUT_SECONDS, CaptureProxy  # noqa: E402
from rondo_eval.multi_m5.command import build_multi_exec_command, team_capability_overrides  # noqa: E402
from rondo_eval.multi_m5.gate1 import run_gate1_paid, run_gate1_rehearsal  # noqa: E402
from rondo_eval.multi_m5.gate2 import (  # noqa: E402
    DockerNotAuthorizedExecutor,
    Gate2Error,
    ScriptedSlotExecutor,
    SlotResult,
    TerminalBenchSlotExecutor,
    run_gate2_real,
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
from rondo_eval.multi_m5.paid import (  # noqa: E402
    PAID_API_PHRASE,
    PAID_DOCKER_PHRASE,
    PaidAuthError,
    PaidAuthorization,
    authorization_from_phrases,
)
from rondo_eval.multi_m5.ready import readiness_report  # noqa: E402
from rondo_eval.multi_m5.rehearsal import MEMBER_TASK, CollaborationStub  # noqa: E402
from rondo_eval.multi_m5.schedule import base_slots  # noqa: E402
from rondo_eval.multi_m5.store import (  # noqa: E402
    StoreError,
    load_archive_records,
    persist_archive_record,
    scratch_root,
)
from rondo_eval.terminal_bench.tasksets import FrozenCanaryCatalog, FrozenTask  # noqa: E402

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

            self.assertEqual(Decimal(ledger.snapshot()["default_run_cap_usd"]), RUN_CAP_USD)
            self.assertEqual(RUN_CAP_USD, Decimal("24.00"))
            ledger.ensure_run("m5-cap-a")
            with self.assertRaises(BudgetCapacityExhausted):
                ledger.reserve("m5-cap-a", "req-too-big", Decimal("40.00"))
            ledger.reserve("m5-cap-a", "req-a", Decimal("24.00"))
            ledger.begin_attempt("m5-cap-a", "req-a", max_attempts=5)
            ledger.settle("m5-cap-a", "req-a", None, pricing=pricing)
            ledger.ensure_run("m5-cap-b")
            ledger.reserve("m5-cap-b", "req-b", Decimal("24.00"))
            ledger.begin_attempt("m5-cap-b", "req-b", max_attempts=5)
            ledger.settle("m5-cap-b", "req-b", None, pricing=pricing)
            ledger.ensure_run("m5-cap-c")
            ledger.reserve("m5-cap-c", "req-c", Decimal("24.00"))
            ledger.begin_attempt("m5-cap-c", "req-c", max_attempts=5)
            ledger.settle("m5-cap-c", "req-c", None, pricing=pricing)
            ledger.ensure_run("m5-cap-d")
            ledger.reserve("m5-cap-d", "req-d", Decimal("24.00"))
            ledger.begin_attempt("m5-cap-d", "req-d", max_attempts=5)
            ledger.settle("m5-cap-d", "req-d", None, pricing=pricing)
            ledger.ensure_run("m5-cap-e")
            ledger.reserve("m5-cap-e", "req-e", Decimal("23.00"))
            ledger.begin_attempt("m5-cap-e", "req-e", max_attempts=5)
            ledger.settle("m5-cap-e", "req-e", None, pricing=pricing)
            remaining = Decimal(ledger.snapshot()["remaining_uncommitted_usd"])
            self.assertLess(remaining, Decimal("2.00"))
            self.assertGreater(remaining, 0)
            ledger.ensure_run("m5-cap-over")
            with self.assertRaises(BudgetCapacityExhausted):
                ledger.reserve("m5-cap-over", "req-over", Decimal("24.00"))


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


class MultiM5TerminalBenchExecutorTests(unittest.TestCase):
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
        self.assertEqual(multi_request.batch_id, "multi-m5-phase-b")
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
                Decimal(info["cap_usd"]) == GATE2_RUN_CAP_USD
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
            "request_reservation_usd": GATE2_REQUEST_RESERVATION_USD,
            "timeout_seconds": FORWARD_TIMEOUT_SECONDS,
        }
        with open_phase_b_ledger(ledger_path) as ledger:
            ledger.ensure_run(run_id, cap_usd=GATE2_RUN_CAP_USD)
            with self.assertRaisesRegex(ApiBudgetProxyError, "existing run cap"):
                LoopbackResponsesProxy(ledger=ledger, **kwargs)
            proxy = LoopbackResponsesProxy(
                ledger=ledger,
                run_cap_usd=GATE2_RUN_CAP_USD,
                **kwargs,
            )
            self.assertEqual(
                Decimal(ledger.snapshot()["runs"][run_id]["cap_usd"]),
                GATE2_RUN_CAP_USD,
            )
            del proxy
            ledger.ensure_run("m5-g1-paid-a1", cap_usd=GATE1_RUN_CAP_USD)
            gate1 = LoopbackResponsesProxy(
                ledger=ledger,
                run_id="m5-g1-paid-a1",
                metadata_path=scratch / "multi-m5-test-gate1-run-cap-meta.json",
                run_cap_usd=GATE1_RUN_CAP_USD,
                **{k: v for k, v in kwargs.items() if k not in {"run_id", "metadata_path"}},
            )
            self.assertEqual(
                Decimal(ledger.snapshot()["runs"]["m5-g1-paid-a1"]["cap_usd"]),
                GATE1_RUN_CAP_USD,
            )
            del gate1
        for item in (ledger_path, lock_path, metadata):
            if item.exists():
                item.unlink()


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
