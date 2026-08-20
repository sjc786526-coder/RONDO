from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.proactive_eval.aggregate import (  # noqa: E402
    aggregate,
    synthetic_team_view,
    write_replay_artifacts,
)
from rondo_eval.proactive_eval.campaign import (  # noqa: E402
    ExecutionResult,
    default_fake_executor,
    run_rehearsal,
)
from rondo_eval.proactive_eval.contract import ContractError, load_contract  # noqa: E402
from rondo_eval.proactive_eval.formal import (  # noqa: E402
    FormalDriftError,
    FormalError,
    FormalExecutionResult,
    FormalInfraError,
    FormalPaths,
    FormalStore,
    Plan049RequestPreflight,
    Plan049TerminalBenchExecutor,
    formal_identity,
    open_paid_ledger,
    plan049_provider_projection,
    require_safe_formal_prefix,
    run_formal_campaign,
)
from rondo_eval.proactive_eval.paid import (  # noqa: E402
    ACTIVATION_ACTION,
    LOCAL_ACTIVATION_CONFIRMATION,
    PHASE_B_AUTHORIZATION,
    PaidGuardError,
    enter_paid_phase,
    production_paid_dependencies,
)
from rondo_eval.proactive_eval.__main__ import main as proactive_main  # noqa: E402
from rondo_eval.proactive_eval.readiness import (  # noqa: E402
    ReadinessError,
    require_phase_a_evidence,
    secret_readiness,
)
from rondo_eval.proactive_eval.schedule import dry_run_projection, slots  # noqa: E402
from rondo_eval.proactive_eval.store import (  # noqa: E402
    RehearsalStore,
    StoreError,
    assert_body_free,
)
from rondo_eval.team_lens.model import dump_team_view  # noqa: E402
from rondo_eval.team_lens.report import render_report  # noqa: E402
from rondo_eval.config import RepoPaths, load_runtime_config  # noqa: E402
from rondo_eval.contracts import Side  # noqa: E402
from rondo_eval.api_budget_proxy import Usage  # noqa: E402


def _spawn_view(*, source_is_root: bool, tool_status: str) -> dict:
    view = synthetic_team_view(side="rondo", run_id="spawn-check", ordinal=1)
    root = view["source"]["root_thread_id"]
    child = "spawn-check-child"
    view["agents"].append(
        {
            "agent_id": child,
            "agent_path": "/root/child",
            "parent_agent_id": root,
            "role": "spawned",
            "started_seq": 2,
            "started_at_unix_ms": 1001,
            "ended_seq": 4,
            "ended_at_unix_ms": 1003,
            "status": "completed",
        }
    )
    source = root
    target = child
    if not source_is_root:
        source = child
        target = "spawn-check-grandchild"
        view["agents"].append(
            {
                "agent_id": target,
                "agent_path": "/root/child/grandchild",
                "parent_agent_id": child,
                "role": "spawned",
                "started_seq": 3,
                "started_at_unix_ms": 1002,
                "ended_seq": 4,
                "ended_at_unix_ms": 1003,
                "status": "completed",
            }
        )
    view["tools"] = [
        {
            "tool_id": "spawn-tool",
            "agent_id": source,
            "turn_id": None,
            "name": "spawn_agent",
            "namespace": "collaboration",
            "requester": "model",
            "kind": "spawn_agent",
            "started_seq": 2,
            "started_at_unix_ms": 1001,
            "ended_seq": 3,
            "ended_at_unix_ms": 1002,
            "status": tool_status,
        }
    ]
    view["interactions"] = [
        {
            "interaction_id": "spawn-edge",
            "kind": "spawn_agent",
            "source_agent_id": source,
            "target_agent_id": target,
            "tool_id": "spawn-tool",
            "started_seq": 2,
            "started_at_unix_ms": 1001,
            "ended_seq": 3,
            "ended_at_unix_ms": 1002,
            "status": "completed",
        }
    ]
    view["summary"]["agent_count"] = len(view["agents"])
    view["summary"]["tool_count"] = 1
    view["summary"]["interaction_count"] = 1
    return view


