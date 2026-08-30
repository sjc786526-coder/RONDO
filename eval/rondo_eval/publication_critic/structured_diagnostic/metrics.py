"""Deterministic Plan 100 development metrics and pre-frozen route mapping."""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ..successor_task import DIMENSION_CLASSES, HARD_DIMENSIONS
from .contract import derive_verdict

MAX_FALSE_PASS = 3
MAX_FALSE_REWRITE = 4
MIN_BALANCED_ACCURACY = 0.75
MIN_SCALAR_AUC = 0.75
FAILURE_RECALL_FLOORS = {
    "useful_state_transfer": 2 / 3,
    "honest_uncertainty": 0.8,
    "conditional_continuity": 2 / 3,
    "scope_and_signal": 2 / 3,
    "internal_consistency": 0.75,
}
MIN_CONTINUITY_NA_RECALL = 2 / 3
MIN_SUPPORTED_CLASS_MACRO_RECALL = 0.6
EXPECTED_CANDIDATES = 27
EXPECTED_PAIRS = 12
EXPECTED_BOUNDARIES = 9


class MetricsError(ValueError):
    """Metric inputs do not form one complete comparable validation cohort."""


def binary_metrics(
    candidate_ids: Sequence[str],
    gold_verdicts: Sequence[str],
    predicted_verdicts: Sequence[str | None],
) -> dict[str, Any]:
    """Compute the shared PASS/REWRITE metrics; typed failures fail closed."""

    if not candidate_ids or not (
        len(candidate_ids) == len(gold_verdicts) == len(predicted_verdicts)
    ):
        raise MetricsError("binary metric rows must be equal and non-empty")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise MetricsError("binary metric candidate ids must be unique")
    rows: list[dict[str, Any]] = []
    confusion = {
        "PASS": {"PASS": 0, "REWRITE": 0},
        "REWRITE": {"PASS": 0, "REWRITE": 0},
    }
    typed_failures = 0
    for candidate_id, gold, predicted in zip(
        candidate_ids,
        gold_verdicts,
        predicted_verdicts,
        strict=True,
    ):
        _verdict(gold, "gold verdict")
        if predicted is None:
            effective = "REWRITE"
            typed_failures += 1
        else:
            effective = _verdict(predicted, "predicted verdict")
        confusion[gold][effective] += 1
        rows.append(
            {
                "candidate_id": candidate_id,
                "gold": gold,
                "predicted": predicted,
                "effective_predicted": effective,
                "correct": gold == effective,
            }
        )
    pass_total = sum(confusion["PASS"].values())
    rewrite_total = sum(confusion["REWRITE"].values())
    if not pass_total or not rewrite_total:
        raise MetricsError("balanced accuracy requires both gold verdict classes")
    pass_recall = confusion["PASS"]["PASS"] / pass_total
    rewrite_recall = confusion["REWRITE"]["REWRITE"] / rewrite_total
    false_pass = confusion["REWRITE"]["PASS"]
    false_rewrite = confusion["PASS"]["REWRITE"]
    return {
        "total": len(rows),
        "correct": confusion["PASS"]["PASS"] + confusion["REWRITE"]["REWRITE"],
        "false_pass": false_pass,
        "false_rewrite": false_rewrite,
        "balanced_accuracy": (pass_recall + rewrite_recall) / 2,
        "class_recall": {"PASS": pass_recall, "REWRITE": rewrite_recall},
        "confusion": confusion,
        "typed_failures": typed_failures,
        "candidate_errors": [row for row in rows if not row["correct"]],
        "rows": rows,
        "meets_candidate_gate": (
            len(rows) == EXPECTED_CANDIDATES
            and typed_failures == 0
            and false_pass <= MAX_FALSE_PASS
            and false_rewrite <= MAX_FALSE_REWRITE
            and (pass_recall + rewrite_recall) / 2 >= MIN_BALANCED_ACCURACY
        ),
    }


