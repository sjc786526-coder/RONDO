"""Real-runtime continuous controller for Plan 082.

The shared Plan 081 controller owns update/observation/checkpoint mechanics.
This layer makes a real Torch runtime identity mandatory while deliberately
leaving research-candidate eligibility to the separately frozen formal-run
finalizer.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from typing import Any

from .contract import (
    MODEL_REPOSITORY,
    MODEL_REVISION,
    FullModelTrainingError,
)
from .plan081_controller import (
    ControllerEvidenceProfile,
    _ContinuousTrainingControllerCore,
)
from .plan082_adapter import ALLOWED_GPUS, RUNTIME_KIND
from .plan082_environment import validate_environment_receipt


CONTROLLER_SCHEMA = "rondo-publication-critic-plan082-controller-state-v1"
SUMMARY_SCHEMA = "rondo-publication-critic-plan082-training-summary-v1"
REAL_RUNTIME_PROFILE = ControllerEvidenceProfile(
    controller_schema=CONTROLLER_SCHEMA,
    evidence_kind="torch_real_direct_original_parameters",
    research_candidate_eligible=False,
    real_quality_claim=True,
)


class Plan082ContinuousTrainingController(_ContinuousTrainingControllerCore):
    """Plan 081 mechanics gated by an exact Plan 082 runtime identity."""

    def __init__(self, **kwargs: Any) -> None:
        if "evidence_profile" in kwargs or "_evidence_profile" in kwargs:
            raise FullModelTrainingError(
                "plan082_controller_profile_override_forbidden"
            )
        super().__init__(**kwargs, evidence_profile=REAL_RUNTIME_PROFILE)
        self.state["plan082"] = {
            "runtime_identity": None,
            "process_identity": None,
            "formal_freeze_sha256": None,
            "recovery_proven_checkpoints": {},
        }

    def initialize(self, adapter: Any) -> dict[str, Any]:
        assertion = getattr(adapter, "assert_fresh_exact_base", None)
        if not callable(assertion):
            raise FullModelTrainingError("plan082_fresh_exact_base_required")
        assertion(MODEL_REPOSITORY, MODEL_REVISION)
        if self.state["plan082"]["process_identity"] is None:
            raise FullModelTrainingError("plan082_process_identity_required")
        return super().initialize(adapter)

    def begin_process(self, identity: Mapping[str, Any]) -> None:
        self.state["plan082"]["process_identity"] = validate_process_identity(identity)

    def bind_formal_freeze(self, freeze_sha256: str) -> None:
        if (
            not isinstance(freeze_sha256, str)
            or len(freeze_sha256) != 64
            or any(character not in "0123456789abcdef" for character in freeze_sha256)
            or self.state["status"] != "created"
            or self.state["plan082"]["formal_freeze_sha256"] is not None
        ):
            raise FullModelTrainingError("plan082_formal_freeze_binding_invalid")
        self.state["plan082"]["formal_freeze_sha256"] = freeze_sha256

    def record_new_process_recovery(
        self, checkpoint_id: str, checkpoint_sha256: str
    ) -> None:
        if (
            not isinstance(checkpoint_id, str)
            or not checkpoint_id
            or not isinstance(checkpoint_sha256, str)
            or len(checkpoint_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in checkpoint_sha256
            )
            or checkpoint_id != self.state.get("latest_checkpoint_id")
            or checkpoint_id in self.state["plan082"]["recovery_proven_checkpoints"]
        ):
            raise FullModelTrainingError("plan082_recovery_checkpoint_role_invalid")
        self.state["plan082"]["recovery_proven_checkpoints"][checkpoint_id] = (
            checkpoint_sha256
        )

    def _additional_retained_checkpoint_ids(self) -> set[str]:
        retained = set(self.state["plan082"]["recovery_proven_checkpoints"])
        best = self._best_checkpoint_observation()
        if best is not None:
            retained.add(best["checkpoint_id"])
        return retained

    def _additional_retained_snapshot_ids(self) -> set[str]:
        best = self._best_checkpoint_observation()
        return {best["snapshot_id"]} if best is not None else set()

    def _best_checkpoint_observation(self) -> Mapping[str, Any] | None:
        checkpoint_observations = [
            record
            for record in self.state["observations"]
            if isinstance(record.get("checkpoint_id"), str)
        ]
        return (
            max(
                checkpoint_observations,
                key=lambda record: record["comparison_value"],
            )
            if checkpoint_observations
            else None
        )

    def _validate_adapter(self, adapter: Any) -> None:
        method = getattr(adapter, "plan082_runtime_identity", None)
        if not callable(method):
            raise FullModelTrainingError("plan082_real_adapter_required")
        identity = method()
        validate_runtime_identity(identity)
        bound = self.state["plan082"]["runtime_identity"]
        if bound is None:
            self.state["plan082"]["runtime_identity"] = json.loads(json.dumps(identity))
        elif bound != identity:
            raise FullModelTrainingError("plan082_runtime_identity_drifted")

    def _accept_update_receipt(self, value: Any, *, step: int, scope: Any) -> None:
        change = value.get("parameter_change") if isinstance(value, Mapping) else None
        if (
            not isinstance(value, Mapping)
            or not isinstance(change, Mapping)
            or set(change)
            != {
                "method",
                "parameter_name",
                "parameter_elements",
                "maximum_absolute_change",
            }
            or change.get("method") != "torch.equal_selected_nonzero_gradient_parameter"
            or change.get("parameter_name") not in scope.parameter_names
            or not isinstance(change.get("parameter_elements"), int)
            or isinstance(change["parameter_elements"], bool)
            or change["parameter_elements"] <= 0
            or not isinstance(change.get("maximum_absolute_change"), (int, float))
            or isinstance(change["maximum_absolute_change"], bool)
            or not math.isfinite(float(change["maximum_absolute_change"]))
            or float(change["maximum_absolute_change"]) <= 0
        ):
            raise FullModelTrainingError("plan082_update_parameter_change_invalid")
        core = {key: item for key, item in value.items() if key != "parameter_change"}
        super()._accept_update_receipt(core, step=step, scope=scope)

    def _accept_resumed_state(
        self,
        value: Mapping[str, Any],
        checkpoint_id: str,
        *,
        training_state_codec: str,
    ) -> None:
        plan082 = value.get("plan082")
        if (
            not isinstance(plan082, Mapping)
            or set(plan082)
            != {
                "runtime_identity",
                "process_identity",
                "formal_freeze_sha256",
                "recovery_proven_checkpoints",
            }
            or plan082.get("runtime_identity")
            != self.state["plan082"]["runtime_identity"]
        ):
            raise FullModelTrainingError("plan082_checkpoint_runtime_identity_invalid")
        validate_process_identity(plan082.get("process_identity"))
        recovered = plan082.get("recovery_proven_checkpoints")
        if not isinstance(recovered, Mapping) or any(
            not isinstance(checkpoint_id, str)
            or not checkpoint_id
            or not isinstance(checkpoint_sha256, str)
            or len(checkpoint_sha256) != 64
            or any(
                character not in "0123456789abcdef" for character in checkpoint_sha256
            )
            for checkpoint_id, checkpoint_sha256 in recovered.items()
        ):
            raise FullModelTrainingError("plan082_checkpoint_recovery_roles_invalid")
        super()._accept_resumed_state(
            value,
            checkpoint_id,
            training_state_codec=training_state_codec,
        )

    def archive_summary(self) -> dict[str, Any]:
        return {
            "schema": SUMMARY_SCHEMA,
            "status": self.state["status"],
            "global_step": self.state["current_step"],
            "actual_trainable_scope": self.state["current_scope"],
            "scope_history": json.loads(json.dumps(self.state["scope_history"])),
            "scope_decisions": json.loads(json.dumps(self.state["scope_decisions"])),
            "observation_count": len(self.state["observations"]),
            "update_count": len(self.state["updates"]),
            "selection": json.loads(json.dumps(self.state["selection"])),
            "retention": {
                "turning_points": json.loads(json.dumps(self.state["turning_points"])),
                "latest_checkpoint_id": self.state["latest_checkpoint_id"],
            },
            "runtime_identity": json.loads(
                json.dumps(self.state["plan082"]["runtime_identity"])
            ),
            "claims": {
                "fixture_fake_control_flow": False,
                "typed_train_only_input_bound": True,
                "real_model_runtime_bound": (
                    self.state["plan082"]["runtime_identity"] is not None
                ),
                "real_training_run": bool(self.state["updates"]),
                "formal_freeze_bound": (
                    self.state["plan082"]["formal_freeze_sha256"] is not None
                ),
                "research_candidate_produced": False,
                "product_go": False,
                "m3_c2_evidence": False,
                "unseen_evidence": False,
            },
        }


def validate_runtime_identity(value: Any) -> dict[str, Any]:
    required = {
        "runtime_kind",
        "gpu_name",
        "gpu_count",
        "cuda_version",
        "torch_version",
        "transformers_version",
        "model_repository",
        "model_revision",
        "peft",
        "quantized_training",
        "snapshot_content_sha256",
        "recipe_sha256",
        "parameter_inventory_sha256",
        "parameter_tensors",
        "parameter_elements",
        "environment",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or value.get("runtime_kind") != RUNTIME_KIND
        or value.get("gpu_name") not in ALLOWED_GPUS
        or value.get("gpu_count") != 1
        or value.get("model_repository") != MODEL_REPOSITORY
        or value.get("model_revision") != MODEL_REVISION
        or value.get("peft") is not False
        or value.get("quantized_training") is not False
        or validate_environment_receipt(value.get("environment"))["gpu_names"]
        != [value.get("gpu_name")]
        or value["environment"]["torch_cuda_runtime"] != value.get("cuda_version")
        or any(
            not isinstance(value.get(key), str) or not value[key]
            for key in (
                "cuda_version",
                "torch_version",
                "transformers_version",
                "snapshot_content_sha256",
                "recipe_sha256",
                "parameter_inventory_sha256",
            )
        )
        or any(
            not isinstance(value.get(key), int)
            or isinstance(value[key], bool)
            or value[key] <= 0
            for key in ("parameter_tensors", "parameter_elements")
        )
    ):
        raise FullModelTrainingError("plan082_runtime_identity_invalid")
    return json.loads(json.dumps(value))


def validate_process_identity(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"instance_id", "hostname", "pid"}
        or not isinstance(value.get("instance_id"), str)
        or len(value["instance_id"]) != 32
        or any(
            character not in "0123456789abcdef" for character in value["instance_id"]
        )
        or not isinstance(value.get("hostname"), str)
        or not value["hostname"]
        or not isinstance(value.get("pid"), int)
        or isinstance(value["pid"], bool)
        or value["pid"] <= 0
    ):
        raise FullModelTrainingError("plan082_process_identity_invalid")
    return json.loads(json.dumps(value))
