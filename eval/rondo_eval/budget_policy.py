"""Small runtime budget policy shared by cloud qualification controllers."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any


MAXIMUM_POLICY_BYTES = 4 * 1024
NORMAL_WORK_RESERVE_USD = 1.25
STOP_AND_RECOVER_RESERVE_USD = 0.75
DELETE_NOW_RESERVE_USD = 0.35


class BudgetPolicyError(RuntimeError):
    """A stable, body-free budget policy failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BudgetPolicy:
    """One loaded policy snapshot and its automatically derived cutoffs."""

    hard_cap_usd: float
    source_sha256: str

    @property
    def normal_work_cutoff_usd(self) -> float:
        return max(0.0, self.hard_cap_usd - NORMAL_WORK_RESERVE_USD)

    @property
    def stop_and_recover_cutoff_usd(self) -> float:
        return max(0.0, self.hard_cap_usd - STOP_AND_RECOVER_RESERVE_USD)

    @property
    def delete_now_cutoff_usd(self) -> float:
        return max(0.0, self.hard_cap_usd - DELETE_NOW_RESERVE_USD)

    def as_receipt(self) -> dict[str, Any]:
        return {
            "hard_cap_usd": self.hard_cap_usd,
            "normal_work_cutoff_usd": self.normal_work_cutoff_usd,
            "stop_and_recover_cutoff_usd": self.stop_and_recover_cutoff_usd,
            "delete_now_cutoff_usd": self.delete_now_cutoff_usd,
            "source_sha256": self.source_sha256,
        }


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise BudgetPolicyError("budget_policy_json_duplicate_key")
        value[key] = item
    return value


def load_budget_policy(path: Path) -> BudgetPolicy:
    """Load one regular JSON file whose only configurable field is the cap."""

    source = Path(path)
    try:
        info = os.lstat(source)
    except OSError as exc:
        raise BudgetPolicyError("budget_policy_missing") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise BudgetPolicyError("budget_policy_regular_file_required")
    if info.st_size <= 0 or info.st_size > MAXIMUM_POLICY_BYTES:
        raise BudgetPolicyError("budget_policy_size_invalid")
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise BudgetPolicyError("budget_policy_read_failed") from exc
    if len(raw) != info.st_size or len(raw) > MAXIMUM_POLICY_BYTES:
        raise BudgetPolicyError("budget_policy_changed_during_read")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BudgetPolicyError("budget_policy_json_invalid") from exc
    if not isinstance(value, dict) or set(value) != {"hard_cap_usd"}:
        raise BudgetPolicyError("budget_policy_shape_invalid")
    hard_cap = value.get("hard_cap_usd")
    if (
        not isinstance(hard_cap, (int, float))
        or isinstance(hard_cap, bool)
        or not math.isfinite(float(hard_cap))
        or float(hard_cap) <= 0
    ):
        raise BudgetPolicyError("budget_policy_hard_cap_invalid")
    return BudgetPolicy(
        hard_cap_usd=float(hard_cap),
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )
