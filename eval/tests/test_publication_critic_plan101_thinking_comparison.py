import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.identity import canonical_json_bytes, sha256_bytes
from rondo_eval.publication_critic.structured_diagnostic.contract import (
    DiagnosticTask,
    parse_output,
)
from rondo_eval.publication_critic.structured_diagnostic.cost import (
    Plan100BudgetLedger,
    settle_attempt,
    worst_case_reservation_rmb,
)
from rondo_eval.publication_critic.structured_diagnostic.release import PublicItem
from rondo_eval.publication_critic.thinking_comparison.archive import ComparisonArchive
from rondo_eval.publication_critic.thinking_comparison.freeze import (
    build_freeze,
    validate_freeze,
)
from rondo_eval.publication_critic.thinking_comparison.metrics import (
    difference_table,
    majority_discrete,
    miss_versus_wrong_drawer,
    repeat_consistency,
    scalar_tie_stats,
    unit_metrics,
    wilson_interval,
)
from rondo_eval.publication_critic.thinking_comparison.runner import (
    logical_key,
    recompute_formal,
    run_batch,
    tracked_projection,
)


def _freeze(mode: str, run_id: str, *, on_repeats: int = 5) -> dict:
    off = 1 if mode == "commissioning" else 2
    on = 1 if mode == "commissioning" else on_repeats
    return build_freeze(
        mode=mode,
        run_id=run_id,
        git_commit="1" * 40,
        diagnostic_contract_sha256="2" * 64,
        executable_sha256="3" * 64,
        descriptor_sha256="4" * 64,
        thinking_off_repeats=off,
        thinking_on_repeats=on,
        missing_usage_rmb=Decimal("1"),
        commissioning_binding_sha256="6" * 64 if mode == "formal" else None,
    )


def _packet(candidate_id: str) -> dict:
    return {
        "actor_role": "member",
        "candidate": {"handoff": "", "summary": f"packet for {candidate_id}"},
        "continuity": {"state": "not_applicable"},
        "evidence_v1": {
            "candidate_window": "not_frozen_before_commit",
            "semantic_entailment": "not_evaluated",
        },
        "local_scope": {"title": candidate_id},
        "qualification": {
            "packet_schema": {"name": "rondo-publication-packet", "revision": "v1"},
            "rubric": {"name": "rondo-publication-qualification", "revision": "v2"},
        },
        "target_kind": "new_event",
    }


def _item(candidate_id: str) -> PublicItem:
    packet = _packet(candidate_id)
    body = canonical_json_bytes(packet)
    return PublicItem(candidate_id=candidate_id, packet=packet, packet_bytes=body)


