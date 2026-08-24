"""Command-line entrypoint for the Plan 060 portable training runtime."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .bundle import (
    create_deterministic_archive,
    extract_verified_archive,
    prepare_bundle,
    verify_bundle,
)
from .checkpoint import read_checkpoint_metadata, require_new_process, verify_checkpoint
from .contract import (
    FullModelTrainingError,
    pretty_json_bytes,
    read_json,
    sha256_file,
    write_exclusive,
)
from .finalize import finalize_formal_receipt
from .runner import (
    MODEL_CONTRACT_RELATIVE,
    RECIPE_RELATIVE,
    capture_dependency_identity,
    run_commissioning_resume,
    run_commissioning_start,
    run_formal_resume,
    run_formal_start,
    _validate_model_contract,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publication-critic-full-model-training")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare-bundle")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)

    verify = commands.add_parser("verify-bundle")
    verify.add_argument("--bundle", type=Path, required=True)

    archive = commands.add_parser("create-archive")
    archive.add_argument("--bundle", type=Path, required=True)
    archive.add_argument("--output", type=Path, required=True)

    extract = commands.add_parser("extract-archive")
    extract.add_argument("--archive", type=Path, required=True)
    extract.add_argument("--expected-sha256", required=True)
    extract.add_argument("--output", type=Path, required=True)

    verify_checkpoint_parser = commands.add_parser("verify-checkpoint")
    verify_checkpoint_parser.add_argument("--checkpoint", type=Path, required=True)
    verify_checkpoint_parser.add_argument("--require-new-process", action="store_true")

    dependencies = commands.add_parser("capture-dependencies")
    dependencies.add_argument("--bundle", type=Path, required=True)
    dependencies.add_argument("--container-image", required=True)
    dependencies.add_argument(
        "--status", choices=("commissioning_observed", "formal_frozen"), required=True
    )
    dependencies.add_argument("--complete-freeze", type=Path)
    dependencies.add_argument("--output", type=Path, required=True)

    finalize = commands.add_parser("finalize-formal")
    finalize.add_argument("--formal-start", type=Path, required=True)
    finalize.add_argument("--formal-pending", type=Path, required=True)
    finalize.add_argument("--provider-facts", type=Path, required=True)
    finalize.add_argument("--budget-policy", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)

    for name in (
        "commission-start",
        "commission-resume",
        "formal-start",
        "formal-resume",
    ):
        run = commands.add_parser(name)
        run.add_argument("--bundle", type=Path, required=True)
        run.add_argument("--model-snapshot", type=Path, required=True)
        run.add_argument("--output", type=Path, required=True)
        run.add_argument("--recipe", type=Path)
        run.add_argument("--winner-lock", type=Path, required=True)
        run.add_argument("--container-image", required=True)
        if name.startswith("formal-"):
            run.add_argument("--dependency-identity", type=Path, required=True)
            run.add_argument("--dependency-freeze", type=Path, required=True)
        if name.endswith("-resume"):
            run.add_argument("--checkpoint", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _dispatch(args)
    except FullModelTrainingError as exc:
        failure = {
            "status": "failed",
            "failure_kind": type(exc).__name__,
            "code": exc.code,
        }
        if exc.detail is not None:
            failure["detail"] = exc.detail
        print(
            json.dumps(failure, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "prepare-bundle":
        return prepare_bundle(args.repo, args.output)
    if args.command == "verify-bundle":
        return verify_bundle(args.bundle)
    if args.command == "create-archive":
        return create_deterministic_archive(args.bundle, args.output)
    if args.command == "extract-archive":
        return extract_verified_archive(
            args.archive,
            args.output,
            expected_sha256=args.expected_sha256,
        )
    if args.command == "verify-checkpoint":
        result = verify_checkpoint(args.checkpoint)
        if args.require_new_process:
            process = require_new_process(read_checkpoint_metadata(args.checkpoint))
            result = {**result, "resume_process": process.as_dict(), "new_process": True}
        return result
    if args.command == "capture-dependencies":
        verify_bundle(args.bundle)
        contract = _validate_model_contract(
            read_json(args.bundle / MODEL_CONTRACT_RELATIVE)
        )
        identity = capture_dependency_identity(
            container_image=args.container_image,
            status=args.status,
            model_contract=contract,
            complete_freeze_sha256=(
                sha256_file(args.complete_freeze)
                if args.complete_freeze is not None
                else None
            ),
        )
        write_exclusive(args.output, pretty_json_bytes(identity))
        return {"status": "written", "output": str(args.output)}
    if args.command == "finalize-formal":
        return finalize_formal_receipt(
            formal_start_path=args.formal_start,
            formal_pending_path=args.formal_pending,
            provider_facts_path=args.provider_facts,
            budget_policy_path=args.budget_policy,
            output_path=args.output,
        )
    recipe = args.recipe or (args.bundle / RECIPE_RELATIVE)
    if args.command == "commission-start":
        return run_commissioning_start(
            bundle_root=args.bundle,
            model_snapshot=args.model_snapshot,
            output_root=args.output,
            recipe_path=recipe,
            winner_lock_path=args.winner_lock,
            container_image=args.container_image,
        )
    if args.command == "commission-resume":
        return run_commissioning_resume(
            bundle_root=args.bundle,
            model_snapshot=args.model_snapshot,
            output_root=args.output,
            checkpoint_root=args.checkpoint,
            recipe_path=recipe,
            winner_lock_path=args.winner_lock,
            container_image=args.container_image,
        )
    if args.command == "formal-start":
        return run_formal_start(
            bundle_root=args.bundle,
            model_snapshot=args.model_snapshot,
            output_root=args.output,
            recipe_path=recipe,
            winner_lock_path=args.winner_lock,
            dependency_identity_path=args.dependency_identity,
            dependency_freeze_path=args.dependency_freeze,
            container_image=args.container_image,
        )
    if args.command == "formal-resume":
        return run_formal_resume(
            bundle_root=args.bundle,
            model_snapshot=args.model_snapshot,
            output_root=args.output,
            checkpoint_root=args.checkpoint,
            recipe_path=recipe,
            winner_lock_path=args.winner_lock,
            dependency_identity_path=args.dependency_identity,
            dependency_freeze_path=args.dependency_freeze,
            container_image=args.container_image,
        )
    raise FullModelTrainingError("command_not_implemented")


if __name__ == "__main__":
    raise SystemExit(main())
