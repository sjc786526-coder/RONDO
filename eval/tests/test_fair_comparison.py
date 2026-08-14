"""E-B8 fair-comparison contracts: projection, preflight, repeats, conditions."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from rondo_eval.api_budget_proxy import (
    LoopbackResponsesProxy,
    ModelPricing,
    PersistentBudgetLedger,
)
from rondo_eval import preflight_cli
from rondo_eval.config import RepoPaths
from rondo_eval.contracts import ContractError, Product, Side, product_for_side
from rondo_eval.terminal_bench.baseline import (
    BASE_ROUNDS,
    FAIR_COMPARISON_SCHEMA_VERSION,
    BaselineError,
    BaselineRun,
    BaselineStatus,
    ConditionalRun,
    _parse_comparison_block,
    assess_baseline,
    campaign_baseline_contract,
    campaign_slot_total,
    load_historical_campaign_identity,
)
from rondo_eval.terminal_bench.scoring import TaskOutcome
from rondo_eval.fair_comparison import (
    AGGREGATION_STRICT_MAJORITY,
    TASK_INDEPENDENT_PROJECTION_VERSION,
    ComparisonConditions,
    FairComparisonError,
    NoUpstreamTransport,
    RepeatContract,
    SymmetryPreflight,
    aggregate_repeat_outcomes,
    compare_task_independent,
    project_task_independent,
    stub_preflight,
    task_independent_contract,
)


MAIN_PRICING = ModelPricing(
    model_id="profile-main-model",
    input_usd_per_million=Decimal("5.00"),
    cached_input_usd_per_million=Decimal("0.50"),
    output_usd_per_million=Decimal("30.00"),
    long_context_threshold_tokens=272_000,
    long_context_input_multiplier=Decimal("2"),
    long_context_output_multiplier=Decimal("1.5"),
    cache_write_input_multiplier=Decimal("1.25"),
    price_source_url="https://platform.openai.com/docs/pricing",
    price_snapshot_date="2026-08-01",
)
GUARDIAN_PRICING = ModelPricing(
    model_id="profile-guardian-model",
    input_usd_per_million=Decimal("0.20"),
    cached_input_usd_per_million=Decimal("0.02"),
    output_usd_per_million=Decimal("1.20"),
    long_context_threshold_tokens=272_000,
    long_context_input_multiplier=Decimal("2"),
    long_context_output_multiplier=Decimal("1.5"),
    cache_write_input_multiplier=Decimal("1.25"),
    price_source_url="https://platform.openai.com/docs/pricing",
    price_snapshot_date="2026-08-01",
)

# The developer prefix is where Responses Lite puts the effective policy and
# the catalog-derived tool descriptions -- the exact partition that produced
# the historical 161-token asymmetry.
_DEVELOPER_PREFIX = {
    "type": "message",
    "role": "developer",
    "content": [
        {
            "type": "input_text",
            "text": (
                "# Policy\nfrozen policy text\n"
                "# AdditionalTools\nspawn_agent: models are "
                "alpha, beta, gamma, delta, epsilon, zeta, eta, theta"
            ),
        }
    ],
}


def _request(
    *,
    prompt: str = "solve the frozen task",
    developer_text: str | None = None,
    tools: list[dict[str, object]] | None = None,
    instructions: str | None = "frozen base instructions",
    effort: str = "low",
    model: str = MAIN_PRICING.model_id,
    guardian: bool = False,
) -> dict[str, object]:
    prefix = json.loads(json.dumps(_DEVELOPER_PREFIX))
    if developer_text is not None:
        prefix["content"][0]["text"] = developer_text
    body: dict[str, object] = {
        "model": model,
        "instructions": instructions,
        "reasoning": {"effort": effort},
        "stream": False,
        "tools": tools
        if tools is not None
        else [
            {"type": "function", "name": "shell", "description": "run a command"},
            {"type": "function", "name": "apply_patch", "description": "edit files"},
        ],
        "input": [
            prefix,
            {"type": "message", "role": "user", "content": prompt},
        ],
    }
    if guardian:
        body["model"] = GUARDIAN_PRICING.model_id
    return body


class TaskIndependentProjectionTests(unittest.TestCase):
    def test_projection_excludes_the_task_body(self) -> None:
        projected = project_task_independent(_request(prompt="task A"))
        encoded = json.dumps(projected)
        self.assertNotIn("task A", encoded)
        self.assertEqual(
            projected["projection_version"], TASK_INDEPENDENT_PROJECTION_VERSION
        )
        prefix = projected["partitions"]["stable_input_prefix"]
        self.assertEqual(len(prefix), 1)
        self.assertEqual(prefix[0]["role"], "developer")

    def test_different_task_bodies_are_not_contract_drift(self) -> None:
        first = task_independent_contract(_request(prompt="task A"))
        second = task_independent_contract(_request(prompt="a completely different task"))
        self.assertEqual(compare_task_independent(first, second), ())

    def test_every_stable_partition_is_attributable(self) -> None:
        base = task_independent_contract(_request())
        cases = {
            "task_independent_tool_specs_differs": _request(
                tools=[{"type": "function", "name": "shell", "description": "changed"}]
            ),
            "task_independent_instructions_differs": _request(
                instructions="different base instructions"
            ),
            "task_independent_stable_input_prefix_differs": _request(
                developer_text="# Policy\nfrozen policy text\n# AdditionalTools\n"
                "spawn_agent: models are alpha"
            ),
            "task_independent_sampling_contract_differs": _request(effort="high"),
        }
        for reason, variant in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(
                    compare_task_independent(base, task_independent_contract(variant)),
                    (reason,),
                )

    def test_output_schema_partition_is_compared(self) -> None:
        schema = {"type": "json_schema", "schema": {"type": "object"}}
        first = _request()
        first["text"] = {"format": schema}
        second = _request()
        second["text"] = {"format": {"type": "json_schema", "schema": {"type": "string"}}}
        self.assertEqual(
            compare_task_independent(
                task_independent_contract(first),
                task_independent_contract(second),
            ),
            ("task_independent_output_schema_differs",),
        )

    def test_trimmed_catalog_asymmetry_is_detected(self) -> None:
        """The historical failure mode: one side sees fewer picker models."""

        codex = _request(
            developer_text=(
                "# Policy\nfrozen policy text\n"
                "# AdditionalTools\nspawn_agent: models are alpha"
            )
        )
        rondo = _request()
        self.assertIn(
            "task_independent_stable_input_prefix_differs",
            compare_task_independent(
                task_independent_contract(rondo),
                task_independent_contract(codex),
            ),
        )


class SymmetryPreflightTests(unittest.TestCase):
    def test_symmetric_pair_passes_without_any_upstream(self) -> None:
        preflight = stub_preflight(
            (
                ("task-1", "main", Side.RONDO, _request(prompt="rondo view")),
                ("task-1", "main", Side.CODEX, _request(prompt="codex view")),
            )
        )
        self.assertFalse(preflight.allow_upstream)
        self.assertEqual(len(preflight.observed), 2)
        with self.assertRaises(FairComparisonError):
            NoUpstreamTransport().open("https://provider.example/v1/responses")

    def test_cross_side_asymmetry_fails_closed_with_reasons(self) -> None:
        preflight = SymmetryPreflight()
        preflight.register(
            task_id="task-1", role="main", side=Side.RONDO, request=_request()
        )
        with self.assertRaises(FairComparisonError) as caught:
            preflight.register(
                task_id="task-1",
                role="main",
                side=Side.CODEX,
                request=_request(
                    developer_text="# Policy\nfrozen policy text\n"
                    "# AdditionalTools\nspawn_agent: models are alpha"
                ),
            )
        self.assertEqual(
            caught.exception.reasons,
            ("cross_side_asymmetry", "task_independent_stable_input_prefix_differs"),
        )

    def test_full_request_digests_are_recorded_but_never_asserted_equal(self) -> None:
        preflight = stub_preflight(
            (
                ("task-1", "main", Side.RONDO, _request(prompt="rondo view")),
                ("task-1", "main", Side.CODEX, _request(prompt="codex view")),
            )
        )
        provenance = preflight.provenance()
        digests = {
            item["full_request_sha256"] for item in provenance["observed_requests"]
        }
        self.assertEqual(len(digests), 2)
        self.assertEqual(len(provenance["frozen_contracts"]), 1)

    def test_roles_are_frozen_independently(self) -> None:
        preflight = SymmetryPreflight()
        preflight.register(
            task_id="task-1", role="main", side=Side.RONDO, request=_request()
        )
        guardian = _request(guardian=True, instructions="guardian instructions")
        preflight.register(
            task_id="task-1", role="guardian", side=Side.RONDO, request=guardian
        )
        preflight.register(
            task_id="task-1", role="guardian", side=Side.CODEX, request=guardian
        )

    def test_invalid_identity_is_rejected(self) -> None:
        preflight = SymmetryPreflight()
        for kwargs, reason in (
            ({"task_id": "Bad Task", "role": "main"}, "preflight_task_id_invalid"),
            ({"task_id": "task-1", "role": "sidecar"}, "preflight_role_invalid"),
        ):
            with self.subTest(reason=reason), self.assertRaises(
                FairComparisonError
            ) as caught:
                preflight.register(side=Side.RONDO, request=_request(), **kwargs)
            self.assertEqual(caught.exception.reasons, (reason,))


class _CountingTransport:
    """Records every upstream attempt and refuses to make one."""

    def __init__(self) -> None:
        self.opens = 0

    def open(self, *_args: object, **_kwargs: object) -> object:
        self.opens += 1
        raise AssertionError("the preflight must stop the request before this point")


class ProxyPreflightGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.transport = _CountingTransport()
        self.ledger = PersistentBudgetLedger(
            self.root / "budget.json",
            batch_id="p2-preflight",
            total_cap_usd="80",
            default_run_cap_usd="40",
        )
        self.preflight = SymmetryPreflight()
        self.preflight.register(
            task_id="task-1", role="main", side=Side.RONDO, request=_request()
        )
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key="sk-test-never-persist-this-value",
            ledger=self.ledger,
            run_id="preflight-r1",
            metadata_path=self.root / "metadata.json",
            main_model=MAIN_PRICING.model_id,
            main_effort="low",
            main_pricing=MAIN_PRICING,
            guardian_model=GUARDIAN_PRICING.model_id,
            guardian_pricing=GUARDIAN_PRICING,
            guardian_effort="low",
            max_attempts=1,
            retry_backoff_seconds=0.0,
            unbilled_retry_statuses=(503,),
            symmetry_preflight=self.preflight,
            preflight_side=Side.CODEX,
            preflight_task_id="task-1",
            _transport=self.transport,
        ).start()

    def tearDown(self) -> None:
        self.proxy.close()
        self.ledger.close()
        self.temp.cleanup()

    def _post(self, body: dict[str, object]) -> tuple[int, dict[str, object]]:
        request = Request(
            self.proxy.base_url + "/responses",
            data=json.dumps(body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.proxy.downstream_api_key}",
                "X-RONDO-Eval-Request-Id": "request-1",
                "X-RONDO-Eval-Role": "main",
                "User-Agent": "codex_cli_rs/0.147.0 (proxy-test)",
                "originator": "codex_cli_rs",
            },
            method="POST",
        )
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            return error.code, json.loads(error.read())
        with response:
            return response.status, json.loads(response.read())

    def test_asymmetric_request_is_rejected_before_any_upstream_attempt(self) -> None:
        status, payload = self._post(
            _request(
                prompt="codex view",
                developer_text="# Policy\nfrozen policy text\n"
                "# AdditionalTools\nspawn_agent: models are alpha",
            )
        )
        self.assertEqual(status, 409)
        self.assertEqual(
            payload["error"]["code"], "cross_side_asymmetry"
        )
        self.assertEqual(self.transport.opens, 0)
        self.assertEqual(self.ledger.snapshot()["runs"]["preflight-r1"]["requests"], {})

    def test_symmetric_request_passes_the_gate(self) -> None:
        # The counting transport asserts if the request survives the gate, so a
        # non-409 status is itself the proof that the preflight admitted it.
        status, _payload = self._post(_request(prompt="codex view"))
        self.assertNotEqual(status, 409)
        self.assertEqual(self.transport.opens, 1)


class RepeatContractTests(unittest.TestCase):
    def test_odd_repeats_of_at_least_three_are_required(self) -> None:
        cases = {
            2: "repeat_count_below_minimum",
            1: "repeat_count_below_minimum",
            4: "repeat_count_not_odd",
            11: "repeat_count_below_minimum",
        }
        for repeats, reason in cases.items():
            with self.subTest(repeats=repeats), self.assertRaises(
                FairComparisonError
            ) as caught:
                RepeatContract(repeats, AGGREGATION_STRICT_MAJORITY, "pilot").validate()
            self.assertEqual(caught.exception.reasons, (reason,))
        RepeatContract(3, AGGREGATION_STRICT_MAJORITY, "pilot").validate()
        RepeatContract(5, AGGREGATION_STRICT_MAJORITY, "pilot").validate()

    def test_unfrozen_or_unknown_formula_is_rejected(self) -> None:
        with self.assertRaises(FairComparisonError) as caught:
            RepeatContract.from_dict(None)
        self.assertEqual(caught.exception.reasons, ("repeat_contract_not_frozen",))
        with self.assertRaises(FairComparisonError) as caught:
            RepeatContract.from_dict(
                {
                    "repeats_per_task": 3,
                    "aggregation": "pairwise_max",
                    "frozen_after": "pilot",
                }
            )
        self.assertEqual(caught.exception.reasons, ("repeat_aggregation_unsupported",))
        with self.assertRaises(FairComparisonError) as caught:
            RepeatContract.from_dict(
                {
                    "repeats_per_task": 3,
                    "aggregation": AGGREGATION_STRICT_MAJORITY,
                    "frozen_after": "final_results",
                }
            )
        self.assertEqual(caught.exception.reasons, ("repeat_freeze_point_invalid",))

    def test_strict_majority_cannot_tie_and_rejects_resampling(self) -> None:
        contract = RepeatContract(3, AGGREGATION_STRICT_MAJORITY, "pilot")
        self.assertEqual(
            aggregate_repeat_outcomes(
                ("pass", "fail", "pass"),
                contract=contract,
                pass_value="pass",
                fail_value="fail",
            ),
            "pass",
        )
        self.assertEqual(
            aggregate_repeat_outcomes(
                ("fail", "fail", "pass"),
                contract=contract,
                pass_value="pass",
                fail_value="fail",
            ),
            "fail",
        )
        with self.assertRaises(FairComparisonError) as caught:
            aggregate_repeat_outcomes(
                ("pass", "fail"),
                contract=contract,
                pass_value="pass",
                fail_value="fail",
            )
        self.assertEqual(caught.exception.reasons, ("repeat_sample_count_differs",))

    def test_non_terminal_outcomes_never_enter_aggregation(self) -> None:
        contract = RepeatContract(3, AGGREGATION_STRICT_MAJORITY, "pilot")
        with self.assertRaises(FairComparisonError) as caught:
            aggregate_repeat_outcomes(
                ("pass", "infra", "pass"),
                contract=contract,
                pass_value="pass",
                fail_value="fail",
            )
        self.assertEqual(caught.exception.reasons, ("repeat_outcome_not_terminal",))


class ComparisonConditionsTests(unittest.TestCase):
    @staticmethod
    def _conditions(**overrides: object) -> ComparisonConditions:
        values: dict[str, object] = {
            "eval_harness_commit": "a" * 40,
            "upstream_timeout_seconds": "180.000",
            "provider_profile_sha256": "b" * 64,
            "catalog_artifact_sha256": "c" * 64,
            "task_image_digests": (("task-1", "sha256:1"), ("task-2", "sha256:2")),
        }
        values.update(overrides)
        return ComparisonConditions(**values)  # type: ignore[arg-type]

    def test_matching_conditions_are_accepted(self) -> None:
        self._conditions().require_match(self._conditions())

    def test_every_frozen_condition_drift_is_attributable(self) -> None:
        cases = {
            "eval_harness_commit_differs": {"eval_harness_commit": "d" * 40},
            "upstream_timeout_differs": {"upstream_timeout_seconds": "90.000"},
            "provider_profile_differs": {"provider_profile_sha256": "e" * 64},
            "catalog_artifact_differs": {"catalog_artifact_sha256": "f" * 64},
            "task_image_differs": {
                "task_image_digests": (("task-1", "sha256:1"), ("task-2", "sha256:9"))
            },
        }
        for reason, overrides in cases.items():
            with self.subTest(reason=reason), self.assertRaises(
                FairComparisonError
            ) as caught:
                self._conditions().require_match(self._conditions(**overrides))
            self.assertEqual(caught.exception.reasons, (reason,))

    def test_round_trip_through_the_lock_representation(self) -> None:
        conditions = self._conditions()
        self.assertEqual(
            ComparisonConditions.from_dict(conditions.to_dict()), conditions
        )
        with self.assertRaises(FairComparisonError) as caught:
            ComparisonConditions.from_dict({"eval_harness_commit": "a" * 40})
        self.assertEqual(
            caught.exception.reasons, ("comparison_conditions_not_frozen",)
        )


class ProductIdentityTests(unittest.TestCase):
    def test_product_is_orthogonal_to_the_comparison_side(self) -> None:
        self.assertEqual(product_for_side(Side.RONDO, None), Product.RONDO_LOCAL)
        self.assertEqual(
            product_for_side(Side.RONDO, Product.RONDO_MULTI), Product.RONDO_MULTI
        )
        self.assertIsNone(product_for_side(Side.CODEX, None))

    def test_the_frozen_upstream_never_carries_a_product(self) -> None:
        with self.assertRaises(ContractError):
            product_for_side(Side.CODEX, Product.RONDO_LOCAL)

    def test_codex_is_not_a_product_value(self) -> None:
        self.assertNotIn("codex", {item.value for item in Product})


class PreflightCliTests(unittest.TestCase):
    """The offline entry point must be usable and structurally offline."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write(self, name: str, body: dict[str, object]) -> Path:
        path = self.root / name
        path.write_text(json.dumps(body), encoding="utf-8")
        return path

    def _run(self, rondo: dict[str, object], codex: dict[str, object]) -> int:
        return preflight_cli.main(
            [
                "--task-id",
                "task-1",
                "--rondo-request",
                str(self._write("rondo.json", rondo)),
                "--codex-request",
                str(self._write("codex.json", codex)),
            ]
        )

    def test_symmetric_requests_exit_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self._run(_request(prompt="rondo"), _request(prompt="codex"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["status"], "symmetric")

    def test_asymmetric_requests_exit_non_zero_with_reasons(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = self._run(
                _request(),
                _request(
                    developer_text="# Policy\nfrozen policy text\n"
                    "# AdditionalTools\nspawn_agent: models are alpha"
                ),
            )
        self.assertEqual(code, 3)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["status"], "blocked")
        self.assertIn(
            "task_independent_stable_input_prefix_differs", payload["reasons"]
        )

    def test_unreadable_request_is_blocked_not_ignored(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = preflight_cli.main(
                [
                    "--task-id",
                    "task-1",
                    "--rondo-request",
                    str(self.root / "missing.json"),
                    "--codex-request",
                    str(self._write("codex.json", _request())),
                ]
            )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out.getvalue())["status"], "blocked")


