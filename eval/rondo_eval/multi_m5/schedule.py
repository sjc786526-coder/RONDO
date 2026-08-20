"""Gate 2 interleave, conditional reruns, and the three-observation rule."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from ..contracts import Product, RunOutcome, Side
from .load import NondegradationContract


@dataclass(frozen=True)
class Slot:
    task_id: str
    side: Side
    product: Product | None
    round_index: int
    kind: str


def base_slots(contract: NondegradationContract) -> tuple[Slot, ...]:
    slots: list[Slot] = []
    for item in contract.base_order:
        side = Side(item["side"])
        product_value = item["product"]
        slots.append(
            Slot(
                task_id=str(item["task_id"]),
                side=side,
                product=None if product_value is None else Product(product_value),
                round_index=1,
                kind="base",
            )
        )
    return tuple(slots)


def conditional_slots(
    contract: NondegradationContract,
    first_round: Mapping[str, Mapping[str, str]],
) -> tuple[Slot, ...]:
    """Return extra pairs only for Codex-complete / Multi-incomplete tasks.

    ``first_round`` maps task_id -> {"codex": outcome, "rondo-multi": outcome}
    using ``RunOutcome`` values. Infra failures must not appear here.
    """

    extra: list[Slot] = []
    for task_id in contract.tasks:
        pair = first_round.get(task_id, {})
        # Callers pass effective outcomes only. Any non-completed Multi result
        # matches the frozen trigger `codex_completed_multi_incomplete`.
        multi = pair.get(Product.RONDO_MULTI.value)
        if (
            pair.get(Side.CODEX.value) == RunOutcome.COMPLETED.value
            and multi is not None
            and multi != RunOutcome.COMPLETED.value
        ):
            for round_index in (2, 3):
                extra.append(
                    Slot(task_id, Side.CODEX, None, round_index, "conditional")
                )
                extra.append(
                    Slot(
                        task_id,
                        Side.RONDO,
                        Product.RONDO_MULTI,
                        round_index,
                        "conditional",
                    )
                )
    if len(base_slots(contract)) + len(extra) > contract.max_effective_runs:
        raise ValueError("conditional reruns exceed the frozen effective-run cap")
    return tuple(extra)


DIAGNOSTIC_ROUND_INDEX = 4
DIAGNOSTIC_SLOT_KIND = "diagnostic_v2_on_team_state_off"


def diagnostic_slots(
    contract: NondegradationContract,
    verdicts: Mapping[str, str],
) -> tuple[Slot, ...]:
    """Return one ``diagnostic_v2_on_team_state_off`` slot per degraded task.

    Derived from the finished verdicts, so the diagnostic can only exist after a
    task actually degraded -- the lock forbids pre-running it. Multi side only:
    the Codex arm of the comparison is unchanged and re-running it would answer
    nothing about attribution.

    The round index sits past every observation round so these rows can never be
    mistaken for a fourth observation of the frozen three.
    """

    slots = [
        Slot(
            task_id,
            Side.RONDO,
            Product.RONDO_MULTI,
            DIAGNOSTIC_ROUND_INDEX,
            DIAGNOSTIC_SLOT_KIND,
        )
        for task_id in contract.tasks
        if verdicts.get(task_id) == "stable_one_way_degradation"
    ]
    return tuple(slots)


def degradation_on_task(
    observations: Sequence[Mapping[str, str]],
) -> str:
    """Classify one task's effective Codex/Multi pairs.

    ``observations`` is up to three maps with keys ``codex`` and ``rondo-multi``.
    Returns ``stable_one_way_degradation``, ``no_stable_one_way_degradation``,
    or ``uncertain``.
    """

    if len(observations) not in {1, 3}:
        return "uncertain"
    if len(observations) == 1:
        pair = observations[0]
        if (
            pair.get(Side.CODEX.value) == RunOutcome.COMPLETED.value
            and pair.get(Product.RONDO_MULTI.value) != RunOutcome.COMPLETED.value
        ):
            return "uncertain"
        if not _both_present(pair):
            return "uncertain"
        return "no_stable_one_way_degradation"
    if not all(_both_present(pair) for pair in observations):
        return "uncertain"
    one_way = all(
        pair.get(Side.CODEX.value) == RunOutcome.COMPLETED.value
        and pair.get(Product.RONDO_MULTI.value) != RunOutcome.COMPLETED.value
        for pair in observations
    )
    return "stable_one_way_degradation" if one_way else "no_stable_one_way_degradation"


def _both_present(pair: Mapping[str, str]) -> bool:
    return Side.CODEX.value in pair and Product.RONDO_MULTI.value in pair


def outcomes_by_task(
    records: Iterable[Mapping[str, object]],
) -> dict[str, list[dict[str, str]]]:
    """Group effective completed/failed records into per-task observation pairs."""

    grouped: dict[str, dict[int, dict[str, str]]] = {}
    for record in records:
        if record.get("counts_as_effective") is not True:
            continue
        task_id = record.get("task_id")
        round_index = record.get("round_index")
        outcome = record.get("outcome")
        product = record.get("product")
        side = record.get("side")
        if not isinstance(task_id, str) or not isinstance(round_index, int):
            continue
        if not isinstance(outcome, str):
            continue
        key = Product.RONDO_MULTI.value if product == Product.RONDO_MULTI.value else (
            Side.CODEX.value if side == Side.CODEX.value else None
        )
        if key is None:
            continue
        grouped.setdefault(task_id, {}).setdefault(round_index, {})[key] = outcome
    return {
        task_id: [rounds[index] for index in sorted(rounds)]
        for task_id, rounds in grouped.items()
    }
