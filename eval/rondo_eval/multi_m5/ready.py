"""Offline readiness probe for Multi M-5 paid runs. Never prints secret values."""

from __future__ import annotations

import hashlib
import stat
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..config import RepoPaths
from .load import (
    M5ContractError,
    load_nondegradation_contract,
    load_runtime_identity,
    load_workflow_contract,
)

_REQUIRED_ENV_NAMES = ("OPENAI_API_KEY",)


def readiness_report(*, common_root: Path | None = None) -> dict[str, Any]:
    paths = RepoPaths.discover(Path.cwd()) if common_root is None else None
    root = common_root or paths.common_root
    missing: list[str] = []
    checks: dict[str, Any] = {}

    try:
        workflow = load_workflow_contract()
        checks["workflow_lock"] = {"ok": True, "lock_id": workflow.lock_id}
    except M5ContractError as exc:
        checks["workflow_lock"] = {"ok": False, "error": str(exc)}
        missing.append("workflow_lock")
        workflow = None

    try:
        from .campaign import load_campaign_generation, require_prior_generation

        campaign = load_campaign_generation()
        require_prior_generation(root, campaign)
        checks["campaign_generation"] = {
            "ok": True,
            "generation": campaign.generation,
            "prior_conservative_exposure_usd": str(campaign.prior_exposure_usd),
            "campaign_cap_usd": str(campaign.campaign_cap_usd),
            "shared_hard_cap_usd": str(campaign.shared_hard_cap_usd),
        }
    except M5ContractError as exc:
        checks["campaign_generation"] = {"ok": False, "error": str(exc)}
        missing.append("campaign_generation")
        campaign = None

    try:
        nondeg = load_nondegradation_contract()
        checks["nondegradation_lock"] = {
            "ok": True,
            "lock_id": nondeg.lock_id,
            "docker_images_pinned": len(nondeg.docker_images) == 10,
            "hard_cap_usd": nondeg.hard_cap_usd,
        }
        if len(nondeg.docker_images) != 10:
            missing.append("docker_images_pinned")
    except M5ContractError as exc:
        checks["nondegradation_lock"] = {"ok": False, "error": str(exc)}
        missing.append("nondegradation_lock")
        nondeg = None

    try:
        runtime = load_runtime_identity(require_frozen=True, common_root=root)
        checks["multi_bundle"] = {
            "ok": True,
            "relpath": runtime.bundle_relpath,
            "status": runtime.status,
        }
    except M5ContractError as exc:
        checks["multi_bundle"] = {"ok": False, "error": str(exc)}
        missing.append("multi_bundle")
        runtime = None

    if runtime is not None:
        baseline_ok, baseline_error = _verify_codex_baseline(root, runtime.baseline)
        checks["codex_bundle"] = (
            {"ok": True, "relpath": runtime.baseline["bundle_relpath"]}
            if baseline_ok
            else {"ok": False, "error": baseline_error}
        )
        if not baseline_ok:
            missing.append("codex_bundle")

    env_check = _probe_env_local(root / ".env.local")
    checks["env_local"] = env_check
    for key, ok in env_check.items():
        if key == "ok":
            continue
        if ok is False:
            missing.append(f"env_local.{key}")

    if nondeg is not None and runtime is not None:
        checks["gate2_model_projection"] = _probe_gate2_projection(root, nondeg)
        if not checks["gate2_model_projection"].get("ok"):
            missing.append("gate2_model_projection")

    if nondeg is not None:
        checks["provider_frozen_projection"] = _probe_provider_projection(nondeg)
        if not checks["provider_frozen_projection"].get("ok"):
            missing.append("provider_frozen_projection")
        else:
            checks["formal_batch_identity"] = _probe_formal_batch_identity(
                root,
                checks["provider_frozen_projection"],
            )
            if not checks["formal_batch_identity"].get("ok"):
                missing.append("formal_batch_identity")

    if nondeg is not None and campaign is not None:
        checks["budget_upper_bound"] = _probe_budget_upper_bound(nondeg)
        checks["budget_upper_bound"]["prior_conservative_exposure_usd"] = str(
            campaign.prior_exposure_usd
        )
        checks["budget_upper_bound"]["campaign_cap_usd"] = str(
            campaign.campaign_cap_usd
        )
        checks["budget_upper_bound"]["shared_cap_reconciles"] = (
            campaign.prior_exposure_usd + campaign.campaign_cap_usd
            == campaign.shared_hard_cap_usd
        )
        checks["budget_upper_bound"]["campaign_cap_covers_worst_shape"] = (
            Decimal(nondeg.worst_schedule_shape_usd) <= campaign.campaign_cap_usd
        )
        checks["budget_upper_bound"]["ok"] = bool(
            checks["budget_upper_bound"].get("ok")
            and checks["budget_upper_bound"]["shared_cap_reconciles"]
            and checks["budget_upper_bound"]["campaign_cap_covers_worst_shape"]
        )
        if not checks["budget_upper_bound"].get("ok"):
            missing.append("budget_upper_bound")

    if nondeg is not None:
        checks["docker_images_present"] = "not_checked"
        checks["docker_note"] = (
            "Ten digests are pinned in the lock. Presence on the host is not "
            "checked: Docker is not authorized in this round."
        )

    return {
        "ready": not missing,
        "missing": missing,
        "checks": checks,
    }


