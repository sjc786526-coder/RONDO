"""The Plan 073 command line: freeze, release, score, judge, select, confirm.

Every step writes exactly one exclusive artifact into the run namespace, so a
commissioning campaign can be resumed step by step while a formal campaign is
still a single write-once record.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any

from ..contract import REPO_ROOT, load_fixed_input_contract
from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from .archive import SelectionArchive
from .contract import (
    CANDIDATES,
    FREEZE_SCHEMA,
    MODES,
    SPLITS,
    SelectionError,
    default_protocol,
    default_runtime,
    freeze_sha256,
    validate_freeze,
)
from .decision import (
    build_selection_lock,
    build_unseen_confirmation,
    evaluate_validation,
    validate_runtime_facts,
    validate_unseen_confirmation,
    validate_validation_result,
)
from .judge import (
    aggregate_batches,
    batch_documents,
    build_judge_package,
    validate_package,
)
from .lock import validate_lock
from .release import build_split_release, release_sha256, validate_release


SCORES_SCHEMA = "rondo-publication-critic-plan073-candidate-scores-v1"
REPORT_SCHEMA = "rondo-publication-critic-plan073-selection-report-v1"
LATENCY_SCOPE = "offline_single_packet_model_forward_ms"
WARMUP_ITEMS = 3
DEFAULT_ENVIRONMENT_LOCK = "eval/environments/publication-critic-plan068/uv.lock"
DEFAULT_DATASET_ROOT = "training/publication-critic-v8"
DEFAULT_BUNDLE_ROOT = (
    "eval-data/publication-critic/plan068/handoff/bundle-plan066-final-01"
)


def _load_json(path: Path, label: str) -> Any:
    if path.is_symlink() or not path.is_file():
        raise SelectionError(f"{label} is missing or unsafe")
    try:
        return json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SelectionError(f"{label} is invalid JSON") from exc


def _write_json_exclusive(path: Path, value: Any) -> Path:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
        raise SelectionError("Plan 073 output path is unsafe")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise SelectionError("Plan 073 output already exists") from exc
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
    return path


def verify_formal_source(repo_root: Path, freeze: Mapping[str, Any]) -> None:
    """A formal Plan 073 step may only run from the frozen clean commit."""

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
        raise SelectionError("formal tracked source state is unavailable") from exc
    if head != source["git_commit"] or status:
        raise SelectionError("formal tracked source is not the frozen clean commit")
    lock_path = repo_root / source["environment_lock_path"]
    if (
        not lock_path.resolve().is_relative_to(repo_root.resolve())
        or lock_path.is_symlink()
        or not lock_path.is_file()
        or sha256_file(lock_path) != source["environment_lock_sha256"]
    ):
        raise SelectionError("formal environment lock identity drifted")


def _mapping_argument(values: Sequence[str], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values:
        name, separator, value = item.partition("=")
        if not separator or name not in CANDIDATES or not value or name in result:
            raise SelectionError(f"{label} argument is invalid")
        result[name] = value
    return result


def _percentile_95(values: Sequence[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise SelectionError("Plan 073 latency observation is empty")
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


# ---------------------------------------------------------------- freeze ----


def _freeze(args: argparse.Namespace) -> int:
    repo_root = args.repo_root
    snapshots = _mapping_argument(args.snapshot, "snapshot")
    if set(snapshots) != set(CANDIDATES):
        raise SelectionError("Plan 073 freeze requires all three candidate snapshots")
    dataset_root = repo_root / args.dataset_root
    manifest = dataset_root / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise SelectionError("Plan 073 dataset manifest is missing or unsafe")
    lock_path = repo_root / args.environment_lock
    if lock_path.is_symlink() or not lock_path.is_file():
        raise SelectionError("Plan 073 environment lock is missing or unsafe")
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
        raise SelectionError("Plan 073 tracked source state is unavailable") from exc
    if args.mode == "formal" and status:
        raise SelectionError("Plan 073 formal freeze requires a clean tracked source")

    freeze = {
        "schema": FREEZE_SCHEMA,
        "mode": args.mode,
        "run_id": args.run_id,
        "candidates": list(CANDIDATES),
        "dataset": {
            "revision": args.dataset_revision,
            "root": args.dataset_root,
            "manifest_sha256": sha256_file(manifest),
            "unseen_test_sealed_at_freeze": True,
        },
        "artifacts": {
            candidate: {
                "deployment_artifact_sha256": sha256_file(
                    Path(snapshots[candidate]) / "model.safetensors"
                ),
                "lineage": args.lineage[candidate],
            }
            for candidate in CANDIDATES
        },
        "runtime": default_runtime(),
        "protocol": default_protocol(),
        "source": {
            "git_commit": head,
            "tracked_source_clean": True,
            "environment_lock_path": args.environment_lock,
            "environment_lock_sha256": sha256_file(lock_path),
        },
    }
    validated = validate_freeze(freeze)
    _write_json_exclusive(args.output, validated)
    return 0


# --------------------------------------------------------------- release ----


def _release(args: argparse.Namespace) -> int:
    freeze = validate_freeze(_load_json(args.freeze, "Plan 073 freeze"))
    if freeze["mode"] == "formal":
        verify_formal_source(args.repo_root, freeze)
    lock = None
    if args.selection_lock is not None:
        lock = validate_lock(_load_json(args.selection_lock, "Plan 073 selection lock"))
        if lock["selection_freeze_sha256"] != freeze_sha256(freeze):
            raise SelectionError("Plan 073 selection lock is bound to another freeze")
    release = build_split_release(
        args.repo_root / freeze["dataset"]["root"],
        args.split,
        repo_root=args.repo_root,
        bundle_root=args.bundle_root,
        selection_lock=lock,
    )
    if release["dataset_manifest_sha256"] != freeze["dataset"]["manifest_sha256"]:
        raise SelectionError("Plan 073 dataset drifted since the freeze")
    _write_json_exclusive(args.output, release)
    return 0


# ----------------------------------------------------------------- score ----


def _score(args: argparse.Namespace) -> int:
    from ..local_deployment.inference import PublicationCriticInference

    freeze = validate_freeze(_load_json(args.freeze, "Plan 073 freeze"))
    if freeze["mode"] == "formal":
        verify_formal_source(args.repo_root, freeze)
    release = validate_release(_load_json(args.release, "Plan 073 release"))
    if release["dataset_manifest_sha256"] != freeze["dataset"]["manifest_sha256"]:
        raise SelectionError("Plan 073 release is not the frozen dataset")
    expected = freeze["artifacts"][args.candidate]["deployment_artifact_sha256"]
    snapshot_sha256 = sha256_file(args.snapshot / "model.safetensors")
    if snapshot_sha256 != expected:
        raise SelectionError("Plan 073 snapshot is not the frozen candidate artifact")

    runtime = freeze["runtime"]
    inference = PublicationCriticInference(
        args.snapshot,
        repo_root=args.repo_root,
        device=runtime["device"],
        dtype=runtime["dtype"],
        cpu_threads=runtime["cpu_threads"],
    )
    inference.load()
    rows: list[dict[str, Any]] = []
    typed_failures: list[dict[str, str]] = []
    for item in release["items"]:
        candidate_id = str(item["candidate_id"])
        try:
            result = inference.score_packet(item["packet"], sample_id=candidate_id)
        except Exception as exc:  # noqa: BLE001 - recorded as a body-free typed failure
            typed_failures.append(
                {"candidate_id": candidate_id, "failure_kind": type(exc).__name__}
            )
            continue
        if result.dropped_oldest_publications != int(item["dropped_oldest_publications"]):
            raise SelectionError("Plan 073 window omission drifted from the frozen census")
        rows.append(
            {
                "candidate_id": candidate_id,
                "raw_logit": result.raw_logit,
                "projected_score": result.projected_score,
                "token_count": result.token_count,
                "dropped_oldest_publications": result.dropped_oldest_publications,
                "model_elapsed_ms": result.model_elapsed_ms,
            }
        )
    resources = inference.resource_snapshot()
    warm = [row["model_elapsed_ms"] for row in rows[WARMUP_ITEMS:]]
    if len(warm) < runtime["warm_latency_samples"]:
        raise SelectionError("Plan 073 warm latency sampling is insufficient")
    cuda = resources.get("cuda")
    document = {
        "schema": SCORES_SCHEMA,
        "mode": freeze["mode"],
        "run_id": freeze["run_id"],
        "selection_freeze_sha256": freeze_sha256(freeze),
        "release_sha256": release_sha256(release),
        "release_split": release["split"],
        "candidate": args.candidate,
        "deployment_artifact_sha256": expected,
        "snapshot_model_sha256": snapshot_sha256,
        "snapshot_files_sha256": {
            entry.name: sha256_file(entry)
            for entry in sorted(args.snapshot.iterdir())
            if entry.is_file() and not entry.is_symlink()
        },
        "runtime_configuration": {
            "device": runtime["device"],
            "dtype": runtime["dtype"],
            "cpu_threads": runtime["cpu_threads"],
            "deployment_format": runtime["deployment_format"],
            "scoring_batch": runtime["scoring_batch"],
            "warmup_items": WARMUP_ITEMS,
            "latency_scope": LATENCY_SCOPE,
        },
        "runtime_facts": validate_runtime_facts(
            {
                "load_seconds": inference.load_seconds,
                "warm_p95_latency_ms": _percentile_95(warm),
                "peak_rss_bytes": int(resources["process_peak_rss_bytes"]),
                "peak_vram_bytes": int(cuda["max_reserved_bytes"]) if cuda else 0,
                "typed_failure_count": len(typed_failures),
                "scored_count": len(rows),
            },
            "Plan 073 score runtime",
        ),
        "warm_latency_ms": warm,
        "rows": rows,
        "typed_failures": typed_failures,
        "resources": resources,
    }
    _write_json_exclusive(args.output, document)
    return 0


def _validate_scores(value: Any, freeze: Mapping[str, Any], release: Mapping[str, Any]) -> dict[str, Any]:
    document = value if isinstance(value, Mapping) else None
    if document is None or document.get("schema") != SCORES_SCHEMA:
        raise SelectionError("Plan 073 candidate scores identity is invalid")
    if (
        document.get("selection_freeze_sha256") != freeze_sha256(freeze)
        or document.get("release_sha256") != release_sha256(release)
        or document.get("release_split") != release["split"]
        or document.get("candidate") not in CANDIDATES
    ):
        raise SelectionError("Plan 073 candidate scores are not bound to this run")
    validate_runtime_facts(document["runtime_facts"], "Plan 073 score runtime")
    return dict(document)


# The tokenizer and config files every candidate is loaded with must be the same
# object, or the three runs are not consuming one input contract.
_SHARED_SNAPSHOT_FILES = (
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
    "added_tokens.json",
    "chat_template.jinja",
    "config.json",
)


def _check_shared_input_identity(documents: Mapping[str, Mapping[str, Any]]) -> None:
    recorded = {
        candidate: document["snapshot_files_sha256"]
        for candidate, document in documents.items()
        if isinstance(document.get("snapshot_files_sha256"), Mapping)
    }
    if len(recorded) != len(documents):
        return
    for name in _SHARED_SNAPSHOT_FILES:
        digests = {files.get(name) for files in recorded.values()}
        if len(digests) != 1 or None in digests:
            raise SelectionError(
                "Plan 073 candidates were loaded with different tokenizer or config identity"
            )


def _observation(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "deployment_artifact_sha256": document["deployment_artifact_sha256"],
        "scores": {
            str(row["candidate_id"]): {
                "score": float(row["projected_score"]),
                "raw_logit": float(row["raw_logit"]),
            }
            for row in document["rows"]
        },
        "runtime": dict(document["runtime_facts"]),
    }


# ----------------------------------------------------------------- judge ----


def _judge_package(args: argparse.Namespace) -> int:
    freeze = validate_freeze(_load_json(args.freeze, "Plan 073 freeze"))
    release = validate_release(_load_json(args.release, "Plan 073 release"))
    if release["dataset_manifest_sha256"] != freeze["dataset"]["manifest_sha256"]:
        raise SelectionError("Plan 073 release is not the frozen dataset")
    salt = os.environ.get("RONDO_PLAN073_JUDGE_SALT")
    if not salt:
        raise SelectionError("Plan 073 judge salt is not configured")
    package, mapping = build_judge_package(
        release,
        load_fixed_input_contract(args.repo_root).rubric,
        salt=salt,
        package_id=args.package_id,
        batch_size=args.batch_size,
    )
    _write_json_exclusive(args.output, package)
    _write_json_exclusive(args.mapping_output, mapping)
    if args.batch_dir is not None:
        for batch_id, document in batch_documents(package).items():
            _write_json_exclusive(args.batch_dir / f"{batch_id}.json", document)
    return 0


def _judge_aggregate(args: argparse.Namespace) -> int:
    package = validate_package(_load_json(args.package, "Plan 073 judge package"))
    mapping = _load_json(args.mapping, "Plan 073 judge mapping")
    responses = [
        _load_json(path, "Plan 073 judge response") for path in args.response
    ]
    aggregate = aggregate_batches(package, mapping, responses)
    _write_json_exclusive(args.output, aggregate)
    return 0


# -------------------------------------------------------------- evaluate ----


def _observations_from_scores(
    values: Sequence[str],
    freeze: Mapping[str, Any],
    release: Mapping[str, Any],
) -> dict[str, Any]:
    scores = _mapping_argument(values, "score")
    if set(scores) != set(CANDIDATES):
        raise SelectionError("Plan 073 evaluation requires all three candidate scores")
    observations: dict[str, Any] = {}
    documents: dict[str, Mapping[str, Any]] = {}
    for candidate, path in scores.items():
        document = _validate_scores(
            _load_json(Path(path), f"Plan 073 {candidate} scores"), freeze, release
        )
        if document["candidate"] != candidate:
            raise SelectionError("Plan 073 candidate scores identity is mismatched")
        observations[candidate] = _observation(document)
        documents[candidate] = document
    _check_shared_input_identity(documents)
    return observations


def _evaluate(args: argparse.Namespace) -> int:
    freeze = validate_freeze(_load_json(args.freeze, "Plan 073 freeze"))
    if freeze["mode"] == "formal":
        verify_formal_source(args.repo_root, freeze)
    release = validate_release(_load_json(args.release, "Plan 073 release"))
    observations = _observations_from_scores(args.score, freeze, release)
    judge = (
        _load_json(args.judge_aggregate, "Plan 073 judge aggregate")
        if args.judge_aggregate is not None
        else None
    )
    package = (
        _load_json(args.judge_package, "Plan 073 judge package")
        if args.judge_package is not None
        else None
    )
    result = evaluate_validation(freeze, release, observations, judge, package)
    archive = _archive(args.runs_root, freeze)
    archive.write_json("selection-freeze.json", freeze)
    archive.write_json("validation-release-identity.json", _release_identity(release))
    archive.write_json("validation-result.json", result)
    return 0


def _archive(runs_root: Path, freeze: Mapping[str, Any]) -> SelectionArchive:
    """Open the run namespace; individual artifacts stay write-once."""

    return SelectionArchive(runs_root, freeze["run_id"], freeze["mode"]).create(
        exist_ok=True
    )


def _release_identity(release: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the release without copying its bodies into the archive."""

    return {
        "split": release["split"],
        "dataset_revision": release["dataset_revision"],
        "dataset_manifest_sha256": release["dataset_manifest_sha256"],
        "authorization": dict(release["authorization"]),
        "candidate_count": len(release["items"]),
        "pair_count": len(release["pairs"]),
        "release_sha256": release_sha256(release),
    }


