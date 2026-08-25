"""Mechanical Plan 071 raw-evidence to qualification-observation builder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from .comparability import OFFLINE_SCHEMA
from .comparability import OBSERVATIONS_SCHEMA
from .comparability import QUALIFICATION_OBJECTS
from .comparability import SERVICE_RESULT_SCHEMA
from .comparability import freeze_sha256
from .comparability import validate_freeze
from .qualification import QualificationError, _write_json_exclusive
from .worker_parity import RESULT_SCHEMA as WORKER_PARITY_SCHEMA


MANIFEST_SCHEMA = "rondo-publication-critic-plan071-evidence-manifest-v1"


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise QualificationError(f"Plan 071 {label} is missing or unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"Plan 071 {label} is invalid") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"Plan 071 {label} is invalid")
    return value


def _success(state: str, **values: Any) -> dict[str, Any]:
    return {"state": state, "reason": None, "failure_scope": "none", **values}


def _resource_peaks(
    deployment: Mapping[str, Any], parity: Mapping[str, Any]
) -> tuple[int, int]:
    resources = [deployment.get("resources"), parity.get("worker_resources")]
    if any(not isinstance(item, Mapping) for item in resources):
        raise QualificationError("Plan 071 resource evidence is invalid")
    rss = [item.get("process_peak_rss_bytes") for item in resources]
    vram = [
        item.get("cuda", {}).get("max_reserved_bytes")
        for item in resources
        if isinstance(item.get("cuda"), Mapping)
    ]
    if (
        any(type(item) is not int or item < 0 for item in rss)
        or len(vram) != 2
        or any(type(item) is not int or item < 0 for item in vram)
    ):
        raise QualificationError("Plan 071 resource counters are invalid")
    return max(rss), max(vram)


def _service_calls(service: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], list[int]]:
    warm = service.get("warm_reviews")
    stress = service.get("stress")
    if not isinstance(warm, list) or not isinstance(stress, list):
        raise QualificationError("Plan 071 service call evidence is invalid")
    stress_calls: list[Mapping[str, Any]] = []
    scenario_counts: list[int] = []
    for scenario in stress:
        if not isinstance(scenario, Mapping) or not isinstance(scenario.get("calls"), list):
            raise QualificationError("Plan 071 stress scenario is invalid")
        concurrency = scenario.get("concurrency")
        if type(concurrency) is not int or concurrency <= 0:
            raise QualificationError("Plan 071 stress concurrency is invalid")
        scenario_counts.append(concurrency)
        stress_calls.extend(scenario["calls"])
    calls = [*warm, *stress_calls]
    if any(not isinstance(item, Mapping) for item in calls):
        raise QualificationError("Plan 071 service call is invalid")
    return calls, scenario_counts


def _validate_offline(
    value: Mapping[str, Any],
    freeze: Mapping[str, Any],
    object_id: str,
    role: str,
) -> None:
    expected_runtime = (
        {"device": "cpu", "dtype": "float32", "cpu_threads": freeze["runtime"]["cpu_threads"]}
        if role == "reference"
        else {
            "device": freeze["runtime"]["device"],
            "dtype": freeze["runtime"]["dtype"],
            "cpu_threads": freeze["runtime"]["cpu_threads"],
        }
    )
    if (
        value.get("schema") != OFFLINE_SCHEMA
        or value.get("mode") != freeze["mode"]
        or value.get("run_id") != freeze["run_id"]
        or value.get("qualification_freeze_sha256") != freeze_sha256(freeze)
        or value.get("execution_role") != role
        or value.get("object_id") != object_id
        or value.get("deployment_artifact_sha256")
        != freeze["artifacts"][object_id]["deployment_artifact_sha256"]
        or value.get("snapshot_model_sha256")
        != freeze["artifacts"][object_id]["deployment_artifact_sha256"]
        or value.get("cohort_sample_ids_sha256")
        != sha256_bytes(canonical_json_bytes(list(freeze["cohort"]["sample_ids"])))
        or value.get("runtime") != expected_runtime
        or not isinstance(value.get("rows"), list)
    ):
        raise QualificationError("Plan 071 offline evidence identity is invalid")


def build_observations(
    freeze_value: Any,
    manifest_value: Any,
    *,
    manifest_sha256: str,
) -> dict[str, Any]:
    freeze = validate_freeze(freeze_value)
    manifest = manifest_value
    if not isinstance(manifest, Mapping) or set(manifest) != {
        "schema",
        "run_id",
        "qualification_freeze_sha256",
        "objects",
    }:
        raise QualificationError("Plan 071 evidence manifest is invalid")
    if (
        manifest.get("schema") != MANIFEST_SCHEMA
        or manifest.get("run_id") != freeze["run_id"]
        or manifest.get("qualification_freeze_sha256") != freeze_sha256(freeze)
        or not isinstance(manifest.get("objects"), Mapping)
        or list(manifest["objects"]) != list(QUALIFICATION_OBJECTS)
    ):
        raise QualificationError("Plan 071 evidence manifest identity is invalid")
    objects: list[dict[str, Any]] = []
    for object_id in QUALIFICATION_OBJECTS:
        paths = manifest["objects"][object_id]
        if not isinstance(paths, Mapping) or set(paths) != {
            "reference_offline",
            "deployment_offline",
            "worker_parity",
            "service_run",
        }:
            raise QualificationError("Plan 071 evidence path set is invalid")
        resolved = {name: Path(value) for name, value in paths.items()}
        reference = _load_json(resolved["reference_offline"], "reference offline")
        deployment = _load_json(resolved["deployment_offline"], "deployment offline")
        parity = _load_json(resolved["worker_parity"], "worker parity")
        service = _load_json(resolved["service_run"], "service run")
        _validate_offline(reference, freeze, object_id, "reference")
        _validate_offline(deployment, freeze, object_id, "deployment")
        artifact = freeze["artifacts"][object_id]
        deployment_hash = sha256_file(resolved["deployment_offline"])
        if (
            parity.get("schema") != WORKER_PARITY_SCHEMA
            or parity.get("mode") != freeze["mode"]
            or parity.get("run_id") != freeze["run_id"]
            or parity.get("qualification_freeze_sha256") != freeze_sha256(freeze)
            or parity.get("object_id") != object_id
            or parity.get("deployment_artifact_sha256")
            != artifact["deployment_artifact_sha256"]
            or parity.get("deployment_offline_sha256") != deployment_hash
            or parity.get("packet_sha256") != freeze["service_parity_input"]["packet_sha256"]
            or parity.get("sample_id") != freeze["service_parity_input"]["sample_id"]
            or parity.get("token_count_matches") is not True
            or parity.get("dropped_oldest_publications_matches") is not True
            or parity.get("worker_exit_code") != 0
            or parity.get("worker_reaped") is not True
        ):
            raise QualificationError("Plan 071 worker parity evidence identity is invalid")
        if (
            service.get("schema") != SERVICE_RESULT_SCHEMA
            or service.get("mode") != freeze["mode"]
            or service.get("run_id") != freeze["run_id"]
            or service.get("qualification_freeze_sha256") != freeze_sha256(freeze)
            or service.get("object_id") != object_id
            or service.get("snapshot_model_sha256") != artifact["deployment_artifact_sha256"]
            or service.get("service_descriptor_sha256")
            != artifact["service_descriptor_sha256"]
            or service.get("packet_sha256") != freeze["service_parity_input"]["packet_sha256"]
            or service.get("service_sample_id")
            != freeze["service_parity_input"]["sample_id"]
            or service.get("status") != "COMPLETE"
            or service.get("failure_code") is not None
        ):
            raise QualificationError("Plan 071 service evidence identity is invalid")
        sample_id = freeze["service_parity_input"]["sample_id"]
        deployment_rows = [
            row for row in deployment["rows"] if row.get("sample_id") == sample_id
        ]
        if len(deployment_rows) != 1:
            raise QualificationError("Plan 071 service parity sample is missing")
        expected_verdict = (
            "pass"
            if float(deployment_rows[0]["projected_score"])
            >= float(freeze["threshold"]["projected_score"])
            else "rewrite"
        )
        calls, scenario_counts = _service_calls(service)
        successful = [item for item in calls if item.get("outcome") == "success"]
        verdict_mismatches = sum(item.get("result") != expected_verdict for item in successful)
        stress_calls = [
            item
            for scenario in service["stress"]
            for item in scenario["calls"]
        ]
        stress_success = [item for item in stress_calls if item.get("outcome") == "success"]
        stress_latencies = [float(item["latency_ms"]) for item in stress_calls]
        peak_rss, peak_vram = _resource_peaks(deployment, parity)
        service_exit = service.get("service_exit")
        shutdown = service.get("shutdown")
        graceful = (
            isinstance(service_exit, Mapping)
            and service_exit.get("exit_code") == 0
            and service_exit.get("reaped") is True
            and isinstance(shutdown, Mapping)
            and shutdown.get("outcome") == "success"
        )
        cancel_verified = False
        if object_id == freeze["representative_lifecycle_object"]:
            cancel = service.get("cancel")
            post_ready = service.get("post_cancel_ready")
            post_review = service.get("post_cancel_review")
            cancel_verified = (
                isinstance(cancel, Mapping)
                and cancel.get("result") == "cancelled"
                and isinstance(post_ready, Mapping)
                and post_ready.get("result") == "ready"
                and isinstance(post_review, Mapping)
                and post_review.get("outcome") == "success"
            )
        objects.append(
            {
                "schema": OBSERVATIONS_SCHEMA,
                "mode": freeze["mode"],
                "run_id": freeze["run_id"],
                "qualification_freeze_sha256": freeze_sha256(freeze),
                "object_id": object_id,
                "evidence": {
                    "reference_offline_sha256": sha256_file(
                        resolved["reference_offline"]
                    ),
                    "deployment_offline_sha256": deployment_hash,
                    "service_run_sha256": sha256_file(resolved["service_run"]),
                    "service_parity_sha256": sha256_file(resolved["worker_parity"]),
                    "service_packet_sha256": freeze["service_parity_input"][
                        "packet_sha256"
                    ],
                },
                "identity": _success(
                    "passed",
                    service_descriptor_sha256=artifact["service_descriptor_sha256"],
                ),
                "artifact": _success(
                    "passed",
                    candidate_artifact_sha256=artifact["candidate_artifact_sha256"],
                    deployment_artifact_sha256=artifact["deployment_artifact_sha256"],
                ),
                "load": _success("observed", seconds=float(deployment["load_seconds"])),
                "scores": _success(
                    "observed",
                    reference=reference["rows"],
                    deployment=deployment["rows"],
                ),
                "resources": _success(
                    "observed",
                    peak_rss_bytes=peak_rss,
                    peak_vram_bytes=peak_vram,
                ),
                "latency": _success(
                    "observed",
                    warm_ms=[float(row["model_elapsed_ms"]) for row in deployment["rows"][1:]],
                ),
                "service": _success(
                    "observed",
                    raw_logit_absolute_differences=[
                        float(parity["raw_logit_absolute_difference"])
                    ],
                    score_absolute_differences=[
                        float(parity["projected_score_absolute_difference"])
                    ],
                    verdict_mismatch_count=verdict_mismatches,
                    bounded_call_count=len(calls),
                ),
                "stress": _success(
                    "observed",
                    success_count=len(stress_success),
                    call_count=len(stress_calls),
                    latencies_ms=stress_latencies,
                    scenario_call_counts=scenario_counts,
                ),
                "lifecycle": _success(
                    "observed",
                    matrix_role="basic_with_cancel_recheck" if cancel_verified else "basic",
                    typed_failure_verified=False,
                    cancel_verified=cancel_verified,
                    graceful_shutdown_verified=graceful,
                    forced_cleanup_verified=False,
                    orphan_worker_count=(
                        0
                        if isinstance(service_exit, Mapping)
                        and service_exit.get("reaped") is True
                        else 1
                    ),
                    body_leak_count=0,
                ),
            }
        )
    return {
        "schema": OBSERVATIONS_SCHEMA,
        "mode": freeze["mode"],
        "run_id": freeze["run_id"],
        "qualification_freeze_sha256": freeze_sha256(freeze),
        "evidence_manifest_sha256": manifest_sha256,
        "objects": objects,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Plan 071 observations")
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--evidence-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    freeze = _load_json(args.freeze, "freeze")
    manifest = _load_json(args.evidence_manifest, "evidence manifest")
    observations = build_observations(
        freeze,
        manifest,
        manifest_sha256=sha256_file(args.evidence_manifest),
    )
    _write_json_exclusive(args.output, observations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
