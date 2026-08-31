"""Plan 101 comparison metrics: intervals, ties, drawers, and repeat consistency.

This module never emits route terminals or meets_gate fields.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from ..successor_task import DIMENSION_CLASSES, HARD_DIMENSIONS
from ..structured_diagnostic.contract import derive_verdict
from ..structured_diagnostic.metrics import (
    binary_metrics,
    pair_verdict_metrics,
    roc_auc,
)

SENSITIVE_CANDIDATE_IDS = (
    "pcv9-hard-boundaries-validation-03-qminus",
    "pcv9-soft-combinations-020-hard-fail",
    "pcv9-continuity-context-019-qminus",
)
Z_WILSON = 1.96


class ComparisonMetricsError(ValueError):
    """Metric inputs do not form one comparable Plan 101 unit."""


def wilson_interval(successes: int, n: int, *, z: float = Z_WILSON) -> dict[str, float]:
    if type(successes) is not int or type(n) is not int or successes < 0 or n <= 0:
        raise ComparisonMetricsError("wilson_inputs_invalid")
    if successes > n:
        raise ComparisonMetricsError("wilson_inputs_invalid")
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    return {
        "low": max(0.0, center - margin),
        "high": min(1.0, center + margin),
        "n": float(n),
        "successes": float(successes),
    }


def _strip_gate(binary: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in binary.items() if key != "meets_candidate_gate"}


def _recall_interval(binary: Mapping[str, Any], gold: str) -> dict[str, float]:
    support = sum(binary["confusion"][gold].values())
    correct = binary["confusion"][gold][gold]
    return wilson_interval(correct, support)


def _balanced_accuracy_interval(binary: Mapping[str, Any]) -> dict[str, float]:
    pass_interval = _recall_interval(binary, "PASS")
    rewrite_interval = _recall_interval(binary, "REWRITE")
    return {
        "low": (pass_interval["low"] + rewrite_interval["low"]) / 2.0,
        "high": (pass_interval["high"] + rewrite_interval["high"]) / 2.0,
        "n": binary["total"],
    }


def scalar_tie_stats(
    candidate_ids: Sequence[str],
    gold_verdicts: Sequence[str],
    scores: Sequence[float | None],
) -> dict[str, Any]:
    if len(candidate_ids) != len(gold_verdicts) or len(candidate_ids) != len(scores):
        raise ComparisonMetricsError("tie_rows_invalid")
    finite = [
        (gold, score)
        for gold, score in zip(gold_verdicts, scores, strict=True)
        if score is not None
    ]
    values = [score for _, score in finite]
    distinct = sorted(set(values))
    positives = [score for gold, score in finite if gold == "PASS"]
    negatives = [score for gold, score in finite if gold == "REWRITE"]
    cross = len(positives) * len(negatives)
    ties = sum(
        1
        for positive in positives
        for negative in negatives
        if positive == negative
    )
    return {
        "finite_scores": len(values),
        "distinct_values": len(distinct),
        "distinct_value_list": distinct,
        "cross_class_pairs": cross,
        "exact_ties": ties,
        "tie_ratio": None if cross == 0 else ties / cross,
    }


def repeat_consistency(outputs: Sequence[Any]) -> dict[str, Any]:
    """outputs is one value per repeat; None means parse/typed failure."""

    if not outputs:
        raise ComparisonMetricsError("repeat_outputs_empty")
    serialized = [_stable(item) for item in outputs]
    agreed = len(set(serialized)) == 1 and serialized[0] is not None
    return {
        "repeats": len(outputs),
        "agreed": agreed,
        "distinct_repeat_values": len({item for item in serialized if item is not None}),
        "typed_failures": sum(item is None for item in outputs),
    }


def miss_versus_wrong_drawer(
    candidate_ids: Sequence[str],
    gold_labels: Sequence[Mapping[str, str]],
    predicted_labels: Sequence[Mapping[str, str] | None],
) -> dict[str, Any]:
    if not (
        len(candidate_ids) == len(gold_labels) == len(predicted_labels) and candidate_ids
    ):
        raise ComparisonMetricsError("drawer_rows_invalid")
    candidate_rows: list[dict[str, Any]] = []
    dimension_rows: list[dict[str, Any]] = []
    gold_fail_candidates = 0
    exact_fail_set = 0
    wrong_drawer = 0
    gate_miss = 0
    gold_fail_cells = 0
    wrong_drawer_miss = 0
    unnoticed_miss = 0
    for candidate_id, gold, predicted in zip(
        candidate_ids, gold_labels, predicted_labels, strict=True
    ):
        gold_fail = {name for name, label in gold.items() if label == "FAIL"}
        gold_verdict = derive_verdict(gold)
        if gold_verdict != "REWRITE":
            continue
        gold_fail_candidates += 1
        if predicted is None:
            predicted_fail: set[str] = set()
            predicted_verdict = None
        else:
            predicted_fail = {name for name, label in predicted.items() if label == "FAIL"}
            predicted_verdict = derive_verdict(predicted)
        if predicted_verdict != "REWRITE":
            kind = "gate_miss"
            gate_miss += 1
        elif predicted_fail == gold_fail:
            kind = "exact_fail_set"
            exact_fail_set += 1
        else:
            kind = "wrong_drawer"
            wrong_drawer += 1
        candidate_rows.append(
            {
                "candidate_id": candidate_id,
                "kind": kind,
                "gold_fail": sorted(gold_fail),
                "predicted_fail": sorted(predicted_fail),
            }
        )
        any_predicted_fail = bool(predicted_fail)
        for dimension in gold_fail:
            gold_fail_cells += 1
            predicted_label = None if predicted is None else predicted[dimension]
            if predicted_label == "FAIL":
                continue
            if any_predicted_fail:
                miss_kind = "wrong_drawer_miss"
                wrong_drawer_miss += 1
            else:
                miss_kind = "unnoticed_miss"
                unnoticed_miss += 1
            dimension_rows.append(
                {
                    "candidate_id": candidate_id,
                    "dimension": dimension,
                    "kind": miss_kind,
                }
            )
    return {
        "gold_rewrite_candidates": gold_fail_candidates,
        "exact_fail_set": exact_fail_set,
        "wrong_drawer": wrong_drawer,
        "gate_miss": gate_miss,
        "gold_fail_cells": gold_fail_cells,
        "wrong_drawer_miss": wrong_drawer_miss,
        "unnoticed_miss": unnoticed_miss,
        "candidates": candidate_rows,
        "dimension_misses": dimension_rows,
    }


def unit_metrics(
    *,
    arm: str,
    candidate_ids: Sequence[str],
    gold_verdicts: Sequence[str],
    gold_labels: Sequence[Mapping[str, str]],
    predicted_verdicts: Sequence[str | None],
    predicted_labels: Sequence[Mapping[str, str] | None],
    scores: Sequence[float | None],
    pairs: Sequence[Any],
    per_candidate_repeats: Mapping[str, Sequence[Any]],
) -> dict[str, Any]:
    if arm not in {"A", "B", "C"}:
        raise ComparisonMetricsError("unknown_arm")
    binary = _strip_gate(binary_metrics(candidate_ids, gold_verdicts, predicted_verdicts))
    pairs_metrics = pair_verdict_metrics(
        pairs, dict(zip(candidate_ids, predicted_verdicts, strict=True))
    )
    pairs_out = {key: value for key, value in pairs_metrics.items() if key != "all_closed"}
    consistency_rows = [
        {"candidate_id": candidate_id, **repeat_consistency(per_candidate_repeats[candidate_id])}
        for candidate_id in candidate_ids
    ]
    agreed = sum(row["agreed"] for row in consistency_rows)
    result: dict[str, Any] = {
        "arm": arm,
        "binary": {
            **binary,
            "pass_recall_wilson": _recall_interval(binary, "PASS"),
            "rewrite_recall_wilson": _recall_interval(binary, "REWRITE"),
            "balanced_accuracy_wilson": _balanced_accuracy_interval(binary),
        },
        "pairs": pairs_out,
        "repeat_consistency": {
            "candidates": len(consistency_rows),
            "agreed": agreed,
            "rate": agreed / len(consistency_rows),
            "rows": consistency_rows,
        },
    }
    if arm == "A":
        finite_scores = [score for score in scores if score is not None]
        result["scalar"] = {
            "auc": None
            if len(finite_scores) != len(scores)
            else roc_auc(gold_verdicts, finite_scores),
            "ties": scalar_tie_stats(candidate_ids, gold_verdicts, scores),
            "curve": _scalar_curve(candidate_ids, gold_verdicts, scores, pairs),
        }
    if arm == "C":
        result["structured"] = {
            "per_dimension": _dimension_tables(gold_labels, predicted_labels),
            "drawers": miss_versus_wrong_drawer(
                candidate_ids, gold_labels, predicted_labels
            ),
        }
    return result


def difference_table(units: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """units keyed by f"{condition}:{arm}"."""

    thinking: dict[str, Any] = {}
    for arm in ("A", "B", "C"):
        off = units[f"thinking_off:{arm}"]["binary"]
        on = units[f"thinking_on:{arm}"]["binary"]
        thinking[arm] = {
            "balanced_accuracy": on["balanced_accuracy"] - off["balanced_accuracy"],
            "false_pass": on["false_pass"] - off["false_pass"],
            "false_rewrite": on["false_rewrite"] - off["false_rewrite"],
            "pairs_closed": units[f"thinking_on:{arm}"]["pairs"]["closed"]
            - units[f"thinking_off:{arm}"]["pairs"]["closed"],
        }
        if arm == "A":
            off_auc = units[f"thinking_off:{arm}"]["scalar"]["auc"]
            on_auc = units[f"thinking_on:{arm}"]["scalar"]["auc"]
            thinking[arm]["auc"] = (
                None if off_auc is None or on_auc is None else on_auc - off_auc
            )
    expression: dict[str, Any] = {}
    for condition in ("thinking_off", "thinking_on"):
        a = units[f"{condition}:A"]["binary"]
        b = units[f"{condition}:B"]["binary"]
        c = units[f"{condition}:C"]["binary"]
        expression[condition] = {
            "C_minus_B": {
                "balanced_accuracy": c["balanced_accuracy"] - b["balanced_accuracy"],
                "false_pass": c["false_pass"] - b["false_pass"],
                "false_rewrite": c["false_rewrite"] - b["false_rewrite"],
            },
            "C_minus_A": {
                "balanced_accuracy": c["balanced_accuracy"] - a["balanced_accuracy"],
                "false_pass": c["false_pass"] - a["false_pass"],
                "false_rewrite": c["false_rewrite"] - a["false_rewrite"],
            },
            "B_minus_A": {
                "balanced_accuracy": b["balanced_accuracy"] - a["balanced_accuracy"],
                "false_pass": b["false_pass"] - a["false_pass"],
                "false_rewrite": b["false_rewrite"] - a["false_rewrite"],
            },
        }
    return {"thinking_on_minus_off": thinking, "expression": expression}


def _scalar_curve(
    candidate_ids: Sequence[str],
    gold_verdicts: Sequence[str],
    scores: Sequence[float | None],
    pairs: Sequence[Any],
) -> list[dict[str, Any]]:
    thresholds: list[float | None] = [None]
    finite = [score for score in scores if score is not None]
    thresholds.extend(sorted(set(finite), reverse=True))
    if 0.0 not in thresholds:
        thresholds.append(0.0)
    curve = []
    for threshold in thresholds:
        predicted = [
            None
            if score is None
            else "REWRITE"
            if threshold is None or score < threshold
            else "PASS"
            for score in scores
        ]
        binary = _strip_gate(binary_metrics(candidate_ids, gold_verdicts, predicted))
        pair = pair_verdict_metrics(
            pairs, dict(zip(candidate_ids, predicted, strict=True))
        )
        curve.append(
            {
                "threshold": threshold,
                "balanced_accuracy": binary["balanced_accuracy"],
                "false_pass": binary["false_pass"],
                "false_rewrite": binary["false_rewrite"],
                "correct": binary["correct"],
                "pairs_closed": pair["closed"],
            }
        )
    return curve


def _dimension_tables(
    gold_labels: Sequence[Mapping[str, str]],
    predicted_labels: Sequence[Mapping[str, str] | None],
) -> dict[str, Any]:
    per_dimension: dict[str, Any] = {}
    for dimension in HARD_DIMENSIONS:
        classes = DIMENSION_CLASSES[dimension]
        columns = (*classes, "PARSE_FAILURE")
        confusion = {actual: {guess: 0 for guess in columns} for actual in classes}
        for expected, actual in zip(gold_labels, predicted_labels, strict=True):
            guess = "PARSE_FAILURE" if actual is None else actual[dimension]
            confusion[expected[dimension]][guess] += 1
        class_recall: dict[str, float | None] = {}
        for label in classes:
            support = sum(confusion[label].values())
            class_recall[label] = (
                None if support == 0 else confusion[label][label] / support
            )
        per_dimension[dimension] = {
            "confusion": confusion,
            "class_recall": class_recall,
            "failure_recall": class_recall.get("FAIL"),
        }
    return {
        "per_dimension": per_dimension,
        "continuity_na_recall": per_dimension["conditional_continuity"]["class_recall"][
            "N/A"
        ],
    }


def _stable(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return repr(sorted(value.items()))
    return repr(value)


def majority_discrete(values: Sequence[str | None]) -> str | None:
    present = [item for item in values if item is not None]
    if len(present) != len(values) or not present:
        return None
    counts = Counter(present)
    top = counts.most_common()
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None
    return top[0][0]


def mean_score(values: Sequence[float | None]) -> float | None:
    present = [item for item in values if item is not None]
    if len(present) != len(values) or not present:
        return None
    return sum(present) / len(present)
