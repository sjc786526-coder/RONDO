from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.terminal_bench.scoring import (  # noqa: E402
    GuardianDecision,
    GuardianOutcome,
    ScoringError,
    TaskAttribution,
    TaskOutcome,
    TaskScoreInput,
    aggregate_scores,
    score_task,
    validate_score_aggregate,
)


class TerminalBenchScoringTests(unittest.TestCase):
    @staticmethod
    def _decision(outcome: GuardianOutcome, digit: str = "1") -> GuardianDecision:
        return GuardianDecision(outcome, digit * 64)

    def test_normal_pass_agent_failure_and_infra_are_mechanical(self) -> None:
        passed = score_task(
            TaskScoreInput("terminal-bench/a", TaskOutcome.PASS),
            deny_adjudications={},
        )
        failed = score_task(
            TaskScoreInput("terminal-bench/b", TaskOutcome.FAIL),
            deny_adjudications={},
        )
        infra = score_task(
            TaskScoreInput("terminal-bench/c", TaskOutcome.INFRA),
            deny_adjudications={},
        )

        aggregate = aggregate_scores((passed, failed, infra), taskset="canary")
        self.assertEqual(aggregate["summary"]["scored_tasks"], 2)
        self.assertEqual(aggregate["summary"]["success_rate"], 0.5)
        self.assertEqual(failed.attribution, TaskAttribution.AGENT)
        self.assertEqual(infra.attribution, TaskAttribution.INFRA)

    def test_correct_and_false_deny_require_independent_adjudication(self) -> None:
        denied = self._decision(GuardianOutcome.DENIED)
        value = TaskScoreInput(
            "terminal-bench/a", TaskOutcome.FAIL, guardian_decisions=(denied,)
        )

        correct = score_task(value, deny_adjudications={"1" * 64: "deny"})
        false = score_task(value, deny_adjudications={"1" * 64: "allow"})
        unknown = score_task(value, deny_adjudications={})

        self.assertEqual(correct.attribution, TaskAttribution.GUARDIAN_CORRECT_DENY)
        self.assertEqual(false.attribution, TaskAttribution.GUARDIAN_FALSE_DENY)
        self.assertEqual(unknown.attribution, TaskAttribution.GUARDIAN_FALSE_DENY)

    def test_technical_guardian_failure_is_infra_and_excluded(self) -> None:
        score = score_task(
            TaskScoreInput(
                "terminal-bench/a",
                TaskOutcome.FAIL,
                guardian_decisions=(
                    self._decision(GuardianOutcome.TECHNICAL_FAILURE),
                ),
            ),
            deny_adjudications={},
        )

        self.assertEqual((score.outcome, score.attribution), (TaskOutcome.INFRA, TaskAttribution.INFRA))

    def test_contradictory_pass_or_mixed_guardian_failure_is_rejected(self) -> None:
        with self.assertRaisesRegex(ScoringError, "passing task contradicts"):
            score_task(
                TaskScoreInput(
                    "terminal-bench/a",
                    TaskOutcome.PASS,
                    guardian_decisions=(self._decision(GuardianOutcome.DENIED),),
                ),
                deny_adjudications={},
            )
        with self.assertRaisesRegex(ScoringError, "conflict"):
            score_task(
                TaskScoreInput(
                    "terminal-bench/a",
                    TaskOutcome.FAIL,
                    guardian_decisions=(
                        self._decision(GuardianOutcome.DENIED, "1"),
                        self._decision(GuardianOutcome.TECHNICAL_FAILURE, "2"),
                    ),
                ),
                deny_adjudications={"1" * 64: "deny"},
            )

    def test_holdout_contains_only_one_batch_aggregate(self) -> None:
        scores = tuple(
            score_task(
                TaskScoreInput(f"terminal-bench/task-{index}", TaskOutcome.PASS),
                deny_adjudications={},
            )
            for index in range(3)
        )
        aggregate = aggregate_scores(scores, taskset="holdout")

        self.assertIsNone(aggregate["tasks"])
        self.assertNotIn("task-0", str(aggregate))
        leaked = copy.deepcopy(aggregate)
        leaked["tasks"] = [{"task_id": "terminal-bench/task-0"}]
        with self.assertRaisesRegex(ScoringError, "holdout"):
            validate_score_aggregate(leaked)

    def test_aggregate_arithmetic_drift_is_rejected(self) -> None:
        score = score_task(
            TaskScoreInput("terminal-bench/a", TaskOutcome.PASS),
            deny_adjudications={},
        )
        aggregate = aggregate_scores((score,), taskset="validation")
        aggregate["summary"]["success_rate"] = 0.0
        with self.assertRaisesRegex(ScoringError, "rate"):
            validate_score_aggregate(aggregate)


if __name__ == "__main__":
    unittest.main()