class _CampaignFixture:
    """Build v6 and v7 campaign identities from one registered historical lock."""

    tasks = tuple(f"terminal-bench/task-{index}" for index in range(10))

    @staticmethod
    def v6():
        legacy = load_historical_campaign_identity(RepoPaths.discover(Path.cwd()), 9)
        return replace(
            legacy,
            schema_version=6,
            budget={
                **legacy.budget,
                "campaign_cap_usd": "1600.000000",
                "prior_estimated_usd": "1136.113528",
                "max_run_slots": 321,
            },
            baseline=campaign_baseline_contract(6),
        )

    @classmethod
    def v7(cls, *, repeats: int = 3, comparison_overrides: dict | None = None):
        base = cls.v6()
        catalog_identity = {
            "sha256": "c" * 64,
            "projection_algorithm": "full_catalog_with_auto_review_override",
            "projection_version": 2,
            "main_model": "gpt-5.6-sol",
            "guardian_model": "gpt-5.6-sol",
            "override_target_slug": "gpt-5.6-sol",
            "model_slugs": [f"model-{index}" for index in range(8)],
            "sources": [
                {
                    "side": "upstream",
                    "commit": "a" * 40,
                    "path": "codex-rs/models-manager/models.json",
                    "blob_id": "f" * 40,
                },
                {
                    "side": "rondo",
                    "commit": "b" * 40,
                    "path": "mydev/codex-rs/models-manager/models.json",
                    "blob_id": "f" * 40,
                },
            ],
        }
        comparison = {
            "repeat_contract": RepeatContract(
                repeats, AGGREGATION_STRICT_MAJORITY, "pilot"
            ).to_dict(),
            "comparison_conditions": ComparisonConditions(
                eval_harness_commit="d" * 40,
                upstream_timeout_seconds="180.000",
                provider_profile_sha256="e" * 64,
                catalog_artifact_sha256="c" * 64,
                task_image_digests=tuple(
                    (task_id, f"sha256:{index}")
                    for index, task_id in enumerate(sorted(cls.tasks))
                ),
            ).to_dict(),
            "catalog_identity": catalog_identity,
            "product": Product.RONDO_LOCAL.value,
        }
        comparison.update(comparison_overrides or {})
        return replace(
            base,
            schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
            budget={
                **base.budget,
                "max_run_slots": campaign_slot_total(
                    task_count=10,
                    max_attempts=4,
                    conditional_repeats_per_side=repeats - 1,
                ),
            },
            baseline=campaign_baseline_contract(
                FAIR_COMPARISON_SCHEMA_VERSION,
                conditional_repeats_per_side=repeats - 1,
            ),
            comparison=comparison,
        )


