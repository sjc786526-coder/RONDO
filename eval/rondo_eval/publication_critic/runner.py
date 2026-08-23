"""Bounded Plan 054 census, calibration and measurement runner.

The runner deliberately has three explicit phases.  Token census may run
without loading model weights.  Calibration and measurement load the exact
checkpoint only while the process is supervised by the repository watchdog.
Measurement additionally requires a committed freeze document and never uses
measurement labels to derive its threshold.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence

from .archive import RunArchive
from .backend import SkyworkBackend, body_free_exception
from .boundaries import build_token_boundary_packets
from .contract import REPO_ROOT, load_fixed_input_contract, load_sample_corpus
from .identity import canonical_json_bytes, load_json, sha256_bytes, sha256_file
from .render import ADOPTED_CONTEXT_WINDOW
from .scoring import derive_temporary_threshold, summarize_measurement
from .tokenization import ExactTokenizer


MODEL_REPOSITORY = "Skywork/Skywork-Reward-V2-Qwen3-1.7B"
MODEL_REVISION = "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc"
MODEL_WEIGHT_SHA256 = "117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9"
ASSET_LOCK_SCHEMA = "rondo-publication-critic-skywork-assets-v1"
FREEZE_SCHEMA = "rondo-publication-critic-measurement-freeze-v3"
RESULT_SCHEMA = "rondo-publication-critic-baseline-result-v3"
CALIBRATION_SCHEMA = "rondo-publication-critic-calibration-result-v2"
TOKEN_CENSUS_SCHEMA = "rondo-publication-critic-token-census-v2"
PARITY_ABSOLUTE_TOLERANCE = 1e-4
FROZEN_DEVICE = "cpu"
FROZEN_DTYPE = "float32"
FROZEN_CPU_THREADS = 4
FROZEN_BATCH_SIZE = 4
MEASUREMENT_METRICS = (
    "valid_and_failed_count",
    "raw_and_projected_score_distribution",
    "confusion_and_false_pass_false_rewrite",
    "accuracy_and_balanced_accuracy",
    "roc_auc",
    "publication_class_metrics",
    "declared_error_slices",
    "atomic_boundary_pair_ranking",
    "token_distribution",
    "forward_latency_p50_p95",
    "wall_time_model_load_and_peak_memory",
)
DECLARED_SLICES = (
    "new_event",
    "existing_event",
    "completed",
    "incomplete",
    "continuity_available",
    "continuity_unavailable",
    "freshness_known_stale",
    "evidence_count_omitted",
    "handoff_empty",
    "unicode",
)
_MEASUREMENT_FREEZE_RELATIVE = Path(
    "eval/manifests/publication-critic/measurement-freeze-v3.json"
)

_INPUT_FILES = (
    "eval/environments/publication-critic-plan054/pyproject.toml",
    "eval/environments/publication-critic-plan054/uv.lock",
    "eval/fixtures/publication-critic-v1/packets.jsonl",
    "eval/fixtures/publication-critic-v1/annotations.jsonl",
    "eval/templates/publication-critic/input-contract-v1.md",
    "eval/templates/publication-critic/qualification-rubric-v1.md",
    "eval/templates/publication-critic/product-packet-limits-v1.json",
    "eval/templates/publication-critic/render-contract-v2.json",
    "eval/templates/publication-critic/temporary-threshold-rule-v1.json",
)
_IMPLEMENTATION_FILES = (
    "eval/rondo_eval/publication_critic/archive.py",
    "eval/rondo_eval/publication_critic/backend.py",
    "eval/rondo_eval/publication_critic/boundaries.py",
    "eval/rondo_eval/publication_critic/contract.py",
    "eval/rondo_eval/publication_critic/identity.py",
    "eval/rondo_eval/publication_critic/render.py",
    "eval/rondo_eval/publication_critic/runner.py",
    "eval/rondo_eval/publication_critic/scoring.py",
    "eval/rondo_eval/publication_critic/tokenization.py",
)


class RunnerError(RuntimeError):
    """A fail-closed Plan 054 runner or freeze error."""


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise RunnerError(f"measurement {label} keys drifted")


def _frozen_runtime_identity() -> dict[str, Any]:
    return {
        "backend_class": "Qwen3ForSequenceClassification",
        "output_shape": ["batch", 1],
        "tensor_index": "logits[:,0]",
        "pooling": "last_non_pad_token",
        "raw_semantics": "unbounded_reward_logit_higher_is_better",
        "device": FROZEN_DEVICE,
        "dtype": FROZEN_DTYPE,
        "eval_mode": True,
        "inference_mode": True,
        "cpu_threads": FROZEN_CPU_THREADS,
        "batch_size": FROZEN_BATCH_SIZE,
        "padding_side": "right",
        "padding_counterfactual": "left",
        "padding_id": 151654,
        "attention_mask": "one_for_content_zero_for_padding",
        "parity_absolute_tolerance": PARITY_ABSOLUTE_TOLERANCE,
        "parity_coverage": "every_scored_row_single_repeat_standard_right_standard_left_alternate_right",
        "chat_template": "immutable_tokenizer_chat_template",
        "add_generation_prompt": False,
        "add_special_tokens_after_chat_template": False,
        "bos_token_id": None,
        "eos_token_id": 151645,
    }


def _validate_frozen_runtime_args(args: argparse.Namespace) -> None:
    observed = {
        "device": args.device,
        "dtype": args.dtype,
        "cpu_threads": args.cpu_threads,
        "batch_size": args.batch_size,
    }
    expected = {
        "device": FROZEN_DEVICE,
        "dtype": FROZEN_DTYPE,
        "cpu_threads": FROZEN_CPU_THREADS,
        "batch_size": FROZEN_BATCH_SIZE,
    }
    if observed != expected:
        raise RunnerError("runtime arguments differ from the Plan 054 v2 identity")


def body_free_runner_exception(exc: BaseException) -> dict[str, str]:
    """Expose only the runner's fixed diagnostic strings.

    RunnerError messages are authored by this module and never interpolate
    packet bodies.  Backend and runtime-bridge failures keep their own typed,
    body-free projection; every other exception remains redacted.
    """

    if isinstance(exc, RunnerError):
        return {"failure_kind": "RunnerError", "message": str(exc)}
    return body_free_exception(exc)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def file_manifest(repo_root: Path, paths: Iterable[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in paths:
        path = repo_root / relative
        if path.is_symlink() or not path.is_file():
            raise RunnerError(f"tracked freeze input is missing or unsafe: {relative}")
        result[relative] = sha256_file(path)
    return result


def combined_manifest_sha256(files: Mapping[str, str]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(files)))


def verify_asset_lock(asset_lock_path: Path, snapshot: Path) -> dict[str, Any]:
    lock = load_json(asset_lock_path)
    if not isinstance(lock, dict) or lock.get("schema") != ASSET_LOCK_SCHEMA:
        raise RunnerError("asset lock schema is invalid")
    model = lock.get("model")
    if not isinstance(model, dict) or model.get("repository") != MODEL_REPOSITORY:
        raise RunnerError("asset lock model repository drifted")
    if model.get("revision") != MODEL_REVISION or snapshot.name != MODEL_REVISION:
        raise RunnerError("asset lock immutable revision drifted")
    if snapshot.is_symlink() or not snapshot.is_dir():
        raise RunnerError("exact model snapshot is missing or unsafe")
    files = lock.get("files")
    if not isinstance(files, dict) or not files:
        raise RunnerError("asset lock file inventory is missing")
    model_cache_root = snapshot.parent.parent.resolve(strict=True)
    for relative, expected in files.items():
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise RunnerError("asset lock file entry is invalid")
        logical = Path(relative)
        if logical.is_absolute() or ".." in logical.parts or len(expected) != 64:
            raise RunnerError("asset lock file entry is unsafe")
        path = snapshot / logical
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise RunnerError(f"asset file is missing: {relative}") from exc
        if not resolved.is_relative_to(model_cache_root) or not resolved.is_file():
            raise RunnerError(f"asset file escapes the exact cache: {relative}")
        if sha256_file(resolved) != expected:
            raise RunnerError(f"asset file identity drifted: {relative}")
    if files.get("model.safetensors") != MODEL_WEIGHT_SHA256:
        raise RunnerError("model weight identity drifted")
    return lock


def load_exact_tokenizer(snapshot: Path) -> ExactTokenizer:
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:
        raise RunnerError("locked tokenizer dependency is unavailable") from exc
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            snapshot,
            local_files_only=True,
            trust_remote_code=False,
        )
    except Exception as exc:
        raise RunnerError("exact tokenizer failed to load") from exc
    return ExactTokenizer(tokenizer)


def tokenize_corpus(repo_root: Path, tokenizer: ExactTokenizer) -> list[dict[str, Any]]:
    fixed = load_fixed_input_contract(repo_root)
    if fixed.render_contract["context"]["adopted_window_tokens"] != ADOPTED_CONTEXT_WINDOW:
        raise RunnerError("render contract and implementation window differ")
    rows: list[dict[str, Any]] = []
    corpus = load_sample_corpus(repo_root)
    for sample in corpus.samples:
        tokenized = tokenizer.fit_packet(
            sample.packet,
            fixed.rubric,
            adopted_window=ADOPTED_CONTEXT_WINDOW,
        )
        rows.append(
            {
                "sample_id": sample.sample_id,
                "data_role": sample.annotation["data_role"],
                "token_count": len(tokenized.input_ids),
                "dropped_oldest_publications": tokenized.plan.dropped_oldest_publications,
                "token_buckets": tokenized.buckets,
                "tokenized": tokenized,
                "sample": sample,
            }
        )
    boundaries = build_token_boundary_packets(
        [sample.packet for sample in corpus.samples],
        fixed.product_limits,
    )
    for boundary in boundaries:
        tokenized = tokenizer.fit_packet(
            boundary.packet,
            fixed.rubric,
            adopted_window=ADOPTED_CONTEXT_WINDOW,
        )
        rows.append(
            {
                "sample_id": boundary.sample_id,
                "data_role": "m3a2_token_census",
                "token_count": len(tokenized.input_ids),
                "dropped_oldest_publications": tokenized.plan.dropped_oldest_publications,
                "token_buckets": tokenized.buckets,
                "tokenized": tokenized,
                "sample": None,
            }
        )
    return rows


def census_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = sorted(int(row["token_count"]) for row in rows)
    if not counts:
        raise RunnerError("token census is empty")
    bucket_totals: Counter[str] = Counter()
    for row in rows:
        bucket_totals.update(row["token_buckets"])
    return {
        "sample_count": len(rows),
        "adopted_window_tokens": ADOPTED_CONTEXT_WINDOW,
        "min_tokens": counts[0],
        "max_tokens": counts[-1],
        "median_tokens": statistics.median(counts),
        "mean_tokens": statistics.fmean(counts),
        "overflow_sample_count": sum(
            int(row["dropped_oldest_publications"] > 0) for row in rows
        ),
        "total_dropped_oldest_publications": sum(
            int(row["dropped_oldest_publications"]) for row in rows
        ),
        "bucket_totals": dict(sorted(bucket_totals.items())),
        "samples": [
            {
                "sample_id": row["sample_id"],
                "data_role": row["data_role"],
                "token_count": row["token_count"],
                "dropped_oldest_publications": row["dropped_oldest_publications"],
                "token_buckets": row["token_buckets"],
            }
            for row in rows
        ],
    }


def _model_row(row: Mapping[str, Any], output: Any) -> dict[str, Any]:
    annotation = row["sample"].annotation
    return {
        "sample_id": row["sample_id"],
        "data_role": str(annotation["data_role"]).removeprefix("m3a2_"),
        "expected_label": annotation["expected_verdict"],
        "publication_class": annotation["publication_class"],
        "pair_id": annotation["pair_id"],
        "pair_direction": annotation["pair_direction"],
        "slices": list(annotation["slices"]),
        "raw_logit": output.raw_logit,
        "score": output.score,
        "latency_ms": output.latency_ms,
        "token_count": row["token_count"],
        "dropped_oldest_publications": row["dropped_oldest_publications"],
    }


def _validate_declared_measurement_slices(
    rows: Sequence[Mapping[str, Any]],
) -> None:
    observed: set[str] = set()
    for row in rows:
        sample = row.get("sample")
        annotation = getattr(sample, "annotation", None)
        if not isinstance(annotation, Mapping) or not isinstance(
            annotation.get("slices"), (list, tuple)
        ):
            raise RunnerError("measurement slice annotation is invalid")
        observed.update(
            value for value in annotation["slices"] if isinstance(value, str)
        )
    if not set(DECLARED_SLICES).issubset(observed):
        raise RunnerError("declared measurement slice is absent from the frozen cohort")


def _validate_declared_quality_slices(quality: Mapping[str, Any]) -> None:
    by_slice = quality.get("by_slice")
    if not isinstance(by_slice, dict) or not set(DECLARED_SLICES).issubset(by_slice):
        raise RunnerError("declared measurement slice is absent from the quality result")


def _assert_parity(reference: float, observed: float, description: str) -> None:
    if not math.isclose(
        reference,
        observed,
        rel_tol=0.0,
        abs_tol=PARITY_ABSOLUTE_TOLERANCE,
    ):
        raise RunnerError(f"scalar parity failed: {description}")


def _batched_outputs(
    backend: SkyworkBackend,
    rows: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
    padding_side: str,
) -> dict[str, Any]:
    if batch_size <= 0:
        raise RunnerError("batch size must be positive")
    outputs: dict[str, Any] = {}
    for start in range(0, len(rows), batch_size):
        batch_rows = rows[start : start + batch_size]
        batch_outputs = backend.score(
            [row["tokenized"] for row in batch_rows],
            padding_side=padding_side,
        )
        if len(batch_outputs) != len(batch_rows):
            raise RunnerError("model batch result count drifted")
        for row, output in zip(batch_rows, batch_outputs):
            sample_id = str(row["sample_id"])
            if sample_id in outputs:
                raise RunnerError("parity sample identity is duplicated")
            outputs[sample_id] = output
    return outputs


def _verify_scalar_parity(
    backend: SkyworkBackend,
    rows: Sequence[Mapping[str, Any]],
    *,
    batch_size: int,
) -> tuple[dict[str, Any], list[Any]]:
    """Prove every scored row is stable across the frozen batch semantics."""

    if len(rows) < 2:
        raise RunnerError("parity cohort is too small")
    sample_ids = [str(row["sample_id"]) for row in rows]
    if len(set(sample_ids)) != len(sample_ids):
        raise RunnerError("parity sample identity is duplicated")

    singles = {
        str(row["sample_id"]): backend.score(
            [row["tokenized"]], padding_side="right"
        )[0]
        for row in rows
    }
    repeats = {
        str(row["sample_id"]): backend.score(
            [row["tokenized"]], padding_side="right"
        )[0]
        for row in rows
    }
    standard_right = _batched_outputs(
        backend,
        rows,
        batch_size=batch_size,
        padding_side="right",
    )
    standard_left = _batched_outputs(
        backend,
        rows,
        batch_size=batch_size,
        padding_side="left",
    )
    alternate_rows = list(rows[::2]) + list(rows[1::2])
    alternate_right = _batched_outputs(
        backend,
        alternate_rows,
        batch_size=batch_size,
        padding_side="right",
    )

    parity_rows: list[dict[str, Any]] = []
    max_delta = 0.0
    for sample_id in sample_ids:
        reference = singles[sample_id].score
        comparisons = {
            "repeat": repeats[sample_id].score,
            "standard_right_batch": standard_right[sample_id].score,
            "standard_left_batch": standard_left[sample_id].score,
            "alternate_right_batch": alternate_right[sample_id].score,
        }
        for description, observed in comparisons.items():
            _assert_parity(reference, observed, f"{sample_id} single versus {description}")
        row_delta = max(abs(reference - observed) for observed in comparisons.values())
        max_delta = max(max_delta, row_delta)
        parity_rows.append(
            {
                "sample_id": sample_id,
                "single_score": reference,
                "repeat_score": comparisons["repeat"],
                "standard_right_batch_score": comparisons["standard_right_batch"],
                "standard_left_batch_score": comparisons["standard_left_batch"],
                "alternate_right_batch_score": comparisons["alternate_right_batch"],
                "max_absolute_projected_delta": row_delta,
            }
        )
    evidence = {
        "schema": "rondo-publication-critic-scalar-parity-v2",
        "row_count": len(rows),
        "batch_size": batch_size,
        "standard_order": sample_ids,
        "alternate_order": [str(row["sample_id"]) for row in alternate_rows],
        "absolute_tolerance": PARITY_ABSOLUTE_TOLERANCE,
        "max_absolute_projected_delta": max_delta,
        "coverage": [
            "single",
            "repeat_single",
            "standard_right_batch",
            "standard_left_batch",
            "alternate_right_batch",
        ],
        "rows": parity_rows,
    }
    return evidence, [standard_right[sample_id] for sample_id in sample_ids]


def _archive_model_rows(
    rows: Sequence[Mapping[str, Any]],
    outputs: Sequence[Any],
    archive: RunArchive,
) -> list[dict[str, Any]]:
    if len(rows) != len(outputs):
        raise RunnerError("model result count drifted")
    projected_rows: list[dict[str, Any]] = []
    for row, output in zip(rows, outputs):
        projected = _model_row(row, output)
        archive.write_json(f"sample-{len(projected_rows) + 1:03d}.json", projected)
        projected_rows.append(projected)
    return projected_rows


def run_census(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve(strict=True)
    verify_asset_lock(args.asset_lock, args.snapshot)
    archive = RunArchive(args.archive_root, args.run_id).create()
    tokenizer = load_exact_tokenizer(args.snapshot)
    rows = tokenize_corpus(repo_root, tokenizer)
    result = {
        "schema": TOKEN_CENSUS_SCHEMA,
        "run_id": args.run_id,
        "created_at": utc_now(),
        "model_revision": MODEL_REVISION,
        "input_manifest": file_manifest(repo_root, _INPUT_FILES),
        "census": census_summary(rows),
    }
    archive.write_json("token-census.json", result)
    return result


def run_calibration(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve(strict=True)
    _validate_frozen_runtime_args(args)
    verify_asset_lock(args.asset_lock, args.snapshot)
    archive = RunArchive(args.archive_root, args.run_id).create()
    archive.write_json(
        "run-start.json",
        {
            "phase": "calibration",
            "run_id": args.run_id,
            "created_at": utc_now(),
            "model_revision": MODEL_REVISION,
            "device": args.device,
            "dtype": args.dtype,
            "cpu_threads": args.cpu_threads,
            "batch_size": args.batch_size,
        },
    )
    try:
        backend = SkyworkBackend(
            args.snapshot,
            device=args.device,
            dtype=args.dtype,
            cpu_threads=args.cpu_threads,
        )
        backend.load()
        rows = tokenize_corpus(repo_root, backend.exact_tokenizer)
        calibration = [row for row in rows if row["data_role"] == "m3a2_calibration"]
        if len(calibration) != 8:
            raise RunnerError("calibration role count drifted")
        boundaries = [row for row in rows if row["data_role"] == "m3a2_token_census"]
        if len(boundaries) != 2:
            raise RunnerError("token boundary role count drifted")
        parity, parity_outputs = _verify_scalar_parity(
            backend,
            calibration,
            batch_size=args.batch_size,
        )
        archive.write_json("scalar-parity.json", parity)
        context = backend.verify_context_forward(ADOPTED_CONTEXT_WINDOW)
        smoke = {
            "model_output_shape": ["batch", 1],
            "tensor_index": "logits[:,0]",
            "pooling": "Qwen3ForSequenceClassification_last_non_pad_token",
            "raw_semantics": "unbounded_reward_logit_higher_is_better",
            "projection": "stable_sigmoid_v1",
            "projected_domain": [0.0, 1.0],
            "parity_absolute_tolerance": PARITY_ABSOLUTE_TOLERANCE,
            "parity_schema": parity["schema"],
            "parity_row_count": parity["row_count"],
            "parity_max_absolute_projected_delta": parity[
                "max_absolute_projected_delta"
            ],
            "context_forward": context,
        }
        archive.write_json("scalar-smoke.json", smoke)
        model_rows = _archive_model_rows(
            calibration,
            parity_outputs[: len(calibration)],
            archive,
        )
        threshold = derive_temporary_threshold(model_rows)
        result = {
            "schema": CALIBRATION_SCHEMA,
            "run_id": args.run_id,
            "completed_at": utc_now(),
            "model_revision": MODEL_REVISION,
            "input_manifest": file_manifest(repo_root, _INPUT_FILES),
            "input_manifest_sha256": combined_manifest_sha256(
                file_manifest(repo_root, _INPUT_FILES)
            ),
            "census": census_summary(rows),
            "scalar_smoke": smoke,
            "scalar_parity": parity,
            "temporary_threshold": threshold,
            "environment": {
                "device": args.device,
                "dtype": args.dtype,
                "cpu_threads": args.cpu_threads,
                "batch_size": args.batch_size,
                "model_load_seconds": backend.load_seconds,
            },
            "resources": backend.resource_snapshot(),
            "calibration_rows": model_rows,
        }
        path = archive.write_json("calibration-result.json", result)
        result["archive_result_sha256"] = sha256_file(path)
        archive.write_json(
            "completion.json",
            {
                "status": "complete",
                "calibration_result_sha256": result["archive_result_sha256"],
            },
        )
        return result
    except BaseException as exc:
        archive.write_json("failure.json", body_free_runner_exception(exc))
        raise


def verify_measurement_freeze(
    freeze_path: Path,
    repo_root: Path,
    asset_lock_path: Path,
    runtime_arguments: Mapping[str, Any] | None = None,
    calibration_result_path: Path | None = None,
) -> dict[str, Any]:
    freeze = load_json(freeze_path)
    if not isinstance(freeze, dict) or freeze.get("schema") != FREEZE_SCHEMA:
        raise RunnerError("measurement freeze schema is invalid")
    _require_exact_keys(
        freeze,
        {
            "schema",
            "purpose",
            "cohort_scope",
            "supersedes",
            "asset_lock_sha256",
            "environment_lock_sha256",
            "input_manifest",
            "input_manifest_sha256",
            "implementation_manifest",
            "implementation_manifest_sha256",
            "qualification_identity",
            "model_identity",
            "scoring_identity",
            "inference_contract",
            "adopted_window_tokens",
            "window_facts",
            "sample_identity",
            "temporary_threshold_source",
            "measurement_metrics",
            "declared_slices",
        },
        "freeze",
    )
    if freeze["purpose"] != "Plan 054 M3-A2 exact Skywork base-model measurement freeze v3":
        raise RunnerError("measurement freeze purpose drifted")
    if freeze["cohort_scope"] != "representative_and_boundary_examples_not_future_unseen_test":
        raise RunnerError("measurement cohort scope drifted")
    if freeze["supersedes"] != "rondo-publication-critic-measurement-freeze-v2":
        raise RunnerError("measurement freeze lineage drifted")

    expected_inputs = file_manifest(repo_root, _INPUT_FILES)
    expected_implementation = file_manifest(repo_root, _IMPLEMENTATION_FILES)
    if freeze["input_manifest"] != expected_inputs:
        raise RunnerError("measurement input manifest drifted")
    if freeze["input_manifest_sha256"] != combined_manifest_sha256(expected_inputs):
        raise RunnerError("measurement input manifest digest drifted")
    if freeze["implementation_manifest"] != expected_implementation:
        raise RunnerError("measurement implementation manifest drifted")
    if freeze["implementation_manifest_sha256"] != combined_manifest_sha256(
        expected_implementation
    ):
        raise RunnerError("measurement implementation manifest digest drifted")
    if freeze["asset_lock_sha256"] != sha256_file(asset_lock_path):
        raise RunnerError("measurement asset lock drifted")
    if freeze["environment_lock_sha256"] != expected_inputs[
        "eval/environments/publication-critic-plan054/uv.lock"
    ]:
        raise RunnerError("measurement environment lock drifted")

    qualification = freeze["qualification_identity"]
    expected_qualification = {
        "packet_schema": {"name": "rondo-publication-packet", "revision": "v1"},
        "rubric": {"name": "rondo-publication-qualification", "revision": "v1"},
    }
    if qualification != expected_qualification:
        raise RunnerError("measurement qualification identity drifted")
    expected_model = {
        "model": {
            "name": "skywork-reward-v2-qwen3-1.7b",
            "revision": MODEL_REVISION,
        },
        "tokenizer": {
            "name": "skywork-reward-v2-qwen3-1.7b-tokenizer",
            "revision": MODEL_REVISION,
        },
    }
    if freeze["model_identity"] != expected_model:
        raise RunnerError("measurement model identity drifted")

    scoring = freeze.get("scoring_identity")
    if not isinstance(scoring, dict):
        raise RunnerError("measurement scoring identity is missing")
    _require_exact_keys(
        scoring,
        {
            "definition",
            "input_template",
            "scalar_projection",
            "domain",
            "threshold",
            "pass_rule",
        },
        "scoring identity",
    )
    threshold = scoring.get("threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise RunnerError("measurement threshold is invalid")
    if not math.isfinite(float(threshold)) or not 0.0 <= float(threshold) <= 1.0:
        raise RunnerError("measurement threshold is outside the frozen domain")
    expected_scoring = {
        "definition": {
            "name": "skywork-reward-scalar-higher-better",
            "revision": f"{MODEL_REVISION}-fp32-v3",
        },
        "input_template": {
            "name": "rondo-publication-packet-render",
            "revision": "v2-sha256-"
            + expected_inputs[
                "eval/templates/publication-critic/render-contract-v2.json"
            ],
        },
        "scalar_projection": {
            "name": "stable-sigmoid-logits-index-0",
            "revision": "v1",
        },
        "domain": {"min": 0.0, "max": 1.0},
        "threshold": float(threshold),
        "pass_rule": "score_greater_than_or_equal_to_threshold",
    }
    if scoring != expected_scoring:
        raise RunnerError("measurement scoring identity drifted")
    if freeze["inference_contract"] != _frozen_runtime_identity():
        raise RunnerError("measurement inference identity drifted")
    if runtime_arguments is not None:
        expected_runtime_arguments = {
            "device": FROZEN_DEVICE,
            "dtype": FROZEN_DTYPE,
            "cpu_threads": FROZEN_CPU_THREADS,
            "batch_size": FROZEN_BATCH_SIZE,
        }
        if dict(runtime_arguments) != expected_runtime_arguments:
            raise RunnerError("measurement CLI runtime differs from frozen identity")

    if freeze["adopted_window_tokens"] != ADOPTED_CONTEXT_WINDOW:
        raise RunnerError("measurement adopted window drifted")
    expected_window_facts = {
        "model_card_training_and_recommended_inference_tokens": 16384,
        "model_config_max_position_embeddings": 40960,
        "tokenizer_model_max_length": 131072,
        "verified_context_forward_tokens": 16384,
        "overflow_policy": "drop_whole_oldest_prior_publications_then_explicitly_encode_additional_omission",
        "required_content_overflow": "typed_input_failure",
        "implicit_tokenizer_truncation": False,
    }
    if freeze["window_facts"] != expected_window_facts:
        raise RunnerError("measurement window facts drifted")

    sample_files = {
        relative: expected_inputs[relative]
        for relative in (
            "eval/fixtures/publication-critic-v1/packets.jsonl",
            "eval/fixtures/publication-critic-v1/annotations.jsonl",
        )
    }
    expected_sample_identity = {
        "name": "rondo-publication-critic-m3a2-cohort",
        "revision": "v2-sha256-" + combined_manifest_sha256(sample_files),
        "calibration_count": 8,
        "measurement_count": 16,
        "token_census_only_count": 2,
        "class_counts": {
            "new_event_completed": 6,
            "new_event_incomplete": 6,
            "existing_event_completed": 6,
            "existing_event_incomplete": 6,
        },
        "label_counts": {"pass": 12, "rewrite": 12},
        "future_m3_b1a_unseen_test": False,
    }
    if freeze["sample_identity"] != expected_sample_identity:
        raise RunnerError("measurement sample identity drifted")

    threshold_source = freeze["temporary_threshold_source"]
    if not isinstance(threshold_source, dict):
        raise RunnerError("measurement threshold source is invalid")
    _require_exact_keys(
        threshold_source,
        {
            "run_id",
            "calibration_result_sha256",
            "rule",
            "rule_sha256",
            "measurement_labels_used",
        },
        "threshold source",
    )
    if (
        not isinstance(threshold_source["run_id"], str)
        or not threshold_source["run_id"].startswith("plan054-")
        or not isinstance(threshold_source["calibration_result_sha256"], str)
        or len(threshold_source["calibration_result_sha256"]) != 64
        or threshold_source["rule"]
        != "maximize_balanced_accuracy_then_minimize_false_pass_then_maximize_threshold_v1"
        or threshold_source["rule_sha256"]
        != expected_inputs[
            "eval/templates/publication-critic/temporary-threshold-rule-v1.json"
        ]
        or threshold_source["measurement_labels_used"] is not False
    ):
        raise RunnerError("measurement threshold source drifted")
    if calibration_result_path is not None:
        if calibration_result_path.is_symlink() or not calibration_result_path.is_file():
            raise RunnerError("measurement calibration result is missing or unsafe")
        if sha256_file(calibration_result_path) != threshold_source["calibration_result_sha256"]:
            raise RunnerError("measurement calibration result digest drifted")
        calibration = load_json(calibration_result_path)
        if not isinstance(calibration, dict):
            raise RunnerError("measurement calibration result identity drifted")
        calibration_threshold = calibration.get("temporary_threshold", {})
        if (
            calibration.get("schema") != CALIBRATION_SCHEMA
            or calibration.get("run_id") != threshold_source["run_id"]
            or calibration.get("model_revision") != MODEL_REVISION
            or calibration.get("input_manifest_sha256")
            != freeze["input_manifest_sha256"]
            or not isinstance(calibration_threshold, dict)
            or calibration_threshold.get("rule") != threshold_source["rule"]
            or calibration_threshold.get("calibration_count") != 8
            or calibration_threshold.get("threshold") != threshold
        ):
            raise RunnerError("measurement calibration result identity drifted")
    if freeze["measurement_metrics"] != list(MEASUREMENT_METRICS):
        raise RunnerError("measurement metrics drifted")
    if freeze["declared_slices"] != list(DECLARED_SLICES):
        raise RunnerError("measurement slices drifted")
    return freeze


def _git_fact(repo_root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if completed.returncode != 0:
        raise RunnerError("cannot establish the local Git freeze fact")
    return completed.stdout.strip()


def _require_committed_freeze(repo_root: Path, freeze_path: Path) -> None:
    expected = repo_root.resolve(strict=True) / _MEASUREMENT_FREEZE_RELATIVE
    try:
        observed = freeze_path.resolve(strict=True)
    except OSError as exc:
        raise RunnerError("measurement freeze path is missing") from exc
    if observed != expected:
        raise RunnerError("measurement freeze is not the canonical tracked path")
    relative = _MEASUREMENT_FREEZE_RELATIVE.as_posix()
    if _git_fact(repo_root, "ls-files", "--error-unmatch", relative) != relative:
        raise RunnerError("measurement freeze is not tracked by Git")


def run_measurement(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve(strict=True)
    _validate_frozen_runtime_args(args)
    verify_asset_lock(args.asset_lock, args.snapshot)
    _require_committed_freeze(repo_root, args.freeze)
    runtime_arguments = {
        "device": args.device,
        "dtype": args.dtype,
        "cpu_threads": args.cpu_threads,
        "batch_size": args.batch_size,
    }
    freeze = verify_measurement_freeze(
        args.freeze,
        repo_root,
        args.asset_lock,
        runtime_arguments,
        args.calibration_result,
    )
    if _git_fact(repo_root, "status", "--porcelain", "--untracked-files=no"):
        raise RunnerError("tracked worktree is not clean at measurement freeze")
    commit = _git_fact(repo_root, "rev-parse", "HEAD")
    archive = RunArchive(args.archive_root, args.run_id).create()
    archive.write_json(
        "run-start.json",
        {
            "phase": "measurement",
            "run_id": args.run_id,
            "created_at": utc_now(),
            "freeze_sha256": sha256_file(args.freeze),
            "code_commit": commit,
            "runtime_arguments": runtime_arguments,
        },
    )
    try:
        measurement_started = datetime.now(timezone.utc)
        backend = SkyworkBackend(
            args.snapshot,
            device=args.device,
            dtype=args.dtype,
            cpu_threads=args.cpu_threads,
        )
        backend.load()
        rows = tokenize_corpus(repo_root, backend.exact_tokenizer)
        measurement = [row for row in rows if row["data_role"] == "m3a2_measurement"]
        if len(measurement) != 16:
            raise RunnerError("measurement role count drifted")
        _validate_declared_measurement_slices(measurement)
        parity, parity_outputs = _verify_scalar_parity(
            backend,
            measurement,
            batch_size=args.batch_size,
        )
        archive.write_json("scalar-parity.json", parity)
        model_rows = _archive_model_rows(measurement, parity_outputs, archive)
        threshold = float(freeze["scoring_identity"]["threshold"])
        for row in model_rows:
            row["predicted_label"] = "pass" if row["score"] >= threshold else "rewrite"
        quality = summarize_measurement(model_rows, threshold)
        _validate_declared_quality_slices(quality)
        measurement_wall_seconds = (
            datetime.now(timezone.utc) - measurement_started
        ).total_seconds()
        result = {
            "schema": RESULT_SCHEMA,
            "run_id": args.run_id,
            "completed_at": utc_now(),
            "code_commit": commit,
            "freeze_sha256": sha256_file(args.freeze),
            "model_identity": freeze["model_identity"],
            "scoring_identity": freeze["scoring_identity"],
            "sample_identity": freeze["sample_identity"],
            "qualification_identity": freeze["qualification_identity"],
            "inference_contract": freeze["inference_contract"],
            "cohort_scope": "m3a2_representative_and_boundary_not_future_unseen_test",
            "scalar_parity": parity,
            "quality": quality,
            "token_census": census_summary(rows),
            "environment": {
                "device": args.device,
                "dtype": args.dtype,
                "cpu_threads": args.cpu_threads,
                "batch_size": args.batch_size,
                "model_load_seconds": backend.load_seconds,
                "measurement_wall_seconds_including_model_load": measurement_wall_seconds,
                "forward_latency_basis": "per_batch_wall_divided_by_batch_size",
                "device_synchronization": "torch_cuda_synchronize_after_each_forward"
                if args.device == "cuda"
                else "synchronous_cpu_forward",
                "peak_reset": "not_reset_process_lifetime_peak_includes_model_load",
            },
            "resources": backend.resource_snapshot(),
            "measurement_rows": model_rows,
        }
        raw_path = archive.write_json("measurement-result.json", result)
        result["raw_result_sha256"] = sha256_file(raw_path)
        args.tracked_result.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.tracked_result.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, allow_nan=False, indent=2)
                handle.write("\n")
        except FileExistsError as exc:
            raise RunnerError("tracked result already exists; refusing overwrite") from exc
        archive.write_json(
            "completion.json",
            {"status": "complete", "raw_result_sha256": result["raw_result_sha256"]},
        )
        return result
    except BaseException as exc:
        archive.write_json("failure.json", body_free_runner_exception(exc))
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan 054 Publication Critic baseline runner")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--snapshot", type=Path, required=True)
        subparser.add_argument("--asset-lock", type=Path, required=True)
        subparser.add_argument("--archive-root", type=Path, required=True)
        subparser.add_argument("--run-id", required=True)

    census = subparsers.add_parser("census")
    common(census)
    census.set_defaults(function=run_census)

    calibration = subparsers.add_parser("calibrate")
    common(calibration)
    calibration.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    calibration.add_argument("--dtype", choices=("bfloat16", "float32"), default=FROZEN_DTYPE)
    calibration.add_argument("--cpu-threads", type=int, default=4)
    calibration.add_argument("--batch-size", type=int, default=4)
    calibration.set_defaults(function=run_calibration)

    measurement = subparsers.add_parser("measure")
    common(measurement)
    measurement.add_argument("--freeze", type=Path, required=True)
    measurement.add_argument("--calibration-result", type=Path, required=True)
    measurement.add_argument("--tracked-result", type=Path, required=True)
    measurement.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    measurement.add_argument("--dtype", choices=("bfloat16", "float32"), default=FROZEN_DTYPE)
    measurement.add_argument("--cpu-threads", type=int, default=4)
    measurement.add_argument("--batch-size", type=int, default=4)
    measurement.set_defaults(function=run_measurement)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = args.function(args)
    except Exception as exc:
        json.dump(body_free_runner_exception(exc), sys.stderr, sort_keys=True)
        sys.stderr.write("\n")
        return 1
    summary = {
        "schema": result["schema"],
        "run_id": result["run_id"],
        "status": "complete",
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