def _attempt() -> dict:
    return {
        "attempt": 1,
        "requested_at": "2026-08-31T04:00:00+00:00",
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
    def __init__(self, *, quality: float, completion_tokens: int) -> None:
        self.quality = quality
        self.completion_tokens = completion_tokens
        self.calls: list[tuple[DiagnosticTask, bytes]] = []

    def evaluate(self, task: DiagnosticTask, packet: dict) -> dict:
        self.calls.append((task, canonical_json_bytes(dict(packet))))
        title = packet["local_scope"]["title"]
        if task is DiagnosticTask.SCALAR:
            # Distinct per packet so commissioning non-degeneration can pass.
            quality = min(0.9, max(0.1, self.quality + (len(title) % 7) * 0.03))
            response = json.dumps({"quality": quality}, separators=(",", ":"))
        elif task is DiagnosticTask.DIRECT:
            verdict = "PASS" if len(title) % 2 == 0 else "REWRITE"
            response = json.dumps({"verdict": verdict}, separators=(",", ":"))
        else:
            fail = "FAIL" if len(title) % 2 else "PASS"
            response = json.dumps(
                {
                    "useful_state_transfer": fail,
                    "honest_uncertainty": "PASS",
                    "conditional_continuity": "N/A",
                    "scope_and_signal": "PASS",
                    "internal_consistency": "PASS",
                },
                separators=(",", ":"),
            )
        usage = {
            "prompt_tokens": 80,
            "completion_tokens": self.completion_tokens,
            "prompt_cache_hit_tokens": 10,
            "prompt_cache_miss_tokens": 70,
        }
        attempt = {
            "attempt": 1,
            "requested_at": "2026-08-31T04:00:00+00:00",
            "usage": usage,
            "recount": None,
            "explicitly_unbilled": False,
        }
        return {
            "requested_model": "deepseek-v4-flash",
            "served_model": "deepseek-v4-flash",
            "response_text": response,
            "attempts": [attempt],
            "elapsed_ms": 12,
            "outcome": {"type": "success"},
        }


class OutputContractTests(unittest.TestCase):
    def test_placeholder_templates_are_not_valid_outputs(self) -> None:
        self.assertRaises(
            Exception, parse_output, DiagnosticTask.SCALAR, '{"quality":<number in [0,1]>}'
        )
        self.assertRaises(
            Exception,
            parse_output,
            DiagnosticTask.DIRECT,
            '{"verdict":<PASS or REWRITE>}',
        )
        self.assertRaises(
            Exception,
            parse_output,
            DiagnosticTask.STRUCTURED,
            '{"useful_state_transfer":<PASS or FAIL>,"honest_uncertainty":<PASS or FAIL>,'
            '"conditional_continuity":<PASS, FAIL, or N/A>,"scope_and_signal":<PASS or FAIL>,'
            '"internal_consistency":<PASS or FAIL>}',
        )


class MetricSliceTests(unittest.TestCase):
    def test_wilson_and_ties_and_drawers_and_consistency(self) -> None:
        interval = wilson_interval(18, 27)
        self.assertGreater(interval["high"], interval["low"])
        ties = scalar_tie_stats(
            ["a", "b", "c", "d"],
            ["PASS", "PASS", "REWRITE", "REWRITE"],
            [0.4, 0.4, 0.4, 0.9],
        )
        self.assertEqual(ties["distinct_values"], 2)
        self.assertEqual(ties["exact_ties"], 2)
        drawers = miss_versus_wrong_drawer(
            ["g1", "g2"],
            [
                {
                    "useful_state_transfer": "FAIL",
                    "honest_uncertainty": "PASS",
                    "conditional_continuity": "N/A",
                    "scope_and_signal": "PASS",
                    "internal_consistency": "PASS",
                },
                {
                    "useful_state_transfer": "FAIL",
                    "honest_uncertainty": "PASS",
                    "conditional_continuity": "N/A",
                    "scope_and_signal": "PASS",
                    "internal_consistency": "PASS",
                },
            ],
            [
                {
                    "useful_state_transfer": "PASS",
                    "honest_uncertainty": "FAIL",
                    "conditional_continuity": "N/A",
                    "scope_and_signal": "PASS",
                    "internal_consistency": "PASS",
                },
                {
                    "useful_state_transfer": "PASS",
                    "honest_uncertainty": "PASS",
                    "conditional_continuity": "N/A",
                    "scope_and_signal": "PASS",
                    "internal_consistency": "PASS",
                },
            ],
        )
        self.assertEqual(drawers["wrong_drawer"], 1)
        self.assertEqual(drawers["gate_miss"], 1)
        self.assertEqual(drawers["wrong_drawer_miss"], 1)
        self.assertEqual(drawers["unnoticed_miss"], 1)
        self.assertTrue(repeat_consistency(["PASS", "PASS"])["agreed"])
        self.assertFalse(repeat_consistency(["PASS", "REWRITE"])["agreed"])
        self.assertIsNone(majority_discrete(["PASS", "REWRITE"]))
        self.assertEqual(majority_discrete(["PASS", "PASS", "REWRITE"]), "PASS")

    def test_unit_metrics_omit_gate_fields(self) -> None:
        ids = [f"c{i}" for i in range(12)] + [f"r{i}" for i in range(15)]
        gold = ["PASS"] * 12 + ["REWRITE"] * 15
        predicted = ["PASS"] * 10 + ["REWRITE"] * 2 + ["REWRITE"] * 12 + ["PASS"] * 3
        labels = [
            {
                "useful_state_transfer": "PASS" if verdict == "PASS" else "FAIL",
                "honest_uncertainty": "PASS",
                "conditional_continuity": "N/A",
                "scope_and_signal": "PASS",
                "internal_consistency": "PASS",
            }
            for verdict in gold
        ]
        predicted_labels = [
            {
                "useful_state_transfer": "PASS" if verdict == "PASS" else "FAIL",
                "honest_uncertainty": "PASS",
                "conditional_continuity": "N/A",
                "scope_and_signal": "PASS",
                "internal_consistency": "PASS",
            }
            for verdict in predicted
        ]
        repeats = {item_id: [predicted[index], predicted[index]] for index, item_id in enumerate(ids)}
        unit = unit_metrics(
            arm="C",
            candidate_ids=ids,
            gold_verdicts=gold,
            gold_labels=labels,
            predicted_verdicts=predicted,
            predicted_labels=predicted_labels,
            scores=[None] * 27,
            pairs=(),
            per_candidate_repeats=repeats,
        )
        dumped = json.dumps(unit)
        self.assertNotIn("meets_gate", dumped)
        self.assertNotIn("meets_candidate_gate", dumped)
        self.assertNotIn("meets_basic", dumped)
        self.assertIn("balanced_accuracy_wilson", dumped)


class ArchiveAndRunnerTests(unittest.TestCase):
    def test_logical_key_includes_condition_arm_candidate_and_repeat(self) -> None:
        self.assertEqual(
            logical_key("thinking_on", DiagnosticTask.SCALAR, "cand-1", 3),
            "thinking_on:A:cand-1:r03",
        )

    def test_reservation_covers_missing_usage_retry_via_top_up(self) -> None:
        reserve = worst_case_reservation_rmb(
            max_attempts=2,
            max_prompt_tokens=16_384,
            max_completion_tokens=131_072,
            missing_usage_rmb=Decimal("1"),
        )
        self.assertGreaterEqual(reserve, Decimal("2"))
        attempts = [
            {
                "attempt": 1,
                "requested_at": "2026-08-31T04:00:00+00:00",
                "usage": None,
                "recount": None,
                "explicitly_unbilled": False,
            },
            {
                "attempt": 2,
                "requested_at": "2026-08-31T04:01:00+00:00",
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "prompt_cache_hit_tokens": 40,
                    "prompt_cache_miss_tokens": 60,
                },
                "recount": None,
                "explicitly_unbilled": False,
            },
        ]
        needed = sum(
            (
                Decimal(settle_attempt(item, missing_usage_rmb=Decimal("1"))["charge_rmb"])
                for item in attempts
            ),
            Decimal(0),
        )
        with tempfile.TemporaryDirectory() as raw:
            ledger = Plan100BudgetLedger(
                Path(raw) / "budget-ledger.json", missing_usage_rmb=Decimal("1")
            )
            ledger.reserve("stuck:retry:1", Decimal("0.24576"))
            ledger.top_up_reservation("stuck:retry:1", needed)
            ledger.settle("stuck:retry:1", attempts)
            snapshot = ledger.snapshot()
            self.assertEqual(snapshot["settled_rmb"], format(needed, "f"))
            self.assertEqual(snapshot["outstanding_reserved_rmb"], "0")

    def test_commissioning_matrix_writes_eighteen_keys(self) -> None:
        freeze = _freeze(
            "commissioning", "plan101-commissioning-20260831T120000Z-test"
        )
        items = [_item("alpha"), _item("beta"), _item("gamma")]
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runs = root / "runs"
            ledger_path = root / "budget-ledger.json"
            archive = ComparisonArchive(runs, freeze["run_id"], "commissioning").start(
                freeze
            )
            ledger = Plan100BudgetLedger(ledger_path, missing_usage_rmb=Decimal("1"))
            evaluators = {
                "thinking_off": _FakeEvaluator(quality=0.31, completion_tokens=8),
                "thinking_on": _FakeEvaluator(quality=0.44, completion_tokens=80),
            }
            execution = run_batch(
                freeze,
                items,
                archive=archive,
                ledger=ledger,
                evaluators=evaluators,
            )
            self.assertTrue(execution["complete"])
            self.assertEqual(execution["terminal_observation_count"], 18)
            key = logical_key("thinking_off", DiagnosticTask.SCALAR, "alpha", 1)
            self.assertIsNotNone(archive.load_terminal(key))
            self.assertEqual(
                evaluators["thinking_off"].calls[0][1],
                canonical_json_bytes(dict(items[0].packet)),
            )
            dumped = json.dumps(execution)
            self.assertNotIn("meets_gate", dumped)

    def test_placeholders_and_tracked_projection_have_no_route(self) -> None:
        ids = [f"c{i:02d}" for i in range(27)]
        gold = ["PASS"] * 12 + ["REWRITE"] * 15
        predicted = ["PASS"] * 12 + ["REWRITE"] * 15
        labels = [
            {
                "useful_state_transfer": "PASS" if verdict == "PASS" else "FAIL",
                "honest_uncertainty": "PASS",
                "conditional_continuity": "N/A",
                "scope_and_signal": "PASS",
                "internal_consistency": "PASS",
            }
            for verdict in gold
        ]
        units = {}
        for condition in ("thinking_off", "thinking_on"):
            for arm in ("A", "B", "C"):
                units[f"{condition}:{arm}"] = unit_metrics(
                    arm=arm if arm != "A" else "B",
                    candidate_ids=ids,
                    gold_verdicts=gold,
                    gold_labels=labels,
                    predicted_verdicts=predicted,
                    predicted_labels=labels,
                    scores=[0.7 if verdict == "PASS" else 0.2 for verdict in gold]
                    if arm == "A"
                    else [None] * 27,
                    pairs=(),
                    per_candidate_repeats={item_id: [predicted[i]] * 2 for i, item_id in enumerate(ids)},
                )
                if arm == "A":
                    units[f"{condition}:{arm}"] = unit_metrics(
                        arm="A",
                        candidate_ids=ids,
                        gold_verdicts=gold,
                        gold_labels=labels,
                        predicted_verdicts=predicted,
                        predicted_labels=[None] * 27,
                        scores=[0.7 if verdict == "PASS" else 0.2 for verdict in gold],
                        pairs=(),
                        per_candidate_repeats={
                            item_id: [0.7 if gold[i] == "PASS" else 0.2] * 2
                            for i, item_id in enumerate(ids)
                        },
                    )
        table = difference_table(units)
        self.assertIn("thinking_on_minus_off", table)
        self.assertIn("C_minus_B", table["expression"]["thinking_off"])
        tracked = tracked_projection(
            {
                "schema": "rondo-publication-critic-plan101-comparison-result@v1",
                "freeze_sha256": "a" * 64,
                "complete": True,
                "terminal_observation_count": 567,
                "expected_terminal_observation_count": 567,
                "thinking_off_repeats": 2,
                "thinking_on_repeats": 5,
                "parse_failure_count": {},
                "usage_and_cost": {
                    "attempts": 1,
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "elapsed_ms": 1,
                    "settled_rmb": "0.0",
                },
                "task_budget": {
                    "schema": "x",
                    "cap_rmb": "20",
                    "settled_rmb": "0",
                    "outstanding_reserved_rmb": "0",
                    "remaining_unreserved_rmb": "20",
                },
                "metrics": units,
                "differences": table,
            }
        )
        self.assertNotIn("route_terminal", tracked)
        self.assertNotIn("meets_gate", json.dumps(tracked))


if __name__ == "__main__":
    unittest.main()
