"""Fixed one-update controller for each clean Plan 090 confirmation run."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from .contract import (
    MODEL_REPOSITORY,
    MODEL_REVISION,
    FullModelTrainingError,
    canonical_json_bytes,
    sha256_bytes,
)
from .plan081_controller import (
    ControllerEvidenceProfile,
    _ContinuousTrainingControllerCore,
)
from .plan081_observation import build_training_observation
from .plan081_contract import TrainableScope
from .plan082_controller import validate_process_identity
from .plan082_environment import validate_environment_receipt
from .objective import binary_reference, pair_reference
from .plan090_adapter import PRECISION_RECEIPT_SCHEMA, RUNTIME_KIND
from .plan090_artifacts import Plan090ArtifactStore
from .plan090_contract import (
    SNAPSHOT_CONTENT_SHA256,
    freeze_sha256,
    validate_budget_snapshot,
    validate_freeze,
    validate_run_spec,
)

CONTROLLER_SCHEMA = "rondo-publication-critic-plan090-controller-state-v1"
SUMMARY_SCHEMA = "rondo-publication-critic-plan090-run-summary-v1"
OBJECTIVE_DIAGNOSTIC_SCHEMA = "rondo-publication-critic-plan090-objective-diagnostic-v1"
REAL_RUNTIME_PROFILE = ControllerEvidenceProfile(
    controller_schema=CONTROLLER_SCHEMA,
    evidence_kind="torch_real_route_o_confirmation",
    research_candidate_eligible=False,
    real_quality_claim=True,
)


class Plan090ConfirmationController(_ContinuousTrainingControllerCore):
    """One fixed exact-base run with validation and train diagnostics."""

    def __init__(
        self,
        *,
        freeze: Mapping[str, Any],
        run_spec: Mapping[str, Any],
        launch_budget_snapshot: Mapping[str, Any],
        **kwargs: Any,
    ) -> None:
        if "evidence_profile" in kwargs or "_evidence_profile" in kwargs:
            raise FullModelTrainingError(
                "plan090_controller_profile_override_forbidden"
            )
        if not isinstance(kwargs.get("artifact_store"), Plan090ArtifactStore):
            raise FullModelTrainingError("plan090_artifact_store_required")
        contract = validate_freeze(freeze)
        spec = validate_run_spec(run_spec, freeze=contract)
        launch_budget = validate_budget_snapshot(launch_budget_snapshot)
        super().__init__(**kwargs, evidence_profile=REAL_RUNTIME_PROFILE)
        self.state["plan090"] = {
            "freeze": contract,
            "freeze_sha256": freeze_sha256(contract),
            "run_spec": spec,
            "launch_budget_snapshot": launch_budget,
            "runtime_identity": None,
            "process_identity": None,
            "training_observations": [],
            "precision_receipt": None,
            "recovery_proven_checkpoints": {},
        }

    @classmethod
    def _resume_constructor_kwargs(
        cls, controller_state: Mapping[str, Any]
    ) -> dict[str, Any]:
        del cls
        plan090 = controller_state.get("plan090")
        if not isinstance(plan090, Mapping):
            raise FullModelTrainingError("plan090_checkpoint_contract_invalid")
        return {
            "freeze": plan090.get("freeze"),
            "run_spec": plan090.get("run_spec"),
            "launch_budget_snapshot": plan090.get("launch_budget_snapshot"),
        }

    def initialize(self, adapter: Any) -> dict[str, Any]:
        assertion = getattr(adapter, "assert_fresh_exact_base", None)
        if not callable(assertion):
            raise FullModelTrainingError("plan090_fresh_exact_base_required")
        assertion(MODEL_REPOSITORY, MODEL_REVISION)
        if self.state["plan090"]["process_identity"] is None:
            raise FullModelTrainingError("plan090_process_identity_required")
        super().initialize(adapter)
        self._record_training_observation(adapter, global_step=0)
        return self.archive_summary()

    def begin_process(self, identity: Mapping[str, Any]) -> None:
        self.state["plan090"]["process_identity"] = validate_process_identity(identity)

    def restart_from_exact_base(self, adapter: Any) -> Any:
        del adapter
        raise FullModelTrainingError(
            "plan090_exact_base_restart_requires_new_attempt_namespace"
        )

    def record_new_process_recovery(
        self, checkpoint_id: str, checkpoint_sha256: str
    ) -> None:
        recovered = self.state["plan090"]["recovery_proven_checkpoints"]
        if (
            not isinstance(checkpoint_id, str)
            or not checkpoint_id
            or not _sha256(checkpoint_sha256)
            or checkpoint_id != self.state.get("latest_checkpoint_id")
            or checkpoint_id in recovered
        ):
            raise FullModelTrainingError("plan090_recovery_checkpoint_role_invalid")
        recovered[checkpoint_id] = checkpoint_sha256

    def _record_observation(
        self, adapter: Any, *, step: int, scope: Any
    ) -> dict[str, Any]:
        value = super()._record_observation(adapter, step=step, scope=scope)
        self._record_training_observation(adapter, global_step=step)
        return value

    def _record_training_observation(self, adapter: Any, *, global_step: int) -> None:
        method = getattr(adapter, "evaluate_training", None)
        if not callable(method):
            raise FullModelTrainingError("plan090_training_diagnostic_required")
        receipt = method(self.training_dataset)
        if (
            not isinstance(receipt, Mapping)
            or set(receipt)
            != {
                "raw_logits",
                "gradient_access",
                "training_state_unchanged",
                "training_identity_sha256",
            }
            or receipt.get("gradient_access") is not False
            or receipt.get("training_state_unchanged") is not True
            or receipt.get("training_identity_sha256")
            != self.state["training_identity_sha256"]
            or not isinstance(receipt.get("raw_logits"), Mapping)
        ):
            raise FullModelTrainingError("plan090_training_diagnostic_receipt_invalid")
        scope = self.state["current_scope"]
        observation = build_training_observation(
            self.training_dataset,
            receipt["raw_logits"],
            global_step=global_step,
            scope=TrainableScope.from_value(scope),
            policy=self.comparison_policy,
            report_threshold=self.report_threshold,
        )
        observation["objective_diagnostic"] = build_objective_diagnostic(
            self.training_dataset,
            receipt["raw_logits"],
            self.state["plan090"]["run_spec"]["recipe"]["objective"][
                "component_weights"
            ],
        )
        previous_rows = self.state["plan090"]["training_observations"]
        observation["comparisons"] = {
            "base": "incumbent"
            if not previous_rows
            else _direction(
                observation["comparison_value"],
                previous_rows[0]["comparison_value"],
            ),
            "previous": None
            if not previous_rows
            else _direction(
                observation["comparison_value"],
                previous_rows[-1]["comparison_value"],
            ),
        }
        identifier = (
            "train-base-step-000000"
            if global_step == 0
            else (
                "train-observation-attempt-"
                f"{int(self.state['artifact_generation']):03d}-"
                f"step-{global_step:06d}"
            )
        )
        reference = self.artifact_store.write_observation(identifier, observation)
        previous_rows.append(
            {
                "observation_id": identifier,
                "global_step": global_step,
                "comparison_value": observation["comparison_value"],
                "observation": reference,
            }
        )

    def _augment_validation_observation(
        self, observation: dict[str, Any], *, raw_logits: Mapping[str, Any]
    ) -> dict[str, Any]:
        observation["objective_diagnostic"] = build_objective_diagnostic(
            self.validation_dataset,
            raw_logits,
            self.state["plan090"]["run_spec"]["recipe"]["objective"][
                "component_weights"
            ],
        )
        return observation

    def _additional_retained_checkpoint_ids(self) -> set[str]:
        return set(self.state["plan090"]["recovery_proven_checkpoints"])

    def _validate_adapter(self, adapter: Any) -> None:
        method = getattr(adapter, "plan090_runtime_identity", None)
        if not callable(method):
            raise FullModelTrainingError("plan090_real_adapter_required")
        identity = validate_runtime_identity(
            method(), run_spec=self.state["plan090"]["run_spec"]
        )
        bound = self.state["plan090"]["runtime_identity"]
        if bound is None:
            self.state["plan090"]["runtime_identity"] = identity
        elif bound != identity:
            raise FullModelTrainingError("plan090_runtime_identity_drifted")

    def _accept_update_receipt(self, value: Any, *, step: int, scope: Any) -> None:
        change = value.get("parameter_change") if isinstance(value, Mapping) else None
        precision = (
            value.get("precision_receipt") if isinstance(value, Mapping) else None
        )
        if (
            not isinstance(change, Mapping)
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
            raise FullModelTrainingError("plan090_update_parameter_change_invalid")
        validated_precision = validate_precision_receipt(
            precision,
            run_spec=self.state["plan090"]["run_spec"],
            scope=scope.as_dict(),
        )
        self.state["plan090"]["precision_receipt"] = validated_precision
        super()._accept_update_receipt(
            {
                key: item
                for key, item in value.items()
                if key not in {"parameter_change", "precision_receipt"}
            },
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
        plan090 = value.get("plan090")
        if (
            not isinstance(plan090, Mapping)
            or set(plan090)
            != {
                "freeze",
                "freeze_sha256",
                "run_spec",
                "launch_budget_snapshot",
                "runtime_identity",
                "process_identity",
                "training_observations",
                "precision_receipt",
                "recovery_proven_checkpoints",
            }
            or validate_freeze(plan090.get("freeze")) != self.state["plan090"]["freeze"]
            or plan090.get("freeze_sha256") != self.state["plan090"]["freeze_sha256"]
            or validate_run_spec(plan090.get("run_spec"), freeze=plan090.get("freeze"))
            != self.state["plan090"]["run_spec"]
            or validate_budget_snapshot(plan090.get("launch_budget_snapshot"))
            != self.state["plan090"]["launch_budget_snapshot"]
            or plan090.get("runtime_identity")
            != self.state["plan090"]["runtime_identity"]
        ):
            raise FullModelTrainingError("plan090_checkpoint_contract_invalid")
        validate_process_identity(plan090.get("process_identity"))
        training_rows = plan090.get("training_observations")
        generation = value.get("artifact_generation")
        current_step = value.get("current_step")
        if (
            not isinstance(training_rows, list)
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 0
            or current_step != 1
        ):
            raise FullModelTrainingError("plan090_checkpoint_contract_invalid")
        expected_ids = [
            "train-base-step-000000",
            (f"train-observation-attempt-{generation:03d}-step-{current_step:06d}"),
        ]
        if len(training_rows) != 2:
            raise FullModelTrainingError("plan090_checkpoint_contract_invalid")
        for index, row in enumerate(training_rows):
            if (
                not isinstance(row, Mapping)
                or set(row)
                != {
                    "observation_id",
                    "global_step",
                    "comparison_value",
                    "observation",
                }
                or row.get("observation_id") != expected_ids[index]
                or row.get("global_step") != index
                or not isinstance(row.get("comparison_value"), (int, float))
                or isinstance(row["comparison_value"], bool)
                or not math.isfinite(float(row["comparison_value"]))
                or row.get("observation")
                != self.artifact_store.verify_observation(expected_ids[index])
            ):
                raise FullModelTrainingError("plan090_checkpoint_contract_invalid")
            observation = self.artifact_store.read_observation(expected_ids[index])
            if (
                observation.get("global_step") != index
                or observation.get("scope") != value.get("current_scope")
                or observation.get("comparison_value") != row.get("comparison_value")
                or observation.get("cohort", {}).get("split") != "train"
                or observation.get("cohort", {}).get("identity_sha256")
                != value.get("training_identity_sha256")
            ):
                raise FullModelTrainingError("plan090_checkpoint_contract_invalid")
        validate_precision_receipt(
            plan090.get("precision_receipt"),
            run_spec=plan090["run_spec"],
            scope=value.get("current_scope"),
        )
        recovered = plan090.get("recovery_proven_checkpoints")
        if not isinstance(recovered, Mapping) or any(
            not isinstance(identifier, str) or not identifier or not _sha256(digest)
            for identifier, digest in recovered.items()
        ):
            raise FullModelTrainingError("plan090_checkpoint_contract_invalid")
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
            "run_id": self.state["plan090"]["run_spec"]["run_id"],
            "freeze_sha256": self.state["plan090"]["freeze_sha256"],
            "launch_budget_snapshot": json.loads(
                json.dumps(self.state["plan090"]["launch_budget_snapshot"])
            ),
            "artifact_namespace": self.state["plan090"]["run_spec"][
                "artifact_namespace"
            ],
            "actual_trainable_scope": self.state["current_scope"],
            "validation_observations": json.loads(
                json.dumps(self.state["observations"])
            ),
            "training_observations": json.loads(
                json.dumps(self.state["plan090"]["training_observations"])
            ),
            "selection": json.loads(json.dumps(self.state["selection"])),
            "latest_checkpoint_id": self.state["latest_checkpoint_id"],
            "runtime_identity": json.loads(
                json.dumps(self.state["plan090"]["runtime_identity"])
            ),
            "precision_receipt": json.loads(
                json.dumps(self.state["plan090"]["precision_receipt"])
            ),
            "claims": {
                "real_training_run": bool(self.state["updates"]),
                "clean_exact_base_start": True,
                "seed_sensitive_stability_tested": False,
                "route_search": False,
                "pre_result_rubric_bound": True,
                "result_assessed": False,
                "product_go": False,
                "m3_c2_evidence": False,
                "unseen_evidence": False,
            },
        }


def validate_runtime_identity(
    value: Any, *, run_spec: Mapping[str, Any]
) -> dict[str, Any]:
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
        "provider_pod_id",
        "provider_pod_name",
        "precision_controls",
        "repeat_semantics",
    }
    spec = run_spec
    environment = value.get("environment") if isinstance(value, Mapping) else None
    observed_environment = validate_environment_receipt(environment)
    expected_repeat_semantics = {
        "recipe_seed_metadata": int(spec["recipe"]["seed"]),
        "data_ordering": "sorted_candidates_and_frozen_pair_order",
        "data_shuffle": False,
        "attention_dropout": 0.0,
        "active_dropout_modules": [],
        "seed_sensitive_consumers": [],
        "seed_sensitive_stability_tested": False,
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or value.get("runtime_kind") != RUNTIME_KIND
        or value.get("gpu_name") != "NVIDIA L40S"
        or value.get("gpu_count") != 1
        or value.get("model_repository") != MODEL_REPOSITORY
        or value.get("model_revision") != MODEL_REVISION
        or value.get("peft") is not False
        or value.get("quantized_training") is not False
        or value.get("snapshot_content_sha256") != SNAPSHOT_CONTENT_SHA256
        or value.get("recipe_sha256")
        != sha256_bytes(canonical_json_bytes(spec["recipe"]))
        or value.get("parameter_inventory_sha256") != spec["parameter_inventory_sha256"]
        or value.get("torch_version") != "2.8.0+cu128"
        or value.get("transformers_version") != "4.52.3"
        or observed_environment.get("container_image")
        != "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
        or observed_environment.get("python_version") != "3.12.3"
        or observed_environment.get("gpu_names") != ["NVIDIA L40S"]
        or observed_environment.get("torch_cuda_runtime") != value.get("cuda_version")
        or not _identifier(value.get("provider_pod_id"))
        or not _identifier(value.get("provider_pod_name"))
        or not value["provider_pod_name"].startswith("rondo-plan090-")
        or value.get("precision_controls")
        != {
            "float32_matmul_precision": "highest",
            "cuda_matmul_allow_tf32": False,
            "cudnn_allow_tf32": False,
            "autocast_enabled": False,
        }
        or value.get("repeat_semantics") != expected_repeat_semantics
        or any(
            not isinstance(value.get(key), int)
            or isinstance(value[key], bool)
            or value[key] <= 0
            for key in ("parameter_tensors", "parameter_elements")
        )
    ):
        raise FullModelTrainingError("plan090_runtime_identity_invalid")
    return json.loads(json.dumps(value))


def validate_precision_receipt(
    value: Any,
    *,
    run_spec: Mapping[str, Any],
    scope: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "parameter_dtype",
        "model_parameter_dtypes",
        "selected_parameter_dtypes",
        "gradient_dtypes",
        "forward_output_dtypes",
        "optimizer_state_dtypes",
        "save_parameter_dtype",
        "save_verification",
        "controls",
        "precision_contract",
    }:
        raise FullModelTrainingError("plan090_precision_receipt_invalid")
    expected = {
        "bfloat16": "torch.bfloat16",
        "float32": "torch.float32",
    }[run_spec["recipe"]["parameter_dtype"]]
    optimizer_dtypes = set(value.get("optimizer_state_dtypes", []))
    if (
        value.get("schema") != PRECISION_RECEIPT_SCHEMA
        or value.get("parameter_dtype") != run_spec["recipe"]["parameter_dtype"]
        or value.get("model_parameter_dtypes") != [expected]
        or value.get("selected_parameter_dtypes")
        != {name: expected for name in scope["parameter_names"]}
        or value.get("gradient_dtypes")
        != {name: expected for name in scope["parameter_names"]}
        or expected not in value.get("forward_output_dtypes", [])
        or value.get("save_parameter_dtype") != expected
        or value.get("save_verification")
        != "fail_closed_safetensors_header_before_checkpoint_publish_and_load"
        or value.get("controls")
        != {
            "float32_matmul_precision": "highest",
            "cuda_matmul_allow_tf32": False,
            "cudnn_allow_tf32": False,
            "autocast_enabled": False,
        }
        or value.get("precision_contract") != run_spec["precision_contract"]
        or not optimizer_dtypes
        or (expected == "torch.float32" and optimizer_dtypes != {expected})
        or (
            expected == "torch.bfloat16"
            and not optimizer_dtypes <= {"torch.bfloat16", "torch.float32"}
        )
    ):
        raise FullModelTrainingError("plan090_precision_receipt_invalid")
    return json.loads(json.dumps(value))


def build_objective_diagnostic(
    dataset: Any,
    raw_logits: Mapping[str, Any],
    component_weights: Mapping[str, Any],
) -> dict[str, Any]:
    if set(component_weights) != {"binary", "boundary", "within_pass"}:
        raise FullModelTrainingError("plan090_objective_diagnostic_invalid")
    try:
        binary = [
            binary_reference(
                float(raw_logits[candidate_id]), dataset.label(candidate_id)
            )[0]
            for candidate_id in sorted(dataset.supervision)
        ]
        pair_losses: dict[str, list[float]] = {"boundary": [], "within_pass": []}
        for pair_id in sorted(dataset.pairs):
            pair = dataset.pairs[pair_id]
            kind = str(pair["kind"])
            if kind not in pair_losses:
                raise KeyError(kind)
            pair_losses[kind].append(
                pair_reference(
                    float(raw_logits[str(pair["preferred_candidate_id"])]),
                    float(raw_logits[str(pair["dispreferred_candidate_id"])]),
                )[0]
            )
        components = {
            "binary": sum(binary) / len(binary),
            **{kind: sum(values) / len(values) for kind, values in pair_losses.items()},
        }
        weighted = sum(
            float(component_weights[kind]) * components[kind] for kind in components
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise FullModelTrainingError("plan090_objective_diagnostic_invalid") from exc
    if not math.isfinite(weighted) or any(
        not math.isfinite(value) for value in components.values()
    ):
        raise FullModelTrainingError("plan090_objective_diagnostic_invalid")
    return {
        "schema": OBJECTIVE_DIAGNOSTIC_SCHEMA,
        "component_mean_loss": components,
        "component_weights": {
            key: float(component_weights[key]) for key in sorted(component_weights)
        },
        "weighted_mean_loss": weighted,
        "gradient_access": False,
    }


def _direction(candidate: float, base: float) -> str:
    if candidate > base:
        return "better"
    if candidate < base:
        return "worse"
    return "equal"


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "CONTROLLER_SCHEMA",
    "OBJECTIVE_DIAGNOSTIC_SCHEMA",
    "Plan090ConfirmationController",
    "SUMMARY_SCHEMA",
    "build_objective_diagnostic",
    "validate_precision_receipt",
    "validate_runtime_identity",
]