class CampaignExecutionOrderTests(unittest.TestCase):
    def test_historical_campaigns_keep_round_blocked_order(self) -> None:
        order = _CampaignFixture.v6().base_round_order
        self.assertEqual(
            tuple(round_id for _task, round_id in order[:10]),
            ("aa-rondo-1",) * 10,
        )

    def test_fair_comparison_campaigns_interleave_by_task(self) -> None:
        identity = _CampaignFixture.v7()
        order = identity.base_round_order
        self.assertEqual(
            tuple(round_id for _task, round_id in order[:4]), BASE_ROUNDS
        )
        first_task = order[0][0]
        self.assertEqual(
            tuple(task_id for task_id, _round in order[:4]), (first_task,) * 4
        )
        # Every side sees each task within the same four-slot window rather
        # than a whole round apart.
        self.assertEqual(len({task for task, _round in order}), 10)
        self.assertEqual(len(order), 40)

    def test_interleaved_slot_plan_stays_within_the_frozen_run_budget(self) -> None:
        identity = _CampaignFixture.v7()
        slots = identity.slots
        self.assertEqual(len(slots), identity.max_run_slots)
        self.assertEqual(len(slots), 321)
        first_base = [item for item in slots if item.kind == "base"][:4]
        self.assertEqual(
            [item.round_id for item in first_base], list(BASE_ROUNDS)
        )
        self.assertEqual(len({item.task_id for item in first_base}), 1)

    def test_five_repeats_expand_the_conditional_plan(self) -> None:
        identity = _CampaignFixture.v7(repeats=5)
        self.assertEqual(identity.conditional_repeat_range, (1, 2, 3, 4))
        self.assertEqual(len(identity.slots), identity.max_run_slots)
        self.assertEqual(len(identity.slots), 1 + 160 + 320)


