"""Loopback-only Responses proxy with fail-closed API budget accounting.

The runner must opt in to this proxy explicitly.  It accepts a credential-free
HTTPS OpenAI-compatible base URL and an API key already loaded into memory;
neither value is read from disk here.  Request bodies are forwarded, but only
redacted shape metadata and the request-body digest are persisted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import socket
import stat
import threading
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .contracts import ModelPricing

MAX_INPUT_TOKENS = 1_050_000
MAX_OUTPUT_TOKENS = 128_000
BATCH_CAP_USD = Decimal("10.00")
RUN_CAP_USD = Decimal("5.00")
_MAX_EXPLICIT_BATCH_CAP_USD = Decimal("1600.00")
_MAX_EXPLICIT_RUN_CAP_USD = Decimal("40.00")
MAX_BENCHMARK_RUNS = 4
_MAX_EXPLICIT_BENCHMARK_RUNS = 321
_MONEY_QUANTUM = Decimal("0.000001")
_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HOSTED_TOOL_TYPES = {
    "web_search",
    "web_search_preview",
    "file_search",
    "computer",
    "computer_use_preview",
    "code_interpreter",
    "image_generation",
    "local_shell",
    "shell",
    "mcp",
}
_RETRY_HEADERS = (
    "x-stainless-retry-count",
    "x-retry-count",
    "x-rondo-eval-attempt",
)
_LITE_HEADER = "x-openai-internal-codex-responses-lite"
_MAX_USER_AGENT_BYTES = 512
_MAX_ORIGINATOR_BYTES = 64
_MAX_UPSTREAM_ATTEMPTS = 5
# Ceiling for the opt-in concurrent-main count. Sized above the frozen product
# default (Root plus three members) with room for a deliberate config change,
# but low enough that a per-run cap can still be derived from it.
_MAX_CONCURRENT_MAIN = 8
_GUARDIAN_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
_SETTLEMENT_USAGE_PRICED = "usage_priced"
_SETTLEMENT_USAGE_PRICED_OVERAGE = "usage_priced_overage"
_SETTLEMENT_OPERATOR_CONFIRMED_UNBILLED = "operator_confirmed_unbilled"
_SETTLEMENT_CONSERVATIVE_RESERVATION = "conservative_reservation"
_SETTLEMENT_UNPRICED_FALLBACK = "unpriced_fallback"
_SETTLEMENT_NOT_SENT_UNBILLED = "not_sent_unbilled"
_SETTLEMENT_KINDS = {
    _SETTLEMENT_USAGE_PRICED,
    _SETTLEMENT_USAGE_PRICED_OVERAGE,
    _SETTLEMENT_OPERATOR_CONFIRMED_UNBILLED,
    _SETTLEMENT_CONSERVATIVE_RESERVATION,
    _SETTLEMENT_UNPRICED_FALLBACK,
    _SETTLEMENT_NOT_SENT_UNBILLED,
}
_UNPRICED_SETTLEMENT_KINDS = {
    _SETTLEMENT_CONSERVATIVE_RESERVATION,
    _SETTLEMENT_UNPRICED_FALLBACK,
}
_STOP_REASONS = {
    "missing_or_invalid_usage",
    "interrupted_request",
    "upstream_deadline_exhausted",
    "upstream_unavailable",
    "upstream_failure",
    "unclassified_upstream_failure",
    "upstream_non_success",
    "upstream_response_unavailable",
    "upstream_terminal_error",
    "upstream_terminal_failed",
    "upstream_terminal_incomplete",
    "operator_confirmed_unbilled_attempts_exhausted",
    "operator_confirmed_unbilled_deadline_exhausted",
    "operator_confirmed_unbilled_proxy_closing",
    "guardian_duplicate_logical_request_rejected",
    "guardian_logical_request_limit_exceeded",
    "logical_request_limit_exceeded",
    "proxy_closing",
    "usage_cost_exceeded_reservation",
    "usage_outside_frozen_envelope",
    "budget_capacity_exhausted",
}
# Stop reasons the batch produced by refusing to spend more. Everything else is
# the upstream, the network or the harness failing, which is not a budget stop
# and must not be reported as one. Callers classify with `stop_reason_class`.
BUDGET_STOP_REASONS = frozenset(
    {
        "budget_capacity_exhausted",
        "usage_cost_exceeded_reservation",
        "logical_request_limit_exceeded",
        "guardian_logical_request_limit_exceeded",
    }
)
INFRA_STOP_REASONS = frozenset(_STOP_REASONS) - BUDGET_STOP_REASONS


def stop_reason_class(reason: str | None) -> str:
    """Classify a ledger stop reason as budget, infra, or unknown.

    A run that stopped because the upstream failed, because usage never arrived,
    or because a deadline expired did not run out of money. Labelling those
    `budget_stopped` hides the real defect and, in gate 2, would turn a provider
    outage into evidence about the product. An unrecognised reason is never
    guessed: it fails closed as `unknown` so the caller can refuse to continue.
    """

    if reason is None:
        return "none"
    if reason in BUDGET_STOP_REASONS:
        return "budget"
    if reason in INFRA_STOP_REASONS:
        return "infra"
    return "unknown"
GUARDIAN_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "risk_level": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
        },
        "user_authorization": {
            "type": "string",
            "enum": ["unknown", "low", "medium", "high"],
        },
        "outcome": {"type": "string", "enum": ["allow", "deny"]},
        "rationale": {"type": "string"},
    },
    "required": ["outcome"],
}
_METADATA_LOCKS_GUARD = threading.Lock()
_METADATA_LOCKS: dict[str, threading.Lock] = {}


class ApiBudgetProxyError(ValueError):
    """Raised when the proxy or its persistent state is unsafe or invalid."""


class BudgetStopped(ApiBudgetProxyError):
    """Raised before forwarding when an authorization limit is exhausted."""


class BudgetCapacityExhausted(BudgetStopped):
    """Raised when a new reservation cannot fit the frozen run or batch cap."""


class _GuardianLogicalRequestLimitExceeded(ApiBudgetProxyError):
    """Raised before reserve/forward when a run exceeds its declared approvals."""


_PREFLIGHT_REASON = re.compile(r"[a-z][a-z0-9_:.-]{0,127}\Z")
_PREFLIGHT_DEFAULT_REASON = "task_independent_contract_drift"


class _SymmetryPreflightRejected(RuntimeError):
    """Raised before reserve/forward when the two sides are not symmetric."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _preflight_reason(exc: BaseException) -> str:
    """Return one bounded, attributable rejection code for a preflight failure."""

    reasons = getattr(exc, "reasons", ())
    if isinstance(reasons, tuple):
        for reason in reasons:
            if isinstance(reason, str) and _PREFLIGHT_REASON.fullmatch(reason):
                return reason
    return _PREFLIGHT_DEFAULT_REASON


class _GuardianDuplicateLogicalRequest(ApiBudgetProxyError):
    """Raised before reserve/forward for a charged review body replay."""


