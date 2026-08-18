"""M-5 phase B budget ledger: $120 hard cap is enforced in code, not docs."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from ..api_budget_proxy import PersistentBudgetLedger
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


class BudgetError(ValueError):
    """Raised when the M-5 ledger would not enforce the frozen dollar cap."""


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
    # Sizing it at 60+12 alone truncates gate 2 in the worst legal case.
    gate1_attempts = load_workflow_contract().max_attempts
    max_runs = loaded.max_effective_runs + loaded.max_infra_attempts_total + gate1_attempts
    if max_runs != 75:
        raise M5ContractError("ledger run-slot count drifted from 60+12+3")
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
