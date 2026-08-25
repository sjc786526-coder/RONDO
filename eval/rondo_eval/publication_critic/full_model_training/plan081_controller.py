"""Continuous, resumable control flow for the Plan 081 local fake route."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from typing import Any

from .contract import (
    MODEL_REPOSITORY,
    MODEL_REVISION,
    FullModelTrainingError,
    canonical_json_bytes,
    sha256_bytes,
)
from .data import PortableTrainingDataset
from .plan066_data import ValidationDataset
from .plan081_artifacts import Plan081ArtifactStore
from .plan081_contract import (
    ComparisonPolicy,
    ControlPlan,
    TrainableScope,
    compare_values,
    validate_route_contract,
)
from .plan081_observation import (
    build_validation_observation,
    training_identity_sha256,
    validation_identity_sha256,
)


CONTROLLER_SCHEMA = "rondo-publication-critic-plan081-controller-state-v1"


class ContinuousTrainingController:
    """Drive updates and observations through a small explicit adapter seam.

    Plan 081 intentionally supports only ``fixture_fake`` evidence.  A future
    authorized real-training task may reuse the state schema, but it must add a
    separately reviewed runtime adapter and candidate-eligibility boundary.
    """

    def __init__(
        self,
        *,
        route_contract: Mapping[str, Any],
        control_plan: ControlPlan,
        initial_scope: TrainableScope,
        comparison_policy: ComparisonPolicy,
        training_dataset: PortableTrainingDataset,
        validation_dataset: ValidationDataset,
        artifact_store: Plan081ArtifactStore,
        report_threshold: float = 0.5,
    ) -> None:
        validated = validate_route_contract(route_contract)
        if (
            not isinstance(control_plan, ControlPlan)
            or not isinstance(initial_scope, TrainableScope)
            or not isinstance(comparison_policy, ComparisonPolicy)
        ):
            raise FullModelTrainingError("plan081_controller_contract_invalid")
        control_plan = ControlPlan.from_value(control_plan.as_dict())
        initial_scope = TrainableScope.from_value(initial_scope.as_dict())
        comparison_policy = ComparisonPolicy.from_value(comparison_policy.as_dict())
        if (
            not isinstance(report_threshold, (int, float))
            or isinstance(report_threshold, bool)
            or not math.isfinite(float(report_threshold))
            or not 0.0 <= float(report_threshold) <= 1.0
        ):
            raise FullModelTrainingError("plan081_report_threshold_invalid")
        self.route_contract = validated
        self.control_plan = control_plan
        self.comparison_policy = comparison_policy
        self.training_dataset = training_dataset
        self.validation_dataset = validation_dataset
        self.artifact_store = artifact_store
        self.report_threshold = float(report_threshold)
        self.state: dict[str, Any] = {
            "schema": CONTROLLER_SCHEMA,
            "route_contract_sha256": sha256_bytes(canonical_json_bytes(validated)),
            "validation_identity_sha256": validation_identity_sha256(
                validation_dataset
            ),
            "training_identity_sha256": training_identity_sha256(training_dataset),
            "control_plan": control_plan.as_dict(),
            "comparison_policy": comparison_policy.as_dict(),
            "report_threshold": self.report_threshold,
            "evidence_kind": "fixture_fake",
            "status": "created",
            "current_step": 0,
            "current_scope": initial_scope.as_dict(),
            "scope_history": [
                {"effective_before_update": 1, "scope": initial_scope.as_dict()}
            ],
            "scope_decisions": [],
            "updates": [],
            "observations": [],
            "base": None,
            "selection": _empty_selection(),
            "turning_points": [],
            "latest_checkpoint_id": None,
            "resume_count": 0,
            "artifact_generation": 0,
        }

    def schedule_scope_expansion(self, scope: TrainableScope) -> dict[str, Any]:
        """Register the next update's expansion after observing current dynamics."""

        if not isinstance(scope, TrainableScope):
            raise FullModelTrainingError("plan081_trainable_scope_invalid")
        scope = TrainableScope.from_value(scope.as_dict())
        current = int(self.state["current_step"])
        if (
            self.state["status"] != "paused"
            or current <= 0
            or current >= self.control_plan.maximum_updates
            or not self.state["observations"]
            or self.state["observations"][-1]["global_step"] != current
            or any(
                decision["before_update"] > current
                for decision in self.state["scope_decisions"]
            )
        ):
            raise FullModelTrainingError("plan081_scope_decision_not_allowed")
        previous = TrainableScope.from_value(self.state["current_scope"])
        scope.require_expansion_of(previous)
        decision = {
            "decided_after_observation_id": self.state["observations"][-1][
                "observation_id"
            ],
            "before_update": current + 1,
            "scope": scope.as_dict(),
        }
        self.state["scope_decisions"].append(decision)
        return json.loads(json.dumps(decision))

    def initialize(self, adapter: Any) -> dict[str, Any]:
        if self.state["status"] != "created" or self.state["base"] is not None:
            raise FullModelTrainingError("plan081_controller_already_initialized")
        self._require_input_identities()
        scope = TrainableScope.from_value(self.state["current_scope"])
        adapter.configure_trainable_scope(scope)
        adapter.assert_trainable_scope(scope)
        observation = self._evaluate(adapter, global_step=0, scope=scope)
        observation["comparisons"] = {"base": "incumbent", "previous": None, "best": None}
        observation["evidence"] = {
            "kind": "fixture_fake",
            "research_candidate_eligible": False,
            "real_quality_claim": False,
        }
        reference = self.artifact_store.write_observation(
            "base-step-000000", observation
        )
        base = {
            "role": "base_incumbent",
            "model": {"repository": MODEL_REPOSITORY, "revision": MODEL_REVISION},
            "snapshot_id": "exact-base-incumbent",
            "observation": reference,
            "comparison_value": observation["comparison_value"],
        }
        self.state["base"] = base
        self.state["selection"] = _selection(
            base=base,
            training_best=None,
            latest=None,
            policy=self.comparison_policy,
        )
        self.state["status"] = "paused"
        return self.archive_summary()

    def run(self, adapter: Any, *, stop_after: int | None = None) -> dict[str, Any]:
        if self.state["base"] is None:
            raise FullModelTrainingError("plan081_controller_not_initialized")
        self._require_input_identities()
        current = int(self.state["current_step"])
        target = self.control_plan.maximum_updates if stop_after is None else stop_after
        if (
            not isinstance(target, int)
            or isinstance(target, bool)
            or target < current
            or target > self.control_plan.maximum_updates
        ):
            raise FullModelTrainingError("plan081_stop_point_invalid")
        if self.state["status"] == "completed" and target != current:
            raise FullModelTrainingError("plan081_controller_completed")
        scope = TrainableScope.from_value(self.state["current_scope"])
        adapter.assert_trainable_scope(scope)
        self.state["status"] = "running"

        for step in range(current + 1, target + 1):
            expanded = False
            decision = _scope_decision_for_step(self.state, step)
            if decision is not None:
                next_scope = TrainableScope.from_value(decision["scope"])
                next_scope.require_expansion_of(scope)
                adapter.configure_trainable_scope(next_scope)
                adapter.assert_trainable_scope(next_scope)
                scope = next_scope
                self.state["current_scope"] = scope.as_dict()
                self.state["scope_history"].append(
                    {"effective_before_update": step, "scope": scope.as_dict()}
                )
                expanded = True

            receipt = adapter.apply_update(step, scope, self.training_dataset)
            self._accept_update_receipt(receipt, step=step, scope=scope)
            self.state["updates"].append(json.loads(json.dumps(receipt)))
            self.state["current_step"] = step

            observation_record: dict[str, Any] | None = None
            if step in self.control_plan.observation_steps:
                observation_record = self._record_observation(
                    adapter, step=step, scope=scope, expanded=expanded
                )
                self._apply_retention(prune_checkpoints=False)

            if step in self.control_plan.checkpoint_steps:
                if observation_record is None:
                    raise FullModelTrainingError("plan081_checkpoint_without_observation")
                checkpoint_id = _artifact_id(
                    "checkpoint", int(self.state["artifact_generation"]), step
                )
                observation_record["checkpoint_id"] = checkpoint_id
                for turning in self.state["turning_points"]:
                    if turning["snapshot_id"] == observation_record["snapshot_id"]:
                        turning["checkpoint_id"] = checkpoint_id
                self.state["latest_checkpoint_id"] = checkpoint_id
                training_state = adapter.capture_training_state()
                _validate_training_state(training_state)
                if training_state["data"] != receipt["data_cursor"]:
                    raise FullModelTrainingError("plan081_data_cursor_checkpoint_mismatch")
                self.artifact_store.save_checkpoint(
                    checkpoint_id,
                    model_saver=adapter.save_model,
                    training_state=training_state,
                    controller_state=self.state,
                    metadata={
                        "global_step": step,
                        "scope": scope.as_dict(),
                        "observation_id": observation_record["observation_id"],
                        "artifact_role": "full_recovery_checkpoint",
                    },
                )
                self._apply_retention(prune_checkpoints=True)

        self.state["status"] = (
            "completed"
            if target == self.control_plan.maximum_updates
            else "paused"
        )
        return self.archive_summary()

    @classmethod
    def resume(
        cls,
        *,
        route_contract: Mapping[str, Any],
        control_plan: ControlPlan,
        comparison_policy: ComparisonPolicy,
        training_dataset: PortableTrainingDataset,
        validation_dataset: ValidationDataset,
        artifact_store: Plan081ArtifactStore,
        adapter: Any,
        checkpoint_id: str,
        report_threshold: float = 0.5,
    ) -> "ContinuousTrainingController":
        artifact_store.recover_incomplete_staging()
        controller_state, training_state, model_root = artifact_store.read_checkpoint(
            checkpoint_id
        )
        if not isinstance(controller_state.get("current_scope"), Mapping):
            raise FullModelTrainingError("plan081_checkpoint_controller_state_invalid")
        scope = TrainableScope.from_value(controller_state["current_scope"])

        controller = cls(
            route_contract=route_contract,
            control_plan=control_plan,
            initial_scope=scope,
            comparison_policy=comparison_policy,
            training_dataset=training_dataset,
            validation_dataset=validation_dataset,
            artifact_store=artifact_store,
            report_threshold=report_threshold,
        )
        controller._accept_resumed_state(controller_state, checkpoint_id)
        fresh_generation = artifact_store.reserve_artifact_generation(
            after_generation=int(controller.state["artifact_generation"])
        )

        # Optimizer param groups are scope-dependent: rebuild and verify the
        # actual inventory before optimizer/scheduler/RNG state is restored.
        adapter.load_model(model_root)
        adapter.configure_trainable_scope(scope)
        adapter.assert_trainable_scope(scope)
        _validate_training_state(training_state)
        if training_state["data"] != controller.state["updates"][-1]["data_cursor"]:
            raise FullModelTrainingError("plan081_data_cursor_checkpoint_mismatch")
        adapter.restore_training_state(training_state)
        adapter.assert_trainable_scope(scope)
        adapter.assert_data_cursor(training_state["data"])

        controller.state["resume_count"] = int(controller.state["resume_count"]) + 1
        controller.state["artifact_generation"] = fresh_generation
        controller.state["status"] = "paused"
        return controller

    def archive_summary(self) -> dict[str, Any]:
        return {
            "schema": "rondo-publication-critic-plan081-local-readiness-summary-v1",
            "status": self.state["status"],
            "global_step": self.state["current_step"],
            "actual_trainable_scope": self.state["current_scope"],
            "scope_decisions": json.loads(json.dumps(self.state["scope_decisions"])),
            "observation_count": len(self.state["observations"]),
            "update_count": len(self.state["updates"]),
            "selection": json.loads(json.dumps(self.state["selection"])),
            "retention": {
                "turning_points": json.loads(json.dumps(self.state["turning_points"])),
                "latest_checkpoint_id": self.state["latest_checkpoint_id"],
            },
            "claims": {
                "fixture_fake_control_flow": True,
                "typed_train_only_input_bound": True,
                "real_model_loaded": False,
                "real_training_run": False,
                "research_candidate_produced": False,
                "product_go": False,
                "m3_c2_evidence": False,
                "unseen_evidence": False,
                "cloud_authorized": False,
            },
        }

    def _evaluate(
        self, adapter: Any, *, global_step: int, scope: TrainableScope
    ) -> dict[str, Any]:
        self._require_input_identities()
        receipt = adapter.evaluate_validation()
        if (
            not isinstance(receipt, Mapping)
            or set(receipt) != {
                "raw_logits",
                "gradient_access",
                "training_state_unchanged",
            }
            or receipt.get("gradient_access") is not False
            or receipt.get("training_state_unchanged") is not True
            or not isinstance(receipt.get("raw_logits"), Mapping)
        ):
            raise FullModelTrainingError("plan081_validation_receipt_invalid")
        return build_validation_observation(
            self.validation_dataset,
            receipt["raw_logits"],
            global_step=global_step,
            scope=scope,
            policy=self.comparison_policy,
            report_threshold=self.report_threshold,
        )

    def _record_observation(
        self, adapter: Any, *, step: int, scope: TrainableScope, expanded: bool
    ) -> dict[str, Any]:
        value = self._evaluate(adapter, global_step=step, scope=scope)
        base = self.state["base"]
        previous = self.state["observations"][-1] if self.state["observations"] else base
        training_best = _training_best_record(self.state)
        best_reference = training_best or base
        comparisons = {
            "base": compare_values(
                value["comparison_value"], base["comparison_value"], self.comparison_policy
            ),
            "previous": compare_values(
                value["comparison_value"],
                previous["comparison_value"],
                self.comparison_policy,
            ),
            "best": compare_values(
                value["comparison_value"],
                best_reference["comparison_value"],
                self.comparison_policy,
            ),
        }
        value["comparisons"] = comparisons
        value["evidence"] = {
            "kind": "fixture_fake",
            "research_candidate_eligible": False,
            "real_quality_claim": False,
        }
        generation = int(self.state["artifact_generation"])
        observation_id = _artifact_id("observation", generation, step)
        snapshot_id = _artifact_id("snapshot", generation, step)
        reference = self.artifact_store.write_observation(observation_id, value)
        self.artifact_store.save_snapshot(
            snapshot_id,
            model_saver=adapter.save_model,
            metadata={
                "global_step": step,
                "scope": scope.as_dict(),
                "observation": reference,
                "artifact_role": "evaluation_snapshot_not_recovery_checkpoint",
            },
        )

        turning_reasons: list[str] = []
        if expanded:
            turning_reasons.append("trainable_scope_expanded")
        if self.state["observations"]:
            prior_trend = self.state["observations"][-1]["comparisons"]["previous"]
            if comparisons["previous"] != prior_trend:
                turning_reasons.append(
                    f"quality_trend_changed_from_{prior_trend}_to_{comparisons['previous']}"
                )
        record = {
            "observation_id": observation_id,
            "artifact_generation": generation,
            "global_step": step,
            "snapshot_id": snapshot_id,
            "checkpoint_id": None,
            "scope": scope.as_dict(),
            "comparison_value": value["comparison_value"],
            "comparisons": comparisons,
            "observation": reference,
            "turning_point_reasons": turning_reasons,
        }
        self.state["observations"].append(record)
        if turning_reasons:
            self.state["turning_points"].append(
                {
                    "observation_id": observation_id,
                    "snapshot_id": snapshot_id,
                    "checkpoint_id": None,
                    "global_step": step,
                    "reasons": turning_reasons,
                }
            )
            self.state["turning_points"] = self.state["turning_points"][
                -self.control_plan.turning_point_limit :
            ]
        self._refresh_selection()
        return record

    def _refresh_selection(self) -> None:
        self.state["selection"] = _selection_from_records(
            base=self.state["base"],
            observations=self.state["observations"],
            policy=self.comparison_policy,
        )

    def _apply_retention(self, *, prune_checkpoints: bool) -> None:
        selection = self.state["selection"]
        snapshot_ids = {
            value
            for value in (
                selection.get("training_best_snapshot_id"),
                selection.get("latest_snapshot_id"),
            )
            if isinstance(value, str)
        }
        checkpoint_ids = {
            value
            for value in (
                self.state.get("latest_checkpoint_id"),
                _checkpoint_for_snapshot(
                    self.state, selection.get("training_best_snapshot_id")
                ),
            )
            if isinstance(value, str)
        }
        for turning in self.state["turning_points"]:
            snapshot_ids.add(turning["snapshot_id"])
            checkpoint_id = _checkpoint_for_snapshot(self.state, turning["snapshot_id"])
            if checkpoint_id is not None:
                checkpoint_ids.add(checkpoint_id)
        self.artifact_store.prune(
            keep_snapshot_ids=snapshot_ids,
            keep_checkpoint_ids=checkpoint_ids,
            prune_checkpoints=prune_checkpoints,
        )

    def _accept_update_receipt(
        self, value: Any, *, step: int, scope: TrainableScope
    ) -> None:
        if (
            not isinstance(value, Mapping)
            or set(value)
            != {
                "global_step",
                "training_split",
                "validation_candidates_consumed",
                "unseen_candidates_consumed",
                "training_identity_sha256",
                "training_candidate_count",
                "training_pair_count",
                "scope",
                "data_cursor",
            }
            or value.get("global_step") != step
            or value.get("training_split") != "train"
            or value.get("validation_candidates_consumed") != 0
            or value.get("unseen_candidates_consumed") != 0
            or value.get("training_identity_sha256")
            != self.state["training_identity_sha256"]
            or value.get("training_candidate_count")
            != len(self.training_dataset.supervision)
            or value.get("training_pair_count") != len(self.training_dataset.pairs)
            or value.get("scope") != scope.as_dict()
            or not isinstance(value.get("data_cursor"), Mapping)
        ):
            raise FullModelTrainingError("plan081_update_receipt_invalid")

    def _accept_resumed_state(
        self, value: Mapping[str, Any], checkpoint_id: str
    ) -> None:
        required = set(self.state)
        if (
            set(value) != required
            or value.get("schema") != CONTROLLER_SCHEMA
            or value.get("route_contract_sha256")
            != self.state["route_contract_sha256"]
            or value.get("validation_identity_sha256")
            != self.state["validation_identity_sha256"]
            or value.get("training_identity_sha256")
            != self.state["training_identity_sha256"]
            or value.get("control_plan") != self.control_plan.as_dict()
            or value.get("comparison_policy") != self.comparison_policy.as_dict()
            or value.get("report_threshold") != self.report_threshold
            or value.get("evidence_kind") != "fixture_fake"
            or value.get("latest_checkpoint_id") != checkpoint_id
            or not isinstance(value.get("base"), Mapping)
            or not isinstance(value.get("selection"), Mapping)
            or not isinstance(value.get("scope_history"), list)
            or not isinstance(value.get("updates"), list)
            or not isinstance(value.get("observations"), list)
            or not isinstance(value.get("turning_points"), list)
            or value.get("current_step") != len(value.get("updates", []))
        ):
            raise FullModelTrainingError("plan081_checkpoint_controller_state_invalid")
        self._validate_resumed_history(value, checkpoint_id)
        self.state = json.loads(json.dumps(value))

    def _require_input_identities(self) -> None:
        if (
            training_identity_sha256(self.training_dataset)
            != self.state["training_identity_sha256"]
            or validation_identity_sha256(self.validation_dataset)
            != self.state["validation_identity_sha256"]
        ):
            raise FullModelTrainingError("plan081_input_identity_drifted")

    def _validate_resumed_history(
        self, value: Mapping[str, Any], checkpoint_id: str
    ) -> None:
        current = value.get("current_step")
        generation = value.get("artifact_generation")
        if (
            not isinstance(current, int)
            or isinstance(current, bool)
            or current <= 0
            or current not in self.control_plan.checkpoint_steps
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 0
            or checkpoint_id != _artifact_id("checkpoint", generation, current)
            or value.get("status") != "running"
            or not isinstance(value.get("resume_count"), int)
            or isinstance(value.get("resume_count"), bool)
            or value["resume_count"] < 0
        ):
            raise FullModelTrainingError("plan081_checkpoint_controller_state_invalid")

        base = value["base"]
        if (
            set(base)
            != {"role", "model", "snapshot_id", "observation", "comparison_value"}
            or base.get("role") != "base_incumbent"
            or base.get("model")
            != {"repository": MODEL_REPOSITORY, "revision": MODEL_REVISION}
            or base.get("snapshot_id") != "exact-base-incumbent"
            or base.get("observation")
            != self.artifact_store.verify_observation("base-step-000000")
        ):
            raise FullModelTrainingError("plan081_checkpoint_base_invalid")
        stored_base = self.artifact_store.read_observation("base-step-000000")
        if (
            stored_base.get("comparison_value") != base.get("comparison_value")
            or stored_base.get("validation", {}).get("identity_sha256")
            != value["validation_identity_sha256"]
        ):
            raise FullModelTrainingError("plan081_checkpoint_base_invalid")

        decisions = value.get("scope_decisions")
        if not isinstance(decisions, list):
            raise FullModelTrainingError("plan081_checkpoint_scope_history_invalid")
        decisions_by_step: dict[int, Mapping[str, Any]] = {}
        for decision in decisions:
            if (
                not isinstance(decision, Mapping)
                or set(decision)
                != {"decided_after_observation_id", "before_update", "scope"}
                or not isinstance(decision.get("before_update"), int)
                or isinstance(decision.get("before_update"), bool)
                or decision["before_update"] <= 1
                or decision["before_update"] > current
                or decision["before_update"] in decisions_by_step
            ):
                raise FullModelTrainingError("plan081_checkpoint_scope_history_invalid")
            scope_decision = TrainableScope.from_value(decision.get("scope"))
            previous_step = decision["before_update"] - 1
            previous_record = next(
                (
                    record
                    for record in value["observations"]
                    if record.get("global_step") == previous_step
                ),
                None,
            )
            if (
                previous_record is None
                or decision.get("decided_after_observation_id")
                != previous_record.get("observation_id")
            ):
                raise FullModelTrainingError("plan081_checkpoint_scope_history_invalid")
            decisions_by_step[decision["before_update"]] = {
                **decision,
                "scope": scope_decision.as_dict(),
            }

        initial_scope = TrainableScope.from_value(value["updates"][0]["scope"])
        expected_history = [
            {"effective_before_update": 1, "scope": initial_scope.as_dict()}
        ]
        active_scope = initial_scope
        for step, receipt in enumerate(value["updates"], start=1):
            if step in decisions_by_step:
                next_scope = TrainableScope.from_value(decisions_by_step[step]["scope"])
                next_scope.require_expansion_of(active_scope)
                active_scope = next_scope
                expected_history.append(
                    {"effective_before_update": step, "scope": active_scope.as_dict()}
                )
            self._accept_update_receipt(receipt, step=step, scope=active_scope)
        if (
            value["scope_history"] != expected_history
            or value["current_scope"] != active_scope.as_dict()
        ):
            raise FullModelTrainingError("plan081_checkpoint_scope_history_invalid")

        expected_steps = [
            step for step in self.control_plan.observation_steps if step <= current
        ]
        if len(value["observations"]) != len(expected_steps):
            raise FullModelTrainingError("plan081_checkpoint_observation_history_invalid")
        for record, step in zip(value["observations"], expected_steps):
            record_generation = record.get("artifact_generation")
            if (
                not isinstance(record_generation, int)
                or isinstance(record_generation, bool)
                or not 0 <= record_generation <= generation
            ):
                raise FullModelTrainingError(
                    "plan081_checkpoint_observation_history_invalid"
                )
            observation_id = _artifact_id("observation", record_generation, step)
            snapshot_id = _artifact_id("snapshot", record_generation, step)
            expected_checkpoint = (
                _artifact_id("checkpoint", record_generation, step)
                if step in self.control_plan.checkpoint_steps
                else None
            )
            if (
                not isinstance(record, Mapping)
                or set(record)
                != {
                    "observation_id",
                    "artifact_generation",
                    "global_step",
                    "snapshot_id",
                    "checkpoint_id",
                    "scope",
                    "comparison_value",
                    "comparisons",
                    "observation",
                    "turning_point_reasons",
                }
                or record.get("observation_id") != observation_id
                or record.get("artifact_generation") != record_generation
                or record.get("global_step") != step
                or record.get("snapshot_id") != snapshot_id
                or record.get("checkpoint_id") != expected_checkpoint
                or record.get("observation")
                != self.artifact_store.verify_observation(observation_id)
            ):
                raise FullModelTrainingError(
                    "plan081_checkpoint_observation_history_invalid"
                )
            stored = self.artifact_store.read_observation(observation_id)
            if (
                stored.get("global_step") != step
                or stored.get("scope") != record.get("scope")
                or stored.get("comparison_value") != record.get("comparison_value")
                or stored.get("comparisons") != record.get("comparisons")
                or stored.get("validation", {}).get("identity_sha256")
                != value["validation_identity_sha256"]
            ):
                raise FullModelTrainingError(
                    "plan081_checkpoint_observation_history_invalid"
                )

        expected_selection = _selection_from_records(
            base=base,
            observations=value["observations"],
            policy=self.comparison_policy,
        )
        if value["selection"] != expected_selection:
            raise FullModelTrainingError("plan081_checkpoint_selection_invalid")
        expected_turning = _turning_points_from_records(
            value["observations"],
            expansion_steps=set(decisions_by_step),
            limit=self.control_plan.turning_point_limit,
        )
        if value["turning_points"] != expected_turning:
            raise FullModelTrainingError("plan081_checkpoint_retention_state_invalid")


