"""Checkpoint-first Route O continuous-training controller for Plan 094."""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contract import (
    MODEL_REPOSITORY,
    MODEL_REVISION,
    FullModelTrainingError,
    canonical_json_bytes,
    sha256_bytes,
)
from .objective import binary_reference, pair_reference
from .plan081_contract import ComparisonPolicy, ControlPlan, TrainableScope
from .plan081_controller import (
    ControllerEvidenceProfile,
    _ContinuousTrainingControllerCore,
    _adapter_training_state_codec,
    _artifact_id,
    _assert_fresh_exact_base,
    _restore_adapter_checkpoint,
    _validate_training_state,
)
from .plan081_observation import build_training_observation
from .plan082_controller import validate_process_identity
from .plan082_environment import validate_environment_receipt
from .plan090_artifacts import Plan090ArtifactStore
from .plan090_contract import frozen_contract as plan090_frozen_contract
from .plan090_controller import (
    OBJECTIVE_DIAGNOSTIC_SCHEMA,
    Plan090ConfirmationController,
    validate_precision_receipt,
)
from .plan094_adapter import RUNTIME_KIND
from .plan094_artifacts import EVALUATION_RESULT_SCHEMA, Plan094ArtifactStore
from .plan094_contract import (
    PLAN090_SOURCE_CHECKPOINT_BYTES,
    PLAN090_SOURCE_CHECKPOINT_ID,
    PLAN090_SOURCE_CHECKPOINT_SHA256,
    assess_material,
    decide_stop,
    freeze_sha256,
    validate_assessment,
    validate_budget_snapshot,
    validate_freeze,
    validate_run_spec,
)


CONTROLLER_SCHEMA = "rondo-publication-critic-plan094-controller-state-v1"
SUMMARY_SCHEMA = "rondo-publication-critic-plan094-training-summary-v1"
REAL_RUNTIME_PROFILE = ControllerEvidenceProfile(
    controller_schema=CONTROLLER_SCHEMA,
    evidence_kind="torch_real_route_o_checkpoint_first_continuous",
    research_candidate_eligible=False,
    real_quality_claim=True,
)


