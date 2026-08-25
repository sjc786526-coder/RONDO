"""Plan 071 cross-runtime comparability qualification.

This version keeps CPU FP32 to CUDA BF16 comparability separate from
same-deployment worker parity and from the product service verdict.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import copy
import json
import math
import os
from pathlib import Path
import re
import statistics
from typing import Any

from ..contract import REPO_ROOT
from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from ..scoring import project_logit
from .inference import PublicationCriticInference
from .qualification import FREEZE_SCHEMA as PLAN068_FREEZE_SCHEMA
from .qualification import OBSERVATIONS_SCHEMA as PLAN068_OBSERVATIONS_SCHEMA
from .qualification import QualificationError
from .qualification import _count
from .qualification import _dimension
from .qualification import _finite
from .qualification import _not_available
from .qualification import _object
from .qualification import _observed
from .qualification import _pair_direction_preservation
from .qualification import _pair_direction_rate
from .qualification import _ranking_concordance
from .qualification import _require_exact_keys
from .qualification import _score_rows
from .qualification import _verify_formal_source
from .qualification import _write_json_exclusive
from .qualification import evaluate_object as evaluate_plan068_object
from .qualification import validate_freeze as validate_plan068_freeze


FREEZE_SCHEMA = "rondo-publication-critic-plan071-comparability-freeze-v1"
OBSERVATIONS_SCHEMA = "rondo-publication-critic-plan071-observations-v1"
RESULT_SCHEMA = "rondo-publication-critic-plan071-comparability-result-v1"
OFFLINE_SCHEMA = "rondo-publication-critic-plan071-offline-scores-v1"
SERVICE_RESULT_SCHEMA = "rondo-publication-critic-plan071-service-run-v1"
QUALIFICATION_OBJECTS = ("base", "c1", "c3")
ALL_ARTIFACT_OBJECTS = ("base", "c1", "c2", "c3")
FORMAL_SAMPLE_IDS = (
    "pc-v1-cal-nc-pass",
    "pc-v1-cal-nc-rewrite",
    "pc-v1-cal-ni-pass",
    "pc-v1-cal-ni-rewrite",
    "pc-v1-cal-ec-pass",
    "pc-v1-cal-ec-rewrite",
    "pc-v1-cal-ei-pass",
    "pc-v1-cal-ei-rewrite",
    "pc-v1-meas-nc-a-pass",
    "pc-v1-meas-nc-a-rewrite",
    "pc-v1-meas-nc-b-pass",
    "pc-v1-meas-nc-b-rewrite",
    "pc-v1-meas-ni-a-pass",
    "pc-v1-meas-ni-a-rewrite",
    "pc-v1-meas-ni-b-pass",
    "pc-v1-meas-ni-b-rewrite",
    "pc-v1-meas-ec-a-pass",
    "pc-v1-meas-ec-a-rewrite",
    "pc-v1-meas-ec-b-pass",
    "pc-v1-meas-ec-b-rewrite",
    "pc-v1-meas-ei-a-pass",
    "pc-v1-meas-ei-a-rewrite",
    "pc-v1-meas-ei-b-pass",
    "pc-v1-meas-ei-b-rewrite",
)
TASK_TERMINALS = ("BASE_COMPARABILITY_GO", "BASE_NOT_COMPARABLE", "INCONCLUSIVE")
FORMAL_THRESHOLD_SOURCE = "plan054-calibration-threshold-v4"
FORMAL_THRESHOLD = 0.9350569011196121
FORMAL_REFERENCE_METHOD = "same-original-safetensors-cpu-float32-v1"
_RUN_ID = re.compile(
    r"plan071-(commissioning|formal)-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}\Z"
)
_METHOD = {
    "cross_runtime_raw": "absolute_raw_logit_cap_v1",
    "cross_runtime_projection": "stable_sigmoid_interval_from_raw_cap_v1",
    "temporary_verdict": "require_match_outside_reference_raw_guard_v1",
    "deployment_worker_parity": "same_runtime_absolute_drift_v1",
    "service_verdict": "exact_descriptor_threshold_v1",
    "lifecycle": "basic_shutdown_recheck_with_plan068_v3_matrix_unchanged_v1",
}
_GATE_KEYS = {
    "max_cross_runtime_raw_logit_absolute_drift",
    "max_projection_envelope_excess",
    "min_ranking_concordance",
    "reference_obvious_margin_floor",
    "min_obvious_margin_direction_agreement",
    "min_pair_direction_agreement",
    "max_stable_verdict_mismatches",
    "max_load_seconds",
    "max_peak_rss_bytes",
    "max_peak_vram_bytes",
    "max_warm_p95_latency_ms",
    "max_worker_score_absolute_drift",
    "max_worker_raw_logit_absolute_drift",
    "max_service_verdict_mismatches",
    "min_stress_success_rate",
    "max_stress_p95_latency_ms",
}


def freeze_sha256(freeze: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(freeze)))


def _plan068_compatibility_freeze(value: Mapping[str, Any]) -> dict[str, Any]:
    """Project shared fields through the strict Plan 068 validator.

    The projected freeze is used only to reuse the already-tested common
    identity, resource, stress, and lifecycle evaluator. Its score and service
    gates are deliberately non-deciding; Plan 071 applies those layers itself.
    """

    projected = copy.deepcopy(dict(value))
    projected["schema"] = PLAN068_FREEZE_SCHEMA
    projected["run_id"] = str(value["run_id"]).replace("plan071-", "plan068-", 1)
    projected["qualification_objects"] = list(ALL_ARTIFACT_OBJECTS)
    projected["representative_lifecycle_object"] = "c2"
    gates = value["gates"]
    projected["gates"] = {
        "max_raw_logit_absolute_drift": 1.0e9,
        "max_projected_absolute_drift": 1.0,
        "min_ranking_concordance": 0.0,
        "reference_obvious_margin_floor": gates["reference_obvious_margin_floor"],
        "min_obvious_margin_direction_agreement": 0.0,
        "min_pair_direction_agreement": 0.0,
        "max_verdict_mismatches": len(value["cohort"]["sample_ids"]),
        "max_load_seconds": gates["max_load_seconds"],
        "max_peak_rss_bytes": gates["max_peak_rss_bytes"],
        "max_peak_vram_bytes": gates["max_peak_vram_bytes"],
        "max_warm_p95_latency_ms": gates["max_warm_p95_latency_ms"],
        "max_service_score_absolute_drift": 1.0,
        "max_service_raw_logit_absolute_drift": 1.0e9,
        "max_service_verdict_mismatches": len(value["cohort"]["sample_ids"]),
        "min_stress_success_rate": gates["min_stress_success_rate"],
        "max_stress_p95_latency_ms": gates["max_stress_p95_latency_ms"],
    }
    projected.pop("comparability_method")
    return validate_plan068_freeze(projected)


def validate_freeze(value: Any) -> dict[str, Any]:
    freeze = _object(value, "Plan 071 comparability freeze")
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
            "comparability_method",
            "gates",
            "stress_call_counts",
            "representative_lifecycle_object",
        },
        "Plan 071 comparability freeze",
    )
    run_match = _RUN_ID.fullmatch(freeze.get("run_id", ""))
    if (
        freeze.get("schema") != FREEZE_SCHEMA
        or list(freeze.get("qualification_objects", [])) != list(QUALIFICATION_OBJECTS)
        or run_match is None
        or freeze.get("mode") not in {"commissioning", "formal"}
        or run_match.group(1) != freeze["mode"]
        or freeze.get("comparability_method") != _METHOD
        or freeze.get("representative_lifecycle_object") != "c1"
    ):
        raise QualificationError("Plan 071 comparability freeze identity is invalid")
    threshold = _object(freeze["threshold"], "Plan 071 threshold")
    threshold_score = _finite(threshold.get("projected_score"), "Plan 071 threshold")
    if not 0.0 < threshold_score < 1.0:
        raise QualificationError("Plan 071 threshold must be strictly inside (0,1)")
    artifacts = _object(freeze["artifacts"], "Plan 071 artifacts")
    if set(artifacts) != set(ALL_ARTIFACT_OBJECTS):
        raise QualificationError("Plan 071 artifact identity set is invalid")
    gates = _object(freeze["gates"], "Plan 071 gates")
    _require_exact_keys(gates, _GATE_KEYS, "Plan 071 gates")
    for name in _GATE_KEYS:
        _finite(gates[name], f"Plan 071 gate {name}", minimum=0.0)
    for name in (
        "min_ranking_concordance",
        "min_obvious_margin_direction_agreement",
        "min_pair_direction_agreement",
        "min_stress_success_rate",
    ):
        if float(gates[name]) > 1.0:
            raise QualificationError(f"Plan 071 gate {name} exceeds one")
    for name in ("max_stable_verdict_mismatches", "max_service_verdict_mismatches"):
        if type(gates[name]) is not int:
            raise QualificationError(f"Plan 071 gate {name} must be an integer")
    _plan068_compatibility_freeze(freeze)
    if freeze["mode"] == "formal":
        if tuple(freeze["cohort"]["sample_ids"]) != FORMAL_SAMPLE_IDS:
            raise QualificationError("Plan 071 formal cohort is not the frozen 24-sample order")
        if (
            threshold.get("source") != FORMAL_THRESHOLD_SOURCE
            or threshold_score != FORMAL_THRESHOLD
        ):
            raise QualificationError("Plan 071 formal threshold identity drifted")
        if freeze["reference_method"] != FORMAL_REFERENCE_METHOD:
            raise QualificationError("Plan 071 formal reference method drifted")
    return copy.deepcopy(dict(freeze))


def _cross_runtime_metrics(
    reference: Mapping[str, Mapping[str, float]],
    deployed: Mapping[str, Mapping[str, float]],
    sample_ids: Sequence[str],
    *,
    threshold: float,
    raw_cap: float,
    obvious_margin_floor: float,
) -> dict[str, Any]:
    threshold_raw = math.log(threshold / (1.0 - threshold))
    reference_scores = [reference[sample_id]["score"] for sample_id in sample_ids]
    deployed_scores = [deployed[sample_id]["score"] for sample_id in sample_ids]
    raw_drift = [
        abs(reference[sample_id]["raw_logit"] - deployed[sample_id]["raw_logit"])
        for sample_id in sample_ids
    ]
    projected_drift = [
        abs(reference[sample_id]["score"] - deployed[sample_id]["score"])
        for sample_id in sample_ids
    ]
    envelope_excess: list[float] = []
    near_threshold_ids: list[str] = []
    near_threshold_mismatches: list[str] = []
    stable_verdict_mismatches: list[str] = []
    for sample_id in sample_ids:
        reference_raw = reference[sample_id]["raw_logit"]
        deployed_score = deployed[sample_id]["score"]
        lower = project_logit(reference_raw - raw_cap)
        upper = project_logit(reference_raw + raw_cap)
        envelope_excess.append(max(lower - deployed_score, deployed_score - upper, 0.0))
        mismatch = (reference[sample_id]["score"] >= threshold) != (
            deployed_score >= threshold
        )
        if abs(reference_raw - threshold_raw) <= raw_cap:
            near_threshold_ids.append(sample_id)
            if mismatch:
                near_threshold_mismatches.append(sample_id)
        elif mismatch:
            stable_verdict_mismatches.append(sample_id)
    obvious = [
        (left, right, deployed_scores[left_index], deployed_scores[right_index])
        for left_index, left in enumerate(reference_scores)
        for right_index, right in enumerate(
            reference_scores[left_index + 1 :], left_index + 1
        )
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
        "max_projected_absolute_drift": max(projected_drift),
        "mean_projected_absolute_drift": statistics.fmean(projected_drift),
        "max_projection_envelope_excess": max(envelope_excess),
        "ranking_concordance": _ranking_concordance(reference_scores, deployed_scores),
        "obvious_margin_comparison_count": len(obvious),
        "obvious_margin_direction_agreement": obvious_agreement,
        "reference_pair_direction_agreement": _pair_direction_rate(reference),
        "deployment_pair_direction_agreement": _pair_direction_rate(deployed),
        "pair_direction_preservation": _pair_direction_preservation(reference, deployed),
        "temporary_verdict_mismatches": len(near_threshold_mismatches)
        + len(stable_verdict_mismatches),
        "near_threshold_sample_ids": near_threshold_ids,
        "near_threshold_verdict_mismatch_sample_ids": near_threshold_mismatches,
        "stable_verdict_mismatch_sample_ids": stable_verdict_mismatches,
        "threshold_raw_logit": threshold_raw,
        "threshold_guard_raw_logit_radius": raw_cap,
    }


def _compatibility_observation(
    observation: Mapping[str, Any],
    compat_freeze: Mapping[str, Any],
) -> dict[str, Any]:
    projected = copy.deepcopy(dict(observation))
    projected["schema"] = PLAN068_OBSERVATIONS_SCHEMA
    projected["run_id"] = compat_freeze["run_id"]
    projected["qualification_freeze_sha256"] = sha256_bytes(
        canonical_json_bytes(dict(compat_freeze))
    )
    lifecycle = projected.get("lifecycle")
    if isinstance(lifecycle, dict) and lifecycle.get("state") == "observed":
        lifecycle.update(
            {
                "matrix_role": "basic",
                "typed_failure_verified": False,
                "cancel_verified": False,
                "forced_cleanup_verified": False,
            }
        )
    return projected


def _split_service_metrics(
    metrics: dict[str, Any],
    gates: Mapping[str, Any],
) -> list[str]:
    service = metrics.pop("service", None)
    if service is None:
        return []
    if service["status"] != "OBSERVED":
        metrics["deployment_worker_parity"] = service
        metrics["service_verdict_parity"] = copy.deepcopy(service)
        return []
    value = service["value"]
    worker = {
        "max_raw_logit_absolute_drift": value["max_raw_logit_absolute_drift"],
        "max_score_absolute_drift": value["max_score_absolute_drift"],
    }
    verdict = {
        "verdict_mismatch_count": value["verdict_mismatch_count"],
        "bounded_call_count": value["bounded_call_count"],
    }
    metrics["deployment_worker_parity"] = _observed(worker)
    metrics["service_verdict_parity"] = _observed(verdict)
    failures: list[str] = []
    if (
        worker["max_raw_logit_absolute_drift"]
        > gates["max_worker_raw_logit_absolute_drift"]
        or worker["max_score_absolute_drift"] > gates["max_worker_score_absolute_drift"]
    ):
        failures.append("deployment_worker_parity_gate_failed")
    if (
        verdict["bounded_call_count"] == 0
        or verdict["verdict_mismatch_count"] > gates["max_service_verdict_mismatches"]
    ):
        failures.append("service_verdict_parity_gate_failed")
    return failures


def _affected_lifecycle_failures(metrics: Mapping[str, Any], object_id: str) -> list[str]:
    lifecycle = metrics.get("lifecycle")
    if not isinstance(lifecycle, Mapping) or lifecycle.get("status") != "OBSERVED":
        return []
    value = lifecycle["value"]
    failed = (
        value["graceful_shutdown_verified"] is not True
        or value["orphan_worker_count"] != 0
        or value["body_leak_count"] != 0
        or (object_id == "c1" and value["cancel_verified"] is not True)
    )
    return ["affected_lifecycle_gate_failed"] if failed else []


def evaluate_object(
    observation_value: Any,
    freeze: Mapping[str, Any],
    expected_freeze_sha256: str,
) -> dict[str, Any]:
    observation = _object(observation_value, "Plan 071 observation")
    if (
        observation.get("schema") != OBSERVATIONS_SCHEMA
        or observation.get("mode") != freeze["mode"]
        or observation.get("run_id") != freeze["run_id"]
        or observation.get("qualification_freeze_sha256") != expected_freeze_sha256
        or observation.get("object_id") not in QUALIFICATION_OBJECTS
    ):
        raise QualificationError("Plan 071 observation identity is invalid")
    compat_freeze = _plan068_compatibility_freeze(freeze)
    common = evaluate_plan068_object(
        _compatibility_observation(observation, compat_freeze),
        compat_freeze,
        sha256_bytes(canonical_json_bytes(dict(compat_freeze))),
    )
    metrics = common["metrics"]
    original_lifecycle = observation.get("lifecycle")
    if (
        "lifecycle" in metrics
        and metrics["lifecycle"]["status"] == "OBSERVED"
        and isinstance(original_lifecycle, Mapping)
        and original_lifecycle.get("state") == "observed"
    ):
        metrics["lifecycle"] = _observed(
            {
                name: original_lifecycle[name]
                for name in (
                    "matrix_role",
                    "typed_failure_verified",
                    "cancel_verified",
                    "graceful_shutdown_verified",
                    "forced_cleanup_verified",
                    "orphan_worker_count",
                    "body_leak_count",
                )
            }
        )
    score_dimension = _dimension(
        observation.get("scores"),
        "Plan 071 cross-runtime scores",
        {"reference", "deployment"},
        success_state="observed",
    )
    if score_dimension["state"] != "observed":
        if "scores" in common["metrics"]:
            common["metrics"]["cross_runtime"] = common["metrics"].pop("scores")
        return common
    reference = _score_rows(
        score_dimension["reference"], freeze["cohort"]["sample_ids"], "reference"
    )
    deployed = _score_rows(
        score_dimension["deployment"], freeze["cohort"]["sample_ids"], "deployment"
    )
    gates = freeze["gates"]
    cross = _cross_runtime_metrics(
        reference,
        deployed,
        freeze["cohort"]["sample_ids"],
        threshold=float(freeze["threshold"]["projected_score"]),
        raw_cap=float(gates["max_cross_runtime_raw_logit_absolute_drift"]),
        obvious_margin_floor=float(gates["reference_obvious_margin_floor"]),
    )
    metrics.pop("scores", None)
    metrics["cross_runtime"] = _observed(cross)
    failures = [
        name
        for name, failed in (
            (
                "cross_runtime_raw_logit_drift_gate_failed",
                cross["max_raw_logit_absolute_drift"]
                > gates["max_cross_runtime_raw_logit_absolute_drift"],
            ),
            (
                "cross_runtime_projection_envelope_gate_failed",
                cross["max_projection_envelope_excess"]
                > gates["max_projection_envelope_excess"],
            ),
            (
                "cross_runtime_ranking_gate_failed",
                cross["ranking_concordance"] < gates["min_ranking_concordance"],
            ),
            (
                "cross_runtime_obvious_direction_gate_failed",
                cross["obvious_margin_direction_agreement"] is None
                or cross["obvious_margin_direction_agreement"]
                < gates["min_obvious_margin_direction_agreement"],
            ),
            (
                "cross_runtime_pair_direction_gate_failed",
                cross["pair_direction_preservation"] < gates["min_pair_direction_agreement"],
            ),
            (
                "stable_temporary_verdict_parity_gate_failed",
                len(cross["stable_verdict_mismatch_sample_ids"])
                > gates["max_stable_verdict_mismatches"],
            ),
        )
        if failed
    ]
    failures.extend(_split_service_metrics(metrics, gates))
    failures.extend(_affected_lifecycle_failures(metrics, common["object_id"]))
    if common["conclusion"] == "INCONCLUSIVE":
        conclusion = "INCONCLUSIVE"
    elif failures or common["conclusion"] == "NOT_QUALIFIED":
        conclusion = "NOT_QUALIFIED"
    else:
        conclusion = "QUALIFIED"
    return {
        "object_id": common["object_id"],
        "conclusion": conclusion,
        "reasons": failures + [reason for reason in common["reasons"] if reason not in failures],
        "metrics": metrics,
    }


def evaluate_run(
    observations_value: Any,
    freeze_value: Any,
    *,
    mode: str,
    run_id: str,
) -> dict[str, Any]:
    freeze = validate_freeze(freeze_value)
    if freeze["mode"] != mode or freeze["run_id"] != run_id:
        raise QualificationError("Plan 071 run does not match the freeze")
    digest = freeze_sha256(freeze)
    observations = _object(observations_value, "Plan 071 observations")
    _require_exact_keys(
        observations,
        {
            "schema",
            "mode",
            "run_id",
            "qualification_freeze_sha256",
            "evidence_manifest_sha256",
            "objects",
        },
        "Plan 071 observations",
    )
    if (
        observations["schema"] != OBSERVATIONS_SCHEMA
        or observations["mode"] != mode
        or observations["run_id"] != run_id
        or observations["qualification_freeze_sha256"] != digest
        or not isinstance(observations["evidence_manifest_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", observations["evidence_manifest_sha256"])
        is None
        or not isinstance(observations["objects"], list)
    ):
        raise QualificationError("Plan 071 observations identity is invalid")
    results = [evaluate_object(item, freeze, digest) for item in observations["objects"]]
    object_ids = [item["object_id"] for item in results]
    expected = list(QUALIFICATION_OBJECTS) if mode == "formal" else object_ids
    if len(set(object_ids)) != len(object_ids) or object_ids != expected:
        raise QualificationError("Plan 071 observation object order is invalid")
    conclusions = {item["object_id"]: item["conclusion"] for item in results}
    anchor_qualified = any(conclusions.get(item) == "QUALIFIED" for item in ("c1", "c3"))
    if mode != "formal":
        terminal = "INCONCLUSIVE"
    elif conclusions.get("base") == "QUALIFIED" and anchor_qualified:
        terminal = "BASE_COMPARABILITY_GO"
    elif conclusions.get("base") == "INCONCLUSIVE" or (
        conclusions.get("base") == "QUALIFIED"
        and not anchor_qualified
        and any(conclusions.get(item) == "INCONCLUSIVE" for item in ("c1", "c3"))
    ):
        terminal = "INCONCLUSIVE"
    else:
        terminal = "BASE_NOT_COMPARABLE"
    if terminal not in TASK_TERMINALS:
        raise AssertionError("unreachable Plan 071 terminal")
    return {
        "schema": RESULT_SCHEMA,
        "mode": mode,
        "run_id": run_id,
        "qualification_freeze_sha256": digest,
        "observations_sha256": sha256_bytes(canonical_json_bytes(dict(observations))),
        "evidence_manifest_sha256": observations["evidence_manifest_sha256"],
        "objects": results,
        "task_terminal": terminal,
        "m3_c2_prerequisite_satisfied": terminal == "BASE_COMPARABILITY_GO",
        "c2_historical_conclusion": "NOT_QUALIFIED",
        "c2_requalified": False,
        "scope_note": "base_comparability_only_no_ranking_or_final_threshold",
    }


def _offline(args: argparse.Namespace) -> int:
    freeze = validate_freeze(json.loads(args.freeze.read_bytes()))
    digest = freeze_sha256(freeze)
    if list(args.sample_id) != list(freeze["cohort"]["sample_ids"]):
        raise QualificationError("Plan 071 offline cohort does not match the freeze")
    artifact_sha256 = sha256_file(args.snapshot / "model.safetensors")
    if artifact_sha256 != freeze["artifacts"][args.object_id]["deployment_artifact_sha256"]:
        raise QualificationError("Plan 071 offline artifact does not match the freeze")
    runtime = freeze["runtime"]
    expected_runtime = (
        ("cpu", "float32", runtime["cpu_threads"])
        if args.execution_role == "reference"
        else (runtime["device"], runtime["dtype"], runtime["cpu_threads"])
    )
    if (args.device, args.dtype, args.cpu_threads) != expected_runtime:
        raise QualificationError("Plan 071 offline runtime does not match its frozen role")
    inference = PublicationCriticInference(
        args.snapshot,
        repo_root=args.repo_root,
        device=args.device,
        dtype=args.dtype,
        cpu_threads=args.cpu_threads,
    )
    inference.load()
    output = {
        "schema": OFFLINE_SCHEMA,
        "mode": freeze["mode"],
        "run_id": freeze["run_id"],
        "qualification_freeze_sha256": digest,
        "execution_role": args.execution_role,
        "object_id": args.object_id,
        "deployment_artifact_sha256": freeze["artifacts"][args.object_id][
            "deployment_artifact_sha256"
        ],
        "snapshot_model_sha256": artifact_sha256,
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
    _write_json_exclusive(args.output, output)
    return 0


def _archive(runs_root: Path, run_id: str, freeze: Any, observations: Any, result: Any) -> None:
    runs_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise QualificationError("Plan 071 archive root is unsafe")
    path = runs_root / run_id
    try:
        path.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise QualificationError("Plan 071 archive already exists") from exc
    try:
        for name, value in (
            ("qualification-freeze.json", freeze),
            ("qualification-observations.json", observations),
            ("qualification-result.json", result),
        ):
            _write_json_exclusive(path / name, value)
    except BaseException:
        for child in path.iterdir():
            if child.is_file() and not child.is_symlink():
                child.unlink()
        path.rmdir()
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Plan 071 comparability qualification")
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--mode", choices=("commissioning", "formal"), required=True)
    evaluate.add_argument("--freeze", type=Path, required=True)
    evaluate.add_argument("--observations", type=Path, required=True)
    evaluate.add_argument("--runs-root", type=Path, required=True)
    evaluate.add_argument("--run-id", required=True)
    offline = subparsers.add_parser("offline")
    offline.add_argument("--object-id", choices=QUALIFICATION_OBJECTS, required=True)
    offline.add_argument("--execution-role", choices=("reference", "deployment"), required=True)
    offline.add_argument("--freeze", type=Path, required=True)
    offline.add_argument("--snapshot", type=Path, required=True)
    offline.add_argument("--device", choices=("cpu", "cuda"), required=True)
    offline.add_argument("--dtype", choices=("float32", "bfloat16"), required=True)
    offline.add_argument("--cpu-threads", type=int, required=True)
    offline.add_argument("--sample-id", action="append", required=True)
    offline.add_argument("--output", type=Path, required=True)
    offline.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "offline":
        return _offline(args)
    freeze = validate_freeze(json.loads(args.freeze.read_bytes()))
    if args.mode == "formal":
        _verify_formal_source(REPO_ROOT, freeze)
    observations = json.loads(args.observations.read_bytes())
    result = evaluate_run(observations, freeze, mode=args.mode, run_id=args.run_id)
    _archive(args.runs_root, args.run_id, freeze, observations, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
