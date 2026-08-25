"""Thin Plan 079 validation scorer, aggregator, and independent recomputation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from functools import partial
import math
from pathlib import Path
import re
import statistics
import time
from typing import Any

from ..full_model_training.contract import (
    canonical_json_bytes,
    read_json,
    sha256_bytes,
    sha256_file,
)
from ..full_model_training.plan066_bundle import verify_plan066_bundle
from ..identity import canonical_json_bytes as publication_canonical_json_bytes
from ..local_deployment.inference import PublicationCriticInference
from ..scoring import project_logit
from ..selection.metrics import (
    build_labeled_rows,
    candidate_metrics,
    quality_gate_failures,
    select_threshold,
)
from ..selection.release import (
    build_split_release,
    release_sha256,
    validate_release,
)
from .archive import BaseQualityArchive
from .backend import Plan079CloudBackend
from .contract import (
    BaseQualityError,
    QUALITY_FLOORS,
    RESULT_SCHEMA,
    RUNTIME_CONTRACT,
    SCORES_SCHEMA,
    run_spec_sha256,
    validate_run_spec,
    validate_runtime_facts,
)
from .snapshot import verify_snapshot
from .source import verify_source_archive_tree
from .runtime import runtime_receipt_sha256, verify_runtime_environment

_ATTEMPT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")
_FINAL_EVIDENCE_SCHEMA = "rondo-publication-critic-plan079-final-evidence-v1"


def prepare_validation_release(
    bundle_root: Path, repo_root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the same physically unseen-free validation release as Plan 073."""

    try:
        bundle = verify_plan066_bundle(bundle_root)
        release = build_split_release(
            Path("/unseen-test-is-physically-unavailable"),
            "validation",
            repo_root=repo_root,
            bundle_root=bundle_root,
        )
    except Exception as exc:  # noqa: BLE001 - normalize cross-facility errors
        raise BaseQualityError("validation_release_failed") from exc
    pair_counts = {
        kind: sum(row["kind"] == kind for row in release["pairs"])
        for kind in ("boundary", "within_pass")
    }
    if (
        len(release["items"]) != 55
        or pair_counts != {"boundary": 19, "within_pass": 7}
        or bundle.get("unseen_test_rows") != 0
    ):
        raise BaseQualityError("validation_release_counts_invalid")
    return release, bundle


