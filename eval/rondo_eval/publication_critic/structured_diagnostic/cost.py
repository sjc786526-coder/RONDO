"""Plan 100 price-card settlement and durable logical-call reservations."""

import copy
import json
import os
import stat
import tempfile
import threading
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..identity import canonical_json_bytes, sha256_bytes

BUDGET_CAP_RMB = Decimal(20)
UNKNOWN_ACTUAL_ATTEMPT_RMB = Decimal("0.1")
MILLION = Decimal(1000000)
BEIJING = ZoneInfo("Asia/Shanghai")
PRICE_CARD = {
    "schema": "rondo-publication-critic-plan100-price-card@v1",
    "provider": "deepseek-official",
    "model": "deepseek-v4-flash",
    "currency": "RMB",
    "unit_tokens": 1_000_000,
    "source": "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/",
    "checked_date": "2026-08-30",
    "timezone": "Asia/Shanghai",
    "peak_windows": ["09:00-12:00", "14:00-18:00"],
    "peak_days": "monday_through_friday",
    "rates_rmb_per_million": {
        "off_peak": {
            "cache_hit_input": "0.05",
            "cache_miss_input": "1.5",
            "output": "4.5",
        },
        "peak": {
            "cache_hit_input": "0.10",
            "cache_miss_input": "3.0",
            "output": "9.0",
        },
    },
}
PRICE_CARD_SHA256 = sha256_bytes(canonical_json_bytes(PRICE_CARD))
LEDGER_SCHEMA = "rondo-publication-critic-plan100-budget-ledger@v1"

_MAX_LEDGER_BYTES = 2 * 1024 * 1024
_RESERVATION_FIELDS = {
    "logical_key",
    "state",
    "reserved_rmb",
    "attempts",
    "settled_rmb",
}


class DiagnosticCostError(RuntimeError):
    """A price, settlement, reservation, or ledger is invalid."""


class DiagnosticBudgetExceeded(DiagnosticCostError):
    """The next complete retry envelope cannot fit below 20 RMB."""


def decimal_text(value: Decimal) -> str:
    if not value.is_finite() or value < 0:
        raise DiagnosticCostError("cost_decimal_invalid")
    return format(value, "f")


