import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.identity import canonical_json_bytes
from rondo_eval.publication_critic.structured_diagnostic.archive import (
    RECEIPT_SCHEMA,
    TERMINAL_SCHEMA,
    DiagnosticArchive,
    DiagnosticArchiveError,
)
from rondo_eval.publication_critic.structured_diagnostic.contract import (
    DiagnosticTask,
    DirectOutput,
    OutputContractError,
    ScalarOutput,
    StructuredOutput,
    parse_output,
)
from rondo_eval.publication_critic.structured_diagnostic.cost import (
    PRICE_CARD,
    PRICE_CARD_SHA256,
    DiagnosticBudgetExceeded,
    Plan100BudgetLedger,
    price_tier_at,
    settle_attempt,
    token_cost_rmb,
    worst_case_reservation_rmb,
)
from rondo_eval.publication_critic.structured_diagnostic.freeze import (
    DiagnosticFreezeError,
    build_freeze,
    validate_commissioning_binding,
)
from rondo_eval.publication_critic.structured_diagnostic.metrics import (
    decide_route,
    decide_route_with_metadata,
    direct_metrics,
    scalar_metrics,
    structured_metrics,
)
from rondo_eval.publication_critic.structured_diagnostic.release import (
    load_commissioning_public_items,
    load_validation_release,
)
from rondo_eval.publication_critic.structured_diagnostic.runner import (
    AmbiguousAttemptError,
    DiagnosticRunnerError,
    build_commissioning_binding,
    recompute_commissioning,
    recompute_formal,
    run_batch,
    tracked_projection,
)


def _freeze(mode: str, run_id: str) -> dict:
    return build_freeze(
        mode=mode,
        run_id=run_id,
        git_commit="1" * 40,
        diagnostic_contract_sha256="2" * 64,
        executable_sha256="3" * 64,
        descriptor_sha256="4" * 64,
        environment_lock_sha256="5" * 64,
        token_recounter_sha256="7" * 64,
        commissioning_binding_sha256="6" * 64 if mode == "formal" else None,
    )


def _attempt() -> dict:
    return {
        "attempt": 1,
        "requested_at": "2026-08-29T04:00:00+00:00",
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 60,
        },
        "recount": None,
        "explicitly_unbilled": False,
    }


class _FakeEvaluator:
    def __init__(self, *, first: str = "success") -> None:
        self.first = first
        self.calls: list[tuple[DiagnosticTask, bytes]] = []

    def evaluate(self, task: DiagnosticTask, packet: dict) -> dict:
        self.calls.append((task, canonical_json_bytes(dict(packet))))
        if len(self.calls) == 1 and self.first == "technical":
            response = None
            outcome = {
                "type": "technical_failure",
                "kind": "provider_transport",
                "http_status": None,
            }
        elif len(self.calls) == 1 and self.first == "parse":
            response = '{"quality":0.5,"extra":true}'
            outcome = {
                "type": "output_contract_failure",
                "kind": "output_contract_violation",
                "http_status": None,
            }
        else:
            response = {
                DiagnosticTask.SCALAR: '{"quality":0.5}',
                DiagnosticTask.DIRECT: '{"verdict":"PASS"}',
                DiagnosticTask.STRUCTURED: (
                    '{"useful_state_transfer":"PASS",'
                    '"honest_uncertainty":"PASS",'
                    '"conditional_continuity":"N/A",'
                    '"scope_and_signal":"PASS",'
                    '"internal_consistency":"PASS"}'
                ),
            }[task]
            outcome = {"type": "success"}
        return {
            "requested_model": "deepseek-v4-flash",
            "served_model": "deepseek-v4-flash",
            "response_text": response,
            "attempts": [_attempt()],
            "elapsed_ms": 1,
            "outcome": outcome,
        }


