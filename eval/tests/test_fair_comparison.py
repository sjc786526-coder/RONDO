"""E-B8 fair-comparison contracts: projection, preflight, repeats, conditions."""

from __future__ import annotations

import contextlib
import asyncio
import inspect
import io
import json
import subprocess
import tempfile
import unittest
from unittest import mock
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from rondo_eval.api_budget_proxy import (
    GUARDIAN_OUTPUT_SCHEMA,
    LoopbackResponsesProxy,
    ModelPricing,
    PersistentBudgetLedger,
    canonical_request_sha256,
)
from rondo_eval import preflight_cli
from rondo_eval.config import RepoPaths
from rondo_eval.contracts import (
    AUTO_REVIEW_EVIDENCE_DIR,
    ContractError,
    Product,
    ProviderProjection,
    RunSpec,
    Side,
    product_for_side,
)
from rondo_eval.terminal_bench.baseline import (
    BASE_ROUNDS,
    CampaignLockRegistration,
    CampaignStateLedger,
    FAIR_COMPARISON_SCHEMA_VERSION,
    BaselineError,
    BaselineRun,
    BaselineStatus,
    ConditionalRun,
    _parse_comparison_block,
    _parse_continuation_references,
    _valid_campaign_budget,
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
    PreflightReceipt,
    RepeatContract,
    SymmetryPreflight,
    aggregate_repeat_outcomes,
    compare_task_independent,
    preflight_receipt_from_stub_run,
    project_task_independent,
    stub_preflight,
    task_independent_contract,
    valid_task_id,
)
from rondo_eval.terminal_bench import (
    baseline_cli,
    baseline_identity,
    preflight_producer,
    results as results_module,
)
from rondo_eval.terminal_bench.baseline_cli import CampaignExecutionError
from rondo_eval.terminal_bench.baseline_identity import (
    CampaignIdentityGenerationError,
    generate_successor_lock,
    validate_successor_run_range,
)
from rondo_eval.terminal_bench.results import HarborResultError
from rondo_eval.terminal_bench.runner import PreparedTerminalBenchRun
from rondo_eval.terminal_bench.__main__ import _load_manifest
from rondo_eval.terminal_bench.freeze import TERMINAL_BENCH_VERSION
from rondo_eval.terminal_bench.live import campaign_terminal_bench_request
from rondo_eval.terminal_bench.task_budget import TASK_BUDGET_ID


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


