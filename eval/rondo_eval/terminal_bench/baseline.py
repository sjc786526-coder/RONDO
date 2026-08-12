"""P2 B6 cost model and B7 canary-baseline aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Iterable

from ..contracts import Side
from .scoring import TaskOutcome


CAMPAIGN_CAP_USD = Decimal("200.000000")
CAMPAIGN_MAX_RUNS = 120
RUN_CAP_USD = Decimal("40.000000")
SOL_MAX_LEGAL_REQUEST_RESERVATION_USD = Decimal("18.885000")
BASE_ROUNDS = (
    "aa-rondo-1",
    "aa-rondo-2",
    "ab-rondo-1",
    "ab-codex-1",
)
MAX_SIGMA = 2


class BaselineError(ValueError):
    """Raised when a campaign record is partial or contradictory."""


class BaselineStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class BaselineRun:
    task_id: str
    round_id: str
    side: Side
    attempt: int
    outcome: TaskOutcome
    run_id: str


@dataclass(frozen=True)
class ConditionalRun:
    task_id: str
    side: Side
    repeat: int
    attempt: int
    outcome: TaskOutcome
    run_id: str


@dataclass(frozen=True)
class BaselineAssessment:
    status: BaselineStatus
    reasons: tuple[str, ...]
    sigma: int | None
    delta: int | None
    conditional_tasks: tuple[str, ...]
    effective_base_runs: tuple[BaselineRun, ...]
    effective_conditional_runs: tuple[ConditionalRun, ...]


def cost_forecast() -> dict[str, object]:
    """Return the frozen, recomputable B6 estimate without claiming a worst-case guarantee."""

    rondo_v19 = Decimal("0.456082")
    codex_v19 = Decimal("0.414705")
    wire_canary = Decimal("0.284300")
    base_point = 30 * rondo_v19 + 10 * codex_v19
    conditional_per_task = 2 * rondo_v19 + 2 * codex_v19
    full_point = base_point + 10 * conditional_per_task + wire_canary
    historical_40 = (Decimal("16.588200"), Decimal("18.243280"))
    historical_80 = (Decimal("33.176400"), Decimal("36.486560"))
    observed_shape_stress = Decimal("86.968700")
    return {
        "schema_version": 1,
        "currency": "USD",
        "actual_usd": None,
        "campaign_cap_usd": _money(CAMPAIGN_CAP_USD),
        "base_runs": 40,
        "maximum_conditional_runs": 40,
        "maximum_infra_replacement_runs": 40,
        "v19_rondo_run_usd": _money(rondo_v19),
        "v19_codex_run_usd": _money(codex_v19),
        "wire_canary_usd": _money(wire_canary),
        "base_point_estimate_usd": _money(base_point),
        "full_condition_point_estimate_usd": _money(full_point),
        "historical_40_run_range_usd": [_money(item) for item in historical_40],
        "historical_80_run_range_usd": [_money(item) for item in historical_80],
        "v19_shape_stress_with_canary_usd": _money(observed_shape_stress),
        "maximum_legal_request_reservation_usd": _money(
            SOL_MAX_LEGAL_REQUEST_RESERVATION_USD
        ),
        "feasible_from_observed_shape": observed_shape_stress < CAMPAIGN_CAP_USD,
        "mathematical_all_legal_usage_guarantee": False,
        "stop_rule": (
            "do not start a request unless its maximum legal reservation fits the "
            "remaining campaign budget"
        ),
    }


def assess_baseline(
    task_ids: tuple[str, ...],
    base_runs: tuple[BaselineRun, ...],
    conditional_runs: tuple[ConditionalRun, ...],
) -> BaselineAssessment:
    """Select bounded infra replacements and apply the frozen B7 gates."""

    if len(task_ids) != 10 or len(set(task_ids)) != 10:
        raise BaselineError("B7 requires ten unique canary tasks")
    expected_sides = {
        "aa-rondo-1": Side.RONDO,
        "aa-rondo-2": Side.RONDO,
        "ab-rondo-1": Side.RONDO,
        "ab-codex-1": Side.CODEX,
    }
    effective_base: list[BaselineRun] = []
    blocked: list[str] = []
    for round_id in BASE_ROUNDS:
        candidates = tuple(item for item in base_runs if item.round_id == round_id)
        selected = _select_round(
            task_ids,
            candidates,
            expected_side=expected_sides[round_id],
            label=round_id,
        )
        if selected is None:
            blocked.append(f"{round_id}_infra_replacement_exhausted")
        else:
            effective_base.extend(selected)
    if blocked:
        return BaselineAssessment(
            BaselineStatus.BLOCKED,
            tuple(blocked),
            None,
            None,
            (),
            tuple(effective_base),
            (),
        )

    by_round = {
        round_id: {item.task_id: item.outcome for item in effective_base if item.round_id == round_id}
        for round_id in BASE_ROUNDS
    }
    sigma = sum(
        by_round["aa-rondo-1"][task_id]
        is not by_round["aa-rondo-2"][task_id]
        for task_id in task_ids
    )
    delta = sum(
        by_round["ab-rondo-1"][task_id]
        is not by_round["ab-codex-1"][task_id]
        for task_id in task_ids
    )
    triggers = tuple(
        task_id
        for task_id in task_ids
        if by_round["ab-rondo-1"][task_id] is TaskOutcome.FAIL
        and by_round["ab-codex-1"][task_id] is TaskOutcome.PASS
    )
    effective_conditional: list[ConditionalRun] = []
    for task_id in triggers:
        for side in (Side.RONDO, Side.CODEX):
            for repeat in (1, 2):
                selected = _select_conditional(
                    task_id,
                    side,
                    repeat,
                    conditional_runs,
                )
                if selected is None:
                    blocked.append(
                        f"conditional_{side.value}_{repeat}_{task_id}_infra_replacement_exhausted"
                    )
                else:
                    effective_conditional.append(selected)
    if blocked:
        return BaselineAssessment(
            BaselineStatus.BLOCKED,
            tuple(blocked),
            sigma,
            delta,
            triggers,
            tuple(effective_base),
            tuple(effective_conditional),
        )

    reasons: list[str] = []
    if sigma > MAX_SIGMA:
        reasons.append("aa_sigma_exceeds_frozen_stability_limit")
    if delta > sigma:
        reasons.append("ab_delta_exceeds_aa_sigma")
    for task_id in triggers:
        rondo = [
            by_round["ab-rondo-1"][task_id],
            *(
                item.outcome
                for item in effective_conditional
                if item.task_id == task_id and item.side is Side.RONDO
            ),
        ]
        codex = [
            by_round["ab-codex-1"][task_id],
            *(
                item.outcome
                for item in effective_conditional
                if item.task_id == task_id and item.side is Side.CODEX
            ),
        ]
        if all(item is TaskOutcome.FAIL for item in rondo) and all(
            item is TaskOutcome.PASS for item in codex
        ):
            reasons.append(f"stable_directional_regression:{task_id}")
    status = BaselineStatus.FAILED if reasons else BaselineStatus.PASSED
    return BaselineAssessment(
        status,
        tuple(reasons),
        sigma,
        delta,
        triggers,
        tuple(effective_base),
        tuple(effective_conditional),
    )


def _select_round(
    task_ids: tuple[str, ...],
    values: tuple[BaselineRun, ...],
    *,
    expected_side: Side,
    label: str,
) -> tuple[BaselineRun, ...] | None:
    if any(
        item.side is not expected_side
        or item.attempt not in {1, 2}
        or item.task_id not in task_ids
        for item in values
    ):
        raise BaselineError(f"{label} contains an invalid run")
    _require_unique_runs(values)
    first = {item.task_id: item for item in values if item.attempt == 1}
    if set(first) != set(task_ids):
        raise BaselineError(f"{label} first attempt is incomplete")
    infra_ids = {task_id for task_id, item in first.items() if item.outcome is TaskOutcome.INFRA}
    second = {item.task_id: item for item in values if item.attempt == 2}
    expected_second = set(task_ids) if len(infra_ids) > 2 else infra_ids
    if set(second) != expected_second:
        raise BaselineError(f"{label} replacement set differs from the frozen rule")
    selected = second if len(infra_ids) > 2 else {**first, **second}
    if any(item.outcome is TaskOutcome.INFRA for item in selected.values()):
        return None
    return tuple(selected[task_id] for task_id in task_ids)


def _select_conditional(
    task_id: str,
    side: Side,
    repeat: int,
    values: tuple[ConditionalRun, ...],
) -> ConditionalRun | None:
    matches = tuple(
        item
        for item in values
        if item.task_id == task_id and item.side is side and item.repeat == repeat
    )
    if not matches or any(item.attempt not in {1, 2} for item in matches):
        raise BaselineError("conditional run is missing or invalid")
    _require_unique_runs(matches)
    by_attempt = {item.attempt: item for item in matches}
    first = by_attempt.get(1)
    if first is None:
        raise BaselineError("conditional first attempt is missing")
    if first.outcome is TaskOutcome.INFRA:
        second = by_attempt.get(2)
        if set(by_attempt) != {1, 2}:
            raise BaselineError("conditional infra replacement is incomplete")
        if second is None or second.outcome is TaskOutcome.INFRA:
            return None
        return second
    if set(by_attempt) != {1}:
        raise BaselineError("conditional replacement was activated without infra")
    return first


def _require_unique_runs(values: Iterable[BaselineRun | ConditionalRun]) -> None:
    run_ids = tuple(item.run_id for item in values)
    keys = tuple(
        (item.task_id, item.side, getattr(item, "round_id", None), getattr(item, "repeat", None), item.attempt)
        for item in values
    )
    if len(run_ids) != len(set(run_ids)) or len(keys) != len(set(keys)):
        raise BaselineError("campaign run identities are duplicated")


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")
