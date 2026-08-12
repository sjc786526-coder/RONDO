from __future__ import annotations

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import RunOutcome, Side  # noqa: E402
from rondo_eval.config import RepoPaths, load_runtime_config  # noqa: E402
from rondo_eval.terminal_bench.baseline import (  # noqa: E402
    BASE_ROUNDS,
    CAMPAIGN_LOCK_PATH,
    RETIRED_CAMPAIGN_LOCK_PATHS,
    BaselineError,
    BaselineRun,
    BaselineStatus,
    CampaignSlotStatus,
    CampaignStateLedger,
    ConditionalRun,
    assess_baseline,
    cost_forecast,
    load_campaign_identity,
)
from rondo_eval.terminal_bench.scoring import TaskOutcome  # noqa: E402
from rondo_eval.terminal_bench import baseline_cli  # noqa: E402


class TerminalBenchBaselineTests(unittest.TestCase):
    tasks = tuple(f"terminal-bench/task-{index}" for index in range(10))

    def _base(
        self,
        outcomes: dict[tuple[str, str], TaskOutcome] | None = None,
        *,
        second: dict[tuple[str, str], TaskOutcome] | None = None,
    ) -> tuple[BaselineRun, ...]:
        outcomes = outcomes or {}
        second = second or {}
        values: list[BaselineRun] = []
        for round_id in BASE_ROUNDS:
            side = Side.CODEX if round_id == "ab-codex-1" else Side.RONDO
            for index, task_id in enumerate(self.tasks):
                values.append(
                    BaselineRun(
                        task_id,
                        round_id,
                        side,
                        1,
                        outcomes.get((round_id, task_id), TaskOutcome.PASS),
                        f"{round_id}-{index}-a1",
                    )
                )
                if (round_id, task_id) in second:
                    values.append(
                        BaselineRun(
                            task_id,
                            round_id,
                            side,
                            2,
                            second[(round_id, task_id)],
                            f"{round_id}-{index}-a2",
                        )
                    )
        return tuple(values)

    def _conditional(
        self,
        task_id: str,
        rondo: TaskOutcome,
        codex: TaskOutcome,
    ) -> tuple[ConditionalRun, ...]:
        return tuple(
            ConditionalRun(
                task_id,
                side,
                repeat,
                1,
                rondo if side is Side.RONDO else codex,
                f"conditional-{side.value}-{repeat}",
            )
            for side in (Side.RONDO, Side.CODEX)
            for repeat in (1, 2)
        )

    def test_cost_forecast_is_recomputable_and_below_cap_for_observed_shape(self) -> None:
        forecast = cost_forecast()
        self.assertEqual(forecast["base_point_estimate_usd"], "17.829510")
        self.assertEqual(forecast["full_condition_point_estimate_usd"], "35.529550")
        self.assertEqual(forecast["v19_shape_stress_with_canary_usd"], "173.653100")
        self.assertTrue(forecast["feasible_from_observed_shape"])
        self.assertFalse(forecast["mathematical_all_legal_usage_guarantee"])
        tracked = json.loads(
            (EVAL_ROOT / "tasksets/p2-b7-cost-forecast.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(tracked, forecast)

    def test_campaign_lock_freezes_unique_full_slot_space_and_profile(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        identity = load_campaign_identity(paths)

        self.assertEqual(len(identity.slots), 161)
        self.assertEqual(len({item.run_id for item in identity.slots}), 161)
        self.assertEqual(len({item.slot_id for item in identity.slots}), 161)
        self.assertEqual(identity.slots[0].slot_id, "wire-canary")
        self.assertEqual(identity.campaign_id, "p2-b7-canary-baseline-v3")
        self.assertEqual(identity.batch_id, "p2-b7-canary-sol-sol-v3")
        self.assertEqual(identity.budget["prior_estimated_usd"], "39.269328")
        identity.validate_provider(load_runtime_config(paths).paid_provider_projection())

    def test_retired_identities_and_slots_are_not_reused(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        active = load_campaign_identity(paths)
        self.assertEqual(
            CAMPAIGN_LOCK_PATH,
            Path("eval/locks/p2-b7-canary-baseline-v3.json"),
        )
        self.assertEqual(
            RETIRED_CAMPAIGN_LOCK_PATHS,
            (
                Path("eval/locks/p2-b7-canary-baseline-v1.json"),
                Path("eval/locks/p2-b7-canary-baseline-v2.json"),
            ),
        )
        retired_values = [
            json.loads((paths.worktree_root / path).read_text(encoding="utf-8"))
            for path in RETIRED_CAMPAIGN_LOCK_PATHS
        ]
        self.assertTrue(
            all(item["campaign_id"] != active.campaign_id for item in retired_values)
        )
        self.assertTrue(
            all(item["batch_id"] != active.batch_id for item in retired_values)
        )
        retired_runs = {
            item["run_id_sequence_base"] + index
            for item in retired_values
            for index in range(1, item["budget"]["max_run_slots"] + 1)
        }
        active_runs = {
            int(slot.run_id.split("-")[1]) for slot in active.slots
        }
        self.assertTrue(retired_runs.isdisjoint(active_runs))

    def test_campaign_lock_catalog_drift_is_rejected(self) -> None:
        live_paths = RepoPaths.discover(Path.cwd())
        live = load_campaign_identity(live_paths)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval/locks").mkdir(parents=True)
            lock = json.loads(
                (
                    live_paths.worktree_root
                    / CAMPAIGN_LOCK_PATH
                ).read_text()
            )
            lock["canary_catalog_sha256"] = "0" * 64
            (root / CAMPAIGN_LOCK_PATH).write_text(
                json.dumps(lock), encoding="utf-8"
            )
            with mock.patch(
                "rondo_eval.terminal_bench.baseline.load_frozen_canary_catalog",
                return_value=live.catalog,
            ):
                with self.assertRaisesRegex(Exception, "contract"):
                    load_campaign_identity(RepoPaths(root, root))

    def test_campaign_state_ledger_is_single_claim_and_crash_closed(self) -> None:
        identity = load_campaign_identity(RepoPaths.discover(Path.cwd()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            with CampaignStateLedger(path, identity=identity) as ledger:
                ledger.claim("wire-canary")
                with self.assertRaisesRegex(BaselineError, "not claimable"):
                    ledger.claim("wire-canary")
                ledger.finish(
                    "wire-canary",
                    status=CampaignSlotStatus.COMPLETED,
                    outcome="completed",
                    estimated_usd="0.123456",
                    artifact_path="eval-data/campaigns/canary/receipt.json",
                    result_record_sha256="1" * 64,
                    reason=None,
                )
            with CampaignStateLedger(path, identity=identity) as ledger:
                snapshot = ledger.snapshot()
                self.assertEqual(snapshot["slots"][0]["status"], "completed")

            state = json.loads(path.read_text())
            state["slots"][1]["status"] = "running"
            path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(BaselineError, "crash-interrupted"):
                with CampaignStateLedger(path, identity=identity):
                    pass
            with CampaignStateLedger(
                path,
                identity=identity,
                allow_interrupted_recovery=True,
            ) as ledger:
                recovered = ledger.fail_interrupted(
                    estimated_usd="18.885000",
                    reason="interrupted_request",
                )
                self.assertEqual(recovered, identity.slots[1].slot_id)
                snapshot = ledger.snapshot()
                self.assertEqual(snapshot["slots"][1]["status"], "failed")
                self.assertEqual(snapshot["slots"][1]["outcome"], "infra_failed")

    def test_campaign_base_orchestrator_activates_only_mechanical_replacements(self) -> None:
        identity = load_campaign_identity(RepoPaths.discover(Path.cwd()))

        class State:
            skipped: list[str] = []

            def skip(self, slot_id: str, *, reason: str) -> None:
                del reason
                self.skipped.append(slot_id)

        state = State()
        calls: list[str] = []

        def execute(*, slot, task, **kwargs):
            del task, kwargs
            calls.append(slot.slot_id)
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.COMPLETED,
                TaskOutcome.PASS,
                Decimal("0.100000"),
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            values = baseline_cli._execute_base_rounds(
                identity=identity,
                state=state,
            )
        self.assertEqual((len(calls), len(values), len(state.skipped)), (40, 40, 40))
        self.assertTrue(all(":a1" in value for value in calls))

    def test_unresolved_base_infra_stops_before_conditionals(self) -> None:
        identity = load_campaign_identity(RepoPaths.discover(Path.cwd()))
        task_id = identity.catalog.tasks[0].task_id
        runs = []
        for round_id in BASE_ROUNDS:
            side = Side.CODEX if round_id == "ab-codex-1" else Side.RONDO
            for index, task in enumerate(identity.catalog.tasks):
                runs.append(
                    BaselineRun(
                        task.task_id,
                        round_id,
                        side,
                        1,
                        TaskOutcome.PASS,
                        f"{round_id}-{index}-a1",
                    )
                )
        runs.append(
            BaselineRun(
                task_id,
                "aa-rondo-1",
                Side.RONDO,
                2,
                TaskOutcome.INFRA,
                "replacement-run",
            )
        )
        with self.assertRaisesRegex(
            baseline_cli.CampaignExecutionError,
            "replacement was exhausted",
        ):
            baseline_cli._require_resolved_base_rounds(identity, runs)

    def test_storage_projection_keeps_initial_final_and_growth(self) -> None:
        initial = baseline_cli.StorageBaseline(100, 200, 300)
        final = baseline_cli.StorageBaseline(120, 250, 280)
        self.assertEqual(
            baseline_cli._storage_projection(initial, final),
            {
                "initial": {
                    "docker_total_bytes": 100,
                    "docker_desktop_vhdx_bytes": 200,
                    "windows_free_bytes": 300,
                },
                "final": {
                    "docker_total_bytes": 120,
                    "docker_desktop_vhdx_bytes": 250,
                    "windows_free_bytes": 280,
                },
                "growth_bytes": 50,
            },
        )
        self.assertIsNone(
            baseline_cli._storage_projection(initial, None)["final"]
        )

    def test_public_campaign_aggregate_scores_rounds_and_sums_usage(self) -> None:
        base = self._base()
        assessment = assess_baseline(self.tasks, base, ())
        records = {
            item.run_id: {
                "outcome": "completed",
                "tasks": [{"task_id": item.task_id, "outcome": "pass"}],
                "summary": {"evidence": []},
            }
            for item in base
        }
        public = baseline_cli._public_assessment(assessment, records)
        self.assertEqual(public["sigma"], 0)
        self.assertEqual(
            public["base_rounds"]["aa-rondo-1"]["summary"]["success_rate"],
            1.0,
        )

        with tempfile.TemporaryDirectory() as directory:
            common = Path(directory)
            artifact = common / "eval-data/runs/example"
            artifact.mkdir(parents=True)
            (artifact / "api-metadata.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "requests": [
                            {
                                "usage": {
                                    "input_tokens": 10,
                                    "cached_input_tokens": 2,
                                    "cache_write_input_tokens": 1,
                                    "output_tokens": 3,
                                }
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            usage = baseline_cli._campaign_usage(
                common,
                {
                    "run": {
                        "artifacts": "eval-data/runs/example",
                        "summary": {"metadata_ready": True},
                    }
                },
            )
        self.assertEqual(
            usage,
            {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "cache_write_input_tokens": 1,
                "output_tokens": 3,
            },
        )

    def test_happy_path_has_zero_sigma_and_delta(self) -> None:
        result = assess_baseline(self.tasks, self._base(), ())
        self.assertEqual((result.status, result.sigma, result.delta), (BaselineStatus.PASSED, 0, 0))

    def test_three_infra_requires_full_round_replacement(self) -> None:
        round_id = "aa-rondo-1"
        outcomes = {
            (round_id, task_id): TaskOutcome.INFRA for task_id in self.tasks[:3]
        }
        partial_second = {
            (round_id, task_id): TaskOutcome.PASS for task_id in self.tasks[:3]
        }
        with self.assertRaisesRegex(BaselineError, "replacement set"):
            assess_baseline(
                self.tasks,
                self._base(outcomes, second=partial_second),
                (),
            )

        all_second = {
            (round_id, task_id): TaskOutcome.PASS for task_id in self.tasks
        }
        result = assess_baseline(
            self.tasks,
            self._base(outcomes, second=all_second),
            (),
        )
        self.assertEqual(result.status, BaselineStatus.PASSED)

    def test_two_infra_use_only_targeted_replacements(self) -> None:
        round_id = "aa-rondo-1"
        outcomes = {
            (round_id, task_id): TaskOutcome.INFRA for task_id in self.tasks[:2]
        }
        second = {(round_id, task_id): TaskOutcome.PASS for task_id in self.tasks[:2]}
        result = assess_baseline(self.tasks, self._base(outcomes, second=second), ())
        self.assertEqual(result.status, BaselineStatus.PASSED)

    def test_sigma_and_delta_boundaries_are_enforced(self) -> None:
        outcomes = {
            ("aa-rondo-2", self.tasks[index]): TaskOutcome.FAIL for index in range(3)
        }
        result = assess_baseline(self.tasks, self._base(outcomes), ())
        self.assertEqual(result.status, BaselineStatus.FAILED)
        self.assertIn("aa_sigma_exceeds_frozen_stability_limit", result.reasons)

        outcomes = {
            ("ab-rondo-1", self.tasks[0]): TaskOutcome.FAIL,
        }
        result = assess_baseline(
            self.tasks,
            self._base(outcomes),
            self._conditional(self.tasks[0], TaskOutcome.PASS, TaskOutcome.PASS),
        )
        self.assertEqual((result.sigma, result.delta), (0, 1))
        self.assertIn("ab_delta_exceeds_aa_sigma", result.reasons)

    def test_stable_directional_regression_fails_after_required_reruns(self) -> None:
        outcomes = {("ab-rondo-1", self.tasks[0]): TaskOutcome.FAIL}
        result = assess_baseline(
            self.tasks,
            self._base(outcomes),
            self._conditional(self.tasks[0], TaskOutcome.FAIL, TaskOutcome.PASS),
        )
        self.assertEqual(result.status, BaselineStatus.FAILED)
        self.assertIn(
            f"stable_directional_regression:{self.tasks[0]}", result.reasons
        )

    def test_exhausted_infra_replacement_is_blocked_not_partial_pass(self) -> None:
        round_id = "aa-rondo-1"
        outcomes = {(round_id, self.tasks[0]): TaskOutcome.INFRA}
        second = {(round_id, self.tasks[0]): TaskOutcome.INFRA}
        result = assess_baseline(self.tasks, self._base(outcomes, second=second), ())
        self.assertEqual(result.status, BaselineStatus.BLOCKED)
        self.assertIsNone(result.sigma)


if __name__ == "__main__":
    unittest.main()