def _probe_gate2_projection(common_root: Path, contract) -> dict[str, Any]:
    """Build both sides' gate 2 runs offline and check every model agrees.

    Nothing here launches Docker or spends money: it is the same preparation the
    paid path performs, stopped one step before execution. It exists because the
    RunSpec quietly inherited the machine-wide model alias while the budget proxy
    used the campaign's own -- a disagreement that only shows up as the provider
    rejecting the very first request, halfway through a paid batch.
    """

    from tempfile import TemporaryDirectory

    from ..config import ConfigError, RepoPaths, load_runtime_config
    from ..terminal_bench.runner import TerminalBenchRunError, prepare_terminal_bench_run
    from .gate2 import Gate2Error, TerminalBenchSlotExecutor, require_pinned_model
    from .schedule import base_slots
    from .store import scratch_root

    result: dict[str, Any] = {"ok": False, "sides": {}}
    try:
        paths = RepoPaths.discover(Path.cwd())
        config = load_runtime_config(paths)
        slots = base_slots(contract)
        by_side = {}
        for slot in slots:
            if slot.side not in by_side:
                by_side[slot.side] = slot
            if len(by_side) == 2:
                break
        # A throwaway staging root: this probe must not collide with, or leave
        # anything behind in, the work area a real batch uses.
        with TemporaryDirectory(prefix="m5-ready-", dir=scratch_root(common_root)) as raw:
            executor = TerminalBenchSlotExecutor(
                common_root=common_root,
                authorize_docker=False,
                paths=paths,
                work_root=Path(raw),
            )
            for side, slot in by_side.items():
                request = executor.build_request(
                    slot, attempt=1, run_id=f"m5-g2-ready-{side.value}"
                )
                prepared = prepare_terminal_bench_run(config, request)
                projection = require_pinned_model(prepared, contract)
                result["sides"][side.value] = projection
        result["ok"] = len(result["sides"]) == 2
    except (
        Gate2Error,
        TerminalBenchRunError,
        ConfigError,
        M5ContractError,
        OSError,
        ValueError,
    ) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _probe_provider_projection(contract) -> dict[str, Any]:
    """Freeze endpoint, model, effort, retry and rates without reading a secret."""

    from ..config import ConfigError, RepoPaths, load_runtime_config
    from .budget import require_frozen_provider

    try:
        config = load_runtime_config(RepoPaths.discover(Path.cwd()))
        provider = config.paid_provider_projection(model_id=contract.root_model)
        identity = require_frozen_provider(
            provider,
            effort=contract.root_effort,
            contract=contract,
        )
        return {"ok": True, **identity}
    except (ConfigError, M5ContractError, OSError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _probe_formal_batch_identity(
    common_root: Path,
    provider_check: dict[str, Any],
) -> dict[str, Any]:
    from .resume import ResumeError, formal_identity, require_formal_receipt
    from .store import batch_receipt_path

    path = batch_receipt_path(common_root)
    if not path.exists() and not path.is_symlink():
        return {"ok": True, "status": "not_started"}
    provider_identity = {
        key: value for key, value in provider_check.items() if key != "ok"
    }
    try:
        from .archive import harness_identity

        require_formal_receipt(
            path,
            formal_identity(
                provider_identity,
                harness=harness_identity(
                    RepoPaths.discover(Path.cwd()).worktree_root
                ),
            ),
        )
        return {"ok": True, "status": "matching"}
    except ResumeError as exc:
        return {"ok": False, "error": str(exc)}


def _probe_budget_upper_bound(contract) -> dict[str, Any]:
    """Confirm the reservation really bounds one request's maximum legal cost.

    This is the property that turns the $120 line from an intention into an
    upper bound, so it is checked before authorization rather than trusted.
    """

    from ..api_budget_proxy import maximum_usage_cost
    from .budget import (
        HARD_CAP_USD,
        gate1_run_cap_usd,
        gate2_run_cap_usd,
        peak_reservation_usd,
        phase_b_pricing,
        request_reservation_usd,
        usage_envelope,
    )

    try:
        envelope = usage_envelope(contract)
        pricing = phase_b_pricing(contract)
        reservation = request_reservation_usd(contract)
        worst_request = maximum_usage_cost(pricing, envelope)
        peak = peak_reservation_usd(contract)
        gate1_cap = gate1_run_cap_usd(contract)
        gate2_cap = gate2_run_cap_usd(contract)
        ok = (
            reservation >= worst_request
            and gate1_cap >= peak
            and gate2_cap >= peak
            and Decimal(contract.worst_schedule_shape_usd) < HARD_CAP_USD
        )
        return {
            "ok": bool(ok),
            "max_request_cost_usd": str(worst_request),
            "request_reservation_usd": str(reservation),
            "peak_in_flight_reservation_usd": str(peak),
            "gate1_run_cap_usd": str(gate1_cap),
            "gate2_run_cap_usd": str(gate2_cap),
            "worst_schedule_shape_usd": contract.worst_schedule_shape_usd,
            "hard_cap_usd": str(HARD_CAP_USD),
        }
    except (M5ContractError, ArithmeticError, ValueError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _verify_codex_baseline(common_root: Path, baseline: dict[str, Any]) -> tuple[bool, str]:
    relpath = baseline.get("bundle_relpath")
    if not isinstance(relpath, str):
        return False, "Codex baseline path is missing"
    bundle = (common_root / relpath).resolve()
    expected = (common_root / "eval-data" / "bin" / "codex").resolve()
    if not bundle.is_relative_to(expected):
        return False, "Codex baseline is outside eval-data/bin/codex"
    files = {
        bundle / "codex": baseline.get("codex_sha256"),
        bundle / "codex-code-mode-host": baseline.get("code_mode_host_sha256"),
        bundle / "codex-resources" / "bwrap": baseline.get("bwrap_sha256"),
        bundle / "manifest.json": baseline.get("manifest_sha256"),
    }
    for path, digest in files.items():
        if not isinstance(digest, str):
            return False, f"{path.name} digest is missing"
        if path.is_symlink() or not path.is_file():
            return False, f"{path.name} is missing"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            return False, f"{path.name} digest differs"
    return True, ""


def _probe_env_local(path: Path) -> dict[str, Any]:
    """Existence, type, mode, and whether required names are non-empty. No values."""

    result = {
        "exists": path.exists(),
        "regular_file": False,
        "mode_0600": False,
        "required_names_present": False,
        "ok": False,
    }
    if not path.exists():
        return result
    try:
        metadata = path.lstat()
    except OSError:
        return result
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return result
    result["regular_file"] = True
    result["mode_0600"] = stat.S_IMODE(metadata.st_mode) == 0o600
    present = _required_names_nonempty(path)
    result["required_names_present"] = present
    result["ok"] = result["regular_file"] and result["mode_0600"] and present
    return result


def _required_names_nonempty(path: Path) -> bool:
    try:
        text = path.read_text("utf-8")
    except (OSError, UnicodeError):
        return False
    found: dict[str, bool] = {name: False for name in _REQUIRED_ENV_NAMES}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name in found:
            found[name] = bool(value) and "$(" not in value and "${" not in value and "`" not in value
    return all(found.values())
