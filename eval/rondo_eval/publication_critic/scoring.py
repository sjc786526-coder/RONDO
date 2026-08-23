"""The single Plan 054 scalar projection, temporary threshold and metrics."""

import math
import statistics
from collections import Counter, defaultdict
from typing import Any, Iterable, Mapping


class ScoringError(ValueError):
    """Raised when a raw model output cannot satisfy the frozen score contract."""


def project_logit(raw_logit: float) -> float:
    """Map the unbounded RM logit to the Plan 055 finite domain [0, 1]."""

    if not isinstance(raw_logit, (int, float)) or isinstance(raw_logit, bool):
        raise ScoringError("raw logit is not numeric")
    value = float(raw_logit)
    if not math.isfinite(value):
        raise ScoringError("raw logit is not finite")
    if value >= 0:
        projected = 1.0 / (1.0 + math.exp(-value))
    else:
        exponential = math.exp(value)
        projected = exponential / (1.0 + exponential)
    if not math.isfinite(projected) or not 0.0 <= projected <= 1.0:
        raise ScoringError("projected score is outside the frozen domain")
    return projected


def _label(value: object) -> str:
    if value not in {"pass", "rewrite"}:
        raise ScoringError("expected label is invalid")
    return str(value)


def _confusion(rows: Iterable[Mapping[str, Any]], threshold: float) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        expected = _label(row["expected_label"])
        score = float(row["score"])
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ScoringError("projected score is invalid")
        predicted = "pass" if score >= threshold else "rewrite"
        key = {
            ("pass", "pass"): "true_pass",
            ("pass", "rewrite"): "false_rewrite",
            ("rewrite", "pass"): "false_pass",
            ("rewrite", "rewrite"): "true_rewrite",
        }[(expected, predicted)]
        counts[key] += 1
    return counts


