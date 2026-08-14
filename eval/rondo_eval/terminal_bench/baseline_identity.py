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
from ..frozen_model_catalog import (
    load_frozen_model_catalog,
    load_shared_model_catalog,
)
from ..fair_comparison import FairComparisonError, RepeatContract
from .baseline import (
    CAMPAIGN_ACTIVE_POINTER_PATH,
    CAMPAIGN_CAP_USD,
    CAMPAIGN_MAX_RUNS,
    FAIR_COMPARISON_SCHEMA_VERSION,
    CampaignIdentity,
    CampaignLockRegistration,
    _parse_comparison_block,
    campaign_baseline_contract,
    campaign_lock_registry,
    campaign_slot_total,
    load_campaign_identity_path,
    load_historical_campaign_identity,
)
from .results import validate_eval_harness_checkout
from .tasksets import load_successor_canary_catalog


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
    comparison: dict[str, object],
    campaign_cap_usd: Decimal,
) -> tuple[Path, Decimal]:
    """Mint the next campaign lock.

    Only fair-comparison (schema v7) successors may be generated.  The caller
    must supply the comparison block frozen after the pilot -- repeat contract,
    run conditions, shared catalog identity and product -- because a campaign
    whose repeat count and aggregation formula are not yet frozen must not
    exist at all.

    A v7 campaign starts fresh: it inherits no continuation and no prior spend
    from v1--v22, because those results were produced without the shared
    catalog, the stub receipts, the frozen harness commit and the interleaved
    order that the fair-comparison contract requires.  Its cap is therefore a
    separately authorized amount rather than the remainder of the historical
    envelope.
    """

    # Pure validation first: a campaign whose repeat count and aggregation
    # formula are not frozen must fail before anything is read or written.
    try:
        parsed_comparison = _parse_comparison_block(
            {"comparison": comparison},
            schema_version=FAIR_COMPARISON_SCHEMA_VERSION,
        )
        repeats = RepeatContract.from_dict(parsed_comparison["repeat_contract"])
    except (ValueError, FairComparisonError) as exc:
        raise CampaignIdentityGenerationError(
            f"successor comparison contract is not frozen: {exc}"
        ) from exc
    if (
        not isinstance(campaign_cap_usd, Decimal)
        or not campaign_cap_usd.is_finite()
        or campaign_cap_usd <= 0
        or campaign_cap_usd > CAMPAIGN_CAP_USD
        or campaign_cap_usd != campaign_cap_usd.quantize(Decimal("0.000001"))
    ):
        raise CampaignIdentityGenerationError("successor campaign cap is not authorized")
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
    # Calling this proves the predecessor's accounting is closed and settled;
    # its value is deliberately not carried into the successor's prior.
    required_successor_prior(paths, version=latest.version)
    prior = Decimal(0)
    lock = _read_json(paths.worktree_root / latest.path)
    successor_catalog = load_successor_canary_catalog(paths)
    if (
        successor_catalog.taskset_sha256 != predecessor.taskset_sha256
        or successor_catalog.terminal_bench_commit != predecessor.terminal_bench_commit
    ):
        raise CampaignIdentityGenerationError(
            "successor catalog changes the frozen taskset identity"
        )
    parsed = parsed_comparison
    conditional_repeats = repeats.repeats_per_task - 1
    slot_total = campaign_slot_total(
        task_count=len(successor_catalog.tasks),
        max_attempts=4,
        conditional_repeats_per_side=conditional_repeats,
    )
    # The frozen repeat count decides how many run IDs this campaign consumes,
    # so the collision check has to cover that range and not a fixed 321.
    validate_successor_run_range(
        registry,
        run_id_date=run_id_date,
        run_id_sequence_base=run_id_sequence_base,
        slot_total=slot_total,
    )
    _validate_successor_comparison_facts(
        paths,
        comparison=parsed,
        selected_profile=lock["selected_profile"],
        catalog=successor_catalog,
    )
    lock.update(
        {
            "schema_version": FAIR_COMPARISON_SCHEMA_VERSION,
            "campaign_id": f"p2-b7-canary-baseline-v{next_version}",
            "batch_id": f"p2-b7-canary-sol-sol-v{next_version}",
            "run_id_date": run_id_date,
            "run_id_sequence_base": run_id_sequence_base,
            "canary_catalog_sha256": successor_catalog.catalog_sha256,
            # No v1--v22 result satisfies the v7 fair-comparison conditions, so
            # none may be carried forward into its aggregate.
            "continuation": [],
            "comparison": parsed,
        }
    )
    # The Codex-only catalog digest is superseded by the shared artifact
    # identity inside the comparison block.
    lock["selected_profile"] = {
        key: value
        for key, value in lock["selected_profile"].items()
        if key
        not in {
            "frozen_codex_model_catalog_sha256",
            "frozen_codex_model_catalog_source_commit",
        }
    }
    lock["budget"] = {
        **lock["budget"],
        "campaign_cap_usd": f"{campaign_cap_usd:.6f}",
        "prior_estimated_usd": f"{prior:.6f}",
        "max_run_slots": slot_total,
    }
    lock["baseline"] = campaign_baseline_contract(
        FAIR_COMPARISON_SCHEMA_VERSION,
        conditional_repeats_per_side=conditional_repeats,
    )
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


