"""Frozen Route O continuous-training and material-candidate contract."""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import (
    MODEL_REPOSITORY,
    MODEL_REVISION,
    FullModelTrainingError,
    canonical_json_bytes,
    sha256_bytes,
)
from .plan081_contract import ComparisonPolicy, ControlPlan, TrainableScope
from .plan087_adapter import validate_adaptive_recipe
from .plan090_contract import (
    BF16_SECONDARY_RUN,
    DATA_BUNDLE_CONTENT_SHA256,
    SCOPE_PARAMETER_ELEMENTS,
    SCOPE_PARAMETER_NAMES,
    SNAPSHOT_CONTENT_SHA256,
    frozen_contract as plan090_frozen_contract,
)


FREEZE_SCHEMA = "rondo-publication-critic-plan094-continuous-freeze-v1"
RUN_SPEC_SCHEMA = "rondo-publication-critic-plan094-run-spec-v1"
ASSESSMENT_SCHEMA = "rondo-publication-critic-plan094-material-assessment-v1"
STOP_DECISION_SCHEMA = "rondo-publication-critic-plan094-stop-decision-v1"
BUDGET_SCHEMA = "rondo-publication-critic-plan094-budget-snapshot-v1"

PLAN090_SOURCE_CHECKPOINT_ID = "checkpoint-attempt-000-step-000001"
PLAN090_SOURCE_CHECKPOINT_SHA256 = (
    "8b4b88b66a88cc50fa10d5f20c575b9a67c6f254f6e26350d38ce4896b949a69"
)
PLAN090_SOURCE_CHECKPOINT_BYTES = 3_591_369_941
PLAN090_SOURCE_CHECKPOINT_PATH = (
    "/workspace/rondo-plan090-20260827-confirm01/formal/"
    "bf16-seed-20260902/artifacts/recovery-checkpoints/"
    + PLAN090_SOURCE_CHECKPOINT_ID
)

ROC_ORDERING_QUANTUM = 1.0 / (34.0 * 21.0)
BOUNDARY_STRICT_QUANTUM = 1.0 / 19.0
WITHIN_PASS_STRICT_QUANTUM = 1.0 / 7.0
BALANCED_ACCURACY_QUANTUM = 1.0 / (2.0 * 34.0)
FALSE_PASS_RATE_QUANTUM = 1.0 / 21.0
OBJECTIVE_DIAGNOSTIC_SCHEMA = (
    "rondo-publication-critic-plan090-objective-diagnostic-v1"
)