class _AOnlyResidualEvaluator:
    def __init__(self, release) -> None:
        supervision = release.supervision_by_id()
        self.gold_by_packet = {
            item.packet_bytes: supervision[item.candidate_id].gold_verdict
            for item in release.public_items
        }

    def evaluate(self, task: DiagnosticTask, packet: dict) -> dict:
        gold = self.gold_by_packet[canonical_json_bytes(packet)]
        if task is DiagnosticTask.SCALAR:
            response = '{"quality":1.0}' if gold == "PASS" else '{"quality":0.0}'
        elif task is DiagnosticTask.DIRECT:
            response = '{"verdict":"PASS"}'
        else:
            response = (
                '{"useful_state_transfer":"PASS",'
                '"honest_uncertainty":"PASS",'
                '"conditional_continuity":"PASS",'
                '"scope_and_signal":"PASS",'
                '"internal_consistency":"PASS"}'
            )
        return {
            "requested_model": "deepseek-v4-flash",
            "served_model": "deepseek-v4-flash",
            "response_text": response,
            "attempts": [_attempt()],
            "elapsed_ms": 1,
            "outcome": {"type": "success"},
        }


class _FakeRecounter:
    def __init__(self, *, identity: str = "7" * 64, prompt_tokens: int = 100) -> None:
        self.identity = identity
        self.prompt_tokens = prompt_tokens

    def recount(self, task: DiagnosticTask, packet: dict, response_text: str | None):
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": 10,
            "method": "fake-calibrated-counter",
            "identity_sha256": self.identity,
        }