def _validate_successor_comparison_facts(
    paths: RepoPaths,
    *,
    comparison: dict[str, object],
    selected_profile: dict[str, object],
    catalog: object,
) -> None:
    """Check the new comparison against reality before any lock is written.

    Loading the generated lock re-checks the declared conditions against the
    lock's own fields, but two of them are facts about this checkout rather
    than about the lock: whether the shared catalog really reproduces from the
    two recorded commits, and which eval-harness commit is actually present.
    A well-formed lock naming a catalog or harness that does not exist would
    otherwise stay active until execution -- possibly past the paid wire canary.
    """

    identity = comparison["catalog_identity"]
    assert isinstance(identity, dict)
    sources = {str(item["side"]): item for item in identity["sources"]}
    try:
        shared = load_shared_model_catalog(
            paths.common_root,
            upstream_source_commit=str(sources["upstream"]["commit"]),
            rondo_source_commit=str(sources["rondo"]["commit"]),
            main_model=str(selected_profile["effective_main_model"]),
            guardian_model=str(selected_profile["effective_guardian_model"]),
        )
    except (OSError, ValueError) as exc:
        raise CampaignIdentityGenerationError(
            "successor shared model catalog does not reproduce"
        ) from exc
    if shared.identity() != identity:
        raise CampaignIdentityGenerationError(
            "successor catalog identity differs from the reproduced artifact"
        )
    conditions = comparison["comparison_conditions"]
    assert isinstance(conditions, dict)
    actual_harness = validate_eval_harness_checkout(common_root=paths.common_root)
    if str(conditions["eval_harness_commit"]) != actual_harness:
        raise CampaignIdentityGenerationError(
            "successor harness commit differs from the checked-out eval harness"
        )
    declared_images = {
        str(task_id): str(digest)
        for task_id, digest in dict(conditions["task_image_digests"]).items()
    }
    actual_images = {
        item.task_id: item.image_digest for item in getattr(catalog, "tasks", ())
    }
    if declared_images != actual_images:
        raise CampaignIdentityGenerationError(
            "successor task image freeze differs from the successor catalog"
        )
    if str(conditions["provider_profile_sha256"]) != str(
        selected_profile["provider_profile_sha256"]
    ):
        raise CampaignIdentityGenerationError(
            "successor provider profile digest differs from the selected profile"
        )


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
    if identity.enforces_fair_comparison:
        # A successor may only be minted once the shared artifact still
        # reproduces from both recorded sources.
        sources = {
            str(item["side"]): item for item in identity.catalog_identity["sources"]
        }
        shared = load_shared_model_catalog(
            paths.common_root,
            upstream_source_commit=str(sources["upstream"]["commit"]),
            rondo_source_commit=str(sources["rondo"]["commit"]),
            main_model=str(selected["effective_main_model"]),
            guardian_model=str(selected["effective_guardian_model"]),
        )
        try:
            identity.validate_shared_model_catalog(shared.identity())
        except ValueError as exc:
            raise CampaignIdentityGenerationError(
                "shared model catalog drifted"
            ) from exc
        return
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
    slot_total: int = CAMPAIGN_MAX_RUNS,
) -> None:
    """Reject a run-ID base whose whole slot range overlaps history.

    ``slot_total`` must be the count this campaign will actually mint: a
    repeat contract above three widens the range well past ``CAMPAIGN_MAX_RUNS``
    and the tail is exactly where a collision would land.
    """

    if isinstance(slot_total, bool) or not isinstance(slot_total, int) or slot_total < 1:
        raise CampaignIdentityGenerationError("successor slot total is invalid")
    requested = {
        (run_id_date, run_id_sequence_base + index)
        for index in range(slot_total)
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
    parser.add_argument(
        "--comparison-contract",
        required=True,
        type=Path,
        help=(
            "JSON file holding the post-pilot frozen comparison block: "
            "repeat_contract, comparison_conditions, catalog_identity, product"
        ),
    )
    parser.add_argument(
        "--campaign-cap-usd",
        required=True,
        help=(
            "the separately authorized cap for this campaign; a v7 campaign "
            "does not inherit the historical shared envelope"
        ),
    )
    args = parser.parse_args(argv)
    try:
        campaign_cap_usd = Decimal(args.campaign_cap_usd)
    except ArithmeticError as exc:
        raise CampaignIdentityGenerationError(
            "successor campaign cap is not a decimal amount"
        ) from exc
    paths = RepoPaths.discover(Path.cwd())
    contract_path = args.comparison_contract
    if contract_path.is_symlink() or not contract_path.is_file():
        raise CampaignIdentityGenerationError("comparison contract file is unavailable")
    try:
        comparison = json.loads(contract_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CampaignIdentityGenerationError(
            "comparison contract file is unreadable"
        ) from exc
    path, prior = generate_successor_lock(
        paths,
        run_id_date=args.run_id_date,
        run_id_sequence_base=args.run_id_sequence_base,
        comparison=comparison,
        campaign_cap_usd=campaign_cap_usd,
    )
    print(json.dumps({"lock_path": path.as_posix(), "prior_estimated_usd": f"{prior:.6f}"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
