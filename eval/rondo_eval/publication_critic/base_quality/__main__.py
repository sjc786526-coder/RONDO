"""Command-line entrypoint for Plan 079 commissioning and formal runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

from ..full_model_training.contract import (
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    sha256_bytes,
    sha256_file,
    write_exclusive,
)
from ..full_model_training.plan066_bundle import verify_plan066_bundle
from ..selection.release import release_sha256, validate_release
from .contract import (
    BaseQualityError,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    QUALITY_FLOORS,
    RUN_SPEC_SCHEMA,
    RUNTIME_CONTRACT,
    validate_run_spec,
)
from .runner import (
    prepare_validation_release,
    recompute_result,
    run_evaluation,
    validate_result,
)
from .snapshot import load_model_lock, validate_snapshot_receipt, verify_snapshot


def _write_json(path: Path, value: Any) -> None:
    write_exclusive(path, pretty_json_bytes(value))


def _git_source(repo_root: Path) -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise BaseQualityError("git_source_identity_unavailable") from exc
    return commit, not bool(status.strip())


def command_verify_snapshot(args: argparse.Namespace) -> None:
    _write_json(args.output, verify_snapshot(args.snapshot, args.model_lock))


def command_prepare_release(args: argparse.Namespace) -> None:
    release, _ = prepare_validation_release(args.bundle, args.repo_root)
    _write_json(args.output, release)


def command_freeze(args: argparse.Namespace) -> None:
    release = validate_release(read_json(args.release))
    bundle = verify_plan066_bundle(args.bundle)
    receipt = validate_snapshot_receipt(read_json(args.snapshot_receipt))
    load_model_lock(args.model_lock)
    if receipt["model_lock_sha256"] != sha256_file(args.model_lock):
        raise BaseQualityError("snapshot_receipt_lock_mismatch")
    commit, clean = _git_source(args.repo_root)
    spec = {
        "schema": RUN_SPEC_SCHEMA,
        "mode": args.mode,
        "run_id": args.run_id,
        "source": {
            "git_commit": commit,
            "tracked_source_clean": clean,
            "source_archive_sha256": sha256_file(args.source_archive),
            "environment_lock_path": args.environment_lock_relative,
            "environment_lock_sha256": sha256_file(args.environment_lock),
        },
        "model": {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "model_lock_sha256": sha256_file(args.model_lock),
            "snapshot_receipt_sha256": sha256_bytes(canonical_json_bytes(receipt)),
            "snapshot_content_sha256": receipt["snapshot_content_sha256"],
        },
        "input": {
            "dataset_revision": "v8",
            "bundle_manifest_sha256": bundle["bundle_manifest_sha256"],
            "release_sha256": release_sha256(release),
            "candidate_count": 55,
            "boundary_pair_count": 19,
            "within_pass_pair_count": 7,
            "unseen_test_rows_available": 0,
        },
        "runtime": {**RUNTIME_CONTRACT, "cpu_threads": args.cpu_threads},
        "cloud": {
            "pod_id": args.pod_id,
            "network_volume_id": args.network_volume_id,
            "data_center_id": args.data_center_id,
            "gpu_model": args.gpu_model,
            "container_image": args.container_image,
            "cuda_host_version": args.cuda_host_version,
        },
        "quality_floors": dict(QUALITY_FLOORS),
    }
    _write_json(args.output, validate_run_spec(spec))


def command_run(args: argparse.Namespace) -> None:
    scores, runtime, result = run_evaluation(
        spec_value=read_json(args.run_spec),
        release_value=read_json(args.release),
        snapshot=args.snapshot,
        model_lock_path=args.model_lock,
        source_archive=args.source_archive,
        environment_lock=args.environment_lock,
        bundle_root=args.bundle,
        runs_root=args.runs_root,
        repo_root=args.repo_root,
        attempt_id=args.attempt_id,
    )
    print(
        json.dumps(
            {
                "terminal": result["terminal"],
                "scored_count": runtime["scored_count"],
                "typed_failure_count": runtime["typed_failure_count"],
                "scores_sha256": sha256_bytes(canonical_json_bytes(scores)),
            },
            sort_keys=True,
        )
    )


def command_recompute(args: argparse.Namespace) -> None:
    spec = read_json(args.run_spec)
    release = read_json(args.release)
    scores = read_json(args.scores)
    runtime = read_json(args.runtime)
    result = recompute_result(spec, release, scores, runtime)
    if args.expected is not None:
        validate_result(read_json(args.expected), spec, release, scores, runtime)
    _write_json(args.output, result)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publication-critic-plan079")
    commands = parser.add_subparsers(dest="command", required=True)

    snapshot = commands.add_parser("verify-snapshot")
    snapshot.add_argument("--snapshot", type=Path, required=True)
    snapshot.add_argument("--model-lock", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    snapshot.set_defaults(handler=command_verify_snapshot)

    release = commands.add_parser("prepare-release")
    release.add_argument("--bundle", type=Path, required=True)
    release.add_argument("--repo-root", type=Path, required=True)
    release.add_argument("--output", type=Path, required=True)
    release.set_defaults(handler=command_prepare_release)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--mode", choices=("commissioning", "formal"), required=True)
    freeze.add_argument("--run-id", required=True)
    freeze.add_argument("--repo-root", type=Path, required=True)
    freeze.add_argument("--source-archive", type=Path, required=True)
    freeze.add_argument("--environment-lock", type=Path, required=True)
    freeze.add_argument("--environment-lock-relative", required=True)
    freeze.add_argument("--model-lock", type=Path, required=True)
    freeze.add_argument("--snapshot-receipt", type=Path, required=True)
    freeze.add_argument("--release", type=Path, required=True)
    freeze.add_argument("--bundle", type=Path, required=True)
    freeze.add_argument("--pod-id", required=True)
    freeze.add_argument("--network-volume-id", required=True)
    freeze.add_argument("--data-center-id", required=True)
    freeze.add_argument("--gpu-model", required=True)
    freeze.add_argument("--container-image", required=True)
    freeze.add_argument("--cuda-host-version", required=True)
    freeze.add_argument("--cpu-threads", type=int, default=4)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.set_defaults(handler=command_freeze)

    run = commands.add_parser("run")
    run.add_argument("--run-spec", type=Path, required=True)
    run.add_argument("--release", type=Path, required=True)
    run.add_argument("--snapshot", type=Path, required=True)
    run.add_argument("--model-lock", type=Path, required=True)
    run.add_argument("--source-archive", type=Path, required=True)
    run.add_argument("--environment-lock", type=Path, required=True)
    run.add_argument("--bundle", type=Path, required=True)
    run.add_argument("--runs-root", type=Path, required=True)
    run.add_argument("--repo-root", type=Path, required=True)
    run.add_argument("--attempt-id", required=True)
    run.set_defaults(handler=command_run)

    recompute = commands.add_parser("recompute")
    recompute.add_argument("--run-spec", type=Path, required=True)
    recompute.add_argument("--release", type=Path, required=True)
    recompute.add_argument("--scores", type=Path, required=True)
    recompute.add_argument("--runtime", type=Path, required=True)
    recompute.add_argument("--expected", type=Path)
    recompute.add_argument("--output", type=Path, required=True)
    recompute.set_defaults(handler=command_recompute)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        args.handler(args)
    except BaseQualityError as exc:
        print(json.dumps({"status": "failed", "code": exc.code}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
