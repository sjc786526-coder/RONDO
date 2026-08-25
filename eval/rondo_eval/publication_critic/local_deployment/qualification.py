"""Plan 068 commissioning/formal qualification runner and three-state decision."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
from typing import Any

from ..contract import REPO_ROOT, load_sample_corpus
from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from ..scoring import project_logit
from .archive import QualificationArchive
from .inference import PublicationCriticInference


FREEZE_SCHEMA = "rondo-publication-critic-plan068-qualification-freeze-v2"
OBSERVATIONS_SCHEMA = "rondo-publication-critic-plan068-observations-v2"
RESULT_SCHEMA = "rondo-publication-critic-plan068-qualification-result-v2"
OFFLINE_SCHEMA = "rondo-publication-critic-plan068-offline-scores-v2"
QUALIFICATION_OBJECTS = ("base", "c1", "c2", "c3")
CONCLUSIONS = ("QUALIFIED", "NOT_QUALIFIED", "INCONCLUSIVE")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_BODY_FREE_REASON = re.compile(r"[a-z0-9][a-z0-9_:-]{0,127}\Z")
_RUN_ID = re.compile(
    r"plan068-(commissioning|formal)-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}\Z"
)

_GATE_KEYS = {
    "max_raw_logit_absolute_drift",
    "max_projected_absolute_drift",
    "min_ranking_concordance",
    "reference_obvious_margin_floor",
    "min_obvious_margin_direction_agreement",
    "min_pair_direction_agreement",
    "max_verdict_mismatches",
    "max_load_seconds",
    "max_peak_rss_bytes",
    "max_peak_vram_bytes",
    "max_warm_p95_latency_ms",
    "max_service_score_absolute_drift",
    "max_service_raw_logit_absolute_drift",
    "max_service_verdict_mismatches",
    "min_stress_success_rate",
    "max_stress_p95_latency_ms",
}
_SERVICE_LIMIT_KEYS = {
    "request_bytes",
    "response_bytes",
    "max_concurrency",
    "queue_capacity",
    "job_timeout_ms",
    "io_timeout_ms",
    "worker_startup_timeout_ms",
    "worker_io_timeout_ms",
    "worker_shutdown_timeout_ms",
    "graceful_shutdown_ms",
    "force_shutdown_ms",
    "call_timeout_ms",
    "startup_timeout_ms",
    "process_timeout_ms",
    "representative_cancel_after_ms",
}


class QualificationError(ValueError):
    """A body-free invalid freeze, observation, or qualification invocation."""


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise QualificationError(f"{label} fields are invalid")


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise QualificationError(f"{label} must be an object")
    return value


def _finite(value: Any, label: str, *, minimum: float | None = None) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise QualificationError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        raise QualificationError(f"{label} is outside its finite domain")
    return number


def _count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise QualificationError(f"{label} must be a nonnegative integer")
    return value


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def validate_freeze(value: Any) -> dict[str, Any]:
    freeze = _object(value, "qualification freeze")
    _require_exact_keys(
        freeze,
        {
            "schema",
            "mode",
            "run_id",
            "qualification_objects",
            "cohort",
            "service_parity_input",
            "threshold",
            "reference_method",
            "source",
            "artifacts",
            "runtime",
            "gates",
            "stress_call_counts",
            "representative_lifecycle_object",
        },
        "qualification freeze",
    )
    if freeze["schema"] != FREEZE_SCHEMA or list(freeze["qualification_objects"]) != list(
        QUALIFICATION_OBJECTS
    ):
        raise QualificationError("qualification freeze identity is invalid")
    run_match = _RUN_ID.fullmatch(freeze["run_id"]) if isinstance(freeze["run_id"], str) else None
    if run_match is None or freeze["mode"] not in {"commissioning", "formal"} or run_match.group(
        1
    ) != freeze["mode"]:
        raise QualificationError("qualification freeze run identity is invalid")
    cohort = _object(freeze["cohort"], "qualification cohort")
    _require_exact_keys(cohort, {"sample_ids", "future_unseen_test"}, "qualification cohort")
    sample_ids = cohort["sample_ids"]
    if (
        not isinstance(sample_ids, list)
        or not sample_ids
        or any(not isinstance(item, str) or not item for item in sample_ids)
        or len(set(sample_ids)) != len(sample_ids)
        or cohort["future_unseen_test"] is not False
    ):
        raise QualificationError("qualification cohort is invalid")
    known_ids = set(load_sample_corpus(REPO_ROOT).by_id)
    if not set(sample_ids).issubset(known_ids):
        raise QualificationError("qualification cohort contains an unknown sample")

    service_input = _object(freeze["service_parity_input"], "service parity input")
    _require_exact_keys(
        service_input,
        {"sample_id", "packet_sha256"},
        "service parity input",
    )
    if (
        service_input["sample_id"] not in sample_ids
        or not _is_sha256(service_input["packet_sha256"])
    ):
        raise QualificationError("service parity input identity is invalid")

    threshold = _object(freeze["threshold"], "qualification threshold")
    _require_exact_keys(threshold, {"source", "projected_score"}, "qualification threshold")
    if not isinstance(threshold["source"], str) or not threshold["source"].strip():
        raise QualificationError("qualification threshold source is invalid")
    threshold_value = _finite(threshold["projected_score"], "qualification threshold")
    if not 0.0 <= threshold_value <= 1.0:
        raise QualificationError("qualification threshold is outside [0,1]")
    if not isinstance(freeze["reference_method"], str) or not freeze["reference_method"].strip():
        raise QualificationError("qualification reference method is invalid")

    source = _object(freeze["source"], "qualification source")
    _require_exact_keys(
        source,
        {
            "git_commit",
            "tracked_source_clean",
            "environment_lock_path",
            "environment_lock_sha256",
        },
        "qualification source",
    )
    if (
        not isinstance(source["git_commit"], str)
        or _GIT_COMMIT.fullmatch(source["git_commit"]) is None
        or source["tracked_source_clean"] is not True
        or not _is_sha256(source["environment_lock_sha256"])
    ):
        raise QualificationError("qualification source identity is invalid")
    environment_lock_path = source["environment_lock_path"]
    if (
        not isinstance(environment_lock_path, str)
        or Path(environment_lock_path).is_absolute()
        or ".." in Path(environment_lock_path).parts
        or Path(environment_lock_path).name != "uv.lock"
    ):
        raise QualificationError("qualification environment lock path is invalid")
    artifacts = _object(freeze["artifacts"], "qualification artifacts")
    _require_exact_keys(artifacts, set(QUALIFICATION_OBJECTS), "qualification artifacts")
    for object_id in QUALIFICATION_OBJECTS:
        artifact = _object(artifacts[object_id], "qualification artifact")
        _require_exact_keys(
            artifact,
            {
                "candidate_artifact_sha256",
                "deployment_artifact_sha256",
                "service_descriptor_sha256",
            },
            "qualification artifact",
        )
        if (
            not _is_sha256(artifact["candidate_artifact_sha256"])
            or not _is_sha256(artifact["deployment_artifact_sha256"])
            or not _is_sha256(artifact["service_descriptor_sha256"])
        ):
            raise QualificationError("qualification artifact identity is invalid")

    runtime = _object(freeze["runtime"], "qualification runtime")
    _require_exact_keys(
        runtime,
        {
            "device",
            "dtype",
            "cpu_threads",
            "deployment_format",
            "programs",
            "service_limits",
        },
        "qualification runtime",
    )
    if runtime["device"] not in {"cpu", "cuda"} or runtime["dtype"] not in {
        "float32",
        "bfloat16",
    }:
        raise QualificationError("qualification runtime device or dtype is invalid")
    if type(runtime["cpu_threads"]) is not int or runtime["cpu_threads"] <= 0:
        raise QualificationError("qualification runtime CPU threads are invalid")
    if not isinstance(runtime["deployment_format"], str) or not runtime[
        "deployment_format"
    ].strip():
        raise QualificationError("qualification deployment format is invalid")
    programs = _object(runtime["programs"], "qualification runtime programs")
    _require_exact_keys(
        programs,
        {"service_sha256", "probe_sha256", "python_sha256"},
        "qualification runtime programs",
    )
    if any(not _is_sha256(value) for value in programs.values()):
        raise QualificationError("qualification runtime program identity is invalid")
    service_limits = _object(runtime["service_limits"], "qualification service limits")
    _require_exact_keys(
        service_limits,
        _SERVICE_LIMIT_KEYS,
        "qualification service limits",
    )
    for name in _SERVICE_LIMIT_KEYS:
        if type(service_limits[name]) is not int or service_limits[name] <= 0:
            raise QualificationError(f"qualification service limit {name} is invalid")

    gates = _object(freeze["gates"], "qualification gates")
    _require_exact_keys(gates, _GATE_KEYS, "qualification gates")
    for name in _GATE_KEYS:
        _finite(gates[name], f"qualification gate {name}", minimum=0.0)
    for name in (
        "min_ranking_concordance",
        "min_obvious_margin_direction_agreement",
        "min_pair_direction_agreement",
        "min_stress_success_rate",
    ):
        if float(gates[name]) > 1.0:
            raise QualificationError(f"qualification gate {name} exceeds one")
    for name in ("max_verdict_mismatches", "max_service_verdict_mismatches"):
        if type(gates[name]) is not int:
            raise QualificationError(f"qualification gate {name} must be an integer")
    stress_counts = freeze["stress_call_counts"]
    if (
        not isinstance(stress_counts, list)
        or not stress_counts
        or any(type(item) is not int or item <= 0 for item in stress_counts)
        or len(set(stress_counts)) != len(stress_counts)
    ):
        raise QualificationError("qualification stress scenarios are invalid")
    if freeze["representative_lifecycle_object"] not in {"c1", "c2", "c3"}:
        raise QualificationError("qualification lifecycle representative is invalid")
    return dict(freeze)


def freeze_sha256(freeze: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(freeze)))


def _not_available(reason: str) -> dict[str, Any]:
    return {"status": "N/A", "value": None, "reason": reason}


def _observed(value: Any) -> dict[str, Any]:
    return {"status": "OBSERVED", "value": value, "reason": None}


def _percentile_95(values: Sequence[float]) -> float:
    if not values:
        raise QualificationError("latency observation is empty")
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _check_state(
    observation: Mapping[str, Any],
    label: str,
    *,
    success_state: str,
) -> tuple[str | None, str | None]:
    state = observation.get("state")
    if state == success_state:
        return None, None
    reason = observation.get("reason")
    if not isinstance(reason, str) or _BODY_FREE_REASON.fullmatch(reason) is None:
        raise QualificationError(f"{label} non-success state requires a reason")
    if state == "not_reached":
        return "INCONCLUSIVE", reason
    if state != "failed" or observation.get("failure_scope") not in {
        "candidate",
        "infrastructure",
    }:
        raise QualificationError(f"{label} state is invalid")
    conclusion = (
        "NOT_QUALIFIED" if observation["failure_scope"] == "candidate" else "INCONCLUSIVE"
    )
    return conclusion, reason


def _dimension(
    value: Any,
    label: str,
    payload_keys: set[str],
    *,
    success_state: str,
) -> Mapping[str, Any]:
    observation = _object(value, label)
    _require_exact_keys(
        observation,
        {"state", "reason", "failure_scope"} | payload_keys,
        label,
    )
    if observation["state"] == success_state:
        if observation["reason"] is not None or observation["failure_scope"] != "none":
            raise QualificationError(f"{label} success metadata is invalid")
    elif observation["state"] == "not_reached":
        if observation["failure_scope"] != "infrastructure":
            raise QualificationError(f"{label} not-reached scope is invalid")
    return observation


def _score_rows(
    rows: Any,
    sample_ids: Sequence[str],
    label: str,
) -> dict[str, dict[str, float]]:
    if not isinstance(rows, list) or len(rows) != len(sample_ids):
        raise QualificationError(f"{label} row count is invalid")
    result: dict[str, dict[str, float]] = {}
    for row_value in rows:
        row = _object(row_value, f"{label} row")
        _require_exact_keys(
            row,
            {
                "sample_id",
                "raw_logit",
                "projected_score",
                "token_count",
                "dropped_oldest_publications",
                "model_elapsed_ms",
            },
            f"{label} row",
        )
        sample_id = row["sample_id"]
        if not isinstance(sample_id, str) or sample_id not in sample_ids or sample_id in result:
            raise QualificationError(f"{label} sample identity is invalid")
        raw = _finite(row["raw_logit"], f"{label} raw logit")
        score = _finite(row["projected_score"], f"{label} projected score")
        latency = _finite(row["model_elapsed_ms"], f"{label} model latency", minimum=0.0)
        _count(row["token_count"], f"{label} token count")
        _count(
            row["dropped_oldest_publications"],
            f"{label} dropped oldest publications",
        )
        if not 0.0 <= score <= 1.0 or abs(project_logit(raw) - score) > 1e-12:
            raise QualificationError(f"{label} scalar projection drifted")
        result[sample_id] = {"raw_logit": raw, "score": score, "latency_ms": latency}
    if set(result) != set(sample_ids):
        raise QualificationError(f"{label} cohort identity drifted")
    return result


def _ranking_concordance(reference: Sequence[float], deployed: Sequence[float]) -> float:
    agreements = 0.0
    comparisons = 0
    for left in range(len(reference)):
        for right in range(left + 1, len(reference)):
            reference_direction = (reference[left] > reference[right]) - (
                reference[left] < reference[right]
            )
            deployed_direction = (deployed[left] > deployed[right]) - (
                deployed[left] < deployed[right]
            )
            agreements += 1.0 if reference_direction == deployed_direction else 0.0
            comparisons += 1
    return agreements / comparisons if comparisons else 1.0


def _pair_directions(rows: Mapping[str, Mapping[str, float]]) -> dict[str, int]:
    corpus = load_sample_corpus(REPO_ROOT)
    pairs: dict[str, dict[str, str]] = {}
    for sample in corpus.samples:
        if sample.sample_id not in rows:
            continue
        annotation = sample.annotation
        pairs.setdefault(str(annotation["pair_id"]), {})[
            str(annotation["expected_verdict"])
        ] = sample.sample_id
    complete = {
        pair_id: pair
        for pair_id, pair in pairs.items()
        if set(pair) == {"pass", "rewrite"}
    }
    if not complete:
        raise QualificationError("qualification cohort has no complete direction pair")
    return {
        pair_id: (rows[pair["pass"]]["score"] > rows[pair["rewrite"]]["score"])
        - (rows[pair["pass"]]["score"] < rows[pair["rewrite"]]["score"])
        for pair_id, pair in complete.items()
    }


def _pair_direction_rate(rows: Mapping[str, Mapping[str, float]]) -> float:
    directions = _pair_directions(rows)
    return sum(direction > 0 for direction in directions.values()) / len(directions)


def _pair_direction_preservation(
    reference: Mapping[str, Mapping[str, float]],
    deployed: Mapping[str, Mapping[str, float]],
) -> float:
    reference_directions = _pair_directions(reference)
    deployed_directions = _pair_directions(deployed)
    if set(reference_directions) != set(deployed_directions):
        raise QualificationError("qualification pair cohort drifted")
    return sum(
        direction == deployed_directions[pair_id]
        for pair_id, direction in reference_directions.items()
    ) / len(reference_directions)


def _score_metrics(
    reference: Mapping[str, Mapping[str, float]],
    deployed: Mapping[str, Mapping[str, float]],
    sample_ids: Sequence[str],
    threshold: float,
    obvious_margin_floor: float,
) -> dict[str, Any]:
    reference_scores = [reference[sample_id]["score"] for sample_id in sample_ids]
    deployed_scores = [deployed[sample_id]["score"] for sample_id in sample_ids]
    raw_drift = [
        abs(reference[sample_id]["raw_logit"] - deployed[sample_id]["raw_logit"])
        for sample_id in sample_ids
    ]
    drift = [abs(left - right) for left, right in zip(reference_scores, deployed_scores)]
    obvious = [
        (left, right, deployed_scores[left_index], deployed_scores[right_index])
        for left_index, left in enumerate(reference_scores)
        for right_index, right in enumerate(reference_scores[left_index + 1 :], left_index + 1)
        if abs(left - right) >= obvious_margin_floor
    ]
    obvious_agreement = (
        sum(
            ((left > right) - (left < right))
            == ((deployed_left > deployed_right) - (deployed_left < deployed_right))
            for left, right, deployed_left, deployed_right in obvious
        )
        / len(obvious)
        if obvious
        else None
    )
    return {
        "max_raw_logit_absolute_drift": max(raw_drift),
        "mean_raw_logit_absolute_drift": statistics.fmean(raw_drift),
        "max_projected_absolute_drift": max(drift),
        "mean_projected_absolute_drift": statistics.fmean(drift),
        "ranking_concordance": _ranking_concordance(reference_scores, deployed_scores),
        "obvious_margin_comparison_count": len(obvious),
        "obvious_margin_direction_agreement": obvious_agreement,
        "reference_pair_direction_agreement": _pair_direction_rate(reference),
        "deployment_pair_direction_agreement": _pair_direction_rate(deployed),
        "pair_direction_preservation": _pair_direction_preservation(reference, deployed),
        "verdict_mismatches": sum(
            (left >= threshold) != (right >= threshold)
            for left, right in zip(reference_scores, deployed_scores)
        ),
    }


def _terminal(
    object_id: str,
    conclusion: str,
    reasons: list[str],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    if conclusion not in CONCLUSIONS:
        raise QualificationError("qualification conclusion is invalid")
    return {
        "object_id": object_id,
        "conclusion": conclusion,
        "reasons": reasons,
        "metrics": metrics,
    }


def evaluate_object(
    observation_value: Any,
    freeze: Mapping[str, Any],
    expected_freeze_sha256: str,
) -> dict[str, Any]:
    observation = _object(observation_value, "qualification observation")
    _require_exact_keys(
        observation,
        {
            "schema",
            "mode",
            "run_id",
            "qualification_freeze_sha256",
            "object_id",
            "evidence",
            "identity",
            "artifact",
            "load",
            "scores",
            "resources",
            "latency",
            "service",
            "stress",
            "lifecycle",
        },
        "qualification observation",
    )
    object_id = observation["object_id"]
    if (
        observation["schema"] != OBSERVATIONS_SCHEMA
        or observation["run_id"] != freeze["run_id"]
        or object_id not in QUALIFICATION_OBJECTS
        or observation["qualification_freeze_sha256"] != expected_freeze_sha256
    ):
        raise QualificationError("qualification observation identity is invalid")
    evidence = _object(observation["evidence"], "qualification evidence binding")
    _require_exact_keys(
        evidence,
        {
            "reference_offline_sha256",
            "deployment_offline_sha256",
            "service_run_sha256",
            "service_parity_sha256",
            "service_packet_sha256",
        },
        "qualification evidence binding",
    )
    if any(
        value is not None and not _is_sha256(value)
        for value in evidence.values()
    ) or evidence["service_packet_sha256"] != freeze["service_parity_input"][
        "packet_sha256"
    ]:
        raise QualificationError("qualification evidence identity is invalid")
    metrics: dict[str, Any] = {}
    for label in ("identity", "artifact"):
        payload_keys = (
            {"candidate_artifact_sha256", "deployment_artifact_sha256"}
            if label == "artifact"
            else {"service_descriptor_sha256"}
        )
        dimension = _dimension(
            observation[label],
            f"qualification {label}",
            payload_keys,
            success_state="passed",
        )
        conclusion, reason = _check_state(
            dimension,
            f"qualification {label}",
            success_state="passed",
        )
        if conclusion is not None:
            metrics["remaining"] = _not_available(reason or "precondition was not reached")
            return _terminal(object_id, conclusion, [reason or "precondition failed"], metrics)
        if label == "artifact":
            frozen_artifact = freeze["artifacts"][object_id]
            if (
                dimension["candidate_artifact_sha256"]
                != frozen_artifact["candidate_artifact_sha256"]
                or dimension["deployment_artifact_sha256"]
                != frozen_artifact["deployment_artifact_sha256"]
            ):
                raise QualificationError("qualification artifact observation drifted")
        else:
            if (
                dimension["service_descriptor_sha256"]
                != freeze["artifacts"][object_id]["service_descriptor_sha256"]
            ):
                raise QualificationError("qualification service identity observation drifted")

    load = _dimension(
        observation["load"],
        "qualification load",
        {"seconds"},
        success_state="observed",
    )
    conclusion, reason = _check_state(load, "qualification load", success_state="observed")
    if conclusion is not None:
        metrics["load_seconds"] = _not_available(reason or "model load was not observed")
        metrics["remaining"] = _not_available(reason or "model load was not observed")
        return _terminal(object_id, conclusion, [reason or "model load failed"], metrics)
    load_seconds = _finite(load.get("seconds"), "qualification load seconds", minimum=0.0)
    metrics["load_seconds"] = _observed(load_seconds)
    gates = freeze["gates"]
    if load_seconds > gates["max_load_seconds"]:
        metrics["remaining"] = _not_available("load time exceeded the frozen gate")
        return _terminal(object_id, "NOT_QUALIFIED", ["load_time_gate_failed"], metrics)

    scores = _dimension(
        observation["scores"],
        "qualification scores",
        {"reference", "deployment"},
        success_state="observed",
    )
    conclusion, reason = _check_state(scores, "qualification scores", success_state="observed")
    if conclusion is not None:
        metrics["scores"] = _not_available(reason or "offline scores were not observed")
        return _terminal(object_id, conclusion, [reason or "offline scoring failed"], metrics)
    if not _is_sha256(evidence["reference_offline_sha256"]) or not _is_sha256(
        evidence["deployment_offline_sha256"]
    ):
        raise QualificationError("qualification offline evidence is unbound")
    reference = _score_rows(scores.get("reference"), freeze["cohort"]["sample_ids"], "reference")
    deployed = _score_rows(scores.get("deployment"), freeze["cohort"]["sample_ids"], "deployment")
    score_metrics = _score_metrics(
        reference,
        deployed,
        freeze["cohort"]["sample_ids"],
        float(freeze["threshold"]["projected_score"]),
        float(gates["reference_obvious_margin_floor"]),
    )
    metrics["scores"] = _observed(score_metrics)
    if score_metrics["obvious_margin_direction_agreement"] is None:
        metrics["remaining"] = _not_available("the frozen reference is insufficient")
        return _terminal(object_id, "INCONCLUSIVE", ["reference_method_invalid"], metrics)
    score_failures = [
        name
        for name, failed in (
            (
                "raw_logit_drift_gate_failed",
                score_metrics["max_raw_logit_absolute_drift"]
                > gates["max_raw_logit_absolute_drift"],
            ),
            (
                "projected_drift_gate_failed",
                score_metrics["max_projected_absolute_drift"]
                > gates["max_projected_absolute_drift"],
            ),
            (
                "ranking_gate_failed",
                score_metrics["ranking_concordance"] < gates["min_ranking_concordance"],
            ),
            (
                "obvious_margin_direction_gate_failed",
                score_metrics["obvious_margin_direction_agreement"]
                < gates["min_obvious_margin_direction_agreement"],
            ),
            (
                "pair_direction_gate_failed",
                score_metrics["pair_direction_preservation"]
                < gates["min_pair_direction_agreement"],
            ),
            (
                "verdict_parity_gate_failed",
                score_metrics["verdict_mismatches"] > gates["max_verdict_mismatches"],
            ),
        )
        if failed
    ]
    if score_failures:
        metrics["remaining"] = _not_available("offline score gate failed")
        return _terminal(object_id, "NOT_QUALIFIED", score_failures, metrics)

    resources = _dimension(
        observation["resources"],
        "qualification resources",
        {"peak_rss_bytes", "peak_vram_bytes"},
        success_state="observed",
    )
    conclusion, reason = _check_state(
        resources, "qualification resources", success_state="observed"
    )
    if conclusion is not None:
        metrics["resources"] = _not_available(reason or "resource counters were not observed")
        return _terminal(object_id, conclusion, [reason or "resource observation failed"], metrics)
    peak_rss = _count(resources.get("peak_rss_bytes"), "qualification peak RSS")
    peak_vram = _count(resources.get("peak_vram_bytes"), "qualification peak VRAM")
    metrics["resources"] = _observed(
        {"peak_rss_bytes": peak_rss, "peak_vram_bytes": peak_vram}
    )
    if peak_rss > gates["max_peak_rss_bytes"] or peak_vram > gates["max_peak_vram_bytes"]:
        metrics["remaining"] = _not_available("resource gate failed")
        return _terminal(object_id, "NOT_QUALIFIED", ["resource_gate_failed"], metrics)

    latency = _dimension(
        observation["latency"],
        "qualification latency",
        {"warm_ms"},
        success_state="observed",
    )
    conclusion, reason = _check_state(latency, "qualification latency", success_state="observed")
    if conclusion is not None:
        metrics["latency"] = _not_available(reason or "warm latency was not observed")
        return _terminal(object_id, conclusion, [reason or "latency observation failed"], metrics)
    warm_values = [
        _finite(item, "qualification warm latency", minimum=0.0)
        for item in latency.get("warm_ms", [])
    ]
    if len(warm_values) < 3:
        raise QualificationError("qualification warm latency requires three observations")
    warm_p95 = _percentile_95(warm_values)
    metrics["latency"] = _observed({"warm_ms": warm_values, "warm_p95_ms": warm_p95})
    if warm_p95 > gates["max_warm_p95_latency_ms"]:
        metrics["remaining"] = _not_available("warm latency gate failed")
        return _terminal(object_id, "NOT_QUALIFIED", ["warm_latency_gate_failed"], metrics)

    service = _dimension(
        observation["service"],
        "qualification service",
        {
            "raw_logit_absolute_differences",
            "score_absolute_differences",
            "verdict_mismatch_count",
            "bounded_call_count",
        },
        success_state="observed",
    )
    conclusion, reason = _check_state(service, "qualification service", success_state="observed")
    if conclusion is not None:
        metrics["service"] = _not_available(reason or "service parity was not observed")
        return _terminal(object_id, conclusion, [reason or "service observation failed"], metrics)
    if not _is_sha256(evidence["service_run_sha256"]) or not _is_sha256(
        evidence["service_parity_sha256"]
    ):
        raise QualificationError("qualification service evidence is unbound")
    service_drift = [
        _finite(item, "qualification service drift", minimum=0.0)
        for item in service.get("score_absolute_differences", [])
    ]
    service_raw_drift = [
        _finite(item, "qualification service raw logit drift", minimum=0.0)
        for item in service.get("raw_logit_absolute_differences", [])
    ]
    if not service_drift or not service_raw_drift:
        raise QualificationError("qualification service parity is empty")
    service_verdict_mismatches = _count(
        service.get("verdict_mismatch_count"), "qualification service verdict mismatches"
    )
    bounded_calls = _count(
        service.get("bounded_call_count"), "qualification bounded service calls"
    )
    metrics["service"] = _observed(
        {
            "max_raw_logit_absolute_drift": max(service_raw_drift),
            "max_score_absolute_drift": max(service_drift),
            "verdict_mismatch_count": service_verdict_mismatches,
            "bounded_call_count": bounded_calls,
        }
    )
    if (
        bounded_calls == 0
        or max(service_raw_drift) > gates["max_service_raw_logit_absolute_drift"]
        or max(service_drift) > gates["max_service_score_absolute_drift"]
        or service_verdict_mismatches > gates["max_service_verdict_mismatches"]
    ):
        metrics["remaining"] = _not_available("service parity gate failed")
        return _terminal(object_id, "NOT_QUALIFIED", ["service_parity_gate_failed"], metrics)

    stress = _dimension(
        observation["stress"],
        "qualification stress",
        {"success_count", "call_count", "latencies_ms", "scenario_call_counts"},
        success_state="observed",
    )
    conclusion, reason = _check_state(stress, "qualification stress", success_state="observed")
    if conclusion is not None:
        metrics["stress"] = _not_available(reason or "bounded stress was not observed")
        return _terminal(object_id, conclusion, [reason or "stress observation failed"], metrics)
    if stress.get("scenario_call_counts") != freeze["stress_call_counts"]:
        raise QualificationError("qualification stress scenarios drifted")
    success_count = _count(stress.get("success_count"), "qualification stress successes")
    call_count = _count(stress.get("call_count"), "qualification stress calls")
    stress_latencies = [
        _finite(item, "qualification stress latency", minimum=0.0)
        for item in stress.get("latencies_ms", [])
    ]
    if (
        call_count != sum(freeze["stress_call_counts"])
        or len(stress_latencies) != call_count
        or success_count > call_count
    ):
        raise QualificationError("qualification stress counts are invalid")
    stress_rate = success_count / call_count
    stress_p95 = _percentile_95(stress_latencies)
    metrics["stress"] = _observed(
        {
            "success_count": success_count,
            "call_count": call_count,
            "success_rate": stress_rate,
            "p95_latency_ms": stress_p95,
            "scenario_call_counts": list(stress["scenario_call_counts"]),
        }
    )
    stress_failures = []
    if stress_rate < gates["min_stress_success_rate"]:
        stress_failures.append("stress_success_gate_failed")
    if stress_p95 > gates["max_stress_p95_latency_ms"]:
        stress_failures.append("stress_latency_gate_failed")
    if stress_failures:
        return _terminal(object_id, "NOT_QUALIFIED", stress_failures, metrics)

    lifecycle = _dimension(
        observation["lifecycle"],
        "qualification lifecycle",
        {
            "matrix_role",
            "typed_failure_verified",
            "cancel_verified",
            "graceful_shutdown_verified",
            "forced_cleanup_verified",
            "orphan_worker_count",
            "body_leak_count",
        },
        success_state="observed",
    )
    conclusion, reason = _check_state(
        lifecycle, "qualification lifecycle", success_state="observed"
    )
    if conclusion is not None:
        metrics["lifecycle"] = _not_available(reason or "lifecycle matrix was not observed")
        return _terminal(object_id, conclusion, [reason or "lifecycle observation failed"], metrics)
    expected_role = (
        "representative"
        if object_id == freeze["representative_lifecycle_object"]
        else "basic"
    )
    if lifecycle.get("matrix_role") != expected_role:
        raise QualificationError("qualification lifecycle role drifted")
    booleans = {
        name: lifecycle.get(name)
        for name in (
            "typed_failure_verified",
            "cancel_verified",
            "graceful_shutdown_verified",
            "forced_cleanup_verified",
        )
    }
    if any(type(value) is not bool for value in booleans.values()):
        raise QualificationError("qualification lifecycle evidence is invalid")
    orphan_count = _count(
        lifecycle.get("orphan_worker_count"), "qualification orphan workers"
    )
    body_leak_count = _count(
        lifecycle.get("body_leak_count"), "qualification body leaks"
    )
    metrics["lifecycle"] = _observed(
        {
            "matrix_role": expected_role,
            **booleans,
            "orphan_worker_count": orphan_count,
            "body_leak_count": body_leak_count,
        }
    )
    required_lifecycle = booleans["graceful_shutdown_verified"]
    if expected_role == "representative":
        required_lifecycle = required_lifecycle and all(booleans.values())
    if not required_lifecycle or orphan_count != 0 or body_leak_count != 0:
        return _terminal(object_id, "NOT_QUALIFIED", ["lifecycle_gate_failed"], metrics)
    return _terminal(object_id, "QUALIFIED", [], metrics)


def evaluate_run(
    observations_value: Any,
    freeze_value: Any,
    *,
    mode: str,
    run_id: str,
) -> dict[str, Any]:
    if mode not in {"commissioning", "formal"}:
        raise QualificationError("qualification mode is invalid")
    freeze = validate_freeze(freeze_value)
    if freeze["mode"] != mode or freeze["run_id"] != run_id:
        raise QualificationError("qualification run does not match the freeze")
    digest = freeze_sha256(freeze)
    observations = _object(observations_value, "qualification observations")
    _require_exact_keys(
        observations,
        {"schema", "mode", "run_id", "qualification_freeze_sha256", "objects"},
        "qualification observations",
    )
    if (
        observations["schema"] != OBSERVATIONS_SCHEMA
        or observations["mode"] != mode
        or observations["run_id"] != run_id
        or observations["qualification_freeze_sha256"] != digest
        or not isinstance(observations["objects"], list)
        or not observations["objects"]
    ):
        raise QualificationError("qualification observations identity is invalid")
    if any(
        _object(item, "qualification observation").get("mode") != mode
        for item in observations["objects"]
    ):
        raise QualificationError("qualification observation mode drifted")
    results = [evaluate_object(item, freeze, digest) for item in observations["objects"]]
    object_ids = [result["object_id"] for result in results]
    if len(set(object_ids)) != len(object_ids):
        raise QualificationError("qualification object observation is duplicated")
    if mode == "formal" and tuple(object_ids) != QUALIFICATION_OBJECTS:
        raise QualificationError("formal qualification requires the frozen four-object order")
    conclusions = {result["object_id"]: result["conclusion"] for result in results}
    unlock = mode == "formal" and conclusions.get("base") == "QUALIFIED" and any(
        conclusions.get(candidate) == "QUALIFIED" for candidate in ("c1", "c2", "c3")
    )
    return {
        "schema": RESULT_SCHEMA,
        "mode": mode,
        "run_id": run_id,
        "qualification_freeze_sha256": digest,
        "observations_sha256": sha256_bytes(canonical_json_bytes(dict(observations))),
        "objects": results,
        "m3_c2_prerequisite_satisfied": unlock,
        "scope_note": (
            "qualification_only_no_candidate_ranking_or_final_threshold"
            if mode == "formal"
            else "commissioning_only_not_formal_qualification_evidence"
        ),
    }


def _load_json(path: Path, label: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise QualificationError(f"{label} is missing or unsafe")
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"{label} is invalid JSON") from exc


def _verify_formal_source(repo_root: Path, freeze: Mapping[str, Any]) -> None:
    source = freeze["source"]
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise QualificationError("formal tracked source state is unavailable") from exc
    if head != source["git_commit"] or status:
        raise QualificationError("formal tracked source is not the frozen clean commit")
    lock_path = repo_root / source["environment_lock_path"]
    if (
        not lock_path.resolve().is_relative_to(repo_root.resolve())
        or lock_path.is_symlink()
        or not lock_path.is_file()
        or sha256_file(lock_path) != source["environment_lock_sha256"]
    ):
        raise QualificationError("formal environment lock identity drifted")


def _write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
        raise QualificationError("offline output path is unsafe")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise QualificationError("offline output already exists") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if path.is_file() and not path.is_symlink():
            path.unlink()
        raise


def _offline(args: argparse.Namespace) -> int:
    freeze = validate_freeze(_load_json(args.freeze, "qualification freeze"))
    digest = freeze_sha256(freeze)
    snapshot_model_sha256 = sha256_file(args.snapshot / "model.safetensors")
    if list(args.sample_id) != list(freeze["cohort"]["sample_ids"]):
        raise QualificationError("offline cohort does not match the freeze")
    if snapshot_model_sha256 != freeze["artifacts"][args.object_id][
        "deployment_artifact_sha256"
    ]:
        raise QualificationError("offline artifact does not match the freeze")
    runtime = freeze["runtime"]
    expected_runtime = (
        ("cpu", "float32", runtime["cpu_threads"])
        if args.execution_role == "reference"
        else (runtime["device"], runtime["dtype"], runtime["cpu_threads"])
    )
    if (args.device, args.dtype, args.cpu_threads) != expected_runtime:
        raise QualificationError("offline runtime does not match its frozen role")
    inference = PublicationCriticInference(
        args.snapshot,
        repo_root=args.repo_root,
        device=args.device,
        dtype=args.dtype,
        cpu_threads=args.cpu_threads,
    )
    inference.load()
    result = {
        "schema": OFFLINE_SCHEMA,
        "mode": freeze["mode"],
        "run_id": freeze["run_id"],
        "qualification_freeze_sha256": digest,
        "execution_role": args.execution_role,
        "object_id": args.object_id,
        "deployment_artifact_sha256": freeze["artifacts"][args.object_id][
            "deployment_artifact_sha256"
        ],
        "snapshot_model_sha256": snapshot_model_sha256,
        "cohort_sample_ids_sha256": sha256_bytes(
            canonical_json_bytes(list(args.sample_id))
        ),
        "runtime": {
            "device": args.device,
            "dtype": args.dtype,
            "cpu_threads": args.cpu_threads,
        },
        "load_seconds": inference.load_seconds,
        "rows": inference.score_frozen_cohort(args.sample_id),
        "resources": inference.resource_snapshot(),
    }
    _write_json_exclusive(args.output, result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Plan 068 local qualification")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--mode", choices=("commissioning", "formal"), required=True)
    evaluate.add_argument("--freeze", type=Path, required=True)
    evaluate.add_argument("--observations", type=Path, required=True)
    evaluate.add_argument("--runs-root", type=Path, required=True)
    evaluate.add_argument("--run-id", required=True)

    offline = subparsers.add_parser("offline")
    offline.add_argument("--object-id", choices=QUALIFICATION_OBJECTS, required=True)
    offline.add_argument(
        "--execution-role", choices=("reference", "deployment"), required=True
    )
    offline.add_argument("--freeze", type=Path, required=True)
    offline.add_argument("--snapshot", type=Path, required=True)
    offline.add_argument("--device", choices=("cpu", "cuda"), required=True)
    offline.add_argument("--dtype", choices=("float32", "bfloat16"), required=True)
    offline.add_argument("--cpu-threads", type=int, required=True)
    offline.add_argument("--sample-id", action="append", required=True)
    offline.add_argument("--output", type=Path, required=True)
    offline.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "offline":
        return _offline(args)
    freeze = validate_freeze(_load_json(args.freeze, "qualification freeze"))
    if args.mode == "formal":
        _verify_formal_source(REPO_ROOT, freeze)
    observations = _load_json(args.observations, "qualification observations")
    result = evaluate_run(
        observations,
        freeze,
        mode=args.mode,
        run_id=args.run_id,
    )
    archive = QualificationArchive(args.runs_root, args.run_id, args.mode).create()
    archive.write_json("qualification-freeze.json", freeze)
    archive.write_json(
        "qualification-observations.json",
        observations,
    )
    archive.write_json("qualification-result.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
