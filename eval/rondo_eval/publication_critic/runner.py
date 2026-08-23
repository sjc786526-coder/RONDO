"""Bounded Plan 054 census, calibration, freeze, measurement and finalizer.

Token census may run without loading model weights. Calibration and measurement
load the exact checkpoint only while the process is supervised by the repository
watchdog. The lightweight freeze and finalizer phases bind the post-process
watchdog summaries without loading the model. Measurement requires a committed
freeze document and never uses measurement labels to derive its threshold.
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
from .evidence import EvidenceError, load_watchdog_summary
from .identity import canonical_json_bytes, load_json, sha256_bytes, sha256_file
from .render import ADOPTED_CONTEXT_WINDOW
from .scoring import derive_temporary_threshold, project_logit, summarize_measurement
from .tokenization import ExactTokenizer


MODEL_REPOSITORY = "Skywork/Skywork-Reward-V2-Qwen3-1.7B"
MODEL_REVISION = "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc"
MODEL_WEIGHT_SHA256 = "117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9"
ASSET_LOCK_SCHEMA = "rondo-publication-critic-skywork-assets-v1"
FREEZE_SCHEMA = "rondo-publication-critic-measurement-freeze-v4"
RESULT_SCHEMA = "rondo-publication-critic-baseline-result-v4"
CALIBRATION_SCHEMA = "rondo-publication-critic-calibration-result-v3"
TOKEN_CENSUS_SCHEMA = "rondo-publication-critic-token-census-v3"
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
    "standard_batch_wall_and_amortized_compute_timing",
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
    "eval/manifests/publication-critic/measurement-freeze-v4.json"
)
_TRACKED_RESULT_RELATIVE = Path(
    "eval/results/publication-critic/skywork-reward-v2-qwen3-1.7b-baseline-v4.json"
)

_INPUT_FILES = (
    "eval/environments/publication-critic-plan054/pyproject.toml",
    "eval/environments/publication-critic-plan054/uv.lock",
    "eval/fixtures/publication-critic-v1/packets.jsonl",
    "eval/fixtures/publication-critic-v1/annotations.jsonl",
    "eval/templates/publication-critic/input-contract-v2.md",
    "eval/templates/publication-critic/qualification-rubric-v1.md",
    "eval/templates/publication-critic/product-packet-limits-v1.json",
    "eval/templates/publication-critic/render-contract-v3.json",
    "eval/templates/publication-critic/temporary-threshold-rule-v1.json",
)
_IMPLEMENTATION_FILES = (
    "eval/rondo_eval/publication_critic/archive.py",
    "eval/rondo_eval/publication_critic/backend.py",
    "eval/rondo_eval/publication_critic/boundaries.py",
    "eval/rondo_eval/publication_critic/contract.py",
    "eval/rondo_eval/publication_critic/evidence.py",
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
        raise RunnerError("runtime arguments differ from the Plan 054 frozen identity")


def body_free_runner_exception(exc: BaseException) -> dict[str, str]:
    """Expose only the runner's fixed diagnostic strings.

    RunnerError messages are authored by this module and never interpolate
    packet bodies.  Backend and runtime-bridge failures keep their own typed,
    body-free projection; every other exception remains redacted.
    """

    if isinstance(exc, (RunnerError, EvidenceError)):
        return {"failure_kind": type(exc).__name__, "message": str(exc)}
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


def _qualification_identity() -> dict[str, Any]:
    return {
        "packet_schema": {"name": "rondo-publication-packet", "revision": "v1"},
        "rubric": {"name": "rondo-publication-qualification", "revision": "v1"},
    }


def _model_identity() -> dict[str, Any]:
    return {
        "model": {
            "name": "skywork-reward-v2-qwen3-1.7b",
            "revision": MODEL_REVISION,
        },
        "tokenizer": {
            "name": "skywork-reward-v2-qwen3-1.7b-tokenizer",
            "revision": MODEL_REVISION,
        },
    }


def _input_template_binding(
    input_manifest: Mapping[str, str],
    implementation_manifest: Mapping[str, str],
    asset_lock: Mapping[str, Any],
) -> dict[str, Any]:
    files = asset_lock.get("files")
    if not isinstance(files, dict):
        raise RunnerError("asset lock file inventory is missing")
    binding = {
        "schema": "rondo-publication-critic-input-template-binding-v1",
        "render_contract_sha256": input_manifest[
            "eval/templates/publication-critic/render-contract-v3.json"
        ],
        "qualification_rubric_sha256": input_manifest[
            "eval/templates/publication-critic/qualification-rubric-v1.md"
        ],
        "renderer_sha256": implementation_manifest[
            "eval/rondo_eval/publication_critic/render.py"
        ],
        "chat_template_sha256": files.get("chat_template.jinja"),
        "added_tokens_sha256": files.get("added_tokens.json"),
        "add_generation_prompt": False,
        "add_special_tokens_after_chat_template": False,
    }
    if any(
        not isinstance(binding[key], str) or len(binding[key]) != 64
        for key in (
            "render_contract_sha256",
            "qualification_rubric_sha256",
            "renderer_sha256",
            "chat_template_sha256",
            "added_tokens_sha256",
        )
    ):
        raise RunnerError("input template binding file identity is invalid")
    return binding


def _scoring_identity(
    threshold: float,
    input_template_binding: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "definition": {
            "name": "skywork-reward-scalar-higher-better",
            "revision": f"{MODEL_REVISION}-fp32-v1",
        },
        "input_template": {
            "name": "rondo-publication-packet-render",
            "revision": "v3-sha256-"
            + sha256_bytes(canonical_json_bytes(dict(input_template_binding))),
        },
        "scalar_projection": {
            "name": "stable-sigmoid-logits-index-0",
            "revision": "v1",
        },
        "domain": {"min": 0.0, "max": 1.0},
        "threshold": float(threshold),
        "pass_rule": "score_greater_than_or_equal_to_threshold",
    }


def _sample_identity(input_manifest: Mapping[str, str]) -> dict[str, Any]:
    sample_files = {
        relative: input_manifest[relative]
        for relative in (
            "eval/fixtures/publication-critic-v1/packets.jsonl",
            "eval/fixtures/publication-critic-v1/annotations.jsonl",
        )
    }
    return {
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


def _window_facts() -> dict[str, Any]:
    return {
        "model_card_training_and_recommended_inference_tokens": 16384,
        "model_config_max_position_embeddings": 40960,
        "tokenizer_model_max_length": 131072,
        "verified_context_forward_tokens": 16384,
        "overflow_policy": "drop_whole_oldest_prior_publications_then_explicitly_encode_additional_omission",
        "required_content_overflow": "typed_input_failure",
        "implicit_tokenizer_truncation": False,
    }


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


def _model_row(
    row: Mapping[str, Any],
    output: Any,
    *,
    standard_batch_index: int,
) -> dict[str, Any]:
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
        "standard_batch_index": standard_batch_index,
        "standard_batch_size": output.batch_size,
        "standard_batch_elapsed_ms": output.batch_elapsed_ms,
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
    *,
    batch_size: int,
) -> list[dict[str, Any]]:
    if len(rows) != len(outputs):
        raise RunnerError("model result count drifted")
    projected_rows: list[dict[str, Any]] = []
    for row, output in zip(rows, outputs):
        index = len(projected_rows)
        expected_batch_size = min(batch_size, len(rows) - (index // batch_size) * batch_size)
        if output.batch_size != expected_batch_size:
            raise RunnerError("model standard batch size drifted")
        projected = _model_row(
            row,
            output,
            standard_batch_index=index // batch_size,
        )
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
    asset_lock = verify_asset_lock(args.asset_lock, args.snapshot)
    if _git_fact(repo_root, "status", "--porcelain", "--untracked-files=no"):
        raise RunnerError("tracked worktree is not clean at calibration identity")
    commit = _git_fact(repo_root, "rev-parse", "HEAD")
    input_manifest = file_manifest(repo_root, _INPUT_FILES)
    implementation_manifest = file_manifest(repo_root, _IMPLEMENTATION_FILES)
    input_template_binding = _input_template_binding(
        input_manifest,
        implementation_manifest,
        asset_lock,
    )
    archive = RunArchive(args.archive_root, args.run_id).create()
    archive.write_json(
        "run-start.json",
        {
            "phase": "calibration",
            "run_id": args.run_id,
            "created_at": utc_now(),
            "model_revision": MODEL_REVISION,
            "code_commit": commit,
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
            batch_size=args.batch_size,
        )
        threshold = derive_temporary_threshold(model_rows)
        scoring_identity = _scoring_identity(
            float(threshold["threshold"]),
            input_template_binding,
        )
        result = {
            "schema": CALIBRATION_SCHEMA,
            "run_id": args.run_id,
            "completed_at": utc_now(),
            "code_commit": commit,
            "model_identity": _model_identity(),
            "qualification_identity": _qualification_identity(),
            "input_template_binding": input_template_binding,
            "scoring_identity": scoring_identity,
            "inference_contract": _frozen_runtime_identity(),
            "input_manifest": input_manifest,
            "input_manifest_sha256": combined_manifest_sha256(input_manifest),
            "implementation_manifest": implementation_manifest,
            "implementation_manifest_sha256": combined_manifest_sha256(
                implementation_manifest
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


def _verify_calibration_result(
    calibration_result_path: Path,
    calibration_watchdog_path: Path,
    repo_root: Path,
    asset_lock: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if calibration_result_path.is_symlink() or not calibration_result_path.is_file():
        raise RunnerError("measurement calibration result is missing or unsafe")
    calibration = load_json(calibration_result_path)
    if not isinstance(calibration, dict):
        raise RunnerError("measurement calibration result identity drifted")
    _require_exact_keys(
        calibration,
        {
            "schema",
            "run_id",
            "completed_at",
            "code_commit",
            "model_identity",
            "qualification_identity",
            "input_template_binding",
            "scoring_identity",
            "inference_contract",
            "input_manifest",
            "input_manifest_sha256",
            "implementation_manifest",
            "implementation_manifest_sha256",
            "census",
            "scalar_smoke",
            "scalar_parity",
            "temporary_threshold",
            "environment",
            "resources",
            "calibration_rows",
        },
        "calibration result",
    )
    expected_inputs = file_manifest(repo_root, _INPUT_FILES)
    expected_implementation = file_manifest(repo_root, _IMPLEMENTATION_FILES)
    expected_binding = _input_template_binding(
        expected_inputs,
        expected_implementation,
        asset_lock,
    )
    if (
        calibration["schema"] != CALIBRATION_SCHEMA
        or not isinstance(calibration["run_id"], str)
        or not calibration["run_id"].startswith("plan054-")
        or not isinstance(calibration["code_commit"], str)
        or len(calibration["code_commit"]) != 40
        or calibration["model_identity"] != _model_identity()
        or calibration["qualification_identity"] != _qualification_identity()
        or calibration["input_template_binding"] != expected_binding
        or calibration["inference_contract"] != _frozen_runtime_identity()
        or calibration["input_manifest"] != expected_inputs
        or calibration["input_manifest_sha256"]
        != combined_manifest_sha256(expected_inputs)
        or calibration["implementation_manifest"] != expected_implementation
        or calibration["implementation_manifest_sha256"]
        != combined_manifest_sha256(expected_implementation)
    ):
        raise RunnerError("measurement calibration result identity drifted")

    environment = calibration["environment"]
    if not isinstance(environment, dict):
        raise RunnerError("measurement calibration environment drifted")
    _require_exact_keys(
        environment,
        {"device", "dtype", "cpu_threads", "batch_size", "model_load_seconds"},
        "calibration environment",
    )
    model_load_seconds = environment["model_load_seconds"]
    if (
        {key: environment[key] for key in ("device", "dtype", "cpu_threads", "batch_size")}
        != {
            "device": FROZEN_DEVICE,
            "dtype": FROZEN_DTYPE,
            "cpu_threads": FROZEN_CPU_THREADS,
            "batch_size": FROZEN_BATCH_SIZE,
        }
        or not isinstance(model_load_seconds, (int, float))
        or isinstance(model_load_seconds, bool)
        or not math.isfinite(float(model_load_seconds))
        or float(model_load_seconds) < 0
    ):
        raise RunnerError("measurement calibration environment drifted")

    rows = calibration["calibration_rows"]
    if not isinstance(rows, list) or len(rows) != 8:
        raise RunnerError("measurement calibration rows drifted")
    expected_samples = {
        sample.sample_id: sample
        for sample in load_sample_corpus(repo_root).samples
        if sample.annotation["data_role"] == "m3a2_calibration"
    }
    expected_row_keys = {
        "sample_id",
        "data_role",
        "expected_label",
        "publication_class",
        "pair_id",
        "pair_direction",
        "slices",
        "raw_logit",
        "score",
        "standard_batch_index",
        "standard_batch_size",
        "standard_batch_elapsed_ms",
        "token_count",
        "dropped_oldest_publications",
    }
    if any(
        not isinstance(row, dict) or not isinstance(row.get("sample_id"), str)
        for row in rows
    ) or {row["sample_id"] for row in rows} != set(expected_samples):
        raise RunnerError("measurement calibration rows drifted")
    batch_elapsed: dict[int, float] = {}
    for position, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != expected_row_keys:
            raise RunnerError("measurement calibration rows drifted")
        sample = expected_samples.get(row["sample_id"])
        if sample is None:
            raise RunnerError("measurement calibration rows drifted")
        annotation = sample.annotation
        expected_metadata = {
            "data_role": "calibration",
            "expected_label": annotation["expected_verdict"],
            "publication_class": annotation["publication_class"],
            "pair_id": annotation["pair_id"],
            "pair_direction": annotation["pair_direction"],
            "slices": list(annotation["slices"]),
        }
        if any(row[key] != value for key, value in expected_metadata.items()):
            raise RunnerError("measurement calibration rows drifted")
        try:
            raw_logit = float(row["raw_logit"])
            score = float(row["score"])
            elapsed_ms = float(row["standard_batch_elapsed_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RunnerError("measurement calibration rows drifted") from exc
        expected_batch_index = position // FROZEN_BATCH_SIZE
        if (
            not math.isfinite(raw_logit)
            or not math.isfinite(score)
            or not math.isclose(project_logit(raw_logit), score, rel_tol=0.0, abs_tol=1e-12)
            or type(row["standard_batch_index"]) is not int
            or row["standard_batch_index"] != expected_batch_index
            or type(row["standard_batch_size"]) is not int
            or row["standard_batch_size"] != FROZEN_BATCH_SIZE
            or not math.isfinite(elapsed_ms)
            or elapsed_ms < 0
            or type(row["token_count"]) is not int
            or not 0 < row["token_count"] <= ADOPTED_CONTEXT_WINDOW
            or type(row["dropped_oldest_publications"]) is not int
            or not 0 <= row["dropped_oldest_publications"] <= 4
        ):
            raise RunnerError("measurement calibration rows drifted")
        prior_elapsed = batch_elapsed.setdefault(expected_batch_index, elapsed_ms)
        if elapsed_ms != prior_elapsed:
            raise RunnerError("measurement calibration rows drifted")
    threshold = derive_temporary_threshold(rows)
    if calibration["temporary_threshold"] != threshold:
        raise RunnerError("measurement calibration threshold derivation drifted")
    expected_scoring = _scoring_identity(float(threshold["threshold"]), expected_binding)
    if calibration["scoring_identity"] != expected_scoring:
        raise RunnerError("measurement calibration scoring identity drifted")

    parity = calibration["scalar_parity"]
    standard_order = [row["sample_id"] for row in rows]
    alternate_order = standard_order[::2] + standard_order[1::2]
    expected_coverage = [
        "single",
        "repeat_single",
        "standard_right_batch",
        "standard_left_batch",
        "alternate_right_batch",
    ]
    if (
        not isinstance(parity, dict)
        or set(parity)
        != {
            "schema",
            "row_count",
            "batch_size",
            "standard_order",
            "alternate_order",
            "absolute_tolerance",
            "max_absolute_projected_delta",
            "coverage",
            "rows",
        }
        or parity.get("schema") != "rondo-publication-critic-scalar-parity-v2"
        or parity.get("row_count") != 8
        or parity.get("batch_size") != FROZEN_BATCH_SIZE
        or parity.get("standard_order") != standard_order
        or parity.get("alternate_order") != alternate_order
        or parity.get("absolute_tolerance") != PARITY_ABSOLUTE_TOLERANCE
        or parity.get("coverage") != expected_coverage
        or not isinstance(parity.get("max_absolute_projected_delta"), (int, float))
        or isinstance(parity.get("max_absolute_projected_delta"), bool)
        or not 0.0
        <= float(parity["max_absolute_projected_delta"])
        <= PARITY_ABSOLUTE_TOLERANCE
        or not isinstance(parity.get("rows"), list)
        or len(parity["rows"]) != 8
    ):
        raise RunnerError("measurement calibration scalar parity drifted")
    rows_by_id = {row["sample_id"]: row for row in rows}
    expected_parity_keys = {
        "sample_id",
        "single_score",
        "repeat_score",
        "standard_right_batch_score",
        "standard_left_batch_score",
        "alternate_right_batch_score",
        "max_absolute_projected_delta",
    }
    observed_max_delta = 0.0
    for parity_row in parity["rows"]:
        if not isinstance(parity_row, dict) or set(parity_row) != expected_parity_keys:
            raise RunnerError("measurement calibration scalar parity drifted")
        scored = rows_by_id.get(parity_row["sample_id"])
        if scored is None:
            raise RunnerError("measurement calibration scalar parity drifted")
        try:
            single = float(parity_row["single_score"])
            compared = [
                float(parity_row[key])
                for key in (
                    "repeat_score",
                    "standard_right_batch_score",
                    "standard_left_batch_score",
                    "alternate_right_batch_score",
                )
            ]
            row_max_delta = float(parity_row["max_absolute_projected_delta"])
        except (TypeError, ValueError) as exc:
            raise RunnerError("measurement calibration scalar parity drifted") from exc
        actual_max_delta = max(abs(single - value) for value in compared)
        if (
            not all(math.isfinite(value) for value in [single, *compared, row_max_delta])
            or not math.isclose(
                compared[1],
                float(scored["score"]),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or not math.isclose(
                actual_max_delta,
                row_max_delta,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or row_max_delta > PARITY_ABSOLUTE_TOLERANCE
        ):
            raise RunnerError("measurement calibration scalar parity drifted")
        observed_max_delta = max(observed_max_delta, row_max_delta)
    if not math.isclose(
        observed_max_delta,
        float(parity["max_absolute_projected_delta"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise RunnerError("measurement calibration scalar parity drifted")
    smoke = calibration["scalar_smoke"]
    context = smoke.get("context_forward") if isinstance(smoke, dict) else None
    context_latency = context.get("latency_ms") if isinstance(context, dict) else None
    if (
        not isinstance(context, dict)
        or set(context) != {"kind", "token_count", "latency_ms", "output_shape", "finite"}
        or not isinstance(smoke, dict)
        or set(smoke)
        != {
            "model_output_shape",
            "tensor_index",
            "pooling",
            "raw_semantics",
            "projection",
            "projected_domain",
            "parity_absolute_tolerance",
            "parity_schema",
            "parity_row_count",
            "parity_max_absolute_projected_delta",
            "context_forward",
        }
        or context.get("kind") != "synthetic_token_context_mechanical_smoke"
        or context.get("token_count") != ADOPTED_CONTEXT_WINDOW
        or context.get("output_shape") != [1, 1]
        or context.get("finite") is not True
        or not isinstance(context_latency, (int, float))
        or isinstance(context_latency, bool)
        or not math.isfinite(float(context_latency))
        or float(context_latency) < 0
        or smoke.get("model_output_shape") != ["batch", 1]
        or smoke.get("tensor_index") != "logits[:,0]"
        or smoke.get("pooling")
        != "Qwen3ForSequenceClassification_last_non_pad_token"
        or smoke.get("raw_semantics")
        != "unbounded_reward_logit_higher_is_better"
        or smoke.get("projection") != "stable_sigmoid_v1"
        or smoke.get("projected_domain") != [0.0, 1.0]
        or smoke.get("parity_absolute_tolerance") != PARITY_ABSOLUTE_TOLERANCE
        or smoke.get("parity_schema") != parity["schema"]
        or smoke.get("parity_row_count") != 8
        or smoke.get("parity_max_absolute_projected_delta")
        != parity["max_absolute_projected_delta"]
    ):
        raise RunnerError("measurement calibration scalar smoke drifted")
    resources = calibration["resources"]
    if (
        not isinstance(resources, dict)
        or set(resources) != {"process_rss_bytes", "process_peak_rss_bytes", "cuda"}
        or type(resources["process_rss_bytes"]) is not int
        or resources["process_rss_bytes"] < 0
        or type(resources["process_peak_rss_bytes"]) is not int
        or resources["process_peak_rss_bytes"] < 0
        or resources["cuda"] is not None
    ):
        raise RunnerError("measurement calibration resource projection drifted")
    watchdog = load_watchdog_summary(calibration_watchdog_path)
    artifact_sha256 = sha256_file(calibration_result_path)
    projection = {
        "schema": "rondo-publication-critic-calibration-evidence-v1",
        "run_id": calibration["run_id"],
        "code_commit": calibration["code_commit"],
        "artifact_sha256": artifact_sha256,
        "implementation_manifest_sha256": calibration[
            "implementation_manifest_sha256"
        ],
        "environment": environment,
        "scoring_identity": calibration["scoring_identity"],
        "scalar_parity": {
            "schema": parity["schema"],
            "row_count": parity["row_count"],
            "coverage": parity["coverage"],
            "absolute_tolerance": parity["absolute_tolerance"],
            "max_absolute_projected_delta": parity[
                "max_absolute_projected_delta"
            ],
        },
        "context_forward": context,
        "threshold_derivation": threshold,
        "calibration_rows": [
            {
                "sample_id": row["sample_id"],
                "expected_label": row["expected_label"],
                "raw_logit": row["raw_logit"],
                "score": row["score"],
            }
            for row in rows
        ],
        "process_resources": resources,
        "watchdog": watchdog,
    }
    return calibration, projection


def create_measurement_freeze(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve(strict=True)
    asset_lock = verify_asset_lock(args.asset_lock, args.snapshot)
    if _git_fact(repo_root, "status", "--porcelain", "--untracked-files=no"):
        raise RunnerError("tracked worktree is not clean at measurement freeze creation")
    calibration, projection = _verify_calibration_result(
        args.calibration_result,
        args.calibration_watchdog_summary,
        repo_root,
        asset_lock,
    )
    if calibration["code_commit"] != _git_fact(repo_root, "rev-parse", "HEAD"):
        raise RunnerError("calibration was not produced from the clean freeze commit")
    expected = repo_root / _MEASUREMENT_FREEZE_RELATIVE
    if args.output.resolve(strict=False) != expected.resolve(strict=False):
        raise RunnerError("measurement freeze output is not the canonical tracked path")
    if args.output.exists() or args.output.is_symlink():
        raise RunnerError("measurement freeze output already exists")

    inputs = calibration["input_manifest"]
    implementation = calibration["implementation_manifest"]
    threshold = float(calibration["temporary_threshold"]["threshold"])
    freeze = {
        "schema": FREEZE_SCHEMA,
        "purpose": "Plan 054 M3-A2 exact Skywork base-model measurement freeze v4",
        "cohort_scope": "representative_and_boundary_examples_not_future_unseen_test",
        "supersedes": "rondo-publication-critic-measurement-freeze-v3",
        "asset_lock_sha256": sha256_file(args.asset_lock),
        "environment_lock_sha256": inputs[
            "eval/environments/publication-critic-plan054/uv.lock"
        ],
        "input_manifest": inputs,
        "input_manifest_sha256": calibration["input_manifest_sha256"],
        "implementation_manifest": implementation,
        "implementation_manifest_sha256": calibration[
            "implementation_manifest_sha256"
        ],
        "qualification_identity": _qualification_identity(),
        "model_identity": _model_identity(),
        "input_template_binding": calibration["input_template_binding"],
        "scoring_identity": _scoring_identity(
            threshold,
            calibration["input_template_binding"],
        ),
        "inference_contract": _frozen_runtime_identity(),
        "adopted_window_tokens": ADOPTED_CONTEXT_WINDOW,
        "window_facts": _window_facts(),
        "sample_identity": _sample_identity(inputs),
        "temporary_threshold_source": {
            "run_id": calibration["run_id"],
            "calibration_code_commit": calibration["code_commit"],
            "calibration_result_sha256": projection["artifact_sha256"],
            "calibration_watchdog_summary_sha256": projection["watchdog"][
                "summary_sha256"
            ],
            "rule": calibration["temporary_threshold"]["rule"],
            "rule_sha256": inputs[
                "eval/templates/publication-critic/temporary-threshold-rule-v1.json"
            ],
            "measurement_labels_used": False,
        },
        "measurement_metrics": list(MEASUREMENT_METRICS),
        "declared_slices": list(DECLARED_SLICES),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(freeze, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise RunnerError("measurement freeze output already exists") from exc
    return freeze


def verify_measurement_freeze(
    freeze_path: Path,
    repo_root: Path,
    asset_lock_path: Path,
    runtime_arguments: Mapping[str, Any] | None = None,
    calibration_result_path: Path | None = None,
    calibration_watchdog_path: Path | None = None,
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
            "input_template_binding",
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
    if freeze["purpose"] != "Plan 054 M3-A2 exact Skywork base-model measurement freeze v4":
        raise RunnerError("measurement freeze purpose drifted")
    if freeze["cohort_scope"] != "representative_and_boundary_examples_not_future_unseen_test":
        raise RunnerError("measurement cohort scope drifted")
    if freeze["supersedes"] != "rondo-publication-critic-measurement-freeze-v3":
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
    asset_lock = load_json(asset_lock_path)
    if not isinstance(asset_lock, dict):
        raise RunnerError("measurement asset lock drifted")
    if freeze["environment_lock_sha256"] != expected_inputs[
        "eval/environments/publication-critic-plan054/uv.lock"
    ]:
        raise RunnerError("measurement environment lock drifted")

    qualification = freeze["qualification_identity"]
    expected_qualification = _qualification_identity()
    if qualification != expected_qualification:
        raise RunnerError("measurement qualification identity drifted")
    expected_model = _model_identity()
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
    expected_binding = _input_template_binding(
        expected_inputs,
        expected_implementation,
        asset_lock,
    )
    if freeze["input_template_binding"] != expected_binding:
        raise RunnerError("measurement input template binding drifted")
    expected_scoring = _scoring_identity(float(threshold), expected_binding)
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
    expected_window_facts = _window_facts()
    if freeze["window_facts"] != expected_window_facts:
        raise RunnerError("measurement window facts drifted")

    expected_sample_identity = _sample_identity(expected_inputs)
    if freeze["sample_identity"] != expected_sample_identity:
        raise RunnerError("measurement sample identity drifted")

    threshold_source = freeze["temporary_threshold_source"]
    if not isinstance(threshold_source, dict):
        raise RunnerError("measurement threshold source is invalid")
    _require_exact_keys(
        threshold_source,
        {
            "run_id",
            "calibration_code_commit",
            "calibration_result_sha256",
            "calibration_watchdog_summary_sha256",
            "rule",
            "rule_sha256",
            "measurement_labels_used",
        },
        "threshold source",
    )
    if (
        not isinstance(threshold_source["run_id"], str)
        or not threshold_source["run_id"].startswith("plan054-")
        or not isinstance(threshold_source["calibration_code_commit"], str)
        or len(threshold_source["calibration_code_commit"]) != 40
        or not isinstance(threshold_source["calibration_result_sha256"], str)
        or len(threshold_source["calibration_result_sha256"]) != 64
        or not isinstance(
            threshold_source["calibration_watchdog_summary_sha256"], str
        )
        or len(threshold_source["calibration_watchdog_summary_sha256"]) != 64
        or threshold_source["rule"]
        != "maximize_balanced_accuracy_then_minimize_false_pass_then_maximize_threshold_v1"
        or threshold_source["rule_sha256"]
        != expected_inputs[
            "eval/templates/publication-critic/temporary-threshold-rule-v1.json"
        ]
        or threshold_source["measurement_labels_used"] is not False
    ):
        raise RunnerError("measurement threshold source drifted")
    if (calibration_result_path is None) != (calibration_watchdog_path is None):
        raise RunnerError("measurement calibration evidence is incomplete")
    if calibration_result_path is not None and calibration_watchdog_path is not None:
        calibration, projection = _verify_calibration_result(
            calibration_result_path,
            calibration_watchdog_path,
            repo_root,
            asset_lock,
        )
        if (
            projection["artifact_sha256"]
            != threshold_source["calibration_result_sha256"]
            or projection["watchdog"]["summary_sha256"]
            != threshold_source["calibration_watchdog_summary_sha256"]
            or calibration["run_id"] != threshold_source["run_id"]
            or calibration["code_commit"]
            != threshold_source["calibration_code_commit"]
            or calibration["input_manifest_sha256"]
            != freeze["input_manifest_sha256"]
            or calibration["implementation_manifest_sha256"]
            != freeze["implementation_manifest_sha256"]
            or calibration["scoring_identity"] != freeze["scoring_identity"]
            or calibration["temporary_threshold"]["rule"]
            != threshold_source["rule"]
            or calibration["temporary_threshold"]["threshold"] != threshold
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
    asset_lock = verify_asset_lock(args.asset_lock, args.snapshot)
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
        args.calibration_watchdog_summary,
    )
    _calibration, calibration_evidence = _verify_calibration_result(
        args.calibration_result,
        args.calibration_watchdog_summary,
        repo_root,
        asset_lock,
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
        model_rows = _archive_model_rows(
            measurement,
            parity_outputs,
            archive,
            batch_size=args.batch_size,
        )
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
            "calibration_evidence": {
                key: value
                for key, value in calibration_evidence.items()
                if key != "watchdog"
            },
            "watchdog": {"calibration": calibration_evidence["watchdog"]},
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
                "forward_timing_basis": "standard_right_batch_wall_clock_with_explicit_amortized_compute",
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
        archive.write_json(
            "completion.json",
            {"status": "complete", "raw_result_sha256": result["raw_result_sha256"]},
        )
        return result
    except BaseException as exc:
        archive.write_json("failure.json", body_free_runner_exception(exc))
        raise


def finalize_measurement(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve(strict=True)
    _require_committed_freeze(repo_root, args.freeze)
    runtime_arguments = {
        "device": FROZEN_DEVICE,
        "dtype": FROZEN_DTYPE,
        "cpu_threads": FROZEN_CPU_THREADS,
        "batch_size": FROZEN_BATCH_SIZE,
    }
    freeze = verify_measurement_freeze(
        args.freeze,
        repo_root,
        args.asset_lock,
        runtime_arguments,
        args.calibration_result,
        args.calibration_watchdog_summary,
    )
    asset_lock = load_json(args.asset_lock)
    if not isinstance(asset_lock, dict):
        raise RunnerError("measurement asset lock drifted")
    _calibration, calibration_projection = _verify_calibration_result(
        args.calibration_result,
        args.calibration_watchdog_summary,
        repo_root,
        asset_lock,
    )
    if _git_fact(repo_root, "status", "--porcelain", "--untracked-files=no"):
        raise RunnerError("tracked worktree is not clean at result finalization")
    commit = _git_fact(repo_root, "rev-parse", "HEAD")

    if args.raw_result.is_symlink() or not args.raw_result.is_file():
        raise RunnerError("raw measurement result is missing or unsafe")
    raw = load_json(args.raw_result)
    if not isinstance(raw, dict):
        raise RunnerError("raw measurement result identity drifted")
    _require_exact_keys(
        raw,
        {
            "schema",
            "run_id",
            "completed_at",
            "code_commit",
            "freeze_sha256",
            "model_identity",
            "scoring_identity",
            "sample_identity",
            "qualification_identity",
            "inference_contract",
            "cohort_scope",
            "calibration_evidence",
            "watchdog",
            "scalar_parity",
            "quality",
            "token_census",
            "environment",
            "resources",
            "measurement_rows",
        },
        "raw result",
    )
    raw_sha256 = sha256_file(args.raw_result)
    if (
        args.measurement_completion.is_symlink()
        or not args.measurement_completion.is_file()
    ):
        raise RunnerError("raw measurement completion is missing or unsafe")
    completion = load_json(args.measurement_completion)
    if completion != {"status": "complete", "raw_result_sha256": raw_sha256}:
        raise RunnerError("raw measurement completion identity drifted")
    expected_calibration_projection = {
        key: value for key, value in calibration_projection.items() if key != "watchdog"
    }
    if (
        raw["schema"] != RESULT_SCHEMA
        or not isinstance(raw["run_id"], str)
        or not raw["run_id"].startswith("plan054-")
        or raw["code_commit"] != commit
        or raw["freeze_sha256"] != sha256_file(args.freeze)
        or raw["model_identity"] != freeze["model_identity"]
        or raw["scoring_identity"] != freeze["scoring_identity"]
        or raw["sample_identity"] != freeze["sample_identity"]
        or raw["qualification_identity"] != freeze["qualification_identity"]
        or raw["inference_contract"] != freeze["inference_contract"]
        or raw["cohort_scope"]
        != "m3a2_representative_and_boundary_not_future_unseen_test"
        or raw["calibration_evidence"] != expected_calibration_projection
        or raw["watchdog"] != {"calibration": calibration_projection["watchdog"]}
    ):
        raise RunnerError("raw measurement result identity drifted")

    rows = raw["measurement_rows"]
    if not isinstance(rows, list) or len(rows) != 16:
        raise RunnerError("raw measurement rows drifted")
    expected_samples = {
        sample.sample_id: sample
        for sample in load_sample_corpus(repo_root).samples
        if sample.annotation["data_role"] == "m3a2_measurement"
    }
    expected_row_keys = {
        "sample_id",
        "data_role",
        "expected_label",
        "publication_class",
        "pair_id",
        "pair_direction",
        "slices",
        "raw_logit",
        "score",
        "standard_batch_index",
        "standard_batch_size",
        "standard_batch_elapsed_ms",
        "token_count",
        "dropped_oldest_publications",
        "predicted_label",
    }
    if any(
        not isinstance(row, dict) or not isinstance(row.get("sample_id"), str)
        for row in rows
    ) or {row["sample_id"] for row in rows} != set(expected_samples):
        raise RunnerError("raw measurement rows drifted")
    threshold = float(freeze["scoring_identity"]["threshold"])
    batch_elapsed: dict[int, float] = {}
    for position, row in enumerate(rows):
        if set(row) != expected_row_keys:
            raise RunnerError("raw measurement rows drifted")
        sample = expected_samples[row["sample_id"]]
        annotation = sample.annotation
        expected_metadata = {
            "data_role": "measurement",
            "expected_label": annotation["expected_verdict"],
            "publication_class": annotation["publication_class"],
            "pair_id": annotation["pair_id"],
            "pair_direction": annotation["pair_direction"],
            "slices": list(annotation["slices"]),
        }
        if any(row[key] != value for key, value in expected_metadata.items()):
            raise RunnerError("raw measurement rows drifted")
        try:
            raw_logit = float(row["raw_logit"])
            score = float(row["score"])
            elapsed_ms = float(row["standard_batch_elapsed_ms"])
        except (TypeError, ValueError) as exc:
            raise RunnerError("raw measurement rows drifted") from exc
        expected_batch_index = position // FROZEN_BATCH_SIZE
        if (
            not math.isfinite(raw_logit)
            or not math.isfinite(score)
            or not math.isclose(
                project_logit(raw_logit), score, rel_tol=0.0, abs_tol=1e-12
            )
            or type(row["standard_batch_index"]) is not int
            or row["standard_batch_index"] != expected_batch_index
            or type(row["standard_batch_size"]) is not int
            or row["standard_batch_size"] != FROZEN_BATCH_SIZE
            or not math.isfinite(elapsed_ms)
            or elapsed_ms < 0
            or type(row["token_count"]) is not int
            or not 0 < row["token_count"] <= ADOPTED_CONTEXT_WINDOW
            or type(row["dropped_oldest_publications"]) is not int
            or not 0 <= row["dropped_oldest_publications"] <= 4
        ):
            raise RunnerError("raw measurement rows drifted")
        prior_elapsed = batch_elapsed.setdefault(expected_batch_index, elapsed_ms)
        if elapsed_ms != prior_elapsed:
            raise RunnerError("raw measurement rows drifted")
        predicted = "pass" if float(row["score"]) >= threshold else "rewrite"
        if row.get("predicted_label") != predicted:
            raise RunnerError("raw measurement prediction drifted")
    expected_quality = summarize_measurement(rows, threshold)
    _validate_declared_quality_slices(expected_quality)
    if raw["quality"] != expected_quality:
        raise RunnerError("raw measurement quality projection drifted")
    environment = raw["environment"]
    if not isinstance(environment, dict) or set(environment) != {
        "device",
        "dtype",
        "cpu_threads",
        "batch_size",
        "model_load_seconds",
        "measurement_wall_seconds_including_model_load",
        "forward_timing_basis",
        "device_synchronization",
        "peak_reset",
    }:
        raise RunnerError("raw measurement environment drifted")
    if (
        {key: environment[key] for key in ("device", "dtype", "cpu_threads", "batch_size")}
        != runtime_arguments
        or environment["forward_timing_basis"]
        != "standard_right_batch_wall_clock_with_explicit_amortized_compute"
        or environment["device_synchronization"] != "synchronous_cpu_forward"
        or environment["peak_reset"]
        != "not_reset_process_lifetime_peak_includes_model_load"
    ):
        raise RunnerError("raw measurement environment drifted")
    for key in ("model_load_seconds", "measurement_wall_seconds_including_model_load"):
        value = environment[key]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise RunnerError("raw measurement environment drifted")
    resources = raw["resources"]
    if (
        not isinstance(resources, dict)
        or set(resources) != {"process_rss_bytes", "process_peak_rss_bytes", "cuda"}
        or type(resources["process_rss_bytes"]) is not int
        or resources["process_rss_bytes"] < 0
        or type(resources["process_peak_rss_bytes"]) is not int
        or resources["process_peak_rss_bytes"] < 0
        or resources["cuda"] is not None
    ):
        raise RunnerError("raw measurement resource projection drifted")
    parity = raw["scalar_parity"]
    expected_parity_coverage = [
        "single",
        "repeat_single",
        "standard_right_batch",
        "standard_left_batch",
        "alternate_right_batch",
    ]
    if (
        not isinstance(parity, dict)
        or set(parity)
        != {
            "schema",
            "row_count",
            "batch_size",
            "standard_order",
            "alternate_order",
            "absolute_tolerance",
            "max_absolute_projected_delta",
            "coverage",
            "rows",
        }
        or parity.get("schema") != "rondo-publication-critic-scalar-parity-v2"
        or parity.get("row_count") != 16
        or parity.get("batch_size") != FROZEN_BATCH_SIZE
        or parity.get("standard_order") != [row["sample_id"] for row in rows]
        or parity.get("alternate_order")
        != [row["sample_id"] for row in rows[::2]]
        + [row["sample_id"] for row in rows[1::2]]
        or parity.get("absolute_tolerance") != PARITY_ABSOLUTE_TOLERANCE
        or parity.get("coverage") != expected_parity_coverage
        or not isinstance(parity.get("max_absolute_projected_delta"), (int, float))
        or isinstance(parity.get("max_absolute_projected_delta"), bool)
        or not 0.0
        <= float(parity["max_absolute_projected_delta"])
        <= PARITY_ABSOLUTE_TOLERANCE
        or not isinstance(parity.get("rows"), list)
        or len(parity["rows"]) != 16
    ):
        raise RunnerError("raw measurement scalar parity drifted")
    rows_by_id = {row["sample_id"]: row for row in rows}
    parity_row_keys = {
        "sample_id",
        "single_score",
        "repeat_score",
        "standard_right_batch_score",
        "standard_left_batch_score",
        "alternate_right_batch_score",
        "max_absolute_projected_delta",
    }
    observed_max_delta = 0.0
    for parity_row in parity["rows"]:
        if not isinstance(parity_row, dict) or set(parity_row) != parity_row_keys:
            raise RunnerError("raw measurement scalar parity drifted")
        scored = rows_by_id.get(parity_row["sample_id"])
        try:
            single = float(parity_row["single_score"])
            comparisons = [
                float(parity_row[key])
                for key in (
                    "repeat_score",
                    "standard_right_batch_score",
                    "standard_left_batch_score",
                    "alternate_right_batch_score",
                )
            ]
            row_delta = float(parity_row["max_absolute_projected_delta"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RunnerError("raw measurement scalar parity drifted") from exc
        actual_delta = max(abs(single - value) for value in comparisons)
        if (
            scored is None
            or not all(math.isfinite(value) for value in [single, *comparisons, row_delta])
            or not math.isclose(
                comparisons[1],
                float(scored["score"]),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            or not math.isclose(actual_delta, row_delta, rel_tol=0.0, abs_tol=1e-12)
            or row_delta > PARITY_ABSOLUTE_TOLERANCE
        ):
            raise RunnerError("raw measurement scalar parity drifted")
        observed_max_delta = max(observed_max_delta, row_delta)
    if not math.isclose(
        observed_max_delta,
        float(parity["max_absolute_projected_delta"]),
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise RunnerError("raw measurement scalar parity drifted")

    measurement_watchdog = load_watchdog_summary(args.measurement_watchdog_summary)
    result = dict(raw)
    result["raw_result_sha256"] = raw_sha256
    result["watchdog"] = {
        "calibration": calibration_projection["watchdog"],
        "measurement": measurement_watchdog,
    }
    expected_output = repo_root / _TRACKED_RESULT_RELATIVE
    if args.tracked_result.resolve(strict=False) != expected_output.resolve(strict=False):
        raise RunnerError("tracked result output is not the canonical path")
    args.tracked_result.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.tracked_result.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise RunnerError("tracked result already exists; refusing overwrite") from exc
    return result


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

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--snapshot", type=Path, required=True)
    freeze.add_argument("--asset-lock", type=Path, required=True)
    freeze.add_argument("--calibration-result", type=Path, required=True)
    freeze.add_argument("--calibration-watchdog-summary", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.set_defaults(function=create_measurement_freeze)

    measurement = subparsers.add_parser("measure")
    common(measurement)
    measurement.add_argument("--freeze", type=Path, required=True)
    measurement.add_argument("--calibration-result", type=Path, required=True)
    measurement.add_argument("--calibration-watchdog-summary", type=Path, required=True)
    measurement.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    measurement.add_argument("--dtype", choices=("bfloat16", "float32"), default=FROZEN_DTYPE)
    measurement.add_argument("--cpu-threads", type=int, default=4)
    measurement.add_argument("--batch-size", type=int, default=4)
    measurement.set_defaults(function=run_measurement)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--freeze", type=Path, required=True)
    finalize.add_argument("--asset-lock", type=Path, required=True)
    finalize.add_argument("--calibration-result", type=Path, required=True)
    finalize.add_argument("--calibration-watchdog-summary", type=Path, required=True)
    finalize.add_argument("--raw-result", type=Path, required=True)
    finalize.add_argument("--measurement-completion", type=Path, required=True)
    finalize.add_argument("--measurement-watchdog-summary", type=Path, required=True)
    finalize.add_argument("--tracked-result", type=Path, required=True)
    finalize.set_defaults(function=finalize_measurement)
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
        "run_id": result.get("run_id")
        or result.get("temporary_threshold_source", {}).get("run_id"),
        "status": "complete",
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
