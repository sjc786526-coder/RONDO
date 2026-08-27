"""Frozen Route O confirmation and budget contracts for Plan 090."""

from __future__ import annotations

import json
import math
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
from .plan087_adapter import RECIPE_SCHEMA, validate_adaptive_recipe

FREEZE_SCHEMA = "rondo-publication-critic-plan090-confirmation-freeze-v1"
RUN_SPEC_SCHEMA = "rondo-publication-critic-plan090-run-spec-v1"
BUDGET_SCHEMA = "rondo-publication-critic-plan090-budget-snapshot-v1"

SNAPSHOT_CONTENT_SHA256 = (
    "18d9edf7132d9c5e13bb0e59e3c2c6a42f82007fa17de464e20783755a171360"
)
DATA_BUNDLE_CONTENT_SHA256 = (
    "2247dd09c168900a47d37a50ecd6511d66d62d3f2ec8056ea3bc829c93de8b46"
)
LEGACY_CHECKPOINT_SHA256 = (
    "d08ff2566d719b3aef4dd58158e86b1c374faf2021cc96a140d878b79857c923"
)

SCOPE_PARAMETER_NAMES = (
    "model.layers.27.self_attn.q_proj.weight",
    "model.layers.27.self_attn.k_proj.weight",
    "model.layers.27.self_attn.v_proj.weight",
    "model.layers.27.self_attn.q_norm.weight",
    "model.layers.27.self_attn.k_norm.weight",
    "model.layers.27.mlp.gate_proj.weight",
    "model.layers.27.mlp.up_proj.weight",
    "model.layers.27.input_layernorm.weight",
    "model.layers.27.post_attention_layernorm.weight",
)
SCOPE_PARAMETER_ELEMENTS = 33_558_784

BF16_PRIMARY_RUN = "bf16-seed-20260901"
BF16_SECONDARY_RUN = "bf16-seed-20260902"
FP32_CONTROL_RUN = "fp32-seed-20260901"
TRAINING_RUNS = (BF16_PRIMARY_RUN, BF16_SECONDARY_RUN, FP32_CONTROL_RUN)