class _LogicalRequestLimitExceeded(ApiBudgetProxyError):
    """Raised before reserve/forward when a short diagnostic exceeds its cap."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int

    def validate(self) -> None:
        values = (
            self.input_tokens,
            self.cached_input_tokens,
            self.cache_write_input_tokens,
            self.output_tokens,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ApiBudgetProxyError("usage token counts must be integers")
        if any(value < 0 for value in values):
            raise ApiBudgetProxyError("usage token counts must be non-negative")
        if self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens:
            raise ApiBudgetProxyError("usage input-token details exceed input tokens")
        if self.input_tokens > MAX_INPUT_TOKENS or self.output_tokens > MAX_OUTPUT_TOKENS:
            raise ApiBudgetProxyError("usage exceeds the frozen request bounds")


@dataclass(frozen=True)
class Settlement:
    charged_usd: Decimal
    usage_valid: bool
    run_stopped: bool
    attempt_count: int
    settlement_kind: str
    usage: Usage | None


def price_usage(usage: Usage, *, pricing: ModelPricing) -> Decimal:
    """Price one request using the selected local provider profile snapshot."""

    usage.validate()
    try:
        pricing.validate()
    except (AttributeError, ValueError) as exc:
        raise ApiBudgetProxyError("model pricing is invalid") from exc
    input_rate = pricing.input_usd_per_million
    cached_input_rate = pricing.cached_input_usd_per_million
    output_rate = pricing.output_usd_per_million
    long_context = usage.input_tokens > pricing.long_context_threshold_tokens
    input_multiplier = (
        pricing.long_context_input_multiplier if long_context else Decimal(1)
    )
    output_multiplier = (
        pricing.long_context_output_multiplier if long_context else Decimal(1)
    )
    uncached = usage.input_tokens - usage.cached_input_tokens - usage.cache_write_input_tokens
    input_cost = (
        Decimal(uncached) * input_rate
        + Decimal(usage.cached_input_tokens) * cached_input_rate
        + Decimal(usage.cache_write_input_tokens)
        * input_rate
        * pricing.cache_write_input_multiplier
    ) * input_multiplier
    output_cost = Decimal(usage.output_tokens) * output_rate * output_multiplier
    return ((input_cost + output_cost) / Decimal(1_000_000)).quantize(
        _MONEY_QUANTUM, rounding=ROUND_UP
    )


@dataclass(frozen=True)
class UsageEnvelope:
    """Frozen per-request token bounds for one campaign's model.

    The generic :data:`MAX_INPUT_TOKENS` / :data:`MAX_OUTPUT_TOKENS` contract is
    wide enough to admit requests no pinned model can physically produce, so a
    reservation sized for a real model is smaller than the largest *legally
    representable* charge. That gap is what lets a settled request cost more
    than it reserved and push a batch past its authorized cap. Declaring the
    model's own envelope closes it: usage outside the envelope is refused rather
    than priced, and the reservation can then be derived from the envelope so
    that ``charged <= reserved`` holds for every request.
    """

    max_input_tokens: int
    max_output_tokens: int

    def validate(self) -> None:
        values = (self.max_input_tokens, self.max_output_tokens)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ApiBudgetProxyError("usage envelope bounds must be integers")
        if any(value < 1 for value in values):
            raise ApiBudgetProxyError("usage envelope bounds must be positive")
        if self.max_input_tokens > MAX_INPUT_TOKENS:
            raise ApiBudgetProxyError("usage envelope exceeds the generic input bound")
        if self.max_output_tokens > MAX_OUTPUT_TOKENS:
            raise ApiBudgetProxyError("usage envelope exceeds the generic output bound")

    def require(self, usage: Usage) -> None:
        """Raise unless this usage fits the frozen envelope."""

        usage.validate()
        if (
            usage.input_tokens > self.max_input_tokens
            or usage.output_tokens > self.max_output_tokens
        ):
            raise ApiBudgetProxyError("usage exceeds the frozen campaign envelope")


def maximum_usage_cost(
    pricing: ModelPricing, envelope: UsageEnvelope | None = None
) -> Decimal:
    """Highest price admitted by the Usage contract, optionally narrowed.

    Mechanical: it enumerates the priciest legal shape of one request under the
    given bounds and the frozen rate table, so a reservation derived from it is
    an upper bound rather than a judgement call.
    """

    return _maximum_usage_cost(pricing, envelope)


def _maximum_usage_cost(
    pricing: ModelPricing, envelope: UsageEnvelope | None = None
) -> Decimal:
    """Return the highest price admitted by the frozen Usage contract."""

    max_input = MAX_INPUT_TOKENS if envelope is None else envelope.max_input_tokens
    max_output = MAX_OUTPUT_TOKENS if envelope is None else envelope.max_output_tokens
    candidates = {max_input}
    if pricing.long_context_threshold_tokens < max_input:
        candidates.add(pricing.long_context_threshold_tokens)
    maximum = Decimal(0)
    for input_tokens in candidates:
        input_rates = (
            pricing.input_usd_per_million,
            pricing.cached_input_usd_per_million,
            pricing.input_usd_per_million * pricing.cache_write_input_multiplier,
        )
        highest = max(range(len(input_rates)), key=input_rates.__getitem__)
        cached = input_tokens if highest == 1 else 0
        cache_write = input_tokens if highest == 2 else 0
        maximum = max(
            maximum,
            price_usage(
                Usage(input_tokens, cached, cache_write, max_output),
                pricing=pricing,
            ),
        )
    return maximum.quantize(_MONEY_QUANTUM, rounding=ROUND_UP)


# The five-dollar value remains the default for direct ledger users. A formal
# proxy with no explicit short-test reservation instead reserves the selected
# role's complete frozen usage envelope before forwarding.
MAX_REQUEST_RESERVATION_USD = RUN_CAP_USD.quantize(_MONEY_QUANTUM)
SHORT_REQUEST_RESERVATION_USD = Decimal("1")

# This transport budget is deliberately independent from the 900/1800 second
# Harbor task deadline. Attempts, backoff, and body reads consume one monotonic
# budget; urllib cannot hard-cancel DNS/connect/header work, so crash recovery
# still conservatively settles any reservation that outlives the process.
UPSTREAM_TIMEOUT_SECONDS = 90.0
_MAX_UPSTREAM_TIMEOUT_SECONDS = 180.0


def load_validated_budget_ledger_state(
    path: Path,
    *,
    batch_id: str,
    total_cap_usd: Decimal | str,
    max_runs: int,
    default_run_cap_usd: Decimal | str,
    unpriced_fallback_usd: Decimal | str | None = None,
    unpriced_fallback_per_attempt: bool = False,
) -> dict[str, Any]:
    """Read and fully validate an existing ledger without locks or writes."""

    _require_safe_id(batch_id, "batch id")
    target = Path(path)
    try:
        metadata = target.lstat()
    except OSError as exc:
        raise ApiBudgetProxyError("budget ledger path is unsafe") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ApiBudgetProxyError("budget ledger path is unsafe")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ApiBudgetProxyError("budget ledger must have mode 0600")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ApiBudgetProxyError("budget ledger is invalid") from exc
    total_cap = _money(total_cap_usd)
    default_run_cap = _money(default_run_cap_usd)
    unpriced_fallback = _unpriced_fallback(
        unpriced_fallback_usd, default_run_cap=default_run_cap
    )
    if not isinstance(unpriced_fallback_per_attempt, bool):
        raise ApiBudgetProxyError("unpriced fallback accounting mode is invalid")
    _validate_state(
        value,
        batch_id=batch_id,
        total_cap=total_cap,
        max_runs=max_runs,
        default_run_cap=default_run_cap,
        unpriced_fallback=unpriced_fallback,
        unpriced_fallback_per_attempt=unpriced_fallback_per_attempt,
    )
    return value


class PersistentBudgetLedger:
    """Thread-safe, atomically persisted budget state for one benchmark batch."""

    def __init__(
        self,
        path: Path,
        *,
        batch_id: str,
        total_cap_usd: Decimal | str = BATCH_CAP_USD,
        max_runs: int = MAX_BENCHMARK_RUNS,
        default_run_cap_usd: Decimal | str = RUN_CAP_USD,
        usage_envelope: UsageEnvelope | None = None,
        unpriced_stop_threshold: int = 1,
        unpriced_fallback_usd: Decimal | str | None = None,
        unpriced_fallback_per_attempt: bool = False,
    ):
        _require_safe_id(batch_id, "batch id")
        self.path = Path(path)
        self.batch_id = batch_id
        self.total_cap = _money(total_cap_usd)
        self.default_run_cap = _money(default_run_cap_usd)
        self.unpriced_fallback = _unpriced_fallback(
            unpriced_fallback_usd, default_run_cap=self.default_run_cap
        )
        if not isinstance(unpriced_fallback_per_attempt, bool):
            raise ApiBudgetProxyError("unpriced fallback accounting mode is invalid")
        if unpriced_fallback_per_attempt and self.unpriced_fallback is None:
            raise ApiBudgetProxyError(
                "per-attempt fallback accounting requires an explicit fallback"
            )
        self.unpriced_fallback_per_attempt = unpriced_fallback_per_attempt
        self.max_runs = max_runs
        # Settling is the only place a charge is written, so the envelope is
        # enforced here rather than at each of the proxy's settle call sites.
        if usage_envelope is not None:
            usage_envelope.validate()
        self.usage_envelope = usage_envelope
        # How many unpriced settlements a run may absorb before it is stopped.
        # 1 means "stop on the first", which is the historical behaviour and the
        # default for every existing campaign.
        #
        # A provider that streams a terminal event without usage is a transient
        # fault, and stopping the run turns it into a total loss: every later
        # request is refused with HTTP 429 and the agent dies of what looks like
        # a budget stop. Two real smoke runs were destroyed this way by a single
        # upstream hiccup each. Absorbing a few is safe because the accounting
        # does not soften -- each unpriced request is still charged its full
        # reservation, and the run and batch caps still gate every later reserve
        # -- so the only thing raising this changes is whether one glitch ends
        # the run.
        if (
            isinstance(unpriced_stop_threshold, bool)
            or not isinstance(unpriced_stop_threshold, int)
            or unpriced_stop_threshold < 1
        ):
            raise ApiBudgetProxyError("unpriced stop threshold must be a positive integer")
        self.unpriced_stop_threshold = unpriced_stop_threshold
        if self.total_cap <= 0 or self.total_cap > _MAX_EXPLICIT_BATCH_CAP_USD:
            raise ApiBudgetProxyError("batch cap exceeds the supported 1600 USD maximum")
        if self.default_run_cap <= 0 or self.default_run_cap > _MAX_EXPLICIT_RUN_CAP_USD:
            raise ApiBudgetProxyError("run cap exceeds the supported 40 USD maximum")
        if (
            not isinstance(max_runs, int)
            or isinstance(max_runs, bool)
            or not 1 <= max_runs <= _MAX_EXPLICIT_BENCHMARK_RUNS
        ):
            raise ApiBudgetProxyError(
                "benchmark run count exceeds the supported maximum of 321"
            )
        self._lock = threading.RLock()
        self._closed = False
        self._prepare_parent()
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._lock_fd = self._acquire_process_lock()
        try:
            if _path_present(self.path):
                self._state = self._read_state()
                self._recover_reserved_requests()
            else:
                self._state = {
                    "schema_version": 1,
                    "batch_id": self.batch_id,
                    "total_cap_usd": _money_text(self.total_cap),
                    "max_runs": self.max_runs,
                    "default_run_cap_usd": _money_text(self.default_run_cap),
                    "runs": {},
                }
                if self.unpriced_fallback is not None:
                    self._state["unpriced_fallback_usd"] = _money_text(
                        self.unpriced_fallback
                    )
                if self.unpriced_fallback_per_attempt:
                    self._state["unpriced_fallback_per_attempt"] = True
                self._persist()
        except Exception:
            self.close()
            raise

    def __enter__(self) -> PersistentBudgetLedger:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        self._closed = True
        try:
            import fcntl

            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(self._lock_fd)

    def ensure_run(self, run_id: str, *, cap_usd: Decimal | str | None = None) -> None:
        self._register_run(run_id, cap_usd=cap_usd, reject_existing=False)

    def claim_run(self, run_id: str, *, cap_usd: Decimal | str | None = None) -> None:
        """Consume one benchmark invocation slot, rejecting every reused run id."""

        self._register_run(run_id, cap_usd=cap_usd, reject_existing=True)

    def resume_pristine_run(
        self, run_id: str, *, cap_usd: Decimal | str | None = None
    ) -> None:
        """Reuse one claimed run only when it provably consumed nothing.

        The process lock excludes another normal ledger writer. This method is
        intentionally narrower than ``ensure_run``: a stopped, tainted, spent,
        reserved, or even merely requested run must receive a new attempt id.
        """

        _require_safe_id(run_id, "run id")
        cap = self.default_run_cap if cap_usd is None else _money(cap_usd)
        with self._lock:
            self._assert_open()
            run = self._require_run(run_id)
            if Decimal(run["cap_usd"]) != cap:
                raise ApiBudgetProxyError("pristine run cap differs")
            if (
                Decimal(run["spent_usd"]) != 0
                or run["requests"]
                or run["stopped"] is not False
                or run["stop_reason"] is not None
                or run.get("infra_taint") is not None
            ):
                raise ApiBudgetProxyError("benchmark run is not pristine")

    def resume_unsent_run(
        self, run_id: str, *, cap_usd: Decimal | str | None = None
    ) -> None:
        """Reuse one run whose prior reservations are proven not to have sent.

        Crash recovery converts an outstanding reservation with zero persisted
        upstream attempts into ``not_sent_unbilled`` at zero cost.  That durable
        row is stronger evidence than an empty in-memory request set, but it
        intentionally makes :meth:`resume_pristine_run` reject the run.  A
        bounded formal campaign may call this narrower transition when it must
        keep the same frozen run ID and is forbidden from replacing a slot.

        No request row is deleted: later accounting can distinguish the zero-
        attempt recovery record from requests that actually reached upstream.
        """

        _require_safe_id(run_id, "run id")
        cap = self.default_run_cap if cap_usd is None else _money(cap_usd)
        with self._lock:
            self._assert_open()
            run = self._require_run(run_id)
            requests = run.get("requests")
            if Decimal(run["cap_usd"]) != cap:
                raise ApiBudgetProxyError("unsent run cap differs")
            if (
                Decimal(run["spent_usd"]) != 0
                or not isinstance(requests, dict)
                or not requests
                or run["stopped"] is not False
                or run["stop_reason"] is not None
                or run.get("infra_taint") is not None
                or any(
                    not isinstance(request, dict)
                    or request.get("status") != "settled"
                    or request.get("attempt_count") != 0
                    or request.get("charged_usd") != "0.000000"
                    or request.get("usage_valid") is not False
                    or request.get("settlement_kind")
                    != _SETTLEMENT_NOT_SENT_UNBILLED
                    for request in requests.values()
                )
            ):
                raise ApiBudgetProxyError("benchmark run is not proven unsent")

    def _register_run(
        self,
        run_id: str,
        *,
        cap_usd: Decimal | str | None,
        reject_existing: bool,
    ) -> None:
        _require_safe_id(run_id, "run id")
        cap = self.default_run_cap if cap_usd is None else _money(cap_usd)
        if cap <= 0 or cap > self.default_run_cap:
            raise ApiBudgetProxyError("run cap exceeds the configured per-run maximum")
        with self._lock:
            self._assert_open()
            runs = self._state["runs"]
            if run_id in runs:
                if reject_existing:
                    raise BudgetStopped("benchmark run id was already consumed")
                if Decimal(runs[run_id]["cap_usd"]) != cap:
                    raise ApiBudgetProxyError("existing run cap differs from the requested cap")
                return
            if len(runs) >= self.max_runs:
                raise BudgetStopped("benchmark run limit is exhausted")
            runs[run_id] = {
                "cap_usd": _money_text(cap),
                "spent_usd": _money_text(Decimal(0)),
                "stopped": False,
                "stop_reason": None,
                "requests": {},
            }
            self._persist()

    def reserve(
        self,
        run_id: str,
        request_id: str,
        amount_usd: Decimal | str | None = None,
        *,
        additional_capacity_usd: Decimal | str = Decimal(0),
    ) -> Decimal:
        _require_safe_id(run_id, "run id")
        _require_safe_id(request_id, "request id")
        with self._lock:
            self._assert_open()
            run = self._require_run(run_id)
            if run["stopped"]:
                raise BudgetStopped("benchmark run is stopped")
            if request_id in run["requests"]:
                raise BudgetStopped("request id was already used; retries are disabled")
            run_spent = Decimal(run["spent_usd"])
            run_reserved = _reserved_total(run)
            batch_spent, batch_reserved = self._totals()
            if amount_usd is None:
                amount = min(
                    MAX_REQUEST_RESERVATION_USD,
                    Decimal(run["cap_usd"]) - run_spent - run_reserved,
                    self.total_cap - batch_spent - batch_reserved,
                ).quantize(_MONEY_QUANTUM)
            else:
                amount = _money(amount_usd)
            additional_capacity = _money(additional_capacity_usd)
            if amount <= 0 or amount > Decimal(run["cap_usd"]):
                raise BudgetCapacityExhausted(
                    "request reservation has no authorized capacity"
                )
            minimum_fallback_reservation = (
                self.unpriced_fallback * _MAX_UPSTREAM_ATTEMPTS
                if self.unpriced_fallback_per_attempt
                and self.unpriced_fallback is not None
                else self.unpriced_fallback
            )
            if (
                minimum_fallback_reservation is not None
                and amount < minimum_fallback_reservation
            ):
                raise BudgetCapacityExhausted(
                    "request reservation cannot cover the unpriced fallback"
                )
            if (
                run_spent + run_reserved + amount + additional_capacity
                > Decimal(run["cap_usd"])
            ):
                raise BudgetCapacityExhausted(
                    "request reservation would exceed the run cost cap"
                )
            if (
                batch_spent + batch_reserved + amount + additional_capacity
                > self.total_cap
            ):
                raise BudgetCapacityExhausted(
                    "request reservation would exceed the batch cost cap"
                )
            run["requests"][request_id] = {
                "status": "reserved",
                "reserved_usd": _money_text(amount),
                "charged_usd": None,
                "usage_valid": None,
                "attempt_count": 0,
                "settlement_kind": None,
            }
            self._persist()
            return amount

    def begin_attempt(self, run_id: str, request_id: str, *, max_attempts: int) -> int:
        """Persist one upstream attempt before any bytes can leave the process."""

        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= _MAX_UPSTREAM_ATTEMPTS
        ):
            raise ApiBudgetProxyError("upstream attempt limit is invalid")
        with self._lock:
            self._assert_open()
            run = self._require_run(run_id)
            request_state = run["requests"].get(request_id)
            if not isinstance(request_state, dict) or request_state.get("status") != "reserved":
                raise ApiBudgetProxyError("request has no active reservation")
            attempt_count = request_state["attempt_count"]
            if (
                isinstance(attempt_count, bool)
                or not isinstance(attempt_count, int)
                or attempt_count < 0
                or attempt_count >= max_attempts
            ):
                raise ApiBudgetProxyError("upstream attempt limit is exhausted")
            attempt_count += 1
            request_state["attempt_count"] = attempt_count
            self._persist()
            return attempt_count

    def settle(
        self,
        run_id: str,
        request_id: str,
        usage: Usage | None,
        *,
        pricing: ModelPricing,
        stop_reason: str | None = None,
    ) -> Settlement:
        if stop_reason is not None and stop_reason not in _STOP_REASONS:
            raise ApiBudgetProxyError("budget stop reason is invalid")
        with self._lock:
            self._assert_open()
            run = self._require_run(run_id)
            request_state = run["requests"].get(request_id)
            if not isinstance(request_state, dict) or request_state.get("status") != "reserved":
                raise ApiBudgetProxyError("request has no active reservation")
            reserved = Decimal(request_state["reserved_usd"])
            attempt_count = request_state["attempt_count"]
            if (
                isinstance(attempt_count, bool)
                or not isinstance(attempt_count, int)
                or not 0 <= attempt_count <= _MAX_UPSTREAM_ATTEMPTS
            ):
                raise ApiBudgetProxyError("budget settlement attempt count is invalid")
            usage_valid = True
            outside_envelope = False
            try:
                if attempt_count == 0:
                    if usage is not None:
                        raise ApiBudgetProxyError(
                            "budget settlement has no persisted attempt"
                        )
                    raise ApiBudgetProxyError("request was not sent")
                if usage is None:
                    raise ApiBudgetProxyError("response usage is missing")
                if self.usage_envelope is not None:
                    try:
                        self.usage_envelope.require(usage)
                    except ApiBudgetProxyError:
                        outside_envelope = True
                        raise
                charged = price_usage(usage, pricing=pricing)
            except ApiBudgetProxyError:
                usage_valid = False
                if attempt_count == 0 and self.unpriced_fallback is not None:
                    charged = Decimal(0)
                    settlement_kind = _SETTLEMENT_NOT_SENT_UNBILLED
                    if stop_reason is not None:
                        run["stopped"] = True
                        run["stop_reason"] = stop_reason
                elif outside_envelope:
                    charged = reserved
                    settlement_kind = _SETTLEMENT_CONSERVATIVE_RESERVATION
                    # Not a provider hiccup: a request outside the frozen
                    # envelope breaks the arithmetic the cap is derived from,
                    # so the run stops regardless of the threshold.
                    run["stopped"] = True
                    run["stop_reason"] = "usage_outside_frozen_envelope"
                else:
                    charged = (
                        self.unpriced_fallback
                        * (attempt_count if self.unpriced_fallback_per_attempt else 1)
                        if self.unpriced_fallback is not None
                        else reserved
                    )
                    settlement_kind = (
                        _SETTLEMENT_UNPRICED_FALLBACK
                        if self.unpriced_fallback is not None
                        else _SETTLEMENT_CONSERVATIVE_RESERVATION
                    )
                    # Count this settlement plus the unpriced ones already on
                    # the run.
                    unpriced = 1 + sum(
                        1
                        for item in run["requests"].values()
                        if isinstance(item, dict)
                        and item.get("settlement_kind") in _UNPRICED_SETTLEMENT_KINDS
                    )
                    if unpriced >= self.unpriced_stop_threshold:
                        run["stopped"] = True
                        run["stop_reason"] = (
                            stop_reason or "missing_or_invalid_usage"
                        )
                if attempt_count >= 1:
                    reason = run["stop_reason"] or stop_reason or "missing_or_invalid_usage"
                    _record_infra_taint(run, reason)
            else:
                if charged > reserved:
                    run["stopped"] = True
                    run["stop_reason"] = "usage_cost_exceeded_reservation"
                    settlement_kind = _SETTLEMENT_USAGE_PRICED_OVERAGE
                else:
                    settlement_kind = _SETTLEMENT_USAGE_PRICED
                    if stop_reason is not None:
                        run["stopped"] = True
                        run["stop_reason"] = stop_reason
            request_state["status"] = "settled"
            request_state["charged_usd"] = _money_text(charged)
            request_state["usage_valid"] = usage_valid
            request_state["settlement_kind"] = settlement_kind
            run["spent_usd"] = _money_text(Decimal(run["spent_usd"]) + charged)
            self._persist()
            return Settlement(
                charged,
                usage_valid,
                bool(run["stopped"]),
                attempt_count,
                settlement_kind,
                usage if usage_valid else None,
            )

    def settle_operator_confirmed_unbilled(
        self,
        run_id: str,
        request_id: str,
        *,
        stop_reason: str,
    ) -> Settlement:
        """Settle an allowlisted canonical provider rejection at zero charge."""

        if stop_reason not in {
            "operator_confirmed_unbilled_attempts_exhausted",
            "operator_confirmed_unbilled_deadline_exhausted",
            "operator_confirmed_unbilled_proxy_closing",
        }:
            raise ApiBudgetProxyError("budget stop reason is invalid")
        with self._lock:
            self._assert_open()
            run = self._require_run(run_id)
            request_state = run["requests"].get(request_id)
            if not isinstance(request_state, dict) or request_state.get("status") != "reserved":
                raise ApiBudgetProxyError("request has no active reservation")
            attempt_count = request_state["attempt_count"]
            if (
                isinstance(attempt_count, bool)
                or not isinstance(attempt_count, int)
                or not 1 <= attempt_count <= _MAX_UPSTREAM_ATTEMPTS
            ):
                raise ApiBudgetProxyError("unbilled settlement has no persisted attempt")
            request_state["status"] = "settled"
            request_state["charged_usd"] = _money_text(Decimal(0))
            request_state["usage_valid"] = False
            request_state["settlement_kind"] = _SETTLEMENT_OPERATOR_CONFIRMED_UNBILLED
            run["stopped"] = True
            run["stop_reason"] = stop_reason
            # Billed nothing, but the upstream still failed: the run saw an
            # infrastructure fault and cannot stand as a product observation.
            _record_infra_taint(run, stop_reason)
            self._persist()
            return Settlement(
                Decimal(0),
                False,
                True,
                attempt_count,
                _SETTLEMENT_OPERATOR_CONFIRMED_UNBILLED,
                None,
            )

    def stop_run(self, run_id: str, *, stop_reason: str) -> None:
        """Persist a fail-closed run stop before another request is reserved."""

        if stop_reason not in _STOP_REASONS:
            raise ApiBudgetProxyError("budget stop reason is invalid")
        with self._lock:
            self._assert_open()
            run = self._require_run(run_id)
            if not run["stopped"]:
                run["stopped"] = True
                run["stop_reason"] = stop_reason
                self._persist()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._assert_open()
            spent, reserved = self._totals()
            snapshot = {
                "schema_version": 1,
                "batch_id": self.batch_id,
                "total_cap_usd": _money_text(self.total_cap),
                "max_runs": self.max_runs,
                "default_run_cap_usd": _money_text(self.default_run_cap),
                "run_slots_used": len(self._state["runs"]),
                "spent_usd": _money_text(spent),
                "reserved_usd": _money_text(reserved),
                "remaining_uncommitted_usd": _money_text(self.total_cap - spent - reserved),
                "runs": json.loads(json.dumps(self._state["runs"])),
            }
            if self.unpriced_fallback is not None:
                snapshot["unpriced_fallback_usd"] = _money_text(self.unpriced_fallback)
            if self.unpriced_fallback_per_attempt:
                snapshot["unpriced_fallback_per_attempt"] = True
            return snapshot

    def recover_interrupted_requests(self) -> None:
        """Settle every outstanding reservation using the crash rules now.

        Normal process recovery performs this transition when the ledger is
        reopened.  A campaign that catches a terminal execution error must be
        able to persist the same conservative close before publishing its
        invalid terminal state, instead of leaving a reservation open until a
        later operator invocation.
        """

        with self._lock:
            self._assert_open()
            self._recover_reserved_requests()

    def _prepare_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink() or not self.path.parent.is_dir():
            raise ApiBudgetProxyError("budget ledger parent is unsafe")
        if _path_present(self.path) and (self.path.is_symlink() or not self.path.is_file()):
            raise ApiBudgetProxyError("budget ledger path is unsafe")

    def _acquire_process_lock(self) -> int:
        if _path_present(self._lock_path) and self._lock_path.is_symlink():
            raise ApiBudgetProxyError("budget ledger lock path is unsafe")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._lock_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, OSError) as exc:
            os.close(descriptor)
            raise ApiBudgetProxyError("budget ledger is already active or cannot be locked") from exc
        return descriptor

    def _read_state(self) -> dict[str, Any]:
        return load_validated_budget_ledger_state(
            self.path,
            batch_id=self.batch_id,
            total_cap_usd=self.total_cap,
            max_runs=self.max_runs,
            default_run_cap_usd=self.default_run_cap,
            unpriced_fallback_usd=self.unpriced_fallback,
            unpriced_fallback_per_attempt=self.unpriced_fallback_per_attempt,
        )

    def _recover_reserved_requests(self) -> None:
        recovered = False
        for run in self._state["runs"].values():
            for request_state in run["requests"].values():
                if request_state["status"] != "reserved":
                    continue
                attempt_count = request_state["attempt_count"]
                request_state["status"] = "settled"
                if attempt_count == 0 and self.unpriced_fallback is not None:
                    charged = Decimal(0)
                    settlement_kind = _SETTLEMENT_NOT_SENT_UNBILLED
                elif self.unpriced_fallback is not None:
                    charged = self.unpriced_fallback * (
                        attempt_count if self.unpriced_fallback_per_attempt else 1
                    )
                    settlement_kind = _SETTLEMENT_UNPRICED_FALLBACK
                else:
                    charged = Decimal(request_state["reserved_usd"])
                    settlement_kind = _SETTLEMENT_CONSERVATIVE_RESERVATION
                request_state["charged_usd"] = _money_text(charged)
                request_state["usage_valid"] = False
                request_state["settlement_kind"] = settlement_kind
                run["spent_usd"] = _money_text(Decimal(run["spent_usd"]) + charged)
                if attempt_count >= 1 or self.unpriced_fallback is None:
                    run["stopped"] = True
                    run["stop_reason"] = "interrupted_request"
                recovered = True
        if recovered:
            self._persist()

    def _persist(self) -> None:
        encoded = (json.dumps(self._state, sort_keys=True, separators=(",", ":")) + "\n").encode()
        temporary = self.path.with_name(
            f".{self.path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
        )
        if _path_present(temporary):
            raise ApiBudgetProxyError("budget ledger temporary path already exists")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            _fsync_directory(self.path.parent)
        except Exception:
            if temporary.is_file() and not temporary.is_symlink():
                temporary.unlink()
            raise

    def _require_run(self, run_id: str) -> dict[str, Any]:
        run = self._state["runs"].get(run_id)
        if not isinstance(run, dict):
            raise ApiBudgetProxyError("benchmark run is not registered")
        return run

    def _totals(self) -> tuple[Decimal, Decimal]:
        spent = sum(
            (Decimal(run["spent_usd"]) for run in self._state["runs"].values()),
            Decimal(0),
        )
        reserved = sum(
            (_reserved_total(run) for run in self._state["runs"].values()), Decimal(0)
        )
        return spent, reserved

    def _assert_open(self) -> None:
        if self._closed:
            raise ApiBudgetProxyError("budget ledger is closed")


class RedactedMetadataStore:
    """Small atomic JSON store containing only bounded, non-secret observations."""

    def __init__(self, path: Path, *, secrets_to_exclude: tuple[str, ...]):
        if not secrets_to_exclude or any(not secret for secret in secrets_to_exclude):
            raise ApiBudgetProxyError("in-memory secrets are required for redaction")
        self.path = Path(path)
        self._secrets = tuple(secret.encode() for secret in secrets_to_exclude)
        lock_key = str(self.path.absolute())
        with _METADATA_LOCKS_GUARD:
            self._lock = _METADATA_LOCKS.setdefault(lock_key, threading.Lock())
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink() or not self.path.parent.is_dir():
            raise ApiBudgetProxyError("metadata parent is unsafe")
        if _path_present(self.path) and (self.path.is_symlink() or not self.path.is_file()):
            raise ApiBudgetProxyError("metadata path is unsafe")

    def append(self, observation: Mapping[str, Any]) -> None:
        expected = {
            "request_id",
            "body_sha256",
            "canonical_body_sha256",
            "role",
            "role_provenance",
            "declared_role",
            "inferred_role",
            "model",
            "reasoning_effort",
            "stream",
            "shape",
            "contract_match",
            "upstream_status",
            "usage_valid",
            "charged_usd",
            "attempt_count",
            "settlement_kind",
            "usage",
        }
        optional = {
            "stream_end_kind",
            "terminal_event_type",
            "terminal_response_status",
            "terminal_error_code",
        }
        if not expected.issubset(observation) or not set(observation).issubset(
            expected | optional
        ):
            raise ApiBudgetProxyError("metadata observation differs from schema v1")
        if observation.get("stream_end_kind") not in {
            None,
            "terminal",
            "clean_eof",
            "read_error",
            "size_limit",
        }:
            raise ApiBudgetProxyError("metadata stream end kind is invalid")
        terminal_event_type = observation.get("terminal_event_type")
        if terminal_event_type not in {
            None,
            "response.completed",
            "response.failed",
            "response.incomplete",
            "error",
        }:
            raise ApiBudgetProxyError("metadata terminal event type is invalid")
        terminal_response_status = observation.get("terminal_response_status")
        if terminal_response_status not in {
            None,
            "completed",
            "failed",
            "incomplete",
            "cancelled",
        }:
            raise ApiBudgetProxyError("metadata terminal response status is invalid")
        terminal_error_code = observation.get("terminal_error_code")
        if terminal_error_code is not None and (
            not isinstance(terminal_error_code, str)
            or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", terminal_error_code) is None
        ):
            raise ApiBudgetProxyError("metadata terminal error code is invalid")
        usage = observation["usage"]
        if (
            (observation.get("usage_valid") is True) != isinstance(usage, dict)
            or (
                isinstance(usage, dict)
                and (
                    set(usage)
                    != {
                        "input_tokens",
                        "cached_input_tokens",
                        "cache_write_input_tokens",
                        "output_tokens",
                    }
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, int)
                        or value < 0
                        for value in usage.values()
                    )
                )
            )
        ):
            raise ApiBudgetProxyError("metadata usage observation is invalid")
        encoded_observation = json.dumps(
            dict(observation), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        if any(secret in encoded_observation for secret in self._secrets):
            raise ApiBudgetProxyError("secret appeared in redacted metadata")
        with self._lock:
            if _path_present(self.path):
                if self.path.is_symlink() or not self.path.is_file():
                    raise ApiBudgetProxyError("metadata path is unsafe")
                if stat.S_IMODE(self.path.stat().st_mode) != 0o600:
                    raise ApiBudgetProxyError("metadata file must have mode 0600")
                try:
                    state = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise ApiBudgetProxyError("metadata file is invalid") from exc
                if not isinstance(state, dict) or set(state) != {"schema_version", "requests"}:
                    raise ApiBudgetProxyError("metadata file differs from schema v1")
                if state["schema_version"] != 1 or not isinstance(state["requests"], list):
                    raise ApiBudgetProxyError("metadata file differs from schema v1")
            else:
                state = {"schema_version": 1, "requests": []}
            state["requests"].append(dict(observation))
            _atomic_private_json(self.path, state)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class _UrllibTransport:
    """No-retry/no-redirect HTTP transport; endpoint override is test-only."""

    def __init__(self, *, endpoint_override: str | None = None):
        if endpoint_override is not None:
            parsed = urlsplit(endpoint_override)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ApiBudgetProxyError("test upstream override must be loopback HTTP")
        self._endpoint_override = endpoint_override
        # A loopback override must never be routed through an ambient
        # HTTP_PROXY. Python's no_proxy matching does not understand the `127.*`
        # glob most local proxy managers export, so without an empty
        # ProxyHandler the offline capture tests reach the user's real proxy and
        # come back 502. The production path keeps the default env behaviour.
        handlers: list[Any] = [_NoRedirect()]
        if endpoint_override is not None:
            handlers.append(ProxyHandler({}))
        self._opener = build_opener(*handlers)

    def open(
        self,
        upstream_endpoint: str,
        *,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any:
        endpoint = self._endpoint_override or upstream_endpoint
        request = Request(endpoint, data=body, headers=dict(headers), method="POST")
        return self._opener.open(request, timeout=timeout)


class _LoopbackServer(ThreadingHTTPServer):
    # server_close() must join every active handler before the enclosing budget
    # ledger or metadata lifecycle may advance.
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False


class LoopbackResponsesProxy:
    """Short-lived local HTTP proxy for a single registered benchmark run."""

    def __init__(
        self,
        *,
        upstream_base_url: str,
        api_key: str,
        ledger: PersistentBudgetLedger,
        run_id: str,
        metadata_path: Path,
        main_model: str,
        main_effort: str,
        main_pricing: ModelPricing,
        guardian_model: str,
        guardian_pricing: ModelPricing,
        guardian_effort: str,
        max_attempts: int,
        retry_backoff_seconds: float,
        unbilled_retry_statuses: tuple[int, ...],
        request_reservation_usd: Decimal | str | None = None,
        run_cap_usd: Decimal | str | None = None,
        max_guardian_logical_requests: int | None = None,
        # RONDO Multi's Root and its members call the model at the same time.
        # The single-main assumption below predates that product, so campaigns
        # raise this deliberately; every other campaign keeps the strict 1. It is
        # a count rather than a flag so "concurrency is allowed" also states how
        # much, which is what a per-run cap has to be sized against -- and so a
        # stray truthy string cannot silently unbound it.
        max_concurrent_main: int = 1,
        usage_envelope: UsageEnvelope | None = None,
        max_logical_requests: int | None = None,
        timeout_seconds: float = UPSTREAM_TIMEOUT_SECONDS,
        symmetry_preflight: Any | None = None,
        preflight_side: Any | None = None,
        preflight_task_id: str | None = None,
        _transport: _UrllibTransport | None = None,
        _monotonic: Any = time.monotonic,
        _sleep: Any = time.sleep,
    ):
        self.upstream_endpoint = _compatible_responses_endpoint(upstream_base_url)
        if not api_key or "\r" in api_key or "\n" in api_key:
            raise ApiBudgetProxyError("an in-memory API key is required")
        if (
            not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
            or timeout_seconds > _MAX_UPSTREAM_TIMEOUT_SECONDS
        ):
            raise ApiBudgetProxyError("proxy timeout must be within the 180 second limit")
        _require_safe_id(run_id, "run id")
        try:
            main_pricing.validate()
            guardian_pricing.validate()
        except (AttributeError, ValueError) as exc:
            raise ApiBudgetProxyError("proxy model pricing is invalid") from exc
        if main_model != main_pricing.model_id or guardian_model != guardian_pricing.model_id:
            raise ApiBudgetProxyError("proxy model differs from its pricing snapshot")
        if main_model == guardian_model and main_pricing != guardian_pricing:
            raise ApiBudgetProxyError("one proxy model cannot have conflicting pricing")
        if main_effort not in _GUARDIAN_EFFORTS:
            raise ApiBudgetProxyError("proxy main reasoning effort is invalid")
        if guardian_effort not in _GUARDIAN_EFFORTS:
            raise ApiBudgetProxyError("proxy Guardian reasoning effort is invalid")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= max_attempts <= _MAX_UPSTREAM_ATTEMPTS
        ):
            raise ApiBudgetProxyError("proxy attempts must be between one and five")
        if (
            isinstance(retry_backoff_seconds, bool)
            or not isinstance(retry_backoff_seconds, (int, float))
            or not math.isfinite(retry_backoff_seconds)
            or not 0 <= retry_backoff_seconds <= 30
        ):
            raise ApiBudgetProxyError("proxy retry backoff is invalid")
        request_reservation: Decimal | None = None
        if request_reservation_usd is not None:
            if isinstance(request_reservation_usd, bool):
                raise ApiBudgetProxyError("proxy request reservation is invalid")
            try:
                request_reservation = _money(request_reservation_usd)
            except (ArithmeticError, TypeError, ValueError) as exc:
                raise ApiBudgetProxyError("proxy request reservation is invalid") from exc
            if request_reservation <= 0 or request_reservation > _MAX_EXPLICIT_RUN_CAP_USD:
                raise ApiBudgetProxyError("proxy request reservation is invalid")
        if (
            not isinstance(unbilled_retry_statuses, tuple)
            or unbilled_retry_statuses != tuple(sorted(unbilled_retry_statuses))
            or len(set(unbilled_retry_statuses)) != len(unbilled_retry_statuses)
            or any(
                isinstance(status, bool)
                or not isinstance(status, int)
                or not 400 <= status <= 599
                for status in unbilled_retry_statuses
            )
        ):
            raise ApiBudgetProxyError("proxy unbilled retry statuses are invalid")
        if max_guardian_logical_requests is not None and (
            isinstance(max_guardian_logical_requests, bool)
            or not isinstance(max_guardian_logical_requests, int)
            or not 1 <= max_guardian_logical_requests <= 3
        ):
            raise ApiBudgetProxyError(
                "proxy Guardian logical request limit must be between one and three"
            )
        if max_logical_requests is not None and (
            isinstance(max_logical_requests, bool)
            or not isinstance(max_logical_requests, int)
            or not 1 <= max_logical_requests <= 4
        ):
            raise ApiBudgetProxyError(
                "proxy short-test logical request limit must be between one and four"
            )
        if (
            isinstance(max_concurrent_main, bool)
            or not isinstance(max_concurrent_main, int)
            or not 1 <= max_concurrent_main <= _MAX_CONCURRENT_MAIN
        ):
            raise ApiBudgetProxyError(
                "proxy concurrent main limit must be between one and eight"
            )
        if usage_envelope is not None:
            usage_envelope.validate()
            if getattr(ledger, "usage_envelope", None) != usage_envelope:
                # The ledger is where a charge is written, so an envelope the
                # ledger does not share would not actually bound anything.
                raise ApiBudgetProxyError("proxy usage envelope differs from the ledger")
            required = max(
                _maximum_usage_cost(main_pricing, usage_envelope),
                _maximum_usage_cost(guardian_pricing, usage_envelope),
            )
            if request_reservation is None or request_reservation < required:
                # Without this the ledger's caps are advisory: a settled request
                # can cost more than it reserved and carry the batch past its
                # authorized total after the money is already gone.
                raise ApiBudgetProxyError(
                    "proxy request reservation is below the frozen usage envelope cost"
                )
        if not callable(_monotonic) or not callable(_sleep):
            raise ApiBudgetProxyError("proxy clock is invalid")
        if symmetry_preflight is not None and (
            preflight_side is None
            or not isinstance(preflight_task_id, str)
            or not preflight_task_id
        ):
            raise ApiBudgetProxyError("symmetry preflight identity is incomplete")
        ledger.ensure_run(run_id, cap_usd=run_cap_usd)
        self._symmetry_preflight = symmetry_preflight
        self._preflight_side = preflight_side
        self._preflight_task_id = preflight_task_id
        self._api_key = api_key
        self._downstream_api_key = "rondo-eval-" + secrets.token_urlsafe(32)
        self._ledger = ledger
        self._run_id = run_id
        self._main_model = main_model
        self._main_effort = main_effort
        self._guardian_model = guardian_model
        self._guardian_effort = guardian_effort
        self._pricing_by_role = {
            "main": main_pricing,
            "guardian": guardian_pricing,
        }
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = float(retry_backoff_seconds)
        self._unbilled_retry_statuses = frozenset(unbilled_retry_statuses)
        self._request_reservations = {
            "main": request_reservation or _maximum_usage_cost(main_pricing),
            "guardian": request_reservation or _maximum_usage_cost(guardian_pricing),
        }
        self._max_guardian_logical_requests = max_guardian_logical_requests
        self._guardian_logical_requests = 0
        self._guardian_body_sha256s: set[str] = set()
        self._main_request_ids: set[str] = set()
        self._max_concurrent_main = max_concurrent_main
        self._usage_envelope = usage_envelope
        self._max_logical_requests = max_logical_requests
        self._logical_requests = 0
        self._request_policy_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._closing = threading.Event()
        self._metadata = RedactedMetadataStore(
            metadata_path,
            secrets_to_exclude=(api_key, self._downstream_api_key),
        )
        self._timeout = timeout_seconds
        self._transport = _transport or _UrllibTransport()
        self._monotonic = _monotonic
        self._sleep = _sleep
        self._server: _LoopbackServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def main_model(self) -> str:
        """The model this proxy meters and forwards. Callers compare against it."""

        return self._main_model

    @property
    def main_effort(self) -> str:
        return self._main_effort

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise ApiBudgetProxyError("loopback proxy is not running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    @property
    def downstream_api_key(self) -> str:
        """Return the ephemeral key that the runner injects into the child only."""

        return self._downstream_api_key

    @property
    def docker_base_url(self) -> str:
        """Return the Docker Desktop bridge for the same loopback listener.

        The listener remains bound to 127.0.0.1.  RONDO's B1 doctor verifies
        that Docker Desktop's ``host.docker.internal`` forwarder reaches that
        loopback socket before a paid run is permitted.
        """

        if self._server is None:
            raise ApiBudgetProxyError("loopback proxy is not running")
        host, port = self._server.server_address[:2]
        if host != "127.0.0.1" or not isinstance(port, int) or port <= 0:
            raise ApiBudgetProxyError("loopback proxy address is invalid")
        return f"http://host.docker.internal:{port}/v1"

    def __enter__(self) -> LoopbackResponsesProxy:
        return self.start()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def start(self) -> LoopbackResponsesProxy:
        if self._server is not None:
            raise ApiBudgetProxyError("loopback proxy is already running")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(owner._timeout)

            def do_POST(self) -> None:  # noqa: N802
                owner._handle(self)

            def do_GET(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_PUT(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_DELETE(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_HEAD(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_OPTIONS(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_PATCH(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = _LoopbackServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rondo-api-budget-proxy",
            daemon=True,
        )
        self._thread.start()
        return self

    def close(self) -> None:
        server = self._server
        thread = self._thread
        # Linearize shutdown against the start of every paid upstream forward.
        # A forward that owns this lock is already persisted and must settle;
        # after this flag is set no transport call can begin.
        with self._lifecycle_lock:
            self._closing.set()
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join()

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        if self._closing.is_set():
            self._reject(handler, 503, "proxy_closing")
            return
        if not self._authenticate(handler):
            self._reject(handler, 401, "unauthorized")
            return
        if handler.path != "/v1/responses":
            self._reject(handler, 404, "responses_path_required")
            return
        if "websocket" in handler.headers.get("Upgrade", "").lower():
            self._reject(handler, 400, "websocket_disabled")
            return
        for name in _RETRY_HEADERS:
            value = handler.headers.get(name)
            if value is not None and value.strip() not in {"", "0"}:
                self._reject(handler, 409, "retries_disabled")
                return
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except ValueError:
            self._reject(handler, 411, "content_length_required")
            return
        if length <= 0 or length > _MAX_REQUEST_BYTES:
            self._reject(handler, 413, "request_size_invalid")
            return
        body = handler.rfile.read(length)
        if len(body) != length:
            self._reject(handler, 400, "request_body_incomplete")
            return
        # Consume the bounded request body before rejecting a malformed Lite
        # routing header. Closing a socket with unread request bytes can reset
        # the connection before the client receives the structured error body.
        try:
            forward_lite_header = _validated_lite_header(handler.headers)
        except ApiBudgetProxyError:
            self._reject(handler, 400, "invalid_lite_header")
            return
        try:
            user_agent = _validated_user_agent(handler.headers)
        except ApiBudgetProxyError:
            self._reject(handler, 400, "invalid_user_agent")
            return
        try:
            originator = _validated_originator(handler.headers)
        except ApiBudgetProxyError:
            self._reject(handler, 400, "invalid_originator")
            return
        request_id = handler.headers.get("X-RONDO-Eval-Request-Id") or uuid.uuid4().hex
        role_header = handler.headers.get("X-RONDO-Eval-Role")
        declared_role = role_header.strip().lower() if role_header is not None else None
        try:
            _require_safe_id(request_id, "request id")
            request_metadata = _inspect_request(
                body,
                declared_role,
                main_model=self._main_model,
                main_effort=self._main_effort,
                guardian_model=self._guardian_model,
                guardian_effort=self._guardian_effort,
            )
            if declared_role is None:
                declared_role = request_metadata["role"]
                request_metadata["role_provenance"] = "declared"
                request_metadata["declared_role"] = declared_role
            # The body is parsed but nothing has been reserved or forwarded
            # yet.  This is the only point where an asymmetric pair can be
            # stopped without either side paying for it.
            if self._symmetry_preflight is not None:
                try:
                    self._symmetry_preflight.register(
                        task_id=self._preflight_task_id,
                        role=request_metadata["role"],
                        side=self._preflight_side,
                        request=json.loads(body),
                    )
                except Exception as exc:  # fail closed on any preflight failure
                    raise _SymmetryPreflightRejected(_preflight_reason(exc)) from None
            with self._lifecycle_lock:
                if self._closing.is_set():
                    self._reject(handler, 503, "proxy_closing")
                    return
                self._claim_and_reserve_logical_request(
                    request_metadata["role"],
                    request_metadata["body_sha256"],
                    request_id,
                )
        except _SymmetryPreflightRejected as exc:
            self._reject(handler, 409, exc.reason)
            return
        except _GuardianDuplicateLogicalRequest:
            self._reject(handler, 409, "guardian_duplicate_logical_request_rejected")
            return
        except _GuardianLogicalRequestLimitExceeded:
            self._reject(handler, 409, "guardian_logical_request_limit_exceeded")
            return
        except _LogicalRequestLimitExceeded:
            self._reject(handler, 409, "logical_request_limit_exceeded")
            return
        except BudgetCapacityExhausted:
            self._ledger.stop_run(
                self._run_id,
                stop_reason="budget_capacity_exhausted",
            )
            self._reject(handler, 429, "budget_stopped")
            return
        except BudgetStopped:
            self._reject(handler, 429, "budget_stopped")
            return
        except ApiBudgetProxyError:
            self._reject(handler, 400, "request_rejected")
            return

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": handler.headers.get("Accept", "application/json"),
            "User-Agent": user_agent,
        }
        if originator is not None:
            headers["originator"] = originator
        if forward_lite_header:
            headers[_LITE_HEADER] = "true"
        for name in ("OpenAI-Beta", "OpenAI-Organization", "OpenAI-Project"):
            value = handler.headers.get(name)
            if value:
                headers[name] = value
        pricing = self._pricing_by_role[request_metadata["role"]]
        deadline = self._monotonic() + self._timeout
        last_unbilled_status = 0
        while True:
            with self._lifecycle_lock:
                if self._closing.is_set():
                    if last_unbilled_status:
                        self._stop_confirmed_unbilled(
                            handler,
                            request_id,
                            request_metadata,
                            last_unbilled_status,
                            "operator_confirmed_unbilled_proxy_closing",
                        )
                    else:
                        settlement = self._ledger.settle(
                            self._run_id,
                            request_id,
                            None,
                            pricing=pricing,
                            stop_reason="proxy_closing",
                        )
                        self._save_observation(
                            request_id,
                            request_metadata,
                            0,
                            settlement,
                        )
                        self._reject(handler, 503, "proxy_closing")
                    return
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                if last_unbilled_status:
                    self._stop_confirmed_unbilled(
                        handler,
                        request_id,
                        request_metadata,
                        last_unbilled_status,
                        "operator_confirmed_unbilled_deadline_exhausted",
                    )
                else:
                    settlement = self._ledger.settle(
                        self._run_id,
                        request_id,
                        None,
                        pricing=pricing,
                        stop_reason="upstream_deadline_exhausted",
                    )
                    self._save_observation(request_id, request_metadata, 0, settlement)
                    self._reject(handler, 502, "upstream_deadline_exhausted")
                return

            try:
                # Persist and start the forward under the same lifecycle lock.
                # close() may wait for an in-flight response, but cannot race a
                # newly billed attempt after shutdown has started.
                with self._lifecycle_lock:
                    if self._closing.is_set():
                        if last_unbilled_status:
                            self._stop_confirmed_unbilled(
                                handler,
                                request_id,
                                request_metadata,
                                last_unbilled_status,
                                "operator_confirmed_unbilled_proxy_closing",
                            )
                        else:
                            settlement = self._ledger.settle(
                                self._run_id,
                                request_id,
                                None,
                                pricing=pricing,
                                stop_reason="proxy_closing",
                            )
                            self._save_observation(
                                request_id,
                                request_metadata,
                                0,
                                settlement,
                            )
                            self._reject(handler, 503, "proxy_closing")
                        return
                    # Another handler may have held the lifecycle lock for an
                    # entire upstream header wait. Never start or persist a new
                    # attempt using the stale value computed before this lock.
                    remaining = deadline - self._monotonic()
                    if remaining <= 0:
                        if last_unbilled_status:
                            self._stop_confirmed_unbilled(
                                handler,
                                request_id,
                                request_metadata,
                                last_unbilled_status,
                                "operator_confirmed_unbilled_deadline_exhausted",
                            )
                        else:
                            settlement = self._ledger.settle(
                                self._run_id,
                                request_id,
                                None,
                                pricing=pricing,
                                stop_reason="upstream_deadline_exhausted",
                            )
                            self._save_observation(
                                request_id, request_metadata, 0, settlement
                            )
                            self._reject(handler, 502, "upstream_deadline_exhausted")
                        return
                    attempt_count = self._ledger.begin_attempt(
                        self._run_id,
                        request_id,
                        max_attempts=self._max_attempts,
                    )
                    upstream = self._transport.open(
                        self.upstream_endpoint,
                        body=body,
                        headers=headers,
                        timeout=remaining,
                    )
            except HTTPError as response:
                upstream = response
            except (OSError, URLError, TimeoutError, socket.timeout):
                settlement = self._ledger.settle(
                    self._run_id,
                    request_id,
                    None,
                    pricing=pricing,
                    stop_reason="upstream_unavailable",
                )
                self._save_observation(request_id, request_metadata, 0, settlement)
                self._reject(handler, 502, "upstream_unavailable")
                return
            except Exception:
                settlement = self._ledger.settle(
                    self._run_id,
                    request_id,
                    None,
                    pricing=pricing,
                    stop_reason="upstream_failure",
                )
                self._save_observation(request_id, request_metadata, 0, settlement)
                self._reject(handler, 502, "upstream_failure")
                return

            try:
                status = int(getattr(upstream, "status", getattr(upstream, "code", 502)))
            except (TypeError, ValueError):
                try:
                    upstream.close()
                except Exception:
                    pass
                settlement = self._ledger.settle(
                    self._run_id,
                    request_id,
                    None,
                    pricing=pricing,
                    stop_reason="unclassified_upstream_failure",
                )
                self._save_observation(request_id, request_metadata, 0, settlement)
                self._reject(handler, 502, "unclassified_upstream_failure")
                return
            if status not in self._unbilled_retry_statuses:
                self._relay(
                    handler,
                    upstream,
                    request_id,
                    request_metadata,
                    deadline=deadline,
                    stop_reason=None if 200 <= status <= 299 else "upstream_non_success",
                )
                return
            confirmed_unbilled = _is_operator_confirmed_unbilled(
                upstream,
                deadline=deadline,
                monotonic=self._monotonic,
            )
            try:
                upstream.close()
            except Exception:
                confirmed_unbilled = False
            if not confirmed_unbilled:
                settlement = self._ledger.settle(
                    self._run_id,
                    request_id,
                    None,
                    pricing=pricing,
                    stop_reason="unclassified_upstream_failure",
                )
                self._save_observation(request_id, request_metadata, status, settlement)
                self._reject(handler, 502, "unclassified_upstream_failure")
                return

            last_unbilled_status = status
            if attempt_count >= self._max_attempts:
                self._stop_confirmed_unbilled(
                    handler,
                    request_id,
                    request_metadata,
                    status,
                    "operator_confirmed_unbilled_attempts_exhausted",
                )
                return
            delay = self._retry_backoff_seconds * (2 ** (attempt_count - 1))
            remaining = deadline - self._monotonic()
            if delay >= remaining:
                self._stop_confirmed_unbilled(
                    handler,
                    request_id,
                    request_metadata,
                    status,
                    "operator_confirmed_unbilled_deadline_exhausted",
                )
                return
            if delay:
                self._sleep(delay)

    def _claim_and_reserve_logical_request(
        self, role: str, body_sha256: str, request_id: str
    ) -> None:
        """Persist the reservation before committing in-memory logical claims."""

        with self._request_policy_lock:
            run = self._ledger.snapshot()["runs"].get(self._run_id)
            if not isinstance(run, dict) or not isinstance(run.get("requests"), dict):
                raise ApiBudgetProxyError("budget run projection is invalid")
            if role == "main":
                in_flight = sum(
                    1
                    for main_request_id in self._main_request_ids
                    if isinstance(run["requests"].get(main_request_id), dict)
                    and run["requests"][main_request_id].get("status") == "reserved"
                )
                if in_flight >= self._max_concurrent_main:
                    raise ApiBudgetProxyError(
                        "concurrent main requests exceed the configured limit"
                    )
            if role == "guardian" and body_sha256 in self._guardian_body_sha256s:
                self._ledger.stop_run(
                    self._run_id,
                    stop_reason="guardian_duplicate_logical_request_rejected",
                )
                raise _GuardianDuplicateLogicalRequest(
                    "A settled Guardian request body cannot be replayed"
                )
            if (
                self._max_logical_requests is not None
                and self._logical_requests >= self._max_logical_requests
            ):
                self._ledger.stop_run(
                    self._run_id,
                    stop_reason="logical_request_limit_exceeded",
                )
                raise _LogicalRequestLimitExceeded(
                    "Short-test logical request limit is exhausted"
                )
            if (
                role == "guardian"
                and self._max_guardian_logical_requests is not None
                and self._guardian_logical_requests
                >= self._max_guardian_logical_requests
            ):
                self._ledger.stop_run(
                    self._run_id,
                    stop_reason="guardian_logical_request_limit_exceeded",
                )
                raise _GuardianLogicalRequestLimitExceeded(
                    "Guardian logical request limit is exhausted"
                )
            self._ledger.reserve(
                self._run_id,
                request_id,
                amount_usd=self._request_reservations[role],
                additional_capacity_usd=(
                    self._request_reservations["guardian"]
                    if role == "main"
                    and self._max_guardian_logical_requests != 0
                    and self._max_logical_requests != 1
                    else Decimal(0)
                ),
            )
            self._logical_requests += 1
            if role == "main":
                self._main_request_ids.add(request_id)
            else:
                self._guardian_logical_requests += 1
                self._guardian_body_sha256s.add(body_sha256)

    def _stop_confirmed_unbilled(
        self,
        handler: BaseHTTPRequestHandler,
        request_id: str,
        request_metadata: Mapping[str, Any],
        upstream_status: int,
        stop_reason: str,
    ) -> None:
        settlement = self._ledger.settle_operator_confirmed_unbilled(
            self._run_id,
            request_id,
            stop_reason=stop_reason,
        )
        self._save_observation(
            request_id,
            request_metadata,
            upstream_status,
            settlement,
        )
        self._reject(handler, 409, "unbilled_retry_exhausted")

    def _authenticate(self, handler: BaseHTTPRequestHandler) -> bool:
        values = handler.headers.get_all("Authorization", [])
        provided = values[0] if len(values) == 1 else ""
        expected = f"Bearer {self._downstream_api_key}"
        return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))

    def _reject_non_post(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._authenticate(handler):
            self._reject(handler, 401, "unauthorized")
            return
        self._reject(handler, 405, "method_not_allowed")

    def _relay(
        self,
        handler: BaseHTTPRequestHandler,
        upstream: Any,
        request_id: str,
        request_metadata: dict[str, Any],
        *,
        deadline: float,
        stop_reason: str | None,
    ) -> None:
        status = int(getattr(upstream, "status", getattr(upstream, "code", 502)))
        content_type = upstream.headers.get("Content-Type", "application/json")
        pricing = self._pricing_by_role[request_metadata["role"]]
        usage: Usage | None = None
        if content_type.lower().split(";", 1)[0].strip() == "text/event-stream":
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.close_connection = True
            collector = _SseUsageCollector()
            total = 0
            writable = True
            pending_event = bytearray()
            try:
                while True:
                    _enforce_upstream_deadline(
                        upstream,
                        deadline=deadline,
                        monotonic=self._monotonic,
                    )
                    remaining = _MAX_RESPONSE_BYTES - total
                    if remaining <= 0:
                        usage = None
                        request_metadata["stream_end_kind"] = "size_limit"
                        break
                    # BufferedResponse.read(8192) may wait for the buffer to fill
                    # on a keep-alive SSE connection.  Reading one bounded line at
                    # a time lets a complete terminal event settle immediately.
                    chunk = upstream.readline(min(8192, remaining + 1))
                    if not chunk:
                        collector.finish()
                        usage = collector.usage if collector.completed else None
                        request_metadata["stream_end_kind"] = (
                            "terminal" if collector.terminal_seen else "clean_eof"
                        )
                        if collector.terminal_seen:
                            request_metadata.update(collector.safe_terminal_metadata())
                            terminal_stop_reason = collector.stop_reason
                            settlement = self._ledger.settle(
                                self._run_id,
                                request_id,
                                usage,
                                pricing=pricing,
                                stop_reason=stop_reason or terminal_stop_reason,
                            )
                            self._save_observation(
                                request_id,
                                request_metadata,
                                status,
                                settlement,
                            )
                        if pending_event and writable:
                            try:
                                handler.wfile.write(pending_event)
                                handler.wfile.flush()
                            except (BrokenPipeError, ConnectionResetError):
                                writable = False
                        if collector.terminal_seen:
                            return
                        break
                    total += len(chunk)
                    if total > _MAX_RESPONSE_BYTES:
                        usage = None
                        request_metadata["stream_end_kind"] = "size_limit"
                        break
                    pending_event.extend(chunk)
                    collector.feed(chunk)
                    terminal_seen = collector.terminal_seen
                    if terminal_seen:
                        usage = collector.usage if collector.completed else None
                        request_metadata["stream_end_kind"] = "terminal"
                        request_metadata.update(collector.safe_terminal_metadata())
                        terminal_stop_reason = collector.stop_reason
                        # Release the conservative reservation before exposing
                        # response.completed to Codex.  Guardian review can start
                        # as soon as the downstream observes this line; writing it
                        # first creates a race where the still-reserved main request
                        # makes the Guardian request fail locally with HTTP 429.
                        settlement = self._ledger.settle(
                            self._run_id,
                            request_id,
                            usage,
                            pricing=pricing,
                            stop_reason=stop_reason or terminal_stop_reason,
                        )
                        self._save_observation(
                            request_id,
                            request_metadata,
                            status,
                            settlement,
                        )
                    # Hold one complete SSE event until it has been classified.
                    # This is the smallest buffer that prevents a terminal event
                    # from becoming visible before its reservation is released.
                    event_complete = chunk in {b"\n", b"\r\n"}
                    if event_complete and writable:
                        try:
                            handler.wfile.write(pending_event)
                            handler.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            writable = False
                    if event_complete:
                        pending_event.clear()
                    if terminal_seen:
                        return
            except (OSError, URLError, TimeoutError, socket.timeout):
                usage = None
                request_metadata["stream_end_kind"] = "read_error"
                stop_reason = "upstream_response_unavailable"
            finally:
                upstream.close()
            settlement = self._ledger.settle(
                self._run_id,
                request_id,
                usage,
                pricing=pricing,
                stop_reason=stop_reason,
            )
            self._save_observation(request_id, request_metadata, status, settlement)
        else:
            try:
                response_body, usage = _read_completed_json_response(
                    upstream,
                    deadline=deadline,
                    monotonic=self._monotonic,
                )
            except (OSError, URLError, TimeoutError, socket.timeout):
                upstream.close()
                settlement = self._ledger.settle(
                    self._run_id,
                    request_id,
                    None,
                    pricing=pricing,
                    stop_reason="upstream_response_unavailable",
                )
                self._save_observation(request_id, request_metadata, 0, settlement)
                self._reject(handler, 502, "upstream_response_unavailable")
                return
            upstream.close()
            settlement = self._ledger.settle(
                self._run_id,
                request_id,
                usage,
                pricing=pricing,
                stop_reason=stop_reason,
            )
            self._save_observation(request_id, request_metadata, status, settlement)
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(response_body)))
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.close_connection = True
            try:
                handler.wfile.write(response_body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _save_observation(
        self,
        request_id: str,
        request_metadata: Mapping[str, Any],
        status: int,
        settlement: Settlement,
    ) -> None:
        observation = dict(request_metadata)
        observation.update(
            {
                "request_id": request_id,
                "upstream_status": status,
                "usage_valid": settlement.usage_valid,
                "charged_usd": _money_text(settlement.charged_usd),
                "attempt_count": settlement.attempt_count,
                "settlement_kind": settlement.settlement_kind,
                "usage": (
                    {
                        "input_tokens": settlement.usage.input_tokens,
                        "cached_input_tokens": settlement.usage.cached_input_tokens,
                        "cache_write_input_tokens": (
                            settlement.usage.cache_write_input_tokens
                        ),
                        "output_tokens": settlement.usage.output_tokens,
                    }
                    if settlement.usage is not None
                    else None
                ),
            }
        )
        self._metadata.append(observation)

    @staticmethod
    def _reject(handler: BaseHTTPRequestHandler, status: int, code: str) -> None:
        body = json.dumps({"error": {"code": code}}, separators=(",", ":")).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        try:
            handler.wfile.write(body)
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def milestone_metadata_ready(metadata_path: Path) -> bool:
    """Return true only when every persisted request has a verified role."""

    try:
        value = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    requests = value.get("requests") if isinstance(value, dict) else None
    return bool(requests) and all(
        isinstance(item, dict)
        and isinstance(item.get("body_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", item["body_sha256"]) is not None
        and isinstance(item.get("canonical_body_sha256"), str)
        and re.fullmatch(r"[0-9a-f]{64}", item["canonical_body_sha256"])
        is not None
        and item.get("role") in {"main", "guardian"}
        and item.get("role_provenance") == "declared"
        and item.get("declared_role") == item.get("role")
        and item.get("inferred_role") == item.get("role")
        and item.get("contract_match") is True
        and item.get("usage_valid") is True
        and isinstance(item.get("usage"), dict)
        and item.get("settlement_kind") == _SETTLEMENT_USAGE_PRICED
        and isinstance(item.get("attempt_count"), int)
        and 1 <= item["attempt_count"] <= _MAX_UPSTREAM_ATTEMPTS
        for item in requests
    )


def _record_infra_taint(run: dict[str, Any], reason: str) -> None:
    """Mark that this run absorbed an upstream fault.

    Kept separate from `stopped` on purpose. Whether a run may *continue* is a
    spending decision; whether it may still be read as evidence about the
    product is not. Conflating them let a run absorb eight upstream terminal
    errors under the stop threshold and still be archived as a clean
    `agent_failed`, which is a verdict about the model that the run never
    earned.
    """

    taint = run.get("infra_taint")
    if isinstance(taint, dict):
        taint["count"] = int(taint["count"]) + 1
    else:
        run["infra_taint"] = {"count": 1, "first_reason": reason}


def infra_taint(snapshot: Mapping[str, Any], run_id: str) -> dict[str, Any] | None:
    """Return this run's upstream-fault record, or None if it saw none."""

    run = snapshot.get("runs", {}).get(run_id)
    if not isinstance(run, dict):
        return None
    taint = run.get("infra_taint")
    return dict(taint) if isinstance(taint, dict) else None


