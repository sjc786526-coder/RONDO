"""Materialize bounded Plan 087 route templates from a real model inventory."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import FullModelTrainingError, canonical_json_bytes, sha256_bytes
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
    """Resolve one bounded strategy against the exact parameter inventory."""

    kind = _validate_scope_strategy(strategy)
    rows = _inventory_rows(parameter_inventory)
    selected: list[dict[str, Any]] = []
    if kind == "all_parameters":
        selected.extend(rows)
        reason = "inventory-resolved all-original-parameter scope"
    elif kind == "terminal_backbone":
        blocks = int(strategy["backbone_blocks"])
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
        if strategy["include_score_head"] and not score:
            raise FullModelTrainingError("plan087_scope_score_head_missing")
        final_norm = [row for row in rows if _is_final_norm(row["name"])]
        if strategy["include_final_norm"] and not final_norm:
            raise FullModelTrainingError("plan087_scope_final_norm_missing")
        if strategy["include_score_head"]:
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
        reason = (
            "inventory-resolved terminal original-parameter scope with "
            f"{blocks} trailing backbone block(s)"
        )
    else:
        prefixes = tuple(strategy["parameter_prefixes"])
        for prefix in prefixes:
            matched = [
                row
                for row in rows
                if row["name"] == prefix or row["name"].startswith(prefix + ".")
            ]
            if not matched:
                raise FullModelTrainingError("plan087_scope_parameter_prefix_missing")
            selected.extend(matched)
        reason = "inventory-resolved explicit module-prefix original-parameter scope"
    names = tuple(row["name"] for row in selected)
    if not names or len(names) != len(set(names)):
        raise FullModelTrainingError("plan087_scope_parameter_duplicate")
    strategy_sha256 = sha256_bytes(canonical_json_bytes(strategy))
    return TrainableScope(
        scope_id=f"plan087-{kind}-{strategy_sha256[:12]}",
        parameter_names=names,
        trainable_parameter_elements=sum(int(row["elements"]) for row in selected),
        reason=reason,
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
    raw_scopes = [resolve_scope(parameter_inventory, row["strategy"]) for row in phases]
    scopes = [raw_scopes[0]]
    for raw_scope in raw_scopes[1:]:
        previous = TrainableScope.from_value(scopes[-1])
        current = TrainableScope.from_value(raw_scope)
        current.require_expansion_of(previous)
        ordered_names = previous.parameter_names + tuple(
            name
            for name in current.parameter_names
            if name not in previous.parameter_names
        )
        scopes.append(
            TrainableScope(
                scope_id=current.scope_id,
                parameter_names=ordered_names,
                trainable_parameter_elements=current.trainable_parameter_elements,
                reason=current.reason,
            ).as_dict()
        )
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
        _validate_scope_strategy(strategy)
        normalized_phases.append(json.loads(json.dumps(phase)))
    if [row["after_observation_step"] for row in normalized_phases[1:]] != sorted(
        row["after_observation_step"] for row in normalized_phases[1:]
    ):
        raise FullModelTrainingError("plan087_route_candidate_invalid")
    return {**json.loads(json.dumps(value)), "scope_phases": normalized_phases}


def _validate_scope_strategy(strategy: Any) -> str:
    if (
        not isinstance(strategy, Mapping)
        or strategy.get("schema") != SCOPE_STRATEGY_SCHEMA
    ):
        raise FullModelTrainingError("plan087_scope_strategy_invalid")
    if set(strategy) == {"schema", "all_parameters"}:
        if strategy.get("all_parameters") is not True:
            raise FullModelTrainingError("plan087_scope_strategy_invalid")
        return "all_parameters"
    if set(strategy) == {
        "schema",
        "backbone_blocks",
        "include_score_head",
        "include_final_norm",
    }:
        blocks = strategy.get("backbone_blocks")
        if (
            not isinstance(blocks, int)
            or isinstance(blocks, bool)
            or blocks < 0
            or type(strategy.get("include_score_head")) is not bool
            or type(strategy.get("include_final_norm")) is not bool
            or not (
                blocks
                or strategy["include_score_head"]
                or strategy["include_final_norm"]
            )
        ):
            raise FullModelTrainingError("plan087_scope_strategy_invalid")
        return "terminal_backbone"
    if set(strategy) != {"schema", "parameter_prefixes"}:
        raise FullModelTrainingError("plan087_scope_strategy_invalid")
    prefixes = strategy.get("parameter_prefixes")
    if (
        not isinstance(prefixes, Sequence)
        or isinstance(prefixes, (str, bytes, bytearray))
        or not prefixes
        or len(set(prefixes)) != len(prefixes)
        or any(
            not isinstance(prefix, str)
            or re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*", prefix) is None
            for prefix in prefixes
        )
    ):
        raise FullModelTrainingError("plan087_scope_strategy_invalid")
    return "module_prefixes"


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
