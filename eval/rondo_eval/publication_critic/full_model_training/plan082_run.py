"""Typed run recipe and segmented controller driver for Plan 082."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from typing import Any

from .contract import FullModelTrainingError
from .plan081_contract import ComparisonPolicy, ControlPlan, TrainableScope
from .plan082_adapter import validate_recipe


RUN_SPEC_SCHEMA = "rondo-publication-critic-plan082-run-spec-v1"


def validate_run_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "recipe",
        "initial_scope",
        "scope_schedule",
        "control_plan",
        "comparison_policy",
        "report_threshold",
    }:
        raise FullModelTrainingError("plan082_run_spec_fields_invalid")
    recipe = validate_recipe(value.get("recipe"))
    initial = TrainableScope.from_value(value.get("initial_scope"))
    control = ControlPlan.from_value(value.get("control_plan"))
    comparison = ComparisonPolicy.from_value(value.get("comparison_policy"))
    schedule_value = value.get("scope_schedule")
    if (
        value.get("schema") != RUN_SPEC_SCHEMA
        or not isinstance(schedule_value, Sequence)
        or isinstance(schedule_value, (str, bytes, bytearray))
    ):
        raise FullModelTrainingError("plan082_run_spec_invalid")
    schedule: list[dict[str, Any]] = []
    previous = initial
    previous_step = 0
    for item in schedule_value:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"after_observation_step", "scope"}
            or not isinstance(item.get("after_observation_step"), int)
            or isinstance(item["after_observation_step"], bool)
        ):
            raise FullModelTrainingError("plan082_scope_schedule_invalid")
        step = item["after_observation_step"]
        scope = TrainableScope.from_value(item.get("scope"))
        if (
            step <= previous_step
            or step >= control.maximum_updates
            or step not in control.observation_steps
        ):
            raise FullModelTrainingError("plan082_scope_schedule_invalid")
        scope.require_expansion_of(previous)
        if scope.parameter_names[: len(previous.parameter_names)] != (
            previous.parameter_names
        ):
            raise FullModelTrainingError("plan082_scope_schedule_order_invalid")
        schedule.append({"after_observation_step": step, "scope": scope.as_dict()})
        previous = scope
        previous_step = step
    threshold = value.get("report_threshold")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not 0 <= float(threshold) <= 1
    ):
        raise FullModelTrainingError("plan082_run_spec_threshold_invalid")
    return {
        "schema": RUN_SPEC_SCHEMA,
        "recipe": recipe,
        "initial_scope": initial.as_dict(),
        "scope_schedule": schedule,
        "control_plan": control.as_dict(),
        "comparison_policy": comparison.as_dict(),
        "report_threshold": float(threshold),
    }


def frozen_scope_history(run_spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    value = validate_run_spec(run_spec)
    return [
        {"effective_before_update": 1, "scope": value["initial_scope"]},
        *[
            {
                "effective_before_update": item["after_observation_step"] + 1,
                "scope": item["scope"],
            }
            for item in value["scope_schedule"]
        ],
    ]


def run_scheduled(
    controller: Any,
    adapter: Any,
    run_spec: Mapping[str, Any],
    *,
    stop_after: int | None = None,
) -> dict[str, Any]:
    """Run to a bounded point, applying only the predeclared scope schedule."""

    value = validate_run_spec(run_spec)
    maximum = value["control_plan"]["maximum_updates"]
    target = maximum if stop_after is None else stop_after
    if (
        not isinstance(target, int)
        or isinstance(target, bool)
        or not 0 <= target <= maximum
    ):
        raise FullModelTrainingError("plan082_stop_after_invalid")
    current = int(controller.state["current_step"])
    if target < current:
        raise FullModelTrainingError("plan082_stop_after_invalid")
    decisions = {
        int(item["before_update"]): item for item in controller.state["scope_decisions"]
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
                decision = controller.schedule_scope_expansion(
                    TrainableScope.from_value(item["scope"])
                )
                decisions[before] = decision
            elif existing.get("scope") != item["scope"]:
                raise FullModelTrainingError("plan082_scope_schedule_drifted")
        if current >= target:
            return controller.archive_summary()
    if current < target:
        controller.run(adapter, stop_after=target)
    return controller.archive_summary()


def run_spec_objects(
    value: Mapping[str, Any],
) -> tuple[dict[str, Any], TrainableScope, ControlPlan, ComparisonPolicy, float]:
    validated = validate_run_spec(value)
    return (
        json.loads(json.dumps(validated["recipe"])),
        TrainableScope.from_value(validated["initial_scope"]),
        ControlPlan.from_value(validated["control_plan"]),
        ComparisonPolicy.from_value(validated["comparison_policy"]),
        float(validated["report_threshold"]),
    )