def _empty_selection() -> dict[str, Any]:
    return {
        "base_incumbent_snapshot_id": "exact-base-incumbent",
        "training_best_snapshot_id": None,
        "latest_snapshot_id": None,
        "target_candidate_state": "no_improvement",
        "control_candidate_snapshot_id": None,
        "research_candidate_snapshot_id": None,
        "research_candidate_eligible": False,
        "evidence_kind": "fixture_fake",
    }


def _selection(
    *,
    base: Mapping[str, Any],
    training_best: Mapping[str, Any] | None,
    latest: Mapping[str, Any] | None,
    policy: ComparisonPolicy,
) -> dict[str, Any]:
    better = (
        training_best is not None
        and compare_values(
            training_best["comparison_value"], base["comparison_value"], policy
        )
        == "improved"
    )
    return {
        "base_incumbent_snapshot_id": "exact-base-incumbent",
        "training_best_snapshot_id": (
            training_best["snapshot_id"] if training_best is not None else None
        ),
        "latest_snapshot_id": latest["snapshot_id"] if latest is not None else None,
        "target_candidate_state": (
            "better_than_base_candidate_control_path" if better else "no_improvement"
        ),
        "control_candidate_snapshot_id": (
            training_best["snapshot_id"] if better else None
        ),
        # Fake evidence can exercise the branch but never creates a real candidate.
        "research_candidate_snapshot_id": None,
        "research_candidate_eligible": False,
        "evidence_kind": "fixture_fake",
    }