class CampaignFairComparisonContractTests(unittest.TestCase):
    def test_a_v7_campaign_without_a_frozen_repeat_contract_is_refused(self) -> None:
        for block in (
            None,
            {},
            {
                "comparison_conditions": {},
                "catalog_identity": {},
                "product": "rondo-local",
            },
        ):
            with self.subTest(block=block), self.assertRaisesRegex(
                BaselineError, "fair-comparison contract is not frozen"
            ):
                _parse_comparison_block(
                    {"comparison": block},
                    schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
                )

    def test_even_or_short_repeat_counts_cannot_be_frozen(self) -> None:
        for repeats in (2, 4):
            block = _CampaignFixture.v7().comparison
            block = {
                **block,
                "repeat_contract": {
                    "repeats_per_task": repeats,
                    "aggregation": AGGREGATION_STRICT_MAJORITY,
                    "frozen_after": "pilot",
                },
            }
            with self.subTest(repeats=repeats), self.assertRaisesRegex(
                BaselineError, "fair-comparison contract is invalid"
            ):
                _parse_comparison_block(
                    {"comparison": block},
                    schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
                )

    def test_historical_locks_may_not_carry_a_comparison_block(self) -> None:
        with self.assertRaisesRegex(BaselineError, "cannot carry"):
            _parse_comparison_block({"comparison": {}}, schema_version=6)
        self.assertIsNone(_parse_comparison_block({}, schema_version=6))

    def test_catalog_provenance_must_name_both_sources(self) -> None:
        identity = _CampaignFixture.v7()
        block = dict(identity.comparison)
        catalog = json.loads(json.dumps(block["catalog_identity"]))
        catalog["sources"] = [catalog["sources"][0]]
        with self.assertRaisesRegex(BaselineError, "provenance is incomplete"):
            _parse_comparison_block(
                {"comparison": {**block, "catalog_identity": catalog}},
                schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
            )

    def test_shared_catalog_identity_drift_fails_closed(self) -> None:
        identity = _CampaignFixture.v7()
        identity.validate_shared_model_catalog(identity.catalog_identity)
        drifted = json.loads(json.dumps(identity.catalog_identity))
        drifted["sources"][1]["blob_id"] = "9" * 40
        with self.assertRaisesRegex(BaselineError, "drifted from the campaign lock"):
            identity.validate_shared_model_catalog(drifted)

    def test_a_fair_comparison_campaign_refuses_the_codex_only_catalog(self) -> None:
        identity = _CampaignFixture.v7()
        with self.assertRaisesRegex(BaselineError, "shared catalog artifact"):
            identity.validate_frozen_model_catalog(
                source_commit="a" * 40,
                sha256="c" * 64,
                main_model="gpt-5.6-sol",
                guardian_model="gpt-5.6-sol",
            )

    def test_product_identity_is_readable_and_not_codex(self) -> None:
        self.assertEqual(_CampaignFixture.v7().product, Product.RONDO_LOCAL)
        multi = _CampaignFixture.v7(
            comparison_overrides={"product": Product.RONDO_MULTI.value}
        )
        self.assertEqual(multi.product, Product.RONDO_MULTI)
        with self.assertRaisesRegex(BaselineError, "product identity is invalid"):
            _parse_comparison_block(
                {
                    "comparison": {
                        **_CampaignFixture.v7().comparison,
                        "product": "codex",
                    }
                },
                schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
            )


