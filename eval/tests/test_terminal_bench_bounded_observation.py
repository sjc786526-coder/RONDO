from __future__ import annotations

import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from rondo_eval.api_budget_proxy import PersistentBudgetLedger
from rondo_eval.config import RepoPaths
from rondo_eval.terminal_bench.baseline_cli import StorageBaseline
from rondo_eval.terminal_bench.bounded_observation import (
    PLAN056_SLOT_COUNT,
    BoundedObservationError,
    BoundedObservationState,
    _validate_source_binding,
    assess_candidates,
    freeze_slots,
)
from rondo_eval.terminal_bench.bounded_observation_cli import (
    _load_budget_snapshot,
    _source_tree_fingerprint,
    _storage_projection,
    status,
)
from rondo_eval.terminal_bench.tasksets import FrozenTask

from .test_harness_observation import _observation


def _tasks() -> tuple[FrozenTask, ...]:
    values = []
    for index in range(1, 11):
        values.append(
            FrozenTask(
                task_id=f"terminal-bench/task-{index:02d}",
                source_digest="sha256:" + f"{index:064x}"[-64:],
                image_tag=f"example/task-{index:02d}:latest",
                image_ref=f"example/task-{index:02d}@sha256:"
                + f"{index + 10:064x}"[-64:],
                workdir="/workspace",
                memory_mb=2048,
                timeout_seconds=1800,
                agent_timeout_seconds=900,
                verifier_timeout_seconds=900,
                build_timeout_seconds=600,
            )
        )
    return tuple(values)


def _records() -> list[dict[str, object]]:
    slots = freeze_slots(
        _tasks(), run_id_date="20260822", run_id_sequence_base=560000001
    )
    return [
        {
            "slot": {
                "round": slot.round,
                "task_id": slot.task_id,
            },
            "terminal_bench": {"task_outcome": "pass"},
            "observation": _observation(),
        }
        for slot in slots
    ]


