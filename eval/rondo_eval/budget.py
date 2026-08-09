"""Process-local batch budget ledger for explicitly authorized real API runs."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import Any


class BudgetError(ValueError):
    """Raised before a call when a batch would exceed its authorization."""


def _money(value: str | int | float | Decimal) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BudgetError("budget value is invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise BudgetError("budget value must be a finite non-negative amount")
    return amount


class BatchBudgetLedger:
    """Reserve then settle at most four calls under one 20 USD batch cap."""

    def __init__(self, *, batch_id: str, total_cap_usd: str = "20.00", max_runs: int = 4):
        if not batch_id or max_runs <= 0:
            raise BudgetError("batch id and a positive run limit are required")
        self.batch_id = batch_id
        self.total_cap = _money(total_cap_usd)
        if self.total_cap <= 0 or self.total_cap > Decimal("20.00"):
            raise BudgetError("batch cap exceeds the authorized 20 USD maximum")
        if max_runs > 4:
            raise BudgetError("batch run limit exceeds the authorized maximum of four")
        self.max_runs = max_runs
        self._active: dict[str, Decimal] = {}
        self._settled: dict[str, Decimal] = {}
        self._lock = Lock()

    def reserve(self, run_id: str, maximum_usd: str | int | float | Decimal) -> None:
        maximum = _money(maximum_usd)
        if not run_id or maximum <= 0:
            raise BudgetError("run id and a positive reservation are required")
        with self._lock:
            if run_id in self._active or run_id in self._settled:
                raise BudgetError("run id already consumed a batch slot")
            if len(self._active) + len(self._settled) >= self.max_runs:
                raise BudgetError("batch run limit is exhausted")
            committed = sum(self._active.values(), sum(self._settled.values(), Decimal(0)))
            if committed + maximum > self.total_cap:
                raise BudgetError("reservation would exceed the batch cost cap")
            self._active[run_id] = maximum

    def settle(self, run_id: str, actual_usd: str | int | float | Decimal) -> None:
        actual = _money(actual_usd)
        with self._lock:
            reserved = self._active.get(run_id)
            if reserved is None:
                raise BudgetError("run has no active reservation")
            if actual > reserved:
                raise BudgetError("actual cost exceeds the run reservation")
            del self._active[run_id]
            self._settled[run_id] = actual

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            spent = sum(self._settled.values(), Decimal(0))
            reserved = sum(self._active.values(), Decimal(0))
            return {
                "batch_id": self.batch_id,
                "total_cap_usd": str(self.total_cap),
                "max_runs": self.max_runs,
                "run_slots_used": len(self._active) + len(self._settled),
                "spent_usd": str(spent),
                "reserved_usd": str(reserved),
                "remaining_uncommitted_usd": str(self.total_cap - spent - reserved),
            }
