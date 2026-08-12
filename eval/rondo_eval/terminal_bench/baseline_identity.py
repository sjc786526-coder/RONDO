"""Generate the next immutable P2/B7 paid identity from retired local facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from decimal import Decimal
from pathlib import Path

from ..config import RepoPaths, load_runtime_config
from ..frozen_model_catalog import load_frozen_model_catalog
from .baseline import (
    CAMPAIGN_ACTIVE_POINTER_PATH,
    CAMPAIGN_CAP_USD,
    CAMPAIGN_MAX_RUNS,
    CampaignIdentity,
    CampaignLockRegistration,
    campaign_lock_registry,
    load_campaign_identity_path,
    load_historical_campaign_identity,
)


class CampaignIdentityGenerationError(RuntimeError):
    """The next identity cannot be derived without resetting or guessing facts."""


def required_successor_prior(
    paths: RepoPaths,
    *,
    version: int | None = None,
) -> Decimal:
    registry = campaign_lock_registry(paths)
    latest = registry[-1] if version is None else next(
        (item for item in registry if item.version == version),
        None,
    )
    if latest is None:
        raise CampaignIdentityGenerationError("predecessor campaign is not registered")
    lock = _read_json(paths.worktree_root / latest.path)
    try:
        prior = Decimal(lock["budget"]["prior_estimated_usd"])
    except (KeyError, TypeError, ArithmeticError) as exc:
        raise CampaignIdentityGenerationError(
            "predecessor lock has no cumulative prior debit"
        ) from exc
    state_path = (
        paths.common_root / "eval-data/campaigns" / latest.campaign_id / "state.json"
    )
    state = _read_json(state_path)
    slots = state.get("slots")
    if (
        state.get("campaign_id") != latest.campaign_id
        or state.get("campaign_lock_sha256") != latest.lock_sha256
        or state.get("status") not in {"passed", "failed", "blocked"}
        or not isinstance(slots, list)
        or any(not isinstance(row, dict) for row in slots)
        or any(row.get("status") in {"planned", "running"} for row in slots)
    ):
        raise CampaignIdentityGenerationError("predecessor campaign is not terminal")
    wire_rows = [row for row in slots if row.get("slot_id") == "wire-canary"]
    if len(wire_rows) != 1:
        raise CampaignIdentityGenerationError("predecessor wire canary state is ambiguous")
    wire = Decimal(str(wire_rows[0].get("estimated_usd")))
    receipt_path = (
        paths.common_root
        / "eval-data/campaigns"
        / latest.campaign_id
        / "wire-canary/receipt.json"
    )
    wire_digest = wire_rows[0].get("result_record_sha256")
    if wire_digest is not None:
        receipt = _read_json(receipt_path)
        if (
            Decimal(str(receipt.get("estimated_spent_usd"))) != wire
            or hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            != wire_digest
        ):
            raise CampaignIdentityGenerationError("wire canary debit is inconsistent")
    elif wire != 0:
        raise CampaignIdentityGenerationError("wire canary debit has no receipt")
    paid_rows = [
        row
        for row in slots
        if isinstance(row, dict) and row.get("slot_id") != "wire-canary"
    ]
    state_by_run = {
        row.get("run_id"): row
        for row in paid_rows
    }
    if None in state_by_run or len(state_by_run) != len(paid_rows):
        raise CampaignIdentityGenerationError("predecessor state run IDs are invalid")
    budget_path = paths.common_root / "eval-data/budgets" / f"{latest.batch_id}.json"
    if not budget_path.exists() and not budget_path.is_symlink():
        if any(row.get("status") != "skipped" for row in paid_rows):
            raise CampaignIdentityGenerationError(
                "predecessor paid state has no budget ledger"
            )
        return (prior + wire).quantize(Decimal("0.000001"))
    budget = _read_json(budget_path)
    runs = budget.get("runs")
    if budget.get("batch_id") != latest.batch_id or not isinstance(runs, dict):
        raise CampaignIdentityGenerationError("predecessor budget identity is invalid")
    if any(run_id not in state_by_run for run_id in runs):
        raise CampaignIdentityGenerationError("predecessor budget has an unknown run")
    paid = Decimal(0)
    for run_id, run in runs.items():
        requests = run.get("requests") if isinstance(run, dict) else None
        if not isinstance(requests, dict) or any(
            request.get("status") != "settled"
            for request in requests.values()
            if isinstance(request, dict)
        ) or any(not isinstance(request, dict) for request in requests.values()):
            raise CampaignIdentityGenerationError(
                "predecessor budget has an unsettled request"
            )
        spent = Decimal(str(run.get("spent_usd")))
        state_row = state_by_run[run_id]
        if (
            state_row.get("status") not in {"completed", "failed"}
            or Decimal(str(state_row.get("estimated_usd"))) != spent
        ):
            raise CampaignIdentityGenerationError(
                "predecessor state and budget debit disagree"
            )
        if sum(Decimal(str(item.get("charged_usd"))) for item in requests.values()) != spent:
            raise CampaignIdentityGenerationError("predecessor budget debit is inconsistent")
        paid += spent
    for run_id, row in state_by_run.items():
        if (
            row.get("status") in {"completed", "failed"}
            and Decimal(str(row.get("estimated_usd"))) != 0
            and run_id not in runs
        ):
            raise CampaignIdentityGenerationError(
                "predecessor state debit is absent from the budget"
            )
    return (prior + wire + paid).quantize(Decimal("0.000001"))


def generate_successor_lock(
    paths: RepoPaths,
    *,
    run_id_date: str,
    run_id_sequence_base: int,
) -> tuple[Path, Decimal]:
    _require_clean_worktree(paths.worktree_root)
    if re.fullmatch(r"[0-9]{8}", run_id_date) is None:
        raise CampaignIdentityGenerationError("run ID date must contain eight digits")
    if (
        isinstance(run_id_sequence_base, bool)
        or not isinstance(run_id_sequence_base, int)
        or run_id_sequence_base < 1
    ):
        raise CampaignIdentityGenerationError("run ID sequence base is invalid")
    pointer_path = paths.worktree_root / CAMPAIGN_ACTIVE_POINTER_PATH
    pointer = _read_json(pointer_path)
    if set(pointer) != {"schema_version", "active_lock"} or pointer.get(
        "schema_version"
    ) != 1:
        raise CampaignIdentityGenerationError("active campaign pointer is invalid")
    registry = campaign_lock_registry(paths)
    latest = registry[-1]
    if pointer["active_lock"] not in {None, latest.path.as_posix()}:
        raise CampaignIdentityGenerationError("active campaign pointer is not the latest lock")
    predecessor = load_historical_campaign_identity(paths, latest.version)
    predecessor.validate_provider(load_runtime_config(paths).paid_provider_projection())
    _validate_frozen_inputs(paths, predecessor)
    next_version = latest.version + 1
    validate_successor_run_range(
        registry,
        run_id_date=run_id_date,
        run_id_sequence_base=run_id_sequence_base,
    )
    prior = required_successor_prior(paths, version=latest.version)
    if prior >= CAMPAIGN_CAP_USD:
        raise CampaignIdentityGenerationError("campaign cap has no remaining capacity")
    lock = _read_json(paths.worktree_root / latest.path)
    lock.update(
        {
            "campaign_id": f"p2-b7-canary-baseline-v{next_version}",
            "batch_id": f"p2-b7-canary-sol-sol-v{next_version}",
            "run_id_date": run_id_date,
            "run_id_sequence_base": run_id_sequence_base,
        }
    )
    lock["budget"] = {
        **lock["budget"],
        "campaign_cap_usd": f"{CAMPAIGN_CAP_USD:.6f}",
        "prior_estimated_usd": f"{prior:.6f}",
    }
    relative = Path(f"eval/locks/p2-b7-canary-baseline-v{next_version}.json")
    destination = paths.worktree_root / relative
    if destination.exists() or destination.is_symlink():
        raise CampaignIdentityGenerationError("successor campaign lock already exists")
    _atomic_json(destination, lock, replace=False)
    try:
        generated = load_campaign_identity_path(paths, relative)
        if (
            generated.campaign_id != lock["campaign_id"]
            or generated.batch_id != lock["batch_id"]
            or generated.budget["prior_estimated_usd"] != f"{prior:.6f}"
        ):
            raise CampaignIdentityGenerationError("generated campaign lock did not validate")
        _atomic_json(
            pointer_path,
            {"schema_version": 1, "active_lock": relative.as_posix()},
            replace=True,
        )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return destination, prior


def _require_clean_worktree(root: Path) -> None:
    try:
        completed = subprocess.run(
            ("git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CampaignIdentityGenerationError(
            "campaign worktree state is unavailable"
        ) from exc
    if completed.returncode != 0 or completed.stdout:
        raise CampaignIdentityGenerationError(
            "campaign identity generation requires a clean worktree"
        )


def _validate_frozen_inputs(paths: RepoPaths, identity: CampaignIdentity) -> None:
    for bundle in identity.bundles.values():
        path = paths.common_root / bundle["manifest_path"]
        if (
            path.is_symlink()
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest()
            != bundle["manifest_sha256"]
        ):
            raise CampaignIdentityGenerationError("frozen bundle manifest drifted")
    seccomp = paths.worktree_root / identity.no_api_seccomp["profile_path"]
    if (
        seccomp.is_symlink()
        or not seccomp.is_file()
        or hashlib.sha256(seccomp.read_bytes()).hexdigest()
        != identity.no_api_seccomp["source_sha256"]
    ):
        raise CampaignIdentityGenerationError("frozen seccomp profile drifted")
    selected = identity.selected_profile
    projection = load_frozen_model_catalog(
        paths.common_root,
        source_commit=selected["frozen_codex_model_catalog_source_commit"],
        main_model=selected["effective_main_model"],
        guardian_model=selected["effective_guardian_model"],
    )
    identity.validate_frozen_model_catalog(
        source_commit=projection.source_commit,
        sha256=projection.sha256,
        main_model=projection.main_model,
        guardian_model=projection.guardian_model,
    )


def validate_successor_run_range(
    registry: tuple[CampaignLockRegistration, ...],
    *,
    run_id_date: str,
    run_id_sequence_base: int,
) -> None:
    requested = {
        (run_id_date, run_id_sequence_base + index)
        for index in range(CAMPAIGN_MAX_RUNS)
    }
    historical = {
        (item.run_id_date, item.run_id_sequence_base + index)
        for item in registry
        for index in range(item.max_run_slots)
    }
    if requested.intersection(historical):
        raise CampaignIdentityGenerationError("new run ID range collides with history")


def _read_json(path: Path) -> dict[str, object]:
    try:
        if path.is_symlink() or not path.is_file():
            raise OSError
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignIdentityGenerationError("campaign fact is unavailable") from exc
    if not isinstance(value, dict):
        raise CampaignIdentityGenerationError("campaign fact is not an object")
    return value


def _atomic_json(path: Path, value: object, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if not replace and (path.exists() or path.is_symlink()):
            raise CampaignIdentityGenerationError("campaign destination already exists")
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rondo_eval.terminal_bench.baseline_identity")
    parser.add_argument("--run-id-date", required=True)
    parser.add_argument("--run-id-sequence-base", required=True, type=int)
    args = parser.parse_args(argv)
    paths = RepoPaths.discover(Path.cwd())
    path, prior = generate_successor_lock(
        paths,
        run_id_date=args.run_id_date,
        run_id_sequence_base=args.run_id_sequence_base,
    )
    print(json.dumps({"lock_path": path.as_posix(), "prior_estimated_usd": f"{prior:.6f}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