class LayeredAssessmentTests(unittest.TestCase):
    tasks = _CampaignFixture.tasks
    contract = RepeatContract(3, AGGREGATION_STRICT_MAJORITY, "pilot")

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
        rondo: tuple[TaskOutcome, TaskOutcome],
        codex: tuple[TaskOutcome, TaskOutcome],
    ) -> tuple[ConditionalRun, ...]:
        values: list[ConditionalRun] = []
        for side, outcomes in ((Side.RONDO, rondo), (Side.CODEX, codex)):
            for repeat, outcome in enumerate(outcomes, start=1):
                values.append(
                    ConditionalRun(
                        task_id,
                        side,
                        repeat,
                        1,
                        outcome,
                        f"conditional-{task_id}-{side.value}-{repeat}-a1",
                    )
                )
        return tuple(values)

    def test_three_layers_are_reported_separately(self) -> None:
        result = assess_baseline(
            self.tasks, self._base(), (), repeat_contract=self.contract
        )
        self.assertEqual(result.status, BaselineStatus.PASSED)
        self.assertEqual(
            tuple(layer.name for layer in result.layers),
            ("aa_consistency", "cross_side", "directional"),
        )
        for layer in result.layers:
            self.assertEqual(layer.status, BaselineStatus.PASSED)
        self.assertEqual(dict(result.layer("aa_consistency").metrics)["sigma"], 0)

    def test_conditional_repeats_change_the_final_cross_side_result(self) -> None:
        """A triggered task whose repeats go RONDO's way must clear the gate."""

        task_id = self.tasks[0]
        base = self._base({("ab-rondo-1", task_id): TaskOutcome.FAIL})
        result = assess_baseline(
            self.tasks,
            base,
            self._conditional(
                task_id,
                rondo=(TaskOutcome.PASS, TaskOutcome.PASS),
                codex=(TaskOutcome.PASS, TaskOutcome.PASS),
            ),
            repeat_contract=self.contract,
        )
        cross = dict(result.layer("cross_side").metrics)
        self.assertEqual(cross["base_delta"], 1)
        self.assertEqual(cross["delta"], 0)
        self.assertEqual(result.delta, 0)
        self.assertEqual(result.status, BaselineStatus.PASSED)
        self.assertIn((task_id, "rondo", TaskOutcome.PASS), result.aggregated_outcomes)

    def test_a_majority_failure_keeps_the_cross_side_gate_failing(self) -> None:
        task_id = self.tasks[0]
        base = self._base({("ab-rondo-1", task_id): TaskOutcome.FAIL})
        result = assess_baseline(
            self.tasks,
            base,
            self._conditional(
                task_id,
                rondo=(TaskOutcome.FAIL, TaskOutcome.PASS),
                codex=(TaskOutcome.PASS, TaskOutcome.PASS),
            ),
            repeat_contract=self.contract,
        )
        self.assertEqual(result.delta, 1)
        self.assertEqual(result.layer("cross_side").status, BaselineStatus.FAILED)
        self.assertEqual(result.layer("aa_consistency").status, BaselineStatus.PASSED)
        self.assertEqual(result.layer("directional").status, BaselineStatus.PASSED)
        self.assertEqual(result.status, BaselineStatus.FAILED)

    def test_directional_backstop_is_its_own_layer(self) -> None:
        task_id = self.tasks[0]
        base = self._base({("ab-rondo-1", task_id): TaskOutcome.FAIL})
        result = assess_baseline(
            self.tasks,
            base,
            self._conditional(
                task_id,
                rondo=(TaskOutcome.FAIL, TaskOutcome.FAIL),
                codex=(TaskOutcome.PASS, TaskOutcome.PASS),
            ),
            repeat_contract=self.contract,
        )
        directional = result.layer("directional")
        self.assertEqual(directional.status, BaselineStatus.FAILED)
        self.assertEqual(
            directional.reasons, (f"stable_directional_regression:{task_id}",)
        )

    def test_historical_assessment_is_unchanged_without_a_repeat_contract(self) -> None:
        legacy = assess_baseline(self.tasks, self._base(), ())
        self.assertEqual(legacy.layers, ())
        self.assertEqual(legacy.aggregated_outcomes, ())
        self.assertEqual(legacy.status, BaselineStatus.PASSED)

    def test_a_blocked_comparison_never_reports_capability_numbers(self) -> None:
        outcomes = {
            ("aa-rondo-1", task_id): TaskOutcome.INFRA for task_id in self.tasks[:3]
        }
        result = assess_baseline(
            self.tasks,
            self._base(outcomes, second=outcomes),
            (),
            repeat_contract=self.contract,
        )
        self.assertEqual(result.status, BaselineStatus.BLOCKED)
        self.assertEqual(result.layers, ())
        self.assertIsNone(result.delta)


if __name__ == "__main__":
    unittest.main()