def derive_temporary_threshold(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Apply the frozen calibration-only balanced-accuracy rule.

    Ties first minimize false PASS, then choose the greater threshold.  No
    measurement label is accepted by this function's caller-facing contract.
    """

    calibration = list(rows)
    if not calibration or any(row.get("data_role") != "calibration" for row in calibration):
        raise ScoringError("temporary threshold requires calibration rows only")
    labels = Counter(_label(row["expected_label"]) for row in calibration)
    if set(labels) != {"pass", "rewrite"} or min(labels["pass"], labels["rewrite"]) == 0:
        raise ScoringError("calibration must contain both expected labels")
    unique = sorted({float(row["score"]) for row in calibration})
    if any(not math.isfinite(score) or not 0.0 <= score <= 1.0 for score in unique):
        raise ScoringError("calibration score is invalid")
    candidates = {0.0, 1.0}
    candidates.update((left + right) / 2.0 for left, right in zip(unique, unique[1:]))
    candidates.update(unique)
    ranked: list[tuple[float, int, float, Counter[str]]] = []
    for threshold in sorted(candidates):
        counts = _confusion(calibration, threshold)
        pass_recall = counts["true_pass"] / labels["pass"]
        rewrite_recall = counts["true_rewrite"] / labels["rewrite"]
        balanced_accuracy = (pass_recall + rewrite_recall) / 2.0
        ranked.append((balanced_accuracy, -counts["false_pass"], threshold, counts))
    balanced_accuracy, _negative_false_pass, threshold, counts = max(ranked)
    return {
        "rule": "maximize_balanced_accuracy_then_minimize_false_pass_then_maximize_threshold_v1",
        "threshold": threshold,
        "calibration_count": len(calibration),
        "balanced_accuracy": balanced_accuracy,
        "confusion": dict(counts),
    }


def _auc(rows: list[Mapping[str, Any]]) -> float | None:
    positive = [float(row["score"]) for row in rows if _label(row["expected_label"]) == "pass"]
    negative = [float(row["score"]) for row in rows if _label(row["expected_label"]) == "rewrite"]
    if not positive or not negative:
        return None
    wins = sum(
        1.0 if left > right else 0.5 if left == right else 0.0
        for left in positive
        for right in negative
    )
    return wins / (len(positive) * len(negative))


def _metrics(rows: list[Mapping[str, Any]], threshold: float) -> dict[str, Any]:
    counts = _confusion(rows, threshold)
    for key in ("true_pass", "false_rewrite", "false_pass", "true_rewrite"):
        counts.setdefault(key, 0)
    total = len(rows)
    pass_total = counts["true_pass"] + counts["false_rewrite"]
    rewrite_total = counts["true_rewrite"] + counts["false_pass"]
    accuracy = (counts["true_pass"] + counts["true_rewrite"]) / total if total else None
    balanced = None
    if pass_total and rewrite_total:
        balanced = (
            counts["true_pass"] / pass_total + counts["true_rewrite"] / rewrite_total
        ) / 2.0
    return {
        "count": total,
        "confusion": dict(counts),
        "accuracy": accuracy,
        "balanced_accuracy": balanced,
        "roc_auc": _auc(rows),
    }


def summarize_measurement(rows: Iterable[Mapping[str, Any]], threshold: float) -> dict[str, Any]:
    measurement = list(rows)
    if any(row.get("data_role") != "measurement" for row in measurement):
        raise ScoringError("measurement summary rejects non-measurement rows")
    by_slice: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_class: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_pair: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in measurement:
        for slice_name in row.get("slices", []):
            by_slice[str(slice_name)].append(row)
        by_class[str(row["publication_class"])].append(row)
        by_pair[str(row["pair_id"])].append(row)
    scores = sorted(float(row["score"]) for row in measurement)
    raw_logits = sorted(float(row["raw_logit"]) for row in measurement)
    latencies = sorted(float(row["latency_ms"]) for row in measurement)
    for value in (*scores, *raw_logits, *latencies):
        if not math.isfinite(value):
            raise ScoringError("measurement contains a non-finite result")
    pair_wins = 0
    pair_ties = 0
    pair_rows: list[dict[str, Any]] = []
    for pair_id, pair in sorted(by_pair.items()):
        if len(pair) != 2 or {row["expected_label"] for row in pair} != {"pass", "rewrite"}:
            raise ScoringError("measurement boundary pair is invalid")
        pass_score = next(float(row["score"]) for row in pair if row["expected_label"] == "pass")
        rewrite_score = next(
            float(row["score"]) for row in pair if row["expected_label"] == "rewrite"
        )
        outcome = "win" if pass_score > rewrite_score else "tie" if pass_score == rewrite_score else "loss"
        pair_wins += int(outcome == "win")
        pair_ties += int(outcome == "tie")
        pair_rows.append(
            {
                "pair_id": pair_id,
                "pass_score": pass_score,
                "rewrite_score": rewrite_score,
                "outcome": outcome,
            }
        )
    overall = _metrics(measurement, threshold)
    false_pass_ids = sorted(
        row["sample_id"]
        for row in measurement
        if row["expected_label"] == "rewrite" and float(row["score"]) >= threshold
    )
    false_rewrite_ids = sorted(
        row["sample_id"]
        for row in measurement
        if row["expected_label"] == "pass" and float(row["score"]) < threshold
    )
    return {
        "threshold": threshold,
        "valid_score_count": len(measurement),
        "typed_failure_count": 0,
        "overall": overall,
        "by_publication_class": {
            name: _metrics(class_rows, threshold)
            for name, class_rows in sorted(by_class.items())
        },
        "by_slice": {name: _metrics(rows, threshold) for name, rows in sorted(by_slice.items())},
        "boundary_pairs": {
            "count": len(pair_rows),
            "strict_wins": pair_wins,
            "ties": pair_ties,
            "strict_win_rate": pair_wins / len(pair_rows) if pair_rows else None,
            "auc_with_ties": (pair_wins + 0.5 * pair_ties) / len(pair_rows)
            if pair_rows
            else None,
            "pairs": pair_rows,
        },
        "errors": {
            "false_pass_sample_ids": false_pass_ids,
            "false_rewrite_sample_ids": false_rewrite_ids,
        },
        "raw_logit_distribution": _distribution(raw_logits),
        "score_distribution": {
            "min": scores[0] if scores else None,
            "max": scores[-1] if scores else None,
            "median": statistics.median(scores) if scores else None,
        },
        "latency_ms": _distribution(latencies),
    }


def _distribution(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p50": None, "p95": None, "max": None}
    rank95 = max(0, math.ceil(0.95 * len(values)) - 1)
    return {
        "min": values[0],
        "p50": statistics.median(values),
        "p95": values[rank95],
        "max": values[-1],
    }
