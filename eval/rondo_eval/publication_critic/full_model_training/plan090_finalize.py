"""Pre-frozen Route O rubric, branch state machine, and terminal result."""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .contract import FullModelTrainingError, canonical_json_bytes, sha256_bytes
from .plan082_controller import validate_process_identity
from .plan090_artifacts import Plan090ArtifactStore
from .plan090_contract import (
    BF16_PRIMARY_RUN,
    BF16_SECONDARY_RUN,
    FP32_CONTROL_RUN,
    TRAINING_RUNS,
    freeze_sha256,
    validate_budget_snapshot,
    validate_freeze,
    validate_run_spec,
)
from .plan090_controller import (
    CONTROLLER_SCHEMA,
    OBJECTIVE_DIAGNOSTIC_SCHEMA,
    validate_precision_receipt,
    validate_runtime_identity,
)

RUN_RESULT_SCHEMA = "rondo-publication-critic-plan090-run-result-v1"
TERMINAL_RESULT_SCHEMA = "rondo-publication-critic-plan090-terminal-result-v1"
RECOVERY_RECEIPT_SCHEMA = "rondo-publication-critic-plan090-recovery-receipt-v1"
TERMINALS = frozenset(
    {
        "ROUTE_O_CONFIRMATION_PASS",
        "ROUTE_O_CONFIRMATION_NO_GO",
        "INCONCLUSIVE_INFRASTRUCTURE",
    }
)