def exposure_summary(
    snapshot: Mapping[str, Any], run_id: str | None = None
) -> dict[str, object]:
    """Split what a ledger actually charged into priced spend and exposure.

    The ledger debits a reservation in full whenever usage is missing or
    invalid. That number is a deliberate over-estimate of the money the provider
    took, and reporting it as spend makes a batch look far more expensive than it
    was -- and can look like a budget stop that never happened. Priced spend is
    what the provider's own token counts justify; conservative exposure is what
    was debited without them. `charged_usd` remains the ledger's real debit and
    the only number the caps are enforced against.
    """

    runs = snapshot.get("runs")
    if not isinstance(runs, dict):
        raise ApiBudgetProxyError("budget snapshot has no runs")
    selected = runs if run_id is None else {run_id: runs.get(run_id)}
    priced = Decimal(0)
    conservative = Decimal(0)
    unbilled = 0
    charged = Decimal(0)
    counted = 0
    for run in selected.values():
        if not isinstance(run, dict):
            raise ApiBudgetProxyError("budget run projection is invalid")
        requests = run.get("requests")
        if not isinstance(requests, dict):
            raise ApiBudgetProxyError("budget run projection is invalid")
        for request in requests.values():
            if not isinstance(request, dict) or request.get("status") != "settled":
                continue
            counted += 1
            amount = _money(request.get("charged_usd") or "0")
            charged += amount
            kind = request.get("settlement_kind")
            if kind in {_SETTLEMENT_USAGE_PRICED, _SETTLEMENT_USAGE_PRICED_OVERAGE}:
                priced += amount
            elif kind == _SETTLEMENT_OPERATOR_CONFIRMED_UNBILLED:
                unbilled += 1
            else:
                conservative += amount
    return {
        "settled_requests": counted,
        "charged_usd": _money_text(charged),
        "priced_usd": _money_text(priced),
        "conservative_exposure_usd": _money_text(conservative),
        "operator_confirmed_unbilled_requests": unbilled,
    }