def _aggregate_record(run_id: str) -> dict:
    return {
        "phase": "pilot",
        "pair_id": "P01",
        "slot_id": "pilot-p01-rondo",
        "run_id": run_id,
        "attempt": 1,
        "task_id": "terminal-bench/filter-js-from-html",
        "side": "rondo",
        "product": "rondo-multi",
        "outcome": "completed",
        "terminal": True,
        "counts_as_effective": True,
        "trace_status": "available",
        "reason_code": None,
    }


def _write_loopback_receipt(
    common_root: Path, contract, *, namespace: str
) -> None:
    root = common_root / "eval-data/plan-049/loopback" / namespace
    side_rows = {}
    for ordinal, side in enumerate(("codex", "rondo"), start=1):
        side_root = root / side
        view = synthetic_team_view(side=side, run_id=f"loopback-{side}", ordinal=ordinal)
        digests = write_replay_artifacts(side_root, view)
        side_rows[side] = {
            "binary_sha256": contract.lock["runtime"][f"{side}_binary_sha256"],
            "request_count": 1,
            "policy_sha256": contract.policy_sha256,
            "policy_matched": True,
            "registered_common_tools": [
                "list_agents",
                "send_message",
                "spawn_agent",
                "wait_agent",
            ],
            "team_state": None if side == "codex" else True,
            **digests,
            "trace_bundle_count": 1,
        }
    summary = {
        "schema_version": 1,
        "evidence_kind": "loopback",
        "identity_class": "rehearsal",
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "policy_sha256": contract.policy_sha256,
        "namespace": namespace,
        "sides": side_rows,
    }
    (root / "loopback.json").write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n",
        "utf-8",
    )


class ProactiveEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract(REPO_ROOT)
        self.temporary = tempfile.TemporaryDirectory()
        self.common_root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_frozen_contract_and_dry_run_are_exact_and_rehearsal_only(self) -> None:
        schedule = slots(self.contract)
        self.assertEqual(len(schedule), 26)
        self.assertEqual(
            [(row.pair_id, row.side) for row in schedule[:6]],
            [
                ("P01", "codex"),
                ("P01", "rondo"),
                ("P02", "rondo"),
                ("P02", "codex"),
                ("P03", "codex"),
                ("P03", "rondo"),
            ],
        )
        first = dry_run_projection(
            self.contract, common_root=self.common_root, namespace="deterministic"
        )
        second = dry_run_projection(
            self.contract, common_root=self.common_root, namespace="deterministic"
        )
        self.assertEqual(first, second)
        self.assertEqual(first["identity_class"], "rehearsal")
        self.assertTrue(all(row["identity_class"] == "rehearsal" for row in first["slots"]))
        self.assertTrue(all("paid" not in row["run_id"] for row in first["slots"]))
        codex = first["side_command_contract"]["codex"]
        rondo = first["side_command_contract"]["rondo"]
        self.assertIn("max_concurrent_threads_per_session=4", codex["config_overrides"][0])
        self.assertIn("max_concurrent_threads_per_session=4", rondo["config_overrides"][0])
        self.assertNotIn("team_state_enabled", codex["config_overrides"][0])
        self.assertIn("team_state_enabled=true", rondo["config_overrides"][0])
        self.assertIsNone(codex["team_state"])

    def test_contract_digest_drift_fails_closed(self) -> None:
        copied = self.common_root / "copy"
        for relpath in (
            "eval/locks/multi-proactive-delegation-v1.json",
            "eval/locks/multi-m5-runtime-v4.json",
            "eval/tasksets/multi-proactive-delegation-v1.json",
            "eval/tasksets/p2-b7-canary-catalog-v4.json",
            "eval/templates/multi-proactive-delegation/proactive-policy-v1.md",
        ):
            target = copied / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / relpath, target)
        taskset = copied / "eval/tasksets/multi-proactive-delegation-v1.json"
        value = json.loads(taskset.read_text("utf-8"))
        value["formal_pairs"][0]["side_order"].reverse()
        taskset.write_text(json.dumps(value), "utf-8")
        with self.assertRaisesRegex(ContractError, "digest differs"):
            load_contract(copied)

    def test_team_lens_replay_is_deterministic_and_codex_team_is_null(self) -> None:
        codex = synthetic_team_view(side="codex", run_id="r1", ordinal=1)
        rondo = synthetic_team_view(side="rondo", run_id="r2", ordinal=2)
        self.assertIsNone(codex["team"])
        self.assertEqual(
            codex["availability"]["team_events_versions"]["status"],
            "not_applicable",
        )
        self.assertIsInstance(rondo["team"], dict)
        self.assertEqual(dump_team_view(codex), dump_team_view(codex))
        self.assertEqual(render_report(codex), render_report(codex))
        first = write_replay_artifacts(self.common_root / "run", codex)
        second = write_replay_artifacts(self.common_root / "run", codex)
        self.assertEqual(first, second)

    def test_activation_requires_a_successful_root_owned_spawn_tool(self) -> None:
        cases = (
            (False, "completed", False),
            (True, "failed", False),
            (True, "completed", True),
        )
        for source_is_root, tool_status, expected in cases:
            with self.subTest(source_is_root=source_is_root, tool_status=tool_status):
                view = _spawn_view(
                    source_is_root=source_is_root, tool_status=tool_status
                )
                record = _aggregate_record("spawn-check")
                result = aggregate(
                    [record],
                    {"spawn-check": view},
                    lock_id=self.contract.lock_id,
                    lock_sha256=self.contract.lock_sha256,
                    policy_sha256=self.contract.policy_sha256,
                )
                self.assertIs(result["activation_observed"], expected)
                self.assertEqual(
                    result["runs"][0]["root_spawn_accept_count"], int(expected)
                )

    def test_success_valid_failure_duplicate_execution_and_body_free_archive(self) -> None:
        first = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="success-resume",
            executor=default_fake_executor,
        )
        store = RehearsalStore(self.common_root, "success-resume")
        archive_before = store.archive_path.read_bytes()
        aggregate_before = store.aggregate_path.read_bytes()
        second = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="success-resume",
            executor=lambda _slot, _attempt: self.fail("terminal slot reran"),
        )
        self.assertEqual(first, second)
        self.assertEqual(archive_before, store.archive_path.read_bytes())
        self.assertEqual(aggregate_before, store.aggregate_path.read_bytes())
        self.assertEqual(first["run_count"], 26)
        self.assertEqual(first["valid_failure_count"], 2)
        self.assertTrue(all(row["peak_agent_concurrency"] == 1 for row in first["runs"]))
        self.assertTrue(all(row["first_spawn_offset_ms"] is None for row in first["runs"]))
        self.assertEqual(len(store.records()), 26)
        self.assertTrue(all(row["cost_usd"] == "0.00" for row in store.records()))
        drifted = dict(store.records()[0])
        drifted["outcome"] = "task_failed"
        with self.assertRaisesRegex(StoreError, "identity drifted"):
            store.append(drifted)
        with self.assertRaisesRegex(ValueError, "contract drifted"):
            run_rehearsal(
                replace(self.contract, lock_sha256="0" * 64),
                common_root=self.common_root,
                namespace="success-resume",
                executor=default_fake_executor,
            )

    def test_provider_failure_partial_pair_and_interruption_resume(self) -> None:
        failed_once = False

        def executor(slot, attempt):
            nonlocal failed_once
            if slot.slot_id == "pilot-p01-codex" and not failed_once:
                failed_once = True
                raise ConnectionError("simulated")
            return ExecutionResult("completed")

        first = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="infra-resume",
            executor=executor,
        )
        self.assertEqual(first["run_count"], 25)
        records = RehearsalStore(self.common_root, "infra-resume").records()
        self.assertEqual(sum(row["outcome"] == "infra_failed" for row in records), 1)
        second = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="infra-resume",
            executor=executor,
        )
        self.assertEqual(second["run_count"], 26)
        target = [row for row in RehearsalStore(self.common_root, "infra-resume").records() if row["slot_id"] == "pilot-p01-codex"]
        self.assertEqual([row["attempt"] for row in target], [1, 2])

    def test_partial_trace_is_valid_but_missing_trace_is_infra(self) -> None:
        def partial(slot, attempt):
            del attempt
            if slot.slot_id == "pilot-p01-codex":
                return ExecutionResult("task_failed", trace_status="partial")
            if slot.slot_id == "pilot-p01-rondo":
                return ExecutionResult(
                    "provider_failed", trace_status="missing", reason_code="simulated_network_failure"
                )
            return ExecutionResult("completed")

        result = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="trace-matrix",
            executor=partial,
        )
        self.assertEqual(result["run_count"], 25)
        records = RehearsalStore(self.common_root, "trace-matrix").records()
        self.assertTrue(any(row["terminal"] and row["trace_status"] == "partial" for row in records))
        self.assertTrue(any(not row["terminal"] and row["trace_status"] == "missing" for row in records))

    def test_report_failure_recovers_and_archive_failure_resumes_same_claim(self) -> None:
        calls = 0
        report_executions = 0

        def report_executor(_slot, _attempt):
            nonlocal report_executions
            report_executions += 1
            return ExecutionResult("completed")

        def flaky_writer(path, view):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated report failure")
            return write_replay_artifacts(path, view)

        first = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="report-recovery",
            executor=report_executor,
            artifact_writer=flaky_writer,
        )
        self.assertEqual(first["run_count"], 25)
        second = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="report-recovery",
            executor=report_executor,
        )
        self.assertEqual(second["run_count"], 26)
        self.assertEqual(report_executions, 26)

        original = RehearsalStore.append
        failed = False
        archive_executions = 0

        def archive_executor(_slot, _attempt):
            nonlocal archive_executions
            archive_executions += 1
            return ExecutionResult("completed")

        def fail_once(store, record):
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("simulated archive failure")
            return original(store, record)

        with mock.patch.object(RehearsalStore, "append", fail_once):
            with self.assertRaisesRegex(OSError, "archive failure"):
                run_rehearsal(
                    self.contract,
                    common_root=self.common_root,
                    namespace="archive-recovery",
                    executor=archive_executor,
                )
        recovered = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="archive-recovery",
            executor=archive_executor,
        )
        self.assertEqual(recovered["run_count"], 26)
        self.assertEqual(archive_executions, 26)
        first_slot = RehearsalStore(self.common_root, "archive-recovery").records()[0]
        self.assertEqual(first_slot["attempt"], 1)

        original_settle = RehearsalStore.settle
        settlement_failed = False

        def fail_settlement_once(store, slot_id, *, outcome):
            nonlocal settlement_failed
            if not settlement_failed:
                settlement_failed = True
                raise OSError("simulated settlement failure")
            return original_settle(store, slot_id, outcome=outcome)

        with mock.patch.object(RehearsalStore, "settle", fail_settlement_once):
            with self.assertRaisesRegex(OSError, "settlement failure"):
                run_rehearsal(
                    self.contract,
                    common_root=self.common_root,
                    namespace="settlement-recovery",
                    executor=lambda _slot, _attempt: ExecutionResult("completed"),
                )
        settled = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="settlement-recovery",
            executor=lambda _slot, _attempt: ExecutionResult("completed"),
        )
        self.assertEqual(settled["run_count"], 26)
        repaired = json.loads(
            RehearsalStore(self.common_root, "settlement-recovery").ledger_path.read_text("utf-8")
        )
        self.assertEqual(repaired["claims"]["pilot-p01-codex"]["status"], "settled")

    def test_body_bearing_fields_are_rejected(self) -> None:
        for key in ("prompt", "response", "reasoning", "agent_message", "stdout", "raw_trace"):
            with self.subTest(key=key), self.assertRaises(StoreError):
                assert_body_free({key: "not persisted"})
        fixture = json.loads(
            (REPO_ROOT / "eval/fixtures/multi-proactive-delegation-v1/body-free-replay-v1.json").read_text("utf-8")
        )
        assert_body_free(fixture)

    def test_ready_requires_complete_rehearsal_and_loopback_receipts(self) -> None:
        with self.assertRaisesRegex(ReadinessError, "rehearsal evidence is absent"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )
        run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="acceptance",
            executor=default_fake_executor,
        )
        with self.assertRaisesRegex(ReadinessError, "loopback summary"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )
        _write_loopback_receipt(self.common_root, self.contract, namespace="loopback")
        receipt = require_phase_a_evidence(
            self.contract,
            common_root=self.common_root,
            rehearsal_namespace="acceptance",
            loopback_namespace="loopback",
        )
        self.assertEqual(receipt["run_count"], 26)
        store = RehearsalStore(self.common_root, "acceptance")
        ledger_bytes = store.ledger_path.read_bytes()
        store.ledger_path.unlink()
        with self.assertRaisesRegex(ReadinessError, "rehearsal ledger"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )
        store.ledger_path.write_bytes(ledger_bytes)
        first = store.records()[0]
        marker = store.runs_root / first["run_id"] / "run.json"
        marker_bytes = marker.read_bytes()
        marker.unlink()
        with self.assertRaisesRegex(ReadinessError, "run publication"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )
        marker.write_bytes(marker_bytes)
        store.aggregate_path.write_text("{}\n", "utf-8")
        with self.assertRaisesRegex(ReadinessError, "aggregate"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )

    def test_paid_guard_stops_before_every_side_effect(self) -> None:
        cases = (
            {},
            {"authorization": PHASE_B_AUTHORIZATION},
            {
                "authorization": PHASE_B_AUTHORIZATION,
                "activation_action": ACTIVATION_ACTION,
                "confirmed_balance_usd": "99.99",
            },
            {
                "authorization": PHASE_B_AUTHORIZATION,
                "activation_action": ACTIVATION_ACTION,
                "confirmed_balance_usd": "100.00",
                "harness_clean": False,
            },
            {
                "authorization": PHASE_B_AUTHORIZATION,
                "activation_action": ACTIVATION_ACTION,
                "confirmed_balance_usd": "100.00",
                "activation_conditions_ready": False,
            },
            {
                "authorization": PHASE_B_AUTHORIZATION,
                "activation_action": ACTIVATION_ACTION,
                "confirmed_balance_usd": "100.00",
                "docker_resource_gate_ready": False,
            },
        )
        for overrides in cases:
            arguments = {
                "repo_root": REPO_ROOT,
                "authorization": None,
                "activation_action": None,
                "confirmed_balance_usd": None,
                "harness_clean": True,
                "resume_prefix_safe": True,
                "activation_conditions_ready": True,
                "docker_resource_gate_ready": True,
                "phase_a_evidence_ready": True,
                "independent_review_passed": True,
                **overrides,
            }
            with self.assertRaises(PaidGuardError):
                enter_paid_phase(**arguments)

        accepted = enter_paid_phase(
            repo_root=REPO_ROOT,
            authorization=PHASE_B_AUTHORIZATION,
            activation_action=ACTIVATION_ACTION,
            confirmed_balance_usd="100.00",
            harness_clean=True,
            resume_prefix_safe=True,
            activation_conditions_ready=True,
            docker_resource_gate_ready=True,
            phase_a_evidence_ready=True,
            independent_review_passed=True,
        )
        self.assertEqual(accepted.lock_id, self.contract.lock_id)

    def test_paid_guard_requires_phase_a_evidence_and_independent_review(self) -> None:
        base = {
            "repo_root": REPO_ROOT,
            "authorization": PHASE_B_AUTHORIZATION,
            "activation_action": ACTIVATION_ACTION,
            "confirmed_balance_usd": "100.00",
            "harness_clean": True,
            "resume_prefix_safe": True,
            "activation_conditions_ready": True,
            "docker_resource_gate_ready": True,
            "phase_a_evidence_ready": True,
            "independent_review_passed": True,
        }
        for key in ("phase_a_evidence_ready", "independent_review_passed"):
            with self.subTest(key=key), self.assertRaises(PaidGuardError):
                enter_paid_phase(**{**base, key: False})

    def test_formal_budget_preflight_and_publication_resume_are_idempotent(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="a" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/test-fixture"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        executions = 0

        class Executor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, attempt
                nonlocal executions
                executions += 1
                view = synthetic_team_view(
                    side=slot.side, run_id=run_id, ordinal=slot.ordinal
                )
                digests = write_replay_artifacts(run_root, view)
                return FormalExecutionResult(
                    outcome="completed",
                    trace_status="available",
                    request_preflight_sha256="b" * 64,
                    **digests,
                )

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            original = store.publish
            failed = False

            def fail_once(record):
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError("simulated formal publication failure")
                return original(record)

            with mock.patch.object(store, "publish", fail_once):
                with self.assertRaisesRegex(OSError, "publication failure"):
                    run_formal_campaign(
                        self.contract,
                        store=store,
                        ledger=ledger,
                        executor=Executor(),
                        phase="pilot",
                    )
            result = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=Executor(),
                phase="pilot",
            )
            again = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=Executor(),
                phase="pilot",
            )
        self.assertEqual(executions, 6)
        self.assertEqual(result, again)
        self.assertEqual(result["run_count"], 6)
        self.assertEqual(len(store.records()), 6)
        require_safe_formal_prefix(paths, identity, self.contract)

        preflight = Plan049RequestPreflight(
            contract=self.contract,
            side=Side.CODEX,
            task_id="terminal-bench/filter-js-from-html",
        )
        request = {
            "model": "gpt-5.6-terra",
            "reasoning": {"effort": "medium"},
            "instructions": self.contract.policy,
            "tools": [
                {"type": "function", "name": name, "parameters": {}}
                for name in ("list_agents", "send_message", "spawn_agent", "wait_agent")
            ],
        }
        preflight.register(
            task_id="terminal-bench/filter-js-from-html",
            role="main",
            side=Side.CODEX,
            request=request,
        )
        self.assertEqual(len(preflight.digest()), 64)
        with self.assertRaisesRegex(Exception, "frozen policy"):
            failed_preflight = Plan049RequestPreflight(
                contract=self.contract,
                side=Side.CODEX,
                task_id="terminal-bench/filter-js-from-html",
            )
            failed_preflight.register(
                task_id="terminal-bench/filter-js-from-html",
                role="main",
                side=Side.CODEX,
                request={**request, "instructions": "drifted"},
            )

        latched = Plan049RequestPreflight(
            contract=self.contract,
            side=Side.CODEX,
            task_id="terminal-bench/filter-js-from-html",
        )
        latched.register(
            task_id="terminal-bench/filter-js-from-html",
            role="main",
            side=Side.CODEX,
            request=request,
        )
        with self.assertRaises(FormalDriftError):
            latched.register(
                task_id="terminal-bench/filter-js-from-html",
                role="main",
                side=Side.CODEX,
                request={**request, "instructions": "drifted"},
            )
        with self.assertRaisesRegex(FormalDriftError, "preflight failed"):
            latched.digest()

    def test_formal_infra_exhaustion_stops_at_the_first_incomplete_slot(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="d" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/infra-exhausted"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        calls = 0

        class InfraExecutor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, slot, attempt, run_id, run_root
                nonlocal calls
                calls += 1
                raise FormalInfraError("simulated provider failure")

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            result = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=InfraExecutor(),
                phase="pilot",
            )
            resumed = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=InfraExecutor(),
                phase="pilot",
            )
        rows = store.records()
        self.assertEqual(calls, 5)
        self.assertEqual(len(rows), 5)
        self.assertEqual({row["slot_id"] for row in rows}, {"pilot-p01-codex"})
        self.assertEqual(result, resumed)

    def test_formal_settled_checkpoint_recovers_reports_without_provider_repeat(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="1" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/settled-recovery"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        provider_calls = 0
        recover_calls = 0
        failed = False

        class Executor:
            @staticmethod
            def result(slot, run_id, run_root):
                view = synthetic_team_view(
                    side=slot.side, run_id=run_id, ordinal=slot.ordinal
                )
                return FormalExecutionResult(
                    outcome="completed",
                    trace_status="available",
                    request_preflight_sha256="7" * 64,
                    **write_replay_artifacts(run_root, view),
                )

            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, attempt
                nonlocal provider_calls, failed
                provider_calls += 1
                if not failed:
                    failed = True
                    run_root.mkdir(parents=True, exist_ok=True)
                    (run_root / "settled.json").write_text("{}\n", "utf-8")
                    raise OSError("simulated report failure after settlement")
                return Executor.result(slot, run_id, run_root)

            def recover(inner, slot, *, attempt, run_id, run_root):
                del inner, attempt
                nonlocal recover_calls
                recover_calls += 1
                return Executor.result(slot, run_id, run_root)

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            with self.assertRaisesRegex(FormalError, "local artifact recovery"):
                run_formal_campaign(
                    self.contract,
                    store=store,
                    ledger=ledger,
                    executor=Executor(),
                    phase="pilot",
                )
            result = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=Executor(),
                phase="pilot",
            )
        self.assertEqual(result["run_count"], 6)
        self.assertEqual(provider_calls, 6)
        self.assertEqual(recover_calls, 1)

    def test_formal_identity_error_is_a_principled_stop(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="e" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/identity-stop"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()

        class DriftExecutor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, slot, attempt, run_id, run_root
                raise FormalError("paid request lacks frozen policy")

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            with self.assertRaisesRegex(FormalError, "frozen policy"):
                run_formal_campaign(
                    self.contract,
                    store=store,
                    ledger=ledger,
                    executor=DriftExecutor(),
                    phase="pilot",
                )
        self.assertEqual(store.records(), ())

    def test_phase_b_cli_reaches_the_concrete_paid_runner(self) -> None:
        pilot_rows = [
            {"phase": "pilot", "counts_as_effective": True}
            for _index in range(6)
        ]
        with mock.patch(
            "rondo_eval.proactive_eval.__main__.run_authorized_paid_phase",
            return_value={
                "runs": pilot_rows,
                "activation_observed": True,
                "missing_slot_ids": [],
            },
        ) as runner, mock.patch("builtins.print"):
            status = proactive_main(
                [
                    "phase-b-paid",
                    "--authorize-phase-b",
                    PHASE_B_AUTHORIZATION,
                    "--activation-action",
                    ACTIVATION_ACTION,
                    "--confirmed-balance-usd",
                    "100.00",
                    "--confirm-local-activation",
                    LOCAL_ACTIVATION_CONFIRMATION,
                    "--independent-review-commit",
                    "f" * 40,
                    "--phase",
                    "pilot",
                    "--namespace",
                    "acceptance",
                    "--loopback-namespace",
                    "loopback",
                ]
            )
        self.assertEqual(status, 0)
        runner.assert_called_once()

    def test_production_paid_dependencies_bind_watchdog_and_docker_counter(self) -> None:
        paths = RepoPaths.discover(REPO_ROOT)
        proof = mock.Mock()
        proof.lease.token = "a" * 48
        proof.lease.held = True
        proof.guard.is_held.return_value = True
        counter = mock.Mock()
        with mock.patch(
            "rondo_eval.runtime_bridge.lease_from_watchdog", return_value=proof
        ) as lease, mock.patch(
            "rondo_eval.runtime_bridge.PowerShellDockerDesktopHostProbe"
        ) as host_probe, mock.patch(
            "rondo_eval.runtime_bridge.DockerCliCounter", return_value=counter
        ) as counter_type:
            resources = production_paid_dependencies(paths).acquire_docker_gate()
        lease.assert_called_once_with()
        host_probe.assert_called_once_with()
        counter_type.assert_called_once_with(
            host_data_root=paths.common_root / "eval-data" / "docker-host",
            desktop_host_probe=host_probe.return_value,
        )
        self.assertIs(resources.counter, counter)
        proof.guard.is_held.assert_called_once_with(resources.lease)

    def test_formal_terminal_bench_requests_share_v2_policy_models_and_trace(self) -> None:
        paths = RepoPaths.discover(REPO_ROOT)
        ledger_path = self.common_root / "eval-data/plan-049/paid/request-ledger.json"
        with open_paid_ledger(ledger_path, self.contract) as ledger:
            executor = Plan049TerminalBenchExecutor(
                contract=self.contract,
                common_root=paths.common_root,
                repo_root=paths.worktree_root,
                ledger=ledger,
                api_key="test-only-not-forwarded",
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=mock.Mock(),
                config=load_runtime_config(paths),
            )
            selected = slots(self.contract)[:2]
            requests = [
                executor.build_request(
                    slot,
                    run_id=slot.run_id().replace("rehearsal", "paid"),
                )
                for slot in selected
            ]
        self.assertEqual([request.side.value for request in requests], ["codex", "rondo"])
        for request in requests:
            self.assertTrue(request.common_multi_agent_v2)
            self.assertEqual(request.pinned_model_id, "gpt-5.6-terra")
            self.assertEqual(request.pinned_subagent_model, "gpt-5.6-terra")
            self.assertEqual(request.pinned_subagent_effort, "medium")
            self.assertEqual(request.multi_agent_max_concurrency, 4)
            self.assertEqual(
                request.developer_instructions_sha256,
                self.contract.policy_sha256,
            )
            self.assertEqual(request.rollout_trace_root, "/logs/agent/rollout-trace")
            self.assertEqual(request.budget_usd, 15.10)
        with self.assertRaisesRegex(FormalError, "lacks receipt identity"):
            executor.execute(
                selected[0],
                attempt=1,
                run_id="plan049-paid-pilot-p01-codex-a01",
                run_root=self.common_root / "eval-data/plan-049/no-receipt",
            )
        self.assertFalse(
            (self.common_root / "eval-data/plan-049/no-receipt").exists()
        )

    def test_formal_resume_abandons_a_requested_unpublished_attempt(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="c" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/requested-fixture"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        first_slot = slots(self.contract)[0]
        first_run = first_slot.run_id().replace("rehearsal", "paid")
        executed_attempts: list[tuple[str, int]] = []

        class Executor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner
                executed_attempts.append((slot.slot_id, attempt))
                view = synthetic_team_view(
                    side=slot.side, run_id=run_id, ordinal=slot.ordinal
                )
                digests = write_replay_artifacts(run_root, view)
                return FormalExecutionResult(
                    outcome="completed",
                    trace_status="available",
                    request_preflight_sha256="d" * 64,
                    **digests,
                )

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            ledger.claim_run(first_run, cap_usd="15.10")
            ledger.reserve(first_run, f"{first_run}-request-001", "2.22")
            ledger.begin_attempt(
                first_run, f"{first_run}-request-001", max_attempts=5
            )
            ledger.settle(
                first_run,
                f"{first_run}-request-001",
                Usage(100, 0, 0, 10),
                pricing=provider.main_pricing,
            )
            result = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=Executor(),
                phase="pilot",
            )
        first_rows = [row for row in store.records() if row["slot_id"] == first_slot.slot_id]
        self.assertEqual(
            [(row["attempt"], row["outcome"]) for row in first_rows],
            [(1, "infra_failed"), (2, "completed")],
        )
        self.assertNotIn((first_slot.slot_id, 1), executed_attempts)
        self.assertIn((first_slot.slot_id, 2), executed_attempts)
        self.assertEqual(result["run_count"], 6)

    def test_secret_readiness_never_opens_an_unsafe_path(self) -> None:
        paths = RepoPaths(self.common_root, REPO_ROOT)
        absent = secret_readiness(paths, provider_name="relay")
        self.assertFalse(any(absent.values()))
        target = self.common_root / "not-a-secret"
        target.write_text("unreadable by contract", "utf-8")
        (self.common_root / ".env.local").symlink_to(target)
        linked = secret_readiness(paths, provider_name="relay")
        self.assertTrue(linked["exists"])
        self.assertFalse(linked["regular_file"])
        self.assertFalse(linked["non_symlink"])
        self.assertFalse(linked["phase_b_required_values_nonempty"])


if __name__ == "__main__":
    unittest.main()