def price_tier_at(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise DiagnosticCostError("attempt_time_invalid")
    local = value.astimezone(BEIJING)
    minute = local.hour * 60 + local.minute
    is_weekday = local.weekday() < 5
    is_peak_window = 540 <= minute < 720 or 840 <= minute < 1080
    return "peak" if is_weekday and is_peak_window else "off_peak"


def _count(value: Any, code: str) -> int:
    if type(value) is not int or value < 0:
        raise DiagnosticCostError(code)
    return value


def _rates(tier: str) -> dict[str, Decimal]:
    if tier not in {"peak", "off_peak"}:
        raise DiagnosticCostError("price_tier_invalid")
    return {
        name: Decimal(text)
        for name, text in PRICE_CARD["rates_rmb_per_million"][tier].items()
    }


def token_cost_rmb(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    cache_hit_tokens: int | None,
    cache_miss_tokens: int | None,
    tier: str,
) -> Decimal:
    """Price classified tokens; any unclassified input is charged as cache miss."""

    prompt = _count(prompt_tokens, "prompt_tokens_invalid")
    completion = _count(completion_tokens, "completion_tokens_invalid")
    if cache_hit_tokens is None and cache_miss_tokens is None:
        hit, miss = 0, prompt
    else:
        hit = (
            0
            if cache_hit_tokens is None
            else _count(cache_hit_tokens, "cache_hit_tokens_invalid")
        )
        miss = (
            0
            if cache_miss_tokens is None
            else _count(cache_miss_tokens, "cache_miss_tokens_invalid")
        )
        if hit + miss > prompt:
            raise DiagnosticCostError("cache_tokens_exceed_prompt")
        miss += prompt - hit - miss
    rates = _rates(tier)
    return (
        Decimal(hit) * rates["cache_hit_input"]
        + Decimal(miss) * rates["cache_miss_input"]
        + Decimal(completion) * rates["output"]
    ) / MILLION


def usage_cost_rmb(usage: Mapping[str, Any], *, tier: str) -> Decimal:
    if not isinstance(usage, Mapping):
        raise DiagnosticCostError("usage_invalid")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    hit = usage.get("prompt_cache_hit_tokens", usage.get("cache_hit_tokens"))
    miss = usage.get("prompt_cache_miss_tokens", usage.get("cache_miss_tokens"))
    return token_cost_rmb(
        prompt_tokens=prompt,
        completion_tokens=completion,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
        tier=tier,
    )


def settle_attempt(
    value: Mapping[str, Any],
    *,
    missing_usage_rmb: Decimal | None = None,
) -> dict[str, Any]:
    """Settle one actual attempt, using recount before the 0.1 RMB last resort."""

    if not isinstance(value, Mapping) or set(value) != {
        "attempt",
        "requested_at",
        "usage",
        "recount",
        "explicitly_unbilled",
    }:
        raise DiagnosticCostError("attempt_fields_invalid")
    attempt = _count(value["attempt"], "attempt_number_invalid")
    if attempt <= 0:
        raise DiagnosticCostError("attempt_number_invalid")
    try:
        requested_at = datetime.fromisoformat(
            str(value["requested_at"]).replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise DiagnosticCostError("attempt_time_invalid") from exc
    tier = price_tier_at(requested_at)
    usage = value["usage"]
    recount = value["recount"]
    explicitly_unbilled = value["explicitly_unbilled"]
    if type(explicitly_unbilled) is not bool:
        raise DiagnosticCostError("attempt_unbilled_invalid")
    if explicitly_unbilled:
        if usage is not None or recount is not None:
            raise DiagnosticCostError("attempt_unbilled_conflict")
        method = "provider_explicitly_unbilled"
        charge = Decimal(0)
        normalized_usage = None
        normalized_recount = None
    elif usage is not None:
        charge = usage_cost_rmb(usage, tier=tier)
        method = "provider_usage"
        normalized_usage = dict(usage)
        normalized_recount = None
    elif recount is not None:
        if not isinstance(recount, Mapping) or set(recount) != {
            "prompt_tokens",
            "completion_tokens",
            "method",
            "identity_sha256",
        }:
            raise DiagnosticCostError("attempt_recount_invalid")
        method_name = recount["method"]
        identity = recount["identity_sha256"]
        if (
            not isinstance(method_name, str)
            or not method_name
            or not isinstance(identity, str)
            or len(identity) != 64
            or any(character not in "0123456789abcdef" for character in identity)
        ):
            raise DiagnosticCostError("attempt_recount_invalid")
        charge = token_cost_rmb(
            prompt_tokens=recount["prompt_tokens"],
            completion_tokens=recount["completion_tokens"],
            cache_hit_tokens=None,
            cache_miss_tokens=None,
            tier=tier,
        )
        method = "recount_cache_miss_conservative"
        normalized_usage = None
        normalized_recount = dict(recount)
    else:
        if missing_usage_rmb is not None:
            if not missing_usage_rmb.is_finite() or missing_usage_rmb <= 0:
                raise DiagnosticCostError("missing_usage_rmb_invalid")
            charge = missing_usage_rmb
            method = "conservative_fixed_missing_usage"
        else:
            charge = UNKNOWN_ACTUAL_ATTEMPT_RMB
            method = "actual_attempt_unquantifiable_fallback"
        normalized_usage = None
        normalized_recount = None
    return {
        "attempt": attempt,
        "requested_at": requested_at.isoformat(),
        "price_tier": tier,
        "usage": normalized_usage,
        "recount": normalized_recount,
        "explicitly_unbilled": explicitly_unbilled,
        "settlement_method": method,
        "charge_rmb": decimal_text(charge),
    }


def worst_case_reservation_rmb(
    *,
    max_attempts: int,
    max_prompt_tokens: int,
    max_completion_tokens: int,
    missing_usage_rmb: Decimal | None = None,
) -> Decimal:
    attempts = _count(max_attempts, "reservation_attempts_invalid")
    if attempts <= 0:
        raise DiagnosticCostError("reservation_attempts_invalid")
    if missing_usage_rmb is not None and (
        not missing_usage_rmb.is_finite() or missing_usage_rmb <= 0
    ):
        raise DiagnosticCostError("missing_usage_rmb_invalid")
    token_envelope = token_cost_rmb(
        prompt_tokens=max_prompt_tokens,
        completion_tokens=max_completion_tokens,
        cache_hit_tokens=0,
        cache_miss_tokens=max_prompt_tokens,
        tier="peak",
    )
    floor = (
        UNKNOWN_ACTUAL_ATTEMPT_RMB
        if missing_usage_rmb is None
        else missing_usage_rmb
    )
    per_attempt = max(token_envelope, floor)
    return Decimal(attempts) * per_attempt


class Plan100BudgetLedger:
    """Small cross-process ledger: settled + outstanding + next reserve never exceed cap."""

    def __init__(
        self,
        path: Path,
        *,
        cap_rmb: Decimal = BUDGET_CAP_RMB,
        must_exist: bool = False,
        read_only: bool = False,
        missing_usage_rmb: Decimal | None = None,
    ) -> None:
        if not path.is_absolute():
            raise DiagnosticCostError("ledger_path_must_be_absolute")
        if not cap_rmb.is_finite() or cap_rmb <= 0 or cap_rmb > BUDGET_CAP_RMB:
            raise DiagnosticCostError("ledger_cap_invalid")
        if read_only and not must_exist:
            raise DiagnosticCostError("read_only_ledger_must_exist")
        self.path = path
        self.cap_rmb = cap_rmb
        self.must_exist = must_exist
        self.read_only = read_only
        if missing_usage_rmb is not None and (
            not missing_usage_rmb.is_finite() or missing_usage_rmb <= 0
        ):
            raise DiagnosticCostError("missing_usage_rmb_invalid")
        self.missing_usage_rmb = missing_usage_rmb
        self._thread_lock = threading.Lock()
        self._lock_path = path.with_name(f".{path.name}.lock")
        if must_exist:
            if self.path.parent.is_symlink() or not self.path.parent.is_dir():
                raise DiagnosticCostError("ledger_parent_unsafe")
        else:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or not self.path.parent.is_dir():
            raise DiagnosticCostError("ledger_parent_unsafe")
        if read_only:
            self._read_existing()
        else:
            with self._locked_document():
                pass

    def reserve(self, logical_key: str, amount: Decimal) -> dict[str, Any]:
        if self.read_only:
            raise DiagnosticCostError("ledger_is_read_only")
        if (
            not isinstance(logical_key, str)
            or not logical_key
            or len(logical_key) > 256
        ):
            raise DiagnosticCostError("logical_key_invalid")
        if not amount.is_finite() or amount <= 0:
            raise DiagnosticCostError("reservation_amount_invalid")
        with self._locked_document() as document:
            if any(
                row["logical_key"] == logical_key for row in document["reservations"]
            ):
                raise DiagnosticCostError("logical_key_already_reserved")
            charged, outstanding = _totals(document["reservations"])
            if charged + outstanding + amount > self.cap_rmb:
                raise DiagnosticBudgetExceeded("budget_insufficient_for_next_action")
            row = {
                "logical_key": logical_key,
                "state": "reserved",
                "reserved_rmb": decimal_text(amount),
                "attempts": [],
                "settled_rmb": None,
            }
            updated = {**document, "reservations": [*document["reservations"], row]}
            self._persist(updated)
            return copy.deepcopy(row)

    def top_up_reservation(self, logical_key: str, amount: Decimal) -> dict[str, Any]:
        if self.read_only:
            raise DiagnosticCostError("ledger_is_read_only")
        if not amount.is_finite() or amount <= 0:
            raise DiagnosticCostError("reservation_amount_invalid")
        with self._locked_document() as document:
            matches = [
                row
                for row in document["reservations"]
                if row["logical_key"] == logical_key
            ]
            if len(matches) != 1 or matches[0]["state"] != "reserved":
                raise DiagnosticCostError("reservation_not_open")
            row = matches[0]
            current = Decimal(row["reserved_rmb"])
            if amount < current:
                raise DiagnosticCostError("reservation_top_up_must_not_decrease")
            if amount == current:
                return copy.deepcopy(row)
            charged, outstanding = _totals(document["reservations"])
            if charged + outstanding + (amount - current) > self.cap_rmb:
                raise DiagnosticBudgetExceeded("budget_insufficient_for_next_action")
            row["reserved_rmb"] = decimal_text(amount)
            self._persist(document)
            return copy.deepcopy(row)

    def settle(
        self, logical_key: str, attempts_value: Sequence[Mapping[str, Any]]
    ) -> dict[str, Any]:
        if self.read_only:
            raise DiagnosticCostError("ledger_is_read_only")
        if not attempts_value:
            raise DiagnosticCostError("settlement_attempts_empty")
        attempts = [
            settle_attempt(value, missing_usage_rmb=self.missing_usage_rmb)
            for value in attempts_value
        ]
        if [row["attempt"] for row in attempts] != list(range(1, len(attempts) + 1)):
            raise DiagnosticCostError("settlement_attempt_order_invalid")
        settled = sum((Decimal(row["charge_rmb"]) for row in attempts), Decimal(0))
        with self._locked_document() as document:
            reservations = copy.deepcopy(document["reservations"])
            matches = [row for row in reservations if row["logical_key"] == logical_key]
            if len(matches) != 1 or matches[0]["state"] != "reserved":
                raise DiagnosticCostError("reservation_not_open")
            row = matches[0]
            if settled > Decimal(row["reserved_rmb"]):
                raise DiagnosticCostError("settlement_exceeds_reservation")
            row.update(
                state="settled",
                attempts=attempts,
                settled_rmb=decimal_text(settled),
            )
            updated = {**document, "reservations": reservations}
            self._persist(updated)
            return copy.deepcopy(row)

    def snapshot(self) -> dict[str, Any]:
        if self.read_only:
            document = self._read_existing()
            reservations = copy.deepcopy(document["reservations"])
            settled, outstanding = _totals(reservations)
        else:
            with self._locked_document() as document:
                reservations = copy.deepcopy(document["reservations"])
                settled, outstanding = _totals(reservations)
        return {
            **document,
            "reservations": reservations,
            "settled_rmb": decimal_text(settled),
            "outstanding_reserved_rmb": decimal_text(outstanding),
            "remaining_unreserved_rmb": decimal_text(
                self.cap_rmb - settled - outstanding
            ),
        }

    @contextmanager
    def _locked_document(self):
        if self.read_only:
            raise DiagnosticCostError("ledger_is_read_only")
        with self._thread_lock:
            flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(self._lock_path, flags, 0o600)
            except OSError as exc:
                raise DiagnosticCostError("ledger_lock_unsafe") from exc
            try:
                metadata = os.fstat(descriptor)
                if not stat.S_ISREG(metadata.st_mode):
                    raise DiagnosticCostError("ledger_lock_unsafe")
                os.fchmod(descriptor, 0o600)
                try:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                except (ImportError, OSError) as exc:
                    raise DiagnosticCostError("ledger_lock_failed") from exc
                try:
                    yield self._load_or_create()
                finally:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _load_or_create(self) -> dict[str, Any]:
        if self.path.exists() or self.path.is_symlink():
            return self._read_existing()
        if self.must_exist:
            raise DiagnosticCostError("ledger_file_missing")
        document = {
            "schema": LEDGER_SCHEMA,
            "cap_rmb": decimal_text(self.cap_rmb),
            "price_card_sha256": PRICE_CARD_SHA256,
            "reservations": [],
        }
        self._persist(document)
        return document

    def _read_existing(self) -> dict[str, Any]:
        if not self.path.exists() and not self.path.is_symlink():
            raise DiagnosticCostError("ledger_file_missing")
        metadata = self.path.lstat()
        if (
            self.path.is_symlink()
            or not self.path.is_file()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 0 < metadata.st_size <= _MAX_LEDGER_BYTES
        ):
            raise DiagnosticCostError("ledger_file_unsafe")
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DiagnosticCostError("ledger_file_invalid") from exc
        _validate_document(
            document, self.cap_rmb, missing_usage_rmb=self.missing_usage_rmb
        )
        return dict(document)

    def _persist(self, document: dict[str, Any]) -> None:
        _validate_document(
            document, self.cap_rmb, missing_usage_rmb=self.missing_usage_rmb
        )
        encoded = canonical_json_bytes(document)
        if len(encoded) > _MAX_LEDGER_BYTES:
            raise DiagnosticCostError("ledger_file_too_large")
        descriptor, name = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
        )
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)