def completed_run_accounting(snapshot: Mapping[str, Any], run_id: str) -> dict[str, object]:
    """Validate and project the exact settled budget state required by completed."""

    _require_safe_id(run_id, "run id")
    if not isinstance(snapshot, Mapping):
        raise ApiBudgetProxyError("budget snapshot is invalid")
    runs = snapshot.get("runs")
    if not isinstance(runs, Mapping):
        raise ApiBudgetProxyError("budget snapshot has no runs")
    run = runs.get(run_id)
    if not isinstance(run, Mapping) or set(run) != {
        "cap_usd",
        "spent_usd",
        "stopped",
        "stop_reason",
        "requests",
    }:
        raise ApiBudgetProxyError("budget snapshot has no requested run")
    if run.get("stopped") is not False or run.get("stop_reason") is not None:
        raise ApiBudgetProxyError("completed budget run must not be stopped")
    requests = run.get("requests")
    if not isinstance(requests, Mapping) or not requests:
        raise ApiBudgetProxyError("completed budget run has no requests")
    cap = _money(run.get("cap_usd"))
    spent = _money(run.get("spent_usd"))
    if cap <= 0 or spent > cap:
        raise ApiBudgetProxyError("completed budget run exceeds its cap")
    settled_total = Decimal(0)
    for request_id, request in requests.items():
        _require_safe_id(request_id, "request id")
        if not isinstance(request, Mapping) or set(request) != {
            "status",
            "reserved_usd",
            "charged_usd",
            "usage_valid",
            "attempt_count",
            "settlement_kind",
        }:
            raise ApiBudgetProxyError("completed budget request differs from schema v1")
        attempt_count = request["attempt_count"]
        if (
            request["status"] != "settled"
            or request["usage_valid"] is not True
            or request["settlement_kind"] != _SETTLEMENT_USAGE_PRICED
            or isinstance(attempt_count, bool)
            or not isinstance(attempt_count, int)
            or not 1 <= attempt_count <= _MAX_UPSTREAM_ATTEMPTS
        ):
            raise ApiBudgetProxyError("completed budget request is not usage-settled")
        reserved = _money(request["reserved_usd"])
        charged = _money(request["charged_usd"])
        if reserved <= 0 or charged > reserved:
            raise ApiBudgetProxyError("completed budget request totals are invalid")
        settled_total += charged
    if settled_total != spent:
        raise ApiBudgetProxyError("completed budget run total is inconsistent")
    count = len(requests)
    return {
        "stopped": False,
        "stop_reason": None,
        "reserved_usd": _money_text(Decimal(0)),
        "spent_usd": _money_text(spent),
        "request_count": count,
        "settled_request_count": count,
        "usage_valid_request_count": count,
    }


