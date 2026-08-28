"""Small Decimal-based Plan 096 usage and conservative budget accounting."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any

from .contract import (
    BUDGET_CAP_RMB,
    CloudQualityError,
    PRICE_RATES_RMB_PER_MILLION,
    UNKNOWN_ATTEMPT_FALLBACK_RMB,
    require_count,
    require_decimal,
    validate_attempt,
)


MILLION = Decimal("1000000")


def decimal_text(value: Decimal) -> str:
    """Stable non-exponent JSON representation for a non-negative amount."""

    if not value.is_finite() or value < 0:
        raise CloudQualityError("cost_decimal_invalid")
    return format(value, "f")


def usage_cost_rmb(
    usage_value: Mapping[str, Any],
    *,
    rates: Mapping[str, Decimal] = PRICE_RATES_RMB_PER_MILLION,
) -> Decimal:
    """Price one provider usage record, charging unknown prompt tokens as misses."""

    usage = validate_attempt(
        {
            "attempt": 1,
            "outcome": "success",
            "usage": dict(usage_value),
            "failure_kind": None,
            "failure_code": None,
        }
    )["usage"]
    assert usage is not None
    prompt = require_count(usage["prompt_tokens"], "usage_prompt_tokens_invalid")
    completion = require_count(
        usage["completion_tokens"], "usage_completion_tokens_invalid"
    )
    hit_value = usage["cache_hit_tokens"]
    miss_value = usage["cache_miss_tokens"]
    if hit_value is None and miss_value is None:
        hit = 0
        miss = prompt
    else:
        hit = 0 if hit_value is None else require_count(hit_value, "usage_cache_hit_invalid")
        miss = (
            0
            if miss_value is None
            else require_count(miss_value, "usage_cache_miss_invalid")
        )
        if hit + miss > prompt:
            raise CloudQualityError("usage_cache_tokens_exceed_prompt")
        # Any prompt tokens the provider did not classify are conservatively misses.
        miss += prompt - hit - miss
    return (
        Decimal(hit) * rates["cache_hit_input"]
        + Decimal(miss) * rates["cache_miss_input"]
        + Decimal(completion) * rates["output"]
    ) / MILLION


def attempts_cost_rmb(attempts_value: Sequence[Mapping[str, Any]]) -> Decimal:
    """Charge usage-backed attempts by the card and unknown actual attempts at 1 RMB."""

    if not attempts_value:
        raise CloudQualityError("cost_attempts_empty")
    total = Decimal("0")
    for expected_index, value in enumerate(attempts_value, start=1):
        attempt = validate_attempt(value)
        if attempt["attempt"] != expected_index:
            raise CloudQualityError("cost_attempt_order_invalid")
        usage = attempt["usage"]
        total += (
            usage_cost_rmb(usage)
            if usage is not None
            else UNKNOWN_ATTEMPT_FALLBACK_RMB
        )
    return total


def scan_plan_cost_rmb(runs_root: Path) -> Decimal:
    """Sum immutable body-free call rows under the Plan 096 runs root."""

    if not runs_root.exists() and not runs_root.is_symlink():
        return Decimal("0")
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise CloudQualityError("cost_runs_root_unsafe")
    total = Decimal("0")
    for directory, names, files in os.walk(runs_root, followlinks=False):
        directory_path = Path(directory)
        safe_names: list[str] = []
        for name in names:
            child = directory_path / name
            if child.is_symlink():
                raise CloudQualityError("cost_runs_tree_unsafe")
            safe_names.append(name)
        names[:] = safe_names
        for name in files:
            if not name.startswith("call-") or not name.endswith(".json"):
                continue
            path = directory_path / name
            if path.is_symlink() or not path.is_file():
                raise CloudQualityError("cost_call_record_unsafe")
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CloudQualityError("cost_call_record_invalid") from exc
            if not isinstance(value, Mapping):
                raise CloudQualityError("cost_call_record_invalid")
            total += require_decimal(
                value.get("conservative_cost_rmb"), "cost_call_record_invalid"
            )
    return total


def require_next_logical_call_budget(
    runs_root: Path,
    *,
    max_attempts: int,
    cap_rmb: Decimal = BUDGET_CAP_RMB,
) -> Decimal:
    """Reserve the frozen worst-case fallback before starting another logical call."""

    if type(max_attempts) is not int or max_attempts <= 0:
        raise CloudQualityError("budget_max_attempts_invalid")
    accrued = scan_plan_cost_rmb(runs_root)
    reserve = Decimal(max_attempts) * UNKNOWN_ATTEMPT_FALLBACK_RMB
    if accrued + reserve > cap_rmb:
        raise CloudQualityError("budget_insufficient_for_next_logical_call")
    return cap_rmb - accrued
