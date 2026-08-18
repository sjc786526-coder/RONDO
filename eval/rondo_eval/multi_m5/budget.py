"""M-5 phase B budget ledger: $120 hard cap is enforced in code, not docs."""

from __future__ import annotations

import threading
from decimal import Decimal
from pathlib import Path

from ..api_budget_proxy import BudgetStopped, PersistentBudgetLedger
from ..contracts import ModelPricing
from .load import M5ContractError, load_nondegradation_contract, load_workflow_contract

BATCH_ID = "multi-m5-phase-b"
HARD_CAP_USD = Decimal("120.00")
# Per-run ceiling. Gate 1 is modelled at ~$8/attempt; $24 is a small multiple.
# Gate 2 TB runs are cheaper and use GATE2_RUN_CAP_USD via ensure_run.
RUN_CAP_USD = Decimal("24.00")
GATE1_RUN_CAP_USD = Decimal("24.00")
GATE2_RUN_CAP_USD = Decimal("8.00")
# A reservation also has to clear the Guardian additional-capacity check, so the
# usable spend inside a run is `cap - 2 * reservation`, not `cap`. Gate 1 at an
# $8 reservation stops at ~$8 spent, exactly the frozen point estimate; $4 keeps
# a 2x margin and still covers the worst realistic single turn (272k input plus
# 32k output prices at ~$2.32 on the frozen snapshot).
GATE1_REQUEST_RESERVATION_USD = Decimal("4.00")
GATE2_REQUEST_RESERVATION_USD = Decimal("2.00")


REQUEST_LIMIT_STOP_REASON = "logical_request_limit_exceeded"


class BudgetError(ValueError):
    """Raised when the M-5 ledger would not enforce the frozen dollar cap."""


class RequestCappedLedger:
    """Ledger view that refuses to reserve past the frozen per-run request cap.

    Classifying an over-cap run after the fact still lets request 81 and every
    one after it leave the process, bill money, and send workspace content
    upstream. `reserve` is called exactly once per logical request and strictly
    before anything is sent, so capping here turns the frozen
    `max_requests_per_run` into a real stop line rather than a verdict label.

    The proxy serves on a threading HTTP server and Multi's Root and members
    call concurrently, so counting and reserving have to be one critical
    section: reading the count, then reserving, lets two requests at 79 both
    pass and land on 81. This wrapper is the only reserve path handed to the
    proxy, so serialising here is sufficient. The ledger never calls back into
    the wrapper, so there is no lock inversion.

    The run is stopped with `logical_request_limit_exceeded` so the reason stays
    distinguishable from running out of dollars: dollars are shared and end the
    batch, this cap is per-run and only ends the slot.
    """

    def __init__(self, ledger: PersistentBudgetLedger, *, max_requests_per_run: int) -> None:
        if isinstance(max_requests_per_run, bool) or not isinstance(max_requests_per_run, int):
            raise BudgetError("per-run request cap must be an integer")
        if max_requests_per_run < 1:
            raise BudgetError("per-run request cap must be positive")
        self._ledger = ledger
        self._max_requests_per_run = max_requests_per_run
        self._gate = threading.Lock()

    def __getattr__(self, name: str):
        return getattr(self._ledger, name)

    def reserve(self, run_id: str, request_id: str, *args, **kwargs):
        with self._gate:
            run = self._ledger.snapshot()["runs"].get(run_id)
            requests = run.get("requests") if isinstance(run, dict) else None
            seen = requests if isinstance(requests, dict) else {}
            # Re-reserving a known request id is a retry of a counted request.
            if request_id not in seen and len(seen) >= self._max_requests_per_run:
                self._ledger.stop_run(run_id, stop_reason=REQUEST_LIMIT_STOP_REASON)
                raise BudgetStopped(
                    f"run exceeded the frozen {self._max_requests_per_run}-request cap"
                )
            return self._ledger.reserve(run_id, request_id, *args, **kwargs)


def run_stop_reason(ledger: PersistentBudgetLedger, run_id: str) -> str | None:
    """Return why the ledger stopped this run, or None.

    The loopback proxy answers an exhausted run with HTTP 429 instead of raising
    into the caller, so a budget cut-off otherwise looks exactly like the agent
    giving up. Gate 1 would file it as `agent_failed` and gate 2 would count it
    as an effective "Multi incomplete" observation.
    """

    run = ledger.snapshot()["runs"].get(run_id)
    if not isinstance(run, dict) or not run.get("stopped"):
        return None
    reason = run.get("stop_reason")
    return str(reason) if isinstance(reason, str) and reason else "budget_stopped"


def run_request_count(ledger: PersistentBudgetLedger, run_id: str) -> int:
    """How many logical requests this run actually reserved.

    A real Terminal-Bench slot is one host process making many model calls, so
    reporting a hardcoded 1 both misstates the archive row and leaves the frozen
    `max_requests_per_run` cap dead. Unbilled retries reuse their request id, so
    this counts logical requests, not socket attempts.
    """

    run = ledger.snapshot()["runs"].get(run_id)
    if not isinstance(run, dict):
        return 0
    requests = run.get("requests")
    return len(requests) if isinstance(requests, dict) else 0


_PRICE_FIELDS = (
    "input_usd_per_million",
    "cached_input_usd_per_million",
    "output_usd_per_million",
    "long_context_input_multiplier",
    "long_context_output_multiplier",
    "cache_write_input_multiplier",
)


