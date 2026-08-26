"""Materialize bounded Plan 087 route templates from a real model inventory."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import FullModelTrainingError
from .plan081_contract import ComparisonPolicy, ControlPlan, TrainableScope
from .plan087_adapter import validate_adaptive_recipe
from .plan087_contract import validate_route_context
from .plan087_run import RUN_SPEC_SCHEMA, validate_run_spec

ROUTE_CANDIDATE_SCHEMA = "rondo-publication-critic-plan087-route-candidate-v1"
SCOPE_STRATEGY_SCHEMA = "rondo-publication-critic-plan087-scope-strategy-v1"
_LAYER = re.compile(r"(?:^|\.)layers\.(\d+)\.")


def resolve_scope(
    parameter_inventory: Mapping[str, Any], strategy: Any
) -> dict[str, Any]:
    """Resolve score head, final norm and trailing blocks without fixed names."""

    _validate_scope_strategy(strategy)
    blocks = int(strategy["backbone_blocks"])
    rows = _inventory_rows(parameter_inventory)
    layer_numbers = sorted(
        {
            int(match.group(1))
            for row in rows
            if (match := _LAYER.search(row["name"])) is not None
        },
        reverse=True,
    )
    if len(layer_numbers) < blocks:
        raise FullModelTrainingError("plan087_scope_backbone_layers_missing")
    score = [row for row in rows if _is_score_head(row["name"])]
    if not score:
        raise FullModelTrainingError("plan087_scope_score_head_missing")
    final_norm = [row for row in rows if _is_final_norm(row["name"])]
    if strategy["include_final_norm"] and not final_norm:
        raise FullModelTrainingError("plan087_scope_final_norm_missing")
    selected: list[dict[str, Any]] = []
    selected.extend(score)
    if strategy["include_final_norm"]:
        selected.extend(final_norm)
    for layer in layer_numbers[:blocks]:
        selected.extend(
            row
            for row in rows
            if (match := _LAYER.search(row["name"])) is not None
            and int(match.group(1)) == layer
        )
    names = tuple(row["name"] for row in selected)
    if len(names) != len(set(names)):
        raise FullModelTrainingError("plan087_scope_parameter_duplicate")
    return TrainableScope(
        scope_id=f"score-head-terminal-{blocks}-blocks",
        parameter_names=names,
        trainable_parameter_elements=sum(int(row["elements"]) for row in selected),
        reason=(
            "adaptive terminal original-parameter scope with score head, "
            f"{blocks} trailing backbone block(s)"
        ),
    ).as_dict()


def materialize_run_spec(
    candidate: Any,
    *,
    route_context: Mapping[str, Any],
    parameter_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a tracked candidate to live names and the exact adaptive history."""

    value = validate_route_candidate(candidate)
    context = validate_route_context(route_context)
    if value["route_id"] != context["route_id"]:
        raise FullModelTrainingError("plan087_route_candidate_context_mismatch")
    phases = value["scope_phases"]
    scopes = [resolve_scope(parameter_inventory, row["strategy"]) for row in phases]
    initial = scopes[0]
    schedule = [
        {
            "after_observation_step": row["after_observation_step"],
            "scope": scope,
        }
        for row, scope in zip(phases[1:], scopes[1:], strict=True)
    ]
    return validate_run_spec(
        {
            "schema": RUN_SPEC_SCHEMA,
            "route_context": context,
            "recipe": value["recipe"],
            "initial_scope": initial,
            "scope_schedule": schedule,
            "control_plan": value["control_plan"],
            "comparison_policy": value["comparison_policy"],
            "report_threshold": value["report_threshold"],
        }
    )


