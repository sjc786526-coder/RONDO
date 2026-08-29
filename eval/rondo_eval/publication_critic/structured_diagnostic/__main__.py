"""Explicit Plan 100 freeze, run/resume, and independent-recompute CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from ...config import RepoPaths, load_allowlisted_secret_values
from ..identity import canonical_json_bytes, sha256_bytes
from .archive import DiagnosticArchive
from .cost import Plan100BudgetLedger
from .freeze import build_freeze, validate_commissioning_binding, validate_freeze
from .release import load_commissioning_public_items, load_validation_release
from .runner import (
    CommandTokenRecounter,
    DiagnosticRunnerError,
    RustSubprocessEvaluator,
    build_commissioning_binding,
    recompute_commissioning,
    recompute_formal,
    run_batch,
    tracked_projection,
)


def _load(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise DiagnosticRunnerError("cli_input_unsafe")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiagnosticRunnerError("cli_input_invalid") from exc


def _print(value: Any) -> None:
    print(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
    )


def _write_exclusive(path: Path, value: Any) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise DiagnosticRunnerError("cli_output_parent_unsafe")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise DiagnosticRunnerError("cli_output_exists_or_unsafe") from exc


def _clean_commit(repo: Path) -> str:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ).stdout
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise DiagnosticRunnerError("cli_git_identity_unavailable") from exc
    if status:
        raise DiagnosticRunnerError("cli_source_not_clean")
    return commit


def _sha_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise DiagnosticRunnerError("cli_input_unsafe")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise DiagnosticRunnerError("cli_input_invalid") from exc
    return digest.hexdigest()


def _recount_identity(executable: Path, arguments: Sequence[str]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "executable_sha256": _sha_file(executable),
                "arguments": list(arguments),
            }
        )
    )


def _archive(args: argparse.Namespace, freeze: dict[str, Any]) -> DiagnosticArchive:
    archive = DiagnosticArchive(args.runs_root, freeze["run_id"], freeze["mode"])
    return archive.resume(freeze) if args.resume else archive.start(freeze)


def _evaluator(
    args: argparse.Namespace, freeze: dict[str, Any]
) -> RustSubprocessEvaluator:
    if _sha_file(args.executable) != freeze["source"]["diagnostic_executable_sha256"]:
        raise DiagnosticRunnerError("cli_executable_identity_drifted")
    if _sha_file(args.descriptor) != freeze["source"]["descriptor_sha256"]:
        raise DiagnosticRunnerError("cli_descriptor_identity_drifted")
    recount_arguments = tuple(args.recount_arg or ())
    recount_identity = _recount_identity(args.recount_executable, recount_arguments)
    if recount_identity != freeze["source"]["token_recounter_sha256"]:
        raise DiagnosticRunnerError("cli_recounter_identity_drifted")
    paths = RepoPaths.discover(Path.cwd())
    credential = load_allowlisted_secret_values(paths, ("DEEPSEEK_API_KEY",))
    retry = freeze["request"]
    timeout = (
        retry["max_attempts"] * retry["request_timeout_ms"] + retry["retry_backoff_ms"]
    ) / 1000 + 5
    return RustSubprocessEvaluator(
        executable=args.executable,
        arguments=("--descriptor", str(args.descriptor)),
        credential_env=credential,
        timeout_seconds=timeout,
        recounter=CommandTokenRecounter(
            command=(str(args.recount_executable), *recount_arguments),
            identity_sha256=recount_identity,
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.publication_critic.structured_diagnostic"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-freeze")
    validate.add_argument("--freeze", type=Path, required=True)

    prepare = commands.add_parser("prepare-freeze")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--contract", type=Path, required=True)
    prepare.add_argument("--executable", type=Path, required=True)
    prepare.add_argument("--descriptor", type=Path, required=True)
    prepare.add_argument("--environment-lock", type=Path, required=True)
    prepare.add_argument("--recount-executable", type=Path, required=True)
    prepare.add_argument("--recount-arg", action="append")
    prepare.add_argument("--commissioning-binding", type=Path)
    prepare.add_argument("--mode", choices=("commissioning", "formal"), required=True)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--output", type=Path, required=True)

    for name in ("run-commissioning", "run-formal"):
        run = commands.add_parser(name)
        run.add_argument("--freeze", type=Path, required=True)
        run.add_argument("--runs-root", type=Path, required=True)
        run.add_argument("--ledger", type=Path, required=True)
        run.add_argument("--executable", type=Path, required=True)
        run.add_argument("--descriptor", type=Path, required=True)
        run.add_argument("--recount-executable", type=Path, required=True)
        run.add_argument("--recount-arg", action="append")
        run.add_argument("--resume", action="store_true")

    recompute = commands.add_parser("recompute")
    recompute.add_argument("--freeze", type=Path, required=True)
    recompute.add_argument("--runs-root", type=Path, required=True)
    recompute.add_argument("--tracked", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-freeze":
        _print(validate_freeze(_load(args.freeze)))
        return 0
    if args.command == "prepare-freeze":
        recount_arguments = tuple(args.recount_arg or ())
        commissioning_value = (
            None
            if args.commissioning_binding is None
            else _load(args.commissioning_binding)
        )
        commissioning = (
            None
            if commissioning_value is None
            else _sha_file(args.commissioning_binding)
        )
        freeze = build_freeze(
            mode=args.mode,
            run_id=args.run_id,
            git_commit=_clean_commit(args.repo),
            diagnostic_contract_sha256=_sha_file(args.contract),
            executable_sha256=_sha_file(args.executable),
            descriptor_sha256=_sha_file(args.descriptor),
            environment_lock_sha256=_sha_file(args.environment_lock),
            token_recounter_sha256=_recount_identity(
                args.recount_executable, recount_arguments
            ),
            commissioning_binding_sha256=commissioning,
        )
        if args.mode == "formal":
            validate_commissioning_binding(commissioning_value, freeze)
        _write_exclusive(args.output, freeze)
        _print(
            {"freeze_sha256": hashlib.sha256(canonical_json_bytes(freeze)).hexdigest()}
        )
        return 0
    if args.command in {"run-commissioning", "run-formal"}:
        freeze = validate_freeze(_load(args.freeze))
        expected_ledger = args.runs_root.parent / "budget-ledger.json"
        if (
            not args.runs_root.is_absolute()
            or args.runs_root.name != "runs"
            or not args.ledger.is_absolute()
            or args.ledger != expected_ledger
        ):
            raise DiagnosticRunnerError("cli_task_wide_budget_path_invalid")
        expected_mode = (
            "commissioning" if args.command == "run-commissioning" else "formal"
        )
        if freeze["mode"] != expected_mode:
            raise DiagnosticRunnerError("cli_run_mode_mismatch")
        archive = _archive(args, freeze)
        ledger = Plan100BudgetLedger(args.ledger)
        evaluator = _evaluator(args, freeze)
        release = load_validation_release()
        items = (
            load_commissioning_public_items()
            if expected_mode == "commissioning"
            else release.public_items
        )
        execution = run_batch(
            freeze,
            items,
            archive=archive,
            ledger=ledger,
            evaluator=evaluator,
        )
        if expected_mode == "commissioning":
            result = recompute_commissioning(
                freeze,
                items,
                archive,
                ledger,
                evaluator.recounter,
            )
            if result["complete"]:
                archive.bind_json("commissioning-result.json", result)
                binding = build_commissioning_binding(freeze, result)
                archive.bind_json("commissioning-binding.json", binding)
                _print({"execution": execution, "binding": binding})
            else:
                _print({"execution": execution, "binding": None})
        else:
            result = recompute_formal(freeze, release, archive, ledger)
            if result["observations_complete"]:
                archive.bind_json("result.json", result)
            if result["complete"]:
                archive.claim_formal_result(freeze, result)
            _print(result)
        return 0
    freeze = validate_freeze(_load(args.freeze))
    if (
        not args.runs_root.is_absolute()
        or args.runs_root.name != "runs"
        or freeze["mode"] != "formal"
    ):
        raise DiagnosticRunnerError("cli_recompute_path_or_mode_invalid")
    archive = DiagnosticArchive(
        args.runs_root, freeze["run_id"], freeze["mode"]
    ).reopen_read_only(freeze)
    ledger = Plan100BudgetLedger(args.runs_root.parent / "budget-ledger.json")
    result = recompute_formal(freeze, load_validation_release(), archive, ledger)
    _print(tracked_projection(result) if args.tracked else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