def require_frozen_provider(projection, *, effort: str, contract=None) -> dict[str, str]:
    """Bind a paid run to the frozen contract and return what actually applied.

    `rondo.local.toml` is mutable machine config, but the proxy meters the $120
    batch with *its* rates and talks to *its* endpoint. Checking only the model
    name would let an edit to that file silently change what the approved dollar
    cap buys, which provider the key is sent to, or how hard the model thinks.

    Rates must match exactly. The snapshot date is provenance rather than spend,
    so a differing date is recorded on every row instead of blocking the run.
    """

    loaded = contract or load_nondegradation_contract()
    raw = loaded.raw
    price = raw["price_snapshot"]
    pricing = projection.main_pricing
    mismatches: list[str] = []
    if projection.provider_id != str(raw["provider"]):
        mismatches.append("provider_id")
    if projection.api != str(raw["provider_api"]):
        mismatches.append("provider_api")
    # The provider name alone does not say where the key, the workspace content
    # and the money actually go. Freeze the endpoint itself.
    if projection.base_url.rstrip("/") != str(raw["provider_base_url"]).rstrip("/"):
        mismatches.append("provider_base_url")
    if projection.main_model != str(price["model_id"]):
        mismatches.append("main_model")
    if projection.main_effort != effort:
        mismatches.append("main_effort")
    if int(projection.max_attempts) != int(raw["provider_max_attempts"]):
        mismatches.append("provider_max_attempts")
    if tuple(projection.unbilled_retry_statuses) != tuple(
        int(item) for item in raw["provider_unbilled_retry_statuses"]
    ):
        mismatches.append("provider_unbilled_retry_statuses")
    if pricing.model_id != str(price["model_id"]):
        mismatches.append("pricing_model_id")
    if int(pricing.long_context_threshold_tokens) != int(
        price["long_context_threshold_tokens"]
    ):
        mismatches.append("long_context_threshold_tokens")
    for field in _PRICE_FIELDS:
        if Decimal(str(getattr(pricing, field))) != Decimal(str(price[field])):
            mismatches.append(field)
    if mismatches:
        raise M5ContractError(
            "paid provider differs from the frozen contract: " + ",".join(sorted(mismatches))
        )
    return {
        "provider_id": projection.provider_id,
        "provider_api": projection.api,
        "provider_base_url": projection.base_url,
        "main_model": projection.main_model,
        "main_effort": projection.main_effort,
        "provider_profile_sha256": projection.profile_sha256,
        "provider_config_sha256": projection.config_sha256,
        "frozen_price_snapshot_date": str(price["date"]),
        "effective_price_snapshot_date": str(pricing.price_snapshot_date),
    }


def phase_b_pricing(contract=None) -> ModelPricing:
    raw = (contract or load_nondegradation_contract()).raw
    price = raw["price_snapshot"]
    pricing = ModelPricing(
        model_id=str(price["model_id"]),
        input_usd_per_million=Decimal(str(price["input_usd_per_million"])),
        cached_input_usd_per_million=Decimal(str(price["cached_input_usd_per_million"])),
        output_usd_per_million=Decimal(str(price["output_usd_per_million"])),
        long_context_threshold_tokens=int(price["long_context_threshold_tokens"]),
        long_context_input_multiplier=Decimal(str(price["long_context_input_multiplier"])),
        long_context_output_multiplier=Decimal(str(price["long_context_output_multiplier"])),
        cache_write_input_multiplier=Decimal(str(price["cache_write_input_multiplier"])),
        price_snapshot_date=str(price["date"]),
        price_source_url=str(price["source_url"]),
    )
    pricing.validate()
    return pricing


def open_phase_b_ledger(path: Path, *, contract=None) -> PersistentBudgetLedger:
    """Open the batch ledger. Cap, batch id, and run slot count come from the lock."""

    loaded = contract or load_nondegradation_contract()
    cap = Decimal(loaded.hard_cap_usd)
    if cap != HARD_CAP_USD:
        raise M5ContractError("non-degradation hard cap drifted from $120.00")
    if loaded.raw.get("cost_forecast", {}).get("ledger_batch_id") != BATCH_ID:
        raise M5ContractError("ledger batch id drifted from multi-m5-phase-b")
    # Both gates share this ledger, so gate 1's attempts need their own slots.
    # Sizing it at 60+12 alone truncates gate 2 in the worst legal case. The
    # attribution diagnostic can fire once per task, and it spends from the same
    # $120, so it needs slots too -- otherwise the run that has to explain a
    # degradation is the one that cannot start.
    gate1_attempts = load_workflow_contract().max_attempts
    max_runs = (
        loaded.max_effective_runs
        + loaded.max_infra_attempts_total
        + gate1_attempts
        + len(loaded.tasks)
    )
    if max_runs != 85:
        raise M5ContractError("ledger run-slot count drifted from 60+12+3+10")
    ledger = PersistentBudgetLedger(
        path,
        batch_id=BATCH_ID,
        total_cap_usd=HARD_CAP_USD,
        max_runs=max_runs,
        default_run_cap_usd=RUN_CAP_USD,
    )
    snapshot = ledger.snapshot()
    if Decimal(snapshot["total_cap_usd"]) != HARD_CAP_USD:
        ledger.close()
        raise BudgetError("opened ledger does not enforce the $120 hard cap")
    if snapshot["batch_id"] != BATCH_ID:
        ledger.close()
        raise BudgetError("opened ledger batch id differs")
    return ledger