def frozen_contract() -> dict[str, Any]:
    """Return the only accepted pre-result Plan 094 research contract."""

    plan090 = plan090_frozen_contract()
    recipe = plan090["recipes"][BF16_SECONDARY_RUN]
    return {
        "schema": FREEZE_SCHEMA,
        "model": {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "snapshot_content_sha256": SNAPSHOT_CONTENT_SHA256,
            "parameter_tensors": 311,
            "parameter_elements": 1_720_577_024,
        },
        "data": {
            "dataset_revision": "v8",
            "bundle_content_sha256": DATA_BUNDLE_CONTENT_SHA256,
            "train_candidate_count": 128,
            "train_pair_count": 58,
            "validation_candidate_count": 55,
            "validation_pair_count": 26,
            "unseen_physically_present": False,
        },
        "runtime": {
            "container_image": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
            "python_version": "3.12.3",
            "torch_version": "2.8.0+cu128",
            "transformers_version": "4.52.3",
            "attention_backend": "sdpa",
            "optimizer": "torch.optim.AdamW",
            "optimizer_fused": True,
            "float32_matmul_precision": "highest",
            "allow_tf32": False,
        },
        "resource": {
            "gpu_name": "NVIDIA L40S",
            "gpu_count": 1,
            "cloud_type": "SECURE",
            "data_center_id": "US-TX-3",
            "network_volume_id": "mwemzrn33y",
            "network_volume_mount_path": "/workspace",
            "initial_network_volume_size_gb": 57,
            "maximum_network_volume_size_gb": 80,
            "maximum_simultaneous_billing_pods": 1,
            "hard_cost_limit_usd": 5.0,
        },
        "scope": {
            "scope_id": "plan094-route-o-layer27-internal-transformations",
            "update_method": "direct_original_parameter_update",
            "parameter_names": list(SCOPE_PARAMETER_NAMES),
            "trainable_parameter_elements": SCOPE_PARAMETER_ELEMENTS,
            "reason": "frozen Route O layer 27 input transformations and internal norms",
        },
        "recipe": recipe,
        "precision_contract": plan090["precision"]["bfloat16"],
        "continuation": {
            "primary": "guarded_plan090_full_checkpoint_import",
            "source_run_id": BF16_SECONDARY_RUN,
            "source_global_step": 1,
            "source_checkpoint_id": PLAN090_SOURCE_CHECKPOINT_ID,
            "source_checkpoint_content_sha256": PLAN090_SOURCE_CHECKPOINT_SHA256,
            "source_checkpoint_bytes": PLAN090_SOURCE_CHECKPOINT_BYTES,
            "source_checkpoint_remote_path": PLAN090_SOURCE_CHECKPOINT_PATH,
            "required_state": [
                "model",
                "optimizer",
                "scheduler",
                "rng",
                "data_cursor",
                "controller_selection",
            ],
            "commissioning_fallback": "exact_base_rebuild_of_route_o_step_1",
            "formal_start": (
                "guarded import only after commissioning proves step 1 to step 2 "
                "and fresh-process step 2 to step 3; otherwise clean exact-base rebuild"
            ),
            "historical_selection_role": "previous_only_reassess_under_plan094_rubric",
        },
        "control_plan": {
            "maximum_updates": 6,
            "observation_steps": [1, 2, 3, 4, 5, 6],
            "checkpoint_steps": [1, 2, 3, 4, 5, 6],
            "turning_point_limit": 2,
        },
        "comparison_policy": {
            "metric": "boundary_pair_mean_margin",
            "direction": "higher_is_better",
            "tolerance": 0.0,
        },
        "report_threshold": 0.5,
        "weak_signal_envelope": {
            "raw_boundary_delta": 0.00390625,
            "projected_boundary_delta": 0.0008611324539553877,
            "raw_within_pass_delta": -0.0033482142857143016,
            "projected_within_pass_delta": 0.0001389426001098884,
            "roc_auc_delta": ROC_ORDERING_QUANTUM,
            "balanced_accuracy_delta": 0.0,
            "best_balanced_accuracy_delta": 0.0,
            "false_pass_rate_delta": 0.0,
            "boundary_strict_win_rate_delta": 0.0,
            "within_pass_strict_win_rate_delta": 0.0,
        },
        "material_rubric": {
            "minimum_raw_boundary_delta": 0.005859375,
            "minimum_projected_boundary_delta": 0.0008611324539553877,
            "minimum_raw_within_pass_delta": -0.00390625,
            "minimum_projected_within_pass_delta": -0.00025,
            "minimum_roc_auc_delta": -ROC_ORDERING_QUANTUM,
            "minimum_balanced_accuracy_delta": 0.0,
            "minimum_best_balanced_accuracy_delta": 0.0,
            "minimum_boundary_raw_improvement_advantage": 4,
            "minimum_raw_logit_span_ratio": 0.9,
            "maximum_false_pass_rate_delta": 0.0,
            "minimum_boundary_strict_delta": 0.0,
            "minimum_within_pass_strict_delta": 0.0,
            "meaningful_events": {
                "minimum_roc_auc_delta": 2.0 * ROC_ORDERING_QUANTUM,
                "minimum_boundary_strict_delta": BOUNDARY_STRICT_QUANTUM,
                "minimum_within_pass_strict_delta": WITHIN_PASS_STRICT_QUANTUM,
                "minimum_frozen_balanced_accuracy_delta": BALANCED_ACCURACY_QUANTUM,
                "minimum_best_balanced_accuracy_delta": BALANCED_ACCURACY_QUANTUM,
                "minimum_best_false_pass_rate_reduction": FALSE_PASS_RATE_QUANTUM,
            },
            "all_companion_checks_required": True,
            "single_bf16_grid_point_is_material": False,
            "single_ordering_is_material": False,
            "projected_only_motion_is_material": False,
            "train_loss_only_is_material": False,
            "no_regression_only_is_material": False,
        },
        "stop_rule": {
            "material_candidate": "stop_after_first_complete_material_checkpoint",
            "early_no_material_step": 4,
            "early_no_material_condition": (
                "three consecutive new evaluated checkpoints have no material event "
                "and never exceed the Plan 090 raw-boundary envelope"
            ),
            "maximum_global_step": 6,
            "maximum_qualified_observation_points": 6,
            "valid_negative_at_maximum": True,
            "infrastructure_failure_is_model_negative": False,
        },
        "retention": {
            "pending_evaluation_is_prunable": False,
            "permanent_small_results": True,
            "maximum_owned_full_checkpoints": 6,
            "roles_in_priority_order": [
                "material_candidate",
                "latest",
                "fresh_process_recovery",
                "turning_point",
                "checkpoint_backed_best",
                "training_best",
            ],
            "role_overlap_reuses_checkpoint": True,
            "source_plan090_checkpoint_is_read_only": True,
        },
        "claims": {
            "validation_is_selection_data": True,
            "independent_cohort_generalization": False,
            "seed_sensitive_stability_tested": False,
            "unseen_evidence": False,
            "product_go": False,
            "m3_c1_or_m3_c2": False,
            "m3_d_unlocked": False,
        },
    }


