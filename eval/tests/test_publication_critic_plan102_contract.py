from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from collections.abc import Callable
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.engineering.cloud_budget_proxy import (  # noqa: E402
    PLAN097_CLOUD_BUDGET_IDENTITY,
    _PersistentLedger,
)
from rondo_eval.publication_critic.engineering.plan102_contract import (  # noqa: E402
    CLOUD_BUDGET_IDENTITY,
    CLOUD_DESCRIPTOR,
    CONTRACT_RELATIVE_PATH,
    SCHEMA,
    Plan102ContractError,
    load_plan102_contract,
)
from rondo_eval.publication_critic.engineering.contract import (  # noqa: E402
    load_contract as load_plan097_contract,
)


def _json(relative: str | Path) -> dict[str, Any]:
    return json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


class Plan102ContractTests(unittest.TestCase):
    def _load_changed(
        self,
        change_contract: Callable[[dict[str, Any]], None] | None = None,
        *,
        change_cloud: Callable[[dict[str, Any]], None] | None = None,
    ):
        contract = _json(CONTRACT_RELATIVE_PATH)
        cloud = _json(CLOUD_DESCRIPTOR)
        if change_contract is not None:
            change_contract(contract)
        if change_cloud is not None:
            change_cloud(cloud)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, value in (
                (CONTRACT_RELATIVE_PATH, contract),
                (Path(CLOUD_DESCRIPTOR), cloud),
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding="utf-8")
            return load_plan102_contract(root)

    def test_loads_five_dimension_identity_without_threshold(self) -> None:
        contract = load_plan102_contract(REPO_ROOT)

        self.assertEqual(contract.schema, SCHEMA)
        self.assertEqual(contract.product_default, "off")
        self.assertEqual(contract.quality_evaluation, "not_in_scope")
        self.assertEqual(contract.budgets.judge_rmb, Decimal("10"))
        self.assertEqual(contract.budgets.producer_usd, Decimal("50"))
        self.assertEqual(contract.budgets.judge_missing_usage_rmb, Decimal("0.1"))
        scoring = contract.backend.service_descriptor["identity"]["scoring"]
        self.assertEqual(
            scoring["pass_rule"], "discrete_non_compensating_conjunction"
        )
        self.assertNotIn("threshold", scoring)
        self.assertNotIn("domain", scoring)
        self.assertNotIn("scalar_projection", scoring)
        self.assertNotEqual(
            CLOUD_BUDGET_IDENTITY.schema, PLAN097_CLOUD_BUDGET_IDENTITY.schema
        )

    def test_plan097_budget_identity_is_untouched(self) -> None:
        plan097 = load_plan097_contract(REPO_ROOT)

        self.assertEqual(plan097.budgets.cloud_scorer_rmb, Decimal("6"))
        self.assertEqual(plan097.budgets.producer_rmb, Decimal("24"))
        self.assertEqual(plan097.budgets.rmb_per_usd, Decimal("7.5"))
        self.assertEqual(plan097.budgets.total_rmb, Decimal("30"))

    def test_rejects_plan097_budget_numbers(self) -> None:
        def change(contract: dict[str, Any]) -> None:
            contract["budgets"]["judge_rmb"] = "6"
            contract["budgets"]["producer_usd"] = "24"

        with self.assertRaisesRegex(Plan102ContractError, "budget_identity_invalid"):
            self._load_changed(change)

    def test_rejects_quality_expectation_on_direct_cases(self) -> None:
        def change(contract: dict[str, Any]) -> None:
            contract["direct_cases"][0]["expected_engineering_branch"] = "rewrite"

        with self.assertRaisesRegex(
            Plan102ContractError, "direct_case_fields_invalid"
        ):
            self._load_changed(change)

    def test_rejects_scalar_threshold_on_five_dimension_descriptor(self) -> None:
        def change(cloud: dict[str, Any]) -> None:
            scoring = cloud["service_descriptor"]["identity"]["scoring"]
            scoring["threshold"] = 0.5
            scoring["domain"] = {"min": 0.0, "max": 1.0}
            scoring["scalar_projection"] = {
                "name": "rondo-cloud-json-quality-scalar",
                "revision": "v1",
            }

        with self.assertRaisesRegex(Plan102ContractError, "service_identity_invalid"):
            self._load_changed(change_cloud=change)

    def test_plan102_ledger_rejects_plan097_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            plan097 = _PersistentLedger(path, Decimal("2"), PLAN097_CLOUD_BUDGET_IDENTITY)
            plan097.reserve()
            with self.assertRaisesRegex(
                Exception, "ledger_identity_invalid"
            ):
                _PersistentLedger(path, Decimal("2"), CLOUD_BUDGET_IDENTITY)

    def test_plan102_unknown_usage_charges_one_tenth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = _PersistentLedger(path, Decimal("2"), CLOUD_BUDGET_IDENTITY)
            attempt = ledger.reserve()
            ledger.settle(attempt, None)
            snapshot = ledger.snapshot()
            self.assertEqual(snapshot["schema"], CLOUD_BUDGET_IDENTITY.schema)
            self.assertEqual(snapshot["attempts"][0]["conservative_charge_rmb"], "0.1")
            self.assertEqual(snapshot["conservative_charged_rmb"], "0.1")


class Plan102ProxyShapeTests(unittest.TestCase):
    def test_records_disabled_thinking_without_bodies(self) -> None:
        from rondo_eval.publication_critic.engineering.cloud_budget_proxy import (  # noqa: E402
            _request_shape,
        )

        shape = _request_shape(
            {
                "model": "deepseek-v4-flash",
                "thinking": {"type": "disabled"},
                "messages": [{"role": "user", "content": "secret-body"}],
            }
        )
        self.assertEqual(shape["thinking_type"], "disabled")
        self.assertEqual(shape["model"], "deepseek-v4-flash")
        self.assertTrue(shape["has_messages"])
        self.assertNotIn("secret-body", json.dumps(shape))


if __name__ == "__main__":
    unittest.main()
