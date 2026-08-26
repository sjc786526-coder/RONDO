"""Real-runtime controller for one adaptive Plan 087 route.

The shared Plan 081 core still owns update, same-cohort observation, artifact,
checkpoint, recovery and retention mechanics.  This thin layer binds those
mechanics to a real Plan 087 runtime and carries the outer search history in
every checkpoint.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from .contract import MODEL_REPOSITORY, MODEL_REVISION, FullModelTrainingError
from .plan081_controller import (
    ControllerEvidenceProfile,
    _ContinuousTrainingControllerCore,
)
from .plan082_adapter import ALLOWED_GPUS
from .plan082_controller import validate_process_identity
from .plan082_environment import validate_environment_receipt
from .plan087_adapter import RUNTIME_KIND
from .plan087_contract import validate_route_context
from .plan087_run import validate_run_spec

CONTROLLER_SCHEMA = "rondo-publication-critic-plan087-controller-state-v1"
SUMMARY_SCHEMA = "rondo-publication-critic-plan087-route-summary-v1"
REAL_RUNTIME_PROFILE = ControllerEvidenceProfile(
    controller_schema=CONTROLLER_SCHEMA,
    evidence_kind="torch_real_adaptive_direct_original_parameters",
    research_candidate_eligible=False,
    real_quality_claim=True,
)


class Plan087AdaptiveTrainingController(_ContinuousTrainingControllerCore):
    """One route whose checkpoint also retains the prior adaptive history."""

    def __init__(
        self,
        *,
        route_context: Mapping[str, Any],
        run_spec: Mapping[str, Any],
        **kwargs: Any,
    ) -> None:
        if "evidence_profile" in kwargs or "_evidence_profile" in kwargs:
            raise FullModelTrainingError(
                "plan087_controller_profile_override_forbidden"
            )
        context = validate_route_context(route_context)
        spec = validate_run_spec(run_spec)
        if spec["route_context"] != context:
            raise FullModelTrainingError("plan087_controller_run_spec_mismatch")
        super().__init__(**kwargs, evidence_profile=REAL_RUNTIME_PROFILE)
        self.state["plan087"] = {
            "runtime_identity": None,
            "process_identity": None,
            "route_context": context,
            "run_spec": spec,
            "recovery_proven_checkpoints": {},
        }

    @classmethod
    def _resume_constructor_kwargs(
        cls, controller_state: Mapping[str, Any]
    ) -> dict[str, Any]:
        del cls
        plan087 = controller_state.get("plan087")
        if not isinstance(plan087, Mapping):
            raise FullModelTrainingError("plan087_checkpoint_runtime_identity_invalid")
        return {
            "route_context": plan087.get("route_context"),
            "run_spec": plan087.get("run_spec"),
        }

    def initialize(self, adapter: Any) -> dict[str, Any]:
        assertion = getattr(adapter, "assert_fresh_exact_base", None)
        if not callable(assertion):
            raise FullModelTrainingError("plan087_fresh_exact_base_required")
        assertion(MODEL_REPOSITORY, MODEL_REVISION)
        if self.state["plan087"]["process_identity"] is None:
            raise FullModelTrainingError("plan087_process_identity_required")
        return super().initialize(adapter)

    def begin_process(self, identity: Mapping[str, Any]) -> None:
        self.state["plan087"]["process_identity"] = validate_process_identity(identity)

    def record_new_process_recovery(
        self, checkpoint_id: str, checkpoint_sha256: str
    ) -> None:
        recovered = self.state["plan087"]["recovery_proven_checkpoints"]
        if (
            not isinstance(checkpoint_id, str)
            or not checkpoint_id
            or not _sha256(checkpoint_sha256)
            or checkpoint_id != self.state.get("latest_checkpoint_id")
            or checkpoint_id in recovered
        ):
            raise FullModelTrainingError("plan087_recovery_checkpoint_role_invalid")
        recovered[checkpoint_id] = checkpoint_sha256

    def _additional_retained_checkpoint_ids(self) -> set[str]:
        retained: set[str] = set()
        latest = self.state.get("latest_checkpoint_id")
        if latest in self.state["plan087"]["recovery_proven_checkpoints"]:
            retained.add(latest)
        best = self._best_checkpoint_observation()
        if best is not None:
            retained.add(best["checkpoint_id"])
        return retained

    def _additional_retained_snapshot_ids(self) -> set[str]:
        best = self._best_checkpoint_observation()
        return {best["snapshot_id"]} if best is not None else set()

    def _best_checkpoint_observation(self) -> Mapping[str, Any] | None:
        records = [
            record
            for record in self.state["observations"]
            if isinstance(record.get("checkpoint_id"), str)
        ]
        return (
            max(records, key=lambda record: record["comparison_value"])
            if records
            else None
        )

    def _validate_adapter(self, adapter: Any) -> None:
        method = getattr(adapter, "plan087_runtime_identity", None)
        if not callable(method):
            raise FullModelTrainingError("plan087_real_adapter_required")
        identity = method()
        validate_runtime_identity(identity)
        bound = self.state["plan087"]["runtime_identity"]
        if bound is None:
            self.state["plan087"]["runtime_identity"] = json.loads(json.dumps(identity))
        elif bound != identity:
            raise FullModelTrainingError("plan087_runtime_identity_drifted")

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
            or change.get("method")
            != "torch.equal_any_nonzero_gradient_parameter_cpu_snapshots"
            or change.get("parameter_name") not in scope.parameter_names
            or not isinstance(change.get("parameter_elements"), int)
            or isinstance(change["parameter_elements"], bool)
            or change["parameter_elements"] <= 0
            or not isinstance(change.get("maximum_absolute_change"), (int, float))
            or isinstance(change["maximum_absolute_change"], bool)
            or not math.isfinite(float(change["maximum_absolute_change"]))
            or float(change["maximum_absolute_change"]) <= 0
        ):
            raise FullModelTrainingError("plan087_update_parameter_change_invalid")
        super()._accept_update_receipt(
            {key: item for key, item in value.items() if key != "parameter_change"},
            step=step,
            scope=scope,
        )

    def _accept_resumed_state(
        self,
        value: Mapping[str, Any],
        checkpoint_id: str,
        *,
        training_state_codec: str,
    ) -> None:
        plan087 = value.get("plan087")
        if (
            not isinstance(plan087, Mapping)
            or set(plan087)
            != {
                "runtime_identity",
                "process_identity",
                "route_context",
                "run_spec",
                "recovery_proven_checkpoints",
            }
            or plan087.get("runtime_identity")
            != self.state["plan087"]["runtime_identity"]
            or validate_route_context(plan087.get("route_context"))
            != self.state["plan087"]["route_context"]
            or validate_run_spec(plan087.get("run_spec"))
            != self.state["plan087"]["run_spec"]
        ):
            raise FullModelTrainingError("plan087_checkpoint_runtime_identity_invalid")
        validate_process_identity(plan087.get("process_identity"))
        recovered = plan087.get("recovery_proven_checkpoints")
        if not isinstance(recovered, Mapping) or any(
            not isinstance(identifier, str)
            or not identifier
            or not _sha256(digest)
            for identifier, digest in recovered.items()
        ):
            raise FullModelTrainingError("plan087_checkpoint_recovery_roles_invalid")
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
            "route_context": json.loads(
                json.dumps(self.state["plan087"]["route_context"])
            ),
            "run_spec": json.loads(json.dumps(self.state["plan087"]["run_spec"])),
            "actual_trainable_scope": self.state["current_scope"],
            "scope_history": json.loads(json.dumps(self.state["scope_history"])),
            "scope_decisions": json.loads(json.dumps(self.state["scope_decisions"])),
            "observations": json.loads(json.dumps(self.state["observations"])),
            "selection": json.loads(json.dumps(self.state["selection"])),
            "retention": {
                "turning_points": json.loads(json.dumps(self.state["turning_points"])),
                "latest_checkpoint_id": self.state["latest_checkpoint_id"],
                "recovery_proven_checkpoints": json.loads(
                    json.dumps(self.state["plan087"]["recovery_proven_checkpoints"])
                ),
            },
            "runtime_identity": json.loads(
                json.dumps(self.state["plan087"]["runtime_identity"])
            ),
            "claims": {
                "real_training_run": bool(self.state["updates"]),
                "adaptive_search_route": True,
                "promising_candidate_decided": False,
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
        raise FullModelTrainingError("plan087_runtime_identity_invalid")
    return json.loads(json.dumps(value))


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
