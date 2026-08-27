"""Exact Route O adapter profile for continuous Plan 094 updates."""

from __future__ import annotations

import os
from typing import Any

from .plan090_adapter import Plan090TorchTrainingAdapter


RUNTIME_KIND = "torch_real_route_o_continuous_direct_original_parameters"


class Plan094TorchTrainingAdapter(Plan090TorchTrainingAdapter):
    """Keep Plan 090 Route O precision semantics while allowing continuation."""

    runtime_kind = RUNTIME_KIND
    image_identity_environment_variable = "RONDO_PLAN094_IMAGE_IDENTITY"
    training_state_codec = "plan094-torch-state-v1"

    def plan094_runtime_identity(self) -> dict[str, Any]:
        identity = self.plan082_runtime_identity()
        repeat = self._repeat_semantics()
        return {
            **identity,
            "provider_pod_id": os.getenv("RONDO_PLAN094_PROVIDER_POD_ID", ""),
            "provider_pod_name": os.getenv("RONDO_PLAN094_PROVIDER_POD_NAME", ""),
            "precision_controls": self._precision_controls(),
            "continuation_semantics": {
                key: value
                for key, value in repeat.items()
                if key != "recipe_seed_metadata"
            },
        }


__all__ = ["Plan094TorchTrainingAdapter", "RUNTIME_KIND"]