def assess_reproduction(
    freeze: Any,
    *,
    base_validation: Mapping[str, Any],
    candidate_validation: Mapping[str, Any],
    base_train: Mapping[str, Any],
    candidate_train: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the whole pre-result rubric to one matching-base run."""

    contract = validate_freeze(freeze)
    rubric = contract["rubric"]
    base = _summarize_observation(base_validation, expected_split="validation")
    candidate = _summarize_observation(
        candidate_validation, expected_split="validation"
    )
    train_base = _summarize_observation(base_train, expected_split="train")
    train_candidate = _summarize_observation(candidate_train, expected_split="train")
    if (
        base["identity_sha256"] != candidate["identity_sha256"]
        or train_base["identity_sha256"] != train_candidate["identity_sha256"]
        or base["global_step"] != 0
        or candidate["global_step"] != 1
        or train_base["global_step"] != 0
        or train_candidate["global_step"] != 1
        or base_validation.get("scope") != candidate_validation.get("scope")
        or base_train.get("scope") != candidate_train.get("scope")
        or base_validation.get("scope") != base_train.get("scope")
    ):
        raise FullModelTrainingError("plan090_matching_base_diagnostic_mismatch")
    deltas = {
        key: candidate[key] - base[key]
        for key in (
            "raw_boundary",
            "projected_boundary",
            "raw_within_pass",
            "projected_within_pass",
            "roc_auc",
            "boundary_strict_win_rate",
            "within_pass_strict_win_rate",
            "balanced_accuracy",
            "false_pass_rate",
            "best_balanced_accuracy",
            "objective_weighted",
            "objective_binary",
            "objective_boundary",
            "objective_within_pass",
        )
    }
    distribution = _pair_distribution(base_validation, candidate_validation)
    boundary = distribution["boundary"]
    within = distribution["within_pass"]
    span_ratio = (
        candidate["raw_logit_span"] / base["raw_logit_span"]
        if base["raw_logit_span"] > 0
        else 0.0
    )
    checks = {
        "raw_boundary_direction": deltas["raw_boundary"]
        >= rubric["minimum_raw_boundary_delta"],
        "projected_boundary_direction": deltas["projected_boundary"]
        >= rubric["minimum_projected_boundary_delta"],
        "projected_within_pass_noncollapse": deltas["projected_within_pass"]
        >= rubric["minimum_projected_within_pass_delta"],
        "raw_within_pass_noncollapse": deltas["raw_within_pass"]
        >= rubric["minimum_raw_within_pass_delta"],
        "roc_noncollapse": deltas["roc_auc"] >= rubric["minimum_roc_auc_delta"],
        "boundary_raw_distribution": (
            boundary["improved_raw"] >= rubric["minimum_boundary_improved_raw_pairs"]
            and boundary["improved_raw"] - boundary["worsened_raw"]
            >= rubric["minimum_boundary_raw_improvement_advantage"]
        ),
        "boundary_projected_distribution": (
            boundary["improved_projected"] - boundary["worsened_projected"]
            >= rubric["minimum_boundary_projected_improvement_advantage"]
        ),
        "within_projected_distribution": (
            within["improved_projected"] - within["worsened_projected"]
            >= rubric["minimum_within_projected_improvement_advantage"]
        ),
        "boundary_strict_noncollapse": deltas["boundary_strict_win_rate"]
        >= rubric["minimum_boundary_strict_win_rate_delta"],
        "within_strict_noncollapse": deltas["within_pass_strict_win_rate"]
        >= rubric["minimum_within_pass_strict_win_rate_delta"],
        "balanced_accuracy_noncollapse": deltas["balanced_accuracy"]
        >= rubric["minimum_balanced_accuracy_delta"],
        "false_pass_noncollapse": deltas["false_pass_rate"]
        <= rubric["maximum_false_pass_rate_delta"],
        "operating_noncollapse": deltas["best_balanced_accuracy"]
        >= rubric["minimum_best_balanced_accuracy_delta"],
        "raw_logit_span_noncollapse": span_ratio
        >= rubric["minimum_raw_logit_span_ratio"],
        "train_before_after_complete": (
            train_base["candidate_count"] == train_candidate["candidate_count"]
            and train_base["pair_count"] == train_candidate["pair_count"]
            and train_base["candidate_count"]
            == contract["data"]["train_candidate_count"]
            and train_base["pair_count"] == contract["data"]["train_pair_count"]
        ),
    }
    passed = all(checks.values())
    return {
        "rubric": json.loads(json.dumps(rubric)),
        "passed": passed,
        "disposition": "pass" if passed else "no_go",
        "checks": checks,
        "validation": {
            "base": base,
            "candidate": candidate,
            "deltas": deltas,
            "pair_distribution": distribution,
            "raw_logit_span_ratio": span_ratio,
        },
        "train": {
            "base": train_base,
            "candidate": train_candidate,
            "deltas": {
                key: train_candidate[key] - train_base[key]
                for key in (
                    "objective_weighted",
                    "objective_binary",
                    "objective_boundary",
                    "objective_within_pass",
                )
            },
            "diagnostic_only": True,
        },
        "claims": {
            "matching_base": True,
            "uniform_offset_alone_sufficient": False,
            "threshold_only_sufficient": False,
            "single_metric_sufficient": False,
            "unseen_evidence": False,
        },
    }


def finalize_run(
    *,
    freeze: Any,
    controller_state: Mapping[str, Any],
    artifact_root: Path,
    selected_checkpoint_id: str,
    recovery_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    if (
        not isinstance(controller_state, Mapping)
        or controller_state.get("schema") != CONTROLLER_SCHEMA
        or controller_state.get("status") != "completed"
        or controller_state.get("current_step") != 1
        or controller_state.get("latest_checkpoint_id") != selected_checkpoint_id
    ):
        raise FullModelTrainingError("plan090_run_not_complete")
    plan090 = controller_state.get("plan090")
    if not isinstance(plan090, Mapping):
        raise FullModelTrainingError("plan090_run_state_invalid")
    spec = validate_run_spec(plan090.get("run_spec"), freeze=contract)
    if plan090.get("freeze_sha256") != freeze_sha256(contract):
        raise FullModelTrainingError("plan090_run_freeze_mismatch")
    store = Plan090ArtifactStore(artifact_root)
    checkpoint = store.verify_checkpoint(selected_checkpoint_id)
    validation_rows = controller_state.get("observations")
    train_rows = plan090.get("training_observations")
    if (
        not isinstance(validation_rows, list)
        or len(validation_rows) != 1
        or not isinstance(train_rows, list)
        or len(train_rows) != 2
    ):
        raise FullModelTrainingError("plan090_run_observation_count_invalid")
    base_validation = store.read_observation(
        controller_state["base"]["observation"]["observation_id"]
    )
    candidate_validation = store.read_observation(validation_rows[0]["observation_id"])
    base_train = store.read_observation(train_rows[0]["observation_id"])
    candidate_train = store.read_observation(train_rows[1]["observation_id"])
    assessment = assess_reproduction(
        contract,
        base_validation=base_validation,
        candidate_validation=candidate_validation,
        base_train=base_train,
        candidate_train=candidate_train,
    )
    precision = validate_precision_receipt(
        plan090.get("precision_receipt"),
        run_spec=spec,
        scope=controller_state["current_scope"],
    )
    recovery = None
    if recovery_receipt is not None:
        recovery = validate_recovery_receipt(
            recovery_receipt,
            run_id=spec["run_id"],
            checkpoint_id=selected_checkpoint_id,
            checkpoint_sha256=checkpoint["content_sha256"],
            freeze_digest=freeze_sha256(contract),
        )
        if (
            plan090["recovery_proven_checkpoints"].get(selected_checkpoint_id)
            != checkpoint["content_sha256"]
        ):
            raise FullModelTrainingError("plan090_recovery_state_mismatch")
    core = {
        "schema": RUN_RESULT_SCHEMA,
        "run_id": spec["run_id"],
        "freeze_sha256": freeze_sha256(contract),
        "run_spec": spec,
        "launch_budget_snapshot": plan090["launch_budget_snapshot"],
        "artifact_namespace": spec["artifact_namespace"],
        "start_state": "exact_base",
        "assessment": assessment,
        "base_validation_observation": base_validation,
        "candidate_validation_observation": candidate_validation,
        "base_train_observation": base_train,
        "candidate_train_observation": candidate_train,
        "selected_checkpoint": {
            "checkpoint_id": selected_checkpoint_id,
            "content_sha256": checkpoint["content_sha256"],
            "bytes": checkpoint["bytes"],
            "remote_only": True,
            "fresh_process_recovery": recovery is not None,
        },
        "recovery_receipt": recovery,
        "runtime_identity": plan090["runtime_identity"],
        "process_identity": validate_process_identity(plan090["process_identity"]),
        "precision_receipt": precision,
        "claims": {
            "clean_exact_base_training": True,
            "matching_base_assessment": True,
            "seed_sensitive_stability_tested": False,
            "route_search": False,
            "unseen_evidence": False,
            "product_go": False,
            "m3_c2_evidence": False,
        },
    }
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def validate_recovery_receipt(
    value: Any,
    *,
    run_id: str,
    checkpoint_id: str,
    checkpoint_sha256: str,
    freeze_digest: str,
) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema",
            "run_id",
            "checkpoint_id",
            "checkpoint_sha256",
            "freeze_sha256",
            "source_process_id",
            "recovery_process_id",
            "fresh_adapter",
            "model_loaded",
            "optimizer_scheduler_rng_data_equal",
            "no_update",
            "checkpoint_reuse_verified",
        }
        or value.get("schema") != RECOVERY_RECEIPT_SCHEMA
        or value.get("run_id") != run_id
        or value.get("checkpoint_id") != checkpoint_id
        or value.get("checkpoint_sha256") != checkpoint_sha256
        or value.get("freeze_sha256") != freeze_digest
        or not _identifier(value.get("source_process_id"))
        or not _identifier(value.get("recovery_process_id"))
        or value["source_process_id"] == value["recovery_process_id"]
        or any(
            value.get(key) is not True
            for key in (
                "fresh_adapter",
                "model_loaded",
                "optimizer_scheduler_rng_data_equal",
                "no_update",
                "checkpoint_reuse_verified",
            )
        )
    ):
        raise FullModelTrainingError("plan090_recovery_receipt_invalid")
    return json.loads(json.dumps(value))


def next_action(
    freeze: Any,
    run_results: Sequence[Mapping[str, Any]],
    *,
    fp32_budget_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    rows = [_validate_run_result(value, freeze=contract) for value in run_results]
    ids = [row["run_id"] for row in rows]
    if ids != list(TRAINING_RUNS[: len(ids)]):
        raise FullModelTrainingError("plan090_run_sequence_invalid")
    if not rows:
        return {"action": "run", "run_id": BF16_PRIMARY_RUN}
    if rows[0]["assessment"]["passed"] is not True:
        return {"action": "finalize", "outcome": "ROUTE_O_CONFIRMATION_NO_GO"}
    if len(rows) == 1:
        return {"action": "run", "run_id": BF16_SECONDARY_RUN}
    if rows[1]["assessment"]["passed"] is not True:
        return {"action": "finalize", "outcome": "ROUTE_O_CONFIRMATION_NO_GO"}
    if len(rows) == 2:
        if fp32_budget_snapshot is None:
            raise FullModelTrainingError("plan090_fp32_budget_snapshot_required")
        budget = validate_budget_snapshot(fp32_budget_snapshot)
        if (
            budget["complete_branch_authorized"]
            and budget["projected_complete_branch_usd"] > 0.0
        ):
            return {"action": "run", "run_id": FP32_CONTROL_RUN, "budget": budget}
        return {
            "action": "finalize",
            "outcome": "ROUTE_O_CONFIRMATION_PASS",
            "fp32": {
                "status": "skipped",
                "reason": "insufficient_safe_budget_for_complete_fp32_closure",
                "budget": budget,
            },
        }
    return {
        "action": "finalize",
        "outcome": "ROUTE_O_CONFIRMATION_PASS",
        "fp32": {
            "status": "completed",
            "rubric_passed": rows[2]["assessment"]["passed"],
            "interpretation": rows[2]["precision_receipt"]["precision_contract"][
                "interpretation"
            ],
        },
    }


def finalize_terminal(
    *,
    freeze: Any,
    run_results: Sequence[Mapping[str, Any]],
    outcome: str,
    reason: str,
    resource_state: Mapping[str, Any],
    terminal_budget_snapshot: Mapping[str, Any],
    fp32_budget_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    if outcome not in TERMINALS or not isinstance(reason, str) or not reason.strip():
        raise FullModelTrainingError("plan090_terminal_invalid")
    rows = [_validate_run_result(value, freeze=contract) for value in run_results]
    ids = [row["run_id"] for row in rows]
    if ids != list(TRAINING_RUNS[: len(ids)]) or any(
        row["freeze_sha256"] != freeze_sha256(contract)
        or validate_run_spec(row["run_spec"], freeze=contract)["run_id"]
        != row["run_id"]
        for row in rows
    ):
        raise FullModelTrainingError("plan090_terminal_run_binding_invalid")
    expected = None
    fp32 = None
    positive_bf16_repeats = len(rows) >= 2 and all(
        row["assessment"]["passed"] is True for row in rows[:2]
    )
    recovery_closure_incomplete = (
        len(rows) >= 2
        and positive_bf16_repeats
        and all(row["assessment"]["passed"] is True for row in rows)
        and rows[1]["selected_checkpoint"]["fresh_process_recovery"] is False
    )
    fp32_branch_incomplete = False
    fp32_incomplete_budget = None
    if outcome == "INCONCLUSIVE_INFRASTRUCTURE":
        if (
            len(rows) == 2
            and positive_bf16_repeats
            and rows[1]["selected_checkpoint"]["fresh_process_recovery"] is True
            and fp32_budget_snapshot is not None
        ):
            decision = next_action(
                contract, rows, fp32_budget_snapshot=fp32_budget_snapshot
            )
            fp32_branch_incomplete = (
                decision.get("action") == "run"
                and decision.get("run_id") == FP32_CONTROL_RUN
            )
            if fp32_branch_incomplete:
                fp32_incomplete_budget = decision["budget"]
                fp32 = {
                    "status": "incomplete_infrastructure",
                    "budget": fp32_incomplete_budget,
                }
        if any(row["assessment"]["passed"] is not True for row in rows) or (
            len(rows) >= 2
            and not (recovery_closure_incomplete or fp32_branch_incomplete)
        ):
            raise FullModelTrainingError(
                "plan090_infrastructure_cannot_override_model_result"
            )
    else:
        decision = next_action(
            contract, rows, fp32_budget_snapshot=fp32_budget_snapshot
        )
        if decision["action"] != "finalize":
            raise FullModelTrainingError("plan090_terminal_sequence_incomplete")
        expected = decision["outcome"]
        fp32 = decision.get("fp32")
        if outcome != expected:
            raise FullModelTrainingError("plan090_terminal_outcome_mismatch")
    resources = _validate_resource_state(resource_state)
    budget = validate_budget_snapshot(terminal_budget_snapshot)
    run_budgets = [row["launch_budget_snapshot"] for row in rows]
    if fp32 is not None and fp32.get("status") == "skipped":
        run_budgets.append(validate_budget_snapshot(fp32["budget"]))
    if fp32_incomplete_budget is not None:
        run_budgets.append(fp32_incomplete_budget)
    baseline = (
        budget["stage_b_baseline_balance_usd"],
        budget["stage_b_baseline_known_unsettled_usd"],
    )
    if any(
        (
            item["stage_b_baseline_balance_usd"],
            item["stage_b_baseline_known_unsettled_usd"],
        )
        != baseline
        for item in run_budgets
    ):
        raise FullModelTrainingError("plan090_budget_baseline_drifted")
    costs = [item["conservative_task_cost_usd"] for item in run_budgets] + [
        budget["conservative_task_cost_usd"]
    ]
    if any(right + 1e-12 < left for left, right in zip(costs, costs[1:])):
        raise FullModelTrainingError("plan090_budget_cost_decreased")
    pod_bindings = {
        (
            row["runtime_identity"]["provider_pod_id"],
            row["runtime_identity"]["provider_pod_name"],
            row["process_identity"]["hostname"],
        )
        for row in rows
    }
    if len(pod_bindings) > 1:
        raise FullModelTrainingError("plan090_formal_pod_identity_drifted")
    if budget["conservative_task_cost_usd"] > 6.0 + 1e-12:
        raise FullModelTrainingError("plan090_terminal_budget_exceeded")
    if outcome == "ROUTE_O_CONFIRMATION_PASS":
        final_bf16 = next(row for row in rows if row["run_id"] == BF16_SECONDARY_RUN)
        if final_bf16["selected_checkpoint"]["fresh_process_recovery"] is not True:
            raise FullModelTrainingError("plan090_pass_recovery_required")
    core = {
        "schema": TERMINAL_RESULT_SCHEMA,
        "outcome": outcome,
        "reason": reason,
        "freeze_sha256": freeze_sha256(contract),
        "runs": rows,
        "formal_pod": (
            {
                "provider_pod_id": binding[0],
                "provider_pod_name": binding[1],
                "hostname": binding[2],
            }
            if (binding := next(iter(pod_bindings), None)) is not None
            else None
        ),
        "fp32": fp32,
        "budget": budget,
        "resource_state": resources,
        "claims": {
            "task_goal_complete": True,
            "route_o_repeated_on_same_validation_two_clean_runs": (
                positive_bf16_repeats
            ),
            "positive_bf16_clean_repeats_observed": positive_bf16_repeats,
            "seed_sensitive_stability_tested": False,
            "confirmation_closure_incomplete": (
                outcome == "INCONCLUSIVE_INFRASTRUCTURE"
                and (recovery_closure_incomplete or fp32_branch_incomplete)
            ),
            "fp32_branch_incomplete": fp32_branch_incomplete,
            "route_o_failed": outcome == "ROUTE_O_CONFIRMATION_NO_GO",
            "model_question_unanswered": (
                outcome == "INCONCLUSIVE_INFRASTRUCTURE" and not positive_bf16_repeats
            ),
            "independent_cohort_generalization": False,
            "unseen_evidence": False,
            "product_go": False,
            "m3_c1_or_m3_c2": False,
            "m3_d_unlocked": False,
        },
    }
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def _summarize_observation(
    value: Mapping[str, Any], *, expected_split: str
) -> dict[str, Any]:
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
            "false_pass_rate": float(value["metrics"]["overall"]["false_pass_rate"]),
            "best_balanced_accuracy": best_balanced,
            "raw_logit_span": float(raw_distribution["max"])
            - float(raw_distribution["min"]),
            "objective_weighted": float(objective["weighted_mean_loss"]),
            "objective_binary": float(objective["component_mean_loss"]["binary"]),
            "objective_boundary": float(objective["component_mean_loss"]["boundary"]),
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
        raise FullModelTrainingError("plan090_observation_invalid") from exc
    if not _sha256(result["identity_sha256"]) or any(
        not math.isfinite(value)
        for key, value in result.items()
        if key
        not in {"identity_sha256", "global_step", "candidate_count", "pair_count"}
    ):
        raise FullModelTrainingError("plan090_observation_invalid")
    return result


def _pair_distribution(
    base: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        left = {row["pair_id"]: row for row in base["pair_margins"]}
        right = {row["pair_id"]: row for row in candidate["pair_margins"]}
    except (KeyError, TypeError) as exc:
        raise FullModelTrainingError("plan090_pair_distribution_invalid") from exc
    if set(left) != set(right) or len(left) != len(base["pair_margins"]):
        raise FullModelTrainingError("plan090_pair_distribution_invalid")
    result: dict[str, Any] = {}
    for kind in ("boundary", "within_pass"):
        rows = []
        for pair_id in sorted(left):
            if left[pair_id].get("kind") != kind:
                continue
            if right[pair_id].get("kind") != kind:
                raise FullModelTrainingError("plan090_pair_distribution_invalid")
            rows.append(
                (
                    float(right[pair_id]["signed_raw_margin"])
                    - float(left[pair_id]["signed_raw_margin"]),
                    float(right[pair_id]["signed_projected_margin"])
                    - float(left[pair_id]["signed_projected_margin"]),
                )
            )
        if not rows:
            raise FullModelTrainingError("plan090_pair_distribution_invalid")
        result[kind] = {
            "count": len(rows),
            "improved_raw": sum(raw > 0 for raw, _projected in rows),
            "unchanged_raw": sum(raw == 0 for raw, _projected in rows),
            "worsened_raw": sum(raw < 0 for raw, _projected in rows),
            "improved_projected": sum(projected > 0 for _raw, projected in rows),
            "unchanged_projected": sum(projected == 0 for _raw, projected in rows),
            "worsened_projected": sum(projected < 0 for _raw, projected in rows),
        }
    return result


def _validate_run_result(value: Any, *, freeze: Any) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    required = {
        "schema",
        "run_id",
        "freeze_sha256",
        "run_spec",
        "launch_budget_snapshot",
        "artifact_namespace",
        "start_state",
        "assessment",
        "base_validation_observation",
        "candidate_validation_observation",
        "base_train_observation",
        "candidate_train_observation",
        "selected_checkpoint",
        "recovery_receipt",
        "runtime_identity",
        "process_identity",
        "precision_receipt",
        "claims",
        "content_sha256",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or value.get("schema") != RUN_RESULT_SCHEMA
        or value.get("run_id") not in TRAINING_RUNS
        or value.get("start_state") != "exact_base"
        or value.get("freeze_sha256") != freeze_sha256(contract)
        or not _sha256(value.get("content_sha256"))
    ):
        raise FullModelTrainingError("plan090_run_result_invalid")
    spec = validate_run_spec(value.get("run_spec"), freeze=contract)
    launch_budget = validate_budget_snapshot(value.get("launch_budget_snapshot"))
    selected = value.get("selected_checkpoint")
    recovery = value.get("recovery_receipt")
    if (
        spec["run_id"] != value["run_id"]
        or launch_budget != value["launch_budget_snapshot"]
        or value.get("artifact_namespace") != spec["artifact_namespace"]
        or not isinstance(selected, Mapping)
        or set(selected)
        != {
            "checkpoint_id",
            "content_sha256",
            "bytes",
            "remote_only",
            "fresh_process_recovery",
        }
        or not _identifier(selected.get("checkpoint_id"))
        or not _sha256(selected.get("content_sha256"))
        or not isinstance(selected.get("bytes"), int)
        or isinstance(selected["bytes"], bool)
        or selected["bytes"] <= 0
        or selected.get("remote_only") is not True
        or type(selected.get("fresh_process_recovery")) is not bool
        or (recovery is None) == selected["fresh_process_recovery"]
    ):
        raise FullModelTrainingError("plan090_run_result_invalid")
    if recovery is not None:
        validate_recovery_receipt(
            recovery,
            run_id=spec["run_id"],
            checkpoint_id=selected["checkpoint_id"],
            checkpoint_sha256=selected["content_sha256"],
            freeze_digest=freeze_sha256(contract),
        )
    assessment = assess_reproduction(
        contract,
        base_validation=value.get("base_validation_observation"),
        candidate_validation=value.get("candidate_validation_observation"),
        base_train=value.get("base_train_observation"),
        candidate_train=value.get("candidate_train_observation"),
    )
    if (
        value.get("assessment") != assessment
        or validate_precision_receipt(
            value.get("precision_receipt"), run_spec=spec, scope=spec["scope"]
        )
        != value["precision_receipt"]
        or validate_runtime_identity(value.get("runtime_identity"), run_spec=spec)
        != value["runtime_identity"]
        or validate_process_identity(value.get("process_identity"))
        != value["process_identity"]
        or value.get("claims")
        != {
            "clean_exact_base_training": True,
            "matching_base_assessment": True,
            "seed_sensitive_stability_tested": False,
            "route_search": False,
            "unseen_evidence": False,
            "product_go": False,
            "m3_c2_evidence": False,
        }
    ):
        raise FullModelTrainingError("plan090_run_result_invalid")
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    if value["content_sha256"] != sha256_bytes(canonical_json_bytes(core)):
        raise FullModelTrainingError("plan090_run_result_invalid")
    return json.loads(json.dumps(value))


def _validate_resource_state(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "captured_at",
            "pod_count",
            "compute_rate_usd_per_hour",
            "volume",
        }
        or not isinstance(value.get("captured_at"), str)
        or not value["captured_at"].strip()
        or value.get("pod_count") != 0
        or value.get("compute_rate_usd_per_hour") != 0
        or value.get("volume")
        != {
            "id": "mwemzrn33y",
            "region": "US-TX-3",
            "size_gb": 57,
            "deleted": False,
        }
    ):
        raise FullModelTrainingError("plan090_resource_terminal_invalid")
    return json.loads(json.dumps(value))


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "RECOVERY_RECEIPT_SCHEMA",
    "RUN_RESULT_SCHEMA",
    "TERMINAL_RESULT_SCHEMA",
    "assess_reproduction",
    "finalize_run",
    "finalize_terminal",
    "next_action",
    "validate_recovery_receipt",
]
