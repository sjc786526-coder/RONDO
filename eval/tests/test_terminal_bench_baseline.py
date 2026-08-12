from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import Side  # noqa: E402
from rondo_eval.terminal_bench.baseline import (  # noqa: E402
    BASE_ROUNDS,
    BaselineError,
    BaselineRun,
    BaselineStatus,
    ConditionalRun,
    assess_baseline,
    cost_forecast,
)
from rondo_eval.terminal_bench.scoring import TaskOutcome  # noqa: E402


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
        self.assertEqual(forecast["v19_shape_stress_with_canary_usd"], "86.968700")
        self.assertTrue(forecast["feasible_from_observed_shape"])
        self.assertFalse(forecast["mathematical_all_legal_usage_guarantee"])
        tracked = json.loads(
            (EVAL_ROOT / "tasksets/p2-b7-cost-forecast.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(tracked, forecast)

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