def frozen_contract() -> dict[str, Any]:
    """Return the pre-result Plan 090 contract in its only accepted form."""

    return {
        "schema": FREEZE_SCHEMA,
        "model": {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "snapshot_content_sha256": SNAPSHOT_CONTENT_SHA256,
            "parameter_tensors": 311,
            "parameter_elements": 1_720_577_024,
            "historical_bf16_inventory_sha256": (
                "13d07191838650bcb6a7a5b7e5ff39d52bf9f2173ff361c0a0e9ed49fa609bac"
            ),
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
            "network_volume_size_gb": 57,
            "network_volume_mount_path": "/workspace",
            "maximum_simultaneous_billing_pods": 1,
        },
        "scope": {
            "scope_id": "plan090-route-o-layer27-internal-transformations",
            "update_method": "direct_original_parameter_update",
            "parameter_names": list(SCOPE_PARAMETER_NAMES),
            "trainable_parameter_elements": SCOPE_PARAMETER_ELEMENTS,
            "reason": "frozen Route O layer 27 input transformations and internal norms",
        },
        "recipes": {
            BF16_PRIMARY_RUN: _recipe(seed=20260901, parameter_dtype="bfloat16"),
            BF16_SECONDARY_RUN: _recipe(seed=20260902, parameter_dtype="bfloat16"),
            FP32_CONTROL_RUN: _recipe(seed=20260901, parameter_dtype="float32"),
        },
        "control_plan": {
            "maximum_updates": 1,
            "observation_steps": [1],
            "checkpoint_steps": [1],
            "turning_point_limit": 1,
        },
        "comparison_policy": {
            "metric": "boundary_pair_mean_margin",
            "direction": "higher_is_better",
            "tolerance": 0.0,
        },
        "report_threshold": 0.5,
        "historical_reference": {
            "source": "Plan 087 retained Route O matching-base validation evidence",
            "run_id": "route-o-internal-transformations",
            "base": {
                "raw_boundary_pair_mean_margin": 0.8104440789473685,
                "projected_boundary_pair_mean_margin": 0.08355612723605446,
                "raw_within_pass_pair_mean_margin": 0.375,
                "projected_within_pass_pair_mean_margin": 0.015236882517573793,
                "roc_auc": 0.6204481792717087,
            },
            "candidate": {
                "raw_boundary_pair_mean_margin": 0.8143503289473685,
                "projected_boundary_pair_mean_margin": 0.08441725969000985,
                "raw_within_pass_pair_mean_margin": 0.3716517857142857,
                "projected_within_pass_pair_mean_margin": 0.015375825117683681,
                "roc_auc": 0.6218487394957983,
            },
            "delta": {
                "raw_boundary_pair_mean_margin": 0.00390625,
                "projected_boundary_pair_mean_margin": 0.0008611324539553877,
                "raw_within_pass_pair_mean_margin": -0.0033482142857143016,
                "projected_within_pass_pair_mean_margin": 0.0001389426001098884,
                "roc_auc": 0.0014005602240896309,
                "boundary_strict_win_rate": 0.0,
                "within_pass_strict_win_rate": 0.0,
                "balanced_accuracy": 0.0,
                "false_pass_rate": 0.0,
                "best_balanced_accuracy": 0.0,
            },
            "pair_distribution": {
                "boundary": {
                    "count": 19,
                    "improved_raw": 7,
                    "unchanged_raw": 9,
                    "worsened_raw": 3,
                    "improved_projected": 13,
                    "unchanged_projected": 1,
                    "worsened_projected": 5,
                },
                "within_pass": {
                    "count": 7,
                    "improved_raw": 1,
                    "unchanged_raw": 4,
                    "worsened_raw": 2,
                    "improved_projected": 4,
                    "unchanged_projected": 2,
                    "worsened_projected": 1,
                },
            },
        },
        "rubric": {
            "primary_metric": "raw_boundary_pair_mean_margin",
            "basis": {
                "raw_boundary": (
                    "minimum is half the historical +0.00390625 BF16-grid delta"
                ),
                "roc_auc": (
                    "allow at most one validation pair-ordering quantum of drift"
                ),
                "companion_metrics": (
                    "historical projected, pair-distribution, strict, operating, "
                    "within-pass and span signals constrain offset or collapse"
                ),
            },
            "minimum_raw_boundary_delta": 0.001953125,
            "minimum_projected_boundary_delta": 0.0,
            "minimum_projected_within_pass_delta": -0.00025,
            "minimum_raw_within_pass_delta": -0.005859375,
            "minimum_roc_auc_delta": -0.002,
            "minimum_boundary_improved_raw_pairs": 5,
            "minimum_boundary_raw_improvement_advantage": 2,
            "minimum_boundary_projected_improvement_advantage": 1,
            "minimum_within_projected_improvement_advantage": 0,
            "minimum_boundary_strict_win_rate_delta": 0.0,
            "minimum_within_pass_strict_win_rate_delta": 0.0,
            "minimum_balanced_accuracy_delta": 0.0,
            "maximum_false_pass_rate_delta": 0.0,
            "minimum_best_balanced_accuracy_delta": 0.0,
            "minimum_raw_logit_span_ratio": 0.9,
            "matching_base_required": True,
            "train_before_after_required": True,
            "all_checks_required": True,
        },
        "precision": {
            "bfloat16": {
                "model_load": "all model parameters loaded as torch.bfloat16",
                "forward": "model forward and activations use the BF16 model path",
                "updated_parameters": "nine selected original parameters remain BF16",
                "gradients": "selected-parameter gradient tensors are observed as BF16",
                "optimizer_state": "fused AdamW state follows the selected BF16 parameters",
                "save": "save_pretrained persists the BF16 model state",
                "interpretation": "Route O BF16 reproduction",
            },
            "float32": {
                "model_load": "the exact BF16 snapshot is materialized as torch.float32",
                "forward": "the full model forward and activations use the FP32 model path",
                "updated_parameters": "nine selected original parameters are FP32",
                "gradients": "selected-parameter gradient tensors are observed as FP32",
                "optimizer_state": "fused AdamW state follows the selected FP32 parameters",
                "save": "save_pretrained persists the FP32 materialized model state",
                "interpretation": (
                    "FP32 parameter-training condition control, not a strict update-only "
                    "causal comparison"
                ),
            },
        },
        "branch_order": list(TRAINING_RUNS),
        "fp32_trigger": {
            "requires_bf16_runs_passed": list(TRAINING_RUNS[:2]),
            "may_skip_only_for": "insufficient_safe_budget_for_complete_fp32_closure",
        },
        "legacy_checkpoint": {
            "use": "no_update_diagnostic_only",
            "task_root": "/workspace/rondo-plan087-20260826-search01",
            "relative_path": (
                "formal-search/route-o-artifacts/recovery-checkpoints/"
                "checkpoint-attempt-000-step-000001"
            ),
            "bytes": 3_591_448_949,
            "content_sha256": LEGACY_CHECKPOINT_SHA256,
            "training_initialization_allowed": False,
        },
        "namespaces": {
            BF16_PRIMARY_RUN: "formal/bf16-seed-20260901",
            BF16_SECONDARY_RUN: "formal/bf16-seed-20260902",
            FP32_CONTROL_RUN: "formal/fp32-seed-20260901",
        },
        "budget": {
            "hard_limit_usd": 6.0,
            "formula": (
                "min(6 - conservative_task_cost, live_balance - known_unsettled "
                "- transfer_stop_and_short_volume_reserve)"
            ),
            "balance_cost_floor": (
                "max((stage_b_baseline_balance - baseline_unsettled) - "
                "(live_balance - known_unsettled), 0)"
            ),
            "full_branch_closure_required": True,
        },
        "retention": {
            "pass": [
                "exact_base_reference",
                "final_effective_candidate_checkpoint",
                "small_metrics_and_pair_margins",
                "fresh_process_recovery_receipt",
                "resource_terminal_state",
            ],
            "no_go": [
                "exact_base_reference",
                "decisive_negative_small_result",
                "small_metrics_and_pair_margins",
                "resource_terminal_state",
            ],
            "inconclusive": [
                "infrastructure_turning_point",
                "small_logs_and_cost_state",
                "resource_terminal_state",
            ],
        },
        "claims": {
            "unseen_evidence": False,
            "independent_cohort_generalization": False,
            "product_go": False,
            "m3_c1_or_m3_c2": False,
            "m3_d_unlocked": False,
        },
    }


