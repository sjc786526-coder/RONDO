from __future__ import annotations

import copy
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

from rondo_eval.publication_critic.engineering.contract import (  # noqa: E402
    CLOUD_DESCRIPTOR,
    CONTRACT_RELATIVE_PATH,
    LOCAL_DESCRIPTOR,
    EngineeringContractError,
    load_contract,
)


def _json(relative: str | Path) -> dict[str, Any]:
    return json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


class EngineeringContractTests(unittest.TestCase):
    def _load_changed(
        self,
        change_contract: Callable[[dict[str, Any]], None] | None = None,
        *,
        change_local: Callable[[dict[str, Any]], None] | None = None,
        change_cloud: Callable[[dict[str, Any]], None] | None = None,
    ):
        contract = _json(CONTRACT_RELATIVE_PATH)
        local = _json(LOCAL_DESCRIPTOR)
        cloud = _json(CLOUD_DESCRIPTOR)
        if change_contract is not None:
            change_contract(contract)
        if change_local is not None:
            change_local(local)
        if change_cloud is not None:
            change_cloud(cloud)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, value in (
                (CONTRACT_RELATIVE_PATH, contract),
                (Path(LOCAL_DESCRIPTOR), local),
                (Path(CLOUD_DESCRIPTOR), cloud),
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value), encoding="utf-8")
            return load_contract(root)

    def test_loads_typed_runner_contract(self) -> None:
        contract = load_contract(REPO_ROOT)

        self.assertEqual(set(contract.backends), {"local", "cloud"})
        self.assertEqual(
            contract.backends["local"].descriptor,
            LOCAL_DESCRIPTOR,
        )
        self.assertEqual(
            contract.backends["cloud"].descriptor,
            CLOUD_DESCRIPTOR,
        )
        self.assertEqual(contract.budgets.cloud_scorer_rmb, Decimal("12"))
        self.assertEqual(contract.budgets.producer_rmb, Decimal("18"))
        self.assertEqual(contract.budgets.total_rmb, Decimal("30"))
        self.assertEqual(contract.producer.model_alias, "terra")
        self.assertEqual(contract.producer.reasoning_effort, "low")
        self.assertEqual(contract.producer.max_input_tokens, 32000)
        self.assertEqual(contract.producer.max_output_tokens, 4000)
        self.assertEqual(len(contract.commissioning_cases), 3)
        self.assertEqual(
            {case.expected_engineering_branch for case in contract.commissioning_cases},
            {"pass", "rewrite"},
        )
        self.assertEqual(len(contract.contract_sha256), 64)
        for backend in contract.backends.values():
            self.assertEqual(len(backend.descriptor_sha256), 64)
            self.assertGreater(
                backend.client_call_timeout_ms,
                backend.service_descriptor["limits"]["job_timeout_ms"],
            )

    def test_rejects_unknown_contract_and_nested_keys(self) -> None:
        with self.assertRaisesRegex(
            EngineeringContractError, "contract_fields_invalid"
        ):
            self._load_changed(lambda value: value.__setitem__("extra", True))
        with self.assertRaisesRegex(
            EngineeringContractError, "producer_usage_envelope_fields_invalid"
        ):
            self._load_changed(
                lambda value: value["producer"]["usage_envelope"].__setitem__(
                    "extra", 1
                )
            )

    def test_requires_exact_decimal_budget_partition(self) -> None:
        mutations = (
            ("cloud_scorer_rmb", "13"),
            ("producer_rmb", "17"),
            ("rmb_per_usd", "7.4"),
            ("total_rmb", "31"),
        )
        for field, replacement in mutations:
            with self.subTest(field=field), self.assertRaisesRegex(
                EngineeringContractError, "budget_identity_invalid"
            ):
                self._load_changed(
                    lambda value, field=field, replacement=replacement: value[
                        "budgets"
                    ].__setitem__(field, replacement)
                )
        with self.assertRaisesRegex(
            EngineeringContractError, "cloud_scorer_budget_invalid"
        ):
            self._load_changed(
                lambda value: value["budgets"].__setitem__("cloud_scorer_rmb", 12)
            )

    def test_binds_descriptor_paths_and_exact_identities(self) -> None:
        with self.assertRaisesRegex(
            EngineeringContractError, "local_descriptor_path_invalid"
        ):
            self._load_changed(
                lambda value: value["backends"]["local"].__setitem__(
                    "descriptor", CLOUD_DESCRIPTOR
                )
            )
        with self.assertRaisesRegex(
            EngineeringContractError, "local_service_identity_invalid"
        ):
            self._load_changed(
                change_local=lambda value: value["service_descriptor"]["identity"][
                    "implementation"
                ].__setitem__("revision", "drifted")
            )
        with self.assertRaisesRegex(
            EngineeringContractError, "cloud_provider_identity_invalid"
        ):
            self._load_changed(
                change_cloud=lambda value: value["provider"].__setitem__(
                    "model", "drifted"
                )
            )

    def test_requires_client_deadline_above_descriptor_job_budget(self) -> None:
        for backend in ("local", "cloud"):
            descriptor = _json(
                LOCAL_DESCRIPTOR if backend == "local" else CLOUD_DESCRIPTOR
            )
            job_timeout = descriptor["service_descriptor"]["limits"]["job_timeout_ms"]
            with self.subTest(backend=backend), self.assertRaisesRegex(
                EngineeringContractError,
                f"{backend}_call_timeout_not_above_job_budget",
            ):
                self._load_changed(
                    lambda value, backend=backend, job_timeout=job_timeout: value[
                        "backends"
                    ][backend].__setitem__("client_call_timeout_ms", job_timeout)
                )

    def test_freezes_producer_model_effort_timeout_and_envelope(self) -> None:
        changes = (
            lambda value: value["producer"].__setitem__("model_alias", "luna"),
            lambda value: value["producer"].__setitem__("reasoning_effort", "medium"),
            lambda value: value["producer"].__setitem__("run_timeout_seconds", 599),
            lambda value: value["producer"]["usage_envelope"].__setitem__(
                "max_input_tokens", 31000
            ),
            lambda value: value["producer"]["usage_envelope"].__setitem__(
                "max_output_tokens", 3000
            ),
        )
        for index, change in enumerate(changes):
            with self.subTest(index=index), self.assertRaisesRegex(
                EngineeringContractError, "producer_identity_invalid"
            ):
                self._load_changed(change)

    def test_cases_are_bounded_unique_and_cover_both_branches(self) -> None:
        with self.assertRaisesRegex(
            EngineeringContractError, "commissioning_case_count_invalid"
        ):
            self._load_changed(
                lambda value: value.__setitem__(
                    "commissioning_cases", value["commissioning_cases"][:1]
                )
            )
        with self.assertRaisesRegex(
            EngineeringContractError, "commissioning_case_id_invalid"
        ):
            self._load_changed(
                lambda value: value["commissioning_cases"][1].__setitem__(
                    "case_id", value["commissioning_cases"][0]["case_id"]
                )
            )
        with self.assertRaisesRegex(
            EngineeringContractError, "commissioning_case_branches_incomplete"
        ):
            self._load_changed(
                lambda value: [
                    case.__setitem__("expected_engineering_branch", "pass")
                    for case in value["commissioning_cases"]
                ]
            )
        with self.assertRaisesRegex(EngineeringContractError, "packet_identity_invalid"):
            self._load_changed(
                lambda value: value["commissioning_cases"][0]["packet"][
                    "candidate"
                ].__setitem__("summary", "x" * 1025)
            )
        with self.assertRaisesRegex(EngineeringContractError, "packet_fields_invalid"):
            self._load_changed(
                lambda value: value["commissioning_cases"][0]["packet"].__setitem__(
                    "label", "REWRITE"
                )
            )

    def test_accepts_two_to_four_cases_without_requiring_one_per_branch(self) -> None:
        two = self._load_changed(
            lambda value: value.__setitem__(
                "commissioning_cases", value["commissioning_cases"][:2]
            )
        )
        self.assertEqual(len(two.commissioning_cases), 2)

        def add_fourth(value: dict[str, Any]) -> None:
            fourth = copy.deepcopy(value["commissioning_cases"][1])
            fourth["case_id"] = "synthetic-complete-bounded-v3"
            value["commissioning_cases"].append(fourth)

        four = self._load_changed(add_fourth)
        self.assertEqual(len(four.commissioning_cases), 4)


if __name__ == "__main__":
    unittest.main()
