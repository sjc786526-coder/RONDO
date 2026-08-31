"""Explicit Plan 101 freeze, run/resume, and independent-recompute CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from ...config import RepoPaths, load_allowlisted_secret_values
from ..identity import canonical_json_bytes
from ..structured_diagnostic.cost import Plan100BudgetLedger
from ..structured_diagnostic.release import (
    load_commissioning_public_items,
    load_validation_release,
)
from ..structured_diagnostic.runner import DiagnosticRunnerError, RustSubprocessEvaluator
from .archive import ComparisonArchive
from .freeze import build_freeze, validate_freeze
from .report import markdown_report
from .runner import (
    build_commissioning_binding,
    decide_supplement,
    recompute_commissioning,
    recompute_formal,
    run_batch,
    tracked_projection,
    validate_commissioning_binding,
)

_TASK_ROOT_RELATIVE = Path("eval-data/publication-critic/plan101")
_CONTRACT_RELATIVE = Path(
    "eval/templates/publication-critic/plan101-thinking-comparison-contract-v1.json"
)
_PROMPT_RELATIVE = Path("multidev/codex-rs/publication-critic/src/cloud_diagnostic.rs")
_ROUND_LOG_NAME = "round-log.json"
_CONDITIONS = ("thinking_off", "thinking_on")
_CONDITION_THINKING = {"thinking_off": "disabled", "thinking_on": "enabled"}


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


def _write_text_exclusive(path: Path, text: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


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


def _repo_paths(repo: Path) -> RepoPaths:
    paths = RepoPaths.discover(repo)
    if repo.resolve(strict=True) != paths.worktree_root:
        raise DiagnosticRunnerError("cli_repo_is_not_current_worktree_root")
    return paths


def _task_paths(paths: RepoPaths) -> tuple[Path, Path, Path]:
    task_root = paths.common_root / _TASK_ROOT_RELATIVE
    return task_root, task_root / "runs", task_root / "budget-ledger.json"


def _require_task_paths(
    args: argparse.Namespace, paths: RepoPaths
) -> tuple[Path, Path]:
    _, expected_runs, expected_ledger = _task_paths(paths)
    if (
        not args.runs_root.is_absolute()
        or args.runs_root != expected_runs
        or not args.ledger.is_absolute()
        or args.ledger != expected_ledger
    ):
        raise DiagnosticRunnerError("cli_task_wide_budget_path_invalid")
    return expected_runs, expected_ledger


def _validate_runtime_identities(
    args: argparse.Namespace, freeze: dict[str, Any], paths: RepoPaths
) -> None:
    source = freeze["source"]
    if _clean_commit(args.repo) != source["git_commit"]:
        raise DiagnosticRunnerError("cli_git_identity_drifted")
    expected_contract = paths.worktree_root / _CONTRACT_RELATIVE
    try:
        contract = args.contract.resolve(strict=True)
        expected_contract = expected_contract.resolve(strict=True)
    except OSError as exc:
        raise DiagnosticRunnerError("cli_contract_identity_unavailable") from exc
    if contract != expected_contract:
        raise DiagnosticRunnerError("cli_contract_path_invalid")
    for path, field, code in (
        (args.contract, "diagnostic_contract_sha256", "cli_contract_identity_drifted"),
        (args.executable, "diagnostic_executable_sha256", "cli_executable_identity_drifted"),
        (args.descriptor, "descriptor_sha256", "cli_descriptor_identity_drifted"),
    ):
        if _sha_file(path) != source[field]:
            raise DiagnosticRunnerError(code)


def _preregistered(contract_path: Path) -> list[Any]:
    contract = _load(contract_path)
    rows = contract.get("commissioning", {}).get("preregistered_observations")
    if not isinstance(rows, list):
        raise DiagnosticRunnerError("cli_preregistered_observations_invalid")
    return rows


def _load_round_log(task_root: Path) -> list[Any]:
    path = task_root / _ROUND_LOG_NAME
    if not path.exists() and not path.is_symlink():
        return []
    value = _load(path)
    rounds = value.get("rounds") if isinstance(value, dict) else None
    return rounds if isinstance(rounds, list) else []


def _require_prompt_source(repo: Path, contract_path: Path) -> None:
    contract = _load(contract_path)
    expected = contract.get("comparison", {}).get("prompt_candidate", {}).get(
        "source_sha256"
    )
    if _sha_file(repo / _PROMPT_RELATIVE) != expected:
        raise DiagnosticRunnerError("cli_prompt_source_drifted")


def _evaluators(
    args: argparse.Namespace, freeze: dict[str, Any]
) -> dict[str, RustSubprocessEvaluator]:
    paths = RepoPaths.discover(Path.cwd())
    credential = load_allowlisted_secret_values(paths, ("DEEPSEEK_API_KEY",))
    retry = freeze["request"]
    timeout = (
        retry["max_attempts"] * retry["request_timeout_ms"] + retry["retry_backoff_ms"]
    ) / 1000 + 5
    return {
        condition: RustSubprocessEvaluator(
            executable=args.executable,
            arguments=("--descriptor", str(args.descriptor)),
            credential_env=credential,
            timeout_seconds=timeout,
            recounter=None,
            thinking=_CONDITION_THINKING[condition],
        )
        for condition in _CONDITIONS
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.publication_critic.thinking_comparison"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-freeze")
    prepare.add_argument("--repo", type=Path, required=True)
    prepare.add_argument("--contract", type=Path, required=True)
    prepare.add_argument("--executable", type=Path, required=True)
    prepare.add_argument("--descriptor", type=Path, required=True)
    prepare.add_argument("--mode", choices=("commissioning", "formal"), required=True)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--thinking-off-repeats", type=int, required=True)
    prepare.add_argument("--thinking-on-repeats", type=int, required=True)
    prepare.add_argument("--missing-usage-rmb", required=True)
    prepare.add_argument("--commissioning-binding", type=Path)
    prepare.add_argument("--output", type=Path, required=True)

    for name in ("run-commissioning", "run-formal"):
        run = commands.add_parser(name)
        run.add_argument("--repo", type=Path, required=True)
        run.add_argument("--freeze", type=Path, required=True)
        run.add_argument("--runs-root", type=Path, required=True)
        run.add_argument("--ledger", type=Path, required=True)
        run.add_argument("--contract", type=Path, required=True)
        run.add_argument("--executable", type=Path, required=True)
        run.add_argument("--descriptor", type=Path, required=True)
        run.add_argument("--commissioning-binding", type=Path)
        run.add_argument("--resume", action="store_true")

    decide = commands.add_parser("decide-supplement")
    decide.add_argument("--repo", type=Path, required=True)
    decide.add_argument("--freeze", type=Path, required=True)
    decide.add_argument("--runs-root", type=Path, required=True)
    decide.add_argument("--ledger", type=Path, required=True)

    recompute = commands.add_parser("recompute")
    recompute.add_argument("--freeze", type=Path, required=True)
    recompute.add_argument("--runs-root", type=Path, required=True)
    recompute.add_argument("--tracked-json", type=Path)
    recompute.add_argument("--tracked-md", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "prepare-freeze":
        paths = _repo_paths(args.repo)
        commissioning_value = (
            None
            if args.commissioning_binding is None
            else _load(args.commissioning_binding)
        )
        commissioning = (
            None
            if args.commissioning_binding is None
            else _sha_file(args.commissioning_binding)
        )
        freeze = build_freeze(
            mode=args.mode,
            run_id=args.run_id,
            git_commit=_clean_commit(args.repo),
            diagnostic_contract_sha256=_sha_file(args.contract),
            executable_sha256=_sha_file(args.executable),
            descriptor_sha256=_sha_file(args.descriptor),
            thinking_off_repeats=args.thinking_off_repeats,
            thinking_on_repeats=args.thinking_on_repeats,
            missing_usage_rmb=Decimal(args.missing_usage_rmb),
            commissioning_binding_sha256=commissioning,
        )
        _require_prompt_source(args.repo, args.contract)
        if args.mode == "formal":
            validate_commissioning_binding(commissioning_value, freeze)
        _write_exclusive(args.output, freeze)
        _print(
            {"freeze_sha256": hashlib.sha256(canonical_json_bytes(freeze)).hexdigest()}
        )
        return 0
    if args.command in {"run-commissioning", "run-formal"}:
        paths = _repo_paths(args.repo)
        freeze = validate_freeze(_load(args.freeze))
        _require_task_paths(args, paths)
        expected_mode = (
            "commissioning" if args.command == "run-commissioning" else "formal"
        )
        if freeze["mode"] != expected_mode:
            raise DiagnosticRunnerError("cli_run_mode_mismatch")
        archive = ComparisonArchive(args.runs_root, freeze["run_id"], freeze["mode"])
        missing = Decimal(str(freeze["budget"]["missing_usage_rmb"]))
        _validate_runtime_identities(args, freeze, paths)
        ledger = (
            Plan100BudgetLedger(args.ledger, missing_usage_rmb=missing)
            if expected_mode == "commissioning"
            else Plan100BudgetLedger(
                args.ledger, must_exist=True, missing_usage_rmb=missing
            )
        )
        archive = archive.resume(freeze) if args.resume else archive.start(freeze)
        evaluators = _evaluators(args, freeze)
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
            evaluators=evaluators,
            allow_technical_retry=args.resume,
        )
        if expected_mode == "commissioning":
            result = recompute_commissioning(
                freeze,
                items,
                archive,
                ledger,
                preregistered_observations=_preregistered(args.contract),
            )
            if result["complete"]:
                archive.bind_json("commissioning-result.json", result)
                binding = build_commissioning_binding(freeze, result)
                archive.bind_json("commissioning-binding.json", binding)
                _print({"execution": execution, "binding": binding})
            else:
                _print({"execution": execution, "binding": None, "result": result})
        else:
            _print(
                {
                    "execution": execution,
                    "supplement": archive.load_optional_json("supplement-decision.json"),
                    "next": None
                    if archive.load_optional_json("supplement-decision.json")
                    is not None
                    else "decide-supplement",
                }
            )
        return 0
    if args.command == "decide-supplement":
        paths = _repo_paths(args.repo)
        freeze = validate_freeze(_load(args.freeze))
        _require_task_paths(args, paths)
        if freeze["mode"] != "formal":
            raise DiagnosticRunnerError("cli_run_mode_mismatch")
        archive = ComparisonArchive(
            args.runs_root, freeze["run_id"], freeze["mode"]
        ).reopen_read_only(freeze)
        missing = Decimal(str(freeze["budget"]["missing_usage_rmb"]))
        ledger = Plan100BudgetLedger(
            args.ledger, must_exist=True, missing_usage_rmb=missing
        )
        decision = decide_supplement(freeze, ledger, archive)
        _print(decision)
        return 0
    if args.command != "recompute":
        raise DiagnosticRunnerError("cli_command_invalid")
    paths = RepoPaths.discover(Path.cwd())
    freeze = validate_freeze(_load(args.freeze))
    _, expected_runs, expected_ledger = _task_paths(paths)
    if (
        not args.runs_root.is_absolute()
        or args.runs_root != expected_runs
        or freeze["mode"] != "formal"
    ):
        raise DiagnosticRunnerError("cli_recompute_path_or_mode_invalid")
    archive = ComparisonArchive(
        args.runs_root, freeze["run_id"], freeze["mode"]
    ).reopen_read_only(freeze)
    ledger = Plan100BudgetLedger(
        expected_ledger,
        must_exist=True,
        read_only=True,
        missing_usage_rmb=Decimal(str(freeze["budget"]["missing_usage_rmb"])),
    )
    task_root, _, _ = _task_paths(paths)
    result = recompute_formal(
        freeze,
        load_validation_release(),
        archive,
        ledger,
        preregistered_observations=_preregistered(
            paths.worktree_root / _CONTRACT_RELATIVE
        ),
    )
    result["disclosed_rounds"] = _load_round_log(task_root)
    if result.get("observations_complete"):
        archive.bind_json("result.json", result)
    tracked = tracked_projection(result)
    if args.tracked_json is not None:
        _write_exclusive(args.tracked_json, tracked)
    if args.tracked_md is not None:
        _write_text_exclusive(args.tracked_md, markdown_report(result, tracked))
    _print(tracked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
