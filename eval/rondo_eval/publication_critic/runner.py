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
FREEZE_SCHEMA = "rondo-publication-critic-measurement-freeze-v1"
RESULT_SCHEMA = "rondo-publication-critic-baseline-result-v1"
PARITY_ABSOLUTE_TOLERANCE = 1e-4

_INPUT_FILES = (
    "eval/fixtures/publication-critic-v1/packets.jsonl",
    "eval/fixtures/publication-critic-v1/annotations.jsonl",
    "eval/templates/publication-critic/input-contract-v1.md",
    "eval/templates/publication-critic/qualification-rubric-v1.md",
    "eval/templates/publication-critic/product-packet-limits-v1.json",
    "eval/templates/publication-critic/render-contract-v1.json",
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


def _assert_parity(reference: float, observed: float, description: str) -> None:
    if not math.isclose(
        reference,
        observed,
        rel_tol=0.0,
        abs_tol=PARITY_ABSOLUTE_TOLERANCE,
    ):
        raise RunnerError(f"scalar parity failed: {description}")


def _score_batches(
    backend: SkyworkBackend,
    rows: Sequence[Mapping[str, Any]],
    archive: RunArchive,
    *,
    batch_size: int,
) -> list[dict[str, Any]]:
    if batch_size <= 0:
        raise RunnerError("batch size must be positive")
    outputs: list[dict[str, Any]] = []
    for start in range(0, len(rows), batch_size):
        batch_rows = rows[start : start + batch_size]
        batch_outputs = backend.score(
            [row["tokenized"] for row in batch_rows],
            padding_side="right",
        )
        if len(batch_outputs) != len(batch_rows):
            raise RunnerError("model batch result count drifted")
        for row, output in zip(batch_rows, batch_outputs):
            projected = _model_row(row, output)
            archive.write_json(f"sample-{len(outputs) + 1:03d}.json", projected)
            outputs.append(projected)
    return outputs


def run_census(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve(strict=True)
    verify_asset_lock(args.asset_lock, args.snapshot)
    archive = RunArchive(args.archive_root, args.run_id).create()
    tokenizer = load_exact_tokenizer(args.snapshot)
    rows = tokenize_corpus(repo_root, tokenizer)
    result = {
        "schema": "rondo-publication-critic-token-census-v1",
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

        shortest = min(calibration, key=lambda row: row["token_count"])
        longest = max(calibration, key=lambda row: row["token_count"])
        single = backend.score([shortest["tokenized"]], padding_side="right")[0]
        repeated = backend.score([shortest["tokenized"]], padding_side="right")[0]
        right = backend.score(
            [shortest["tokenized"], longest["tokenized"]], padding_side="right"
        )
        left = backend.score(
            [shortest["tokenized"], longest["tokenized"]], padding_side="left"
        )
        _assert_parity(single.score, repeated.score, "repeat")
        _assert_parity(single.score, right[0].score, "single versus right-padded batch")
        _assert_parity(single.score, left[0].score, "single versus left-padded batch")
        for index in range(2):
            _assert_parity(right[index].score, left[index].score, "left versus right padding")
        context = backend.verify_context_forward(ADOPTED_CONTEXT_WINDOW)
        smoke = {
            "output_shape": [1, 1],
            "tensor_index": "logits[:,0]",
            "pooling": "Qwen3ForSequenceClassification_last_non_pad_token",
            "raw_semantics": "unbounded_reward_logit_higher_is_better",
            "projection": "stable_sigmoid_v1",
            "projected_domain": [0.0, 1.0],
            "parity_absolute_tolerance": PARITY_ABSOLUTE_TOLERANCE,
            "short_sample_id": shortest["sample_id"],
            "long_sample_id": longest["sample_id"],
            "repeat_score": repeated.score,
            "single_score": single.score,
            "right_batch_scores": [output.score for output in right],
            "left_batch_scores": [output.score for output in left],
            "context_forward": context,
        }
        archive.write_json("scalar-smoke.json", smoke)
        model_rows = _score_batches(
            backend,
            calibration,
            archive,
            batch_size=args.batch_size,
        )
        threshold = derive_temporary_threshold(model_rows)
        result = {
            "schema": "rondo-publication-critic-calibration-result-v1",
            "run_id": args.run_id,
            "completed_at": utc_now(),
            "model_revision": MODEL_REVISION,
            "input_manifest": file_manifest(repo_root, _INPUT_FILES),
            "input_manifest_sha256": combined_manifest_sha256(
                file_manifest(repo_root, _INPUT_FILES)
            ),
            "census": census_summary(rows),
            "scalar_smoke": smoke,
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
) -> dict[str, Any]:
    freeze = load_json(freeze_path)
    if not isinstance(freeze, dict) or freeze.get("schema") != FREEZE_SCHEMA:
        raise RunnerError("measurement freeze schema is invalid")
    expected_inputs = freeze.get("input_manifest")
    expected_implementation = freeze.get("implementation_manifest")
    if expected_inputs != file_manifest(repo_root, _INPUT_FILES):
        raise RunnerError("measurement input manifest drifted")
    if expected_implementation != file_manifest(repo_root, _IMPLEMENTATION_FILES):
        raise RunnerError("measurement implementation manifest drifted")
    if freeze.get("asset_lock_sha256") != sha256_file(asset_lock_path):
        raise RunnerError("measurement asset lock drifted")
    scoring = freeze.get("scoring_identity")
    if not isinstance(scoring, dict):
        raise RunnerError("measurement scoring identity is missing")
    threshold = scoring.get("threshold")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        raise RunnerError("measurement threshold is invalid")
    if not math.isfinite(float(threshold)) or not 0.0 <= float(threshold) <= 1.0:
        raise RunnerError("measurement threshold is outside the frozen domain")
    if scoring.get("pass_rule") != "score_greater_than_or_equal_to_threshold":
        raise RunnerError("measurement pass rule drifted")
    if freeze.get("adopted_window_tokens") != ADOPTED_CONTEXT_WINDOW:
        raise RunnerError("measurement adopted window drifted")
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


def run_measurement(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve(strict=True)
    verify_asset_lock(args.asset_lock, args.snapshot)
    freeze = verify_measurement_freeze(args.freeze, repo_root, args.asset_lock)
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
        model_rows = _score_batches(
            backend,
            measurement,
            archive,
            batch_size=args.batch_size,
        )
        threshold = float(freeze["scoring_identity"]["threshold"])
        for row in model_rows:
            row["predicted_label"] = "pass" if row["score"] >= threshold else "rewrite"
        quality = summarize_measurement(model_rows, threshold)
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
            "cohort_scope": "m3a2_representative_and_boundary_not_future_unseen_test",
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
        archive.write_json(
            "completion.json",
            {"status": "complete", "raw_result_sha256": result["raw_result_sha256"]},
        )
        args.tracked_result.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.tracked_result.open("x", encoding="utf-8") as handle:
                json.dump(result, handle, ensure_ascii=False, allow_nan=False, indent=2)
                handle.write("\n")
        except FileExistsError as exc:
            raise RunnerError("tracked result already exists; refusing overwrite") from exc
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
    calibration.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    calibration.add_argument("--cpu-threads", type=int, default=4)
    calibration.add_argument("--batch-size", type=int, default=4)
    calibration.set_defaults(function=run_calibration)

    measurement = subparsers.add_parser("measure")
    common(measurement)
    measurement.add_argument("--freeze", type=Path, required=True)
    measurement.add_argument("--tracked-result", type=Path, required=True)
    measurement.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    measurement.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
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
