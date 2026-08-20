"""M-5 phase B budget ledger: $120 hard cap is enforced in code, not docs."""

from __future__ import annotations

import threading
from decimal import Decimal, ROUND_UP
from pathlib import Path

from ..api_budget_proxy import (
    BudgetStopped,
    PersistentBudgetLedger,
    UsageEnvelope,
    infra_taint,
    maximum_usage_cost,
)
from ..contracts import ModelPricing
from .campaign import BATCH_ID, CAMPAIGN_CAP_USD, load_campaign_generation
from .load import M5ContractError, load_nondegradation_contract, load_workflow_contract

HARD_CAP_USD = Decimal("120.00")
# Final pre-contract connectivity smoke. Separately authorized, so it gets its
# own batch and its own ledger file: it must never draw on the $120 the two
# gates share, and its rows must never look like contract evidence. The cap is
# the frozen gate-1-shaped run cap, not the authorization ceiling -- a cap is a
# stop line, not a spending target.
SMOKE_BATCH_ID = "multi-m5-clean-smoke-v5"
SMOKE_LOCK_ID = "multi-m5-clean-smoke-v5"
# The 2026-08-18 exploratory smoke (`multi-m5-code-mode-smoke`, USD 40, no
# attempt limit) is spent and stays on disk as history: it ran on the pre-fix
# bundle, where members could not complete a turn. Clean smoke v1 on runtime-v2
# used two slots but mixed its rows into the old archive; v2 then produced one
# zero-taint observation that exposed the code-mode evidence gap. All historical
# files remain read-only. Clean smoke v3 was then blocked by the execution
# sandbox before the provider received its first reserved request, leaving an
# intentionally preserved, unsettled pre-network row. A v4 replacement was
# retired before a provider request because runtime-v3's self-mutating inspect
# cursor failed rehearsal. This v5 identity carries one validation run for the
# repaired runtime-v4 and workflow-v5; the smoke identity stays historical
# while the formal gates advance to v6.
# Its cap is derived from that run cap in `open_smoke_ledger` and stays under
# the gates' own $120.
SMOKE_MAX_RUNS = 1
SMOKE_CAP_USD = Decimal("23.10")


REQUEST_LIMIT_STOP_REASON = "logical_request_limit_exceeded"
# How many responses may arrive without usage before a run is stopped. The relay
# streams a terminal event with no usage occasionally; with the historical value
# of 1 that single glitch stopped the run, so every later request was refused
# with HTTP 429 and the agent died -- both real smoke runs were lost this way,
# each to one hiccup. Accounting is unchanged: every unpriced request is still
# charged its full reservation. Only the "does one glitch end the run" question
# moves, and `_require_unpriced_budget` keeps the worst case inside the run cap.
# The formal batch stops on the first unpriced settlement, which is the
# historical behaviour. Raising it there would buy nothing: an upstream fault
# taints the run, and a tainted run cannot be product evidence for either gate,
# so letting it continue only spends money to produce something unusable. The
# contract-free smoke is different -- it exists to characterise the provider, so
# it keeps collecting after a fault.
UNPRICED_STOP_THRESHOLD = 1
# The contract-free smoke gets more tolerance than the formal gates. It exists
# to characterise this relay, which was measured dropping roughly one stream in
# three, and each drop costs a full reservation of *phantom* budget -- the
# provider's own records show those responses produced no tokens and were not
# billed. The formal gates keep the tighter number: they must fail loudly on a
# provider this unreliable rather than quietly absorb it. Both are still bounded
# by their run cap, and the batch cap is untouched.
SMOKE_UNPRICED_STOP_THRESHOLD = 9
_CENT = Decimal("0.01")


def usage_envelope(contract=None) -> UsageEnvelope:
    """The frozen per-request token bounds for the M-5 model."""

    raw = (contract or load_nondegradation_contract()).raw
    block = raw.get("usage_envelope")
    if not isinstance(block, dict):
        raise M5ContractError("M-5 usage envelope is missing from the lock")
    envelope = UsageEnvelope(
        max_input_tokens=_positive_int(block.get("max_input_tokens")),
        max_output_tokens=_positive_int(block.get("max_output_tokens")),
    )
    envelope.validate()
    return envelope