class Plan100CostAndArchiveTest(unittest.TestCase):
    def test_price_tier_uses_weekday_beijing_windows_and_exact_boundaries(
        self,
    ) -> None:
        self.assertEqual(PRICE_CARD["peak_days"], "monday_through_friday")
        self.assertEqual(
            PRICE_CARD_SHA256,
            "b0ed7297408c252edff1fc022e7e22538dfcb798a706db457b89cf2bb9834307",
        )
        tracked = json.loads(
            (
                REPO_ROOT
                / "eval/templates/publication-critic/plan100-diagnostic-contract-v1.json"
            ).read_text(encoding="utf-8")
        )["budget"]["price_card"]
        self.assertEqual(
            tracked["peak_days_beijing"],
            ["monday", "tuesday", "wednesday", "thursday", "friday"],
        )
        self.assertEqual(
            tracked["peak_windows_beijing"],
            ["09:00-12:00", "14:00-18:00"],
        )
        self.assertEqual(tracked["weekends"], "off_peak_all_day")
        cases = (
            (datetime(2026, 8, 31, 0, 59, tzinfo=timezone.utc), "off_peak"),
            (datetime(2026, 8, 31, 1, 0, tzinfo=timezone.utc), "peak"),
            (datetime(2026, 8, 31, 3, 59, tzinfo=timezone.utc), "peak"),
            (datetime(2026, 8, 31, 4, 0, tzinfo=timezone.utc), "off_peak"),
            (datetime(2026, 8, 31, 5, 59, tzinfo=timezone.utc), "off_peak"),
            (datetime(2026, 8, 31, 6, 0, tzinfo=timezone.utc), "peak"),
            (datetime(2026, 8, 31, 9, 59, tzinfo=timezone.utc), "peak"),
            (datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc), "off_peak"),
            (datetime(2026, 8, 29, 1, 0, tzinfo=timezone.utc), "off_peak"),
            (datetime(2026, 8, 29, 6, 0, tzinfo=timezone.utc), "off_peak"),
            (datetime(2026, 8, 30, 1, 0, tzinfo=timezone.utc), "off_peak"),
            (datetime(2026, 8, 30, 6, 0, tzinfo=timezone.utc), "off_peak"),
        )
        for instant, expected in cases:
            with self.subTest(instant=instant):
                self.assertEqual(price_tier_at(instant), expected)

    def test_usage_recount_and_last_resort_fallback_are_distinct(self) -> None:
        self.assertEqual(
            token_cost_rmb(
                prompt_tokens=100,
                completion_tokens=10,
                cache_hit_tokens=40,
                cache_miss_tokens=60,
                tier="off_peak",
            ),
            Decimal("0.000137"),
        )
        recounted = settle_attempt(
            {
                "attempt": 1,
                "requested_at": "2026-08-29T04:00:00+00:00",
                "usage": None,
                "recount": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "method": "deepseek-official-tokenizer-calibrated-v1",
                    "identity_sha256": "a" * 64,
                },
                "explicitly_unbilled": False,
            }
        )
        self.assertEqual(
            recounted["settlement_method"], "recount_cache_miss_conservative"
        )
        self.assertEqual(recounted["charge_rmb"], "0.000195")
        fallback = settle_attempt(
            {
                "attempt": 1,
                "requested_at": "2026-08-29T04:00:00+00:00",
                "usage": None,
                "recount": None,
                "explicitly_unbilled": False,
            }
        )
        self.assertEqual(
            fallback["settlement_method"], "actual_attempt_unquantifiable_fallback"
        )
        self.assertEqual(fallback["charge_rmb"], "0.1")

    def test_ledger_counts_settled_and_outstanding_before_next_action(self) -> None:
        reserve = worst_case_reservation_rmb(
            max_attempts=2,
            max_prompt_tokens=16_384,
            max_completion_tokens=256,
        )
        self.assertEqual(reserve, Decimal("0.2"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = Plan100BudgetLedger(path, cap_rmb=Decimal("0.3"))
            ledger.reserve("formal:A:item-1:1", reserve)
            with self.assertRaises(DiagnosticBudgetExceeded):
                ledger.reserve("formal:A:item-2:1", reserve)
            ledger.settle(
                "formal:A:item-1:1",
                [
                    {
                        "attempt": 1,
                        "requested_at": "2026-08-29T04:00:00+00:00",
                        "usage": {
                            "prompt_tokens": 100,
                            "completion_tokens": 10,
                            "prompt_cache_hit_tokens": 40,
                            "prompt_cache_miss_tokens": 60,
                        },
                        "recount": None,
                        "explicitly_unbilled": False,
                    }
                ],
            )
            ledger.reserve("formal:A:item-2:1", reserve)
            snapshot = Plan100BudgetLedger(path, cap_rmb=Decimal("0.3")).snapshot()
            self.assertEqual(snapshot["settled_rmb"], "0.000137")
            self.assertEqual(snapshot["outstanding_reserved_rmb"], "0.2")
            self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)

    def test_write_once_receipt_terminal_resume_and_authority(self) -> None:
        freeze = {"schema": "fake-plan100-freeze", "identity": "frozen"}
        logical_key = "A:item-1"
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "logical_key": logical_key,
            "freeze_sha256": "a" * 64,
            "budget_key": "formal:A:item-1:1",
            "outcome": {"type": "success", "response_text": '{"quality":0.5}'},
            "attempts": [],
        }
        terminal = {
            "schema": TERMINAL_SCHEMA,
            "logical_key": logical_key,
            "arm": "A",
            "candidate_id": "item-1",
            "packet_sha256": "b" * 64,
            "status": "success",
            "parsed_output": {"quality": 0.5},
            "receipt_sha256": "c" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory) / "runs"
            archive = DiagnosticArchive(
                runs,
                "plan100-formal-20260829T120000Z-test",
                "formal",
            ).start(freeze)
            archive.write_receipt(logical_key, receipt)
            archive.write_terminal(logical_key, terminal)
            resumed = DiagnosticArchive(
                runs,
                "plan100-formal-20260829T120000Z-test",
                "formal",
            ).resume(freeze)
            self.assertEqual(resumed.load_receipts(logical_key), (receipt,))
            self.assertEqual(resumed.load_terminal(logical_key), terminal)
            resumed.write_terminal(logical_key, terminal)
            with self.assertRaisesRegex(DiagnosticArchiveError, "terminal_drifted"):
                resumed.write_terminal(
                    logical_key, terminal | {"status": "parse_failure"}
                )
            result = {
                "complete": True,
                "terminal_observation_count": 81,
                "route_terminal": "TASK_EXECUTABILITY_INSUFFICIENT",
                "residual_mixed_signal": False,
            }
            resumed.claim_formal_result(freeze, result)
            reopened = DiagnosticArchive(
                runs,
                "plan100-formal-20260829T120000Z-test",
                "formal",
            ).reopen_read_only(freeze)
            self.assertEqual(reopened.load_terminal(logical_key), terminal)
            with self.assertRaisesRegex(
                DiagnosticArchiveError, "formal_result_already_authoritative"
            ):
                DiagnosticArchive(
                    runs,
                    "plan100-formal-20260829T130000Z-second",
                    "formal",
                ).start(freeze)