def validate_freeze(value: Any) -> dict[str, Any]:
    expected = frozen_contract()
    if value != expected:
        raise FullModelTrainingError("plan090_freeze_drifted")
    for recipe in value["recipes"].values():
        validate_adaptive_recipe(recipe)
    TrainableScope.from_value(value["scope"])
    ControlPlan.from_value(value["control_plan"])
    ComparisonPolicy.from_value(value["comparison_policy"])
    return json.loads(json.dumps(expected))


def freeze_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(validate_freeze(value)))


def materialize_run_spec(
    freeze: Any, run_id: str, parameter_inventory: Any
) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    if run_id not in TRAINING_RUNS:
        raise FullModelTrainingError("plan090_run_id_invalid")
    inventory = _validate_inventory(parameter_inventory)
    expected_dtype = {
        "bfloat16": "torch.bfloat16",
        "float32": "torch.float32",
    }[contract["recipes"][run_id]["parameter_dtype"]]
    selected = {row["name"]: row for row in inventory["parameters"]}
    if any(selected[name]["dtype"] != expected_dtype for name in SCOPE_PARAMETER_NAMES):
        raise FullModelTrainingError("plan090_scope_dtype_mismatch")
    observed_elements = sum(
        selected[name]["elements"] for name in SCOPE_PARAMETER_NAMES
    )
    if observed_elements != SCOPE_PARAMETER_ELEMENTS:
        raise FullModelTrainingError("plan090_scope_elements_mismatch")
    value = {
        "schema": RUN_SPEC_SCHEMA,
        "freeze_sha256": freeze_sha256(contract),
        "run_id": run_id,
        "start_state": "exact_base",
        "artifact_namespace": contract["namespaces"][run_id],
        "recipe": contract["recipes"][run_id],
        "scope": contract["scope"],
        "control_plan": contract["control_plan"],
        "comparison_policy": contract["comparison_policy"],
        "report_threshold": contract["report_threshold"],
        "precision_contract": contract["precision"][
            contract["recipes"][run_id]["parameter_dtype"]
        ],
        "parameter_inventory_sha256": inventory["inventory_sha256"],
    }
    return validate_run_spec(value, freeze=contract)