class Plan094ContinuousTrainingController(_ContinuousTrainingControllerCore):
    """Two-phase update/checkpoint then evaluation controller.

    The immutable checkpoint contains selection state through the previous
    evaluated point and declares its own evaluation pending.  A small atomic
    overlay binds the checkpoint hash to train/validation observations,
    material assessment, selection roles, and the stop decision.  Resume
    always deep-qualifies the checkpoint and then idempotently replays or
    creates that overlay before another update is allowed.
    """

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
                "plan094_controller_profile_override_forbidden"
            )
        if not isinstance(kwargs.get("artifact_store"), Plan094ArtifactStore):
            raise FullModelTrainingError("plan094_artifact_store_required")
        contract = validate_freeze(freeze)
        spec = validate_run_spec(run_spec, freeze=contract)
        launch_budget = validate_budget_snapshot(launch_budget_snapshot)
        super().__init__(**kwargs, evidence_profile=REAL_RUNTIME_PROFILE)
        self.state["plan094"] = {
            "freeze": contract,
            "freeze_sha256": freeze_sha256(contract),
            "run_spec": spec,
            "launch_budget_snapshot": launch_budget,
            "runtime_identity": None,
            "process_identity": None,
            "base_training_observation": None,
            "pending_checkpoint": None,
            "evaluation_overlays": [],
            "checkpoint_roles": {},
            "recovery_proven_checkpoints": {},
            "resume_verification": None,
            "precision_receipts": {},
            "stop_decision": None,
            "terminal_deferred_for_recovery": False,
            "continuation_origin": None,
        }

    @property
    def plan094_store(self) -> Plan094ArtifactStore:
        return self.artifact_store

    def begin_process(self, identity: Mapping[str, Any]) -> None:
        self.state["plan094"]["process_identity"] = validate_process_identity(
            identity
        )

    def initialize(self, adapter: Any) -> dict[str, Any]:
        if self.state["status"] != "created" or self.state["base"] is not None:
            raise FullModelTrainingError("plan094_controller_already_initialized")
        if self.state["plan094"]["process_identity"] is None:
            raise FullModelTrainingError("plan094_process_identity_required")
        self._validate_adapter(adapter)
        self._require_input_identities()
        self._bind_training_state_codec(adapter)
        _assert_fresh_exact_base(adapter)
        scope = TrainableScope.from_value(self.state["current_scope"])
        adapter.configure_trainable_scope(scope)
        adapter.assert_trainable_scope(scope)
        validation = self._base_observation(adapter, scope)
        training = self._evaluate_training(adapter, global_step=0, scope=scope)
        validation_reference = self.plan094_store.write_observation(
            "base-step-000000", validation
        )
        training_reference = self.plan094_store.write_observation(
            "train-base-step-000000", training
        )
        self.state["base"] = {
            "role": "matching_exact_base",
            "model": {"repository": MODEL_REPOSITORY, "revision": MODEL_REVISION},
            "validation_observation": validation_reference,
            "training_observation": training_reference,
            "comparison_value": validation["comparison_value"],
        }
        self.state["plan094"]["base_training_observation"] = training_reference
        self.state["selection"] = {
            "base": "matching_exact_base",
            "previous_checkpoint_id": None,
            "training_best_checkpoint_id": None,
            "checkpoint_backed_best_id": None,
            "material_candidate_checkpoint_id": None,
            "latest_checkpoint_id": None,
        }
        if (
            self.state["plan094"]["run_spec"]["continuation_mode"]
            == "exact_base_rebuild_of_route_o_step_1"
        ):
            self.state["plan094"]["continuation_origin"] = {
                "mode": "exact_base_rebuild_of_route_o_step_1",
                "source_global_step": 0,
                "matching_base_observation_id": "base-step-000000",
            }
        self.state["status"] = "paused"
        return self.archive_summary()

    def import_plan090_checkpoint(
        self,
        adapter: Any,
        *,
        source_store: Plan090ArtifactStore,
        checkpoint_id: str = PLAN090_SOURCE_CHECKPOINT_ID,
    ) -> dict[str, Any]:
        """Guarded full-state import of the retained Plan 090 checkpoint."""

        if (
            self.state["status"] != "paused"
            or self.state["current_step"] != 0
            or self.state["updates"]
            or self.state["observations"]
            or self.state["plan094"]["continuation_origin"] is not None
            or checkpoint_id != PLAN090_SOURCE_CHECKPOINT_ID
            or self.state["plan094"]["run_spec"]["continuation_mode"]
            != "guarded_plan090_full_checkpoint_import"
        ):
            raise FullModelTrainingError("plan094_source_import_not_allowed")
        self._validate_adapter(adapter)
        checkpoint = source_store.verify_checkpoint(checkpoint_id)
        if (
            checkpoint["content_sha256"] != PLAN090_SOURCE_CHECKPOINT_SHA256
            or checkpoint["bytes"] != PLAN090_SOURCE_CHECKPOINT_BYTES
            or checkpoint["metadata"].get("training_state_codec")
            != "plan090-torch-state-v1"
        ):
            raise FullModelTrainingError("plan094_source_checkpoint_identity_mismatch")
        codec_id, _writer, state_reader = _adapter_training_state_codec(adapter)
        controller_state, training_state, model_root = source_store.read_checkpoint(
            checkpoint_id, state_reader=state_reader
        )
        self._validate_plan090_source_controller(
            source_store=source_store,
            controller_state=controller_state,
            checkpoint_id=checkpoint_id,
        )
        _validate_training_state(training_state)
        if training_state["data"] != {"macro_update": 1}:
            raise FullModelTrainingError("plan094_source_data_cursor_invalid")
        self._require_matching_source_base(source_store, controller_state)
        scope = TrainableScope.from_value(self.state["current_scope"])
        _restore_adapter_checkpoint(
            adapter,
            model_root=model_root,
            scope=scope,
            training_state=training_state,
        )
        if codec_id != self.state["training_state_codec"]:
            raise FullModelTrainingError("plan094_training_state_codec_mismatch")
        self.state["updates"] = [
            json.loads(json.dumps(controller_state["updates"][0]))
        ]
        self.state["plan094"]["precision_receipts"]["1"] = json.loads(
            json.dumps(controller_state["plan090"]["precision_receipt"])
        )
        self.state["current_step"] = 1
        self.state["latest_checkpoint_id"] = checkpoint_id
        self.state["plan094"]["continuation_origin"] = {
            "mode": "guarded_plan090_full_checkpoint_import",
            "checkpoint_id": checkpoint_id,
            "content_sha256": checkpoint["content_sha256"],
            "bytes": checkpoint["bytes"],
            "source_controller_schema": controller_state["schema"],
            "source_training_state_codec": checkpoint["metadata"][
                "training_state_codec"
            ],
            "source_runtime_identity": controller_state["plan090"][
                "runtime_identity"
            ],
        }
        self.state["plan094"]["pending_checkpoint"] = {
            "checkpoint_id": checkpoint_id,
            "content_sha256": checkpoint["content_sha256"],
            "bytes": checkpoint["bytes"],
            "global_step": 1,
            "source_external": True,
        }
        self.state["status"] = "evaluation_pending"
        source_observations = self._qualify_source_evaluation(
            adapter, source_store, controller_state
        )
        self._ensure_pending_evaluated(
            adapter, precomputed_observations=source_observations
        )
        return self.archive_summary()

    def run(self, adapter: Any, *, stop_after: int | None = None) -> dict[str, Any]:
        if self.state["base"] is None:
            raise FullModelTrainingError("plan094_controller_not_initialized")
        deferred_on_entry = bool(
            self.state["plan094"]["terminal_deferred_for_recovery"]
        )
        if (
            deferred_on_entry
            and self.state["plan094"]["resume_verification"] is None
        ):
            raise FullModelTrainingError("plan094_terminal_resume_required")
        self._validate_adapter(adapter)
        self._require_input_identities()
        if self.state["status"] == "evaluation_pending":
            self._ensure_pending_evaluated(adapter)
        if self.state["status"] == "terminal":
            if stop_after not in {None, self.state["current_step"]}:
                raise FullModelTrainingError("plan094_controller_terminal")
            return self.archive_summary()
        if (
            self.state["plan094"]["terminal_deferred_for_recovery"]
            and self.state["plan094"]["resume_verification"] is None
        ):
            return self.archive_summary()
        if self.state["status"] != "paused":
            raise FullModelTrainingError("plan094_controller_state_invalid")
        current = int(self.state["current_step"])
        maximum = self.control_plan.maximum_updates
        target = maximum if stop_after is None else stop_after
        if (
            not isinstance(target, int)
            or isinstance(target, bool)
            or target < current
            or target > maximum
        ):
            raise FullModelTrainingError("plan094_stop_point_invalid")
        scope = TrainableScope.from_value(self.state["current_scope"])
        adapter.assert_trainable_scope(scope)
        for step in range(current + 1, target + 1):
            if (
                step == maximum
                and not self.state["plan094"]["recovery_proven_checkpoints"]
                and self.state["plan094"]["resume_verification"] is None
            ):
                raise FullModelTrainingError(
                    "plan094_fresh_process_recovery_required_before_final_step"
                )
            self._run_checkpoint_first_step(adapter, step=step, scope=scope)
            if (
                self.state["status"] == "terminal"
                or self.state["plan094"]["terminal_deferred_for_recovery"]
            ):
                break
        return self.archive_summary()

    def _run_checkpoint_first_step(
        self, adapter: Any, *, step: int, scope: TrainableScope
    ) -> None:
        committed = json.loads(json.dumps(self.state))
        checkpoint_id = _artifact_id(
            "checkpoint", int(self.state["artifact_generation"]), step
        )
        published = False
        qualified = False
        try:
            self.state["status"] = "running"
            receipt = adapter.apply_update(step, scope, self.training_dataset)
            self._accept_update_receipt(receipt, step=step, scope=scope)
            self._complete_resume_verification_before_checkpoint(
                continued_to_step=step
            )
            self.state["updates"].append(json.loads(json.dumps(receipt)))
            self.state["current_step"] = step
            training_state = adapter.capture_training_state()
            _validate_training_state(training_state)
            if training_state["data"] != receipt["data_cursor"]:
                raise FullModelTrainingError(
                    "plan094_data_cursor_checkpoint_mismatch"
                )
            codec_id, state_writer, _reader = _adapter_training_state_codec(adapter)
            if codec_id != self.state["training_state_codec"]:
                raise FullModelTrainingError("plan094_training_state_codec_mismatch")
            pending = {
                "checkpoint_id": checkpoint_id,
                "content_sha256": None,
                "bytes": None,
                "global_step": step,
                "source_external": False,
            }
            self.state["latest_checkpoint_id"] = checkpoint_id
            self.state["plan094"]["pending_checkpoint"] = pending
            self.state["status"] = "evaluation_pending"
            checkpoint_state = json.loads(json.dumps(self.state))
            checkpoint = self.plan094_store.save_checkpoint(
                checkpoint_id,
                model_saver=adapter.save_model,
                training_state=training_state,
                controller_state=checkpoint_state,
                metadata={
                    "global_step": step,
                    "scope": scope.as_dict(),
                    "artifact_role": "full_recovery_checkpoint_evaluation_pending",
                    "training_state_codec": codec_id,
                    "evaluation_order": "checkpoint_first",
                },
                state_writer=state_writer,
            )
            published = True
            pending["content_sha256"] = checkpoint["content_sha256"]
            pending["bytes"] = checkpoint["bytes"]
            checkpoint_state["plan094"]["pending_checkpoint"] = json.loads(
                json.dumps(pending)
            )
            if (
                self.plan094_store.read_checkpoint_controller_state(checkpoint_id)
                != checkpoint_state
            ):
                # The immutable state deliberately contains a null hash/size because
                # those values are created by its containing manifest.  Verify the
                # semantically relevant pre-publication state instead.
                stored = self.plan094_store.read_checkpoint_controller_state(
                    checkpoint_id
                )
                stored_pending = stored.get("plan094", {}).get(
                    "pending_checkpoint", {}
                )
                expected_without_manifest = {
                    **pending,
                    "content_sha256": None,
                    "bytes": None,
                }
                if stored_pending != expected_without_manifest:
                    raise FullModelTrainingError(
                        "plan094_checkpoint_controller_state_invalid"
                    )
                checkpoint_state = stored
            self._qualify_checkpoint(
                checkpoint_id,
                adapter=adapter,
                scope=scope,
                expected_codec_id=codec_id,
                expected_controller_state=checkpoint_state,
                expected_data_cursor=receipt["data_cursor"],
            )
            qualified = True
            self.state = checkpoint_state
            self.state["plan094"]["pending_checkpoint"] = pending
            self.state["status"] = "evaluation_pending"
            self._ensure_pending_evaluated(adapter)
        except BaseException:
            if qualified:
                if self.state["plan094"].get("pending_checkpoint") is None:
                    self.state["plan094"]["pending_checkpoint"] = json.loads(
                        json.dumps(pending)
                    )
                self.state["status"] = "evaluation_pending"
            elif published:
                self.plan094_store.discard_unqualified_checkpoint(checkpoint_id)
                self.state = committed
                self.state["status"] = "recovery_required"
            else:
                self.state = committed
                self.state["status"] = "recovery_required"
            raise

    def _ensure_pending_evaluated(
        self,
        adapter: Any,
        *,
        precomputed_observations: tuple[dict[str, Any], dict[str, Any]] | None = None,
    ) -> None:
        pending = self.state["plan094"]["pending_checkpoint"]
        if self.state["status"] != "evaluation_pending" or not isinstance(
            pending, Mapping
        ):
            raise FullModelTrainingError("plan094_pending_evaluation_invalid")
        checkpoint_id = str(pending["checkpoint_id"])
        if self.plan094_store.has_evaluation_result(checkpoint_id):
            result = self.plan094_store.read_evaluation_result(checkpoint_id)
        else:
            result = self._build_evaluation_overlay(
                adapter,
                pending=pending,
                precomputed_observations=precomputed_observations,
            )
            self.plan094_store.publish_evaluation_result(
                checkpoint_id,
                checkpoint_content_sha256=str(pending["content_sha256"]),
                value=result,
            )
        self._reconcile_evaluation_overlay(result)
        if pending.get("source_external") is not True:
            if self.plan094_store.has_retention_completion(checkpoint_id):
                self.plan094_store.verify_retention_complete(checkpoint_id)
            else:
                self._apply_plan094_retention()
                self.plan094_store.mark_retention_complete(checkpoint_id)

    def _build_evaluation_overlay(
        self,
        adapter: Any,
        *,
        pending: Mapping[str, Any],
        precomputed_observations: tuple[dict[str, Any], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        step = int(pending["global_step"])
        scope = TrainableScope.from_value(self.state["current_scope"])
        if precomputed_observations is None:
            validation = self._evaluate(adapter, global_step=step, scope=scope)
            training = self._evaluate_training(adapter, global_step=step, scope=scope)
        else:
            validation, training = precomputed_observations
        base_validation = self.plan094_store.read_observation("base-step-000000")
        assessment = assess_material(
            self.state["plan094"]["freeze"],
            base_validation=base_validation,
            candidate_validation=validation,
            candidate_eligible=pending.get("source_external") is not True,
        )
        prior_results = self._evaluation_results_from_state()
        assessments = [
            result["assessment"] for result in prior_results
        ] + [assessment]
        stop = decide_stop(self.state["plan094"]["freeze"], assessments)
        roles = self._roles_after(prior_results + [{
            "checkpoint": dict(pending),
            "validation_observation": validation,
            "training_observation": training,
            "assessment": assessment,
        }])
        return {
            "schema": EVALUATION_RESULT_SCHEMA,
            "freeze_sha256": self.state["plan094"]["freeze_sha256"],
            "run_spec_sha256": sha256_bytes(
                canonical_json_bytes(self.state["plan094"]["run_spec"])
            ),
            "checkpoint": json.loads(json.dumps(pending)),
            "evaluation_process": json.loads(
                json.dumps(self.state["plan094"]["process_identity"])
            ),
            "validation_observation": validation,
            "training_observation": training,
            "assessment": assessment,
            "stop_decision": stop,
            "checkpoint_roles_after": roles,
            "claims": {
                "checkpoint_complete_before_evaluation": True,
                "checkpoint_deep_qualified_before_evaluation": True,
                "validation_gradient_access": False,
                "training_diagnostic_gradient_access": False,
                "unseen_evidence": False,
                "product_go": False,
            },
        }

    def _reconcile_evaluation_overlay(self, value: Mapping[str, Any]) -> None:
        pending = self.state["plan094"]["pending_checkpoint"]
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != EVALUATION_RESULT_SCHEMA
            or value.get("freeze_sha256")
            != self.state["plan094"]["freeze_sha256"]
            or value.get("run_spec_sha256")
            != sha256_bytes(
                canonical_json_bytes(self.state["plan094"]["run_spec"])
            )
            or value.get("checkpoint") != pending
            or validate_process_identity(value.get("evaluation_process"))
            != value["evaluation_process"]
            or value.get("claims")
            != {
                "checkpoint_complete_before_evaluation": True,
                "checkpoint_deep_qualified_before_evaluation": True,
                "validation_gradient_access": False,
                "training_diagnostic_gradient_access": False,
                "unseen_evidence": False,
                "product_go": False,
            }
        ):
            raise FullModelTrainingError("plan094_evaluation_overlay_invalid")
        base = self.plan094_store.read_observation("base-step-000000")
        assessment = assess_material(
            self.state["plan094"]["freeze"],
            base_validation=base,
            candidate_validation=value["validation_observation"],
            candidate_eligible=pending.get("source_external") is not True,
        )
        if validate_assessment(value.get("assessment")) != assessment:
            raise FullModelTrainingError("plan094_evaluation_overlay_invalid")
        prior_results = self._evaluation_results_from_state()
        checkpoint_id = str(pending["checkpoint_id"])
        if (
            self.state["observations"]
            and self.state["observations"][-1].get("checkpoint_id") == checkpoint_id
            and self.state["plan094"]["evaluation_overlays"][-1:] == [checkpoint_id]
        ):
            if value != prior_results[-1]:
                raise FullModelTrainingError("plan094_evaluation_overlay_invalid")
            self.state["plan094"]["pending_checkpoint"] = None
            self._apply_stop_status(value["stop_decision"])
            return
        expected_stop = decide_stop(
            self.state["plan094"]["freeze"],
            [result["assessment"] for result in prior_results] + [assessment],
        )
        expected_roles = self._roles_after(prior_results + [value])
        if (
            value.get("stop_decision") != expected_stop
            or value.get("checkpoint_roles_after") != expected_roles
        ):
            raise FullModelTrainingError("plan094_evaluation_overlay_invalid")
        self.state["observations"].append(
            {
                "global_step": int(pending["global_step"]),
                "checkpoint_id": checkpoint_id,
                "checkpoint_content_sha256": pending["content_sha256"],
                "source_external": pending["source_external"],
                "assessment_content_sha256": assessment["content_sha256"],
                "evaluation_result": {
                    "relative": (
                        f"evaluation-results/{checkpoint_id}/payload/evaluation.json"
                    )
                },
            }
        )
        self.state["plan094"]["evaluation_overlays"].append(checkpoint_id)
        self.state["plan094"]["checkpoint_roles"] = expected_roles
        self.state["plan094"]["stop_decision"] = expected_stop
        self.state["plan094"]["pending_checkpoint"] = None
        self.state["selection"] = self._selection_from_roles(
            expected_roles, checkpoint_id
        )
        self._apply_stop_status(expected_stop)

    def _apply_stop_status(self, stop: Mapping[str, Any]) -> None:
        deferred = bool(stop["terminal"]) and not bool(
            self.state["plan094"]["recovery_proven_checkpoints"]
        )
        self.state["plan094"]["terminal_deferred_for_recovery"] = deferred
        self.state["status"] = (
            "terminal" if stop["terminal"] and not deferred else "paused"
        )

    def _roles_after(
        self,
        results: list[Mapping[str, Any]],
        *,
        recovered: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not results:
            return {}
        latest = results[-1]
        material = next(
            (
                row
                for row in results
                if row["assessment"]["passed"] is True
            ),
            None,
        )
        checkpoint_best = max(
            results,
            key=lambda row: (
                float(row["assessment"]["deltas"]["raw_boundary"]),
                float(row["assessment"]["deltas"]["roc_auc"]),
            ),
        )
        training_best = max(
            results,
            key=lambda row: float(row["training_observation"]["comparison_value"]),
        )
        if recovered is None:
            recovered = self.state["plan094"]["recovery_proven_checkpoints"]
        recovery_id = next(reversed(recovered), None) if recovered else None
        turning: list[str] = []
        previous_signature: tuple[Any, ...] | None = None
        for row in results:
            signature = _discrete_signature(row["assessment"])
            if previous_signature is not None and signature != previous_signature:
                turning.append(str(row["checkpoint"]["checkpoint_id"]))
            previous_signature = signature
        turning = turning[-self.control_plan.turning_point_limit :]
        return {
            "material_candidate": (
                material["checkpoint"]["checkpoint_id"]
                if material is not None
                else None
            ),
            "latest": latest["checkpoint"]["checkpoint_id"],
            "fresh_process_recovery": recovery_id,
            "checkpoint_backed_best": checkpoint_best["checkpoint"][
                "checkpoint_id"
            ],
            "training_best": training_best["checkpoint"]["checkpoint_id"],
            "turning_points": turning,
        }

    def _selection_from_roles(
        self, roles: Mapping[str, Any], checkpoint_id: str
    ) -> dict[str, Any]:
        return {
            "base": "matching_exact_base",
            "previous_checkpoint_id": (
                self.state["observations"][-2]["checkpoint_id"]
                if len(self.state["observations"]) >= 2
                else None
            ),
            "training_best_checkpoint_id": roles.get("training_best"),
            "checkpoint_backed_best_id": roles.get("checkpoint_backed_best"),
            "material_candidate_checkpoint_id": roles.get("material_candidate"),
            "latest_checkpoint_id": checkpoint_id,
        }

    def _apply_plan094_retention(self) -> None:
        pending = self.state["plan094"]["pending_checkpoint"]
        if pending is not None:
            raise FullModelTrainingError("plan094_pending_checkpoint_prune_forbidden")
        owned = set(self.plan094_store.verified_checkpoint_ids())
        roles = self.state["plan094"]["checkpoint_roles"]
        ordered = [
            roles.get("material_candidate") or roles.get("checkpoint_backed_best"),
            roles.get("latest"),
            roles.get("fresh_process_recovery"),
            *roles.get("turning_points", []),
            roles.get("checkpoint_backed_best"),
            roles.get("training_best"),
        ]
        limit = int(
            self.state["plan094"]["freeze"]["retention"][
                "maximum_owned_full_checkpoints"
            ]
        )
        keep: list[str] = []
        for checkpoint_id in ordered:
            if (
                isinstance(checkpoint_id, str)
                and checkpoint_id in owned
                and checkpoint_id not in keep
            ):
                keep.append(checkpoint_id)
            if len(keep) == limit:
                break
        if owned and not keep:
            keep.append(max(owned))
        self.plan094_store.prune(
            keep_snapshot_ids=set(),
            keep_checkpoint_ids=set(keep),
            prune_checkpoints=True,
        )

    @classmethod
    def resume(
        cls,
        *,
        freeze: Mapping[str, Any],
        run_spec: Mapping[str, Any],
        route_contract: Mapping[str, Any],
        control_plan: ControlPlan,
        comparison_policy: ComparisonPolicy,
        training_dataset: Any,
        validation_dataset: Any,
        artifact_store: Plan094ArtifactStore,
        adapter: Any,
        checkpoint_id: str,
        process_identity: Mapping[str, Any],
        budget_snapshot: Mapping[str, Any],
        report_threshold: float = 0.5,
    ) -> "Plan094ContinuousTrainingController":
        artifact_store.recover_incomplete_staging()
        if not artifact_store.is_latest_checkpoint(checkpoint_id):
            raise FullModelTrainingError("plan094_resume_checkpoint_not_latest")
        checkpoint = artifact_store.verify_checkpoint(checkpoint_id)
        codec_id, _writer, state_reader = _adapter_training_state_codec(adapter)
        if checkpoint["metadata"].get("training_state_codec") != codec_id:
            raise FullModelTrainingError("plan094_training_state_codec_mismatch")
        controller_state, training_state, model_root = artifact_store.read_checkpoint(
            checkpoint_id, state_reader=state_reader
        )
        controller = cls(
            freeze=freeze,
            run_spec=run_spec,
            launch_budget_snapshot=budget_snapshot,
            route_contract=route_contract,
            control_plan=control_plan,
            initial_scope=TrainableScope.from_value(
                controller_state.get("current_scope")
            ),
            comparison_policy=comparison_policy,
            training_dataset=training_dataset,
            validation_dataset=validation_dataset,
            artifact_store=artifact_store,
            report_threshold=report_threshold,
        )
        controller._validate_adapter(adapter)
        controller._bind_training_state_codec(adapter)
        current_runtime = json.loads(
            json.dumps(controller.state["plan094"]["runtime_identity"])
        )
        controller._validate_resumed_state(
            controller_state,
            checkpoint_id,
            current_runtime_identity=current_runtime,
        )
        earlier_budget = validate_budget_snapshot(
            controller_state["plan094"].get("launch_budget_snapshot")
        )
        current_budget = validate_budget_snapshot(budget_snapshot)
        if (
            earlier_budget["stage_b_baseline_balance_usd"]
            != current_budget["stage_b_baseline_balance_usd"]
            or earlier_budget["stage_b_baseline_known_unsettled_usd"]
            != current_budget["stage_b_baseline_known_unsettled_usd"]
            or current_budget["conservative_task_cost_usd"] + 1e-12
            < earlier_budget["conservative_task_cost_usd"]
        ):
            raise FullModelTrainingError("plan094_budget_history_invalid")
        _validate_training_state(training_state)
        _assert_fresh_exact_base(adapter)
        scope = TrainableScope.from_value(controller_state["current_scope"])
        _restore_adapter_checkpoint(
            adapter,
            model_root=model_root,
            scope=scope,
            training_state=training_state,
        )
        source_process = validate_process_identity(
            controller_state["plan094"]["process_identity"]
        )
        current_process = validate_process_identity(process_identity)
        if (
            source_process["instance_id"] == current_process["instance_id"]
            or (
                source_process["hostname"] == current_process["hostname"]
                and source_process["pid"] == current_process["pid"]
            )
        ):
            raise FullModelTrainingError("plan094_resume_requires_new_process")
        controller.state = json.loads(json.dumps(controller_state))
        controller.state["plan094"]["process_identity"] = current_process
        controller.state["plan094"]["runtime_identity"] = current_runtime
        controller.state["plan094"]["launch_budget_snapshot"] = current_budget
        controller.state["plan094"]["resume_verification"] = {
            "source_checkpoint_id": checkpoint_id,
            "source_checkpoint_content_sha256": checkpoint["content_sha256"],
            "source_process": source_process,
            "resume_process": current_process,
            "source_runtime_identity": json.loads(
                json.dumps(controller_state["plan094"]["runtime_identity"])
            ),
            "resume_runtime_identity": json.loads(json.dumps(current_runtime)),
            "continued_to_step": None,
        }
        controller.state["resume_count"] = int(
            controller.state["resume_count"]
        ) + 1
        controller.state["artifact_generation"] = (
            artifact_store.reserve_artifact_generation(
                after_generation=int(controller.state["artifact_generation"])
            )
        )
        pending = controller.state["plan094"]["pending_checkpoint"]
        if not isinstance(pending, Mapping):
            raise FullModelTrainingError("plan094_pending_evaluation_invalid")
        controller.state["plan094"]["pending_checkpoint"] = {
            **dict(pending),
            "content_sha256": checkpoint["content_sha256"],
            "bytes": checkpoint["bytes"],
        }
        controller.state["status"] = "evaluation_pending"
        controller._ensure_pending_evaluated(adapter)
        return controller

    def _validate_resumed_state(
        self,
        value: Mapping[str, Any],
        checkpoint_id: str,
        *,
        current_runtime_identity: Mapping[str, Any],
    ) -> None:
        plan094 = value.get("plan094")
        pending = plan094.get("pending_checkpoint") if isinstance(plan094, Mapping) else None
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != CONTROLLER_SCHEMA
            or value.get("route_contract_sha256")
            != self.state["route_contract_sha256"]
            or value.get("training_identity_sha256")
            != self.state["training_identity_sha256"]
            or value.get("validation_identity_sha256")
            != self.state["validation_identity_sha256"]
            or value.get("control_plan") != self.control_plan.as_dict()
            or value.get("comparison_policy") != self.comparison_policy.as_dict()
            or value.get("training_state_codec")
            != self.state["training_state_codec"]
            or value.get("status") != "evaluation_pending"
            or value.get("latest_checkpoint_id") != checkpoint_id
            or not isinstance(plan094, Mapping)
            or validate_freeze(plan094.get("freeze"))
            != self.state["plan094"]["freeze"]
            or validate_run_spec(
                plan094.get("run_spec"), freeze=plan094.get("freeze")
            )
            != self.state["plan094"]["run_spec"]
            or validate_budget_snapshot(plan094.get("launch_budget_snapshot"))
            != plan094.get("launch_budget_snapshot")
            or validate_runtime_identity(
                plan094.get("runtime_identity"),
                run_spec=plan094.get("run_spec"),
            )
            != plan094.get("runtime_identity")
            or _runtime_continuation_core(plan094.get("runtime_identity"))
            != _runtime_continuation_core(current_runtime_identity)
            or not isinstance(pending, Mapping)
            or pending.get("checkpoint_id") != checkpoint_id
            or pending.get("source_external") is not False
            or pending.get("content_sha256") is not None
            or pending.get("bytes") is not None
            or value.get("current_step") != pending.get("global_step")
            or value.get("current_step") != len(value.get("updates", []))
        ):
            raise FullModelTrainingError("plan094_checkpoint_controller_state_invalid")
        self._validate_resumed_history(value)

    def _validate_resumed_history(self, value: Mapping[str, Any]) -> None:
        plan094 = value["plan094"]
        observations = value.get("observations")
        overlay_ids = plan094.get("evaluation_overlays")
        if (
            not isinstance(observations, list)
            or not isinstance(overlay_ids, list)
            or len(observations) != len(overlay_ids)
            or any(
                not isinstance(row, Mapping)
                or not isinstance(row.get("global_step"), int)
                or row["global_step"] >= value["current_step"]
                for row in observations
            )
            or [row.get("checkpoint_id") for row in observations] != overlay_ids
            or [row["global_step"] for row in observations]
            != sorted(set(row["global_step"] for row in observations))
        ):
            raise FullModelTrainingError("plan094_checkpoint_history_invalid")
        results = [
            self.plan094_store.read_evaluation_result(identifier)
            for identifier in overlay_ids
        ]
        if results:
            expected_roles = self._roles_after(
                results,
                recovered=plan094.get("recovery_proven_checkpoints", {}),
            )
            expected_stop = decide_stop(
                plan094["freeze"], [row["assessment"] for row in results]
            )
            if (
                plan094.get("checkpoint_roles") != expected_roles
                or plan094.get("stop_decision") != expected_stop
            ):
                raise FullModelTrainingError("plan094_checkpoint_history_invalid")
        elif plan094.get("checkpoint_roles") or plan094.get("stop_decision") is not None:
            raise FullModelTrainingError("plan094_checkpoint_history_invalid")

    def _complete_resume_verification_before_checkpoint(
        self, *, continued_to_step: int
    ) -> None:
        verification = self.state["plan094"]["resume_verification"]
        if verification is None:
            return
        if verification.get("continued_to_step") is not None:
            return
        if continued_to_step != int(self.state["current_step"]) + 1:
            raise FullModelTrainingError("plan094_resume_continue_step_invalid")
        verification["continued_to_step"] = continued_to_step
        self.state["plan094"]["recovery_proven_checkpoints"][
            verification["source_checkpoint_id"]
        ] = verification["source_checkpoint_content_sha256"]
        results = self._evaluation_results_from_state()
        if results:
            roles = self._roles_after(results)
            self.state["plan094"]["checkpoint_roles"] = roles
            self.state["selection"] = self._selection_from_roles(
                roles, str(results[-1]["checkpoint"]["checkpoint_id"])
            )

    def _validate_plan090_source_controller(
        self,
        *,
        source_store: Plan090ArtifactStore,
        controller_state: Mapping[str, Any],
        checkpoint_id: str,
    ) -> None:
        plan090 = controller_state.get("plan090")
        if not isinstance(plan090, Mapping):
            raise FullModelTrainingError("plan094_source_controller_invalid")
        legacy = Plan090ConfirmationController(
            freeze=plan090.get("freeze"),
            run_spec=plan090.get("run_spec"),
            launch_budget_snapshot=plan090.get("launch_budget_snapshot"),
            route_contract=self.route_contract,
            control_plan=ControlPlan.from_value(controller_state["control_plan"]),
            initial_scope=TrainableScope.from_value(controller_state["current_scope"]),
            comparison_policy=ComparisonPolicy.from_value(
                controller_state["comparison_policy"]
            ),
            training_dataset=self.training_dataset,
            validation_dataset=self.validation_dataset,
            artifact_store=source_store,
            report_threshold=float(controller_state["report_threshold"]),
        )
        legacy.state["plan090"]["runtime_identity"] = json.loads(
            json.dumps(plan090.get("runtime_identity"))
        )
        legacy._accept_resumed_state(
            controller_state,
            checkpoint_id,
            training_state_codec="plan090-torch-state-v1",
        )
        contract = plan090_frozen_contract()
        if (
            plan090.get("freeze") != contract
            or plan090.get("run_spec", {}).get("run_id") != "bf16-seed-20260902"
            or controller_state.get("current_step") != 1
        ):
            raise FullModelTrainingError("plan094_source_controller_invalid")

    def _require_matching_source_base(
        self,
        source_store: Plan090ArtifactStore,
        controller_state: Mapping[str, Any],
    ) -> None:
        source_base = source_store.read_observation("base-step-000000")
        matching_base = self.plan094_store.read_observation("base-step-000000")
        if _observation_comparable_core(source_base) != _observation_comparable_core(
            matching_base
        ):
            raise FullModelTrainingError("plan094_source_matching_base_mismatch")
        source_training = source_store.read_observation("train-base-step-000000")
        matching_training = self.plan094_store.read_observation(
            "train-base-step-000000"
        )
        if _observation_comparable_core(
            source_training
        ) != _observation_comparable_core(matching_training):
            raise FullModelTrainingError("plan094_source_matching_base_mismatch")
        if controller_state["base"]["comparison_value"] != source_base[
            "comparison_value"
        ]:
            raise FullModelTrainingError("plan094_source_matching_base_mismatch")

    def _qualify_source_evaluation(
        self,
        adapter: Any,
        source_store: Plan090ArtifactStore,
        controller_state: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        scope = TrainableScope.from_value(self.state["current_scope"])
        validation = self._evaluate(adapter, global_step=1, scope=scope)
        training = self._evaluate_training(adapter, global_step=1, scope=scope)
        source_validation = source_store.read_observation(
            controller_state["observations"][-1]["observation_id"]
        )
        source_training = source_store.read_observation(
            controller_state["plan090"]["training_observations"][-1][
                "observation_id"
            ]
        )
        if (
            _observation_comparable_core(validation)
            != _observation_comparable_core(source_validation)
            or _observation_comparable_core(training)
            != _observation_comparable_core(source_training)
        ):
            raise FullModelTrainingError("plan094_source_checkpoint_score_mismatch")
        return validation, training

    def _evaluation_results_from_state(self) -> list[dict[str, Any]]:
        return [
            self.plan094_store.read_evaluation_result(checkpoint_id)
            for checkpoint_id in self.state["plan094"]["evaluation_overlays"]
        ]

    def _evaluate_training(
        self, adapter: Any, *, global_step: int, scope: TrainableScope
    ) -> dict[str, Any]:
        method = getattr(adapter, "evaluate_training", None)
        if not callable(method):
            raise FullModelTrainingError("plan094_training_diagnostic_required")
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
            raise FullModelTrainingError(
                "plan094_training_diagnostic_receipt_invalid"
            )
        observation = build_training_observation(
            self.training_dataset,
            receipt["raw_logits"],
            global_step=global_step,
            scope=scope,
            policy=self.comparison_policy,
            report_threshold=self.report_threshold,
        )
        observation["objective_diagnostic"] = _build_objective_diagnostic(
            self.training_dataset,
            receipt["raw_logits"],
            self.state["plan094"]["run_spec"]["recipe"]["objective"][
                "component_weights"
            ],
        )
        return observation

    def _augment_validation_observation(
        self, observation: dict[str, Any], *, raw_logits: Mapping[str, Any]
    ) -> dict[str, Any]:
        observation["objective_diagnostic"] = _build_objective_diagnostic(
            self.validation_dataset,
            raw_logits,
            self.state["plan094"]["run_spec"]["recipe"]["objective"][
                "component_weights"
            ],
        )
        return observation

    def _accept_update_receipt(self, value: Any, *, step: int, scope: Any) -> None:
        change = value.get("parameter_change") if isinstance(value, Mapping) else None
        precision = value.get("precision_receipt") if isinstance(value, Mapping) else None
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
            or float(change["maximum_absolute_change"]) <= 0.0
        ):
            raise FullModelTrainingError("plan094_update_parameter_change_invalid")
        validated_precision = validate_precision_receipt(
            precision,
            run_spec={
                "recipe": self.state["plan094"]["run_spec"]["recipe"],
                "precision_contract": self.state["plan094"]["run_spec"][
                    "precision_contract"
                ],
            },
            scope=scope.as_dict(),
        )
        self.state["plan094"]["precision_receipts"][str(step)] = validated_precision
        super()._accept_update_receipt(
            {
                key: item
                for key, item in value.items()
                if key not in {"parameter_change", "precision_receipt"}
            },
            step=step,
            scope=scope,
        )

    def _validate_adapter(self, adapter: Any) -> None:
        method = getattr(adapter, "plan094_runtime_identity", None)
        if not callable(method):
            raise FullModelTrainingError("plan094_real_adapter_required")
        identity = validate_runtime_identity(
            method(), run_spec=self.state["plan094"]["run_spec"]
        )
        bound = self.state["plan094"]["runtime_identity"]
        if bound is None:
            self.state["plan094"]["runtime_identity"] = identity
        elif bound != identity:
            raise FullModelTrainingError("plan094_runtime_identity_drifted")

    def archive_summary(self) -> dict[str, Any]:
        return {
            "schema": SUMMARY_SCHEMA,
            "status": self.state["status"],
            "global_step": self.state["current_step"],
            "freeze_sha256": self.state["plan094"]["freeze_sha256"],
            "run_kind": self.state["plan094"]["run_spec"]["run_kind"],
            "launch_budget_snapshot": copy.deepcopy(
                self.state["plan094"]["launch_budget_snapshot"]
            ),
            "continuation_origin": copy.deepcopy(
                self.state["plan094"]["continuation_origin"]
            ),
            "pending_checkpoint": copy.deepcopy(
                self.state["plan094"]["pending_checkpoint"]
            ),
            "evaluated_checkpoints": copy.deepcopy(
                self.state["observations"]
            ),
            "selection": copy.deepcopy(self.state["selection"]),
            "checkpoint_roles": copy.deepcopy(
                self.state["plan094"]["checkpoint_roles"]
            ),
            "stop_decision": copy.deepcopy(
                self.state["plan094"]["stop_decision"]
            ),
            "recovery_proven_checkpoints": copy.deepcopy(
                self.state["plan094"]["recovery_proven_checkpoints"]
            ),
            "runtime_identity": copy.deepcopy(
                self.state["plan094"]["runtime_identity"]
            ),
            "claims": {
                "checkpoint_first_evaluation": True,
                "training_and_evaluation_recovery_separate": True,
                "matching_exact_base": self.state["base"] is not None,
                "real_training_run": bool(self.state["updates"]),
                "unseen_evidence": False,
                "product_go": False,
                "m3_c2_evidence": False,
            },
        }


def _runtime_continuation_core(value: Mapping[str, Any]) -> dict[str, Any]:
    """Exclude only task-owned provider binding from exact resume identity."""

    result = json.loads(json.dumps(value))
    result.pop("provider_pod_id", None)
    result.pop("provider_pod_name", None)
    return result


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
        "continuation_semantics",
    }
    environment = value.get("environment") if isinstance(value, Mapping) else None
    observed_environment = validate_environment_receipt(environment)
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
        or value.get("snapshot_content_sha256")
        != "18d9edf7132d9c5e13bb0e59e3c2c6a42f82007fa17de464e20783755a171360"
        or value.get("recipe_sha256")
        != sha256_bytes(canonical_json_bytes(run_spec["recipe"]))
        or value.get("parameter_inventory_sha256")
        != run_spec["parameter_inventory_sha256"]
        or value.get("parameter_tensors") != 311
        or value.get("parameter_elements") != 1_720_577_024
        or value.get("torch_version") != "2.8.0+cu128"
        or value.get("transformers_version") != "4.52.3"
        or observed_environment.get("container_image")
        != "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
        or observed_environment.get("python_version") != "3.12.3"
        or observed_environment.get("gpu_names") != ["NVIDIA L40S"]
        or observed_environment.get("torch_cuda_runtime") != value.get("cuda_version")
        or not _identifier(value.get("provider_pod_id"))
        or not _identifier(value.get("provider_pod_name"))
        or not value["provider_pod_name"].startswith("rondo-plan094-")
        or value.get("precision_controls")
        != {
            "float32_matmul_precision": "highest",
            "cuda_matmul_allow_tf32": False,
            "cudnn_allow_tf32": False,
            "autocast_enabled": False,
        }
        or value.get("continuation_semantics")
        != {
            "data_ordering": "sorted_candidates_and_frozen_pair_order",
            "data_shuffle": False,
            "attention_dropout": 0.0,
            "active_dropout_modules": [],
            "seed_sensitive_consumers": [],
            "seed_sensitive_stability_tested": False,
        }
    ):
        raise FullModelTrainingError("plan094_runtime_identity_invalid")
    return json.loads(json.dumps(value))


