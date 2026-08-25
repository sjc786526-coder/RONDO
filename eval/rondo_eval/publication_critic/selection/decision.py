"""Admission, ranking, the selection lock and the single unseen confirmation.

The rules applied here are exactly the ones named in the frozen protocol.  No
weighted total score exists anywhere: candidates are compared on error types in
a fixed lexicographic order, and every floor must hold on its own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from .contract import (
    CANDIDATES,
    EXPECTED_JUDGE_IDENTITY,
    SELECTION_METHOD,
    SelectionError,
    freeze_sha256,
    require_count,
    require_exact_keys,
    require_finite,
    require_object,
    require_sha256,
    validate_freeze,
)
from .judge import (
    model_agreement,
    package_sha256,
    reference_agreement,
    validate_aggregate,
    validate_package,
)
from .lock import SCHEMA as LOCK_SCHEMA
from .lock import TERMINAL as LOCK_TERMINAL
from .lock import lock_sha256, validate_lock
from .metrics import (
    PASS,
    REWRITE,
    LabeledRow,
    build_labeled_rows,
    candidate_metrics,
    confusion_at,
    roc_auc,
    select_threshold,
)
from .release import release_sha256, validate_release


VALIDATION_SCHEMA = "rondo-publication-critic-plan073-validation-result-v1"
UNSEEN_SCHEMA = "rondo-publication-critic-plan073-unseen-confirmation-v1"

VALIDATION_TERMINALS = ("SELECTED", "NO_GO", "INCONCLUSIVE")
TASK_TERMINALS = ("GO", "NO_GO", "INCONCLUSIVE")

_RUNTIME_FACT_KEYS = {
    "load_seconds",
    "warm_p95_latency_ms",
    "peak_rss_bytes",
    "peak_vram_bytes",
    "typed_failure_count",
    "scored_count",
}
_STAGE_ORDER = {candidate: index for index, candidate in enumerate(CANDIDATES)}


def validate_runtime_facts(value: Any, label: str) -> dict[str, Any]:
    facts = require_object(value, label)
    require_exact_keys(facts, _RUNTIME_FACT_KEYS, label)
    require_finite(facts["load_seconds"], f"{label} load seconds", minimum=0.0)
    require_finite(facts["warm_p95_latency_ms"], f"{label} warm latency", minimum=0.0)
    require_count(facts["peak_rss_bytes"], f"{label} peak RSS")
    require_count(facts["peak_vram_bytes"], f"{label} peak VRAM")
    require_count(facts["typed_failure_count"], f"{label} typed failures")
    require_count(facts["scored_count"], f"{label} scored count")
    return dict(facts)


def _runtime_gate_failures(
    facts: Mapping[str, Any],
    gates: Mapping[str, Any],
) -> list[str]:
    return [
        name
        for name, failed in (
            ("load_time_gate_failed", facts["load_seconds"] > gates["max_load_seconds"]),
            (
                "warm_latency_gate_failed",
                facts["warm_p95_latency_ms"] > gates["max_warm_p95_latency_ms"],
            ),
            ("peak_rss_gate_failed", facts["peak_rss_bytes"] > gates["max_peak_rss_bytes"]),
            (
                "peak_vram_gate_failed",
                facts["peak_vram_bytes"] > gates["max_peak_vram_bytes"],
            ),
        )
        if failed
    ]


def _quality_gate_failures(
    search: Mapping[str, Any],
    metrics: Mapping[str, Any],
    typed_failures: int,
    floors: Mapping[str, Any],
) -> list[str]:
    failures: list[str] = []
    if not search["feasible"]:
        failures.append("no_admissible_operating_point")
    roc_auc = metrics["roc_auc"]
    if roc_auc is None or roc_auc < floors["min_roc_auc"]:
        failures.append("roc_auc_floor_failed")
    boundary_rate = metrics["boundary_pairs"]["strict_win_rate"]
    if (
        boundary_rate is None
        or boundary_rate < floors["min_boundary_pair_strict_win_rate"]
    ):
        failures.append("boundary_pair_floor_failed")
    if typed_failures > floors["max_typed_failures"]:
        failures.append("typed_failure_floor_failed")
    return failures


def _predictions(metrics: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(row["candidate_id"]): str(row["predicted"]) for row in metrics["rows"]
    }


def _ranking_key(report: Mapping[str, Any]) -> tuple[Any, ...]:
    overall = report["metrics"]["overall"]
    judge = report["judge_agreement"]
    judge_rate = -1.0 if judge is None else float(judge["agreement_rate"])
    return (
        overall["confusion"]["false_pass"],
        -overall["balanced_accuracy"],
        -float(report["metrics"]["boundary_pairs"]["strict_win_rate"]),
        overall["confusion"]["false_rewrite"],
        -float(report["metrics"]["roc_auc"]),
        -judge_rate,
        _STAGE_ORDER[report["candidate"]],
    )


def _bind_judge_package(
    aggregate: Any,
    package_value: Any,
    release: Mapping[str, Any],
) -> None:
    """Tie a judge aggregate to the exact package that was sent out."""

    if aggregate is None:
        raise SelectionError("Plan 073 judge package binding needs a judge aggregate")
    package = validate_package(package_value)
    digest = package_sha256(package)
    if validate_aggregate(aggregate)["package_sha256"] != digest:
        raise SelectionError("Plan 073 judge aggregate is not bound to this package")
    if package["item_count"] != len(release["items"]):
        raise SelectionError("Plan 073 judge package does not cover the release")


def _judge_view(
    release: Mapping[str, Any],
    aggregate: Any,
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    if aggregate is None:
        return {
            "present": False,
            "aggregate_sha256": None,
            "model_identity": None,
            "reference_agreement": None,
            "gate_applicable": False,
            "gate_reason": "judge_evidence_absent",
        }
    validated = validate_aggregate(aggregate)
    if validated["model_identity"] != EXPECTED_JUDGE_IDENTITY:
        return {
            "present": False,
            "aggregate_sha256": None,
            "model_identity": validated["model_identity"],
            "reference_agreement": None,
            "gate_applicable": False,
            "gate_reason": "judge_model_identity_is_not_the_authorised_model",
        }
    agreement = reference_agreement(release, validated)
    threshold = float(protocol["judge"]["min_reference_agreement_for_gate"])
    applicable = (
        agreement["agreement_rate"] is not None
        and agreement["agreement_rate"] >= threshold
    )
    return {
        "present": True,
        "aggregate_sha256": sha256_bytes(canonical_json_bytes(dict(validated))),
        "model_identity": validated["model_identity"],
        "judged_dates": list(validated["judged_dates"]),
        "reference_agreement": agreement,
        "gate_applicable": applicable,
        "gate_reason": (
            None
            if applicable
            else "judge_reference_agreement_below_gate_activation_threshold"
        ),
    }


def evaluate_validation(
    freeze_value: Any,
    release_value: Any,
    observations: Mapping[str, Any],
    judge_aggregate: Any = None,
    judge_package: Any = None,
) -> dict[str, Any]:
    """Compare the three candidates and, if one qualifies, name the winner."""

    freeze = validate_freeze(freeze_value)
    release = validate_release(release_value)
    if release["split"] != "validation":
        raise SelectionError("Plan 073 validation requires the validation release")
    if release["dataset_manifest_sha256"] != freeze["dataset"]["manifest_sha256"]:
        raise SelectionError("Plan 073 validation release is not the frozen dataset")
    if set(observations) != set(CANDIDATES):
        raise SelectionError("Plan 073 validation requires all three candidates")
    if judge_package is not None:
        _bind_judge_package(judge_aggregate, judge_package, release)

    protocol = freeze["protocol"]
    floors = protocol["quality_floors"]
    judge_view = _judge_view(release, judge_aggregate, protocol)

    reports: list[dict[str, Any]] = []
    for candidate in CANDIDATES:
        observation = require_object(
            observations[candidate], f"Plan 073 {candidate} observation"
        )
        require_exact_keys(
            observation,
            {"deployment_artifact_sha256", "scores", "runtime"},
            f"Plan 073 {candidate} observation",
        )
        if observation["deployment_artifact_sha256"] != freeze["artifacts"][candidate][
            "deployment_artifact_sha256"
        ]:
            raise SelectionError("Plan 073 candidate artifact identity drifted")
        facts = validate_runtime_facts(
            observation["runtime"], f"Plan 073 {candidate} runtime"
        )
        # A candidate that could not score the whole cohort yields no
        # comparable evidence. That is an INCONCLUSIVE task terminal, not a
        # quality verdict, so refuse it here rather than ranking a partial run.
        if facts["typed_failure_count"] or facts["scored_count"] != len(release["items"]):
            raise SelectionError(
                "Plan 073 candidate scoring is incomplete; the run cannot produce a "
                "comparable selection and must be reported INCONCLUSIVE"
            )
        rows = build_labeled_rows(release, observation["scores"])
        if facts["scored_count"] != len(rows):
            raise SelectionError("Plan 073 scored count does not match the release")
        search = select_threshold(rows, floors)
        metrics = candidate_metrics(release, rows, search["threshold"])
        agreement = (
            model_agreement(judge_aggregate, _predictions(metrics))
            if judge_view["present"]
            else None
        )
        failures = _quality_gate_failures(
            search, metrics, int(facts["typed_failure_count"]), floors
        ) + _runtime_gate_failures(facts, protocol["runtime_gates"])
        reports.append(
            {
                "candidate": candidate,
                "deployment_artifact_sha256": observation["deployment_artifact_sha256"],
                "lineage": freeze["artifacts"][candidate]["lineage"],
                "threshold_search": search,
                "metrics": metrics,
                "runtime": facts,
                "judge_agreement": agreement,
                "admission": {
                    "admissible": not failures,
                    "failed_gates": failures,
                },
            }
        )

    admissible = [report for report in reports if report["admission"]["admissible"]]
    ranked = sorted(admissible, key=_ranking_key)
    terminal, selected, runner_up, reasons = _validation_terminal(
        ranked, judge_view, protocol
    )
    return {
        "schema": VALIDATION_SCHEMA,
        "mode": freeze["mode"],
        "run_id": freeze["run_id"],
        "method": dict(SELECTION_METHOD),
        "selection_freeze_sha256": freeze_sha256(freeze),
        "release_sha256": release_sha256(release),
        "cohort": {
            "split": release["split"],
            "candidate_count": len(release["items"]),
            "pair_count": len(release["pairs"]),
        },
        "judge": judge_view,
        "candidates": {report["candidate"]: report for report in reports},
        "ranking": [report["candidate"] for report in ranked],
        "terminal": terminal,
        "selected": selected,
        "runner_up": runner_up,
        "reasons": reasons,
        "scope_note": (
            "validation_selection_only_threshold_fitted_here_unseen_test_still_sealed"
        ),
    }


def _validation_terminal(
    ranked: Sequence[Mapping[str, Any]],
    judge_view: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> tuple[str, str | None, str | None, list[str]]:
    if not judge_view["present"]:
        return (
            "INCONCLUSIVE",
            None,
            None,
            [judge_view["gate_reason"] or "judge_evidence_absent"],
        )
    if not ranked:
        return (
            "NO_GO",
            None,
            None,
            ["no_candidate_reached_the_frozen_publication_quality_floors"],
        )
    winner = ranked[0]
    runner_up = ranked[1]["candidate"] if len(ranked) > 1 else None
    if judge_view["gate_applicable"]:
        agreement = winner["judge_agreement"]
        minimum = float(protocol["judge"]["min_selected_agreement"])
        if agreement is None or agreement["agreement_rate"] < minimum:
            return (
                "INCONCLUSIVE",
                None,
                None,
                ["independent_judge_materially_disagrees_with_the_leading_candidate"],
            )
    reasons = ["leading_candidate_passed_every_frozen_floor_and_ranked_first"]
    if not judge_view["gate_applicable"]:
        reasons.append("judge_sanity_gate_not_applicable_reference_agreement_too_low")
    return "SELECTED", winner["candidate"], runner_up, reasons


def _rows_from_report(report: Mapping[str, Any]) -> tuple[LabeledRow, ...]:
    """Rebuild scoring rows from a reported result, for independent recomputation."""

    rows = report["metrics"]["rows"]
    if not isinstance(rows, list) or not rows:
        raise SelectionError("Plan 073 candidate report carries no scored rows")
    rebuilt: list[LabeledRow] = []
    for row_value in rows:
        row = require_object(row_value, "Plan 073 reported row")
        require_exact_keys(
            row,
            {"candidate_id", "label", "score", "raw_logit", "predicted", "margin_to_threshold"},
            "Plan 073 reported row",
        )
        if row["label"] not in {PASS, REWRITE}:
            raise SelectionError("Plan 073 reported row label is invalid")
        rebuilt.append(
            LabeledRow(
                candidate_id=str(row["candidate_id"]),
                score=require_finite(row["score"], "Plan 073 reported score", minimum=0.0, maximum=1.0),
                raw_logit=require_finite(row["raw_logit"], "Plan 073 reported raw logit"),
                label=str(row["label"]),
                slices=(),
                facets={},
            )
        )
    if len({row.candidate_id for row in rebuilt}) != len(rebuilt):
        raise SelectionError("Plan 073 reported rows contain a duplicate candidate")
    return tuple(rebuilt)


def _recheck_candidate(report: Mapping[str, Any], freeze: Mapping[str, Any]) -> None:
    """Recompute a candidate report from its own rows and the frozen protocol.

    This is what stops a hand-edited result from opening unseen-test: the
    threshold, its feasibility, the confusion counts, the separability and the
    admission verdict must all follow from the scored rows the document itself
    carries.
    """

    require_exact_keys(
        report,
        {
            "candidate",
            "deployment_artifact_sha256",
            "lineage",
            "threshold_search",
            "metrics",
            "runtime",
            "judge_agreement",
            "admission",
        },
        "Plan 073 candidate report",
    )
    candidate = report["candidate"]
    if candidate not in CANDIDATES:
        raise SelectionError("Plan 073 candidate report identity is invalid")
    artifact = freeze["artifacts"][candidate]
    if (
        report["deployment_artifact_sha256"] != artifact["deployment_artifact_sha256"]
        or report["lineage"] != artifact["lineage"]
    ):
        raise SelectionError("Plan 073 candidate report artifact identity drifted")

    protocol = freeze["protocol"]
    floors = protocol["quality_floors"]
    rows = _rows_from_report(report)
    metrics = report["metrics"]
    if select_threshold(rows, floors) != report["threshold_search"]:
        raise SelectionError("Plan 073 candidate threshold search is not reproducible")
    threshold = float(report["threshold_search"]["threshold"])
    if metrics["threshold"] != threshold:
        raise SelectionError("Plan 073 candidate metrics use a different threshold")
    if confusion_at(rows, threshold) != metrics["overall"]["confusion"]:
        raise SelectionError("Plan 073 candidate confusion is not reproducible")
    if roc_auc(rows) != metrics["roc_auc"]:
        raise SelectionError("Plan 073 candidate separability is not reproducible")

    facts = validate_runtime_facts(report["runtime"], "Plan 073 candidate runtime")
    if facts["scored_count"] != len(rows):
        raise SelectionError("Plan 073 candidate scored count does not match its rows")
    failures = _quality_gate_failures(
        report["threshold_search"], metrics, int(facts["typed_failure_count"]), floors
    ) + _runtime_gate_failures(facts, protocol["runtime_gates"])
    if report["admission"] != {
        "admissible": not failures,
        "failed_gates": failures,
    }:
        raise SelectionError("Plan 073 candidate admission does not follow its evidence")


def validate_validation_result(
    value: Any,
    freeze_value: Any,
) -> dict[str, Any]:
    """Accept a validation result only if it re-derives from its own evidence."""

    freeze = validate_freeze(freeze_value)
    result = require_object(value, "Plan 073 validation result")
    require_exact_keys(
        result,
        {
            "schema",
            "mode",
            "run_id",
            "method",
            "selection_freeze_sha256",
            "release_sha256",
            "cohort",
            "judge",
            "candidates",
            "ranking",
            "terminal",
            "selected",
            "runner_up",
            "reasons",
            "scope_note",
        },
        "Plan 073 validation result",
    )
    if (
        result["schema"] != VALIDATION_SCHEMA
        or result["method"] != SELECTION_METHOD
        or result["mode"] != freeze["mode"]
        or result["run_id"] != freeze["run_id"]
        or result["selection_freeze_sha256"] != freeze_sha256(freeze)
    ):
        raise SelectionError("Plan 073 validation result is not bound to this freeze")
    require_sha256(result["release_sha256"], "Plan 073 validation result release")

    candidates = require_object(result["candidates"], "Plan 073 validation candidates")
    require_exact_keys(candidates, set(CANDIDATES), "Plan 073 validation candidates")
    reports = []
    for candidate in CANDIDATES:
        report = require_object(candidates[candidate], "Plan 073 candidate report")
        if report["candidate"] != candidate:
            raise SelectionError("Plan 073 candidate report is misfiled")
        _recheck_candidate(report, freeze)
        reports.append(report)

    judge = require_object(result["judge"], "Plan 073 judge view")
    ranked = sorted(
        (report for report in reports if report["admission"]["admissible"]),
        key=_ranking_key,
    )
    if result["ranking"] != [report["candidate"] for report in ranked]:
        raise SelectionError("Plan 073 ranking does not follow the frozen order")
    terminal, selected, runner_up, reasons = _validation_terminal(
        ranked, judge, freeze["protocol"]
    )
    if (
        result["terminal"] != terminal
        or result["selected"] != selected
        or result["runner_up"] != runner_up
        or list(result["reasons"]) != reasons
    ):
        raise SelectionError("Plan 073 validation terminal does not follow its evidence")
    return dict(result)


def build_selection_lock(
    validation_result: Mapping[str, Any],
    freeze_value: Any,
) -> dict[str, Any]:
    """Turn a ``SELECTED`` validation result into the one artifact unseen needs."""

    freeze = validate_freeze(freeze_value)
    validation_result = validate_validation_result(validation_result, freeze)
    if validation_result["mode"] != "formal":
        raise SelectionError("Plan 073 selection lock requires a formal validation run")
    if validation_result["terminal"] != "SELECTED":
        raise SelectionError("Plan 073 selection lock requires a SELECTED terminal")
    selected = validation_result["selected"]
    report = validation_result["candidates"][selected]
    lock = {
        "schema": LOCK_SCHEMA,
        "terminal": LOCK_TERMINAL,
        "run_id": validation_result["run_id"],
        "selection_freeze_sha256": validation_result["selection_freeze_sha256"],
        "validation_result_sha256": sha256_bytes(
            canonical_json_bytes(dict(validation_result))
        ),
        "selected": {
            "candidate": selected,
            "deployment_artifact_sha256": report["deployment_artifact_sha256"],
            "threshold": {
                "projected_score": float(report["threshold_search"]["threshold"]),
                "method": SELECTION_METHOD["threshold_rule"],
            },
            "runtime": dict(freeze["runtime"]),
        },
        "runner_up": validation_result["runner_up"],
        "reasons": list(validation_result["reasons"]),
        "unseen_release_authorized": True,
    }
    return validate_lock(lock)


def evaluate_unseen_confirmation(
    lock_value: Any,
    freeze_value: Any,
    release_value: Any,
    observation: Mapping[str, Any],
    judge_aggregate: Any = None,
) -> dict[str, Any]:
    """Apply the locked combination unchanged to the released unseen split."""

    lock = validate_lock(lock_value)
    freeze = validate_freeze(freeze_value)
    release = validate_release(release_value)
    if lock["selection_freeze_sha256"] != freeze_sha256(freeze):
        raise SelectionError("Plan 073 unseen confirmation freeze binding is invalid")
    if release["split"] != "unseen_test":
        raise SelectionError("Plan 073 confirmation requires the unseen-test release")
    if release["authorization"]["selection_lock_sha256"] != lock_sha256(lock):
        raise SelectionError("Plan 073 unseen release was not opened by this lock")
    if release["dataset_manifest_sha256"] != freeze["dataset"]["manifest_sha256"]:
        raise SelectionError("Plan 073 unseen release is not the frozen dataset")

    require_exact_keys(
        require_object(observation, "Plan 073 confirmation observation"),
        {"candidate", "deployment_artifact_sha256", "scores", "runtime"},
        "Plan 073 confirmation observation",
    )
    selected = lock["selected"]
    if (
        observation["candidate"] != selected["candidate"]
        or observation["deployment_artifact_sha256"]
        != selected["deployment_artifact_sha256"]
    ):
        raise SelectionError("Plan 073 confirmation ran a different locked combination")

    protocol = freeze["protocol"]
    floors = protocol["quality_floors"]
    threshold = float(selected["threshold"]["projected_score"])
    facts = validate_runtime_facts(observation["runtime"], "Plan 073 confirmation runtime")
    if facts["typed_failure_count"] or facts["scored_count"] != len(release["items"]):
        raise SelectionError(
            "Plan 073 confirmation scoring is incomplete; the blind confirmation is "
            "INCONCLUSIVE rather than a quality verdict"
        )
    rows = build_labeled_rows(release, observation["scores"])
    if facts["scored_count"] != len(rows):
        raise SelectionError("Plan 073 scored count does not match the release")
    metrics = candidate_metrics(release, rows, threshold)
    judge_view = _judge_view(release, judge_aggregate, protocol)
    agreement = (
        model_agreement(judge_aggregate, _predictions(metrics))
        if judge_view["present"]
        else None
    )

    overall = metrics["overall"]
    failures = [
        name
        for name, failed in (
            (
                "false_pass_floor_failed",
                overall["false_pass_rate"] is None
                or overall["false_pass_rate"] > floors["max_false_pass_rate"],
            ),
            (
                "false_rewrite_floor_failed",
                overall["false_rewrite_rate"] is None
                or overall["false_rewrite_rate"] > floors["max_false_rewrite_rate"],
            ),
            (
                "balanced_accuracy_floor_failed",
                overall["balanced_accuracy"] is None
                or overall["balanced_accuracy"] < floors["min_balanced_accuracy"],
            ),
        )
        if failed
    ]
    failures += _quality_gate_failures(
        {"feasible": True}, metrics, int(facts["typed_failure_count"]), floors
    )
    failures += _runtime_gate_failures(facts, protocol["runtime_gates"])

    terminal, reasons = _confirmation_terminal(
        failures, judge_view, agreement, protocol
    )
    return {
        "schema": UNSEEN_SCHEMA,
        "mode": "formal",
        "run_id": lock["run_id"],
        "method": SELECTION_METHOD["unseen_confirmation"],
        "selection_lock_sha256": lock_sha256(lock),
        "selection_freeze_sha256": lock["selection_freeze_sha256"],
        "release_sha256": release_sha256(release),
        "locked_combination": dict(selected),
        "cohort": {
            "split": release["split"],
            "candidate_count": len(release["items"]),
            "pair_count": len(release["pairs"]),
        },
        "metrics": metrics,
        "runtime": facts,
        "judge": judge_view,
        "judge_agreement": agreement,
        "failed_gates": failures,
        "terminal": terminal,
        "reasons": reasons,
        "scope_note": "single_blind_confirmation_of_one_locked_combination",
    }


def _confirmation_terminal(
    failures: Sequence[str],
    judge_view: Mapping[str, Any],
    agreement: Mapping[str, Any] | None,
    protocol: Mapping[str, Any],
) -> tuple[str, list[str]]:
    if not judge_view["present"]:
        return "INCONCLUSIVE", [judge_view["gate_reason"] or "judge_evidence_absent"]
    if failures:
        return "NO_GO", ["locked_combination_failed_a_frozen_publication_quality_floor"]
    if judge_view["gate_applicable"]:
        minimum = float(protocol["judge"]["min_selected_agreement"])
        if agreement is None or agreement["agreement_rate"] < minimum:
            return (
                "INCONCLUSIVE",
                ["independent_judge_materially_disagrees_on_the_unseen_split"],
            )
    reasons = ["locked_combination_passed_every_frozen_floor_on_unseen_test"]
    if not judge_view["gate_applicable"]:
        reasons.append("judge_sanity_gate_not_applicable_reference_agreement_too_low")
    return "GO", reasons


__all__ = [
    "PASS",
    "REWRITE",
    "TASK_TERMINALS",
    "UNSEEN_SCHEMA",
    "VALIDATION_SCHEMA",
    "VALIDATION_TERMINALS",
    "build_selection_lock",
    "evaluate_unseen_confirmation",
    "evaluate_validation",
    "require_sha256",
    "validate_runtime_facts",
    "validate_validation_result",
]
