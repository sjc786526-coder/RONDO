"""Typed adaptive route run specification for Plan 087."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import FullModelTrainingError
from .plan081_contract import ComparisonPolicy, ControlPlan, TrainableScope
from .plan087_adapter import validate_adaptive_recipe
from .plan087_contract import validate_route_context

RUN_SPEC_SCHEMA = "rondo-publication-critic-plan087-run-spec-v1"


def validate_run_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "route_context",
        "recipe",
        "initial_scope",
        "scope_schedule",
        "control_plan",
        "comparison_policy",
        "report_threshold",
    }:
        raise FullModelTrainingError("plan087_run_spec_invalid")
    if value.get("schema") != RUN_SPEC_SCHEMA:
        raise FullModelTrainingError("plan087_run_spec_invalid")
    route_context = validate_route_context(value.get("route_context"))
    recipe = validate_adaptive_recipe(value.get("recipe"))
    initial = TrainableScope.from_value(value.get("initial_scope"))
    control = ControlPlan.from_value(value.get("control_plan"))
    comparison = ComparisonPolicy.from_value(value.get("comparison_policy"))
    threshold = value.get("report_threshold")
    schedule = value.get("scope_schedule")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(float(threshold))
        or not 0.0 <= float(threshold) <= 1.0
        or not isinstance(schedule, Sequence)
        or isinstance(schedule, (str, bytes, bytearray))
    ):
        raise FullModelTrainingError("plan087_run_spec_invalid")
    previous = initial
    seen_steps: set[int] = set()
    normalized_schedule: list[dict[str, Any]] = []
    for row in schedule:
        if (
            not isinstance(row, Mapping)
            or set(row) != {"after_observation_step", "scope"}
            or not isinstance(row.get("after_observation_step"), int)
            or isinstance(row["after_observation_step"], bool)
            or row["after_observation_step"] not in control.observation_steps
            or row["after_observation_step"] >= control.maximum_updates
            or row["after_observation_step"] in seen_steps
        ):
            raise FullModelTrainingError("plan087_scope_schedule_invalid")
        scope = TrainableScope.from_value(row.get("scope"))
        scope.require_expansion_of(previous)
        if (
            scope.parameter_names[: len(previous.parameter_names)]
            != previous.parameter_names
        ):
            raise FullModelTrainingError("plan087_scope_schedule_order_invalid")
        seen_steps.add(row["after_observation_step"])
        previous = scope
        normalized_schedule.append(
            {
                "after_observation_step": row["after_observation_step"],
                "scope": scope.as_dict(),
            }
        )
    if [row["after_observation_step"] for row in normalized_schedule] != sorted(
        seen_steps
    ):
        raise FullModelTrainingError("plan087_scope_schedule_invalid")
    scheduler = recipe["scheduler"]
    if (
        scheduler["name"] == "linear_warmup_decay"
        and scheduler["total_updates"] != control.maximum_updates
    ):
        raise FullModelTrainingError("plan087_scheduler_control_mismatch")
    return {
        "schema": RUN_SPEC_SCHEMA,
        "route_context": route_context,
        "recipe": recipe,
        "initial_scope": initial.as_dict(),
        "scope_schedule": normalized_schedule,
        "control_plan": control.as_dict(),
        "comparison_policy": comparison.as_dict(),
        "report_threshold": float(threshold),
    }


def run_spec_objects(
    value: Any,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    TrainableScope,
    ControlPlan,
    ComparisonPolicy,
    float,
]:
    spec = validate_run_spec(value)
    return (
        json.loads(json.dumps(spec["route_context"])),
        json.loads(json.dumps(spec["recipe"])),
        TrainableScope.from_value(spec["initial_scope"]),
        ControlPlan.from_value(spec["control_plan"]),
        ComparisonPolicy.from_value(spec["comparison_policy"]),
        float(spec["report_threshold"]),
    )


def run_scheduled(
    controller: Any,
    adapter: Any,
    run_spec: Mapping[str, Any],
    *,
    stop_after: int | None = None,
) -> dict[str, Any]:
    """Run one route to a bounded point using its validated scope schedule."""

    value = validate_run_spec(run_spec)
    maximum = value["control_plan"]["maximum_updates"]
    target = maximum if stop_after is None else stop_after
    if (
        not isinstance(target, int)
        or isinstance(target, bool)
        or not 0 <= target <= maximum
    ):
        raise FullModelTrainingError("plan087_stop_after_invalid")
    current = int(controller.state["current_step"])
    if target < current:
        raise FullModelTrainingError("plan087_stop_after_invalid")
    decisions = {
        int(item["before_update"]): item
        for item in controller.state["scope_decisions"]
    }
    for item in value["scope_schedule"]:
        after = int(item["after_observation_step"])
        before = after + 1
        if current < after:
            controller.run(adapter, stop_after=min(after, target))
            current = int(controller.state["current_step"])
        if current == after and target > after:
            existing = decisions.get(before)
            if existing is None:
                decisions[before] = controller.schedule_scope_expansion(
                    TrainableScope.from_value(item["scope"])
                )
            elif existing.get("scope") != item["scope"]:
                raise FullModelTrainingError("plan087_scope_schedule_drifted")
        if current >= target:
            return controller.archive_summary()
    if current < target:
        controller.run(adapter, stop_after=target)
    return controller.archive_summary()


__all__ = [
    "RUN_SPEC_SCHEMA",
    "run_scheduled",
    "run_spec_objects",
    "validate_run_spec",
]
