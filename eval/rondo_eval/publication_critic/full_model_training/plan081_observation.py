"""Same-cohort validation observations for the Plan 081 continuous route."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
import statistics
from typing import Any

from ..scoring import project_logit
from ..selection.metrics import (
    build_labeled_rows,
    candidate_metrics,
    operating_points,
)
from .contract import FullModelTrainingError
from .contract import canonical_json_bytes, sha256_bytes
from .data import PortableTrainingDataset
from .plan066_data import ValidationDataset
from .plan081_contract import ComparisonPolicy, TrainableScope


OBSERVATION_SCHEMA = "rondo-publication-critic-plan081-observation-v1"


def validation_identity_sha256(dataset: ValidationDataset) -> str:
    """Bind every metric-affecting validation row without retaining packet bodies."""

    if (
        not dataset.supervision
        or set(dataset.packets) != set(dataset.supervision)
        or any(
            row.get("proposed_split") != "validation"
            for row in dataset.supervision.values()
        )
        or any(
            str(pair.get("preferred_candidate_id")) not in dataset.supervision
            or str(pair.get("dispreferred_candidate_id")) not in dataset.supervision
            for pair in dataset.pairs.values()
        )
    ):
        raise FullModelTrainingError("plan081_validation_input_invalid")
    identity = {
        "input_identity": _plain_json(dataset.input_identity),
        "rubric_sha256": sha256_bytes(dataset.rubric.encode("utf-8")),
        "packets": [
            _plain_json(dataset.packets[candidate_id])
            for candidate_id in sorted(dataset.packets)
        ],
        "supervision": [
            _plain_json(dataset.supervision[candidate_id])
            for candidate_id in sorted(dataset.supervision)
        ],
        "pairs": [
            _plain_json(dataset.pairs[pair_id]) for pair_id in sorted(dataset.pairs)
        ],
    }
    return sha256_bytes(canonical_json_bytes(identity))


def training_identity_sha256(dataset: PortableTrainingDataset) -> str:
    """Bind the typed train-only input consumed by every update callback."""

    candidate_ids = set(dataset.supervision)
    pair_ids = set(dataset.pairs)
    if (
        dataset.dataset_revision != "v8"
        or not dataset.supervision
        or set(dataset.packets) != candidate_ids
        or any(
            row.get("candidate_id") != candidate_id
            for candidate_id, row in dataset.packets.items()
        )
        or any(
            row.get("candidate_id") != candidate_id
            for candidate_id, row in dataset.supervision.items()
        )
        or any(
            pair.get("pair_id") != pair_id
            for pair_id, pair in dataset.pairs.items()
        )
        or any(
            row.get("proposed_split") != "train"
            for row in dataset.supervision.values()
        )
        or any(
            str(pair.get("preferred_candidate_id")) not in dataset.supervision
            or str(pair.get("dispreferred_candidate_id")) not in dataset.supervision
            for pair in dataset.pairs.values()
        )
    ):
        raise FullModelTrainingError("plan081_training_input_not_train_only_v8")
    _validate_train_only_membership(dataset.membership, candidate_ids, pair_ids)
    identity = {
        "dataset_revision": dataset.dataset_revision,
        "input_identity": _plain_json(dataset.input_identity),
        "rubric_sha256": sha256_bytes(dataset.rubric.encode("utf-8")),
        "packets": [
            _plain_json(dataset.packets[candidate_id])
            for candidate_id in sorted(dataset.packets)
        ],
        "supervision": [
            _plain_json(dataset.supervision[candidate_id])
            for candidate_id in sorted(dataset.supervision)
        ],
        "pairs": [
            _plain_json(dataset.pairs[pair_id]) for pair_id in sorted(dataset.pairs)
        ],
        "membership": _plain_json(dataset.membership),
    }
    return sha256_bytes(canonical_json_bytes(identity))


def _validate_train_only_membership(
    value: Any, candidate_ids: set[str], pair_ids: set[str]
) -> None:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != 1
        or value.get("dataset_revision") != "v8"
        or not isinstance(value.get("stages"), Mapping)
        or not value["stages"]
    ):
        raise FullModelTrainingError("plan081_training_membership_invalid")
    for stage in value["stages"].values():
        if not isinstance(stage, Mapping) or set(stage) != {"candidate_ids", "pair_ids"}:
            raise FullModelTrainingError("plan081_training_membership_invalid")
        stage_candidates = stage["candidate_ids"]
        stage_pairs = stage["pair_ids"]
        if (
            not isinstance(stage_candidates, list)
            or not isinstance(stage_pairs, list)
            or len(set(stage_candidates)) != len(stage_candidates)
            or len(set(stage_pairs)) != len(stage_pairs)
            or any(item not in candidate_ids for item in stage_candidates)
            or any(item not in pair_ids for item in stage_pairs)
        ):
            raise FullModelTrainingError("plan081_training_membership_invalid")


def build_validation_observation(
    dataset: ValidationDataset,
    raw_logits: Mapping[str, Any],
    *,
    global_step: int,
    scope: TrainableScope,
    policy: ComparisonPolicy,
    report_threshold: float = 0.5,
) -> dict[str, Any]:
    """Build a complete, small validation record without model access.

    The caller owns inference and must provide a no-gradient evaluation receipt.
    This pure layer reuses the established projection and Plan 073 metric
    functions, then adds the raw signed pair margins needed for training
    diagnostics.
    """

    if (
        not isinstance(global_step, int)
        or isinstance(global_step, bool)
        or global_step < 0
        or not isinstance(report_threshold, (int, float))
        or isinstance(report_threshold, bool)
        or not math.isfinite(float(report_threshold))
        or not 0.0 <= float(report_threshold) <= 1.0
    ):
        raise FullModelTrainingError("plan081_observation_arguments_invalid")
    if any(
        row.get("proposed_split") != "validation"
        for row in dataset.supervision.values()
    ):
        raise FullModelTrainingError("plan081_observation_requires_validation_split")
    if set(raw_logits) != set(dataset.supervision):
        raise FullModelTrainingError("plan081_observation_score_cohort_mismatch")

    scores: dict[str, dict[str, float]] = {}
    for candidate_id in sorted(raw_logits):
        value = raw_logits[candidate_id]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            raise FullModelTrainingError("plan081_observation_raw_logit_invalid")
        raw = float(value)
        scores[candidate_id] = {"raw_logit": raw, "score": project_logit(raw)}

    release = {
        "supervision": [
            dict(dataset.supervision[candidate_id])
            for candidate_id in sorted(dataset.supervision)
        ],
        "pairs": [dict(dataset.pairs[pair_id]) for pair_id in sorted(dataset.pairs)],
    }
    try:
        rows = build_labeled_rows(release, scores)
        metrics = candidate_metrics(release, rows, float(report_threshold))
        curve = []
        for threshold in operating_points(rows):
            point = candidate_metrics(release, rows, threshold)["overall"]
            curve.append(
                {
                    "threshold": threshold,
                    "confusion": point["confusion"],
                    "accuracy": point["accuracy"],
                    "balanced_accuracy": point["balanced_accuracy"],
                    "false_pass_rate": point["false_pass_rate"],
                    "false_rewrite_rate": point["false_rewrite_rate"],
                }
            )
    except Exception as exc:  # Plan 073 exposes a distinct public error type.
        raise FullModelTrainingError("plan081_observation_metrics_failed") from exc

    pair_margins: list[dict[str, Any]] = []
    for pair_id in sorted(dataset.pairs):
        pair = dataset.pairs[pair_id]
        preferred_id = str(pair["preferred_candidate_id"])
        dispreferred_id = str(pair["dispreferred_candidate_id"])
        raw_margin = scores[preferred_id]["raw_logit"] - scores[dispreferred_id][
            "raw_logit"
        ]
        projected_margin = scores[preferred_id]["score"] - scores[dispreferred_id][
            "score"
        ]
        pair_margins.append(
            {
                "pair_id": pair_id,
                "kind": str(pair["kind"]),
                "target_dimension": pair.get("target_dimension"),
                "preferred_candidate_id": preferred_id,
                "dispreferred_candidate_id": dispreferred_id,
                "preferred_raw_logit": scores[preferred_id]["raw_logit"],
                "dispreferred_raw_logit": scores[dispreferred_id]["raw_logit"],
                "signed_raw_margin": raw_margin,
                "signed_projected_margin": projected_margin,
                "direction": (
                    "preferred" if raw_margin > 0 else "tie" if raw_margin == 0 else "dispreferred"
                ),
            }
        )

    comparison_value = _comparison_value(metrics, pair_margins, policy.metric)
    return {
        "schema": OBSERVATION_SCHEMA,
        "global_step": global_step,
        "scope": scope.as_dict(),
        "validation": {
            "identity_sha256": validation_identity_sha256(dataset),
            "dataset_revision": "v8",
            "split": "validation",
            "candidate_count": len(dataset.supervision),
            "pair_count": len(dataset.pairs),
            "gradient_access": False,
            "feeds_parameter_updates": False,
            "control_use": "quality_observation_scope_and_stop_decisions_only",
            "qualification_claim": False,
            "m3_c2_claim": False,
            "unseen_claim": False,
        },
        "report_threshold": float(report_threshold),
        "metrics": metrics,
        "operating_curve": curve,
        "pair_margins": pair_margins,
        "comparison_policy": policy.as_dict(),
        "comparison_value": comparison_value,
    }


def _comparison_value(
    metrics: Mapping[str, Any], pair_margins: list[dict[str, Any]], metric: str
) -> float:
    if metric == "roc_auc":
        value = metrics.get("roc_auc")
    elif metric == "balanced_accuracy":
        value = metrics["overall"].get("balanced_accuracy")
    elif metric == "boundary_pair_strict_win_rate":
        value = metrics["boundary_pairs"].get("strict_win_rate")
    elif metric == "within_pass_pair_strict_win_rate":
        value = metrics["within_pass_pairs"].get("strict_win_rate")
    elif metric in {"boundary_pair_mean_margin", "within_pass_pair_mean_margin"}:
        kind = "boundary" if metric.startswith("boundary") else "within_pass"
        margins = [
            float(row["signed_raw_margin"])
            for row in pair_margins
            if row["kind"] == kind
        ]
        value = statistics.fmean(margins) if margins else None
    else:  # ComparisonPolicy has already rejected unknown names.
        value = None
    if not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise FullModelTrainingError("plan081_comparison_metric_unavailable")
    return float(value)


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise FullModelTrainingError("plan081_validation_identity_invalid") from exc