def _selection_from_records(
    *,
    base: Mapping[str, Any],
    observations: list[Mapping[str, Any]],
    policy: ComparisonPolicy,
) -> dict[str, Any]:
    training_best = None
    for record in observations:
        if training_best is None or compare_values(
            record["comparison_value"],
            training_best["comparison_value"],
            policy,
        ) == "improved":
            training_best = record
    return _selection(
        base=base,
        training_best=training_best,
        latest=observations[-1] if observations else None,
        policy=policy,
    )


def _turning_points_from_records(
    observations: list[Mapping[str, Any]],
    *,
    expansion_steps: set[int],
    limit: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, record in enumerate(observations):
        reasons: list[str] = []
        step = int(record["global_step"])
        if step in expansion_steps:
            reasons.append("trainable_scope_expanded")
        if index:
            prior = observations[index - 1]["comparisons"]["previous"]
            current = record["comparisons"]["previous"]
            if current != prior:
                reasons.append(f"quality_trend_changed_from_{prior}_to_{current}")
        if reasons:
            if record.get("turning_point_reasons") != reasons:
                raise FullModelTrainingError("plan081_checkpoint_turning_point_invalid")
            result.append(
                {
                    "observation_id": record["observation_id"],
                    "snapshot_id": record["snapshot_id"],
                    "checkpoint_id": record["checkpoint_id"],
                    "global_step": step,
                    "reasons": reasons,
                }
            )
        elif record.get("turning_point_reasons") != []:
            raise FullModelTrainingError("plan081_checkpoint_turning_point_invalid")
    return result[-limit:]


def _training_best_record(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    snapshot_id = state["selection"].get("training_best_snapshot_id")
    return next(
        (
            record
            for record in state["observations"]
            if record["snapshot_id"] == snapshot_id
        ),
        None,
    )


def _checkpoint_for_snapshot(
    state: Mapping[str, Any], snapshot_id: Any
) -> str | None:
    if not isinstance(snapshot_id, str):
        return None
    return next(
        (
            str(record["checkpoint_id"])
            for record in state["observations"]
            if record["snapshot_id"] == snapshot_id
            and isinstance(record.get("checkpoint_id"), str)
        ),
        None,
    )


def _scope_decision_for_step(
    state: Mapping[str, Any], step: int
) -> Mapping[str, Any] | None:
    return next(
        (
            decision
            for decision in state["scope_decisions"]
            if decision["before_update"] == step
        ),
        None,
    )


def _artifact_id(kind: str, generation: int, step: int) -> str:
    return f"{kind}-attempt-{generation:03d}-step-{step:06d}"


def _validate_training_state(value: Any) -> None:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"optimizer", "scheduler", "rng", "data"}
        or any(not isinstance(value[name], Mapping) for name in value)
    ):
        raise FullModelTrainingError("plan081_training_state_invalid")