def validate_score_row(value: Any) -> dict[str, Any]:
    keys = {
        "candidate_id",
        "raw_logit",
        "score",
        "token_count",
        "dropped_oldest_publications",
        "model_elapsed_ms",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BaseQualityError("score_row_fields_invalid")
    if not isinstance(value.get("candidate_id"), str) or not value["candidate_id"]:
        raise BaseQualityError("score_row_identity_invalid")
    for name in ("raw_logit", "score", "model_elapsed_ms"):
        item = value.get(name)
        if (
            not isinstance(item, (int, float))
            or isinstance(item, bool)
            or not math.isfinite(float(item))
        ):
            raise BaseQualityError("score_row_number_invalid")
    if not 0.0 <= float(value["score"]) <= 1.0 or float(value["model_elapsed_ms"]) < 0:
        raise BaseQualityError("score_row_number_invalid")
    if not math.isclose(
        project_logit(float(value["raw_logit"])),
        float(value["score"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise BaseQualityError("score_row_projection_mismatch")
    for name in ("token_count", "dropped_oldest_publications"):
        if type(value.get(name)) is not int or value[name] < 0:
            raise BaseQualityError("score_row_count_invalid")
    if value["token_count"] > RUNTIME_CONTRACT["context_window"]:
        raise BaseQualityError("score_row_token_window_invalid")
    return dict(value)


def build_scores_document(
    spec: Mapping[str, Any],
    release: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    typed_failures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validated_rows = [validate_score_row(row) for row in rows]
    failures: list[dict[str, str]] = []
    for failure in typed_failures:
        if (
            not isinstance(failure, Mapping)
            or set(failure) != {"candidate_id", "failure_kind", "failure_code"}
            or not all(
                isinstance(failure.get(name), str) and failure[name] for name in failure
            )
        ):
            raise BaseQualityError("typed_failure_invalid")
        failures.append(dict(failure))
    return {
        "schema": SCORES_SCHEMA,
        "run_spec_sha256": run_spec_sha256(spec),
        "release_sha256": release_sha256(release),
        "rows": validated_rows,
        "typed_failures": failures,
    }


def validate_scores_document(
    value: Any,
    spec: Mapping[str, Any],
    release: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "run_spec_sha256",
        "release_sha256",
        "rows",
        "typed_failures",
    }:
        raise BaseQualityError("scores_fields_invalid")
    if (
        value.get("schema") != SCORES_SCHEMA
        or value.get("run_spec_sha256") != run_spec_sha256(spec)
        or value.get("release_sha256") != release_sha256(release)
        or not isinstance(value.get("rows"), list)
        or not isinstance(value.get("typed_failures"), list)
    ):
        raise BaseQualityError("scores_identity_invalid")
    return build_scores_document(spec, release, value["rows"], value["typed_failures"])


def _distribution(values: Sequence[int]) -> dict[str, float | int | None]:
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


def recompute_result(
    spec_value: Any,
    release_value: Any,
    scores_value: Any,
    runtime_value: Any,
) -> dict[str, Any]:
    """Independently reconstruct the terminal and every quality metric."""

    spec = validate_run_spec(spec_value)
    try:
        release = validate_release(release_value)
    except Exception as exc:  # noqa: BLE001
        raise BaseQualityError("release_invalid") from exc
    if (
        release["split"] != "validation"
        or release_sha256(release) != spec["input"]["release_sha256"]
    ):
        raise BaseQualityError("release_identity_mismatch")
    scores = validate_scores_document(scores_value, spec, release)
    runtime = validate_runtime_facts(runtime_value)
    if runtime["gpu_name"] != spec["cloud"]["gpu_model"]:
        raise BaseQualityError("runtime_gpu_identity_mismatch")
    rows = scores["rows"]
    failures = scores["typed_failures"]
    expected_ids = [str(item["candidate_id"]) for item in release["items"]]
    observed_ids = [str(row["candidate_id"]) for row in rows]
    if runtime["scored_count"] != len(rows) or runtime["typed_failure_count"] != len(
        failures
    ):
        raise BaseQualityError("runtime_score_counts_mismatch")
    full = (
        not failures
        and observed_ids == expected_ids
        and runtime["scored_count"] == 55
        and runtime["typed_failure_count"] == 0
    )
    search: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    gate_failures: list[str] = []
    if full:
        try:
            labeled = build_labeled_rows(
                release,
                {
                    str(row["candidate_id"]): {
                        "score": float(row["score"]),
                        "raw_logit": float(row["raw_logit"]),
                    }
                    for row in rows
                },
            )
            search = select_threshold(labeled, QUALITY_FLOORS)
            metrics = candidate_metrics(release, labeled, search["threshold"])
            gate_failures = quality_gate_failures(search, metrics, 0, QUALITY_FLOORS)
        except Exception as exc:  # noqa: BLE001
            raise BaseQualityError("quality_recompute_failed") from exc
        if spec["mode"] == "commissioning":
            terminal = "COMMISSIONING_COMPLETE"
        else:
            terminal = (
                "4B_BASE_QUALITY_GO" if not gate_failures else "4B_BASE_QUALITY_NO_GO"
            )
    else:
        terminal = "INCONCLUSIVE"
        gate_failures = ["formal_score_cohort_incomplete"]

    return {
        "schema": RESULT_SCHEMA,
        "terminal": terminal,
        "valid_full_quality_run": full,
        "run_spec_sha256": run_spec_sha256(spec),
        "release_sha256": release_sha256(release),
        "scores_sha256": sha256_bytes(canonical_json_bytes(scores)),
        "quality_floors": dict(QUALITY_FLOORS),
        "gate_failures": gate_failures,
        "threshold_search": search,
        "metrics": metrics,
        "tokenization": {
            "token_count": _distribution([int(row["token_count"]) for row in rows]),
            "dropped_oldest_publications": _distribution(
                [int(row["dropped_oldest_publications"]) for row in rows]
            ),
            "rows_with_omission": sum(
                int(row["dropped_oldest_publications"]) > 0 for row in rows
            ),
        },
        "runtime": runtime,
    }


def validate_result(
    value: Any,
    spec: Mapping[str, Any],
    release: Mapping[str, Any],
    scores: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    recomputed = recompute_result(spec, release, scores, runtime)
    if not isinstance(value, Mapping) or publication_canonical_json_bytes(
        dict(value)
    ) != publication_canonical_json_bytes(recomputed):
        raise BaseQualityError("result_recompute_mismatch")
    return recomputed


def build_commissioning_binding(
    spec_value: Any,
    release_value: Any,
    scores_value: Any,
    runtime_value: Any,
    result_value: Any,
) -> dict[str, str]:
    """Validate one completed commissioning run and bind its evidence."""

    spec = validate_run_spec(spec_value)
    if spec["mode"] != "commissioning":
        raise BaseQualityError("formal_qualification_mode_invalid")
    release = validate_release(release_value)
    scores = validate_scores_document(scores_value, spec, release)
    runtime = validate_runtime_facts(runtime_value)
    result = validate_result(result_value, spec, release, scores, runtime)
    if (
        result["terminal"] != "COMMISSIONING_COMPLETE"
        or result["valid_full_quality_run"] is not True
        or runtime["scored_count"] != 55
        or runtime["typed_failure_count"] != 0
    ):
        raise BaseQualityError("formal_commissioning_not_complete")
    return {
        "run_id": spec["run_id"],
        "run_spec_sha256": run_spec_sha256(spec),
        "scores_sha256": sha256_bytes(canonical_json_bytes(scores)),
        "runtime_sha256": sha256_bytes(canonical_json_bytes(runtime)),
        "result_sha256": sha256_bytes(canonical_json_bytes(result)),
    }


def validate_formal_commissioning(
    formal_spec_value: Any,
    formal_release_value: Any,
    commissioning_spec_value: Any,
    commissioning_release_value: Any,
    commissioning_scores_value: Any,
    commissioning_runtime_value: Any,
    commissioning_result_value: Any,
) -> dict[str, str]:
    """Require formal to preserve every result-related commissioning identity."""

    formal = validate_run_spec(formal_spec_value)
    if formal["mode"] != "formal":
        raise BaseQualityError("formal_qualification_target_mode_invalid")
    formal_release = validate_release(formal_release_value)
    commissioning_spec = validate_run_spec(commissioning_spec_value)
    commissioning_release = validate_release(commissioning_release_value)
    binding = build_commissioning_binding(
        commissioning_spec,
        commissioning_release,
        commissioning_scores_value,
        commissioning_runtime_value,
        commissioning_result_value,
    )
    if formal["commissioning"] != binding:
        raise BaseQualityError("formal_commissioning_binding_mismatch")
    if publication_canonical_json_bytes(formal_release) != (
        publication_canonical_json_bytes(commissioning_release)
    ):
        raise BaseQualityError("formal_commissioning_release_mismatch")
    for name in ("source", "model", "input", "runtime", "quality_floors"):
        if formal[name] != commissioning_spec[name]:
            raise BaseQualityError(f"formal_commissioning_{name}_mismatch")
    for name in (
        "network_volume_id",
        "data_center_id",
        "gpu_model",
        "container_image",
        "cuda_host_version",
    ):
        if formal["cloud"][name] != commissioning_spec["cloud"][name]:
            raise BaseQualityError("formal_commissioning_cloud_mismatch")
    return binding


def run_evaluation(
    *,
    spec_value: Any,
    release_value: Any,
    snapshot: Path,
    model_lock_path: Path,
    source_archive: Path,
    environment_lock: Path,
    runtime_receipt_path: Path,
    dependency_freeze: Path,
    image_id: str,
    bundle_root: Path,
    runs_root: Path,
    repo_root: Path,
    attempt_id: str,
    commissioning_evidence: tuple[Any, Any, Any, Any, Any] | None = None,
    inference_factory: Callable[..., Any] = PublicationCriticInference,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Score once; commissioning resumes only exact prior successful rows."""

    spec = validate_run_spec(spec_value)
    if _ATTEMPT_ID.fullmatch(attempt_id) is None:
        raise BaseQualityError("attempt_id_invalid")
    release = validate_release(release_value)
    if release_sha256(release) != spec["input"]["release_sha256"]:
        raise BaseQualityError("release_identity_mismatch")
    receipt = verify_snapshot(snapshot, model_lock_path)
    if (
        receipt["snapshot_content_sha256"] != spec["model"]["snapshot_content_sha256"]
        or sha256_bytes(canonical_json_bytes(receipt))
        != spec["model"]["snapshot_receipt_sha256"]
        or receipt["model_lock_sha256"] != spec["model"]["model_lock_sha256"]
    ):
        raise BaseQualityError("snapshot_identity_mismatch")
    if (
        sha256_file(source_archive) != spec["source"]["source_archive_sha256"]
        or sha256_file(environment_lock) != spec["source"]["environment_lock_sha256"]
    ):
        raise BaseQualityError("source_identity_mismatch")
    verify_source_archive_tree(source_archive, repo_root, exact_tree=True)
    expected_release, bundle = prepare_validation_release(bundle_root, repo_root)
    if bundle["bundle_manifest_sha256"] != spec["input"]["bundle_manifest_sha256"]:
        raise BaseQualityError("validation_bundle_identity_mismatch")
    if publication_canonical_json_bytes(release) != publication_canonical_json_bytes(
        expected_release
    ):
        raise BaseQualityError("validation_release_bundle_mismatch")
    if spec["mode"] == "formal":
        if commissioning_evidence is None:
            raise BaseQualityError("formal_commissioning_evidence_missing")
        validate_formal_commissioning(
            spec,
            release,
            *commissioning_evidence,
        )
    elif commissioning_evidence is not None:
        raise BaseQualityError("commissioning_run_evidence_unexpected")
    try:
        runtime_receipt = read_json(runtime_receipt_path)
    except Exception as exc:  # noqa: BLE001 - normalize receipt parsing
        raise BaseQualityError("runtime_receipt_invalid") from exc
    if (
        runtime_receipt_sha256(runtime_receipt)
        != spec["source"]["runtime_receipt_sha256"]
    ):
        raise BaseQualityError("runtime_receipt_identity_mismatch")
    runtime_receipt = verify_runtime_environment(
        runtime_receipt,
        image_id=image_id,
        dependency_freeze=dependency_freeze,
        environment_lock=environment_lock,
    )
    if (
        runtime_receipt["image_id"] != spec["cloud"]["container_image"]
        or runtime_receipt["cuda_host_version"] != spec["cloud"]["cuda_host_version"]
        or runtime_receipt["gpu_name"] != spec["cloud"]["gpu_model"]
    ):
        raise BaseQualityError("runtime_receipt_cloud_identity_mismatch")
    archive = BaseQualityArchive(runs_root, spec["run_id"], spec["mode"])
    archive.require_formal_unclaimed()
    archive.create()
    archive.bind_json("run-spec.json", spec)
    archive.bind_json("validation-release.json", release)

    final_evidence = archive.load_json("final-evidence.json")
    final_names = ("scores.json", "runtime.json", "result.json")
    if final_evidence is not None:
        if set(final_evidence) != {"schema", "scores", "runtime", "result"} or (
            final_evidence.get("schema") != _FINAL_EVIDENCE_SCHEMA
        ):
            raise BaseQualityError("run_final_evidence_invalid")
        recovered_scores = validate_scores_document(
            final_evidence["scores"], spec, release
        )
        recovered_runtime = validate_runtime_facts(final_evidence["runtime"])
        recovered_result = validate_result(
            final_evidence["result"],
            spec,
            release,
            recovered_scores,
            recovered_runtime,
        )
        for name, value in zip(
            final_names,
            (recovered_scores, recovered_runtime, recovered_result),
            strict=True,
        ):
            archive.bind_json(name, value)
        return recovered_scores, recovered_runtime, recovered_result
    if any(archive.load_json(name) is not None for name in final_names):
        raise BaseQualityError("run_finalization_partial_without_evidence")

    items = release["items"]
    rows: list[dict[str, Any]] = []
    pending: list[Mapping[str, Any]] = []
    for item in items:
        prior = archive.load_score(str(item["candidate_id"]))
        if prior is None:
            pending.append(item)
        elif spec["mode"] != "commissioning":
            raise BaseQualityError("formal_namespace_not_empty")
        else:
            rows.append(validate_score_row(prior))

    started = time.perf_counter()
    inference: Any | None = None
    inference_loaded = False
    typed_failures: list[dict[str, str]] = []
    if pending or (spec["mode"] == "commissioning" and len(rows) == len(items)):
        backend_factory = partial(Plan079CloudBackend, model_lock_path=model_lock_path)
        inference = inference_factory(
            snapshot,
            repo_root=repo_root,
            device="cuda",
            dtype="bfloat16",
            cpu_threads=spec["runtime"]["cpu_threads"],
            backend_factory=backend_factory,
        )
        current_candidate = "model_load"
        try:
            inference.load()
            inference_loaded = True
            for item in pending:
                candidate_id = str(item["candidate_id"])
                current_candidate = candidate_id
                result = inference.score_packet(item["packet"], sample_id=candidate_id)
                row = validate_score_row(
                    {
                        "candidate_id": candidate_id,
                        "raw_logit": result.raw_logit,
                        "score": result.projected_score,
                        "token_count": result.token_count,
                        "dropped_oldest_publications": result.dropped_oldest_publications,
                        "model_elapsed_ms": result.model_elapsed_ms,
                    }
                )
                archive.write_score(candidate_id, row)
                rows.append(row)
        except Exception as exc:  # noqa: BLE001 - record only type/code, never body
            typed_failures.append(
                {
                    "candidate_id": current_candidate,
                    "failure_kind": type(exc).__name__,
                    "failure_code": getattr(exc, "code", "model_runtime_failure"),
                }
            )
            archive.write_json(
                f"attempt-{attempt_id}.json",
                {
                    "status": "incomplete",
                    "scored_count": len(rows),
                    "typed_failures": typed_failures,
                },
            )
            if spec["mode"] == "commissioning":
                raise BaseQualityError("commissioning_incomplete") from exc

    by_id = {str(row["candidate_id"]): row for row in rows}
    ordered = [
        by_id[str(item["candidate_id"])]
        for item in items
        if str(item["candidate_id"]) in by_id
    ]
    resource = (
        inference.resource_snapshot()
        if inference_loaded
        else {
            "process_peak_rss_bytes": 0,
            "cuda": {"max_allocated_bytes": 0, "max_reserved_bytes": 0},
        }
    )
    cloud = (
        inference.backend.cloud_runtime_snapshot()
        if inference_loaded
        else {
            "torch_version": "resume-no-load",
            "transformers_version": "resume-no-load",
            "cuda_runtime_version": "resume-no-load",
            "gpu_name": spec["cloud"]["gpu_model"],
            "gpu_capability": "resume-no-load",
        }
    )
    warm = sorted(
        float(row["model_elapsed_ms"])
        for row in ordered[RUNTIME_CONTRACT["warmup_items"] :]
    )
    p95 = warm[max(0, math.ceil(0.95 * len(warm)) - 1)] if warm else 0.0
    runtime = validate_runtime_facts(
        {
            "load_seconds": float(inference.load_seconds) if inference_loaded else 0.0,
            "warm_p95_latency_ms": p95,
            "wall_seconds": time.perf_counter() - started,
            "peak_rss_bytes": int(resource["process_peak_rss_bytes"]),
            "peak_vram_allocated_bytes": int(
                (resource.get("cuda") or {}).get("max_allocated_bytes", 0)
            ),
            "peak_vram_reserved_bytes": int(
                (resource.get("cuda") or {}).get("max_reserved_bytes", 0)
            ),
            "scored_count": len(ordered),
            "typed_failure_count": len(typed_failures),
            **cloud,
        }
    )
    scores = build_scores_document(spec, release, ordered, typed_failures)
    result = recompute_result(spec, release, scores, runtime)
    archive.bind_json(
        "final-evidence.json",
        {
            "schema": _FINAL_EVIDENCE_SCHEMA,
            "scores": scores,
            "runtime": runtime,
            "result": result,
        },
    )
    archive.bind_json("scores.json", scores)
    archive.bind_json("runtime.json", runtime)
    archive.bind_json("result.json", result)
    if spec["mode"] == "formal" and result["valid_full_quality_run"] is True:
        archive.claim_formal_result(result)
    return scores, runtime, result