def validate_run_spec(value: Any, *, freeze: Any) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "freeze_sha256",
        "run_id",
        "start_state",
        "artifact_namespace",
        "recipe",
        "scope",
        "control_plan",
        "comparison_policy",
        "report_threshold",
        "precision_contract",
        "parameter_inventory_sha256",
    }:
        raise FullModelTrainingError("plan090_run_spec_invalid")
    run_id = value.get("run_id")
    if (
        value.get("schema") != RUN_SPEC_SCHEMA
        or value.get("freeze_sha256") != freeze_sha256(contract)
        or run_id not in TRAINING_RUNS
        or value.get("start_state") != "exact_base"
        or value.get("artifact_namespace") != contract["namespaces"].get(run_id)
        or validate_adaptive_recipe(value.get("recipe"))
        != contract["recipes"].get(run_id)
        or TrainableScope.from_value(value.get("scope")).as_dict() != contract["scope"]
        or ControlPlan.from_value(value.get("control_plan")).as_dict()
        != contract["control_plan"]
        or ComparisonPolicy.from_value(value.get("comparison_policy")).as_dict()
        != contract["comparison_policy"]
        or value.get("report_threshold") != contract["report_threshold"]
        or value.get("precision_contract")
        != contract["precision"][value["recipe"]["parameter_dtype"]]
        or not _sha256(value.get("parameter_inventory_sha256"))
    ):
        raise FullModelTrainingError("plan090_run_spec_drifted")
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
        "projected_complete_branch_usd",
    }
    derived_fields = {
        "safe_available_usd",
        "remaining_task_headroom_usd",
        "remaining_account_headroom_usd",
        "action_headroom_usd",
        "balance_metered_cost_floor_usd",
        "complete_branch_authorized",
        "content_sha256",
    }
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("plan090_budget_snapshot_invalid")
    fields = set(value)
    if fields != base_fields and fields != base_fields | derived_fields:
        raise FullModelTrainingError("plan090_budget_snapshot_invalid")
    if value.get("schema") != BUDGET_SCHEMA or not _text(value.get("captured_at")):
        raise FullModelTrainingError("plan090_budget_snapshot_invalid")
    numbers = {
        key: _nonnegative(value.get(key))
        for key in base_fields
        if key not in {"schema", "captured_at"}
    }
    if (
        numbers["stage_b_baseline_known_unsettled_usd"]
        > numbers["stage_b_baseline_balance_usd"]
    ):
        raise FullModelTrainingError("plan090_budget_snapshot_invalid")
    balance_cost_floor = max(
        (
            numbers["stage_b_baseline_balance_usd"]
            - numbers["stage_b_baseline_known_unsettled_usd"]
        )
        - (numbers["live_balance_usd"] - numbers["known_unsettled_usd"]),
        0.0,
    )
    if numbers["conservative_task_cost_usd"] + 1e-12 < balance_cost_floor:
        raise FullModelTrainingError("plan090_budget_cost_floor_violated")
    safe_available = min(
        6.0,
        max(
            numbers["live_balance_usd"]
            - numbers["known_unsettled_usd"]
            - numbers["closure_reserve_usd"],
            0.0,
        ),
    )
    task_headroom = max(6.0 - numbers["conservative_task_cost_usd"], 0.0)
    account_headroom = max(
        numbers["live_balance_usd"]
        - numbers["known_unsettled_usd"]
        - numbers["closure_reserve_usd"],
        0.0,
    )
    action_headroom = min(task_headroom, account_headroom)
    core = {
        "schema": BUDGET_SCHEMA,
        "captured_at": value["captured_at"],
        **numbers,
        "safe_available_usd": safe_available,
        "remaining_task_headroom_usd": task_headroom,
        "remaining_account_headroom_usd": account_headroom,
        "action_headroom_usd": action_headroom,
        "balance_metered_cost_floor_usd": balance_cost_floor,
        "complete_branch_authorized": (
            numbers["projected_complete_branch_usd"] <= action_headroom + 1e-12
        ),
    }
    result = {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}
    if set(value) == base_fields | derived_fields and dict(value) != result:
        raise FullModelTrainingError("plan090_budget_snapshot_derived_drifted")
    return result