def validate_freeze(value: Any) -> dict[str, Any]:
    expected = frozen_contract()
    if value != expected:
        raise FullModelTrainingError("plan094_freeze_drifted")
    validate_adaptive_recipe(value["recipe"])
    TrainableScope.from_value(value["scope"])
    ControlPlan.from_value(value["control_plan"])
    ComparisonPolicy.from_value(value["comparison_policy"])
    return json.loads(json.dumps(expected))


def freeze_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(validate_freeze(value)))


def materialize_run_spec(
    freeze: Any,
    *,
    run_kind: str,
    namespace: str,
    source_commit: str,
    source_archive_sha256: str,
    parameter_inventory: Any,
    continuation_mode: str,
) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    inventory = _validate_inventory(parameter_inventory)
    if continuation_mode not in {
        "guarded_plan090_full_checkpoint_import",
        "exact_base_rebuild_of_route_o_step_1",
    }:
        raise FullModelTrainingError("plan094_continuation_mode_invalid")
    value = {
        "schema": RUN_SPEC_SCHEMA,
        "freeze_sha256": freeze_sha256(contract),
        "run_kind": run_kind,
        "artifact_namespace": namespace,
        "source_commit": source_commit,
        "source_archive_sha256": source_archive_sha256,
        "continuation_mode": continuation_mode,
        "recipe": contract["recipe"],
        "scope": contract["scope"],
        "control_plan": contract["control_plan"],
        "comparison_policy": contract["comparison_policy"],
        "report_threshold": contract["report_threshold"],
        "precision_contract": contract["precision_contract"],
        "parameter_inventory_sha256": inventory["inventory_sha256"],
    }
    return validate_run_spec(value, freeze=contract)


def validate_run_spec(value: Any, *, freeze: Any) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    required = {
        "schema",
        "freeze_sha256",
        "run_kind",
        "artifact_namespace",
        "source_commit",
        "source_archive_sha256",
        "continuation_mode",
        "recipe",
        "scope",
        "control_plan",
        "comparison_policy",
        "report_threshold",
        "precision_contract",
        "parameter_inventory_sha256",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or value.get("schema") != RUN_SPEC_SCHEMA
        or value.get("freeze_sha256") != freeze_sha256(contract)
        or value.get("run_kind") not in {"commissioning", "formal"}
        or not _identifier(value.get("artifact_namespace"))
        or not _commit(value.get("source_commit"))
        or not _sha256(value.get("source_archive_sha256"))
        or value.get("continuation_mode")
        not in {
            "guarded_plan090_full_checkpoint_import",
            "exact_base_rebuild_of_route_o_step_1",
        }
        or validate_adaptive_recipe(value.get("recipe")) != contract["recipe"]
        or TrainableScope.from_value(value.get("scope")).as_dict()
        != contract["scope"]
        or ControlPlan.from_value(value.get("control_plan")).as_dict()
        != contract["control_plan"]
        or ComparisonPolicy.from_value(value.get("comparison_policy")).as_dict()
        != contract["comparison_policy"]
        or value.get("report_threshold") != contract["report_threshold"]
        or value.get("precision_contract") != contract["precision_contract"]
        or not _sha256(value.get("parameter_inventory_sha256"))
    ):
        raise FullModelTrainingError("plan094_run_spec_invalid")
    return json.loads(json.dumps(value))