class BoundedObservationIdentityTests(unittest.TestCase):
    def test_slots_are_exactly_two_rounds_of_the_same_ten_tasks(self) -> None:
        tasks = _tasks()
        slots = freeze_slots(
            tasks, run_id_date="20260822", run_id_sequence_base=560000001
        )

        self.assertEqual(len(slots), PLAN056_SLOT_COUNT)
        self.assertEqual(len({slot.run_id for slot in slots}), PLAN056_SLOT_COUNT)
        self.assertEqual(
            tuple(slot.task_id for slot in slots[:10]), tuple(t.task_id for t in tasks)
        )
        self.assertEqual(
            tuple(slot.task_id for slot in slots[10:]), tuple(t.task_id for t in tasks)
        )
        self.assertEqual(tuple(slot.round for slot in slots), (1,) * 10 + (2,) * 10)

    def test_wrong_task_denominator_is_rejected(self) -> None:
        with self.assertRaisesRegex(BoundedObservationError, "denominator"):
            freeze_slots(
                _tasks()[:-1],
                run_id_date="20260822",
                run_id_sequence_base=560000001,
            )

    def test_fourth_unsent_execution_attempt_persists_invalid_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tasks = _tasks()
            slots = freeze_slots(
                tasks, run_id_date="20260822", run_id_sequence_base=560000001
            )
            identity = SimpleNamespace(
                campaign_id="plan056-test",
                lock_sha256="a" * 64,
                tasks=tasks,
                slots=slots,
                slot=lambda slot_id: next(
                    slot for slot in slots if slot.slot_id == slot_id
                ),
            )
            state_path = Path(raw) / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "rondo_direction1_bounded_observation",
                        "campaign_id": identity.campaign_id,
                        "campaign_lock_sha256": identity.lock_sha256,
                        "status": "running",
                        "invalid_reason": None,
                        "formal_boundary": False,
                        "preflight": [
                            {
                                "task_id": task.task_id,
                                "status": "complete",
                                "attempts": 1,
                                "receipt_sha256": "b" * 64,
                                "last_error": None,
                            }
                            for task in tasks
                        ],
                        "slots": [
                            {
                                "slot_id": slot.slot_id,
                                "run_id": slot.run_id,
                                "status": "running" if index == 0 else "pending",
                                "execution_attempts": 3 if index == 0 else 0,
                                "record_sha256": None,
                            }
                            for index, slot in enumerate(slots)
                        ],
                        "final_storage": None,
                        "outcome": None,
                        "selected_candidate": None,
                    }
                ),
                encoding="utf-8",
            )
            with BoundedObservationState(state_path, identity=identity) as state:
                self.assertIsNone(state.claim_or_resume_slot())

            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["status"], "invalid")
            self.assertEqual(
                persisted["invalid_reason"], "unsent_execution_attempt_bound_exceeded"
            )
            self.assertEqual(persisted["slots"][0]["execution_attempts"], 3)

    def test_default_status_is_zero_api_and_does_not_require_config(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.assertEqual(
                status(RepoPaths(common_root=root, worktree_root=root)),
                {"status": "uninitialized", "paid_requests_sent": 0},
            )

    def test_private_source_fingerprint_detects_trace_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            slot = freeze_slots(
                _tasks(), run_id_date="20260822", run_id_sequence_base=560000001
            )[0]
            attempt = root / "slots" / slot.slot_id / "attempt-1"
            trace = attempt / "trial" / "agent" / "rollout-trace"
            trace.mkdir(parents=True)
            (trace / "events.jsonl").write_text("first\n", encoding="utf-8")
            before = _source_tree_fingerprint(root, trace)
            sources = {
                "terminal_bench": {
                    "path": f"slots/{slot.slot_id}/attempt-1/trial/result.json",
                    "sha256": "a" * 64,
                    "host_returncode": 0,
                },
                "api_metadata": {
                    "path": f"slots/{slot.slot_id}/attempt-1/api-metadata.json",
                    "sha256": "b" * 64,
                },
                "native_trace": before,
            }
            self.assertEqual(_validate_source_binding(sources, slot=slot), sources)

            (trace / "events.jsonl").write_text("second\n", encoding="utf-8")
            self.assertNotEqual(_source_tree_fingerprint(root, trace), before)

    def test_fail_closed_storage_projection_preserves_last_reliable_baseline(
        self,
    ) -> None:
        baseline = StorageBaseline(10, 20, 30)
        projection = _storage_projection(
            baseline, None, unavailable_reason="CampaignExecutionError"
        )

        self.assertEqual(
            projection["final_sample_status"], "unavailable_after_fail_closed"
        )
        self.assertEqual(projection["docker_total_bytes_before"], 10)
        self.assertIsNone(projection["docker_total_bytes_after"])
        self.assertEqual(projection["windows_c_free_bytes_before"], 30)


class BoundedObservationBudgetTests(unittest.TestCase):
    def test_read_only_budget_snapshot_exposes_live_totals(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = root / "eval-data/budgets/plan056-test-batch.json"
            with PersistentBudgetLedger(
                path,
                batch_id="plan056-test-batch",
                total_cap_usd="50",
                max_runs=20,
                default_run_cap_usd="40",
                unpriced_fallback_usd="1",
                unpriced_fallback_per_attempt=True,
            ) as ledger:
                ledger.claim_run("slot-1", cap_usd="40")
                ledger.reserve("slot-1", "request-1", "5")

            snapshot = _load_budget_snapshot(
                RepoPaths(common_root=root, worktree_root=root),
                SimpleNamespace(
                    batch_id="plan056-test-batch",
                ),
            )

            self.assertEqual(snapshot["run_slots_used"], 1)
            self.assertEqual(snapshot["spent_usd"], "0.000000")
            self.assertEqual(snapshot["reserved_usd"], "5.000000")

    def test_zero_attempt_recovery_reuses_same_run_without_deleting_history(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "budget.json"
            with PersistentBudgetLedger(
                path,
                batch_id="plan056-test",
                total_cap_usd="50",
                max_runs=20,
                default_run_cap_usd="40",
                unpriced_fallback_usd="1",
                unpriced_fallback_per_attempt=True,
            ) as ledger:
                ledger.claim_run("slot-1", cap_usd="40")
                ledger.reserve("slot-1", "unsent", "5")
            with PersistentBudgetLedger(
                path,
                batch_id="plan056-test",
                total_cap_usd="50",
                max_runs=20,
                default_run_cap_usd="40",
                unpriced_fallback_usd="1",
                unpriced_fallback_per_attempt=True,
            ) as ledger:
                ledger.resume_unsent_run("slot-1", cap_usd="40")
                snapshot = ledger.snapshot()

            request = snapshot["runs"]["slot-1"]["requests"]["unsent"]
            self.assertEqual(request["attempt_count"], 0)
            self.assertEqual(request["settlement_kind"], "not_sent_unbilled")
            self.assertEqual(Decimal(request["charged_usd"]), Decimal(0))

    def test_sent_or_charged_run_cannot_use_unsent_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "budget.json"
            with PersistentBudgetLedger(
                path,
                batch_id="plan056-test",
                total_cap_usd="50",
                max_runs=20,
                default_run_cap_usd="40",
                unpriced_fallback_usd="1",
                unpriced_fallback_per_attempt=True,
            ) as ledger:
                ledger.claim_run("slot-1", cap_usd="40")
                ledger.reserve("slot-1", "sent", "5")
                ledger.begin_attempt("slot-1", "sent", max_attempts=5)
            with (
                PersistentBudgetLedger(
                    path,
                    batch_id="plan056-test",
                    total_cap_usd="50",
                    max_runs=20,
                    default_run_cap_usd="40",
                    unpriced_fallback_usd="1",
                    unpriced_fallback_per_attempt=True,
                ) as ledger,
                self.assertRaisesRegex(Exception, "proven unsent"),
            ):
                ledger.resume_unsent_run("slot-1", cap_usd="40")

    def test_caught_interruption_closes_sent_reservation_at_one_usd(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "budget.json"
            with PersistentBudgetLedger(
                path,
                batch_id="plan056-test",
                total_cap_usd="50",
                max_runs=20,
                default_run_cap_usd="40",
                unpriced_fallback_usd="1",
                unpriced_fallback_per_attempt=True,
            ) as ledger:
                ledger.claim_run("slot-1", cap_usd="40")
                ledger.reserve("slot-1", "sent", "7")
                ledger.begin_attempt("slot-1", "sent", max_attempts=5)
                ledger.recover_interrupted_requests()
                snapshot = ledger.snapshot()

            request = snapshot["runs"]["slot-1"]["requests"]["sent"]
            self.assertEqual(request["settlement_kind"], "unpriced_fallback")
            self.assertEqual(Decimal(request["charged_usd"]), Decimal(1))
            self.assertEqual(snapshot["reserved_usd"], "0.000000")

    def test_interrupted_attempts_are_each_charged_one_usd(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "budget.json"
            with PersistentBudgetLedger(
                path,
                batch_id="plan056-test",
                total_cap_usd="50",
                max_runs=20,
                default_run_cap_usd="40",
                unpriced_fallback_usd="1",
                unpriced_fallback_per_attempt=True,
            ) as ledger:
                ledger.claim_run("slot-1", cap_usd="40")
                ledger.reserve("slot-1", "sent", "7")
                for _attempt in range(3):
                    ledger.begin_attempt("slot-1", "sent", max_attempts=5)
                ledger.recover_interrupted_requests()
                snapshot = ledger.snapshot()

            request = snapshot["runs"]["slot-1"]["requests"]["sent"]
            self.assertEqual(request["attempt_count"], 3)
            self.assertEqual(request["settlement_kind"], "unpriced_fallback")
            self.assertEqual(Decimal(request["charged_usd"]), Decimal(3))


class CandidateDecisionTests(unittest.TestCase):
    def test_exact_twenty_denominator_is_required(self) -> None:
        with self.assertRaisesRegex(BoundedObservationError, "not 20"):
            assess_candidates(_records()[:-1])
        with self.assertRaisesRegex(BoundedObservationError, "not 20"):
            assess_candidates([*_records(), copy.deepcopy(_records()[0])])

    def test_c1_requires_two_rounds_and_two_tasks(self) -> None:
        records = _records()
        records[0]["observation"]["tools"]["model_visible_presentation_truncations"] = 1
        records[1]["observation"]["tools"][
            "model_visible_collection_omission_events"
        ] = 1
        records[1]["observation"]["tools"]["model_visible_collection_omitted_bytes"] = (
            100
        )
        self.assertIsNone(assess_candidates(records)["selected_candidate"])

        records[10]["observation"]["tools"][
            "model_visible_presentation_truncations"
        ] = 1
        records[11]["observation"]["tools"][
            "model_visible_collection_omission_events"
        ] = 1
        records[11]["observation"]["tools"][
            "model_visible_collection_omitted_bytes"
        ] = 100
        self.assertEqual(assess_candidates(records)["selected_candidate"], "C1")

    def test_c2_requires_repeat_count_and_positive_duration_in_both_rounds(
        self,
    ) -> None:
        records = _records()
        for index in (0, 1, 10, 11):
            observation = records[index]["observation"]
            observation["tools"]["repeated_exact_commands"] = 1
            observation["tools"]["repeated_exact_command_lifecycle_duration_ms"] = 10
        self.assertEqual(assess_candidates(records)["selected_candidate"], "C2")

        missing_duration = _records()
        missing_duration[0]["observation"]["tools"]["repeated_exact_commands"] = 1
        self.assertIsNone(assess_candidates(missing_duration)["selected_candidate"])

    def test_c11_requires_typed_context_failure_that_impacts_the_task(self) -> None:
        records = _records()
        observation = records[0]["observation"]
        observation["errors"]["total"] = 1
        observation["errors"]["context_window_exceeded"] = 1
        observation["responses"]["terminal_completed"] = 0
        observation["responses"]["terminal_failed"] = 1
        observation["responses"]["with_valid_usage"] = 0
        observation["responses"]["missing_or_invalid_usage"] = 1
        observation["availability"]["response_usage"] = "unmeasurable"
        for key in observation["responses"]["usage"]:
            observation["responses"]["usage"][key] = 0
        self.assertIsNone(assess_candidates(records)["selected_candidate"])

        records[0]["terminal_bench"]["task_outcome"] = "fail"
        self.assertEqual(assess_candidates(records)["selected_candidate"], "C11")

    def test_tie_break_prefers_lower_behavior_risk_and_selects_only_one(self) -> None:
        records = _records()
        for index in (0, 1, 10, 11):
            observation = records[index]["observation"]
            observation["tools"]["model_visible_presentation_truncations"] = 1
            observation["tools"]["repeated_exact_commands"] = 1
            observation["tools"]["repeated_exact_command_lifecycle_duration_ms"] = 10
        decision = assess_candidates(records)

        self.assertTrue(decision["candidates"]["C1"]["eligible"])
        self.assertTrue(decision["candidates"]["C2"]["eligible"])
        self.assertEqual(decision["selected_candidate"], "C2")

    def test_tie_break_does_not_compare_bytes_with_milliseconds(self) -> None:
        records = _records()
        for index in (0, 1, 10, 11):
            observation = records[index]["observation"]
            observation["tools"]["model_visible_collection_omission_events"] = 1
            observation["tools"]["model_visible_collection_omitted_bytes"] = 10**9
            observation["tools"]["repeated_exact_commands"] = 1
            observation["tools"]["repeated_exact_command_lifecycle_duration_ms"] = 1

        decision = assess_candidates(records)

        self.assertEqual(decision["candidates"]["C1"]["impact"], 4 * 10**9)
        self.assertEqual(decision["candidates"]["C2"]["impact"], 4)
        self.assertEqual(decision["selected_candidate"], "C2")


if __name__ == "__main__":
    unittest.main()
