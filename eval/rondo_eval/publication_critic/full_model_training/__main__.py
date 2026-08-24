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
from .plan066_bundle import (
    PLAN066_MODEL_CONTRACT_RELATIVE,
    PLAN066_RECIPE_RELATIVE,
    prepare_plan066_bundle,
)
from .plan066_runner import (
    run_plan066_commissioning_resume,
    run_plan066_commissioning_start,
    run_plan066_formal_resume,
    run_plan066_formal_start,
)
from .plan066_finalize import finalize_plan066_receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="publication-critic-full-model-training")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare-bundle")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)

    prepare_plan066 = commands.add_parser("prepare-plan066-bundle")
    prepare_plan066.add_argument("--repo", type=Path, required=True)
    prepare_plan066.add_argument("--output", type=Path, required=True)

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
    dependencies.add_argument(
        "--profile", choices=("plan060", "plan066")
    )

    finalize = commands.add_parser("finalize-formal")
    finalize.add_argument("--formal-start", type=Path, required=True)
    finalize.add_argument("--formal-pending", type=Path, required=True)
    finalize.add_argument("--provider-facts", type=Path, required=True)
    finalize.add_argument("--budget-policy", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)

    finalize_plan066 = commands.add_parser("finalize-plan066-formal")
    finalize_plan066.add_argument("--formal-start", type=Path, required=True)
    finalize_plan066.add_argument("--formal-pending", type=Path, required=True)
    finalize_plan066.add_argument("--provider-facts", type=Path, required=True)
    finalize_plan066.add_argument("--budget-policy", type=Path, required=True)
    finalize_plan066.add_argument("--output", type=Path, required=True)

    for name in (
        "commission-start",
        "commission-resume",
        "formal-start",
        "formal-resume",
        "plan066-commission-start",
        "plan066-commission-resume",
        "plan066-formal-start",
        "plan066-formal-resume",
    ):
        run = commands.add_parser(name)
        run.add_argument("--bundle", type=Path, required=True)
        run.add_argument("--model-snapshot", type=Path, required=True)
        run.add_argument("--output", type=Path, required=True)
        run.add_argument("--recipe", type=Path)
        run.add_argument("--winner-lock", type=Path, required=True)
        run.add_argument("--container-image", required=True)
        if name.startswith("formal-") or name.startswith("plan066-formal-"):
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
    if args.command == "prepare-plan066-bundle":
        return prepare_plan066_bundle(args.repo, args.output)
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
        bundle_receipt = verify_bundle(args.bundle)
        inferred_profile = (
            "plan066"
            if bundle_receipt.get("schema") == "rondo-publication-critic-plan066-bundle-v1"
            else "plan060"
        )
        if args.profile is not None and args.profile != inferred_profile:
            raise FullModelTrainingError("dependency_profile_bundle_mismatch")
        profile = args.profile or inferred_profile
        relative = (
            PLAN066_MODEL_CONTRACT_RELATIVE
            if profile == "plan066"
            else MODEL_CONTRACT_RELATIVE
        )
        contract = _validate_model_contract(
            read_json(args.bundle / relative), profile=profile
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
    if args.command == "finalize-plan066-formal":
        return finalize_plan066_receipt(
            formal_start_path=args.formal_start,
            formal_pending_path=args.formal_pending,
            provider_facts_path=args.provider_facts,
            budget_policy_path=args.budget_policy,
            output_path=args.output,
        )
    plan066 = args.command.startswith("plan066-")
    recipe = args.recipe or (
        args.bundle / (PLAN066_RECIPE_RELATIVE if plan066 else RECIPE_RELATIVE)
    )
    if args.command == "plan066-commission-start":
        return run_plan066_commissioning_start(
            bundle_root=args.bundle,
            model_snapshot=args.model_snapshot,
            output_root=args.output,
            recipe_path=recipe,
            winner_lock_path=args.winner_lock,
            container_image=args.container_image,
        )
    if args.command == "plan066-commission-resume":
        return run_plan066_commissioning_resume(
            bundle_root=args.bundle,
            model_snapshot=args.model_snapshot,
            output_root=args.output,
            checkpoint_root=args.checkpoint,
            recipe_path=recipe,
            winner_lock_path=args.winner_lock,
            container_image=args.container_image,
        )
    if args.command == "plan066-formal-start":
        return run_plan066_formal_start(
            bundle_root=args.bundle,
            model_snapshot=args.model_snapshot,
            output_root=args.output,
            recipe_path=recipe,
            winner_lock_path=args.winner_lock,
            dependency_identity_path=args.dependency_identity,
            dependency_freeze_path=args.dependency_freeze,
            container_image=args.container_image,
        )
    if args.command == "plan066-formal-resume":
        return run_plan066_formal_resume(
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