def _recipe(*, seed: int, parameter_dtype: str) -> dict[str, Any]:
    return {
        "schema": RECIPE_SCHEMA,
        "seed": seed,
        "optimizer": {
            "name": "torch.optim.AdamW",
            "learning_rate": 0.000005,
            "betas": [0.9, 0.999],
            "epsilon": 1e-8,
            "weight_decay": 0.0,
            "fused": True,
        },
        "scheduler": {"name": "constant"},
        "parameter_dtype": parameter_dtype,
        "binary_micro_batch_size": 1,
        "pair_micro_batch_size": 1,
        "gradient_clip_norm": 1.0,
        "activation_checkpointing": True,
        "attention_backend": "sdpa",
        "macro_update": "one_full_v8_train_cohort",
        "objective": {
            "scalar": "logits[:,0]",
            "direction": "preferred_minus_dispreferred",
            "binary_loss": "softplus(-signed_target*logits[:,0])",
            "pair_loss": "softplus(dispreferred-preferred)",
            "pair_margin": 0.0,
            "pair_temperature": 1.0,
            "component_weights": {
                "binary": 0.05,
                "boundary": 0.25,
                "within_pass": 0.7,
            },
        },
    }


def _validate_inventory(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not isinstance(
        value.get("parameters"), Sequence
    ):
        raise FullModelTrainingError("plan090_parameter_inventory_invalid")
    rows = value["parameters"]
    if isinstance(rows, (str, bytes, bytearray)) or any(
        not isinstance(row, Mapping)
        or not isinstance(row.get("name"), str)
        or not row["name"]
        or not isinstance(row.get("elements"), int)
        or isinstance(row["elements"], bool)
        or row["elements"] <= 0
        or not isinstance(row.get("dtype"), str)
        or not row["dtype"]
        for row in rows
    ):
        raise FullModelTrainingError("plan090_parameter_inventory_invalid")
    names = [str(row["name"]) for row in rows]
    if (
        len(names) != len(set(names))
        or any(name not in names for name in SCOPE_PARAMETER_NAMES)
        or value.get("parameter_tensors") != len(rows)
        or value.get("parameter_tensors") != 311
        or value.get("parameter_elements") != sum(int(row["elements"]) for row in rows)
        or value.get("parameter_elements") != 1_720_577_024
    ):
        raise FullModelTrainingError("plan090_parameter_inventory_invalid")
    identity_rows = [
        {"name": row["name"], "elements": row["elements"], "dtype": row["dtype"]}
        for row in rows
    ]
    observed_sha256 = sha256_bytes(canonical_json_bytes(identity_rows))
    if value.get("inventory_sha256") != observed_sha256:
        raise FullModelTrainingError("plan090_parameter_inventory_invalid")
    return json.loads(json.dumps(value))


def _nonnegative(value: Any) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise FullModelTrainingError("plan090_budget_snapshot_invalid")
    return float(value)


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = [
    "BF16_PRIMARY_RUN",
    "BF16_SECONDARY_RUN",
    "BUDGET_SCHEMA",
    "FP32_CONTROL_RUN",
    "FREEZE_SCHEMA",
    "RUN_SPEC_SCHEMA",
    "TRAINING_RUNS",
    "freeze_sha256",
    "frozen_contract",
    "materialize_run_spec",
    "validate_budget_snapshot",
    "validate_freeze",
    "validate_run_spec",
]