def _build_objective_diagnostic(
    dataset: Any,
    raw_logits: Mapping[str, Any],
    component_weights: Mapping[str, Any],
) -> dict[str, Any]:
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
            pair_losses[kind].append(
                pair_reference(
                    float(raw_logits[str(pair["preferred_candidate_id"])]),
                    float(raw_logits[str(pair["dispreferred_candidate_id"])]),
                )[0]
            )
        components = {
            "binary": sum(binary) / len(binary),
            **{
                kind: sum(values) / len(values)
                for kind, values in pair_losses.items()
            },
        }
        weighted = sum(
            float(component_weights[kind]) * components[kind]
            for kind in components
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise FullModelTrainingError("plan094_objective_diagnostic_invalid") from exc
    return {
        "schema": OBJECTIVE_DIAGNOSTIC_SCHEMA,
        "component_mean_loss": components,
        "component_weights": {
            key: float(component_weights[key]) for key in sorted(component_weights)
        },
        "weighted_mean_loss": weighted,
        "gradient_access": False,
    }


def _observation_comparable_core(value: Mapping[str, Any]) -> dict[str, Any]:
    excluded = {"comparisons", "evidence"}
    result = {
        key: json.loads(json.dumps(item))
        for key, item in value.items()
        if key not in excluded
    }
    scope = result.get("scope")
    if isinstance(scope, Mapping):
        result["scope"] = {
            key: item for key, item in scope.items() if key != "scope_id"
        }
    return result


def _discrete_signature(assessment: Mapping[str, Any]) -> tuple[Any, ...]:
    candidate = assessment["candidate"]
    best = assessment["best_operating"]["candidate"]
    return (
        round(float(candidate["roc_auc"]) * 1428.0),
        round(float(candidate["boundary_strict_win_rate"]) * 19.0),
        round(float(candidate["within_pass_strict_win_rate"]) * 7.0),
        tuple(sorted(best["confusion"].items())),
    )


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "CONTROLLER_SCHEMA",
    "Plan094ContinuousTrainingController",
    "SUMMARY_SCHEMA",
    "validate_runtime_identity",
]
