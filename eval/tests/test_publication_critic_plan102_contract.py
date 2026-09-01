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


class Plan102ProducerLedgerGenerationTests(unittest.TestCase):
    """A retired ledger generation must not hand the next one a fresh task cap."""

    def _write(self, root: Path, ledger_name: str, batch_id: str, spends: list[str]) -> None:
        path = root / "budget" / ledger_name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "batch_id": batch_id,
                    "runs": {
                        f"run-{index}": {"spent_usd": spent}
                        for index, spent in enumerate(spends)
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_active_generation_only_inherits_the_leftover_budget(self) -> None:
        from types import SimpleNamespace

        from rondo_eval.publication_critic.engineering import (  # noqa: E402
            plan102_campaign as campaign,
        )

        contract = load_plan102_contract(REPO_ROOT)
        first, second = campaign._PRODUCER_LEDGER_GENERATIONS
        self.assertEqual(campaign._PRODUCER_BATCH_ID, second[0])

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = SimpleNamespace(runtime_root=root)
            self._write(root, first[1], first[0], ["0.700000", "0.052782"])

            retired = campaign._producer_retired_spend(paths)
            self.assertEqual(retired, Decimal("0.752782"))

            snapshot = campaign._producer_budget_snapshot(paths, contract)
            self.assertEqual(Decimal(snapshot["spent_usd"]), Decimal("0.752782"))
            self.assertEqual(
                Decimal(snapshot["remaining_usd"]),
                contract.budgets.producer_usd - Decimal("0.752782"),
            )
            self.assertEqual(snapshot["run_count"], 2)
            self.assertEqual(snapshot["generations"], [first[0], second[0]])

            # Spending in the active generation keeps counting against the one cap.
            self._write(root, second[1], second[0], ["0.200000"])
            snapshot = campaign._producer_budget_snapshot(paths, contract)
            self.assertEqual(Decimal(snapshot["spent_usd"]), Decimal("0.952782"))
            self.assertEqual(snapshot["run_count"], 3)
            self.assertEqual(campaign._producer_retired_spend(paths), Decimal("0.752782"))

    def test_rejects_a_generation_ledger_with_a_foreign_batch_id(self) -> None:
        from types import SimpleNamespace

        from rondo_eval.publication_critic.engineering import (  # noqa: E402
            plan102_campaign as campaign,
        )

        first, _second = campaign._PRODUCER_LEDGER_GENERATIONS
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = SimpleNamespace(runtime_root=root)
            self._write(root, first[1], "plan097-producer-terra-v8", ["1.0"])
            with self.assertRaisesRegex(
                campaign.Plan102CampaignError, "producer_ledger_identity_invalid"
            ):
                campaign._producer_retired_spend(paths)


class Plan102ProducerPromptTests(unittest.TestCase):
    def test_plan102_member_prompt_keeps_every_evidence_invariant(self) -> None:
        from rondo_eval.publication_critic.engineering import (  # noqa: E402
            plan102_campaign as campaign,
        )
        from rondo_eval.publication_critic.engineering.producer_runtime import (  # noqa: E402
            PRODUCER_MEMBER_PROMPT,
        )

        prompt = campaign.PLAN102_PRODUCER_MEMBER_PROMPT
        for requirement in (
            "exactly one fresh code cell for each team_publish attempt",
            "exactly one awaited team_publish call",
            "Never prewrite, duplicate, batch, or parallelize publish attempts",
            "The first team_publish is the only call that may omit review_cycle_id",
            "Never open a second Event",
            "you MUST continue in the next model turn",
            "do not publish another Version",
            "Never print or send the publication body to Root",
        ):
            self.assertIn(requirement, prompt)
        # The Plan 102 sharpening: bind the result, read the id off it, and
        # treat a rejected attempt as recoverable rather than terminal.
        self.assertIn("Bind the awaited result to a variable", prompt)
        self.assertIn("rather than retyping it", prompt)
        self.assertIn("never resend the previous candidate unchanged", prompt)
        self.assertIn("A rejection does not consume a rewrite opportunity", prompt)
        # Plan 097 keeps its own frozen prompt.
        self.assertNotEqual(prompt, PRODUCER_MEMBER_PROMPT)
        self.assertIn("Plan 097", PRODUCER_MEMBER_PROMPT)


class Plan102TraceFailureTests(unittest.TestCase):
    def test_trace_failures_keep_their_reason_as_a_body_free_code(self) -> None:
        from rondo_eval.publication_critic.engineering import (  # noqa: E402
            plan102_campaign as campaign,
        )

        with tempfile.TemporaryDirectory() as directory:
            # An empty trace root is the "no bundle was written" case.
            with self.assertRaises(campaign.Plan102CampaignError) as raised:
                campaign._load_producer_trace(Path(directory))

        code = str(raised.exception)
        self.assertTrue(code.startswith("producer_trace_invalid:"), code)
        self.assertRegex(code, r"\A[a-z0-9_:-]{1,160}\Z")
        self.assertIn("no_rollout_trace_bundle_was_written", code)


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