def validate_task_budget_snapshot(value: Any) -> dict[str, Any]:
    """Validate the fixed-cap task-wide snapshot embedded in diagnostic results."""

    expected = {
        "schema",
        "cap_rmb",
        "price_card_sha256",
        "reservations",
        "settled_rmb",
        "outstanding_reserved_rmb",
        "remaining_unreserved_rmb",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise DiagnosticCostError("ledger_snapshot_invalid")
    document = {
        name: value[name]
        for name in ("schema", "cap_rmb", "price_card_sha256", "reservations")
    }
    _validate_document(
        document, BUDGET_CAP_RMB, missing_usage_rmb=None
    )
    settled, outstanding = _totals(document["reservations"])
    if (
        value["settled_rmb"] != decimal_text(settled)
        or value["outstanding_reserved_rmb"] != decimal_text(outstanding)
        or value["remaining_unreserved_rmb"]
        != decimal_text(BUDGET_CAP_RMB - settled - outstanding)
    ):
        raise DiagnosticCostError("ledger_snapshot_totals_invalid")
    return copy.deepcopy(dict(value))


def validate_task_budget_extension(current: Any, required: Any) -> dict[str, Any]:
    """Require the live task ledger to preserve every settled B1 reservation exactly."""

    current_snapshot = validate_task_budget_snapshot(current)
    required_snapshot = validate_task_budget_snapshot(required)
    if required_snapshot["outstanding_reserved_rmb"] != "0":
        raise DiagnosticCostError("required_ledger_has_outstanding_reservation")
    current_by_key = {
        row["logical_key"]: row for row in current_snapshot["reservations"]
    }
    for row in required_snapshot["reservations"]:
        if row["state"] != "settled" or current_by_key.get(row["logical_key"]) != row:
            raise DiagnosticCostError("task_ledger_does_not_preserve_commissioning")
    return current_snapshot


def task_budget_summary(value: Any) -> dict[str, Any]:
    """Return body-free task totals covering commissioning, retries, and formal runs."""

    snapshot = validate_task_budget_snapshot(value)
    methods: dict[str, int] = {}
    provider_prompt = provider_completion = 0
    recounted_prompt = recounted_completion = 0
    http_attempts = 0
    settled_calls = outstanding_calls = 0
    for reservation in snapshot["reservations"]:
        if reservation["state"] == "reserved":
            outstanding_calls += 1
            continue
        settled_calls += 1
        for attempt in reservation["attempts"]:
            http_attempts += 1
            method = attempt["settlement_method"]
            methods[method] = methods.get(method, 0) + 1
            usage = attempt["usage"]
            recount = attempt["recount"]
            if usage is not None:
                provider_prompt += usage["prompt_tokens"]
                provider_completion += usage["completion_tokens"]
            if recount is not None:
                recounted_prompt += recount["prompt_tokens"]
                recounted_completion += recount["completion_tokens"]
    return {
        "schema": snapshot["schema"],
        "cap_rmb": snapshot["cap_rmb"],
        "price_card_sha256": snapshot["price_card_sha256"],
        "settled_rmb": snapshot["settled_rmb"],
        "outstanding_reserved_rmb": snapshot["outstanding_reserved_rmb"],
        "remaining_unreserved_rmb": snapshot["remaining_unreserved_rmb"],
        "settled_logical_call_count": settled_calls,
        "outstanding_logical_call_count": outstanding_calls,
        "http_attempt_count": http_attempts,
        "provider_prompt_tokens_reported": provider_prompt,
        "provider_completion_tokens_reported": provider_completion,
        "recounted_prompt_tokens": recounted_prompt,
        "recounted_completion_tokens": recounted_completion,
        "settlement_methods": dict(sorted(methods.items())),
    }


def _stored_decimal(value: Any, code: str) -> Decimal:
    if isinstance(value, bool):
        raise DiagnosticCostError(code)
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DiagnosticCostError(code) from exc
    if not result.is_finite() or result < 0:
        raise DiagnosticCostError(code)
    return result


def _validate_document(
    document: Any,
    cap: Decimal,
    *,
    missing_usage_rmb: Decimal | None = None,
) -> None:
    if (
        not isinstance(document, Mapping)
        or set(document) != {"schema", "cap_rmb", "price_card_sha256", "reservations"}
        or document.get("schema") != LEDGER_SCHEMA
        or document.get("cap_rmb") != decimal_text(cap)
        or document.get("price_card_sha256") != PRICE_CARD_SHA256
        or not isinstance(document.get("reservations"), list)
    ):
        raise DiagnosticCostError("ledger_schema_invalid")
    keys: set[str] = set()
    for row in document["reservations"]:
        if not isinstance(row, Mapping) or set(row) != _RESERVATION_FIELDS:
            raise DiagnosticCostError("ledger_reservation_invalid")
        key = row["logical_key"]
        if not isinstance(key, str) or not key or key in keys or len(key) > 256:
            raise DiagnosticCostError("ledger_reservation_invalid")
        keys.add(key)
        reserved = _stored_decimal(row["reserved_rmb"], "ledger_reservation_invalid")
        if reserved <= 0 or row["state"] not in {"reserved", "settled"}:
            raise DiagnosticCostError("ledger_reservation_invalid")
        if row["state"] == "reserved":
            if row["attempts"] != [] or row["settled_rmb"] is not None:
                raise DiagnosticCostError("ledger_reservation_invalid")
        else:
            attempts = row["attempts"]
            if not isinstance(attempts, list) or not attempts:
                raise DiagnosticCostError("ledger_reservation_invalid")
            normalized_attempts = [
                _validate_settled_attempt(
                    item, index, missing_usage_rmb=missing_usage_rmb
                )
                for index, item in enumerate(attempts, start=1)
            ]
            settled = _stored_decimal(row["settled_rmb"], "ledger_reservation_invalid")
            if (
                settled > reserved
                or sum(
                    (
                        _stored_decimal(item["charge_rmb"], "ledger_attempt_invalid")
                        for item in normalized_attempts
                    ),
                    Decimal(0),
                )
                != settled
            ):
                raise DiagnosticCostError("ledger_reservation_invalid")
    settled, outstanding = _totals(document["reservations"])
    if settled + outstanding > cap:
        raise DiagnosticCostError("ledger_cap_exceeded")


def _totals(reservations: Sequence[Mapping[str, Any]]) -> tuple[Decimal, Decimal]:
    settled = sum(
        (
            Decimal(row["settled_rmb"])
            for row in reservations
            if row["state"] == "settled"
        ),
        Decimal(0),
    )
    outstanding = sum(
        (
            Decimal(row["reserved_rmb"])
            for row in reservations
            if row["state"] == "reserved"
        ),
        Decimal(0),
    )
    return settled, outstanding


def _validate_settled_attempt(
    value: Any,
    expected_attempt: int,
    *,
    missing_usage_rmb: Decimal | None = None,
) -> dict[str, Any]:
    expected_fields = {
        "attempt",
        "requested_at",
        "price_tier",
        "usage",
        "recount",
        "explicitly_unbilled",
        "settlement_method",
        "charge_rmb",
    }
    if not isinstance(value, Mapping) or set(value) != expected_fields:
        raise DiagnosticCostError("ledger_attempt_invalid")
    recalculated = settle_attempt(
        {
            "attempt": value["attempt"],
            "requested_at": value["requested_at"],
            "usage": value["usage"],
            "recount": value["recount"],
            "explicitly_unbilled": value["explicitly_unbilled"],
        },
        missing_usage_rmb=missing_usage_rmb,
    )
    if recalculated != dict(value) or recalculated["attempt"] != expected_attempt:
        raise DiagnosticCostError("ledger_attempt_invalid")
    return recalculated


__all__ = [
    "BUDGET_CAP_RMB",
    "PRICE_CARD",
    "PRICE_CARD_SHA256",
    "DiagnosticBudgetExceeded",
    "DiagnosticCostError",
    "Plan100BudgetLedger",
    "decimal_text",
    "price_tier_at",
    "settle_attempt",
    "token_cost_rmb",
    "usage_cost_rmb",
    "validate_task_budget_extension",
    "validate_task_budget_snapshot",
    "worst_case_reservation_rmb",
]