class Plan100ContractAndReleaseTest(unittest.TestCase):
    def test_strict_a_b_c_parsers_and_local_non_compensating_gate(self) -> None:
        self.assertEqual(parse_output("A", '{"quality":0.75}'), ScalarOutput(0.75))
        self.assertEqual(
            parse_output("B", '{"verdict":"REWRITE"}'), DirectOutput("REWRITE")
        )
        decisions = {
            "useful_state_transfer": "PASS",
            "honest_uncertainty": "PASS",
            "conditional_continuity": "N/A",
            "scope_and_signal": "PASS",
            "internal_consistency": "PASS",
        }
        self.assertEqual(
            parse_output("C", json.dumps(decisions)),
            StructuredOutput(decisions=decisions, verdict="PASS"),
        )
        decisions["internal_consistency"] = "FAIL"
        self.assertEqual(parse_output("C", json.dumps(decisions)).verdict, "REWRITE")

    def test_strict_parsers_reject_contract_escape_hatches(self) -> None:
        invalid = (
            (DiagnosticTask.SCALAR, '{"quality":true}'),
            (DiagnosticTask.SCALAR, '{"quality":NaN}'),
            (DiagnosticTask.SCALAR, '{"quality":0.5,"score":0.5}'),
            (DiagnosticTask.SCALAR, '{"quality":0.5} explanation'),
            (DiagnosticTask.DIRECT, '{"verdict":"PASS","explanation":"nice"}'),
            (DiagnosticTask.DIRECT, '{"verdict":"pass"}'),
            (
                DiagnosticTask.STRUCTURED,
                json.dumps(
                    {
                        "useful_state_transfer": "N/A",
                        "honest_uncertainty": "PASS",
                        "conditional_continuity": "N/A",
                        "scope_and_signal": "PASS",
                        "internal_consistency": "PASS",
                    }
                ),
            ),
            (
                DiagnosticTask.STRUCTURED,
                json.dumps(
                    {
                        "useful_state_transfer": "PASS",
                        "honest_uncertainty": "PASS",
                        "conditional_continuity": "N/A",
                        "scope_and_signal": "PASS",
                        "internal_consistency": "PASS",
                        "verdict": "PASS",
                    }
                ),
            ),
            (DiagnosticTask.SCALAR, '{"quality":0.2,"quality":0.3}'),
        )
        for task, raw in invalid:
            with (
                self.subTest(task=task, raw=raw),
                self.assertRaises(OutputContractError),
            ):
                parse_output(task, raw)

    def test_v10_loader_opens_only_exact_validation_projection(self) -> None:
        release = load_validation_release(REPO_ROOT)
        self.assertEqual(len(release.public_items), 27)
        self.assertEqual(len(release.candidate_supervision), 27)
        self.assertEqual(len(release.pair_supervision), 12)
        self.assertEqual(
            [item.candidate_id for item in release.public_items],
            [item.candidate_id for item in release.candidate_supervision],
        )
        for item in release.public_items:
            encoded = item.packet_bytes.decode("utf-8")
            for forbidden in (
                '"labels"',
                '"continuity_label_basis"',
                '"group_id"',
                '"pair_id"',
                '"target_dimension"',
            ):
                self.assertNotIn(forbidden, encoded)
        selected = release.commissioning_public_items()
        self.assertEqual(
            [len(item.packet_bytes) for item in selected],
            [486, 1241],
        )