def _validated_lite_header(headers: Any) -> bool:
    values = headers.get_all(_LITE_HEADER, [])
    if not values:
        return False
    if values != ["true"]:
        raise ApiBudgetProxyError("Lite routing header must be exactly true")
    return True


def _validated_user_agent(headers: Any) -> str:
    """Return one safe downstream User-Agent for the compatible upstream."""

    values = headers.get_all("User-Agent", [])
    if len(values) != 1 or not isinstance(values[0], str):
        raise ApiBudgetProxyError("exactly one User-Agent header is required")
    value = values[0]
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise ApiBudgetProxyError("User-Agent header is invalid") from exc
    if not encoded or len(encoded) > _MAX_USER_AGENT_BYTES:
        raise ApiBudgetProxyError("User-Agent header is invalid")
    if any(byte < 0x20 or byte > 0x7E for byte in encoded):
        raise ApiBudgetProxyError("User-Agent header is invalid")
    return value


def _validated_originator(headers: Any) -> str | None:
    """Forward one bounded printable Codex originator when it is present."""

    values = headers.get_all("originator", [])
    if not values:
        return None
    if len(values) != 1 or not isinstance(values[0], str):
        raise ApiBudgetProxyError("originator header is invalid")
    value = values[0]
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise ApiBudgetProxyError("originator header is invalid") from exc
    if not encoded or len(encoded) > _MAX_ORIGINATOR_BYTES:
        raise ApiBudgetProxyError("originator header is invalid")
    if any(byte < 0x20 or byte > 0x7E for byte in encoded):
        raise ApiBudgetProxyError("originator header is invalid")
    return value