def request_reservation_usd(contract=None) -> Decimal:
    """Derive the per-request reservation from the price table and envelope.

    Mechanical rather than chosen: it is the most one request can legally cost
    inside the frozen envelope, rounded up to the cent. Reserving less would let
    a settled request cost more than it held and carry the batch past $120 after
    the money was already spent; reserving a round number instead would make the
    guarantee depend on someone re-checking the arithmetic after a price change.
    """

    loaded = contract or load_nondegradation_contract()
    pricing = phase_b_pricing(loaded)
    derived = maximum_usage_cost(pricing, usage_envelope(loaded))
    reservation = derived.quantize(_CENT, rounding=ROUND_UP)
    declared = loaded.raw.get("cost_forecast", {}).get("request_reservation_usd")
    if declared is not None and Decimal(str(declared)) != reservation:
        raise M5ContractError(
            "declared request reservation differs from the price-derived value"
        )
    return reservation


def retry_backoff_seconds(contract=None) -> float:
    """The exponential retry base both M-5 gates use.

    Taken from the lock, not from `paid_eval.retry_backoff_seconds`: that key is
    machine-wide, so gate 2 was inheriting whatever this host happened to say
    while gate 1 used its own hard-coded value. Same isolation as the model id.
    """

    return (contract or load_nondegradation_contract()).retry_backoff_seconds


def max_concurrent_main(contract=None) -> int:
    """How many Root/member requests the frozen product can have in flight.

    Sizing a per-run cap needs this number, and so does refusing an unexpected
    fifth caller. It is frozen in the lock rather than read from the product so
    the harness stops instead of silently paying for a config that moved.
    """

    raw = (contract or load_nondegradation_contract()).raw
    block = raw.get("concurrency")
    if not isinstance(block, dict):
        raise M5ContractError("M-5 concurrency contract is missing from the lock")
    return _positive_int(block.get("max_concurrent_main_requests"))


def peak_reservation_usd(contract=None) -> Decimal:
    """Reserved dollars when every legal caller is in flight at once.

    `reserve` also demands headroom for one Guardian request alongside each main
    one, so the peak is `(mains + 1) * reservation`. A run cap below this rejects
    a request the product is entitled to make, which shows up as a product
    failure rather than the harness limit it is.
    """

    loaded = contract or load_nondegradation_contract()
    return (max_concurrent_main(loaded) + 1) * request_reservation_usd(loaded)


def _spend_allowance(loaded, key: str) -> Decimal:
    block = loaded.raw.get("cost_forecast", {})
    value = block.get(key)
    if value is None:
        raise M5ContractError(f"cost forecast is missing {key}")
    amount = Decimal(str(value))
    if amount <= 0:
        raise M5ContractError(f"cost forecast {key} must be positive")
    return amount


def gate1_run_cap_usd(contract=None) -> Decimal:
    """Peak in-flight reservations plus this gate's cumulative spend allowance."""

    loaded = contract or load_nondegradation_contract()
    return peak_reservation_usd(loaded) + _spend_allowance(
        loaded, "gate1_run_spend_allowance_usd"
    )


def gate2_run_cap_usd(contract=None) -> Decimal:
    loaded = contract or load_nondegradation_contract()
    return peak_reservation_usd(loaded) + _spend_allowance(
        loaded, "gate2_run_spend_allowance_usd"
    )


def default_run_cap_usd(contract=None) -> Decimal:
    """Ledger-wide per-run maximum. Must admit the largest gate cap."""

    loaded = contract or load_nondegradation_contract()
    return max(gate1_run_cap_usd(loaded), gate2_run_cap_usd(loaded))


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise M5ContractError("M-5 lock integer is missing or not positive")
    return value


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


def run_infra_taint(ledger: PersistentBudgetLedger, run_id: str) -> dict | None:
    """Whether this run absorbed an upstream fault, and how many.

    Separate from the stop reason. A run that continued under the threshold has
    no stop reason at all, yet it still saw the upstream fail -- and a run that
    saw the upstream fail cannot be read as a statement about the product.
    """

    return infra_taint(ledger.snapshot(), run_id)


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


def smoke_run_cap_usd(contract=None) -> Decimal:
    """The smoke run gets the same shape of cap as a gate 1 attempt.

    It runs the same flow with the same concurrency, so sizing it any smaller
    would reject a request the product legitimately makes and blame the product.
    """

    return gate1_run_cap_usd(contract)


def _frozen_unpriced_threshold(contract) -> int:
    """Read the batch stop line from the lock and refuse a silent divergence."""

    threshold = contract.unpriced_stop_threshold
    if threshold != UNPRICED_STOP_THRESHOLD:
        raise M5ContractError("frozen unpriced stop threshold differs from the harness")
    return threshold


