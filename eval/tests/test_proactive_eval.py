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
    synthetic_team_view,
    write_replay_artifacts,
)
from rondo_eval.proactive_eval.campaign import (  # noqa: E402
    ExecutionResult,
    default_fake_executor,
    run_rehearsal,
)
from rondo_eval.proactive_eval.contract import ContractError, load_contract  # noqa: E402
from rondo_eval.proactive_eval.paid import (  # noqa: E402
    ACTIVATION_ACTION,
    PHASE_B_AUTHORIZATION,
    PaidEntryCallbacks,
    PaidGuardError,
    enter_paid_phase,
)
from rondo_eval.proactive_eval.readiness import secret_readiness  # noqa: E402
from rondo_eval.proactive_eval.schedule import dry_run_projection, slots  # noqa: E402
from rondo_eval.proactive_eval.store import (  # noqa: E402
    RehearsalStore,
    StoreError,
    assert_body_free,
)
from rondo_eval.team_lens.model import dump_team_view  # noqa: E402
from rondo_eval.team_lens.report import render_report  # noqa: E402
from rondo_eval.config import RepoPaths  # noqa: E402


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
            executor=lambda _slot, _attempt: ExecutionResult("completed"),
            artifact_writer=flaky_writer,
        )
        self.assertEqual(first["run_count"], 25)
        second = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="report-recovery",
            executor=lambda _slot, _attempt: ExecutionResult("completed"),
        )
        self.assertEqual(second["run_count"], 26)

        original = RehearsalStore.append
        failed = False

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
                    executor=lambda _slot, _attempt: ExecutionResult("completed"),
                )
        recovered = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="archive-recovery",
            executor=lambda _slot, _attempt: ExecutionResult("completed"),
        )
        self.assertEqual(recovered["run_count"], 26)
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

    def test_paid_guard_stops_before_every_side_effect(self) -> None:
        calls: list[str] = []
        callbacks = PaidEntryCallbacks(
            read_secret=lambda: calls.append("secret"),
            create_formal_state=lambda: calls.append("state"),
            touch_network=lambda: calls.append("network"),
            touch_docker=lambda: calls.append("docker"),
        )
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
            calls.clear()
            arguments = {
                "repo_root": REPO_ROOT,
                "authorization": None,
                "activation_action": None,
                "confirmed_balance_usd": None,
                "harness_clean": True,
                "resume_prefix_safe": True,
                "activation_conditions_ready": True,
                "docker_resource_gate_ready": True,
                "callbacks": callbacks,
                **overrides,
            }
            with self.assertRaises(PaidGuardError):
                enter_paid_phase(**arguments)
            self.assertEqual(calls, [])

        enter_paid_phase(
            repo_root=REPO_ROOT,
            authorization=PHASE_B_AUTHORIZATION,
            activation_action=ACTIVATION_ACTION,
            confirmed_balance_usd="100.00",
            harness_clean=True,
            resume_prefix_safe=True,
            activation_conditions_ready=True,
            docker_resource_gate_ready=True,
            callbacks=callbacks,
        )
        self.assertEqual(calls, ["secret", "state", "network", "docker"])

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