def canonical_request_sha256(value: object) -> str:
    """Hash one JSON request using the repository's single canonical encoding."""

    if not isinstance(value, dict):
        raise ApiBudgetProxyError("canonical request must be a JSON object")
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ApiBudgetProxyError("canonical request is not valid JSON") from exc
    if len(encoded) > _MAX_RESPONSE_BYTES:
        raise ApiBudgetProxyError("canonical request is too large")
    return hashlib.sha256(encoded).hexdigest()


def canonical_guardian_request_sha256(value: object) -> str:
    """Hash the same normalized Guardian request that RONDO writes as E_final."""

    if not isinstance(value, dict):
        raise ApiBudgetProxyError("canonical Guardian request must be a JSON object")
    normalized = json.loads(json.dumps(value))
    for field in (
        "client_metadata",
        "prompt_cache_key",
        "store",
        "stream",
        "stream_options",
    ):
        normalized.pop(field, None)
    call_ids: dict[str, str] = {}
    turn_ids: dict[str, str] = {}
    input_items = normalized.get("input")
    if isinstance(input_items, list):
        for item in input_items:
            if not isinstance(item, dict):
                continue
            item.pop("id", None)
            item.pop("encrypted_function_args", None)
            _canonicalize_guardian_id(item, "call_id", "call", call_ids)
            metadata = item.get("internal_chat_message_metadata_passthrough")
            if isinstance(metadata, dict):
                _canonicalize_guardian_id(
                    metadata, "turn_id", "turn", turn_ids
                )
    return canonical_request_sha256(normalized)


