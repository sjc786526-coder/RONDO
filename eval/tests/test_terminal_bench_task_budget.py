from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.terminal_bench.task_budget import (  # noqa: E402
    TASK_BUDGET_CAP_USD,
    TASK_BUDGET_ID,
    TASK_BUDGET_RELPATH,
    TaskBudgetError,
    TaskBudgetIdentity,
    close_task_budget,
    load_task_budget,
    roll_forward_task_budget,
    start_task_budget,
    task_budget_status,
    task_budget_path,
    verify_active_identity,
)


class TaskBudgetEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "budget" / "plan-051.json"
        self.v23 = TaskBudgetIdentity(
            "p2-b7-canary-baseline-v23", "p2-b7-canary-terra-v23"
        )
        self.v24 = TaskBudgetIdentity(
            "p2-b7-canary-baseline-v24", "p2-b7-canary-terra-v24"
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_first_v7_identity_starts_at_zero_with_secure_files(self) -> None:
        state = start_task_budget(self.path, active=self.v23)

        self.assertEqual(state["task_budget_id"], TASK_BUDGET_ID)
        self.assertEqual(task_budget_path(Path(self.directory.name)).relative_to(self.directory.name), TASK_BUDGET_RELPATH)
        self.assertEqual(state["prior_settled_usd"], "0.000000")
        self.assertEqual(state["active_identity"]["campaign_id"], self.v23.campaign_id)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(
            stat.S_IMODE(self.path.with_suffix(".json.lock").stat().st_mode), 0o600
        )
        self.assertEqual(
            verify_active_identity(
                self.path,
                active=self.v23,
                prior_settled_usd=Decimal("0.000000"),
            )["status"],
            "active",
        )

    def test_successor_rolls_forward_settlement_without_reset(self) -> None:
        start_task_budget(self.path, active=self.v23)
        state = roll_forward_task_budget(
            self.path,
            predecessor=self.v23,
            predecessor_terminal_status="failed",
            cumulative_settled_usd=Decimal("12.500000"),
            successor=self.v24,
        )

        self.assertEqual(state["prior_settled_usd"], "12.500000")
        self.assertEqual(state["closed_identities"][0]["settled_usd"], "12.500000")
        self.assertEqual(state["active_identity"]["prior_settled_usd"], "12.500000")
        status = verify_active_identity(
            self.path, active=self.v24, prior_settled_usd=Decimal("12.500000")
        )
        self.assertEqual(status["remaining_usd"], "387.500000")

    def test_rejects_nonterminal_decreasing_duplicate_and_over_cap_rolls(self) -> None:
        start_task_budget(self.path, active=self.v23)
        kwargs = {
            "predecessor": self.v23,
            "cumulative_settled_usd": Decimal("1.000000"),
            "successor": self.v24,
        }
        with self.assertRaisesRegex(TaskBudgetError, "not terminal"):
            roll_forward_task_budget(self.path, predecessor_terminal_status="running", **kwargs)
        with self.assertRaisesRegex(TaskBudgetError, "exceeds"):
            roll_forward_task_budget(
                self.path,
                predecessor=self.v23,
                predecessor_terminal_status="failed",
                cumulative_settled_usd=Decimal("400.000001"),
                successor=self.v24,
            )
        roll_forward_task_budget(
            self.path, predecessor_terminal_status="failed", **kwargs
        )
        with self.assertRaisesRegex(TaskBudgetError, "current active"):
            roll_forward_task_budget(
                self.path,
                predecessor=self.v23,
                predecessor_terminal_status="failed",
                cumulative_settled_usd=Decimal("2.000000"),
                successor=self.v24,
            )
        with self.assertRaisesRegex(TaskBudgetError, "already used"):
            roll_forward_task_budget(
                self.path,
                predecessor=self.v24,
                predecessor_terminal_status="failed",
                cumulative_settled_usd=Decimal("2.000000"),
                successor=TaskBudgetIdentity(self.v24.campaign_id, "new-batch"),
            )
        with self.assertRaisesRegex(TaskBudgetError, "cannot decrease"):
            close_task_budget(
                self.path,
                active=self.v24,
                terminal_status="failed",
                cumulative_settled_usd=Decimal("0.999999"),
            )

    def test_closing_at_cap_hard_stops_and_preserves_all_identity_cost(self) -> None:
        start_task_budget(self.path, active=self.v23)
        state = close_task_budget(
            self.path,
            active=self.v23,
            terminal_status="blocked",
            cumulative_settled_usd=TASK_BUDGET_CAP_USD,
        )

        self.assertIsNone(state["active_identity"])
        self.assertTrue(state["hard_stop"])
        self.assertEqual(task_budget_status(state)["status"], "hard_stopped")
        with self.assertRaisesRegex(TaskBudgetError, "hard stop"):
            verify_active_identity(
                self.path,
                active=self.v23,
                prior_settled_usd=TASK_BUDGET_CAP_USD,
            )

    def test_rejects_tampered_prior_and_symlink_envelope(self) -> None:
        start_task_budget(self.path, active=self.v23)
        state = load_task_budget(self.path)
        state["prior_settled_usd"] = "1.000000"
        self.path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(TaskBudgetError, "prior differs"):
            load_task_budget(self.path)

        os.chmod(self.path, 0o644)
        with self.assertRaisesRegex(TaskBudgetError, "permissions"):
            load_task_budget(self.path)

        unsafe = self.path.with_name("unsafe.json")
        target = self.path.with_name("target.json")
        target.write_text("{}", encoding="utf-8")
        os.symlink(target, unsafe)
        with self.assertRaisesRegex(TaskBudgetError, "unsafe"):
            load_task_budget(unsafe)


if __name__ == "__main__":
    unittest.main()