def pair_verdict_metrics(
    pairs: Sequence[Any],
    verdict_by_id: Mapping[str, str | None],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for pair in pairs:
        pair_id = _field(pair, "pair_id")
        kind = _field(pair, "kind")
        if kind not in {"boundary", "soft_only_invariance"}:
            raise MetricsError(f"invalid pair kind: {pair_id}")
        left_value = _required_lookup(verdict_by_id, _field(pair, "left_candidate_id"))
        right_value = _required_lookup(
            verdict_by_id, _field(pair, "right_candidate_id")
        )
        typed_failure = left_value is None or right_value is None
        left = _effective_verdict(left_value)
        right = _effective_verdict(right_value)
        if typed_failure:
            closed = False
        elif kind == "boundary":
            closed = left == "PASS" and right == "REWRITE"
        elif kind == "soft_only_invariance":
            closed = left == right == "PASS"
        else:
            raise AssertionError("validated pair kind was not handled")
        results.append(
            {
                "pair_id": pair_id,
                "kind": kind,
                "typed_failure": typed_failure,
                "closed": closed,
            }
        )
    return {
        "total": len(results),
        "closed": sum(row["closed"] for row in results),
        "all_closed": len(results) == EXPECTED_PAIRS
        and all(row["closed"] for row in results),
        "pairs": results,
    }


def scalar_metrics(
    candidate_ids: Sequence[str],
    gold_verdicts: Sequence[str],
    scores: Sequence[float | None],
    pairs: Sequence[Any],
) -> dict[str, Any]:
    """Report the full A operating curve, rank AUC, and nine strict wins."""

    if not candidate_ids or not len(candidate_ids) == len(gold_verdicts) == len(scores):
        raise MetricsError("scalar metric rows must be equal and non-empty")
    normalized_scores = [None if value is None else _score(value) for value in scores]
    score_by_id = dict(zip(candidate_ids, normalized_scores, strict=True))
    curve: list[dict[str, Any]] = []
    thresholds: list[float | None] = [None]
    finite_scores = [score for score in normalized_scores if score is not None]
    thresholds.extend(sorted(set(finite_scores), reverse=True))
    if 0.0 not in thresholds:
        thresholds.append(0.0)
    for threshold in thresholds:
        predicted = [
            None
            if score is None
            else "REWRITE"
            if threshold is None or score < threshold
            else "PASS"
            for score in normalized_scores
        ]
        binary = binary_metrics(candidate_ids, gold_verdicts, predicted)
        pair = pair_verdict_metrics(
            pairs, dict(zip(candidate_ids, predicted, strict=True))
        )
        curve.append(
            {
                "threshold": threshold,
                "binary": binary,
                "pairs": pair,
            }
        )
    rank_auc = (
        None
        if len(finite_scores) != len(normalized_scores)
        else roc_auc(gold_verdicts, finite_scores)
    )
    boundary_results: list[dict[str, Any]] = []
    for pair in pairs:
        if _field(pair, "kind") != "boundary":
            continue
        left_id = _field(pair, "left_candidate_id")
        right_id = _field(pair, "right_candidate_id")
        left_score = score_by_id[left_id]
        right_score = score_by_id[right_id]
        won = (
            left_score is not None
            and right_score is not None
            and left_score > right_score
        )
        boundary_results.append(
            {
                "pair_id": _field(pair, "pair_id"),
                "left_score": left_score,
                "right_score": right_score,
                "strict_win": won,
            }
        )
    strict_wins = sum(result["strict_win"] for result in boundary_results)
    candidates = [point for point in curve if point["binary"]["meets_candidate_gate"]]
    selected = (
        max(candidates, key=_scalar_point_order)
        if candidates
        else max(curve, key=_scalar_point_order)
    )
    meets_basic = (
        bool(candidates) and rank_auc is not None and rank_auc >= MIN_SCALAR_AUC
    )
    meets_gate = (
        meets_basic
        and len(boundary_results) == EXPECTED_BOUNDARIES
        and strict_wins == EXPECTED_BOUNDARIES
    )
    return {
        "auc": rank_auc,
        "curve": curve,
        "selected_operating_point": selected,
        "boundary_strict": {
            "total": len(boundary_results),
            "wins": strict_wins,
            "all_won": len(boundary_results) == EXPECTED_BOUNDARIES
            and strict_wins == EXPECTED_BOUNDARIES,
            "pairs": boundary_results,
        },
        "meets_basic": meets_basic,
        "meets_gate": meets_gate,
    }


def roc_auc(gold_verdicts: Sequence[str], scores: Sequence[float]) -> float:
    if not gold_verdicts or len(gold_verdicts) != len(scores):
        raise MetricsError("AUC rows must be equal and non-empty")
    positives = [
        _score(score)
        for gold, score in zip(gold_verdicts, scores, strict=True)
        if _verdict(gold, "gold verdict") == "PASS"
    ]
    negatives = [
        _score(score)
        for gold, score in zip(gold_verdicts, scores, strict=True)
        if gold == "REWRITE"
    ]
    if not positives or not negatives:
        raise MetricsError("AUC requires both gold verdict classes")
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def direct_metrics(
    candidate_ids: Sequence[str],
    gold_verdicts: Sequence[str],
    predicted_verdicts: Sequence[str | None],
    pairs: Sequence[Any],
) -> dict[str, Any]:
    binary = binary_metrics(candidate_ids, gold_verdicts, predicted_verdicts)
    pair = pair_verdict_metrics(
        pairs,
        dict(zip(candidate_ids, predicted_verdicts, strict=True)),
    )
    return {
        "binary": binary,
        "pairs": pair,
        "meets_basic": binary["meets_candidate_gate"],
        "meets_gate": binary["meets_candidate_gate"] and pair["all_closed"],
    }


def structured_metrics(
    candidate_ids: Sequence[str],
    gold_labels: Sequence[Mapping[str, str]],
    predicted_labels: Sequence[Mapping[str, str] | None],
    pairs: Sequence[Any],
) -> dict[str, Any]:
    if not candidate_ids or not len(candidate_ids) == len(gold_labels) == len(
        predicted_labels
    ):
        raise MetricsError("structured metric rows must be equal and non-empty")
    gold = [_labels(labels) for labels in gold_labels]
    predicted = [
        None if labels is None else _labels(labels) for labels in predicted_labels
    ]
    binary = binary_metrics(
        candidate_ids,
        [derive_verdict(labels) for labels in gold],
        [None if labels is None else derive_verdict(labels) for labels in predicted],
    )
    per_dimension: dict[str, Any] = {}
    recalls: list[float] = []
    failed_dimensions: list[str] = []
    coverage_ok = True
    for dimension in HARD_DIMENSIONS:
        classes = DIMENSION_CLASSES[dimension]
        columns = (*classes, "PARSE_FAILURE")
        confusion = {actual: {guess: 0 for guess in columns} for actual in classes}
        for expected, actual in zip(gold, predicted, strict=True):
            guess = "PARSE_FAILURE" if actual is None else actual[dimension]
            confusion[expected[dimension]][guess] += 1
        class_recall: dict[str, float | None] = {}
        for label in classes:
            support = sum(confusion[label].values())
            recall = confusion[label][label] / support if support else None
            class_recall[label] = recall
            if recall is not None:
                recalls.append(recall)
        predicted_classes = sorted(
            {labels[dimension] for labels in predicted if labels is not None}
        )
        dimension_coverage = set(predicted_classes) == set(classes)
        coverage_ok = coverage_ok and dimension_coverage
        failure_recall = class_recall["FAIL"]
        if failure_recall is None or failure_recall < FAILURE_RECALL_FLOORS[dimension]:
            failed_dimensions.append(dimension)
        per_dimension[dimension] = {
            "confusion": confusion,
            "class_recall": class_recall,
            "failure_recall": failure_recall,
            "predicted_classes": predicted_classes,
            "required_classes_covered": dimension_coverage,
        }
    continuity_na_recall = per_dimension["conditional_continuity"]["class_recall"][
        "N/A"
    ]
    macro_recall = sum(recalls) / len(recalls)
    predicted_by_id = dict(zip(candidate_ids, predicted, strict=True))
    pair = _structured_pair_metrics(pairs, predicted_by_id)
    dimensions_good = (
        binary["meets_candidate_gate"]
        and macro_recall >= MIN_SUPPORTED_CLASS_MACRO_RECALL
    )
    meets_gate = (
        len(candidate_ids) == EXPECTED_CANDIDATES
        and binary["meets_candidate_gate"]
        and coverage_ok
        and not failed_dimensions
        and continuity_na_recall is not None
        and continuity_na_recall >= MIN_CONTINUITY_NA_RECALL
        and macro_recall >= MIN_SUPPORTED_CLASS_MACRO_RECALL
        and pair["all_closed"]
    )
    blocker_dimensions = set(failed_dimensions)
    if continuity_na_recall is None or continuity_na_recall < MIN_CONTINUITY_NA_RECALL:
        blocker_dimensions.add("conditional_continuity")
    target_blockers = {
        row["target_dimension"]
        for row in pair["pairs"]
        if row["kind"] == "boundary" and not row["target_closed"]
    }
    invariance_blockers = [
        row for row in pair["pairs"] if not row["non_target_invariant"]
    ]
    concentrated = (
        dimensions_good
        and not meets_gate
        and (
            (len(blocker_dimensions | target_blockers) <= 1 and not invariance_blockers)
            or (
                not blocker_dimensions
                and not target_blockers
                and 0 < len(invariance_blockers) <= 3
            )
        )
    )
    return {
        "binary": binary,
        "per_dimension": per_dimension,
        "supported_class_macro_recall": macro_recall,
        "continuity_na_recall": continuity_na_recall,
        "required_prediction_coverage": coverage_ok,
        "pairs": pair,
        "failed_dimension_floors": sorted(blocker_dimensions),
        "dimensions_generally_good": dimensions_good,
        "concentrated_blocker": concentrated,
        "meets_basic": dimensions_good,
        "meets_gate": meets_gate,
    }


def decide_route(
    scalar: Mapping[str, Any],
    direct: Mapping[str, Any],
    structured: Mapping[str, Any],
    *,
    formal_valid: bool,
) -> str:
    """Return the terminal from the exhaustive, pre-frozen route decision."""

    return decide_route_with_metadata(
        scalar, direct, structured, formal_valid=formal_valid
    )["terminal"]


def decide_route_with_metadata(
    scalar: Mapping[str, Any],
    direct: Mapping[str, Any],
    structured: Mapping[str, Any],
    *,
    formal_valid: bool,
) -> dict[str, Any]:
    """Apply priority without altering metrics and identify the approved residual path."""

    if not formal_valid:
        return {
            "terminal": "INCONCLUSIVE_TECHNICAL_OR_BUDGET",
            "residual_mixed_signal": False,
        }
    if structured["meets_gate"] and _noticeably_better(structured, direct):
        return {
            "terminal": "FIVE_DIMENSION_STRONGLY_SUPPORTED",
            "residual_mixed_signal": False,
        }
    if (
        direct["meets_gate"]
        and structured["meets_gate"]
        and _noticeably_better(direct, scalar)
        and _noticeably_better(structured, scalar)
        and _close(direct, structured)
    ):
        return {
            "terminal": "DISCRETE_SUPPORTED_FIVE_DIMENSION_INCREMENT_UNCONFIRMED",
            "residual_mixed_signal": False,
        }
    if structured["dimensions_generally_good"] and structured["concentrated_blocker"]:
        return {
            "terminal": "CONSTRAINT_OR_DATA_ISSUE",
            "residual_mixed_signal": False,
        }
    if (
        not scalar["meets_basic"]
        and not direct["meets_basic"]
        and not structured["meets_basic"]
    ):
        return {
            "terminal": "TASK_EXECUTABILITY_INSUFFICIENT",
            "residual_mixed_signal": False,
        }
    return {
        "terminal": "CONSTRAINT_OR_DATA_ISSUE",
        "residual_mixed_signal": True,
    }


def _structured_pair_metrics(
    pairs: Sequence[Any],
    predicted: Mapping[str, Mapping[str, str] | None],
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for pair in pairs:
        left = predicted[_field(pair, "left_candidate_id")]
        right = predicted[_field(pair, "right_candidate_id")]
        kind = _field(pair, "kind")
        target = _field(pair, "target_dimension")
        if kind not in {"boundary", "soft_only_invariance"}:
            raise MetricsError("structured pair kind is invalid")
        typed_failure = left is None or right is None
        if typed_failure:
            target_closed = False if kind == "boundary" else None
            invariant = False
            absolute = False
        elif kind == "boundary":
            assert left is not None and right is not None
            target_closed = left[target] == "PASS" and right[target] == "FAIL"
            invariant = all(
                left[dimension] == right[dimension]
                for dimension in HARD_DIMENSIONS
                if dimension != target
            )
            absolute = (
                derive_verdict(left) == "PASS" and derive_verdict(right) == "REWRITE"
            )
        elif kind == "soft_only_invariance":
            assert left is not None and right is not None
            target_closed = None
            invariant = left == right
            absolute = derive_verdict(left) == derive_verdict(right) == "PASS"
        else:
            raise AssertionError("validated pair kind was not handled")
        results.append(
            {
                "pair_id": _field(pair, "pair_id"),
                "kind": kind,
                "target_dimension": target,
                "typed_failure": typed_failure,
                "target_closed": target_closed,
                "non_target_invariant": invariant,
                "absolute_gate_closed": absolute,
                "closed": invariant and absolute and target_closed is not False,
            }
        )
    return {
        "total": len(results),
        "closed": sum(row["closed"] for row in results),
        "target_total": sum(row["kind"] == "boundary" for row in results),
        "target_closed": sum(row["target_closed"] is True for row in results),
        "non_target_invariant": sum(row["non_target_invariant"] for row in results),
        "all_closed": len(results) == EXPECTED_PAIRS
        and all(row["closed"] for row in results),
        "pairs": results,
    }


def _noticeably_better(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_correct, left_pairs = _quality_counts(left)
    right_correct, right_pairs = _quality_counts(right)
    return (
        left_correct >= right_correct
        and left_pairs >= right_pairs
        and (left_correct - right_correct >= 2 or left_pairs - right_pairs >= 2)
    )


def _close(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_correct, left_pairs = _quality_counts(left)
    right_correct, right_pairs = _quality_counts(right)
    return abs(left_correct - right_correct) <= 1 and abs(left_pairs - right_pairs) <= 1


def _quality_counts(metrics: Mapping[str, Any]) -> tuple[int, int]:
    if "selected_operating_point" in metrics:
        return (
            metrics["selected_operating_point"]["binary"]["correct"],
            metrics["selected_operating_point"]["pairs"]["closed"],
        )
    return metrics["binary"]["correct"], metrics["pairs"]["closed"]


def _scalar_point_order(point: Mapping[str, Any]) -> tuple[Any, ...]:
    binary = point["binary"]
    threshold = point["threshold"]
    return (
        binary["meets_candidate_gate"],
        binary["balanced_accuracy"],
        -binary["false_pass"],
        binary["correct"],
        -binary["false_rewrite"],
        point["pairs"]["closed"],
        -1.0 if threshold is None else threshold,
    )


def _labels(value: Mapping[str, str]) -> dict[str, str]:
    if set(value) != set(HARD_DIMENSIONS):
        raise MetricsError("structured label keys differ")
    result: dict[str, str] = {}
    for dimension in HARD_DIMENSIONS:
        label = value[dimension]
        if label not in DIMENSION_CLASSES[dimension]:
            raise MetricsError(f"invalid structured label: {dimension}")
        result[dimension] = label
    return result


def _score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MetricsError("scalar score must be numeric")
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise MetricsError("scalar score must be finite and in [0, 1]")
    return score


def _verdict(value: Any, where: str) -> str:
    if value not in {"PASS", "REWRITE"}:
        raise MetricsError(f"{where} must be PASS or REWRITE")
    return value


def _effective_verdict(value: Any) -> str:
    return "REWRITE" if value is None else _verdict(value, "pair verdict")


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        if name not in value:
            raise MetricsError(f"pair is missing {name}")
        return value[name]
    try:
        return getattr(value, name)
    except AttributeError as exc:
        raise MetricsError(f"pair is missing {name}") from exc


def _required_lookup(value: Mapping[str, Any], key: str) -> Any:
    if key not in value:
        raise MetricsError(f"pair references missing candidate: {key}")
    return value[key]
