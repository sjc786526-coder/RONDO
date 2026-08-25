"""Deterministic Plan 073 quality metrics and the frozen threshold search.

Nothing here knows about model identity or about the Judge.  It turns one
candidate's projected scores over one released split into the error-type detail
the selection protocol ranks on, and it applies the frozen threshold rule.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
import statistics
from typing import Any

from .contract import SELECTION_METHOD, SelectionError


PASS = "PASS"
REWRITE = "REWRITE"

# Categorical facets reported alongside the free-form ``slices`` list.  Each is
# reported with its denominator; none of them is a hard gate.
_FACETS = (
    "publication_class",
    "completion_state",
    "actor_role",
    "hard_focus",
    "length_bucket",
    "style",
)


@dataclass(frozen=True)
class LabeledRow:
    candidate_id: str
    score: float
    raw_logit: float
    label: str
    slices: tuple[str, ...]
    facets: Mapping[str, str]


def build_labeled_rows(
    release: Mapping[str, Any],
    scores: Mapping[str, Mapping[str, float]],
) -> tuple[LabeledRow, ...]:
    """Join a released split with one candidate's projected scores."""

    supervision = {str(row["candidate_id"]): row for row in release["supervision"]}
    if set(scores) != set(supervision):
        raise SelectionError("Plan 073 score cohort does not match the release")
    rows: list[LabeledRow] = []
    for candidate_id in sorted(supervision):
        row = supervision[candidate_id]
        score = float(scores[candidate_id]["score"])
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise SelectionError("Plan 073 projected score is outside its domain")
        raw_logit = float(scores[candidate_id]["raw_logit"])
        if not math.isfinite(raw_logit):
            raise SelectionError("Plan 073 raw logit is not finite")
        rows.append(
            LabeledRow(
                candidate_id=candidate_id,
                score=score,
                raw_logit=raw_logit,
                label=str(row["binary_label"]),
                slices=tuple(str(item) for item in row["slices"]),
                facets={
                    name: "none" if row[name] is None else str(row[name])
                    for name in _FACETS
                }
                | {"unicode": "true" if row["unicode"] else "false"},
            )
        )
    return tuple(rows)


def _confusion(rows: Sequence[LabeledRow], threshold: float) -> dict[str, int]:
    counts = {"true_pass": 0, "false_rewrite": 0, "false_pass": 0, "true_rewrite": 0}
    for row in rows:
        predicted = PASS if row.score >= threshold else REWRITE
        if row.label == PASS:
            counts["true_pass" if predicted == PASS else "false_rewrite"] += 1
        else:
            counts["false_pass" if predicted == PASS else "true_rewrite"] += 1
    return counts


def _rates(counts: Mapping[str, int]) -> dict[str, Any]:
    pass_total = counts["true_pass"] + counts["false_rewrite"]
    rewrite_total = counts["true_rewrite"] + counts["false_pass"]
    total = pass_total + rewrite_total
    pass_recall = counts["true_pass"] / pass_total if pass_total else None
    rewrite_recall = counts["true_rewrite"] / rewrite_total if rewrite_total else None
    balanced = (
        (pass_recall + rewrite_recall) / 2.0
        if pass_recall is not None and rewrite_recall is not None
        else None
    )
    return {
        "count": total,
        "pass_count": pass_total,
        "rewrite_count": rewrite_total,
        "confusion": dict(counts),
        "accuracy": (
            (counts["true_pass"] + counts["true_rewrite"]) / total if total else None
        ),
        "balanced_accuracy": balanced,
        "false_pass_rate": (
            counts["false_pass"] / rewrite_total if rewrite_total else None
        ),
        "false_rewrite_rate": (
            counts["false_rewrite"] / pass_total if pass_total else None
        ),
    }


def roc_auc(rows: Sequence[LabeledRow]) -> float | None:
    positive = [row.score for row in rows if row.label == PASS]
    negative = [row.score for row in rows if row.label == REWRITE]
    if not positive or not negative:
        return None
    wins = sum(
        1.0 if left > right else 0.5 if left == right else 0.0
        for left in positive
        for right in negative
    )
    return wins / (len(positive) * len(negative))


def operating_points(rows: Sequence[LabeledRow]) -> tuple[float, ...]:
    """The frozen threshold search space for one candidate."""

    unique = sorted({row.score for row in rows})
    if not unique:
        raise SelectionError("Plan 073 threshold search needs at least one score")
    points = {0.0, 1.0}
    points.update(unique)
    points.update((left + right) / 2.0 for left, right in zip(unique, unique[1:]))
    return tuple(sorted(points))


def _pair_outcomes(
    release: Mapping[str, Any],
    rows: Sequence[LabeledRow],
    kind: str,
) -> dict[str, Any]:
    by_id = {row.candidate_id: row for row in rows}
    outcomes: list[dict[str, Any]] = []
    for pair in release["pairs"]:
        if pair["kind"] != kind:
            continue
        preferred = by_id[str(pair["preferred_candidate_id"])]
        dispreferred = by_id[str(pair["dispreferred_candidate_id"])]
        outcome = (
            "win"
            if preferred.score > dispreferred.score
            else "tie"
            if preferred.score == dispreferred.score
            else "loss"
        )
        outcomes.append(
            {
                "pair_id": str(pair["pair_id"]),
                "target_dimension": pair["target_dimension"],
                "preferred_score": preferred.score,
                "dispreferred_score": dispreferred.score,
                "outcome": outcome,
            }
        )
    wins = sum(item["outcome"] == "win" for item in outcomes)
    ties = sum(item["outcome"] == "tie" for item in outcomes)
    return {
        "count": len(outcomes),
        "strict_wins": wins,
        "ties": ties,
        "strict_win_rate": wins / len(outcomes) if outcomes else None,
        "rate_with_ties": (wins + 0.5 * ties) / len(outcomes) if outcomes else None,
        "pairs": outcomes,
    }


