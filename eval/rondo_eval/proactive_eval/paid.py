"""Phase-B authorization guard. Stage A recipes never forward these tokens."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from ..config import ConfigError, RepoPaths, load_runtime_config
from .contract import CampaignContract, load_contract


PHASE_B_AUTHORIZATION = "AUTHORIZE RONDO PLAN 049 PHASE B REAL API AND DOCKER UP TO USD 100.00"
ACTIVATION_ACTION = "START RONDO PLAN 049 ACTIVATION PILOT"


class PaidGuardError(PermissionError):
    """Raised before secret, network, Docker, ledger, receipt, or run creation."""


@dataclass(frozen=True)
class PaidEntryCallbacks:
    read_secret: Callable[[], object]
    create_formal_state: Callable[[], object]
    touch_network: Callable[[], object]
    touch_docker: Callable[[], object]


def enter_paid_phase(
    *,
    repo_root: Path,
    authorization: str | None,
    activation_action: str | None,
    confirmed_balance_usd: str | None,
    harness_clean: bool,
    resume_prefix_safe: bool,
    activation_conditions_ready: bool,
    docker_resource_gate_ready: bool,
    callbacks: PaidEntryCallbacks,
) -> CampaignContract:
    """Validate every side-effect-free gate, then hand control to Phase B.

    The complete paid executor remains a Phase-B implementation concern. This
    guard fixes the ordering contract now and makes accidental Stage-A entry
    mechanically unable to read a key or create formal identity/state.
    """

    if authorization != PHASE_B_AUTHORIZATION:
        raise PaidGuardError("Plan 049 Phase B authorization is absent")
    if activation_action != ACTIVATION_ACTION:
        raise PaidGuardError("Plan 049 activation action is absent")
    try:
        balance = Decimal(confirmed_balance_usd or "")
    except InvalidOperation as exc:
        raise PaidGuardError("Plan 049 balance confirmation is invalid") from exc
    if not balance.is_finite() or balance < Decimal("100.00"):
        raise PaidGuardError("Plan 049 confirmed balance is below USD 100.00")
    if harness_clean is not True:
        raise PaidGuardError("Plan 049 paid harness is not clean")
    if resume_prefix_safe is not True:
        raise PaidGuardError("Plan 049 paid resume prefix is unsafe")
    if activation_conditions_ready is not True:
        raise PaidGuardError("Plan 049 local activation conditions are not ready")
    if docker_resource_gate_ready is not True:
        raise PaidGuardError("Plan 049 Docker resource gate is not ready")
    contract = load_contract(repo_root)
    _require_local_projection(contract, RepoPaths.discover(repo_root))
    # All callbacks are deliberately after the complete local authorization
    # chain. Their order is explicit for the future Phase-B executor.
    callbacks.read_secret()
    callbacks.create_formal_state()
    callbacks.touch_network()
    callbacks.touch_docker()
    return contract


def _require_local_projection(contract: CampaignContract, paths: RepoPaths) -> None:
    expected_provider = contract.lock["provider"]
    expected_price = contract.lock["price_snapshot"]
    try:
        projection = load_runtime_config(paths).paid_provider_projection(
            expected_provider["name"],
            model_id=expected_provider["root_model"],
        )
    except ConfigError as exc:
        raise PaidGuardError("Plan 049 local provider projection is unavailable") from exc
    price = projection.main_pricing.to_dict()
    # Plan 049's own proxy/orchestrator consumes the frozen two-second retry
    # ladder from the campaign lock; the host-wide backoff is intentionally not
    # inherited. Endpoint, model, prices, attempts and retryable statuses still
    # have to agree before a key can be read.
    if (
        projection.provider_id != expected_provider["name"]
        or projection.api != expected_provider["wire_api"]
        or projection.base_url != expected_provider["base_url"]
        or projection.main_model != expected_provider["root_model"]
        or projection.main_effort != expected_provider["root_effort"]
        or projection.max_attempts != expected_provider["request_attempt_limit"]
        or list(projection.unbilled_retry_statuses) != expected_provider["retry_statuses"]
        or price
        != {
            "model_id": expected_price["model_id"],
            "input_usd_per_million": expected_price["input_usd_per_million"],
            "cached_input_usd_per_million": expected_price[
                "cached_input_usd_per_million"
            ],
            "output_usd_per_million": expected_price["output_usd_per_million"],
            "long_context_threshold_tokens": str(
                expected_price["long_context_threshold_tokens"]
            ),
            "long_context_input_multiplier": expected_price[
                "long_context_input_multiplier"
            ],
            "long_context_output_multiplier": expected_price[
                "long_context_output_multiplier"
            ],
            "cache_write_input_multiplier": expected_price[
                "cache_write_input_multiplier"
            ],
            "price_snapshot_date": expected_price["date"],
            "price_source_url": expected_price["source_url"],
        }
    ):
        raise PaidGuardError("Plan 049 local provider or price projection drifted")