def _lock(args: argparse.Namespace) -> int:
    freeze = validate_freeze(_load_json(args.freeze, "Plan 073 freeze"))
    verify_formal_source(args.repo_root, freeze)
    release = validate_release(_load_json(args.release, "Plan 073 release"))
    result = _load_json(args.validation_result, "Plan 073 validation result")
    lock = build_selection_lock(
        result,
        freeze,
        release_value=release,
        observations=_observations_from_scores(args.score, freeze, release),
        judge_aggregate=_load_json(args.judge_aggregate, "Plan 073 judge aggregate"),
        judge_package=_load_json(args.judge_package, "Plan 073 judge package"),
        dataset_root=args.repo_root / freeze["dataset"]["root"],
        bundle_root=args.bundle_root,
        repo_root=args.repo_root,
    )
    _archive(args.runs_root, freeze).write_json("selection-lock.json", lock)
    return 0


def _confirm(args: argparse.Namespace) -> int:
    freeze = validate_freeze(_load_json(args.freeze, "Plan 073 freeze"))
    verify_formal_source(args.repo_root, freeze)
    lock = validate_lock(_load_json(args.selection_lock, "Plan 073 selection lock"))
    release = validate_release(_load_json(args.release, "Plan 073 release"))
    document = _validate_scores(
        _load_json(args.score, "Plan 073 confirmation scores"), freeze, release
    )
    if document["candidate"] != lock["selected"]["candidate"]:
        raise SelectionError("Plan 073 confirmation scored a different candidate")
    observation = {"candidate": document["candidate"], **_observation(document)}
    judge_aggregate = (
        _load_json(args.judge_aggregate, "Plan 073 judge aggregate")
        if args.judge_aggregate is not None
        else None
    )
    judge_package = (
        _load_json(args.judge_package, "Plan 073 judge package")
        if args.judge_package is not None
        else None
    )
    result = build_unseen_confirmation(
        lock,
        freeze,
        release,
        observation,
        judge_aggregate,
        judge_package,
        dataset_root=args.repo_root / freeze["dataset"]["root"],
        repo_root=args.repo_root,
    )
    archive = _archive(args.runs_root, freeze)
    archive.write_json("unseen-release-identity.json", _release_identity(release))
    archive.write_json("unseen-confirmation.json", result)
    return 0


