"""Plan 081 route and handoff contracts.

This module deliberately sits beside, rather than inside, the frozen Plan 060
and Plan 066 recipe validators.  It binds the unchanged model, data, scalar and
split identities while leaving the real training recipe to commissioning.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

from .contract import (
    MODEL_REPOSITORY,
    MODEL_REVISION,
    FullModelTrainingError,
    read_json,
    require_nonnegative_number,
    require_positive_int,
    require_text,
)
from .plan066_data import (
    V8_CONTENT_SHA256,
    V8_MANIFEST_SHA256,
    V8_MEMBERSHIP_SHA256,
)


ROUTE_SCHEMA = "rondo-publication-critic-plan081-route-v1"
CLOUD_HANDOFF_SCHEMA = "rondo-publication-critic-plan081-cloud-handoff-v1"
UPDATE_METHOD = "direct_original_parameter_update"
CLOUD_REQUIRED_INPUTS = (
    "exact_model_and_v8_route_contract",
    "runtime_selected_trainable_scope_and_expansion_policy",
    "runtime_selected_optimizer_scheduler_and_update_recipe",
    "same_validation_cohort_comparison_policy_and_tolerance",
    "separate_external_action_authorization",
)
CLOUD_REQUIRED_OUTPUTS = (
    "commissioning_runtime_and_memory_facts",
    "actual_recipe_and_trainable_inventory",
    "continuous_validation_observations",
    "verified_latest_recovery_checkpoint",
    "base_best_latest_and_turning_point_retention",
    "better_than_base_candidate_or_no_improvement",
)
COMPARISON_METRICS = frozenset(
    {
        "roc_auc",
        "balanced_accuracy",
        "boundary_pair_strict_win_rate",
        "boundary_pair_mean_margin",
        "within_pass_pair_strict_win_rate",
        "within_pass_pair_mean_margin",
    }
)


@dataclass(frozen=True)
class TrainableScope:
    """The actual original-model parameter inventory updated at one point."""

    scope_id: str
    parameter_names: tuple[str, ...]
    trainable_parameter_elements: int
    reason: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.scope_id, str)
            or not self.scope_id.strip()
            or not isinstance(self.parameter_names, tuple)
            or not self.parameter_names
            or any(not isinstance(name, str) or not name.strip() for name in self.parameter_names)
            or len(set(self.parameter_names)) != len(self.parameter_names)
            or not isinstance(self.trainable_parameter_elements, int)
            or isinstance(self.trainable_parameter_elements, bool)
            or self.trainable_parameter_elements <= 0
            or not isinstance(self.reason, str)
            or not self.reason.strip()
        ):
            raise FullModelTrainingError("plan081_trainable_scope_invalid")

    @classmethod
    def from_value(cls, value: Any) -> "TrainableScope":
        if not isinstance(value, Mapping) or set(value) != {
            "scope_id",
            "update_method",
            "parameter_names",
            "trainable_parameter_elements",
            "reason",
        }:
            raise FullModelTrainingError("plan081_trainable_scope_invalid")
        names = value.get("parameter_names")
        if (
            value.get("update_method") != UPDATE_METHOD
            or not isinstance(names, Sequence)
            or isinstance(names, (str, bytes, bytearray))
            or not names
            or any(not isinstance(name, str) or not name.strip() for name in names)
            or len(set(names)) != len(names)
        ):
            raise FullModelTrainingError("plan081_trainable_scope_invalid")
        return cls(
            scope_id=require_text(value.get("scope_id"), "plan081_scope_id_invalid"),
            parameter_names=tuple(names),
            trainable_parameter_elements=require_positive_int(
                value.get("trainable_parameter_elements"),
                "plan081_trainable_elements_invalid",
            ),
            reason=require_text(value.get("reason"), "plan081_scope_reason_invalid"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope_id": self.scope_id,
            "update_method": UPDATE_METHOD,
            "parameter_names": list(self.parameter_names),
            "trainable_parameter_elements": self.trainable_parameter_elements,
            "reason": self.reason,
        }

    def require_expansion_of(self, previous: "TrainableScope") -> None:
        old = set(previous.parameter_names)
        new = set(self.parameter_names)
        if (
            self.scope_id == previous.scope_id
            or not old < new
            or self.trainable_parameter_elements <= previous.trainable_parameter_elements
        ):
            raise FullModelTrainingError("plan081_scope_not_strict_expansion")


@dataclass(frozen=True)
class ComparisonPolicy:
    """Runtime-selected same-cohort comparison rule, not a frozen recipe."""

    metric: str
    tolerance: float

    def __post_init__(self) -> None:
        if self.metric not in COMPARISON_METRICS:
            raise FullModelTrainingError("plan081_comparison_policy_invalid")
        require_nonnegative_number(
            self.tolerance, "plan081_comparison_tolerance_invalid"
        )

    @classmethod
    def from_value(cls, value: Any) -> "ComparisonPolicy":
        if (
            not isinstance(value, Mapping)
            or set(value) != {"metric", "direction", "tolerance"}
            or value.get("metric") not in COMPARISON_METRICS
            or value.get("direction") != "higher_is_better"
        ):
            raise FullModelTrainingError("plan081_comparison_policy_invalid")
        return cls(
            metric=str(value["metric"]),
            tolerance=require_nonnegative_number(
                value.get("tolerance"), "plan081_comparison_tolerance_invalid"
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "direction": "higher_is_better",
            "tolerance": self.tolerance,
        }


@dataclass(frozen=True)
class ControlPlan:
    """One commissioning run's configurable control points."""

    maximum_updates: int
    observation_steps: tuple[int, ...]
    checkpoint_steps: tuple[int, ...]
    turning_point_limit: int

    def __post_init__(self) -> None:
        maximum = require_positive_int(
            self.maximum_updates, "plan081_maximum_updates_invalid"
        )
        observations = _steps(
            self.observation_steps, maximum, "plan081_observation_steps_invalid"
        )
        checkpoints = _steps(
            self.checkpoint_steps, maximum, "plan081_checkpoint_steps_invalid"
        )
        if (
            observations != self.observation_steps
            or checkpoints != self.checkpoint_steps
            or not observations
            or not checkpoints
            or checkpoints[-1] != maximum
            or not set(checkpoints) <= set(observations)
        ):
            raise FullModelTrainingError("plan081_control_plan_invalid")
        require_positive_int(
            self.turning_point_limit, "plan081_turning_point_limit_invalid"
        )

    @classmethod
    def from_value(cls, value: Any) -> "ControlPlan":
        if not isinstance(value, Mapping) or set(value) != {
            "maximum_updates",
            "observation_steps",
            "checkpoint_steps",
            "turning_point_limit",
        }:
            raise FullModelTrainingError("plan081_control_plan_invalid")
        maximum = require_positive_int(
            value.get("maximum_updates"), "plan081_maximum_updates_invalid"
        )
        observations = _steps(
            value.get("observation_steps"), maximum, "plan081_observation_steps_invalid"
        )
        checkpoints = _steps(
            value.get("checkpoint_steps"), maximum, "plan081_checkpoint_steps_invalid"
        )
        if (
            not observations
            or not checkpoints
            or checkpoints[-1] != maximum
            or not set(checkpoints) <= set(observations)
        ):
            raise FullModelTrainingError("plan081_control_plan_invalid")
        return cls(
            maximum_updates=maximum,
            observation_steps=observations,
            checkpoint_steps=checkpoints,
            turning_point_limit=require_positive_int(
                value.get("turning_point_limit"),
                "plan081_turning_point_limit_invalid",
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "maximum_updates": self.maximum_updates,
            "observation_steps": list(self.observation_steps),
            "checkpoint_steps": list(self.checkpoint_steps),
            "turning_point_limit": self.turning_point_limit,
        }


def load_route_contract(path: Path) -> dict[str, Any]:
    return validate_route_contract(read_json(Path(path)))


def validate_route_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "model",
        "data",
        "update_route",
        "controller",
        "validation",
        "selection",
        "claims",
    }:
        raise FullModelTrainingError("plan081_route_contract_invalid")
    model = value.get("model")
    if model != {
        "repository": MODEL_REPOSITORY,
        "revision": MODEL_REVISION,
        "scalar": "logits[:,0]",
        "projection": "stable_sigmoid_v1",
        "direction": "higher_is_better",
    }:
        raise FullModelTrainingError("plan081_model_identity_invalid")
    data = value.get("data")
    if data != {
        "dataset_revision": "v8",
        "manifest_file_sha256": V8_MANIFEST_SHA256,
        "manifest_content_sha256": V8_CONTENT_SHA256,
        "membership_sha256": V8_MEMBERSHIP_SHA256,
        "source": "plan066_unseen_free_train_validation_projection_v1",
        "training_split": "train",
        "validation_split": "validation",
        "pair_and_label_semantics": "frozen_unchanged",
        "unseen_test_body_exported": False,
    }:
        raise FullModelTrainingError("plan081_data_identity_invalid")
    update = value.get("update_route")
    if update != {
        "method": UPDATE_METHOD,
        "peft": False,
        "lora": False,
        "qlora": False,
        "quantized_training": False,
        "initial_scope": "partial_runtime_inventory",
        "scope_expansion": "observation_driven_runtime_decision",
        "actual_scope_recorded_in_checkpoint": True,
        "recipe_fields_fixed_here": [],
        "recipe_fields_deferred": [
            "parameter_names",
            "learning_rate",
            "batch",
            "update_count",
            "optimizer",
            "scheduler",
            "scope_expansion_policy",
        ],
    }:
        raise FullModelTrainingError("plan081_update_route_invalid")
    if value.get("controller") != {
        "continuous_updates": True,
        "observation_points": "runtime_configurable",
        "checkpoint_points": "runtime_configurable",
        "pause_continue_resume": True,
    }:
        raise FullModelTrainingError("plan081_controller_contract_invalid")
    if value.get("validation") != {
        "split": "validation",
        "gradient_access": False,
        "feeds_parameter_updates": False,
        "may_inform_scope_and_stop_decisions": True,
        "retains_full_metrics_and_signed_pair_margins": True,
        "qualification_claim": False,
        "m3_c2_claim": False,
        "unseen_claim": False,
    }:
        raise FullModelTrainingError("plan081_validation_contract_invalid")
    if value.get("selection") != {
        "base_role": "research_incumbent",
        "training_best_role": "best_within_training_sequence",
        "candidate_requires_better_than_base": True,
        "otherwise": "no_improvement",
        "product_go_required": False,
        "comparison_policy": "runtime_configurable_same_validation_cohort",
    }:
        raise FullModelTrainingError("plan081_selection_contract_invalid")
    if value.get("claims") != {
        "local_fixture_only": True,
        "real_model_loaded": False,
        "gpu_validated": False,
        "quality_candidate_produced": False,
        "cloud_authorized": False,
    }:
        raise FullModelTrainingError("plan081_claims_invalid")
    if value.get("schema") != ROUTE_SCHEMA:
        raise FullModelTrainingError("plan081_route_schema_invalid")
    return dict(value)


