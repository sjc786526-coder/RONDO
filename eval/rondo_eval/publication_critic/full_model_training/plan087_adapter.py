"""Adaptive direct-parameter Torch recipe for Plan 087.

The model loader, update proof, validation isolation and checkpoint codec stay
in the Plan 082 adapter.  This module only widens the commissioning variables
that Plan 087 is explicitly allowed to change.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import FullModelTrainingError
from .plan082_adapter import TorchContinuousTrainingAdapter

RECIPE_SCHEMA = "rondo-publication-critic-plan087-training-recipe-v1"
RUNTIME_KIND = "torch_real_adaptive_direct_original_parameters"
COMPONENTS = frozenset({"binary", "boundary", "within_pass"})


def validate_adaptive_recipe(value: Any) -> dict[str, Any]:
    """Validate only the bounded optimizer/objective family allowed by Plan 087."""

    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "seed",
        "optimizer",
        "scheduler",
        "parameter_dtype",
        "binary_micro_batch_size",
        "pair_micro_batch_size",
        "gradient_clip_norm",
        "activation_checkpointing",
        "attention_backend",
        "macro_update",
        "objective",
    }:
        raise FullModelTrainingError("plan087_recipe_fields_invalid")
    optimizer = value.get("optimizer")
    scheduler = value.get("scheduler")
    objective = value.get("objective")
    if (
        value.get("schema") != RECIPE_SCHEMA
        or not _positive_int(value.get("seed"))
        or not isinstance(optimizer, Mapping)
        or set(optimizer)
        != {
            "name",
            "learning_rate",
            "betas",
            "epsilon",
            "weight_decay",
            "fused",
        }
        or optimizer.get("name") != "torch.optim.AdamW"
        or not _positive_finite(optimizer.get("learning_rate"))
        or not _betas(optimizer.get("betas"))
        or not _positive_finite(optimizer.get("epsilon"))
        or not _nonnegative_finite(optimizer.get("weight_decay"))
        or type(optimizer.get("fused")) is not bool
        or not _scheduler(scheduler)
        or value.get("parameter_dtype") not in {"float32", "bfloat16"}
        or not _positive_int(value.get("binary_micro_batch_size"))
        or not _positive_int(value.get("pair_micro_batch_size"))
        or not _nonnegative_finite(value.get("gradient_clip_norm"))
        or type(value.get("activation_checkpointing")) is not bool
        or value.get("attention_backend") != "sdpa"
        or value.get("macro_update") != "one_full_v8_train_cohort"
        or not _objective(objective)
    ):
        raise FullModelTrainingError("plan087_recipe_invalid")
    return json.loads(json.dumps(value))


class Plan087TorchTrainingAdapter(TorchContinuousTrainingAdapter):
    """Plan 082 mechanics with a separately validated adaptive recipe."""

    runtime_kind = RUNTIME_KIND
    image_identity_environment_variable = "RONDO_PLAN087_IMAGE_IDENTITY"
    training_state_codec = "plan087-torch-state-v1"

    @classmethod
    def validate_recipe_value(cls, value: Any) -> dict[str, Any]:
        return validate_adaptive_recipe(value)

    def plan087_runtime_identity(self) -> dict[str, Any]:
        return self.plan082_runtime_identity()


def _objective(value: Any) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "scalar",
        "direction",
        "binary_loss",
        "pair_loss",
        "pair_margin",
        "pair_temperature",
        "component_weights",
    }:
        return False
    weights = value.get("component_weights")
    return not (
        value.get("scalar") != "logits[:,0]"
        or value.get("direction") != "preferred_minus_dispreferred"
        or value.get("binary_loss") != "softplus(-signed_target*logits[:,0])"
        or value.get("pair_loss") != "softplus(dispreferred-preferred)"
        or value.get("pair_margin") != 0.0
        or value.get("pair_temperature") != 1.0
        or not isinstance(weights, Mapping)
        or set(weights) != COMPONENTS
        or any(not _nonnegative_finite(item) for item in weights.values())
        or not math.isclose(
            sum(float(item) for item in weights.values()),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        or sum(float(item) > 0.0 for item in weights.values()) < 2
    )


def _scheduler(value: Any) -> bool:
    if value == {"name": "constant"}:
        return True
    return (
        isinstance(value, Mapping)
        and set(value) == {"name", "warmup_updates", "total_updates"}
        and value.get("name") == "linear_warmup_decay"
        and _nonnegative_int(value.get("warmup_updates"))
        and _positive_int(value.get("total_updates"))
        and int(value["warmup_updates"]) < int(value["total_updates"])
    )


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _nonnegative_finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _betas(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 2
        and all(
            isinstance(item, (int, float))
            and not isinstance(item, bool)
            and math.isfinite(float(item))
            and 0 <= float(item) < 1
            for item in value
        )
    )