def _slice_summary(metrics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: {
            "count": row["count"],
            "pass_count": row["pass_count"],
            "rewrite_count": row["rewrite_count"],
            "accuracy": row["accuracy"],
            "false_pass": row["confusion"]["false_pass"],
            "false_rewrite": row["confusion"]["false_rewrite"],
        }
        for name, row in metrics["by_slice"].items()
    }


def _pair_summary(block: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: block[name]
        for name in ("count", "strict_wins", "ties", "strict_win_rate", "rate_with_ties")
    }


def _candidate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Keep what a reader needs to understand and recompute the decision.

    The full operating curve, per-pair rows and facet breakdowns stay in the
    ignored run archive: every one of them is recomputable from the per-item
    scores kept here plus the tracked v8 supervision.
    """

    search = report["threshold_search"]
    metrics = report["metrics"]
    curve = search["curve"]
    return {
        "candidate": report["candidate"],
        "lineage": report["lineage"],
        "deployment_artifact_sha256": report["deployment_artifact_sha256"],
        "admission": dict(report["admission"]),
        "threshold": {
            "search": search["search"],
            "rule": search["rule"],
            "search_point_count": search["search_point_count"],
            "feasible_point_count": search["feasible_point_count"],
            "feasible": search["feasible"],
            "selected": search["threshold"],
            "best_balanced_accuracy_over_curve": max(
                point["balanced_accuracy"] for point in curve
            ),
            "min_false_pass_over_curve": min(point["false_pass"] for point in curve),
        },
        "overall": metrics["overall"],
        "roc_auc": metrics["roc_auc"],
        "boundary_pairs": _pair_summary(metrics["boundary_pairs"]),
        "within_pass_pairs": _pair_summary(metrics["within_pass_pairs"]),
        "score_distribution": metrics["score_distribution"],
        "raw_logit_distribution": metrics["raw_logit_distribution"],
        "by_slice": _slice_summary(metrics),
        "errors": dict(metrics["errors"]),
        "runtime": dict(report["runtime"]),
        "judge_agreement": report["judge_agreement"],
        "rows": metrics["rows"],
    }


def _report_lock(
    result: Mapping[str, Any], freeze: Mapping[str, Any], lock_value: Any
) -> dict[str, Any]:
    """Bind a report's lock to the exact selected validation result."""

    lock = validate_lock(lock_value)
    selected = result.get("selected")
    if result.get("terminal") != "SELECTED" or selected not in CANDIDATES:
        raise SelectionError(
            "Plan 073 report cannot attach unseen evidence to an unselected result"
        )
    report = result["candidates"][selected]
    if (
        lock["validation_result_sha256"]
        != sha256_bytes(canonical_json_bytes(dict(result)))
        or lock["selection_freeze_sha256"] != freeze_sha256(freeze)
        or lock["run_id"] != result["run_id"]
        or lock["selected"]["candidate"] != selected
        or lock["selected"]["deployment_artifact_sha256"]
        != report["deployment_artifact_sha256"]
        or lock["selected"]["threshold"]["projected_score"]
        != float(report["threshold_search"]["threshold"])
        or lock["selected"]["threshold"]["method"]
        != result["method"]["threshold_rule"]
        or lock["selected"]["runtime"] != freeze["runtime"]
        or lock["runner_up"] != result["runner_up"]
        or lock["reasons"] != result["reasons"]
    ):
        raise SelectionError(
            "Plan 073 report selection lock is not bound to this validation result"
        )
    return lock


