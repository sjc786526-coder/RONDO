"""Explicit Plan 096 freeze, run, history, and independent-recompute CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Sequence

from ...config import RepoPaths, load_allowlisted_secret_values
from ..identity import canonical_json_bytes
from .contract import CloudQualityError, build_freeze, validate_freeze
from .history import project_historical_results
from .runner import (
    RustSubprocessEvaluator,
    recompute,
    run_commissioning,
    run_formal,
    tracked_projection,
)


def _load(path: Path) -> Any:
    if path.is_symlink() or not path.is_file():
        raise CloudQualityError("cli_input_unsafe")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CloudQualityError("cli_input_invalid") from exc


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise CloudQualityError("cli_input_unsafe")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CloudQualityError("cli_input_invalid") from exc
    return digest.hexdigest()


def _write_exclusive_json(path: Path, value: Any) -> None:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise CloudQualityError("cli_output_parent_unsafe")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise CloudQualityError("cli_output_exists_or_unsafe") from exc


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
        raise CloudQualityError("cli_git_identity_unavailable") from exc
    if status:
        raise CloudQualityError("cli_source_not_clean")
    return commit


def _evaluator(args: argparse.Namespace, freeze: dict[str, Any]) -> RustSubprocessEvaluator:
    paths = RepoPaths.discover(Path.cwd())
    credential = load_allowlisted_secret_values(paths, ("DEEPSEEK_API_KEY",))
    retry = freeze["retry"]
    timeout_seconds = (
        retry["max_attempts"] * retry["request_timeout_seconds"]
        + sum(retry["backoff_seconds"])
        + 5.0
    )
    return RustSubprocessEvaluator(
        executable=args.executable,
        arguments=("--descriptor", str(args.descriptor)),
        credential_env=credential,
        timeout_seconds=timeout_seconds,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m rondo_eval.publication_critic.cloud_quality")
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("validate-freeze")
    freeze.add_argument("--freeze", type=Path, required=True)

    history = commands.add_parser("history")
    history.add_argument("--one-seven", type=Path, required=True)
    history.add_argument("--four", type=Path, required=True)

    prepare = commands.add_parser("prepare-freeze")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--descriptor", type=Path, required=True)
    prepare.add_argument("--static-contract", type=Path, required=True)
    prepare.add_argument("--environment-lock", type=Path, required=True)
    prepare.add_argument("--executable", type=Path, required=True)
    prepare.add_argument("--price-observed-at", required=True)
    prepare.add_argument("--commissioning", type=Path)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--mode", choices=("commissioning", "formal"), required=True)
    prepare.add_argument("--output", type=Path, required=True)

    for name in ("run-commissioning", "run-formal"):
        run = commands.add_parser(name)
        run.add_argument("--freeze", type=Path, required=True)
        run.add_argument("--input", type=Path, required=True)
        run.add_argument("--runs-root", type=Path, required=True)
        run.add_argument("--executable", type=Path, required=True)
        run.add_argument("--descriptor", type=Path, required=True)

    command = commands.add_parser("recompute")
    command.add_argument("--freeze", type=Path, required=True)
    command.add_argument("--release", type=Path, required=True)
    command.add_argument("--scores", type=Path, required=True)
    command.add_argument("--expected", type=Path)
    command.add_argument("--tracked", action="store_true")
    command.add_argument("--one-seven", type=Path)
    command.add_argument("--four", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-freeze":
        _print(validate_freeze(_load(args.freeze)))
        return 0
    if args.command == "history":
        _print(project_historical_results(_load(args.one_seven), _load(args.four)))
        return 0
    if args.command == "prepare-freeze":
        freeze = build_freeze(
            source={
                "git_commit": _clean_commit(args.repo),
                "tracked_source_clean": True,
                "tracked_contract_sha256": _sha256_file(args.static_contract),
                "environment_lock_sha256": _sha256_file(args.environment_lock),
                "scalar_executable_sha256": _sha256_file(args.executable),
            },
            descriptor_sha256=_sha256_file(args.descriptor),
            price_observed_at=args.price_observed_at,
            commissioning=(
                None if args.commissioning is None else _load(args.commissioning)
            ),
            run_id=args.run_id,
            mode=args.mode,
        )
        _write_exclusive_json(args.output, freeze)
        _print(
            {
                "freeze_sha256": hashlib.sha256(
                    canonical_json_bytes(freeze)
                ).hexdigest()
            }
        )
        return 0
    if args.command in {"run-commissioning", "run-formal"}:
        freeze = validate_freeze(_load(args.freeze))
        evaluator = _evaluator(args, freeze)
        if args.command == "run-commissioning":
            result, binding = run_commissioning(
                freeze,
                _load(args.input),
                runs_root=args.runs_root,
                evaluator=evaluator,
            )
            _print({"result": result, "binding": binding})
        else:
            _, result = run_formal(
                freeze,
                _load(args.input),
                runs_root=args.runs_root,
                evaluator=evaluator,
            )
            _print(result)
        return 0
    result = recompute(_load(args.freeze), _load(args.release), _load(args.scores))
    if args.expected is not None:
        expected = _load(args.expected)
        if canonical_json_bytes(result) != canonical_json_bytes(expected):
            raise CloudQualityError("cli_expected_result_mismatch")
    if args.tracked:
        if (args.one_seven is None) != (args.four is None):
            raise CloudQualityError("cli_history_pair_required")
        historical = (
            project_historical_results(_load(args.one_seven), _load(args.four))
            if args.one_seven is not None and args.four is not None
            else None
        )
        _print(tracked_projection(_load(args.freeze), result, historical=historical))
    else:
        _print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