def _canonicalize_guardian_id(
    value: dict[str, object],
    field: str,
    prefix: str,
    observed: dict[str, str],
) -> None:
    original = value.get(field)
    if not isinstance(original, str):
        return
    if original not in observed:
        observed[original] = f"{prefix}_{len(observed)}"
    value[field] = observed[original]


def _inspect_request(
    body: bytes,
    declared_role: str | None,
    *,
    main_model: str,
    main_effort: str,
    guardian_model: str,
    guardian_effort: str,
) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ApiBudgetProxyError("request body must be JSON") from exc
    if not isinstance(value, dict):
        raise ApiBudgetProxyError("request body must be a JSON object")
    model = value.get("model")
    stream = value.get("stream", False)
    if not isinstance(stream, bool):
        raise ApiBudgetProxyError("stream must be boolean")
    tools = value.get("tools", [])
    if not isinstance(tools, list):
        raise ApiBudgetProxyError("tools must be an array")
    tool_types: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("type"), str):
            raise ApiBudgetProxyError("tool declarations must have string types")
        tool_type = tool["type"]
        if tool_type in _HOSTED_TOOL_TYPES:
            raise ApiBudgetProxyError("hosted tools are disabled")
        tool_types.append(tool_type)
    reasoning = value.get("reasoning", {})
    if reasoning is None:
        reasoning = {}
    if not isinstance(reasoning, dict):
        raise ApiBudgetProxyError("reasoning must be an object")
    effort = reasoning.get("effort")
    if effort is not None and not isinstance(effort, str):
        raise ApiBudgetProxyError("reasoning effort must be a string")
    inferred_role = "guardian" if _has_guardian_output_schema(value) else "main"
    if declared_role in {"main", "guardian"}:
        if declared_role != inferred_role:
            raise ApiBudgetProxyError("declared request role conflicts with request shape")
        role = declared_role
        role_provenance = "declared"
    elif declared_role is None:
        role = inferred_role
        role_provenance = "inferred"
    else:
        raise ApiBudgetProxyError("declared request role is invalid")
    expected_model = main_model if role == "main" else guardian_model
    expected_effort = main_effort if role == "main" else guardian_effort
    contract_match = model == expected_model and effort == expected_effort
    if not contract_match:
        raise ApiBudgetProxyError("request model or reasoning effort differs from the frozen pair")
    input_value = value.get("input")
    if isinstance(input_value, list):
        input_kind = "array"
        input_items = len(input_value)
    elif isinstance(input_value, str):
        input_kind = "string"
        input_items = 1
    elif input_value is None:
        input_kind = "missing"
        input_items = 0
    else:
        input_kind = "other"
        input_items = 1
    return {
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "canonical_body_sha256": (
            canonical_guardian_request_sha256(value)
            if role == "guardian"
            else canonical_request_sha256(value)
        ),
        "role": role,
        "role_provenance": role_provenance,
        "declared_role": declared_role,
        "inferred_role": inferred_role,
        "model": model,
        "reasoning_effort": effort,
        "stream": stream,
        "shape": {
            "input_kind": input_kind,
            "input_items": input_items,
            "instructions_present": "instructions" in value,
            "tools_count": len(tools),
            "tool_types": sorted(tool_types),
            "previous_response_id_present": "previous_response_id" in value,
        },
        "contract_match": contract_match,
    }


def _has_guardian_output_schema(value: Mapping[str, Any]) -> bool:
    text = value.get("text")
    if not isinstance(text, dict):
        return False
    output_format = text.get("format")
    if not isinstance(output_format, dict):
        return False
    return output_format.get("schema") == GUARDIAN_OUTPUT_SCHEMA


def _usage_from_json_bytes(body: bytes) -> Usage | None:
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    usage = value.get("usage")
    if usage is None and isinstance(value.get("response"), dict):
        usage = value["response"].get("usage")
    try:
        return _parse_usage(usage)
    except ApiBudgetProxyError:
        return None


def _enforce_upstream_deadline(
    upstream: Any,
    *,
    deadline: float,
    monotonic: Any,
) -> None:
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("upstream absolute deadline exhausted")
    # urllib applies its timeout per socket operation.  Tighten the live socket
    # before every read so a trickling peer cannot restart the 90 second clock.
    candidates = [upstream, getattr(upstream, "fp", None)]
    candidates.append(getattr(candidates[-1], "fp", None))
    for candidate in candidates:
        raw = getattr(candidate, "raw", None)
        sock = getattr(raw, "_sock", None)
        if sock is not None and hasattr(sock, "settimeout"):
            sock.settimeout(remaining)
            break