def _require_unpriced_budget(contract=None, *, threshold: int, cap: Decimal) -> int:
    """Confirm the absorbed unpriced settlements still fit under a run cap.

    Each one is charged in full, so a threshold is only safe while
    `threshold * reservation` leaves room inside the run cap it applies to.
    """

    loaded = contract or load_nondegradation_contract()
    if threshold * request_reservation_usd(loaded) >= cap:
        raise M5ContractError(
            "absorbed unpriced settlements would exceed a per-run cap"
        )
    return threshold


def open_smoke_ledger(path: Path) -> PersistentBudgetLedger:
    """Ledger for the separately authorized connectivity smoke test.

    Deliberately not `open_phase_b_ledger`: a different batch id and a different
    file mean the smoke spend cannot be confused with, or subtracted from, the
    $120 the two gates share.
    """

    # Derived, not chosen: the one final attempt at this flow's existing run cap.
    # A hand-picked total would drift the moment either input moved.
    if SMOKE_CAP_USD != SMOKE_MAX_RUNS * smoke_run_cap_usd():
        raise M5ContractError("smoke cap is not the attempt count times the run cap")
    if SMOKE_CAP_USD >= HARD_CAP_USD:
        raise M5ContractError("smoke cap must stay under the two gates' hard cap")
    ledger = PersistentBudgetLedger(
        path,
        batch_id=SMOKE_BATCH_ID,
        total_cap_usd=SMOKE_CAP_USD,
        max_runs=SMOKE_MAX_RUNS,
        default_run_cap_usd=smoke_run_cap_usd(),
        usage_envelope=usage_envelope(),
        unpriced_stop_threshold=_require_unpriced_budget(
            threshold=SMOKE_UNPRICED_STOP_THRESHOLD, cap=smoke_run_cap_usd()
        ),
    )
    snapshot = ledger.snapshot()
    if snapshot["batch_id"] != SMOKE_BATCH_ID or Decimal(
        snapshot["total_cap_usd"]
    ) != SMOKE_CAP_USD:
        ledger.close()
        raise BudgetError("smoke ledger does not enforce its own batch and cap")
    if snapshot["batch_id"] == BATCH_ID:
        ledger.close()
        raise BudgetError("smoke ledger must not share the phase B batch")
    return ledger


def open_phase_b_ledger(path: Path, *, contract=None) -> PersistentBudgetLedger:
    """Open the batch ledger. Cap, batch id, and run slot count come from the lock."""

    loaded = contract or load_nondegradation_contract()
    cap = Decimal(loaded.hard_cap_usd)
    if cap != HARD_CAP_USD:
        raise M5ContractError("non-degradation hard cap drifted from $120.00")
    if loaded.raw.get("cost_forecast", {}).get("ledger_batch_id") != "multi-m5-phase-b-v6":
        raise M5ContractError("v6 behavior contract ledger identity drifted")
    campaign = load_campaign_generation()
    if campaign.batch_id != BATCH_ID or campaign.campaign_cap_usd != CAMPAIGN_CAP_USD:
        raise M5ContractError("campaign generation budget identity drifted")
    # Both gates share this ledger, so gate 1's attempts need their own slots.
    # Sizing it at effective+infra alone truncates the shared batch. The
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
    if max_runs != 116:
        raise M5ContractError("ledger run-slot count drifted from 60+40+6+10")
    ledger = PersistentBudgetLedger(
        path,
        batch_id=BATCH_ID,
        total_cap_usd=CAMPAIGN_CAP_USD,
        max_runs=max_runs,
        default_run_cap_usd=default_run_cap_usd(loaded),
        # With this set, every settled charge is bounded by its reservation, so
        # the reserve-time cap arithmetic below is an upper bound on real spend
        # rather than a best effort.
        usage_envelope=usage_envelope(loaded),
        # The formal threshold is the lock's, not this module's: the value that
        # decides when the $120 batch stops has to be readable in the frozen
        # contract rather than in code the run could be re-pointed at.
        unpriced_stop_threshold=_require_unpriced_budget(
            loaded,
            threshold=_frozen_unpriced_threshold(loaded),
            cap=min(gate1_run_cap_usd(loaded), gate2_run_cap_usd(loaded)),
        ),
    )
    snapshot = ledger.snapshot()
    if Decimal(snapshot["total_cap_usd"]) != CAMPAIGN_CAP_USD:
        ledger.close()
        raise BudgetError("opened ledger does not enforce the remaining shared cap")
    if snapshot["batch_id"] != BATCH_ID:
        ledger.close()
        raise BudgetError("opened ledger batch id differs")
    return ledger