def _report(args: argparse.Namespace) -> int:
    freeze = validate_freeze(_load_json(args.freeze, "Plan 073 freeze"))
    result = validate_validation_result(
        _load_json(args.validation_result, "Plan 073 validation result"), freeze
    )
    confirmation = None
    if args.unseen_confirmation is not None:
        if (
            args.selection_lock is None
            or args.unseen_release is None
            or args.unseen_score is None
        ):
            raise SelectionError(
                "Plan 073 report needs the lock, release and raw score that produced "
                "the unseen confirmation"
            )
        lock = _report_lock(
            result,
            freeze,
            _load_json(args.selection_lock, "Plan 073 selection lock"),
        )
        release = validate_release(
            _load_json(args.unseen_release, "Plan 073 unseen release")
        )
        score = _validate_scores(
            _load_json(args.unseen_score, "Plan 073 unseen score"), freeze, release
        )
        if score["candidate"] != lock["selected"]["candidate"]:
            raise SelectionError("Plan 073 report scored a different locked candidate")
        observation = {"candidate": score["candidate"], **_observation(score)}
        judge_aggregate = (
            _load_json(args.unseen_judge_aggregate, "Plan 073 unseen Judge aggregate")
            if args.unseen_judge_aggregate is not None
            else None
        )
        judge_package = (
            _load_json(args.unseen_judge_package, "Plan 073 unseen Judge package")
            if args.unseen_judge_package is not None
            else None
        )
        confirmation = validate_unseen_confirmation(
            _load_json(args.unseen_confirmation, "Plan 073 unseen confirmation"),
            freeze,
            lock,
            release_value=release,
            observation=observation,
            judge_aggregate=judge_aggregate,
            judge_package=judge_package,
            dataset_root=args.repo_root / freeze["dataset"]["root"],
            repo_root=args.repo_root,
        )
    elif any(
        value is not None
        for value in (
            args.selection_lock,
            args.unseen_release,
            args.unseen_score,
            args.unseen_judge_aggregate,
            args.unseen_judge_package,
        )
    ):
        raise SelectionError(
            "Plan 073 report confirmation evidence was provided without a confirmation"
        )
    document = {
        "schema": REPORT_SCHEMA,
        "run_id": result["run_id"],
        "mode": result["mode"],
        "method": result["method"],
        "selection_freeze_sha256": result["selection_freeze_sha256"],
        "validation_release_sha256": result["release_sha256"],
        "cohort": result["cohort"],
        "quality_floors": freeze["protocol"]["quality_floors"],
        "runtime_gates": freeze["protocol"]["runtime_gates"],
        "judge": result["judge"],
        "candidates": {
            name: _candidate_report(report)
            for name, report in result["candidates"].items()
        },
        "ranking": result["ranking"],
        "validation_terminal": result["terminal"],
        "selected": result["selected"],
        "runner_up": result["runner_up"],
        "reasons": result["reasons"],
        "unseen_test": (
            {"state": "sealed", "reason": "no_valid_selection_lock_was_produced"}
            if confirmation is None
            else {
                "state": "released_and_confirmed",
                "selection_lock_sha256": confirmation["selection_lock_sha256"],
                "terminal": confirmation["terminal"],
                "failed_gates": confirmation["failed_gates"],
                "metrics": {
                    "threshold": confirmation["metrics"]["threshold"],
                    "overall": confirmation["metrics"]["overall"],
                    "roc_auc": confirmation["metrics"]["roc_auc"],
                    "boundary_pairs": _pair_summary(
                        confirmation["metrics"]["boundary_pairs"]
                    ),
                },
            }
        ),
        "task_terminal": (
            confirmation["terminal"]
            if confirmation is not None
            else ("NO_GO" if result["terminal"] == "NO_GO" else "INCONCLUSIVE")
        ),
    }
    _write_json_exclusive(args.output, document)
    return 0