def _contains_usage_or_terminal(value: object) -> bool:
    if isinstance(value, dict):
        if "usage" in value or "response" in value or "output" in value:
            return True
        if value.get("type") in {
            "response.completed",
            "response.failed",
            "response.incomplete",
        }:
            return True
        if value.get("status") in {"completed", "failed", "incomplete", "cancelled"}:
            return True
        if value.get("terminal") is True or value.get("completed") is True:
            return True
        return any(_contains_usage_or_terminal(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_usage_or_terminal(item) for item in value)
    return False


def _is_operator_confirmed_unbilled(
    upstream: Any,
    *,
    deadline: float,
    monotonic: Any,
) -> bool:
    """Recognize only a complete bounded canonical non-billing error envelope."""

    content_type = upstream.headers.get("Content-Type", "")
    if (
        not isinstance(content_type, str)
        or content_type.lower().split(";", 1)[0].strip() != "application/json"
    ):
        return False
    raw_length = upstream.headers.get("Content-Length")
    try:
        length = int(raw_length)
    except (TypeError, ValueError):
        return False
    if length <= 0 or length > _MAX_RESPONSE_BYTES:
        return False
    body = bytearray()
    try:
        while len(body) < length:
            _enforce_upstream_deadline(
                upstream,
                deadline=deadline,
                monotonic=monotonic,
            )
            chunk = upstream.read(min(8192, length - len(body)))
            if not chunk:
                return False
            body.extend(chunk)
    except Exception:
        return False
    try:
        value = json.loads(bytes(body))
    except (UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(value, dict)
        and set(value) == {"error"}
        and isinstance(value["error"], dict)
        and bool(value["error"])
        and not _contains_usage_or_terminal(value)
    )


def _read_completed_json_response(
    upstream: Any,
    *,
    deadline: float,
    monotonic: Any,
) -> tuple[bytes, Usage | None]:
    """Read one bounded JSON response without waiting for keep-alive EOF."""

    body = bytearray()
    read1 = getattr(upstream, "read1", None)
    while len(body) <= _MAX_RESPONSE_BYTES:
        _enforce_upstream_deadline(
            upstream,
            deadline=deadline,
            monotonic=monotonic,
        )
        remaining = _MAX_RESPONSE_BYTES + 1 - len(body)
        if remaining <= 0:
            break
        if callable(read1):
            chunk = read1(min(8192, remaining))
        else:
            # A one-byte fallback preserves the no-EOF contract for injected
            # transports that do not expose BufferedIOBase.read1().
            chunk = upstream.read(1)
        if not chunk:
            break
        body.extend(chunk)
        if len(body) > _MAX_RESPONSE_BYTES:
            break
        try:
            text = bytes(body).decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.reason == "unexpected end of data" and exc.end == len(body):
                continue
            break
        start = len(text) - len(text.lstrip())
        try:
            value, end = json.JSONDecoder().raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if text[end:].strip():
            break
        usage = None
        if isinstance(value, dict) and value.get("status") == "completed":
            usage = _usage_from_json_bytes(bytes(body))
        return bytes(body), usage
    return bytes(body), None


def _parse_usage(value: object) -> Usage:
    if not isinstance(value, dict):
        raise ApiBudgetProxyError("response usage is missing")
    details = value.get("input_tokens_details", {})
    if details is None:
        details = {}
    if not isinstance(details, dict):
        raise ApiBudgetProxyError("input token details are invalid")
    cached = details.get("cached_tokens", value.get("cached_input_tokens", 0))
    cache_write = details.get(
        "cache_write_tokens",
        value.get("cache_write_input_tokens", value.get("cache_creation_input_tokens", 0)),
    )
    usage = Usage(
        input_tokens=value.get("input_tokens"),
        cached_input_tokens=cached,
        cache_write_input_tokens=cache_write,
        output_tokens=value.get("output_tokens"),
    )
    usage.validate()
    return usage


class _SseUsageCollector:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self.usage: Usage | None = None
        self.terminal_seen = False
        self.completed = False
        self.terminal_event_type: str | None = None
        self.terminal_response_status: str | None = None
        self.terminal_error_code: str | None = None

    @property
    def stop_reason(self) -> str | None:
        return {
            "response.failed": "upstream_terminal_failed",
            "response.incomplete": "upstream_terminal_incomplete",
            "error": "upstream_terminal_error",
        }.get(self.terminal_event_type)

    def safe_terminal_metadata(self) -> dict[str, str]:
        result: dict[str, str] = {}
        if self.terminal_event_type is not None:
            result["terminal_event_type"] = self.terminal_event_type
        if self.terminal_response_status is not None:
            result["terminal_response_status"] = self.terminal_response_status
        if self.terminal_error_code is not None:
            result["terminal_error_code"] = self.terminal_error_code
        return result

    def feed(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)
        if len(self._buffer) > _MAX_RESPONSE_BYTES:
            self._buffer.clear()
            self.usage = None
            return
        normalized = bytes(self._buffer).replace(b"\r\n", b"\n")
        events = normalized.split(b"\n\n")
        self._buffer = bytearray(events.pop())
        for event in events:
            self._consume(event)

    def finish(self) -> None:
        if self._buffer:
            self._consume(bytes(self._buffer).replace(b"\r\n", b"\n"))
            self._buffer.clear()

    def _consume(self, event: bytes) -> None:
        event_names = [
            line[6:].strip()
            for line in event.splitlines()
            if line.startswith(b"event:")
        ]
        data = b"\n".join(
            line[5:].lstrip() for line in event.splitlines() if line.startswith(b"data:")
        )
        if not data or data == b"[DONE]":
            return
        try:
            value = json.loads(data)
        except (UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(value, dict):
            return
        event_type = value.get("type")
        if event_type not in {
            "response.completed",
            "response.failed",
            "response.incomplete",
            "error",
        }:
            return
        self.terminal_seen = True
        self.terminal_event_type = event_type
        response = value.get("response")
        if isinstance(response, dict):
            response_status = response.get("status")
            if response_status in {"completed", "failed", "incomplete", "cancelled"}:
                self.terminal_response_status = response_status
        error = value.get("error")
        if not isinstance(error, dict) and isinstance(response, dict):
            error = response.get("error")
        error_code = error.get("code") if isinstance(error, dict) else value.get("code")
        if isinstance(error_code, str) and re.fullmatch(
            r"[A-Za-z0-9._-]{1,128}", error_code
        ):
            self.terminal_error_code = error_code
        if event_type != "response.completed":
            return
        if event_names and event_names != [b"response.completed"]:
            return
        parsed = _usage_from_json_bytes(data)
        if parsed is not None:
            self.usage = parsed
            self.completed = True


def _compatible_responses_endpoint(base_url: str) -> str:
    if (
        not isinstance(base_url, str)
        or not base_url
        or base_url != base_url.strip()
        or any(ord(character) < 0x20 or character == "\\" for character in base_url)
    ):
        raise ApiBudgetProxyError("upstream base URL is invalid")
    try:
        parsed = urlsplit(base_url)
        parsed.port
    except ValueError as exc:
        raise ApiBudgetProxyError("upstream base URL is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ApiBudgetProxyError(
            "upstream must be a credential-free HTTPS OpenAI-compatible base URL"
        )
    return f"{base_url.rstrip('/')}/responses"


def _money(value: Decimal | str | int) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ApiBudgetProxyError("money value is invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise ApiBudgetProxyError("money value must be finite and non-negative")
    return amount.quantize(_MONEY_QUANTUM, rounding=ROUND_UP)


def _money_text(value: Decimal) -> str:
    return format(value.quantize(_MONEY_QUANTUM), "f")


def _unpriced_fallback(
    value: Decimal | str | None, *, default_run_cap: Decimal
) -> Decimal | None:
    if value is None:
        return None
    fallback = _money(value)
    if fallback <= 0 or fallback > default_run_cap:
        raise ApiBudgetProxyError("unpriced fallback is outside the run cap")
    return fallback


def _require_safe_id(value: object, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ApiBudgetProxyError(f"{label} is invalid")


def _reserved_total(run: Mapping[str, Any]) -> Decimal:
    return sum(
        (
            Decimal(request["reserved_usd"])
            for request in run["requests"].values()
            if request["status"] == "reserved"
        ),
        Decimal(0),
    )


def _validate_state(
    value: object,
    *,
    batch_id: str,
    total_cap: Decimal,
    max_runs: int,
    default_run_cap: Decimal,
    unpriced_fallback: Decimal | None,
    unpriced_fallback_per_attempt: bool = False,
) -> None:
    expected_keys = {
        "schema_version",
        "batch_id",
        "total_cap_usd",
        "max_runs",
        "default_run_cap_usd",
        "runs",
    }
    if unpriced_fallback is not None:
        expected_keys.add("unpriced_fallback_usd")
    if unpriced_fallback_per_attempt:
        expected_keys.add("unpriced_fallback_per_attempt")
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ApiBudgetProxyError("budget ledger differs from schema v1")
    if (
        value["schema_version"] != 1
        or value["batch_id"] != batch_id
        or value["total_cap_usd"] != _money_text(total_cap)
        or value["max_runs"] != max_runs
        or value["default_run_cap_usd"] != _money_text(default_run_cap)
        or not isinstance(value["runs"], dict)
        or len(value["runs"]) > max_runs
        or (
            unpriced_fallback is not None
            and value["unpriced_fallback_usd"] != _money_text(unpriced_fallback)
        )
        or (
            unpriced_fallback_per_attempt
            and value["unpriced_fallback_per_attempt"] is not True
        )
    ):
        raise ApiBudgetProxyError("budget ledger does not match the authorized batch")
    total_spent = Decimal(0)
    total_reserved = Decimal(0)
    total_priced_overage_delta = Decimal(0)
    for run_id, run in value["runs"].items():
        _require_safe_id(run_id, "run id")
        required_run_keys = {
            "cap_usd",
            "spent_usd",
            "stopped",
            "stop_reason",
            "requests",
        }
        # `infra_taint` is optional so ledgers written before it existed still
        # load unchanged. When present it records that this run absorbed an
        # upstream failure, which is what disqualifies it as product evidence.
        if not isinstance(run, dict) or not required_run_keys <= set(run) or set(
            run
        ) - required_run_keys - {"infra_taint"}:
            raise ApiBudgetProxyError("budget run state differs from schema v1")
        taint = run.get("infra_taint")
        if taint is not None and (
            not isinstance(taint, dict)
            or set(taint) != {"count", "first_reason"}
            or isinstance(taint["count"], bool)
            or not isinstance(taint["count"], int)
            or taint["count"] < 1
            or not isinstance(taint["first_reason"], str)
            or not taint["first_reason"]
        ):
            raise ApiBudgetProxyError("budget run infra taint is invalid")
        cap = _money(run["cap_usd"])
        spent = _money(run["spent_usd"])
        if cap <= 0 or cap > default_run_cap:
            raise ApiBudgetProxyError("budget run totals are invalid")
        if not isinstance(run["stopped"], bool) or not isinstance(run["requests"], dict):
            raise ApiBudgetProxyError("budget run state is invalid")
        if run["stop_reason"] is not None and run["stop_reason"] not in _STOP_REASONS:
            raise ApiBudgetProxyError("budget stop reason is invalid")
        if run["stopped"] != (run["stop_reason"] is not None):
            raise ApiBudgetProxyError("budget run stop state is inconsistent")
        settled_total = Decimal(0)
        run_priced_overage_delta = Decimal(0)
        for request_id, request in run["requests"].items():
            _require_safe_id(request_id, "request id")
            if not isinstance(request, dict) or set(request) != {
                "status",
                "reserved_usd",
                "charged_usd",
                "usage_valid",
                "attempt_count",
                "settlement_kind",
            }:
                raise ApiBudgetProxyError("budget request state differs from schema v1")
            reserved = _money(request["reserved_usd"])
            if reserved <= 0 or reserved > cap:
                raise ApiBudgetProxyError("budget reservation is invalid")
            attempt_count = request["attempt_count"]
            if (
                isinstance(attempt_count, bool)
                or not isinstance(attempt_count, int)
                or not 0 <= attempt_count <= _MAX_UPSTREAM_ATTEMPTS
            ):
                raise ApiBudgetProxyError("budget attempt count is invalid")
            if request["status"] == "reserved":
                if (
                    request["charged_usd"] is not None
                    or request["usage_valid"] is not None
                    or request["settlement_kind"] is not None
                ):
                    raise ApiBudgetProxyError("active budget reservation is invalid")
                total_reserved += reserved
            elif request["status"] == "settled":
                charged = _money(request["charged_usd"])
                settlement_kind = request["settlement_kind"]
                if (
                    not isinstance(request["usage_valid"], bool)
                    or settlement_kind not in _SETTLEMENT_KINDS
                ):
                    raise ApiBudgetProxyError("settled budget request is invalid")
                if settlement_kind != _SETTLEMENT_USAGE_PRICED_OVERAGE and charged > reserved:
                    raise ApiBudgetProxyError("settled budget request exceeds its reservation")
                if settlement_kind == _SETTLEMENT_USAGE_PRICED and (
                    request["usage_valid"] is not True or attempt_count < 1
                ):
                    raise ApiBudgetProxyError("priced budget settlement is invalid")
                if settlement_kind == _SETTLEMENT_USAGE_PRICED_OVERAGE:
                    if (
                        request["usage_valid"] is not True
                        or attempt_count < 1
                        or charged <= reserved
                        or run["stopped"] is not True
                        or run["stop_reason"] != "usage_cost_exceeded_reservation"
                    ):
                        raise ApiBudgetProxyError("priced overage settlement is invalid")
                    run_priced_overage_delta += charged - reserved
                if settlement_kind == _SETTLEMENT_OPERATOR_CONFIRMED_UNBILLED and (
                    request["usage_valid"] is not False
                    or charged != 0
                    or attempt_count < 1
                ):
                    raise ApiBudgetProxyError("unbilled budget settlement is invalid")
                if settlement_kind == _SETTLEMENT_NOT_SENT_UNBILLED and (
                    request["usage_valid"] is not False
                    or charged != 0
                    or attempt_count != 0
                ):
                    raise ApiBudgetProxyError("not-sent budget settlement is invalid")
                if settlement_kind == _SETTLEMENT_UNPRICED_FALLBACK and (
                    unpriced_fallback is None
                    or request["usage_valid"] is not False
                    or charged
                    != unpriced_fallback
                    * (attempt_count if unpriced_fallback_per_attempt else 1)
                    or attempt_count < 1
                ):
                    raise ApiBudgetProxyError("fallback budget settlement is invalid")
                if settlement_kind == _SETTLEMENT_CONSERVATIVE_RESERVATION and (
                    request["usage_valid"] is not False or charged != reserved
                ):
                    raise ApiBudgetProxyError("conservative budget settlement is invalid")
                settled_total += charged
            else:
                raise ApiBudgetProxyError("budget request status is invalid")
        if spent != settled_total:
            raise ApiBudgetProxyError("budget run total is inconsistent")
        run_reserved = _reserved_total(run)
        if run_priced_overage_delta and run_reserved:
            raise ApiBudgetProxyError("priced overage run retains a reservation")
        if spent + run_reserved > cap + run_priced_overage_delta:
            raise ApiBudgetProxyError("budget run exceeds its cap")
        total_priced_overage_delta += run_priced_overage_delta
        total_spent += spent
    if total_spent + total_reserved > total_cap + total_priced_overage_delta:
        raise ApiBudgetProxyError("budget ledger exceeds its batch cap")


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _atomic_private_json(path: Path, value: object) -> None:
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    except Exception:
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