class _StubTask:
    """The task fields the preflight producer reads."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.image_digest = "sha256:" + "1" * 64


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
        body["text"] = {
            "format": {
                "type": "json_schema",
                "name": "codex_output_schema",
                "strict": True,
                "schema": GUARDIAN_OUTPUT_SCHEMA,
            }
        }
    return body


def _lite_request(
    *,
    prompt: str = "solve the frozen task",
    model_names: tuple[str, ...] = (
        "alpha",
        "beta",
        "gamma",
        "delta",
        "epsilon",
        "zeta",
        "eta",
        "theta",
    ),
    developer_text: str = "frozen Responses Lite developer instructions",
) -> dict[str, object]:
    """Match the frozen Responses Lite wire shape, including AdditionalTools."""

    body = _request(prompt=prompt)
    body.pop("instructions")
    body.pop("tools")
    body["input"] = [
        {
            "type": "additional_tools",
            "role": "developer",
            "tools": [
                {
                    "type": "function",
                    "name": "spawn_agent",
                    "description": "available models: " + ", ".join(model_names),
                }
            ],
        },
        {
            "type": "message",
            "role": "developer",
            "content": [{"type": "input_text", "text": developer_text}],
        },
        {"type": "message", "role": "user", "content": prompt},
    ]
    return body


def _stub_trace(
    label: str,
    *,
    main_instructions: str | None = "frozen base instructions",
    main_developer_text: str | None = None,
) -> tuple[tuple[str, dict[str, object]], ...]:
    """Build the exact approval trajectory captured by the no-API stub."""

    return (
        (
            "main",
            _request(
                prompt=f"{label} main",
                instructions=main_instructions,
                developer_text=main_developer_text,
            ),
        ),
        ("guardian", _request(prompt=f"{label} guardian", guardian=True)),
        (
            "main",
            _request(
                prompt=f"{label} after approval",
                instructions=main_instructions,
                developer_text=main_developer_text,
            ),
        ),
    )


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
        """The historical Lite failure mode: one side sees fewer picker models."""

        rondo = _lite_request(prompt="rondo task body")
        codex = _lite_request(
            prompt="different codex task body", model_names=("alpha",)
        )
        prefix = project_task_independent(rondo)["partitions"][
            "stable_input_prefix"
        ]
        self.assertEqual(
            [item["type"] for item in prefix], ["additional_tools", "message"]
        )
        self.assertIn(
            "task_independent_tool_specs_differs",
            compare_task_independent(
                task_independent_contract(rondo),
                task_independent_contract(codex),
            ),
        )
        self.assertIn(
            "task_independent_stable_input_prefix_differs",
            compare_task_independent(
                task_independent_contract(rondo),
                task_independent_contract(codex),
            ),
        )

    def test_lite_task_body_is_still_excluded(self) -> None:
        first = task_independent_contract(_lite_request(prompt="task A"))
        second = task_independent_contract(_lite_request(prompt="task B"))
        self.assertEqual(compare_task_independent(first, second), ())

    def test_malformed_lite_prefix_fails_closed(self) -> None:
        malformed = _lite_request()
        malformed["input"][0]["tools"] = "not-a-catalog"  # type: ignore[index]
        duplicate = _lite_request()
        duplicate["input"].insert(  # type: ignore[union-attr]
            1, duplicate["input"][0]  # type: ignore[index]
        )
        misplaced = _lite_request()
        misplaced["input"][0], misplaced["input"][1] = (  # type: ignore[index]
            misplaced["input"][1],  # type: ignore[index]
            misplaced["input"][0],  # type: ignore[index]
        )
        mixed = _lite_request()
        mixed["tools"] = []
        for request in (malformed, duplicate, misplaced, mixed):
            with self.subTest(request=request), self.assertRaises(
                FairComparisonError
            ) as caught:
                task_independent_contract(request)
            self.assertEqual(
                caught.exception.reasons,
                ("task_independent_stable_input_prefix_invalid",),
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
            ("task_independent_stable_input_prefix_differs", "cross_side_asymmetry"),
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
            payload["error"]["code"], "task_independent_stable_input_prefix_differs"
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
            "task_image_digests": (
                ("task-1", "sha256:" + "1" * 64),
                ("task-2", "sha256:" + "2" * 64),
            ),
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
                "task_image_digests": (
                    ("task-1", "sha256:" + "1" * 64),
                    ("task-2", "sha256:" + "9" * 64),
                )
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

    @staticmethod
    def catalog_identity(**overrides: object) -> dict:
        value = {
            "sha256": "c" * 64,
            "projection_algorithm": "full_catalog_with_auto_review_override",
            "projection_version": 2,
            "main_model": "gpt-5.6-sol",
            "guardian_model": "gpt-5.6-sol",
            "override_target_slug": "gpt-5.6-sol",
            "model_slugs": ["gpt-5.6-sol", *(f"model-{index}" for index in range(7))],
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
        value.update(overrides)
        return value

    @classmethod
    def v7(cls, *, repeats: int = 3, comparison_overrides: dict | None = None):
        base = cls.v6()
        paths = RepoPaths.discover(Path.cwd())
        bundles = {
            side: {
                **bundle,
                "source_commit": _load_manifest(
                    paths.common_root / bundle["manifest_path"], paths.common_root
                ).source_commit,
            }
            for side, bundle in base.bundles.items()
        }
        catalog_identity = cls.catalog_identity()
        # Bind the declared conditions to the campaign's own authoritative
        # facts so the fixture exercises the real cross-check rather than a
        # self-consistent fiction.
        comparison = {
            "repeat_contract": RepeatContract(
                repeats, AGGREGATION_STRICT_MAJORITY, "pilot"
            ).to_dict(),
            "comparison_conditions": ComparisonConditions(
                eval_harness_commit="d" * 40,
                upstream_timeout_seconds=str(
                    base.baseline["upstream_timeout_seconds"]
                ),
                provider_profile_sha256=str(
                    base.selected_profile["provider_profile_sha256"]
                ),
                catalog_artifact_sha256=str(catalog_identity["sha256"]),
                task_image_digests=tuple(
                    sorted((item.task_id, item.image_digest) for item in base.catalog.tasks)
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
                # A v7 campaign starts fresh inside the exact Plan 051 envelope.
                "campaign_cap_usd": "400.000000",
                "prior_estimated_usd": "0.000000",
                "task_budget_id": TASK_BUDGET_ID,
                "task_budget_cap_usd": "400.000000",
                "task_budget_prior_estimated_usd": "0.000000",
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
            bundles=bundles,
            comparison=comparison,
        )


class CampaignExecutionOrderTests(unittest.TestCase):
    def test_pristine_v7_identity_can_retire_after_zero_api_preflight_defect(
        self,
    ) -> None:
        identity = _CampaignFixture.v7()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with CampaignStateLedger(path, identity=identity) as ledger:
                ledger.retire_preflight_blocked(
                    reason=(
                        "diagnosed_campaign_defect:"
                        "local_implementation_defect:preflight_projection"
                    )
                )
                snapshot = ledger.snapshot()
        self.assertEqual(snapshot["status"], "blocked")
        self.assertTrue(all(row["status"] == "skipped" for row in snapshot["slots"]))
        self.assertTrue(
            all(row["estimated_usd"] == "0.000000" for row in snapshot["slots"])
        )

    def test_historical_campaign_request_keeps_host_provider_defaults(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        identity = _CampaignFixture.v6()
        task = identity.catalog.tasks[0]
        manifest = _load_manifest(
            paths.common_root / identity.bundles["codex"]["manifest_path"],
            paths.common_root,
        )
        request = campaign_terminal_bench_request(
            identity=identity,
            side=Side.CODEX,
            task=task,
            binary=manifest,
            common_root=paths.common_root,
            work_root=paths.common_root / "eval-data/work/historical-contract",
            docker_task_id="historical-contract-codex",
            seccomp_profile=paths.worktree_root
            / identity.no_api_seccomp["profile_path"],
            budget_usd=40.0,
        )
        self.assertIsNone(request.pinned_model_id)
        self.assertIsNone(request.pinned_main_effort)
        self.assertIsNone(request.pinned_guardian_effort)

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
    def test_campaign_durable_record_and_aggregate_reject_product_tampering(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        identity = _CampaignFixture.v7()
        slot = next(item for item in identity.slots if item.side is Side.RONDO)
        manifest_path = paths.common_root / identity.bundles["rondo"]["manifest_path"]
        manifest = _load_manifest(manifest_path, paths.common_root)
        record = {
            "run_id": slot.run_id,
            "track": "tb",
            "side": Side.RONDO.value,
            "product": Product.RONDO_LOCAL.value,
            "binary_sha256": manifest.sha256,
            "config": {
                **identity.selected_profile,
                "private_summary_schema_version": 1,
                "product": Product.RONDO_LOCAL.value,
                "binary_product": Product.RONDO_LOCAL.value,
                "campaign_schema_version": identity.schema_version,
                "campaign_product": Product.RONDO_LOCAL.value,
                "campaign_id": identity.campaign_id,
                "campaign_lock_sha256": identity.lock_sha256,
                "campaign_slot_id": slot.slot_id,
                "binary_source_commit": manifest.source_commit,
                "binary_workspace_lock_normalization": (
                    manifest.workspace_lock_normalization
                ),
                "auto_review_config": {
                    "schema_version": 1,
                    "model": "gpt-5.6-sol",
                    "model_provider": None,
                    "reasoning_effort": "low",
                    "evidence_dir": AUTO_REVIEW_EVIDENCE_DIR,
                },
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            results_root = Path(directory) / "results"
            baseline_cli._validate_campaign_record_product(
                identity, record, common_root=paths.common_root
            )
            float_key = next(
                key
                for key, value in identity.selected_profile.items()
                if isinstance(value, float)
            )
            record["config"][float_key] = True
            with self.assertRaisesRegex(CampaignExecutionError, "selected profile"):
                baseline_cli._validate_campaign_record_product(
                    identity, record, common_root=paths.common_root
                )
            record["config"][float_key] = identity.selected_profile[float_key]
            record["config"]["guardian_model"] = "forged-guardian"
            record["config"]["guardian_effort"] = "high"
            record["config"]["auto_review_config"]["model"] = "forged-guardian"
            record["config"]["auto_review_config"]["reasoning_effort"] = "high"
            with self.assertRaisesRegex(CampaignExecutionError, "selected profile"):
                baseline_cli._validate_campaign_record_product(
                    identity, record, common_root=paths.common_root
                )
            record["config"].update(identity.selected_profile)
            record["config"]["auto_review_config"]["model"] = "gpt-5.6-sol"
            record["config"]["auto_review_config"]["reasoning_effort"] = "low"
            record["config"]["product"] = Product.RONDO_MULTI.value
            with self.assertRaisesRegex(CampaignExecutionError, "product identity"):
                baseline_cli._validate_campaign_record_product(
                    identity, record, common_root=paths.common_root
                )
            record["config"]["product"] = Product.RONDO_LOCAL.value
            record["binary_sha256"] = "f" * 64
            with self.assertRaisesRegex(CampaignExecutionError, "binary differs"):
                baseline_cli._validate_campaign_record_product(
                    identity, record, common_root=paths.common_root
                )

            campaign_root = Path(directory) / "campaign"
            campaign_root.mkdir()
            aggregate = {
                "campaign_id": identity.campaign_id,
                "campaign_lock_sha256": identity.lock_sha256,
                "status": "completed",
                "product": Product.RONDO_MULTI.value,
            }
            (campaign_root / "aggregate.json").write_text(
                json.dumps(aggregate), encoding="utf-8"
            )
            with self.assertRaisesRegex(CampaignExecutionError, "identity drifted"):
                baseline_cli._restore_tracked_aggregate_from_local(
                    campaign_root=campaign_root,
                    identity=identity,
                    results_root=results_root,
                    expected_status="completed",
                )

    def test_real_campaign_request_binds_manifest_runspec_and_product(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        local = _CampaignFixture.v7()
        provider = ProviderProjection(
            provider_id="test",
            display_name="Test provider",
            api="responses",
            base_url="https://provider.example/v1",
            api_key_env="TEST_API_KEY",
            main_model=MAIN_PRICING.model_id,
            main_effort="medium",
            guardian_model=GUARDIAN_PRICING.model_id,
            guardian_effort="low",
            main_pricing=MAIN_PRICING,
            guardian_pricing=GUARDIAN_PRICING,
            max_attempts=5,
            retry_backoff_seconds=1.0,
            unbilled_retry_statuses=(429, 500, 502, 503, 504),
            profile_sha256="d" * 64,
            config_sha256="e" * 64,
        )
        local = replace(
            local,
            selected_profile={
                **provider.to_public_dict(),
                "max_guardian_logical_requests": 3,
            },
        )
        task = local.catalog.tasks[0]
        manifests = {}
        for side in Side:
            manifest_path = paths.common_root / local.bundles[side.value]["manifest_path"]
            manifest = _load_manifest(manifest_path, paths.common_root)
            local.validate_manifest(
                common_root=paths.common_root,
                side=side,
                manifest_path=manifest_path,
                manifest=manifest,
            )
            manifests[side] = manifest
            request = campaign_terminal_bench_request(
                identity=local,
                side=side,
                task=task,
                binary=manifest,
                common_root=paths.common_root,
                work_root=paths.common_root / "eval-data/work/product-contract",
                docker_task_id=f"product-contract-{side.value}",
                seccomp_profile=paths.worktree_root / local.no_api_seccomp["profile_path"],
                budget_usd=40.0,
            )
            self.assertIs(
                request.product,
                Product.RONDO_LOCAL if side is Side.RONDO else None,
            )
            self.assertEqual(request.pinned_model_id, provider.main_model)
            self.assertEqual(request.pinned_main_effort, provider.main_effort)
            self.assertEqual(
                request.pinned_guardian_effort, provider.guardian_effort
            )
            spec = RunSpec(
                side=side,
                batch_id=request.batch_id,
                task_id=task.task_id,
                task_image_digest=task.image_digest,
                binary=manifest,
                terminal_bench_version=TERMINAL_BENCH_VERSION,
                provider=provider,
                product=request.product,
                timeout_seconds=task.timeout_seconds,
                max_retries=0,
                budget_usd=40.0,
            )
            slot = next(
                item
                for item in local.slots
                if item.task_id == task.task_id and item.side is side and item.attempt == 1
            )
            local.validate_spec(spec, slot=slot, task=task)

        multi = _CampaignFixture.v7(
            comparison_overrides={"product": Product.RONDO_MULTI.value}
        )
        multi = replace(multi, selected_profile=local.selected_profile)
        local_manifest_path = paths.common_root / multi.bundles["rondo"]["manifest_path"]
        with self.assertRaisesRegex(BaselineError, "product differs"):
            multi.validate_manifest(
                common_root=paths.common_root,
                side=Side.RONDO,
                manifest_path=local_manifest_path,
                manifest=manifests[Side.RONDO],
            )
        multi_manifest = replace(
            manifests[Side.RONDO], product=Product.RONDO_MULTI.value
        )
        multi_request = campaign_terminal_bench_request(
            identity=multi,
            side=Side.RONDO,
            task=task,
            binary=multi_manifest,
            common_root=paths.common_root,
            work_root=paths.common_root / "eval-data/work/product-contract-multi",
            docker_task_id="product-contract-rondo-multi",
            seccomp_profile=paths.worktree_root / multi.no_api_seccomp["profile_path"],
            budget_usd=40.0,
        )
        self.assertIs(multi_request.product, Product.RONDO_MULTI)
        multi_spec = RunSpec(
            side=Side.RONDO,
            batch_id=multi_request.batch_id,
            task_id=task.task_id,
            task_image_digest=task.image_digest,
            binary=multi_manifest,
            terminal_bench_version=TERMINAL_BENCH_VERSION,
            provider=provider,
            product=multi_request.product,
            timeout_seconds=task.timeout_seconds,
            max_retries=0,
            budget_usd=40.0,
        )
        multi_slot = next(
            item
            for item in multi.slots
            if item.task_id == task.task_id and item.side is Side.RONDO and item.attempt == 1
        )
        multi.validate_spec(multi_spec, slot=multi_slot, task=task)

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


class PreflightReceiptTests(unittest.TestCase):
    """A receipt frozen on a stub must gate the first paid side, not just the second."""

    bundles = {"rondo": "1" * 64, "codex": "2" * 64}

    def _receipt(self, **overrides: object) -> PreflightReceipt:
        values: dict[str, object] = {
            "campaign_id": "p2-b7-canary-baseline-v23",
            "campaign_lock_sha256": "a" * 64,
            "task_id": "terminal-bench/fix-git",
            "bundle_manifest_sha256": dict(self.bundles),
            "requests_by_side": {
                Side.RONDO: _stub_trace("rondo"),
                Side.CODEX: _stub_trace("codex"),
            },
        }
        values.update(overrides)
        return preflight_receipt_from_stub_run(**values)  # type: ignore[arg-type]

    def test_a_stub_run_freezes_the_contract_for_both_sides(self) -> None:
        receipt = self._receipt()
        self.assertEqual(
            [role for role, _c in receipt.contracts], ["guardian", "main"]
        )
        self.assertEqual(dict(receipt.bundle_manifest_sha256), self.bundles)
        expected = [
            (side, role, sequence, canonical_request_sha256(request))
            for side, label in ((Side.RONDO, "rondo"), (Side.CODEX, "codex"))
            for sequence, (role, request) in enumerate(
                _stub_trace(label), start=1
            )
        ]
        self.assertEqual(
            [
                (item.side, item.role, item.sequence, item.full_request_sha256)
                for item in receipt.request_provenance
            ],
            expected,
        )
        self.assertNotEqual(expected[0][3], expected[2][3])

    def test_an_asymmetric_stub_run_produces_no_receipt(self) -> None:
        with self.assertRaises(FairComparisonError) as caught:
            self._receipt(
                requests_by_side={
                    Side.RONDO: _stub_trace("rondo"),
                    Side.CODEX: _stub_trace(
                        "codex",
                        main_developer_text="# Policy\nfrozen policy text\n"
                        "# AdditionalTools\nspawn_agent: models are alpha",
                    ),
                }
            )
        self.assertIn(
            "task_independent_stable_input_prefix_differs", caught.exception.reasons
        )

    def test_a_seeded_preflight_checks_the_very_first_side(self) -> None:
        receipt = self._receipt()
        preflight = SymmetryPreflight(require_expectation=True)
        receipt.seed(preflight)
        self.assertEqual(
            preflight.seeded_keys,
            (
                ("terminal-bench/fix-git", "guardian"),
                ("terminal-bench/fix-git", "main"),
            ),
        )
        # The first arrival is no longer free: it must match the frozen contract.
        with self.assertRaises(FairComparisonError) as caught:
            preflight.register(
                task_id="terminal-bench/fix-git",
                role="main",
                side=Side.RONDO,
                request=_request(instructions="drifted base instructions"),
            )
        self.assertEqual(
            caught.exception.reasons,
            ("task_independent_instructions_differs", "frozen_contract_asymmetry"),
        )
        preflight.register(
            task_id="terminal-bench/fix-git",
            role="main",
            side=Side.RONDO,
            request=_request(prompt="any task body"),
        )

    def test_an_uncovered_request_is_refused_under_require_expectation(self) -> None:
        preflight = SymmetryPreflight(require_expectation=True)
        with self.assertRaises(FairComparisonError) as caught:
            preflight.register(
                task_id="terminal-bench/fix-git",
                role="guardian",
                side=Side.RONDO,
                request=_request(guardian=True),
            )
        self.assertEqual(
            caught.exception.reasons, ("preflight_expectation_missing",)
        )

    def test_a_main_only_stub_run_cannot_freeze_a_paid_receipt(self) -> None:
        with self.assertRaises(FairComparisonError) as caught:
            self._receipt(
                requests_by_side={
                    Side.RONDO: (("main", _request()),),
                    Side.CODEX: (("main", _request()),),
                }
            )
        self.assertEqual(
            caught.exception.reasons, ("preflight_stub_trajectory_incomplete",)
        )

    def test_binding_rejects_reuse_across_campaign_task_or_binary(self) -> None:
        receipt = self._receipt()
        binding: dict[str, object] = {
            "campaign_id": "p2-b7-canary-baseline-v23",
            "campaign_lock_sha256": "a" * 64,
            "task_id": "terminal-bench/fix-git",
            "bundle_manifest_sha256": dict(self.bundles),
        }
        receipt.require_binding(**binding)  # type: ignore[arg-type]
        cases = {
            "preflight_receipt_campaign_differs": {
                "campaign_id": "p2-b7-canary-baseline-v24"
            },
            "preflight_receipt_lock_differs": {"campaign_lock_sha256": "b" * 64},
            "preflight_receipt_task_differs": {"task_id": "terminal-bench-other"},
            "preflight_receipt_bundle_differs": {
                "bundle_manifest_sha256": {"rondo": "9" * 64, "codex": "2" * 64}
            },
        }
        for reason, override in cases.items():
            with self.subTest(reason=reason), self.assertRaises(
                FairComparisonError
            ) as caught:
                receipt.require_binding(**{**binding, **override})  # type: ignore[arg-type]
            self.assertEqual(caught.exception.reasons, (reason,))

    def test_receipt_round_trips_and_rejects_a_malformed_file(self) -> None:
        receipt = self._receipt()
        self.assertEqual(PreflightReceipt.from_dict(receipt.to_dict()), receipt)
        with self.assertRaises(FairComparisonError) as caught:
            PreflightReceipt.from_dict({"campaign_id": "x"})
        self.assertEqual(
            caught.exception.reasons, ("preflight_receipt_not_frozen",)
        )
        for mutate in (
            lambda value: value["request_provenance"].pop(),
            lambda value: value["request_provenance"][0].__setitem__(
                "sequence", True
            ),
            lambda value: value["request_provenance"][0].__setitem__(
                "full_request_sha256", "invalid"
            ),
        ):
            malformed = receipt.to_dict()
            mutate(malformed)
            with self.subTest(malformed=malformed), self.assertRaises(
                FairComparisonError
            ) as caught:
                PreflightReceipt.from_dict(malformed)
            self.assertEqual(
                caught.exception.reasons,
                ("preflight_receipt_provenance_invalid",),
            )


class PaidRunnerPreflightGateTests(unittest.TestCase):
    """The paid entry point must refuse to start without a usable receipt."""

    def test_a_fair_comparison_slot_without_a_receipt_is_refused(self) -> None:
        identity = _CampaignFixture.v7()
        task = identity.catalog.tasks[0]
        with self.assertRaisesRegex(
            CampaignExecutionError, "stub preflight receipt is missing"
        ):
            baseline_cli._load_preflight_receipt(
                RepoPaths.discover(Path.cwd()), identity, task
            )

    def test_historical_campaigns_do_not_consume_receipts(self) -> None:
        identity = _CampaignFixture.v6()
        self.assertIsNone(
            baseline_cli._load_preflight_receipt(
                RepoPaths.discover(Path.cwd()), identity, identity.catalog.tasks[0]
            )
        )

    def test_the_receipt_path_is_campaign_and_task_scoped(self) -> None:
        identity = _CampaignFixture.v7()
        task = identity.catalog.tasks[0]
        path = baseline_cli.preflight_receipt_path(
            RepoPaths.discover(Path.cwd()), identity, task.task_id
        )
        self.assertEqual(path.parent.name, "preflight")
        self.assertEqual(path.parent.parent.name, identity.campaign_id)
        self.assertTrue(path.name.startswith(f"{task.task_id.split('/')[-1]}-"))
        self.assertTrue(path.name.endswith(".json"))
        # Namespaced IDs sharing a leaf must not share a receipt file.
        other = baseline_cli.preflight_receipt_path(
            RepoPaths.discover(Path.cwd()), identity, "other-suite/" + task.task_id.split("/")[-1]
        )
        self.assertNotEqual(path.name, other.name)


class SuccessorIdentityTests(unittest.TestCase):
    """`eval-b7-next-identity` may only mint frozen fair-comparison campaigns."""

    def test_a_successor_cannot_be_minted_without_a_frozen_contract(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        for block in (
            {},
            {"repeat_contract": {"repeats_per_task": 2, "aggregation": "strict_majority", "frozen_after": "pilot"}},
            {
                "repeat_contract": RepeatContract(
                    3, AGGREGATION_STRICT_MAJORITY, "pilot"
                ).to_dict(),
                "comparison_conditions": {},
                "catalog_identity": {},
                "product": "rondo-local",
            },
        ):
            with self.subTest(block=sorted(block)), self.assertRaisesRegex(
                CampaignIdentityGenerationError, "not frozen"
            ):
                generate_successor_lock(
                    paths,
                    run_id_date="20260901",
                    run_id_sequence_base=500000001,
                    comparison=block,
                    rondo_runtime_manifest=Path("missing-rondo-manifest.json"),
                    codex_runtime_manifest=Path("missing-codex-manifest.json"),
                    task_budget_id=TASK_BUDGET_ID,
                    task_budget_cap_usd=Decimal("400.000000"),
                    task_budget_prior_estimated_usd=Decimal("0.000000"),
                )

    def test_the_generator_requires_explicit_frozen_inputs(self) -> None:
        signature = inspect.signature(generate_successor_lock)
        for name in (
            "comparison",
            "rondo_runtime_manifest",
            "codex_runtime_manifest",
            "task_budget_id",
            "task_budget_cap_usd",
            "task_budget_prior_estimated_usd",
        ):
            self.assertEqual(signature.parameters[name].default, inspect.Parameter.empty)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            baseline_identity.main(
                ["--run-id-date", "20260901", "--run-id-sequence-base", "500000001"]
            )

    def test_multi_successor_cannot_inherit_local_bundles(self) -> None:
        catalog = json.loads(
            json.dumps(_CampaignFixture.v7().comparison["catalog_identity"])
        )
        catalog["sources"][1]["path"] = (
            "multidev/codex-rs/models-manager/models.json"
        )
        comparison = {
            **_CampaignFixture.v7().comparison,
            "catalog_identity": catalog,
            "product": Product.RONDO_MULTI.value,
        }
        with self.assertRaisesRegex(
            CampaignIdentityGenerationError, "product must be rondo-local"
        ):
            generate_successor_lock(
                RepoPaths.discover(Path.cwd()),
                run_id_date="20260901",
                run_id_sequence_base=500000001,
                comparison=comparison,
                rondo_runtime_manifest=Path("missing-rondo-manifest.json"),
                codex_runtime_manifest=Path("missing-codex-manifest.json"),
                task_budget_id=TASK_BUDGET_ID,
                task_budget_cap_usd=Decimal("400.000000"),
                task_budget_prior_estimated_usd=Decimal("0.000000"),
            )

    def test_an_unreadable_contract_file_fails_before_any_work(self) -> None:
        with self.assertRaisesRegex(
            CampaignIdentityGenerationError, "comparison contract file is unavailable"
        ):
            baseline_identity.main(
                [
                    "--run-id-date",
                    "20260901",
                    "--run-id-sequence-base",
                    "500000001",
                    "--comparison-contract",
                    "/nonexistent/comparison.json",
                    "--rondo-runtime-manifest",
                    "missing-rondo-manifest.json",
                    "--codex-runtime-manifest",
                    "missing-codex-manifest.json",
                    "--task-budget-id",
                    "plan-051",
                    "--task-budget-cap-usd",
                    "100.000000",
                    "--task-budget-prior-estimated-usd",
                    "0.000000",
                ]
            )


class DeclaredConditionsBindingTests(unittest.TestCase):
    """A frozen comparison block may not contradict the campaign it belongs to."""

    def test_a_faithful_block_matches_the_campaigns_own_facts(self) -> None:
        identity = _CampaignFixture.v7()
        declared = identity.require_declared_conditions()
        self.assertEqual(
            declared.catalog_artifact_sha256, identity.catalog_identity["sha256"]
        )

    def test_contradictory_declarations_are_rejected_with_a_reason(self) -> None:
        identity = _CampaignFixture.v7()
        cases = {
            "upstream_timeout_differs": {"upstream_timeout_seconds": "90.000"},
            "provider_profile_differs": {"provider_profile_sha256": "9" * 64},
            "catalog_artifact_differs": {"catalog_artifact_sha256": "8" * 64},
            "task_image_differs": {
                "task_image_digests": {"terminal-bench/other": "sha256:" + "7" * 64}
            },
        }
        for reason, override in cases.items():
            conditions = {
                **identity.comparison["comparison_conditions"],
                **override,
            }
            drifted = replace(
                identity,
                comparison={
                    **identity.comparison,
                    "comparison_conditions": conditions,
                },
            )
            with self.subTest(reason=reason), self.assertRaisesRegex(
                BaselineError, reason
            ):
                drifted.require_declared_conditions()

    def test_a_drifted_harness_commit_is_rejected_at_runtime(self) -> None:
        identity = _CampaignFixture.v7()
        identity.require_declared_conditions(eval_harness_commit="d" * 40)
        with self.assertRaisesRegex(BaselineError, "eval_harness_commit_differs"):
            identity.require_declared_conditions(eval_harness_commit="9" * 40)

    def test_malformed_catalog_provenance_is_rejected(self) -> None:
        cases = [
            ("provenance is invalid", {
                "sources": [
                    {
                        "side": "upstream",
                        "commit": "zzz",
                        "path": "codex-rs/models-manager/models.json",
                        "blob_id": "f" * 40,
                    },
                    {
                        "side": "rondo",
                        "commit": "b" * 40,
                        "path": "mydev/codex-rs/models-manager/models.json",
                        "blob_id": "f" * 40,
                    },
                ]
            }),
            ("record different blobs", {
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
                        "blob_id": "e" * 40,
                    },
                ]
            }),
            ("projection is invalid", {"projection_algorithm": "totally-made-up"}),
            ("projection is invalid", {"projection_version": 999}),
            ("projection is invalid", {"model_slugs": []}),
            ("override target is invalid", {"override_target_slug": "not-in-catalog"}),
        ]
        for message, override in cases:
            block = {
                **_CampaignFixture.v7().comparison,
                "catalog_identity": _CampaignFixture.catalog_identity(**override),
            }
            with self.subTest(message=message), self.assertRaisesRegex(
                BaselineError, message
            ):
                _parse_comparison_block(
                    {"comparison": block},
                    schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
                )

    def test_the_reviewed_malformed_block_is_now_refused(self) -> None:
        """Regression for the exact block that used to load cleanly."""

        block = {
            "repeat_contract": RepeatContract(
                3, AGGREGATION_STRICT_MAJORITY, "pilot"
            ).to_dict(),
            "comparison_conditions": {
                "eval_harness_commit": "9" * 40,
                "upstream_timeout_seconds": "180.000",
                "provider_profile_sha256": "b" * 64,
                "catalog_artifact_sha256": "c" * 64,
                "task_image_digests": {"unrelated-task": "not-a-digest"},
                "projection_version": 1,
            },
            "catalog_identity": _CampaignFixture.catalog_identity(
                projection_algorithm="totally-made-up",
                projection_version=999,
                override_target_slug="not-even-in-the-catalog",
                model_slugs=[],
            ),
            "product": "rondo-local",
        }
        with self.assertRaises(BaselineError):
            _parse_comparison_block(
                {"comparison": block},
                schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
            )


class BidirectionalRepeatTests(unittest.TestCase):
    """Every cross-side disagreement is repeated, in both directions."""

    tasks = _CampaignFixture.tasks
    contract = RepeatContract(3, AGGREGATION_STRICT_MAJORITY, "pilot")

    def _base(self, outcomes: dict) -> tuple[BaselineRun, ...]:
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
        return tuple(values)

    def _conditional(self, task_id: str, rondo: tuple, codex: tuple):
        values = []
        for side, outcomes in ((Side.RONDO, rondo), (Side.CODEX, codex)):
            for repeat, outcome in enumerate(outcomes, start=1):
                values.append(
                    ConditionalRun(
                        task_id,
                        side,
                        repeat,
                        1,
                        outcome,
                        f"c-{task_id}-{side.value}-{repeat}",
                    )
                )
        return tuple(values)

    def test_a_rondo_pass_codex_fail_task_is_repeated(self) -> None:
        task_id = self.tasks[0]
        base = self._base({("ab-codex-1", task_id): TaskOutcome.FAIL})
        result = assess_baseline(
            self.tasks,
            base,
            self._conditional(
                task_id,
                rondo=(TaskOutcome.PASS, TaskOutcome.PASS),
                codex=(TaskOutcome.FAIL, TaskOutcome.FAIL),
            ),
            repeat_contract=self.contract,
        )
        self.assertEqual(result.conditional_tasks, (task_id,))
        self.assertEqual(result.delta, 1)
        self.assertEqual(result.layer("cross_side").status, BaselineStatus.FAILED)
        # The backstop stays one-way: RONDO winning is not a regression.
        self.assertEqual(result.layer("directional").status, BaselineStatus.PASSED)

    def test_the_reverse_direction_no_longer_bypasses_the_repeat_contract(self) -> None:
        """Regression: this used to pass with zero repeats when sigma absorbed it."""

        task_id = self.tasks[0]
        base = self._base(
            {
                ("ab-codex-1", task_id): TaskOutcome.FAIL,
                ("aa-rondo-2", self.tasks[1]): TaskOutcome.FAIL,
            }
        )
        with self.assertRaises(BaselineError):
            # No conditional runs were supplied, so the frozen repeats for the
            # now-triggered task are missing and the assessment cannot proceed.
            assess_baseline(self.tasks, base, (), repeat_contract=self.contract)

    def test_historical_assessments_keep_the_one_way_trigger(self) -> None:
        task_id = self.tasks[0]
        base = self._base({("ab-codex-1", task_id): TaskOutcome.FAIL})
        legacy = assess_baseline(self.tasks, base, ())
        self.assertEqual(legacy.conditional_tasks, ())
        self.assertEqual(legacy.delta, 1)


class NamespacedTaskIdTests(unittest.TestCase):
    """Regression: real TB task IDs are namespaced and must hold receipts.

    The first fix round only exercised ``terminal-bench-fix-git``, which is not
    a task any campaign actually runs, so a validator that rejected ``/`` made
    the whole facility unusable while every test still passed.
    """

    def test_the_frozen_canary_task_id_survives_the_whole_receipt_path(self) -> None:
        task_id = "terminal-bench/fix-git"
        receipt = preflight_receipt_from_stub_run(
            campaign_id="p2-b7-canary-baseline-v23",
            campaign_lock_sha256="a" * 64,
            task_id=task_id,
            bundle_manifest_sha256={"rondo": "1" * 64, "codex": "2" * 64},
            requests_by_side={
                Side.RONDO: _stub_trace("rondo body"),
                Side.CODEX: _stub_trace("codex body"),
            },
        )
        restored = PreflightReceipt.from_dict(receipt.to_dict())
        self.assertEqual(restored.task_id, task_id)
        preflight = SymmetryPreflight(require_expectation=True)
        restored.seed(preflight)
        preflight.register(
            task_id=task_id, role="main", side=Side.RONDO, request=_request()
        )

    def test_path_traversal_shapes_are_still_refused(self) -> None:
        for task_id in (
            "terminal-bench/../etc",
            "/terminal-bench/fix-git",
            "terminal-bench/fix-git/extra",
            "terminal-bench//fix-git",
            "Terminal-Bench/Fix-Git",
            "terminal-bench/" + "x" * 200,
        ):
            with self.subTest(task_id=task_id):
                self.assertFalse(valid_task_id(task_id))


class PreflightProducerTests(unittest.TestCase):
    def test_noop_verifier_returns_zero_without_touching_the_environment(self) -> None:
        environment = mock.Mock()
        verifier = preflight_producer.PreflightNoopVerifier(
            task=object(),
            trial_paths=object(),
            environment=environment,
        )
        result = asyncio.run(verifier.verify())

        self.assertEqual(result.rewards, {"reward": 0})
        environment.assert_not_called()

    """The receipt must come from an entry point that really drives both sides."""

    tasks = ("terminal-bench/fix-git", "terminal-bench/db-wal-recovery")

    class _Identity:
        """The narrow slice of a campaign the producer reads."""

        enforces_fair_comparison = True
        campaign_id = "p2-b7-canary-baseline-v23"
        lock_sha256 = "a" * 64
        bundles = {"rondo": {"manifest_sha256": "1" * 64}, "codex": {"manifest_sha256": "2" * 64}}

        def __init__(self, tasks: tuple[str, ...]) -> None:
            self.catalog = type(
                "Catalog",
                (),
                {"tasks": tuple(_StubTask(task_id) for task_id in tasks)},
            )()

    def _paths(self, root: Path) -> RepoPaths:
        return replace(RepoPaths.discover(Path.cwd()), common_root=root)

    @staticmethod
    def _captured_requests(
        side: Side,
    ) -> tuple[tuple[str, dict[str, object]], ...]:
        return _stub_trace(side.value)

    def test_the_stub_server_captures_bodies_and_refuses_unauthorized_calls(self) -> None:
        with preflight_producer.PreflightCaptureServer() as server:
            base = server.docker_base_url.replace(
                "host.docker.internal", "127.0.0.1"
            )
            body = json.dumps({"model": "gpt-5.6-sol", "stream": True}).encode()
            with self.assertRaises(HTTPError) as caught:
                urlopen(
                    Request(f"{base}/responses", data=body, method="POST"),
                    timeout=10,
                )
            self.assertEqual(caught.exception.code, 401)
            self.assertEqual(server.bodies, ())
            response = urlopen(
                Request(
                    f"{base}/responses",
                    data=body,
                    method="POST",
                    headers={
                        "Authorization": (
                            f"Bearer {preflight_producer.PREFLIGHT_STUB_BEARER}"
                        )
                    },
                ),
                timeout=10,
            )
            self.assertEqual(response.status, 200)
            first = response.read()
            self.assertIn(b'"name":"exec_command"', first)
            second = urlopen(
                Request(
                    f"{base}/responses",
                    data=body,
                    method="POST",
                    headers={
                        "Authorization": (
                            f"Bearer {preflight_producer.PREFLIGHT_STUB_BEARER}"
                        )
                    },
                ),
                timeout=10,
            ).read()
            self.assertIn(b'\\"outcome\\":\\"allow\\"', second)
            third = urlopen(
                Request(
                    f"{base}/responses",
                    data=body,
                    method="POST",
                    headers={
                        "Authorization": (
                            f"Bearer {preflight_producer.PREFLIGHT_STUB_BEARER}"
                        )
                    },
                ),
                timeout=10,
            ).read()
            self.assertIn(b"preflight", third)
            self.assertEqual(server.bodies, (body, body, body))
            self.assertEqual(server.rejections, ("unauthorized",))

    def test_it_writes_one_bound_receipt_per_task(self) -> None:
        identity = self._Identity(self.tasks)
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            written = preflight_producer.produce_preflight_receipts(
                paths,
                identity=identity,
                seccomp_profile=Path("/dev/null"),
                manifests={Side.RONDO: object(), Side.CODEX: object()},
                counter=None,
                lock_guard=None,
                lease=None,
                config=None,
                capture=lambda **kwargs: self._captured_requests(kwargs["side"]),
            )
            self.assertEqual(len(written), 2)
            for path, task_id in zip(written, self.tasks):
                receipt = PreflightReceipt.from_dict(json.loads(path.read_bytes()))
                receipt.require_binding(
                    campaign_id=identity.campaign_id,
                    campaign_lock_sha256=identity.lock_sha256,
                    task_id=task_id,
                    bundle_manifest_sha256={
                        side: str(bundle["manifest_sha256"])
                        for side, bundle in identity.bundles.items()
                    },
                )

    def test_an_asymmetric_pair_writes_nothing(self) -> None:
        identity = self._Identity(self.tasks[:1])
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            with self.assertRaisesRegex(
                preflight_producer.PreflightProductionError, "asymmetric on the stub"
            ):
                preflight_producer.produce_preflight_receipts(
                    paths,
                    identity=identity,
                    seccomp_profile=Path("/dev/null"),
                    manifests={Side.RONDO: object(), Side.CODEX: object()},
                    counter=None,
                    lock_guard=None,
                    lease=None,
                    config=None,
                    capture=lambda **kwargs: _stub_trace(
                        kwargs["side"].value,
                        main_instructions=(
                            "base"
                            if kwargs["side"] is Side.RONDO
                            else "drifted"
                        ),
                    ),
                )
            self.assertEqual(
                list((paths.common_root / "eval-data/campaigns").rglob("*.json")), []
            )

    def test_an_identical_existing_receipt_makes_a_retry_idempotent(self) -> None:
        identity = self._Identity(self.tasks[:1])
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            arguments = {
                "identity": identity,
                "seccomp_profile": Path("/dev/null"),
                "manifests": {Side.RONDO: object(), Side.CODEX: object()},
                "counter": None,
                "lock_guard": None,
                "lease": None,
                "config": None,
                "capture": lambda **kwargs: self._captured_requests(kwargs["side"]),
            }
            first = preflight_producer.produce_preflight_receipts(paths, **arguments)
            second = preflight_producer.produce_preflight_receipts(paths, **arguments)
            self.assertEqual(first, second)

    def test_a_conflicting_existing_receipt_is_never_overwritten(self) -> None:
        identity = self._Identity(self.tasks)
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            arguments = {
                "identity": identity,
                "seccomp_profile": Path("/dev/null"),
                "manifests": {Side.RONDO: object(), Side.CODEX: object()},
                "counter": None,
                "lock_guard": None,
                "lease": None,
                "config": None,
                "capture": lambda **kwargs: self._captured_requests(kwargs["side"]),
            }
            written = preflight_producer.produce_preflight_receipts(paths, **arguments)
            written[0].unlink()
            written[1].write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                preflight_producer.PreflightProductionError, "different bytes"
            ):
                preflight_producer.produce_preflight_receipts(paths, **arguments)
            self.assertFalse(written[0].exists())
            self.assertEqual(written[1].read_text(encoding="utf-8"), "{}\n")

    def test_a_later_task_failure_publishes_no_half_batch(self) -> None:
        identity = self._Identity(self.tasks)

        def capture(
            **kwargs: object,
        ) -> tuple[tuple[str, dict[str, object]], ...]:
            side = kwargs["side"]
            assert isinstance(side, Side)
            captured = list(self._captured_requests(side))
            task = kwargs["task"]
            if getattr(task, "task_id") == self.tasks[1] and side is Side.CODEX:
                captured[0] = ("main", _request(instructions="drifted"))
                captured[2] = (
                    "main",
                    _request(prompt="after approval", instructions="drifted"),
                )
            return tuple(captured)

        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(Path(directory))
            with self.assertRaisesRegex(
                preflight_producer.PreflightProductionError, "asymmetric on the stub"
            ):
                preflight_producer.produce_preflight_receipts(
                    paths,
                    identity=identity,
                    seccomp_profile=Path("/dev/null"),
                    manifests={Side.RONDO: object(), Side.CODEX: object()},
                    counter=None,
                    lock_guard=None,
                    lease=None,
                    config=None,
                    capture=capture,
                )
            self.assertEqual(
                list((paths.common_root / "eval-data/campaigns").rglob("*.json")), []
            )

    def test_stub_projection_uses_the_real_prepared_run_shape(self) -> None:
        identity = _CampaignFixture.v7()
        task = identity.catalog.tasks[0]
        provider = SimpleNamespace(
            main_model="main-model",
            guardian_model="guardian-model",
            main_effort="medium",
            guardian_effort="low",
        )
        spec = RunSpec(
            side=Side.RONDO,
            batch_id=identity.batch_id,
            task_id=task.task_id,
            task_image_digest=task.image_digest,
            binary=object(),  # type: ignore[arg-type]
            terminal_bench_version="0.20.0",
            provider=provider,  # type: ignore[arg-type]
        )
        prepared = PreparedTerminalBenchRun(
            spec=spec,
            command=SimpleNamespace(
                stub_verifier=True,
                delete_environment=False,
                argv=(
                    "--verifier",
                    preflight_producer.PREFLIGHT_STUB_VERIFIER_IMPORT,
                    "--no-delete",
                ),
            ),  # type: ignore[arg-type]
            adapter=object(),  # type: ignore[arg-type]
            materialized_task=object(),  # type: ignore[arg-type]
        )
        request = SimpleNamespace(
            seccomp_profile_source_sha256=identity.no_api_seccomp["source_sha256"],
            seccomp_profile_effective_sha256=identity.no_api_seccomp[
                "effective_sha256"
            ],
            frozen_model_catalog_sha256=identity.catalog_identity["sha256"],
        )
        preflight_producer._validate_stub_projection(
            prepared,
            request=request,
            identity=identity,
            task=task,
            provider=provider,
        )

    def test_role_capture_requires_the_complete_stable_approval_trajectory(self) -> None:
        provider = SimpleNamespace(
            main_model=MAIN_PRICING.model_id,
            main_effort="low",
            guardian_model=GUARDIAN_PRICING.model_id,
            guardian_effort="low",
        )
        main = _request()
        guardian = _request(guardian=True)
        bodies = tuple(
            json.dumps(request).encode("utf-8")
            for request in (main, guardian, _request(prompt="after approval"))
        )
        self.assertEqual(
            tuple(
                role
                for role, _request_body in preflight_producer._request_trace(
                    bodies, provider=provider
                )
            ),
            ("main", "guardian", "main"),
        )
        with self.assertRaisesRegex(
            preflight_producer.PreflightProductionError, "main-Guardian-main"
        ):
            preflight_producer._request_trace(bodies[:2], provider=provider)
        drifted = (
            bodies[0],
            bodies[1],
            json.dumps(_request(instructions="drifted after approval")).encode(
                "utf-8"
            ),
        )
        with self.assertRaisesRegex(
            preflight_producer.PreflightProductionError,
            "contract drifted after Guardian",
        ):
            preflight_producer._request_trace(drifted, provider=provider)

    def test_historical_campaigns_cannot_produce_receipts(self) -> None:
        identity = _CampaignFixture.v6()
        with self.assertRaisesRegex(
            preflight_producer.PreflightProductionError, "only fair-comparison"
        ):
            preflight_producer.produce_preflight_receipts(
                RepoPaths.discover(Path.cwd()),
                identity=identity,
                seccomp_profile=Path("/dev/null"),
                manifests={},
                counter=None,
                lock_guard=None,
                lease=None,
                config=None,
                capture=lambda **kwargs: {},
            )


class CampaignStartupReceiptGateTests(unittest.TestCase):
    """Receipts are checked once at startup, ahead of the paid wire canary."""

    def test_a_missing_receipt_blocks_the_whole_campaign(self) -> None:
        identity = _CampaignFixture.v7()
        with self.assertRaisesRegex(
            CampaignExecutionError, "stub preflight receipt is missing"
        ):
            baseline_cli._require_all_preflight_receipts(
                RepoPaths.discover(Path.cwd()), identity
            )

    def test_historical_campaigns_are_unaffected(self) -> None:
        baseline_cli._require_all_preflight_receipts(
            RepoPaths.discover(Path.cwd()), _CampaignFixture.v6()
        )

    def test_the_gate_runs_before_the_wire_canary(self) -> None:
        source = inspect.getsource(baseline_cli._worker_step_main)
        self.assertIn("_require_all_preflight_receipts", source)
        self.assertNotIn("_execute_wire_canary", source)
        self.assertLess(
            source.index("identity.require_declared_conditions"),
            source.index("_require_all_preflight_receipts"),
        )


class EvalHarnessLifecycleTests(unittest.TestCase):
    """An identity-only commit may advance HEAD without changing harness code."""

    @staticmethod
    def _git(root: Path, *args: str) -> str:
        completed = subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return completed.stdout.strip()

    def test_generated_identity_can_be_committed_and_consumed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "RONDO test")
            self._git(root, "config", "user.email", "rondo-test@example.invalid")
            (root / "eval/rondo_eval").mkdir(parents=True)
            (root / "eval/locks").mkdir(parents=True)
            (root / "eval/rondo_eval/harness.py").write_text("VALUE = 1\n")
            (root / "eval/locks/p2-b7-canary-baseline-v22.json").write_text(
                "{}\n"
            )
            (root / "eval/pyproject.toml").write_text("[project]\nname='test'\n")
            (root / "eval/uv.lock").write_text("version = 1\n")
            (root / "justfile").write_text("test:\n    true\n")
            self._git(root, "add", ".")
            self._git(root, "commit", "-qm", "harness")
            harness_commit = self._git(root, "rev-parse", "HEAD")

            (root / "eval/locks/p2-b7-canary-baseline-v23.json").write_text("{}\n")
            (root / "eval/locks/p2-b7-active.json").write_text("{}\n")
            with self.assertRaisesRegex(HarborResultError, "checkout is dirty"):
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=harness_commit,
                )
            self._git(root, "add", "eval/locks")
            self._git(root, "commit", "-qm", "identity")
            identity_commit = self._git(root, "rev-parse", "HEAD")

            self.assertEqual(
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=identity_commit,
                ),
                harness_commit,
            )
            historical = root / "eval/locks/p2-b7-canary-baseline-v22.json"
            historical.write_text('{"drifted":true}\n')
            self._git(root, "add", historical.relative_to(root).as_posix())
            self._git(root, "commit", "-qm", "change historical lock")
            with self.assertRaisesRegex(
                HarborResultError, "historical eval lock projection differs"
            ):
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=self._git(root, "rev-parse", "HEAD"),
                )
            historical.write_text("{}\n")
            self._git(root, "add", historical.relative_to(root).as_posix())
            self._git(root, "commit", "-qm", "restore historical lock")
            restored_commit = self._git(root, "rev-parse", "HEAD")
            self.assertEqual(
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=restored_commit,
                ),
                harness_commit,
            )
            (root / "eval/rondo_eval/harness.py").write_text("VALUE = 2\n")
            with self.assertRaisesRegex(HarborResultError, "checkout is dirty"):
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=restored_commit,
                )
            self._git(root, "add", "eval/rondo_eval/harness.py")
            self._git(root, "commit", "-qm", "change harness")
            drifted_commit = self._git(root, "rev-parse", "HEAD")
            with self.assertRaisesRegex(HarborResultError, "differs from the campaign"):
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=drifted_commit,
                )

    def test_new_identity_cannot_change_after_its_addition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "RONDO test")
            self._git(root, "config", "user.email", "rondo-test@example.invalid")
            (root / "eval/rondo_eval").mkdir(parents=True)
            (root / "eval/locks").mkdir(parents=True)
            (root / "eval/rondo_eval/harness.py").write_text("VALUE = 1\n")
            self._git(root, "add", ".")
            self._git(root, "commit", "-qm", "harness")
            harness_commit = self._git(root, "rev-parse", "HEAD")
            trunk = self._git(root, "branch", "--show-current")
            self._git(root, "checkout", "-qb", "identity-work")

            identity = root / "eval/locks/p2-b7-canary-baseline-v23.json"
            identity.write_text('{"repeat":3}\n')
            (root / "eval/locks/p2-b7-active.json").write_text("{}\n")
            self._git(root, "add", "eval/locks")
            self._git(root, "commit", "-qm", "identity")
            self._git(root, "checkout", "-q", trunk)
            self._git(
                root,
                "merge",
                "-q",
                "--no-ff",
                "-m",
                "merge identity",
                "identity-work",
            )
            addition_commit = self._git(root, "rev-parse", "HEAD")
            self.assertEqual(
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=addition_commit,
                ),
                harness_commit,
            )

            (root / "README.md").write_text("unrelated\n")
            self._git(root, "add", "README.md")
            self._git(root, "commit", "-qm", "unrelated")
            unrelated_commit = self._git(root, "rev-parse", "HEAD")
            self.assertEqual(
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=unrelated_commit,
                ),
                harness_commit,
            )

            identity.write_text('{"repeat":5}\n')
            self._git(root, "add", identity.relative_to(root).as_posix())
            self._git(root, "commit", "-qm", "mutate identity")
            with self.assertRaisesRegex(
                HarborResultError, "new eval identity changed after addition"
            ):
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=self._git(root, "rev-parse", "HEAD"),
                )

            identity.write_text('{"repeat":3}\n')
            self._git(root, "add", identity.relative_to(root).as_posix())
            self._git(root, "commit", "-qm", "restore identity")
            with self.assertRaisesRegex(
                HarborResultError, "new eval identity changed after addition"
            ):
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=self._git(root, "rev-parse", "HEAD"),
                )

    def test_merged_identity_mutation_cannot_hide_behind_original_blob(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._git(root, "init", "-q")
            self._git(root, "config", "user.name", "RONDO test")
            self._git(root, "config", "user.email", "rondo-test@example.invalid")
            (root / "eval/rondo_eval").mkdir(parents=True)
            (root / "eval/locks").mkdir(parents=True)
            (root / "eval/rondo_eval/harness.py").write_text("VALUE = 1\n")
            self._git(root, "add", ".")
            self._git(root, "commit", "-qm", "harness")
            harness_commit = self._git(root, "rev-parse", "HEAD")
            trunk = self._git(root, "branch", "--show-current")

            identity = root / "eval/locks/p2-b7-canary-baseline-v23.json"
            identity.write_text('{"repeat":3}\n')
            (root / "eval/locks/p2-b7-active.json").write_text("{}\n")
            self._git(root, "add", "eval/locks")
            self._git(root, "commit", "-qm", "identity")
            identity_commit = self._git(root, "rev-parse", "HEAD")
            self._git(root, "checkout", "-qb", "mutate-identity")
            identity.write_text('{"repeat":5}\n')
            self._git(root, "add", identity.relative_to(root).as_posix())
            self._git(root, "commit", "-qm", "mutate identity on side branch")

            self._git(root, "checkout", "-q", trunk)
            self._git(
                root,
                "merge",
                "-q",
                "--no-ff",
                "--no-commit",
                "mutate-identity",
            )
            identity.write_text('{"repeat":3}\n')
            self._git(root, "add", identity.relative_to(root).as_posix())
            self._git(root, "commit", "-qm", "merge with original identity blob")
            self.assertEqual(
                self._git(
                    root,
                    "rev-parse",
                    "HEAD:" + identity.relative_to(root).as_posix(),
                ),
                self._git(
                    root,
                    "rev-parse",
                    identity_commit + ":" + identity.relative_to(root).as_posix(),
                ),
            )
            with self.assertRaisesRegex(
                HarborResultError, "new eval identity changed after addition"
            ):
                results_module._validate_eval_harness_projection(
                    root,
                    expected_commit=harness_commit,
                    head=self._git(root, "rev-parse", "HEAD"),
                )


class SuccessorRunRangeTests(unittest.TestCase):
    """A widened repeat contract widens the run-ID range that must be checked."""

    def _registry(self) -> tuple:
        return (
            CampaignLockRegistration(
                version=22,
                path=Path("eval/locks/p2-b7-canary-baseline-v22.json"),
                campaign_id="p2-b7-canary-baseline-v22",
                batch_id="p2-b7-canary-sol-sol-v22",
                run_id_date="20260901",
                run_id_sequence_base=500000400,
                max_run_slots=321,
                lock_sha256="a" * 64,
            ),
        )

    def test_five_repeats_catch_a_tail_collision_that_321_slots_missed(self) -> None:
        registry = self._registry()
        # 481 slots from 500000001 run into the historical block at 500000400.
        slot_total = campaign_slot_total(
            task_count=10, max_attempts=4, conditional_repeats_per_side=4
        )
        self.assertEqual(slot_total, 481)
        validate_successor_run_range(
            registry, run_id_date="20260901", run_id_sequence_base=500000001
        )
        with self.assertRaisesRegex(CampaignIdentityGenerationError, "collides"):
            validate_successor_run_range(
                registry,
                run_id_date="20260901",
                run_id_sequence_base=500000001,
                slot_total=slot_total,
            )

    def test_an_invalid_slot_total_is_refused(self) -> None:
        with self.assertRaisesRegex(
            CampaignIdentityGenerationError, "slot total is invalid"
        ):
            validate_successor_run_range(
                self._registry(),
                run_id_date="20260901",
                run_id_sequence_base=1,
                slot_total=0,
            )


class SuccessorBudgetTests(unittest.TestCase):
    """Every v7 successor shares the exact authorized Plan 051 envelope."""

    def test_the_generator_requires_an_authorized_task_cap(self) -> None:
        parameter = inspect.signature(generate_successor_lock).parameters[
            "task_budget_cap_usd"
        ]
        self.assertEqual(parameter.default, inspect.Parameter.empty)
        paths = RepoPaths.discover(Path.cwd())
        frozen = {
            "repeat_contract": RepeatContract(
                3, AGGREGATION_STRICT_MAJORITY, "pilot"
            ).to_dict(),
            "comparison_conditions": ComparisonConditions(
                eval_harness_commit="d" * 40,
                upstream_timeout_seconds="120.000",
                provider_profile_sha256="e" * 64,
                catalog_artifact_sha256="c" * 64,
                task_image_digests=(("terminal-bench/fix-git", "sha256:" + "1" * 64),),
            ).to_dict(),
            "catalog_identity": _CampaignFixture.catalog_identity(),
            "product": Product.RONDO_LOCAL.value,
        }
        for cap in (
            Decimal("0"),
            Decimal("-1"),
            Decimal("200.000000"),
            Decimal("400.000001"),
        ):
            with self.subTest(cap=cap), self.assertRaisesRegex(
                CampaignIdentityGenerationError, "task budget is not authorized"
            ):
                generate_successor_lock(
                    paths,
                    run_id_date="20260901",
                    run_id_sequence_base=500000001,
                    comparison=frozen,
                    rondo_runtime_manifest=Path("missing-rondo-manifest.json"),
                    codex_runtime_manifest=Path("missing-codex-manifest.json"),
                    task_budget_id=TASK_BUDGET_ID,
                    task_budget_cap_usd=cap,
                    task_budget_prior_estimated_usd=Decimal("0.000000"),
                )

    def test_a_v7_budget_requires_the_exact_task_envelope(self) -> None:
        identity = _CampaignFixture.v7()
        self.assertTrue(
            _valid_campaign_budget(
                {**identity.budget, "campaign_cap_usd": "400.000000",
                 "prior_estimated_usd": "0.000000",
                 "task_budget_cap_usd": "400.000000",
                 "task_budget_prior_estimated_usd": "0.000000"},
                schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
                expected_max_run_slots=identity.budget["max_run_slots"],
            )
        )
        self.assertFalse(
            _valid_campaign_budget(
                {**identity.budget, "campaign_cap_usd": "200.000000",
                 "task_budget_cap_usd": "200.000000"},
                schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
                expected_max_run_slots=identity.budget["max_run_slots"],
            )
        )
        self.assertFalse(
            _valid_campaign_budget(
                {**identity.budget, "task_budget_id": "other-task"},
                schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
                expected_max_run_slots=identity.budget["max_run_slots"],
            )
        )

    def test_a_v7_lock_may_not_inherit_historical_continuation(self) -> None:
        with self.assertRaisesRegex(BaselineError, "cannot inherit historical"):
            _parse_continuation_references(
                [{"chain_id": "base:ab-rondo-1:terminal-bench/fix-git"}],
                schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
                successor_timeout=Decimal("120.000"),
            )
        self.assertEqual(
            _parse_continuation_references(
                [],
                schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
                successor_timeout=Decimal("120.000"),
            ),
            (),
        )


if __name__ == "__main__":
    unittest.main()