# ------------------------------------------------------------------- cli ----


def _lineage_argument(values: Sequence[str]) -> dict[str, str]:
    lineage = _mapping_argument(values, "lineage")
    if set(lineage) != set(CANDIDATES):
        raise SelectionError("Plan 073 freeze requires lineage for all three candidates")
    return lineage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Plan 073 M3-C2 joint selection")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--mode", choices=MODES, required=True)
    freeze.add_argument("--run-id", required=True)
    freeze.add_argument("--snapshot", action="append", required=True)
    freeze.add_argument("--lineage", action="append", required=True)
    freeze.add_argument("--dataset-root", default=DEFAULT_DATASET_ROOT)
    freeze.add_argument("--dataset-revision", default="v8")
    freeze.add_argument("--environment-lock", default=DEFAULT_ENVIRONMENT_LOCK)
    freeze.add_argument("--output", type=Path, required=True)

    release = subparsers.add_parser("release")
    release.add_argument("--freeze", type=Path, required=True)
    release.add_argument("--split", choices=SPLITS, required=True)
    release.add_argument("--selection-lock", type=Path, default=None)
    release.add_argument("--bundle-root", type=Path, default=None)
    release.add_argument("--output", type=Path, required=True)

    score = subparsers.add_parser("score")
    score.add_argument("--freeze", type=Path, required=True)
    score.add_argument("--release", type=Path, required=True)
    score.add_argument("--candidate", choices=CANDIDATES, required=True)
    score.add_argument("--snapshot", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)

    package = subparsers.add_parser("judge-package")
    package.add_argument("--freeze", type=Path, required=True)
    package.add_argument("--release", type=Path, required=True)
    package.add_argument("--package-id", required=True)
    package.add_argument("--batch-size", type=int, default=8)
    package.add_argument("--output", type=Path, required=True)
    package.add_argument("--mapping-output", type=Path, required=True)
    package.add_argument("--batch-dir", type=Path, default=None)

    aggregate = subparsers.add_parser("judge-aggregate")
    aggregate.add_argument("--package", type=Path, required=True)
    aggregate.add_argument("--mapping", type=Path, required=True)
    aggregate.add_argument("--response", type=Path, action="append", required=True)
    aggregate.add_argument("--output", type=Path, required=True)

    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--freeze", type=Path, required=True)
    evaluate.add_argument("--release", type=Path, required=True)
    evaluate.add_argument("--score", action="append", required=True)
    evaluate.add_argument("--judge-aggregate", type=Path, default=None)
    evaluate.add_argument("--judge-package", type=Path, default=None)
    evaluate.add_argument("--runs-root", type=Path, required=True)

    lock = subparsers.add_parser("lock")
    lock.add_argument("--freeze", type=Path, required=True)
    lock.add_argument("--release", type=Path, required=True)
    lock.add_argument("--score", action="append", required=True)
    lock.add_argument("--judge-aggregate", type=Path, required=True)
    lock.add_argument("--judge-package", type=Path, required=True)
    lock.add_argument("--validation-result", type=Path, required=True)
    lock.add_argument("--bundle-root", type=Path, required=True)
    lock.add_argument("--runs-root", type=Path, required=True)

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--freeze", type=Path, required=True)
    confirm.add_argument("--selection-lock", type=Path, required=True)
    confirm.add_argument("--release", type=Path, required=True)
    confirm.add_argument("--score", type=Path, required=True)
    confirm.add_argument("--judge-aggregate", type=Path, default=None)
    confirm.add_argument("--judge-package", type=Path, default=None)
    confirm.add_argument("--runs-root", type=Path, required=True)

    report = subparsers.add_parser("report")
    report.add_argument("--freeze", type=Path, required=True)
    report.add_argument("--validation-result", type=Path, required=True)
    report.add_argument("--unseen-confirmation", type=Path, default=None)
    report.add_argument("--selection-lock", type=Path, default=None)
    report.add_argument("--unseen-release", type=Path, default=None)
    report.add_argument("--unseen-score", type=Path, default=None)
    report.add_argument("--unseen-judge-aggregate", type=Path, default=None)
    report.add_argument("--unseen-judge-package", type=Path, default=None)
    report.add_argument("--output", type=Path, required=True)
    return parser


_COMMANDS = {
    "freeze": _freeze,
    "release": _release,
    "score": _score,
    "judge-package": _judge_package,
    "judge-aggregate": _judge_aggregate,
    "evaluate": _evaluate,
    "lock": _lock,
    "confirm": _confirm,
    "report": _report,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "freeze":
        args.lineage = _lineage_argument(args.lineage)
    return _COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "LATENCY_SCOPE",
    "REPORT_SCHEMA",
    "SCORES_SCHEMA",
    "WARMUP_ITEMS",
    "build_parser",
    "main",
    "verify_formal_source",
]