def load_cloud_handoff(path: Path) -> dict[str, Any]:
    return validate_cloud_handoff(read_json(Path(path)))


def validate_cloud_handoff(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "authorization",
        "work",
        "hardware_priority",
        "limits",
        "retained_plan079_volume",
        "required_inputs",
        "required_outputs",
        "claims",
    }:
        raise FullModelTrainingError("plan081_cloud_handoff_invalid")
    hardware = value.get("hardware_priority")
    limits = value.get("limits")
    if (
        value.get("schema") != CLOUD_HANDOFF_SCHEMA
        or value.get("authorization") != "not_granted"
        or value.get("work") != "commissioning_and_training_parameter_development"
        or hardware
        != [
            {"priority": 1, "gpu": "NVIDIA A40", "vram_gb": 48},
            {"priority": 2, "gpu": "NVIDIA L40S", "vram_gb": 48},
        ]
        or limits
        != {
            "gpu_count": 1,
            "maximum_window_hours": 12,
            "maximum_external_cost_usd": 15,
        }
        or value.get("retained_plan079_volume")
        != {
            "required": False,
            "selects_gpu": False,
            "selects_region": False,
            "guarantees_capacity": False,
            "startup_prerequisite": False,
        }
    ):
        raise FullModelTrainingError("plan081_cloud_handoff_invalid")
    required_inputs = value.get("required_inputs")
    required_outputs = value.get("required_outputs")
    if (
        required_inputs != list(CLOUD_REQUIRED_INPUTS)
        or required_outputs != list(CLOUD_REQUIRED_OUTPUTS)
    ):
        raise FullModelTrainingError("plan081_cloud_handoff_io_invalid")
    if value.get("claims") != {
        "inventory_checked": False,
        "resource_created": False,
        "data_uploaded": False,
        "cost_incurred": False,
        "a40_or_l40s_feasibility_proven": False,
    }:
        raise FullModelTrainingError("plan081_cloud_handoff_claims_invalid")
    return dict(value)


def compare_values(value: float, reference: float, policy: ComparisonPolicy) -> str:
    try:
        current = float(value)
        baseline = float(reference)
    except (TypeError, ValueError) as exc:
        raise FullModelTrainingError("plan081_comparison_value_invalid") from exc
    if not math.isfinite(current) or not math.isfinite(baseline):
        raise FullModelTrainingError("plan081_comparison_value_invalid")
    difference = current - baseline
    if difference > policy.tolerance:
        return "improved"
    if difference < -policy.tolerance:
        return "regressed"
    return "stalled"


def _steps(value: Any, maximum: int, code: str) -> tuple[int, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or any(
            not isinstance(step, int)
            or isinstance(step, bool)
            or step <= 0
            or step > maximum
            for step in value
        )
    ):
        raise FullModelTrainingError(code)
    result = tuple(value)
    if tuple(sorted(set(result))) != result:
        raise FullModelTrainingError(code)
    return result
