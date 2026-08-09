from __future__ import annotations

import sys
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.budget import BatchBudgetLedger, BudgetError  # noqa: E402


class BudgetTests(unittest.TestCase):
    def test_batch_cap_is_shared_across_runs(self) -> None:
        ledger = BatchBudgetLedger(batch_id="p1")
        ledger.reserve("r1", "12.00")
        ledger.settle("r1", "3.25")
        ledger.reserve("r2", "16.75")
        with self.assertRaises(BudgetError):
            ledger.reserve("r3", "0.01")
        self.assertEqual(ledger.snapshot()["remaining_uncommitted_usd"], "0.00")

    def test_run_limit_and_duplicate_ids_are_fail_closed(self) -> None:
        ledger = BatchBudgetLedger(batch_id="p1", max_runs=2)
        ledger.reserve("r1", "1")
        ledger.settle("r1", "0")
        with self.assertRaises(BudgetError):
            ledger.reserve("r1", "1")
        ledger.reserve("r2", "1")
        with self.assertRaises(BudgetError):
            ledger.reserve("r3", "1")

    def test_invalid_or_over_authorized_limits_are_rejected(self) -> None:
        with self.assertRaises(BudgetError):
            BatchBudgetLedger(batch_id="p1", total_cap_usd="20.01")
        with self.assertRaises(BudgetError):
            BatchBudgetLedger(batch_id="p1", max_runs=5)


if __name__ == "__main__":
    unittest.main()
