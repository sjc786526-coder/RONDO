"""Exact comparable projections of the tracked 1.7B and 4B validation results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contract import CloudQualityError, VALIDATION_RELEASE_SHA256


EXACT_1_7B = {
    "repository": "Skywork/Skywork-Reward-V2-Qwen3-1.7B",
    "revision": "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc",
    "weight_sha256": "117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9",
    "lineage": "skywork-reward-v2-qwen3-1.7b-exact-base",
}
EXACT_4B = {
    "repository": "Skywork/Skywork-Reward-V2-Qwen3-4B",
    "revision": "fd958fef475f323f4e6b195930e3dd918485c668",
}


def _pair_projection(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CloudQualityError(code)
    try:
        return {
            "count": int(value["count"]),
            "strict_wins": int(value["strict_wins"]),
            "strict_win_rate": float(value["strict_win_rate"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise CloudQualityError(code) from exc


def project_1_7b(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != "rondo-publication-critic-plan073-selection-report-v1"
        or value.get("validation_release_sha256") != VALIDATION_RELEASE_SHA256
    ):
        raise CloudQualityError("history_1_7b_identity_invalid")
    candidates = value.get("candidates")
    base = candidates.get("base") if isinstance(candidates, Mapping) else None
    if (
        not isinstance(base, Mapping)
        or base.get("candidate") != "base"
        or base.get("lineage") != EXACT_1_7B["lineage"]
        or base.get("deployment_artifact_sha256") != EXACT_1_7B["weight_sha256"]
        or not isinstance(base.get("rows"), list)
        or len(base["rows"]) != 55
    ):
        raise CloudQualityError("history_1_7b_base_invalid")
    overall = base.get("overall")
    runtime = base.get("runtime")
    if not isinstance(overall, Mapping) or not isinstance(runtime, Mapping):
        raise CloudQualityError("history_1_7b_metrics_invalid")
    if overall.get("count") != 55 or runtime.get("typed_failure_count") != 0:
        raise CloudQualityError("history_1_7b_cohort_invalid")
    try:
        metrics = {
            "false_pass": int(overall["confusion"]["false_pass"]),
            "false_pass_rate": float(overall["false_pass_rate"]),
            "false_rewrite": int(overall["confusion"]["false_rewrite"]),
            "false_rewrite_rate": float(overall["false_rewrite_rate"]),
            "balanced_accuracy": float(overall["balanced_accuracy"]),
            "roc_auc": float(base["roc_auc"]),
            "boundary_pairs": _pair_projection(
                base["boundary_pairs"], "history_1_7b_boundary_invalid"
            ),
            "within_pass_pairs": _pair_projection(
                base["within_pass_pairs"], "history_1_7b_within_pass_invalid"
            ),
            "typed_failure_count": 0,
            "feasible": bool(base["threshold"]["feasible"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise CloudQualityError("history_1_7b_metrics_invalid") from exc
    return {
        "source": "eval/results/publication-critic/m3-c2-joint-selection-v1.json",
        "identity": dict(EXACT_1_7B),
        "release_sha256": VALIDATION_RELEASE_SHA256,
        "terminal": value.get("validation_terminal"),
        "metrics": metrics,
    }


def project_4b(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema")
        != "rondo-publication-critic-plan079-base-quality-summary-v1"
        or value.get("valid_full_quality_run") is not True
    ):
        raise CloudQualityError("history_4b_identity_invalid")
    identity = value.get("identity")
    cohort = value.get("cohort")
    result = value.get("formal_result")
    if (
        not isinstance(identity, Mapping)
        or identity.get("model_repository") != EXACT_4B["repository"]
        or identity.get("model_revision") != EXACT_4B["revision"]
        or identity.get("validation_release_sha256") != VALIDATION_RELEASE_SHA256
        or not isinstance(cohort, Mapping)
        or cohort.get("candidate_count") != 55
        or cohort.get("typed_failure_count") != 0
        or not isinstance(result, Mapping)
    ):
        raise CloudQualityError("history_4b_result_invalid")
    point = result.get("operating_point")
    search = result.get("threshold_search")
    if not isinstance(point, Mapping) or not isinstance(search, Mapping):
        raise CloudQualityError("history_4b_metrics_invalid")
    try:
        metrics = {
            "false_pass": int(point["false_pass"]),
            "false_pass_rate": float(point["false_pass_rate"]),
            "false_rewrite": int(point["false_rewrite"]),
            "false_rewrite_rate": float(point["false_rewrite_rate"]),
            "balanced_accuracy": float(point["balanced_accuracy"]),
            "roc_auc": float(result["roc_auc"]),
            "boundary_pairs": _pair_projection(
                result["boundary_pairs"], "history_4b_boundary_invalid"
            ),
            "within_pass_pairs": _pair_projection(
                result["within_pass_pairs"], "history_4b_within_pass_invalid"
            ),
            "typed_failure_count": 0,
            "feasible": bool(search["feasible"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise CloudQualityError("history_4b_metrics_invalid") from exc
    return {
        "source": (
            "eval/results/publication-critic/"
            "skywork-reward-v2-qwen3-4b-base-quality-v1.json"
        ),
        "identity": dict(EXACT_4B),
        "release_sha256": VALIDATION_RELEASE_SHA256,
        "terminal": value.get("terminal"),
        "metrics": metrics,
    }


def project_historical_results(one_7b: Any, four_b: Any) -> dict[str, Any]:
    return {
        "exact_1_7b": project_1_7b(one_7b),
        "exact_4b": project_4b(four_b),
        "comparison_scope": {
            "comparable": [
                "false_pass",
                "false_rewrite",
                "balanced_accuracy",
                "roc_auc",
                "boundary_pairs",
                "within_pass_pairs",
                "typed_failure_count",
                "feasible",
            ],
            "not_compared": [
                "raw_logit",
                "absolute_threshold",
                "score_calibration",
                "tokenizer_window",
                "template",
                "latency",
                "resources",
            ],
        },
    }