class Plan100RunnerLifecycleTest(unittest.TestCase):
    def test_complete_a_only_formal_uses_explicit_residual_quality_route(self) -> None:
        release = load_validation_release(REPO_ROOT)
        freeze = _freeze("formal", "plan100-formal-20260829T120000Z-residual")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = DiagnosticArchive(
                root / "runs", freeze["run_id"], "formal"
            ).start(freeze)
            ledger = Plan100BudgetLedger(root / "ledger.json")
            execution = run_batch(
                freeze,
                release.public_items,
                archive=archive,
                ledger=ledger,
                evaluator=_AOnlyResidualEvaluator(release),
            )
            self.assertTrue(execution["complete"])
            result = recompute_formal(freeze, release, archive, ledger)
            self.assertTrue(result["complete"])
            self.assertTrue(result["observations_complete"])
            self.assertEqual(result["route_terminal"], "CONSTRAINT_OR_DATA_ISSUE")
            self.assertTrue(result["residual_mixed_signal"])
            self.assertIsNone(result["route_contract_gap"])
            self.assertTrue(result["metrics"]["A"]["meets_gate"])
            self.assertFalse(result["metrics"]["B"]["meets_basic"])
            self.assertFalse(result["metrics"]["C"]["meets_basic"])
            tracked = tracked_projection(result)
            self.assertTrue(tracked["residual_mixed_signal"])
            self.assertEqual(tracked["route_terminal"], "CONSTRAINT_OR_DATA_ISSUE")

    def test_fake_formal_runs_81_once_and_recomputes_without_supervision_leak(
        self,
    ) -> None:
        release = load_validation_release(REPO_ROOT)
        freeze = _freeze("formal", "plan100-formal-20260829T120000Z-fake")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = DiagnosticArchive(
                root / "runs", freeze["run_id"], "formal"
            ).start(freeze)
            ledger = Plan100BudgetLedger(root / "ledger.json")
            evaluator = _FakeEvaluator()
            execution = run_batch(
                freeze,
                release.public_items,
                archive=archive,
                ledger=ledger,
                evaluator=evaluator,
            )
            self.assertTrue(execution["complete"])
            self.assertEqual(execution["terminal_observation_count"], 81)
            self.assertEqual(len(evaluator.calls), 81)
            self.assertEqual(
                [task for task, _ in evaluator.calls],
                [DiagnosticTask.SCALAR] * 27
                + [DiagnosticTask.DIRECT] * 27
                + [DiagnosticTask.STRUCTURED] * 27,
            )
            for index, item in enumerate(release.public_items):
                self.assertEqual(evaluator.calls[index][1], item.packet_bytes)
                self.assertEqual(evaluator.calls[index + 27][1], item.packet_bytes)
                self.assertEqual(evaluator.calls[index + 54][1], item.packet_bytes)

            result = recompute_formal(freeze, release, archive, ledger)
            self.assertTrue(result["complete"])
            self.assertEqual(
                result["route_terminal"], "TASK_EXECUTABILITY_INSUFFICIENT"
            )
            self.assertEqual(
                canonical_json_bytes(result),
                canonical_json_bytes(
                    recompute_formal(freeze, release, archive, ledger)
                ),
            )
            self.assertEqual(result["task_budget"]["settled_rmb"], "0.011097")
            tracked = tracked_projection(result)
            tracked_text = json.dumps(tracked, sort_keys=True)
            self.assertNotIn("response_text", tracked_text)
            self.assertNotIn("candidate_id", tracked_text)
            self.assertNotIn(release.public_items[0].candidate_id, tracked_text)

            second = _FakeEvaluator()
            resumed = run_batch(
                freeze,
                release.public_items,
                archive=archive,
                ledger=ledger,
                evaluator=second,
            )
            self.assertTrue(resumed["complete"])
            self.assertEqual(second.calls, [])
            archive.claim_formal_result(freeze, result)
            reopened = DiagnosticArchive(
                root / "runs", freeze["run_id"], "formal"
            ).reopen_read_only(freeze)
            self.assertEqual(
                canonical_json_bytes(
                    recompute_formal(freeze, release, reopened, ledger)
                ),
                canonical_json_bytes(result),
            )
            with self.assertRaisesRegex(
                DiagnosticArchiveError, "formal_result_already_authoritative"
            ):
                DiagnosticArchive(root / "runs", freeze["run_id"], "formal").resume(
                    freeze
                )

    def test_parse_failure_is_terminal_and_never_retried(self) -> None:
        release = load_validation_release(REPO_ROOT)
        freeze = _freeze("formal", "plan100-formal-20260829T120000Z-parse")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = DiagnosticArchive(
                root / "runs", freeze["run_id"], "formal"
            ).start(freeze)
            ledger = Plan100BudgetLedger(root / "ledger.json")
            evaluator = _FakeEvaluator(first="parse")
            execution = run_batch(
                freeze,
                release.public_items,
                archive=archive,
                ledger=ledger,
                evaluator=evaluator,
            )
            self.assertTrue(execution["complete"])
            self.assertEqual(len(evaluator.calls), 81)
            result = recompute_formal(freeze, release, archive, ledger)
            self.assertEqual(result["parse_failure_count"], {"A": 1, "B": 0, "C": 0})
            self.assertEqual(result["metrics"]["A"]["auc"], None)
            second = _FakeEvaluator()
            run_batch(
                freeze,
                release.public_items,
                archive=archive,
                ledger=ledger,
                evaluator=second,
            )
            self.assertEqual(second.calls, [])

    def test_commissioning_technical_receipt_resumes_only_failed_logical_item(
        self,
    ) -> None:
        items = load_commissioning_public_items(REPO_ROOT)
        freeze = _freeze(
            "commissioning",
            "plan100-commissioning-20260829T120000Z-resume",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = DiagnosticArchive(
                root / "runs", freeze["run_id"], "commissioning"
            ).start(freeze)
            ledger = Plan100BudgetLedger(root / "ledger.json")
            first = _FakeEvaluator(first="technical")
            stopped = run_batch(
                freeze,
                items,
                archive=archive,
                ledger=ledger,
                evaluator=first,
            )
            self.assertFalse(stopped["complete"])
            self.assertEqual(len(first.calls), 1)
            resumed_evaluator = _FakeEvaluator()
            resumed = run_batch(
                freeze,
                items,
                archive=archive,
                ledger=ledger,
                evaluator=resumed_evaluator,
            )
            self.assertTrue(resumed["complete"])
            self.assertEqual(len(resumed_evaluator.calls), 9)
            receipts = archive.load_receipts(f"A:{items[0].candidate_id}")
            self.assertEqual(len(receipts), 2)
            result = recompute_commissioning(
                freeze, items, archive, ledger, _FakeRecounter()
            )
            self.assertTrue(result["complete"])
            self.assertEqual(result["successful_terminal_observation_count"], 9)
            self.assertEqual(result["calibration"]["calibrated_attempt_count"], 9)
            binding = build_commissioning_binding(freeze, result)
            validate_commissioning_binding(
                binding,
                _freeze("formal", "plan100-formal-20260829T130000Z-bound"),
            )
            drifted_formal = _freeze(
                "formal", "plan100-formal-20260829T130000Z-drifted"
            )
            drifted_formal["source"]["descriptor_sha256"] = "8" * 64
            with self.assertRaisesRegex(
                DiagnosticFreezeError, "formal_identity_not_commissioned"
            ):
                validate_commissioning_binding(binding, drifted_formal)

    def test_commissioning_parse_or_uncalibrated_result_cannot_unlock_formal(
        self,
    ) -> None:
        items = load_commissioning_public_items(REPO_ROOT)
        freeze = _freeze(
            "commissioning",
            "plan100-commissioning-20260829T120000Z-parse",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = DiagnosticArchive(
                root / "runs", freeze["run_id"], "commissioning"
            ).start(freeze)
            ledger = Plan100BudgetLedger(root / "ledger.json")
            execution = run_batch(
                freeze,
                items,
                archive=archive,
                ledger=ledger,
                evaluator=_FakeEvaluator(first="parse"),
            )
            self.assertFalse(execution["complete"])
            result = recompute_commissioning(
                freeze, items, archive, ledger, _FakeRecounter(prompt_tokens=101)
            )
            self.assertFalse(result["complete"])
            self.assertEqual(result["parse_failure_count"], 1)
            with self.assertRaisesRegex(
                DiagnosticRunnerError, "commissioning_binding_requires_success"
            ):
                build_commissioning_binding(freeze, result)

            forged = {
                "schema": "rondo-publication-critic-plan100-commissioning-binding@v1",
                "run_id": freeze["run_id"],
                "commissioning_freeze": freeze,
                "freeze_sha256": result["freeze_sha256"],
                "commissioning_result": result | {"complete": True},
                "result_sha256": "0" * 64,
            }
            with self.assertRaises(DiagnosticFreezeError):
                validate_commissioning_binding(
                    forged,
                    _freeze("formal", "plan100-formal-20260829T130000Z-forged"),
                )

    def test_reserved_without_receipt_stops_without_another_call(self) -> None:
        release = load_validation_release(REPO_ROOT)
        freeze = _freeze("formal", "plan100-formal-20260829T120000Z-ambiguous")
        item = release.public_items[0]
        logical_key = f"A:{item.candidate_id}"
        budget_key = f"{freeze['run_id']}:{logical_key}:1"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = DiagnosticArchive(
                root / "runs", freeze["run_id"], "formal"
            ).start(freeze)
            ledger = Plan100BudgetLedger(root / "ledger.json")
            ledger.reserve(budget_key, Decimal("0.2"))
            evaluator = _FakeEvaluator()
            with self.assertRaises(AmbiguousAttemptError):
                run_batch(
                    freeze,
                    release.public_items,
                    archive=archive,
                    ledger=ledger,
                    evaluator=evaluator,
                )
            self.assertEqual(evaluator.calls, [])


class Plan100RouteTest(unittest.TestCase):
    def test_gold_projection_closes_all_frozen_candidate_dimension_and_pair_gates(
        self,
    ) -> None:
        release = load_validation_release(REPO_ROOT)
        supervision = release.candidate_supervision
        ids = [row.candidate_id for row in supervision]
        verdicts = [row.gold_verdict for row in supervision]
        scalar = scalar_metrics(
            ids,
            verdicts,
            [1.0 if verdict == "PASS" else 0.0 for verdict in verdicts],
            release.pair_supervision,
        )
        direct = direct_metrics(ids, verdicts, verdicts, release.pair_supervision)
        structured = structured_metrics(
            ids,
            [row.labels for row in supervision],
            [row.labels for row in supervision],
            release.pair_supervision,
        )
        self.assertTrue(scalar["meets_gate"])
        self.assertTrue(direct["meets_gate"])
        self.assertTrue(structured["meets_gate"])

    @staticmethod
    def _scalar(correct: int, pairs: int, *, basic: bool, gate: bool) -> dict:
        return {
            "meets_basic": basic,
            "meets_gate": gate,
            "selected_operating_point": {
                "binary": {"correct": correct},
                "pairs": {"closed": pairs},
            },
        }

    @staticmethod
    def _arm(
        correct: int,
        pairs: int,
        *,
        basic: bool,
        gate: bool,
        dimensions_good: bool = False,
        concentrated: bool = False,
    ) -> dict:
        return {
            "meets_basic": basic,
            "meets_gate": gate,
            "binary": {"correct": correct},
            "pairs": {"closed": pairs},
            "dimensions_generally_good": dimensions_good,
            "concentrated_blocker": concentrated,
        }

    def test_priority_terminals_and_exhaustive_residual_marker_are_explicit(
        self,
    ) -> None:
        tracked_route = json.loads(
            (
                REPO_ROOT
                / "eval/templates/publication-critic/plan100-diagnostic-contract-v1.json"
            ).read_text(encoding="utf-8")
        )["route"]
        self.assertEqual(
            tracked_route["otherwise"],
            "CONSTRAINT_OR_DATA_ISSUE_with_residual_mixed_signal_true_for_complete_valid_formal",
        )
        self.assertTrue(tracked_route["residual_preserves_metrics"])
        scalar_low = self._scalar(18, 4, basic=False, gate=False)
        direct_low = self._arm(19, 5, basic=False, gate=False)
        structured_high = self._arm(24, 10, basic=True, gate=True)
        self.assertEqual(
            decide_route(scalar_low, direct_low, structured_high, formal_valid=True),
            "FIVE_DIMENSION_STRONGLY_SUPPORTED",
        )
        self.assertFalse(
            decide_route_with_metadata(
                scalar_low, direct_low, structured_high, formal_valid=True
            )["residual_mixed_signal"]
        )

        direct_high = self._arm(24, 10, basic=True, gate=True)
        structured_close = self._arm(25, 10, basic=True, gate=True)
        self.assertEqual(
            decide_route(scalar_low, direct_high, structured_close, formal_valid=True),
            "DISCRETE_SUPPORTED_FIVE_DIMENSION_INCREMENT_UNCONFIRMED",
        )
        constrained = self._arm(
            22,
            8,
            basic=True,
            gate=False,
            dimensions_good=True,
            concentrated=True,
        )
        self.assertEqual(
            decide_route(scalar_low, direct_low, constrained, formal_valid=True),
            "CONSTRAINT_OR_DATA_ISSUE",
        )
        self.assertFalse(
            decide_route_with_metadata(
                scalar_low, direct_low, constrained, formal_valid=True
            )["residual_mixed_signal"]
        )
        self.assertEqual(
            decide_route(
                scalar_low,
                direct_low,
                self._arm(18, 4, basic=False, gate=False),
                formal_valid=True,
            ),
            "TASK_EXECUTABILITY_INSUFFICIENT",
        )
        self.assertEqual(
            decide_route(scalar_low, direct_low, structured_high, formal_valid=False),
            "INCONCLUSIVE_TECHNICAL_OR_BUDGET",
        )
        self.assertFalse(
            decide_route_with_metadata(
                scalar_low, direct_low, structured_high, formal_valid=False
            )["residual_mixed_signal"]
        )

        residuals = {
            "A_only": (
                self._scalar(24, 10, basic=True, gate=True),
                direct_low,
                self._arm(20, 6, basic=False, gate=False),
            ),
            "B_only": (
                scalar_low,
                self._arm(24, 10, basic=True, gate=True),
                self._arm(20, 6, basic=False, gate=False),
            ),
            "mixed_basic": (
                self._scalar(21, 7, basic=True, gate=False),
                self._arm(21, 7, basic=True, gate=False),
                self._arm(
                    21,
                    7,
                    basic=True,
                    gate=False,
                    dimensions_good=True,
                ),
            ),
        }
        for name, (scalar, direct, structured) in residuals.items():
            with self.subTest(name=name):
                decision = decide_route_with_metadata(
                    scalar, direct, structured, formal_valid=True
                )
                self.assertEqual(decision["terminal"], "CONSTRAINT_OR_DATA_ISSUE")
                self.assertTrue(decision["residual_mixed_signal"])
                self.assertNotEqual(
                    decision["terminal"], "INCONCLUSIVE_TECHNICAL_OR_BUDGET"
                )


if __name__ == "__main__":
    unittest.main()