def assess_material(
    freeze: Any,
    *,
    base_validation: Mapping[str, Any],
    candidate_validation: Mapping[str, Any],
    candidate_eligible: bool = True,
) -> dict[str, Any]:
    """Apply the pre-result whole-candidate material rubric."""

    contract = validate_freeze(freeze)
    base = _summarize_observation(base_validation, expected_split="validation")
    candidate = _summarize_observation(
        candidate_validation, expected_split="validation"
    )
    if (
        base["identity_sha256"] != candidate["identity_sha256"]
        or base["global_step"] != 0
        or candidate["global_step"] <= 0
    ):
        raise FullModelTrainingError("plan094_matching_base_required")
    fields = (
        "raw_boundary",
        "projected_boundary",
        "raw_within_pass",
        "projected_within_pass",
        "roc_auc",
        "balanced_accuracy",
        "false_pass_rate",
        "best_balanced_accuracy",
        "boundary_strict_win_rate",
        "within_pass_strict_win_rate",
    )
    deltas = {key: candidate[key] - base[key] for key in fields}
    distribution = _pair_distribution(base_validation, candidate_validation)
    span_ratio = (
        candidate["raw_logit_span"] / base["raw_logit_span"]
        if base["raw_logit_span"] > 0.0
        else 0.0
    )
    best_base = _best_operating_point(base_validation)
    best_candidate = _best_operating_point(candidate_validation)
    meaningful = contract["material_rubric"]["meaningful_events"]
    meaningful_events = {
        "roc_auc_two_orderings": deltas["roc_auc"]
        >= meaningful["minimum_roc_auc_delta"] - 1e-12,
        "boundary_strict_one_pair": deltas["boundary_strict_win_rate"]
        >= meaningful["minimum_boundary_strict_delta"] - 1e-12,
        "within_pass_strict_one_pair": deltas["within_pass_strict_win_rate"]
        >= meaningful["minimum_within_pass_strict_delta"] - 1e-12,
        "frozen_operating_one_cell": deltas["balanced_accuracy"]
        >= meaningful["minimum_frozen_balanced_accuracy_delta"] - 1e-12,
        "best_operating_one_cell": (
            deltas["best_balanced_accuracy"]
            >= meaningful["minimum_best_balanced_accuracy_delta"] - 1e-12
            and best_candidate["false_pass_rate"]
            <= best_base["false_pass_rate"] + 1e-12
        ),
        "best_operating_false_pass_one_cell": (
            best_candidate["balanced_accuracy"]
            >= best_base["balanced_accuracy"] - 1e-12
            and best_base["false_pass_rate"]
            - best_candidate["false_pass_rate"]
            >= meaningful["minimum_best_false_pass_rate_reduction"] - 1e-12
        ),
    }
    rubric = contract["material_rubric"]
    raw_pair_deltas = _raw_pair_deltas(base_validation, candidate_validation)
    checks = {
        "raw_boundary_exceeds_weak_envelope": deltas["raw_boundary"]
        >= rubric["minimum_raw_boundary_delta"] - 1e-12,
        "projected_boundary_reaches_weak_envelope": deltas[
            "projected_boundary"
        ]
        >= rubric["minimum_projected_boundary_delta"] - 1e-12,
        "raw_within_pass_not_obviously_regressed": deltas["raw_within_pass"]
        >= rubric["minimum_raw_within_pass_delta"] - 1e-12,
        "projected_within_pass_not_obviously_regressed": deltas[
            "projected_within_pass"
        ]
        >= rubric["minimum_projected_within_pass_delta"] - 1e-12,
        "boundary_pair_distribution": (
            distribution["boundary"]["improved_raw"]
            - distribution["boundary"]["worsened_raw"]
            >= rubric["minimum_boundary_raw_improvement_advantage"]
        ),
        "pair_change_not_uniform_offset": (
            any(abs(value) > 1e-12 for value in raw_pair_deltas)
            and max(raw_pair_deltas) - min(raw_pair_deltas) > 1e-12
        ),
        "boundary_strict_not_regressed": deltas["boundary_strict_win_rate"]
        >= rubric["minimum_boundary_strict_delta"] - 1e-12,
        "within_pass_strict_not_regressed": deltas[
            "within_pass_strict_win_rate"
        ]
        >= rubric["minimum_within_pass_strict_delta"] - 1e-12,
        "roc_auc_not_obviously_regressed": deltas["roc_auc"]
        >= rubric["minimum_roc_auc_delta"] - 1e-12,
        "frozen_balanced_accuracy_not_regressed": deltas["balanced_accuracy"]
        >= rubric["minimum_balanced_accuracy_delta"] - 1e-12,
        "best_balanced_accuracy_not_regressed": deltas[
            "best_balanced_accuracy"
        ]
        >= rubric["minimum_best_balanced_accuracy_delta"] - 1e-12,
        "frozen_false_pass_not_regressed": deltas["false_pass_rate"]
        <= rubric["maximum_false_pass_rate_delta"] + 1e-12,
        "raw_logit_span_noncollapse": span_ratio
        >= rubric["minimum_raw_logit_span_ratio"] - 1e-12,
        "meaningful_discrete_event": any(meaningful_events.values()),
    }
    if type(candidate_eligible) is not bool:
        raise FullModelTrainingError("plan094_candidate_eligibility_invalid")
    rubric_passed = all(checks.values())
    core = {
        "schema": ASSESSMENT_SCHEMA,
        "global_step": candidate["global_step"],
        "base": base,
        "candidate": candidate,
        "deltas": deltas,
        "pair_distribution": distribution,
        "raw_logit_span_ratio": span_ratio,
        "best_operating": {"base": best_base, "candidate": best_candidate},
        "meaningful_events": meaningful_events,
        "checks": checks,
        "candidate_eligible": candidate_eligible,
        "rubric_passed": rubric_passed,
        "passed": candidate_eligible and rubric_passed,
    }
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def decide_stop(freeze: Any, assessments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    rows = [validate_assessment(item) for item in assessments]
    if not rows:
        raise FullModelTrainingError("plan094_stop_assessments_empty")
    steps = [int(row["global_step"]) for row in rows]
    if steps != sorted(set(steps)) or steps[0] != 1:
        raise FullModelTrainingError("plan094_stop_assessment_sequence_invalid")
    latest = rows[-1]
    material = next((row for row in rows if row["passed"]), None)
    if material is not None:
        outcome = "ROUTE_O_MATERIAL_CANDIDATE_RETAINED"
        reason = "first_complete_checkpoint_meets_frozen_material_rubric"
        terminal = True
    else:
        rule = contract["stop_rule"]
        new_tail = [row for row in rows if int(row["global_step"]) > 1][-3:]
        weak = contract["weak_signal_envelope"]["raw_boundary_delta"]
        early_plateau = (
            latest["global_step"] >= rule["early_no_material_step"]
            and len(new_tail) == 3
            and all(not row["passed"] for row in new_tail)
            and max(float(row["deltas"]["raw_boundary"]) for row in new_tail)
            <= weak + 1e-12
            and not any(
                any(row["meaningful_events"].values()) for row in new_tail
            )
        )
        at_maximum = latest["global_step"] >= rule["maximum_global_step"]
        if early_plateau:
            outcome = "ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT"
            reason = "prefrozen_three_checkpoint_no_material_plateau"
            terminal = True
        elif at_maximum:
            outcome = "ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT"
            reason = "prefrozen_maximum_qualified_observation_reached"
            terminal = True
        else:
            outcome = "CONTINUE"
            reason = "frozen_stop_rule_not_reached"
            terminal = False
    core = {
        "schema": STOP_DECISION_SCHEMA,
        "terminal": terminal,
        "outcome": outcome,
        "reason": reason,
        "global_step": (
            material["global_step"] if material is not None else latest["global_step"]
        ),
        "evaluated_steps": steps,
    }
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def validate_assessment(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != ASSESSMENT_SCHEMA
        or not _sha256(value.get("content_sha256"))
    ):
        raise FullModelTrainingError("plan094_assessment_invalid")
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    if (
        sha256_bytes(canonical_json_bytes(core)) != value["content_sha256"]
        or not isinstance(value.get("global_step"), int)
        or isinstance(value["global_step"], bool)
        or value["global_step"] <= 0
        or type(value.get("passed")) is not bool
        or type(value.get("candidate_eligible")) is not bool
        or type(value.get("rubric_passed")) is not bool
        or not isinstance(value.get("deltas"), Mapping)
        or not isinstance(value.get("meaningful_events"), Mapping)
        or not isinstance(value.get("checks"), Mapping)
        or any(type(item) is not bool for item in value["meaningful_events"].values())
        or any(type(item) is not bool for item in value["checks"].values())
        or value["rubric_passed"] != all(value["checks"].values())
        or value["passed"]
        != (value["candidate_eligible"] and value["rubric_passed"])
    ):
        raise FullModelTrainingError("plan094_assessment_invalid")
    return json.loads(json.dumps(value))


def validate_budget_snapshot(value: Any) -> dict[str, Any]:
    base_fields = {
        "schema",
        "captured_at",
        "live_balance_usd",
        "known_unsettled_usd",
        "stage_b_baseline_balance_usd",
        "stage_b_baseline_known_unsettled_usd",
        "conservative_task_cost_usd",
        "closure_reserve_usd",
        "projected_segment_and_closure_usd",
    }
    derived_fields = {
        "balance_metered_cost_floor_usd",
        "remaining_task_headroom_usd",
        "remaining_account_headroom_usd",
        "action_headroom_usd",
        "segment_authorized",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or frozenset(value) not in {
        frozenset(base_fields),
        frozenset(base_fields | derived_fields),
    }:
        raise FullModelTrainingError("plan094_budget_snapshot_invalid")
    if value.get("schema") != BUDGET_SCHEMA or not _identifier(value.get("captured_at")):
        raise FullModelTrainingError("plan094_budget_snapshot_invalid")
    numbers = {
        key: _nonnegative(value.get(key))
        for key in base_fields
        if key not in {"schema", "captured_at"}
    }
    baseline_available = (
        numbers["stage_b_baseline_balance_usd"]
        - numbers["stage_b_baseline_known_unsettled_usd"]
    )
    live_available = numbers["live_balance_usd"] - numbers["known_unsettled_usd"]
    balance_floor = max(baseline_available - live_available, 0.0)
    if numbers["conservative_task_cost_usd"] > 5.0 + 1e-12:
        raise FullModelTrainingError("plan094_budget_hard_limit_exceeded")
    if numbers["conservative_task_cost_usd"] + 1e-12 < balance_floor:
        raise FullModelTrainingError("plan094_budget_cost_floor_violated")
    task_headroom = max(5.0 - numbers["conservative_task_cost_usd"], 0.0)
    account_headroom = max(live_available - numbers["closure_reserve_usd"], 0.0)
    action_headroom = min(task_headroom, account_headroom)
    core = {
        "schema": BUDGET_SCHEMA,
        "captured_at": value["captured_at"],
        **numbers,
        "balance_metered_cost_floor_usd": balance_floor,
        "remaining_task_headroom_usd": task_headroom,
        "remaining_account_headroom_usd": account_headroom,
        "action_headroom_usd": action_headroom,
        "segment_authorized": (
            numbers["projected_segment_and_closure_usd"]
            <= action_headroom + 1e-12
        ),
    }
    result = {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}
    if set(value) == base_fields | derived_fields and dict(value) != result:
        raise FullModelTrainingError("plan094_budget_snapshot_derived_drifted")
    return result


def _summarize_observation(
    value: Mapping[str, Any], *, expected_split: str
) -> dict[str, Any]:
    """Summarize a full observation without importing Plan 090 internals."""

    metadata = (
        value.get("validation")
        if expected_split == "validation"
        else value.get("cohort")
    )
    try:
        if metadata["split"] != expected_split:
            raise KeyError
        pairs = value["pair_margins"]
        boundary = [row for row in pairs if row["kind"] == "boundary"]
        within = [row for row in pairs if row["kind"] == "within_pass"]
        raw_distribution = value["metrics"]["raw_logit_distribution"]
        objective = value["objective_diagnostic"]
        if (
            objective["schema"] != OBJECTIVE_DIAGNOSTIC_SCHEMA
            or objective["gradient_access"] is not False
            or set(objective["component_mean_loss"])
            != {"binary", "boundary", "within_pass"}
        ):
            raise KeyError
        best_balanced = max(
            float(row["balanced_accuracy"])
            for row in value["operating_curve"]
            if row["balanced_accuracy"] is not None
        )
        result = {
            "identity_sha256": metadata["identity_sha256"],
            "global_step": int(value["global_step"]),
            "candidate_count": int(metadata["candidate_count"]),
            "pair_count": int(metadata["pair_count"]),
            "raw_boundary": statistics.fmean(
                float(row["signed_raw_margin"]) for row in boundary
            ),
            "projected_boundary": statistics.fmean(
                float(row["signed_projected_margin"]) for row in boundary
            ),
            "raw_within_pass": statistics.fmean(
                float(row["signed_raw_margin"]) for row in within
            ),
            "projected_within_pass": statistics.fmean(
                float(row["signed_projected_margin"]) for row in within
            ),
            "boundary_strict_win_rate": sum(
                float(row["signed_raw_margin"]) > 0 for row in boundary
            )
            / len(boundary),
            "within_pass_strict_win_rate": sum(
                float(row["signed_raw_margin"]) > 0 for row in within
            )
            / len(within),
            "roc_auc": float(value["metrics"]["roc_auc"]),
            "balanced_accuracy": float(
                value["metrics"]["overall"]["balanced_accuracy"]
            ),
            "false_pass_rate": float(
                value["metrics"]["overall"]["false_pass_rate"]
            ),
            "best_balanced_accuracy": best_balanced,
            "raw_logit_span": float(raw_distribution["max"])
            - float(raw_distribution["min"]),
            "objective_weighted": float(objective["weighted_mean_loss"]),
            "objective_binary": float(
                objective["component_mean_loss"]["binary"]
            ),
            "objective_boundary": float(
                objective["component_mean_loss"]["boundary"]
            ),
            "objective_within_pass": float(
                objective["component_mean_loss"]["within_pass"]
            ),
        }
    except (
        KeyError,
        TypeError,
        ValueError,
        ZeroDivisionError,
        statistics.StatisticsError,
    ) as exc:
        raise FullModelTrainingError("plan094_observation_invalid") from exc
    if not _sha256(result["identity_sha256"]) or any(
        not math.isfinite(item)
        for key, item in result.items()
        if key
        not in {"identity_sha256", "global_step", "candidate_count", "pair_count"}
    ):
        raise FullModelTrainingError("plan094_observation_invalid")
    return result


def _pair_distribution(
    base: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        left = {row["pair_id"]: row for row in base["pair_margins"]}
        right = {row["pair_id"]: row for row in candidate["pair_margins"]}
    except (KeyError, TypeError) as exc:
        raise FullModelTrainingError("plan094_pair_distribution_invalid") from exc
    if set(left) != set(right) or len(left) != len(base["pair_margins"]):
        raise FullModelTrainingError("plan094_pair_distribution_invalid")
    result: dict[str, Any] = {}
    for kind in ("boundary", "within_pass"):
        rows: list[tuple[float, float]] = []
        for pair_id in sorted(left):
            if left[pair_id].get("kind") != kind:
                continue
            if right[pair_id].get("kind") != kind:
                raise FullModelTrainingError(
                    "plan094_pair_distribution_invalid"
                )
            rows.append(
                (
                    float(right[pair_id]["signed_raw_margin"])
                    - float(left[pair_id]["signed_raw_margin"]),
                    float(right[pair_id]["signed_projected_margin"])
                    - float(left[pair_id]["signed_projected_margin"]),
                )
            )
        if not rows:
            raise FullModelTrainingError("plan094_pair_distribution_invalid")
        result[kind] = {
            "count": len(rows),
            "improved_raw": sum(raw > 0 for raw, _projected in rows),
            "unchanged_raw": sum(raw == 0 for raw, _projected in rows),
            "worsened_raw": sum(raw < 0 for raw, _projected in rows),
            "improved_projected": sum(
                projected > 0 for _raw, projected in rows
            ),
            "unchanged_projected": sum(
                projected == 0 for _raw, projected in rows
            ),
            "worsened_projected": sum(
                projected < 0 for _raw, projected in rows
            ),
        }
    return result


def _best_operating_point(observation: Mapping[str, Any]) -> dict[str, Any]:
    try:
        rows = [
            row
            for row in observation["operating_curve"]
            if row["balanced_accuracy"] is not None
        ]
        selected = max(
            rows,
            key=lambda row: (
                float(row["balanced_accuracy"]),
                -float(row["false_pass_rate"]),
                -float(row["false_rewrite_rate"]),
            ),
        )
        return {
            "threshold": float(selected["threshold"]),
            "balanced_accuracy": float(selected["balanced_accuracy"]),
            "false_pass_rate": float(selected["false_pass_rate"]),
            "false_rewrite_rate": float(selected["false_rewrite_rate"]),
            "confusion": json.loads(json.dumps(selected["confusion"])),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise FullModelTrainingError("plan094_operating_curve_invalid") from exc


def _raw_pair_deltas(
    base: Mapping[str, Any], candidate: Mapping[str, Any]
) -> list[float]:
    try:
        left = {row["pair_id"]: row for row in base["pair_margins"]}
        right = {row["pair_id"]: row for row in candidate["pair_margins"]}
        if set(left) != set(right) or not left:
            raise KeyError
        return [
            float(right[pair_id]["signed_raw_margin"])
            - float(left[pair_id]["signed_raw_margin"])
            for pair_id in sorted(left)
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise FullModelTrainingError("plan094_pair_delta_invalid") from exc


def _validate_inventory(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(
        value.get("parameters"), Sequence
    ):
        raise FullModelTrainingError("plan094_parameter_inventory_invalid")
    rows = value["parameters"]
    if isinstance(rows, (str, bytes, bytearray)) or any(
        not isinstance(row, Mapping)
        or not _identifier(row.get("name"))
        or not isinstance(row.get("elements"), int)
        or isinstance(row["elements"], bool)
        or row["elements"] <= 0
        or row.get("dtype") != "torch.bfloat16"
        for row in rows
    ):
        raise FullModelTrainingError("plan094_parameter_inventory_invalid")
    selected = {str(row["name"]): row for row in rows}
    identity_rows = [
        {"name": row["name"], "elements": row["elements"], "dtype": row["dtype"]}
        for row in rows
    ]
    if (
        len(selected) != len(rows)
        or any(name not in selected for name in SCOPE_PARAMETER_NAMES)
        or sum(int(selected[name]["elements"]) for name in SCOPE_PARAMETER_NAMES)
        != SCOPE_PARAMETER_ELEMENTS
        or value.get("parameter_tensors") != 311
        or value.get("parameter_elements") != 1_720_577_024
        or value.get("parameter_tensors") != len(rows)
        or value.get("parameter_elements")
        != sum(int(row["elements"]) for row in rows)
        or value.get("inventory_sha256")
        != sha256_bytes(canonical_json_bytes(identity_rows))
    ):
        raise FullModelTrainingError("plan094_parameter_inventory_invalid")
    return json.loads(json.dumps(value))


def _nonnegative(value: Any) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise FullModelTrainingError("plan094_budget_snapshot_invalid")
    return float(value)


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _commit(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "ASSESSMENT_SCHEMA",
    "BUDGET_SCHEMA",
    "FREEZE_SCHEMA",
    "PLAN090_SOURCE_CHECKPOINT_BYTES",
    "PLAN090_SOURCE_CHECKPOINT_ID",
    "PLAN090_SOURCE_CHECKPOINT_PATH",
    "PLAN090_SOURCE_CHECKPOINT_SHA256",
    "RUN_SPEC_SCHEMA",
    "STOP_DECISION_SCHEMA",
    "assess_material",
    "decide_stop",
    "freeze_sha256",
    "frozen_contract",
    "materialize_run_spec",
    "validate_assessment",
    "validate_budget_snapshot",
    "validate_freeze",
    "validate_run_spec",
]