def validate_route_candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "route_id",
        "description",
        "recipe",
        "scope_phases",
        "control_plan",
        "comparison_policy",
        "report_threshold",
    }:
        raise FullModelTrainingError("plan087_route_candidate_invalid")
    phases = value.get("scope_phases")
    if (
        value.get("schema") != ROUTE_CANDIDATE_SCHEMA
        or not isinstance(value.get("route_id"), str)
        or not value["route_id"]
        or not isinstance(value.get("description"), str)
        or not value["description"].strip()
        or not isinstance(phases, Sequence)
        or isinstance(phases, (str, bytes, bytearray))
        or not phases
    ):
        raise FullModelTrainingError("plan087_route_candidate_invalid")
    normalized_phases: list[dict[str, Any]] = []
    control = ControlPlan.from_value(value.get("control_plan"))
    ComparisonPolicy.from_value(value.get("comparison_policy"))
    recipe = validate_adaptive_recipe(value.get("recipe"))
    if (
        recipe["scheduler"]["name"] == "linear_warmup_decay"
        and recipe["scheduler"]["total_updates"] != control.maximum_updates
    ):
        raise FullModelTrainingError("plan087_scheduler_control_mismatch")
    threshold = value.get("report_threshold")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not 0.0 <= float(threshold) <= 1.0
    ):
        raise FullModelTrainingError("plan087_route_candidate_invalid")
    previous_blocks = 0
    previous_final_norm: bool | None = None
    for index, phase in enumerate(phases):
        if (
            not isinstance(phase, Mapping)
            or set(phase) != {"after_observation_step", "strategy"}
            or (index == 0 and phase.get("after_observation_step") is not None)
            or (
                index > 0
                and (
                    not isinstance(phase.get("after_observation_step"), int)
                    or isinstance(phase["after_observation_step"], bool)
                    or phase["after_observation_step"] < 1
                    or phase["after_observation_step"] not in control.observation_steps
                    or phase["after_observation_step"] >= control.maximum_updates
                )
            )
        ):
            raise FullModelTrainingError("plan087_route_candidate_invalid")
        strategy = phase.get("strategy")
        if not isinstance(strategy, Mapping):
            raise FullModelTrainingError("plan087_scope_strategy_invalid")
        blocks = strategy.get("backbone_blocks")
        if (
            not isinstance(blocks, int)
            or isinstance(blocks, bool)
            or blocks <= previous_blocks
        ):
            raise FullModelTrainingError("plan087_scope_strategy_not_expanding")
        _validate_scope_strategy(strategy)
        if (
            previous_final_norm is not None
            and strategy["include_final_norm"] != previous_final_norm
        ):
            raise FullModelTrainingError("plan087_scope_strategy_not_expanding")
        previous_blocks = blocks
        previous_final_norm = bool(strategy["include_final_norm"])
        normalized_phases.append(json.loads(json.dumps(phase)))
    if [row["after_observation_step"] for row in normalized_phases[1:]] != sorted(
        row["after_observation_step"] for row in normalized_phases[1:]
    ):
        raise FullModelTrainingError("plan087_route_candidate_invalid")
    return {**json.loads(json.dumps(value)), "scope_phases": normalized_phases}


def _validate_scope_strategy(strategy: Any) -> None:
    if not isinstance(strategy, Mapping) or set(strategy) != {
        "schema",
        "backbone_blocks",
        "include_score_head",
        "include_final_norm",
    }:
        raise FullModelTrainingError("plan087_scope_strategy_invalid")
    blocks = strategy.get("backbone_blocks")
    if (
        strategy.get("schema") != SCOPE_STRATEGY_SCHEMA
        or not isinstance(blocks, int)
        or isinstance(blocks, bool)
        or not 1 <= blocks <= 4
        or strategy.get("include_score_head") is not True
        or type(strategy.get("include_final_norm")) is not bool
    ):
        raise FullModelTrainingError("plan087_scope_strategy_invalid")


def _inventory_rows(value: Any) -> list[dict[str, Any]]:
    rows = value.get("parameters") if isinstance(value, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise FullModelTrainingError("plan087_parameter_inventory_invalid")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("name"), str)
            or not row["name"]
            or row["name"] in seen
            or not isinstance(row.get("elements"), int)
            or isinstance(row["elements"], bool)
            or row["elements"] <= 0
        ):
            raise FullModelTrainingError("plan087_parameter_inventory_invalid")
        seen.add(row["name"])
        normalized.append({"name": row["name"], "elements": row["elements"]})
    if not normalized:
        raise FullModelTrainingError("plan087_parameter_inventory_invalid")
    return normalized


def _is_score_head(name: str) -> bool:
    return name == "score" or name.startswith("score.") or ".score." in name


def _is_final_norm(name: str) -> bool:
    return bool(re.search(r"(?:^|\.)model\.norm(?:\.|$)", name))


__all__ = [
    "ROUTE_CANDIDATE_SCHEMA",
    "SCOPE_STRATEGY_SCHEMA",
    "materialize_run_spec",
    "resolve_scope",
    "validate_route_candidate",
]