def _distribution(values: Sequence[float]) -> dict[str, float | None]:
    ordered = sorted(values)
    if not ordered:
        return {"min": None, "p50": None, "p95": None, "max": None}
    rank95 = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "min": ordered[0],
        "p50": statistics.median(ordered),
        "p95": ordered[rank95],
        "max": ordered[-1],
    }


def threshold_free_metrics(
    release: Mapping[str, Any],
    rows: Sequence[LabeledRow],
) -> dict[str, Any]:
    """Everything that does not depend on where the threshold lands."""

    return {
        "roc_auc": roc_auc(rows),
        "boundary_pairs": _pair_outcomes(release, rows, "boundary"),
        "within_pass_pairs": _pair_outcomes(release, rows, "within_pass"),
        "score_distribution": _distribution([row.score for row in rows]),
        "raw_logit_distribution": _distribution([row.raw_logit for row in rows]),
    }


def select_threshold(
    rows: Sequence[LabeledRow],
    floors: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the frozen threshold rule and report the search honestly.

    ``feasible`` distinguishes "this candidate has an operating point that meets
    every threshold-dependent floor" from "this is only the best point it has".
    An infeasible candidate is still reported, but it cannot be admitted.
    """

    max_false_pass = float(floors["max_false_pass_rate"])
    max_false_rewrite = float(floors["max_false_rewrite_rate"])
    min_balanced = float(floors["min_balanced_accuracy"])
    evaluated: list[dict[str, Any]] = []
    for threshold in operating_points(rows):
        summary = _rates(_confusion(rows, threshold))
        if (
            summary["balanced_accuracy"] is None
            or summary["false_pass_rate"] is None
            or summary["false_rewrite_rate"] is None
        ):
            raise SelectionError("Plan 073 threshold search needs both labels present")
        feasible = (
            summary["false_pass_rate"] <= max_false_pass
            and summary["false_rewrite_rate"] <= max_false_rewrite
            and summary["balanced_accuracy"] >= min_balanced
        )
        evaluated.append({"threshold": threshold, "feasible": feasible, **summary})

    feasible_points = [point for point in evaluated if point["feasible"]]
    pool = feasible_points or evaluated
    best = max(
        pool,
        key=lambda point: (
            point["balanced_accuracy"],
            -point["confusion"]["false_pass"],
            point["threshold"],
        ),
    )
    return {
        "search": SELECTION_METHOD["threshold_search"],
        "rule": SELECTION_METHOD["threshold_rule"],
        "search_point_count": len(evaluated),
        "feasible_point_count": len(feasible_points),
        "feasible": bool(feasible_points),
        "threshold": float(best["threshold"]),
        "operating_point": {
            name: value for name, value in best.items() if name != "threshold"
        },
        "curve": [
            {
                "threshold": point["threshold"],
                "feasible": point["feasible"],
                "false_pass": point["confusion"]["false_pass"],
                "false_rewrite": point["confusion"]["false_rewrite"],
                "balanced_accuracy": point["balanced_accuracy"],
            }
            for point in evaluated
        ],
    }


def candidate_metrics(
    release: Mapping[str, Any],
    rows: Sequence[LabeledRow],
    threshold: float,
) -> dict[str, Any]:
    """The full per-candidate report at one threshold."""

    overall = _rates(_confusion(rows, threshold))
    by_slice: dict[str, list[LabeledRow]] = defaultdict(list)
    for row in rows:
        for name in row.slices:
            by_slice[name].append(row)
    facet_groups: dict[str, dict[str, list[LabeledRow]]] = {
        facet: defaultdict(list) for facet in (*_FACETS, "unicode")
    }
    for row in rows:
        for facet, value in row.facets.items():
            facet_groups[facet][value].append(row)

    false_pass_ids = sorted(
        row.candidate_id
        for row in rows
        if row.label == REWRITE and row.score >= threshold
    )
    false_rewrite_ids = sorted(
        row.candidate_id for row in rows if row.label == PASS and row.score < threshold
    )
    return {
        "threshold": threshold,
        "overall": overall,
        **threshold_free_metrics(release, rows),
        "by_slice": {
            name: _rates(_confusion(group, threshold))
            for name, group in sorted(by_slice.items())
        },
        "by_facet": {
            facet: {
                value: _rates(_confusion(group, threshold))
                for value, group in sorted(groups.items())
            }
            for facet, groups in sorted(facet_groups.items())
        },
        "errors": {
            "false_pass_candidate_ids": false_pass_ids,
            "false_rewrite_candidate_ids": false_rewrite_ids,
        },
        "rows": [
            {
                "candidate_id": row.candidate_id,
                "label": row.label,
                "score": row.score,
                "raw_logit": row.raw_logit,
                "predicted": PASS if row.score >= threshold else REWRITE,
                "margin_to_threshold": row.score - threshold,
            }
            for row in rows
        ],
    }
