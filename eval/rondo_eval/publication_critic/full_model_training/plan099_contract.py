"""Frozen identities, development gate, and dynamic budget for Plan 099."""

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..qualification import decision_implementation_identity
from ..successor_task import DIMENSION_CLASSES, HARD_DIMENSIONS
from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    regular_file,
    sha256_file,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PLAN_ROOT = Path("training/publication-critic-plan099")
MODEL_CONTRACT = PLAN_ROOT / "model-contract-v1.json"
RECIPE_CONTRACT = PLAN_ROOT / "recipe-v1.json"
DEVELOPMENT_GATE = PLAN_ROOT / "development-gate-v1.json"
RESOURCE_CONTRACT = PLAN_ROOT / "resource-contract-v1.json"
ASSET_CONTRACT = PLAN_ROOT / "asset-contract-v1.json"
FREEZE_LOCK = PLAN_ROOT / "freeze-lock-v1.json"
V10_ROOT = Path("training/publication-critic-v10")
V10_MANIFEST_SHA256 = "61498f2f8580eab7dda59df0e2dba9bf5700c168e33f41bfec5cbdf3bd5041a4"
V10_TRAIN_CANDIDATES_SHA256 = (
    "d19b53adfafb1948c4e60e7e4cc1905c0b11a0ae37bc7e983638b9fb5919179b"
)
V10_TRAIN_PAIRS_SHA256 = (
    "ae161b1033b8fb9a51ef3450281d3940411f7bf5e97a80888cc893cecd566ba8"
)
V10_VALIDATION_CANDIDATES_SHA256 = (
    "20c545469a3c1972e90d4c587fc114845000a2c938c21bea95e42eeb94602508"
)
V10_VALIDATION_PAIRS_SHA256 = (
    "4b0fe7c7f8148b5c5d9b12fdfe9e2055c6b46e4c9cdb30e2058be0d13224edfd"
)
MODEL_REPOSITORY = "Skywork/Skywork-Reward-V2-Qwen3-1.7B"
MODEL_REVISION = "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc"
MODEL_WEIGHT_SHA256 = "117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9"
FREEZE_SCHEMA = "rondo-publication-critic-plan099-freeze-lock-v1"
BUDGET_SCHEMA = "rondo-publication-critic-plan099-budget-snapshot-v1"
SEGMENT_SCHEMA = "rondo-publication-critic-plan099-paid-segment-authorization-v1"
LIVE_RESOURCE_SCHEMA = "rondo-publication-critic-plan099-live-resource-receipt-v1"
LIFECYCLE_SCHEMA = "rondo-publication-critic-plan099-pod-lifecycle-authorization-v1"
ASSESSMENT_SCHEMA = "rondo-publication-critic-plan099-development-assessment-v1"
WORKER_KILL_GRACE_SECONDS = 60
TERMINAL_CONFIRMATION_SECONDS = 360
MAXIMUM_TASK_POD_WALL_SECONDS = 10800
MAXIMUM_RUNTIME_CONTROL_BYTES = 16 * 1024
# CUDA reports usable device memory, not the vendor's nominal decimal 48 GB.
# The exact GPU identity remains mandatory; this lower bound only avoids treating
# a real L40S as if it had to expose 48 GiB of addressable memory.
MINIMUM_L40S_VISIBLE_MEMORY_BYTES = 44 * 1024**3
RUNTIME_CONTROL_ROLES = {
    "live-resource": LIVE_RESOURCE_SCHEMA,
    "lifecycle": LIFECYCLE_SCHEMA,
    "segment": SEGMENT_SCHEMA,
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_MINIMUM_FAILURE_RECALL = {
    "useful_state_transfer": Fraction(2, 3),
    "honest_uncertainty": Fraction(4, 5),
    "conditional_continuity": Fraction(2, 3),
    "scope_and_signal": Fraction(2, 3),
    "internal_consistency": Fraction(3, 4),
}


def load_freeze(repo_root: Path | str = REPO_ROOT) -> dict[str, Any]:
    """Load the only accepted Phase-B recipe after checking its byte lock."""

    root = Path(repo_root)
    lock = read_json(root / FREEZE_LOCK)
    if not isinstance(lock, Mapping) or set(lock) != {
        "schema",
        "algorithm",
        "components",
        "bundle_sha256",
    }:
        raise FullModelTrainingError("plan099_freeze_lock_invalid")
    if (
        lock.get("schema") != FREEZE_SCHEMA
        or lock.get("algorithm") != "sha256-canonical-component-list-v1"
        or not isinstance(lock.get("components"), list)
    ):
        raise FullModelTrainingError("plan099_freeze_lock_invalid")
    expected_paths = [
        MODEL_CONTRACT.as_posix(),
        RECIPE_CONTRACT.as_posix(),
        DEVELOPMENT_GATE.as_posix(),
        RESOURCE_CONTRACT.as_posix(),
        ASSET_CONTRACT.as_posix(),
        "training/publication-critic-plan099/dependencies-v1.txt",
        "training/publication-critic-plan099/runbook.md",
        "training/publication-critic-plan099/runpod-bootstrap.sh",
        "training/publication-critic-plan099/runpod-release.py",
        "training/publication-critic-plan099/runpod-worker.sh",
        "training/publication-critic-plan094/runpod-lifecycle-guard.py",
        "training/publication-critic-plan087/runpod-terminal.py",
        "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json",
        "doc/rondo-multi-publication-critic-task-contract-v2.md",
        "doc/rondo-multi-publication-critic-decision-contract-v1.md",
        "eval/templates/publication-critic/input-contract-v3.md",
        "eval/templates/publication-critic/qualification-rubric-v2.md",
        "eval/templates/publication-critic/render-contract-v4.json",
        "eval/templates/publication-critic/successor-output-schema-v1.json",
        "eval/templates/publication-critic/decision-implementation-lock-v1.json",
        "eval/rondo_eval/publication_critic/successor_task.py",
        "eval/rondo_eval/publication_critic/qualification.py",
        "eval/rondo_eval/publication_critic/directional_data.py",
        "eval/rondo_eval/publication_critic/full_model_training/plan099_artifacts.py",
        "eval/rondo_eval/publication_critic/full_model_training/plan099_bundle.py",
        "eval/rondo_eval/publication_critic/full_model_training/plan099_cli.py",
        "eval/rondo_eval/publication_critic/full_model_training/plan099_contract.py",
        "eval/rondo_eval/publication_critic/full_model_training/plan099_data.py",
        "eval/rondo_eval/publication_critic/full_model_training/plan099_model.py",
        "eval/rondo_eval/publication_critic/full_model_training/plan099_objective.py",
        "eval/rondo_eval/publication_critic/full_model_training/plan099_training.py",
    ]
    components: list[dict[str, str]] = []
    for index, value in enumerate(lock["components"]):
        if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
            raise FullModelTrainingError("plan099_freeze_component_invalid")
        path = value.get("path")
        digest = value.get("sha256")
        if index >= len(expected_paths) or path != expected_paths[index]:
            raise FullModelTrainingError("plan099_freeze_component_order_invalid")
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise FullModelTrainingError("plan099_freeze_component_invalid")
        if sha256_file(root / path) != digest:
            raise FullModelTrainingError("plan099_freeze_component_drifted", path)
        components.append({"path": path, "sha256": digest})
    if len(components) != len(expected_paths):
        raise FullModelTrainingError("plan099_freeze_component_order_invalid")
    bundle_sha256 = hashlib.sha256(canonical_json_bytes(components)).hexdigest()
    if lock.get("bundle_sha256") != bundle_sha256:
        raise FullModelTrainingError("plan099_freeze_bundle_drifted")

    model = _validate_model_contract(read_json(root / MODEL_CONTRACT), root)
    recipe = _validate_recipe(read_json(root / RECIPE_CONTRACT))
    gate = _validate_development_gate(read_json(root / DEVELOPMENT_GATE))
    resource = _validate_resource_contract(read_json(root / RESOURCE_CONTRACT))
    assets = _validate_asset_contract(read_json(root / ASSET_CONTRACT))
    decision = decision_implementation_identity(root)
    if decision["bundle_sha256"] != (
        "9ef18b6c04a63fd1b3285e69ccf2616f3c22f2558802f01794573e2e07d7afef"
    ):
        raise FullModelTrainingError("plan099_decision_identity_drifted")
    _validate_v10_identity(root)
    return {
        "schema": "rondo-publication-critic-plan099-freeze-v1",
        "freeze_bundle_sha256": bundle_sha256,
        "model": model,
        "recipe": recipe,
        "development_gate": gate,
        "resource": resource,
        "assets": assets,
        "data": {
            "revision": "publication-critic-v10",
            "manifest_sha256": V10_MANIFEST_SHA256,
            "train_candidates_sha256": V10_TRAIN_CANDIDATES_SHA256,
            "train_pairs_sha256": V10_TRAIN_PAIRS_SHA256,
            "validation_candidates_sha256": V10_VALIDATION_CANDIDATES_SHA256,
            "validation_pairs_sha256": V10_VALIDATION_PAIRS_SHA256,
        },
        "decision_implementation": decision,
    }


def freeze_sha256(repo_root: Path | str = REPO_ROOT) -> str:
    return hashlib.sha256(canonical_json_bytes(load_freeze(repo_root))).hexdigest()


def decision_margin_grid(gate: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    checked = _validate_development_gate(gate)
    grid = checked["decision_grid"]
    result = []
    for pass_margin in grid["shared_pass_over_fail_margins"]:
        for na_margin in grid["continuity_na_over_applicable_margins"]:
            heads = {
                dimension: {"pass_over_fail_margin": float(pass_margin)}
                for dimension in HARD_DIMENSIONS
                if dimension != "conditional_continuity"
            }
            heads["conditional_continuity"] = {
                "pass_over_fail_margin": float(pass_margin),
                "na_over_applicable_margin": float(na_margin),
            }
            result.append(heads)
    if len(result) != grid["candidate_count"]:
        raise FullModelTrainingError("plan099_decision_grid_invalid")
    return tuple(result)


def assess_development_checkpoint(
    *,
    metrics: Mapping[str, Any],
    pair_evaluation: Mapping[str, Any],
    predicted_rows: Sequence[Mapping[str, Any]],
    training_loss: float,
) -> dict[str, Any]:
    """Apply the pre-result admission gate without reading any test split."""

    gate = _validate_development_gate(read_json(REPO_ROOT / DEVELOPMENT_GATE))
    if not math.isfinite(training_loss):
        raise FullModelTrainingError("plan099_training_loss_nonfinite")
    if len(predicted_rows) != gate["validation"]["candidate_rows"]:
        raise FullModelTrainingError("plan099_prediction_rows_invalid")
    checked_metrics = _validate_metrics(metrics, gate)
    pair_closed = _pair_closed(pair_evaluation, gate["validation"]["pair_rows"])
    predicted_support = {
        dimension: sorted({str(row[dimension]) for row in predicted_rows})
        for dimension in HARD_DIMENSIONS
    }
    required_support = gate["eligibility"]["required_predicted_classes"]
    checks = {
        "all_validation_pairs_closed": pair_closed,
        "gate_false_pass": checked_metrics["gate"]["false_pass"]
        <= gate["eligibility"]["maximum_gate_false_pass"],
        "gate_false_rewrite": checked_metrics["gate"]["false_rewrite"]
        <= gate["eligibility"]["maximum_gate_false_rewrite"],
        "gate_balanced_accuracy": _gate_balanced_accuracy(checked_metrics)
        >= Fraction(3, 4),
        "failure_recall": all(
            _failure_recall_fraction(checked_metrics, dimension)
            >= _MINIMUM_FAILURE_RECALL[dimension]
            for dimension in HARD_DIMENSIONS
        ),
        "continuity_na_recall": _class_recall_fraction(
            checked_metrics, "conditional_continuity", "N/A"
        )
        >= Fraction(2, 3),
        "supported_class_macro_recall": all(
            _macro_recall_fraction(checked_metrics, dimension) >= Fraction(3, 5)
            for dimension in HARD_DIMENSIONS
        ),
        "non_collapsed": all(
            predicted_support[dimension] == sorted(required_support[dimension])
            for dimension in HARD_DIMENSIONS
        ),
        "training_loss_finite": True,
    }
    return {
        "schema": ASSESSMENT_SCHEMA,
        "eligible": all(checks.values()),
        "checks": checks,
        "metrics": json.loads(json.dumps(checked_metrics)),
        "pair_evaluation": json.loads(json.dumps(pair_evaluation)),
        "predicted_support": predicted_support,
        "training_loss": float(training_loss),
    }


def checkpoint_selection_key(
    assessment: Mapping[str, Any],
    *,
    global_step: int,
    decision_config_sha256: str,
    checkpoint_content_sha256: str,
) -> tuple[Any, ...]:
    """Return an exact deterministic key; larger values are preferred."""

    if (
        not isinstance(assessment, Mapping)
        or assessment.get("schema") != ASSESSMENT_SCHEMA
        or not isinstance(global_step, int)
        or isinstance(global_step, bool)
        or global_step <= 0
        or _SHA256.fullmatch(decision_config_sha256) is None
        or _SHA256.fullmatch(checkpoint_content_sha256) is None
    ):
        raise FullModelTrainingError("plan099_selection_input_invalid")
    metrics = assessment["metrics"]
    recalls = tuple(
        _macro_recall_fraction(metrics, dimension) for dimension in HARD_DIMENSIONS
    )
    correct_sum = sum(
        int(metrics["per_dimension"][dimension]["correct"])
        for dimension in HARD_DIMENSIONS
    )
    # Reverse hashes so max() implements the contract's ascending SHA tie-break.
    reverse_config = tuple(-int(character, 16) for character in decision_config_sha256)
    reverse_checkpoint = tuple(
        -int(character, 16) for character in checkpoint_content_sha256
    )
    return (
        bool(assessment["eligible"]),
        min(recalls),
        -int(metrics["gate"]["false_pass"]),
        int(metrics["gate"]["correct"]),
        -int(metrics["gate"]["false_rewrite"]),
        correct_sum,
        -global_step,
        reverse_config,
        reverse_checkpoint,
    )


def validate_budget_snapshot(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "captured_at",
        "stage_b_baseline_available_balance_usd",
        "stage_b_baseline_known_unsettled_usd",
        "stage_b_baseline_volume_rate_usd_per_hour",
        "stage_b_dynamic_budget_usd",
        "current_available_balance_usd",
        "current_known_unsettled_usd",
        "current_volume_rate_usd_per_hour",
        "conservative_task_cost_usd",
        "closure_reserve_usd",
        "next_action",
    }
    if not isinstance(value, Mapping) or set(value) not in {
        frozenset(required),
        frozenset(required | {"content_sha256"}),
    }:
        raise FullModelTrainingError("plan099_budget_snapshot_invalid")
    if value.get("schema") != BUDGET_SCHEMA:
        raise FullModelTrainingError("plan099_budget_snapshot_invalid")
    _timestamp(value.get("captured_at"), "plan099_budget_timestamp_invalid")
    numbers = {
        key: _nonnegative(value.get(key), "plan099_budget_value_invalid")
        for key in required
        if key.endswith(("_usd", "_usd_per_hour"))
    }
    expected_budget = max(
        numbers["stage_b_baseline_available_balance_usd"]
        - numbers["stage_b_baseline_known_unsettled_usd"]
        - 6.0 * numbers["stage_b_baseline_volume_rate_usd_per_hour"],
        0.0,
    )
    if not math.isclose(
        numbers["stage_b_dynamic_budget_usd"],
        expected_budget,
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise FullModelTrainingError("plan099_dynamic_budget_invalid")
    if numbers["conservative_task_cost_usd"] > expected_budget + 1e-9:
        raise FullModelTrainingError("plan099_budget_exhausted")
    current_spendable = max(
        numbers["current_available_balance_usd"]
        - numbers["current_known_unsettled_usd"]
        - 6.0 * numbers["current_volume_rate_usd_per_hour"],
        0.0,
    )
    if numbers["closure_reserve_usd"] > current_spendable + 1e-9:
        raise FullModelTrainingError("plan099_closure_reserve_unfunded")
    if not isinstance(value.get("next_action"), str) or not value["next_action"]:
        raise FullModelTrainingError("plan099_budget_action_invalid")
    core = {key: value[key] for key in required}
    result = {
        **core,
        "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
    }
    if "content_sha256" in value and dict(value) != result:
        raise FullModelTrainingError("plan099_budget_snapshot_drifted")
    return json.loads(json.dumps(result))


def create_budget_snapshot(
    *,
    captured_at: str,
    stage_b_baseline_available_balance_usd: float,
    stage_b_baseline_known_unsettled_usd: float,
    stage_b_baseline_volume_rate_usd_per_hour: float,
    current_available_balance_usd: float,
    current_known_unsettled_usd: float,
    current_volume_rate_usd_per_hour: float,
    conservative_task_cost_usd: float,
    closure_reserve_usd: float,
    next_action: str,
) -> dict[str, Any]:
    """Create the canonical budget input instead of accepting hand-built JSON."""

    dynamic_budget = max(
        float(stage_b_baseline_available_balance_usd)
        - float(stage_b_baseline_known_unsettled_usd)
        - 6.0 * float(stage_b_baseline_volume_rate_usd_per_hour),
        0.0,
    )
    return validate_budget_snapshot(
        {
            "schema": BUDGET_SCHEMA,
            "captured_at": captured_at,
            "stage_b_baseline_available_balance_usd": stage_b_baseline_available_balance_usd,
            "stage_b_baseline_known_unsettled_usd": stage_b_baseline_known_unsettled_usd,
            "stage_b_baseline_volume_rate_usd_per_hour": stage_b_baseline_volume_rate_usd_per_hour,
            "stage_b_dynamic_budget_usd": dynamic_budget,
            "current_available_balance_usd": current_available_balance_usd,
            "current_known_unsettled_usd": current_known_unsettled_usd,
            "current_volume_rate_usd_per_hour": current_volume_rate_usd_per_hour,
            "conservative_task_cost_usd": conservative_task_cost_usd,
            "closure_reserve_usd": closure_reserve_usd,
            "next_action": next_action,
        }
    )


def create_live_resource_receipt(
    *,
    captured_at: str,
    provider: str,
    cloud_type: str,
    data_center_id: str,
    pod_id: str,
    pod_name: str,
    pod_started_at: str,
    account_task_pod_count: int,
    task_cumulative_pods_created: int,
    task_prior_pod_wall_seconds: int,
    gpu_name: str,
    gpu_count: int,
    gpu_total_memory_bytes: int,
    compute_rate_usd_per_hour: float,
    container_rate_usd_per_hour: float,
    container_disk_gb: int,
    image_identity: str,
    volume_id: str,
    volume_mount_path: str,
    volume_size_gb: float,
) -> dict[str, Any]:
    """Create and validate the only uploadable live-resource receipt bytes."""

    core = {
        "schema": LIVE_RESOURCE_SCHEMA,
        "captured_at": captured_at,
        "provider": provider,
        "cloud_type": cloud_type,
        "data_center_id": data_center_id,
        "pod_id": pod_id,
        "pod_name": pod_name,
        "pod_started_at": pod_started_at,
        "account_task_pod_count": account_task_pod_count,
        "task_cumulative_pods_created": task_cumulative_pods_created,
        "task_prior_pod_wall_seconds": task_prior_pod_wall_seconds,
        "gpu_name": gpu_name,
        "gpu_count": gpu_count,
        "gpu_total_memory_bytes": gpu_total_memory_bytes,
        "compute_rate_usd_per_hour": compute_rate_usd_per_hour,
        "container_rate_usd_per_hour": container_rate_usd_per_hour,
        "container_disk_gb": container_disk_gb,
        "image_identity": image_identity,
        "volume_id": volume_id,
        "volume_mount_path": volume_mount_path,
        "volume_size_gb": volume_size_gb,
    }
    return validate_live_resource_receipt(
        {
            **core,
            "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
        }
    )


def validate_live_resource_receipt(value: Any) -> dict[str, Any]:
    fields = {
        "schema",
        "captured_at",
        "provider",
        "cloud_type",
        "data_center_id",
        "pod_id",
        "pod_name",
        "pod_started_at",
        "account_task_pod_count",
        "task_cumulative_pods_created",
        "task_prior_pod_wall_seconds",
        "gpu_name",
        "gpu_count",
        "gpu_total_memory_bytes",
        "compute_rate_usd_per_hour",
        "container_rate_usd_per_hour",
        "container_disk_gb",
        "image_identity",
        "volume_id",
        "volume_mount_path",
        "volume_size_gb",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise FullModelTrainingError("plan099_live_resource_receipt_invalid")
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    _timestamp(value.get("captured_at"), "plan099_live_resource_receipt_invalid")
    _timestamp(value.get("pod_started_at"), "plan099_live_resource_receipt_invalid")
    compute = _nonnegative(
        value.get("compute_rate_usd_per_hour"),
        "plan099_live_resource_receipt_invalid",
    )
    _nonnegative(
        value.get("container_rate_usd_per_hour"),
        "plan099_live_resource_receipt_invalid",
    )
    volume_size = _nonnegative(
        value.get("volume_size_gb"), "plan099_live_resource_receipt_invalid"
    )
    prior_wall = value.get("task_prior_pod_wall_seconds")
    if (
        value.get("schema") != LIVE_RESOURCE_SCHEMA
        or value.get("content_sha256")
        != hashlib.sha256(canonical_json_bytes(core)).hexdigest()
        or value.get("provider") != "RunPod"
        or value.get("cloud_type") != "SECURE"
        or value.get("data_center_id") != "US-TX-3"
        or not isinstance(value.get("pod_id"), str)
        or _IDENTIFIER.fullmatch(value["pod_id"]) is None
        or not isinstance(value.get("pod_name"), str)
        or not value["pod_name"].startswith("rondo-plan099-")
        or value.get("account_task_pod_count") != 1
        or value.get("task_cumulative_pods_created") not in {1, 2}
        or not isinstance(prior_wall, int)
        or isinstance(prior_wall, bool)
        or prior_wall < 0
        or prior_wall > 10800
        or value.get("gpu_name") != "NVIDIA L40S"
        or value.get("gpu_count") != 1
        or not isinstance(value.get("gpu_total_memory_bytes"), int)
        or isinstance(value.get("gpu_total_memory_bytes"), bool)
        or value["gpu_total_memory_bytes"] < MINIMUM_L40S_VISIBLE_MEMORY_BYTES
        or compute <= 0.0
        or value.get("container_disk_gb") != 20
        or value.get("image_identity")
        != "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
        or value.get("volume_id") != "mwemzrn33y"
        or value.get("volume_mount_path") != "/workspace"
        or volume_size > 100.0
    ):
        raise FullModelTrainingError("plan099_live_resource_receipt_invalid")
    return json.loads(json.dumps(value))


def authorize_pod_lifecycle(
    budget_snapshot: Any,
    resource_receipt: Any,
    *,
    maximum_lifecycle_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    budget = validate_budget_snapshot(budget_snapshot)
    resource = validate_live_resource_receipt(resource_receipt)
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    captured = _timestamp(budget["captured_at"], "plan099_lifecycle_invalid")
    resource_captured = _timestamp(resource["captured_at"], "plan099_lifecycle_invalid")
    started = _timestamp(resource["pod_started_at"], "plan099_lifecycle_invalid")
    if (
        not isinstance(maximum_lifecycle_seconds, int)
        or isinstance(maximum_lifecycle_seconds, bool)
        or maximum_lifecycle_seconds <= 0
        or not -30.0 <= (observed - captured).total_seconds() <= 300.0
        or not -30.0 <= (observed - resource_captured).total_seconds() <= 300.0
        or not -30.0 <= (observed - started).total_seconds() <= 300.0
    ):
        raise FullModelTrainingError("plan099_lifecycle_invalid")
    billable_seconds = (
        maximum_lifecycle_seconds
        + WORKER_KILL_GRACE_SECONDS
        + TERMINAL_CONFIRMATION_SECONDS
    )
    cumulative_billable_seconds = (
        resource["task_prior_pod_wall_seconds"] + billable_seconds
    )
    if cumulative_billable_seconds > MAXIMUM_TASK_POD_WALL_SECONDS:
        raise FullModelTrainingError("plan099_lifecycle_invalid")
    rate = float(resource["compute_rate_usd_per_hour"]) + float(
        resource["container_rate_usd_per_hour"]
    )
    lifecycle_cost = rate * billable_seconds / 3600.0
    upper_bound = (
        float(budget["conservative_task_cost_usd"])
        + lifecycle_cost
        + float(budget["closure_reserve_usd"])
    )
    _require_budget_capacity(budget, lifecycle_cost, upper_bound)
    trigger = started + timedelta(
        seconds=maximum_lifecycle_seconds + WORKER_KILL_GRACE_SECONDS
    )
    core = {
        "schema": LIFECYCLE_SCHEMA,
        "authorized_at": observed.isoformat().replace("+00:00", "Z"),
        "budget_snapshot_sha256": budget["content_sha256"],
        "live_resource_receipt_sha256": resource["content_sha256"],
        "pod_id": resource["pod_id"],
        "pod_name": resource["pod_name"],
        "pod_started_at": resource["pod_started_at"],
        "task_prior_pod_wall_seconds": resource["task_prior_pod_wall_seconds"],
        "maximum_lifecycle_seconds": maximum_lifecycle_seconds,
        "termination_trigger_at": trigger.isoformat().replace("+00:00", "Z"),
        "worker_kill_grace_seconds": WORKER_KILL_GRACE_SECONDS,
        "terminal_confirmation_seconds": TERMINAL_CONFIRMATION_SECONDS,
        "billable_seconds_upper_bound": billable_seconds,
        "cumulative_billable_seconds_upper_bound": cumulative_billable_seconds,
        "compute_rate_usd_per_hour": float(resource["compute_rate_usd_per_hour"]),
        "container_rate_usd_per_hour": float(resource["container_rate_usd_per_hour"]),
        "lifecycle_cost_upper_bound_usd": lifecycle_cost,
        "closure_reserve_usd": float(budget["closure_reserve_usd"]),
        "task_cost_and_closure_upper_bound_usd": upper_bound,
    }
    return {
        **core,
        "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
    }


def validate_pod_lifecycle_authorization(value: Any) -> dict[str, Any]:
    fields = {
        "schema",
        "authorized_at",
        "budget_snapshot_sha256",
        "live_resource_receipt_sha256",
        "pod_id",
        "pod_name",
        "pod_started_at",
        "task_prior_pod_wall_seconds",
        "maximum_lifecycle_seconds",
        "termination_trigger_at",
        "worker_kill_grace_seconds",
        "terminal_confirmation_seconds",
        "billable_seconds_upper_bound",
        "cumulative_billable_seconds_upper_bound",
        "compute_rate_usd_per_hour",
        "container_rate_usd_per_hour",
        "lifecycle_cost_upper_bound_usd",
        "closure_reserve_usd",
        "task_cost_and_closure_upper_bound_usd",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise FullModelTrainingError("plan099_lifecycle_invalid")
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    started = _timestamp(value.get("pod_started_at"), "plan099_lifecycle_invalid")
    trigger = _timestamp(
        value.get("termination_trigger_at"), "plan099_lifecycle_invalid"
    )
    _timestamp(value.get("authorized_at"), "plan099_lifecycle_invalid")
    maximum = value.get("maximum_lifecycle_seconds")
    prior_wall = value.get("task_prior_pod_wall_seconds")
    if (
        not isinstance(maximum, int)
        or isinstance(maximum, bool)
        or not isinstance(prior_wall, int)
        or isinstance(prior_wall, bool)
    ):
        raise FullModelTrainingError("plan099_lifecycle_invalid")
    billable = maximum + WORKER_KILL_GRACE_SECONDS + TERMINAL_CONFIRMATION_SECONDS
    cumulative_billable = prior_wall + billable
    compute = _nonnegative(
        value.get("compute_rate_usd_per_hour"), "plan099_lifecycle_invalid"
    )
    container = _nonnegative(
        value.get("container_rate_usd_per_hour"), "plan099_lifecycle_invalid"
    )
    expected_cost = (compute + container) * billable / 3600.0
    if (
        value.get("schema") != LIFECYCLE_SCHEMA
        or value.get("content_sha256")
        != hashlib.sha256(canonical_json_bytes(core)).hexdigest()
        or _SHA256.fullmatch(str(value.get("budget_snapshot_sha256"))) is None
        or _SHA256.fullmatch(str(value.get("live_resource_receipt_sha256"))) is None
        or not isinstance(value.get("pod_name"), str)
        or not value["pod_name"].startswith("rondo-plan099-")
        or maximum <= 0
        or prior_wall < 0
        or cumulative_billable > MAXIMUM_TASK_POD_WALL_SECONDS
        or trigger != started + timedelta(seconds=maximum + WORKER_KILL_GRACE_SECONDS)
        or value.get("worker_kill_grace_seconds") != WORKER_KILL_GRACE_SECONDS
        or value.get("terminal_confirmation_seconds") != TERMINAL_CONFIRMATION_SECONDS
        or value.get("billable_seconds_upper_bound") != billable
        or value.get("cumulative_billable_seconds_upper_bound") != cumulative_billable
        or not math.isclose(
            float(value.get("lifecycle_cost_upper_bound_usd", -1)),
            expected_cost,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    ):
        raise FullModelTrainingError("plan099_lifecycle_invalid")
    return json.loads(json.dumps(value))


def authorize_paid_segment(
    budget_snapshot: Any,
    lifecycle_authorization: Any,
    *,
    maximum_seconds: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    budget = validate_budget_snapshot(budget_snapshot)
    lifecycle = validate_pod_lifecycle_authorization(lifecycle_authorization)
    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    captured = _timestamp(
        budget["captured_at"], "plan099_segment_authorization_invalid"
    )
    termination = _timestamp(
        lifecycle["termination_trigger_at"], "plan099_segment_authorization_invalid"
    )
    if (
        not isinstance(maximum_seconds, int)
        or isinstance(maximum_seconds, bool)
        or maximum_seconds <= 0
        or maximum_seconds > 10800
        or not -30.0 <= (observed - captured).total_seconds() <= 300.0
        or observed + timedelta(seconds=maximum_seconds + WORKER_KILL_GRACE_SECONDS)
        > termination
    ):
        raise FullModelTrainingError("plan099_segment_duration_invalid")
    compute = float(lifecycle["compute_rate_usd_per_hour"])
    container = float(lifecycle["container_rate_usd_per_hour"])
    billed_seconds = (
        maximum_seconds + WORKER_KILL_GRACE_SECONDS + TERMINAL_CONFIRMATION_SECONDS
    )
    segment_cost = (compute + container) * billed_seconds / 3600.0
    upper_bound = (
        float(budget["conservative_task_cost_usd"])
        + segment_cost
        + float(budget["closure_reserve_usd"])
    )
    _require_budget_capacity(budget, segment_cost, upper_bound)
    core = {
        "schema": SEGMENT_SCHEMA,
        "authorized_at": observed.isoformat().replace("+00:00", "Z"),
        "budget_snapshot_sha256": budget["content_sha256"],
        "pod_lifecycle_authorization_sha256": lifecycle["content_sha256"],
        "pod_id": lifecycle["pod_id"],
        "pod_name": lifecycle["pod_name"],
        "termination_trigger_at": lifecycle["termination_trigger_at"],
        "maximum_seconds": maximum_seconds,
        "worker_kill_grace_seconds": WORKER_KILL_GRACE_SECONDS,
        "terminal_confirmation_seconds": TERMINAL_CONFIRMATION_SECONDS,
        "billable_seconds_upper_bound": billed_seconds,
        "compute_rate_usd_per_hour": compute,
        "container_rate_usd_per_hour": container,
        "segment_cost_upper_bound_usd": segment_cost,
        "closure_reserve_usd": float(budget["closure_reserve_usd"]),
        "task_cost_and_closure_upper_bound_usd": upper_bound,
    }
    return {
        **core,
        "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
    }


def validate_paid_segment_authorization(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "authorized_at",
        "budget_snapshot_sha256",
        "pod_lifecycle_authorization_sha256",
        "pod_id",
        "pod_name",
        "termination_trigger_at",
        "maximum_seconds",
        "worker_kill_grace_seconds",
        "terminal_confirmation_seconds",
        "billable_seconds_upper_bound",
        "compute_rate_usd_per_hour",
        "container_rate_usd_per_hour",
        "segment_cost_upper_bound_usd",
        "closure_reserve_usd",
        "task_cost_and_closure_upper_bound_usd",
        "content_sha256",
    }:
        raise FullModelTrainingError("plan099_segment_authorization_invalid")
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    _timestamp(value.get("authorized_at"), "plan099_segment_authorization_invalid")
    _timestamp(
        value.get("termination_trigger_at"), "plan099_segment_authorization_invalid"
    )
    maximum = value.get("maximum_seconds")
    if not isinstance(maximum, int) or isinstance(maximum, bool):
        raise FullModelTrainingError("plan099_segment_authorization_invalid")
    billed = maximum + WORKER_KILL_GRACE_SECONDS + TERMINAL_CONFIRMATION_SECONDS
    compute = _nonnegative(
        value.get("compute_rate_usd_per_hour"),
        "plan099_segment_authorization_invalid",
    )
    container = _nonnegative(
        value.get("container_rate_usd_per_hour"),
        "plan099_segment_authorization_invalid",
    )
    expected_cost = (compute + container) * billed / 3600.0
    if (
        value.get("schema") != SEGMENT_SCHEMA
        or value.get("worker_kill_grace_seconds") != WORKER_KILL_GRACE_SECONDS
        or value.get("terminal_confirmation_seconds") != TERMINAL_CONFIRMATION_SECONDS
        or value.get("billable_seconds_upper_bound") != billed
        or maximum <= 0
        or maximum > 10800
        or _SHA256.fullmatch(str(value.get("budget_snapshot_sha256"))) is None
        or _SHA256.fullmatch(str(value.get("pod_lifecycle_authorization_sha256")))
        is None
        or not isinstance(value.get("pod_name"), str)
        or not value["pod_name"].startswith("rondo-plan099-")
        or not math.isclose(
            float(value.get("segment_cost_upper_bound_usd", -1)),
            expected_cost,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        or value.get("content_sha256")
        != hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    ):
        raise FullModelTrainingError("plan099_segment_authorization_invalid")
    for key in (
        "compute_rate_usd_per_hour",
        "container_rate_usd_per_hour",
        "segment_cost_upper_bound_usd",
        "closure_reserve_usd",
        "task_cost_and_closure_upper_bound_usd",
    ):
        _nonnegative(value.get(key), "plan099_segment_authorization_invalid")
    return json.loads(json.dumps(value))


def validate_runtime_control_file(
    role: str,
    path: Path | str,
    task_root: Path | str,
) -> dict[str, Any]:
    """Validate one of the three exact host-to-Pod runtime JSON controls."""

    if role not in RUNTIME_CONTROL_ROLES:
        raise FullModelTrainingError("plan099_runtime_control_invalid")
    root = Path(task_root).resolve(strict=True)
    candidate = Path(path)
    file_path = regular_file(candidate, maximum_bytes=MAXIMUM_RUNTIME_CONTROL_BYTES)
    resolved = file_path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise FullModelTrainingError("plan099_runtime_control_invalid") from exc
    raw = file_path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FullModelTrainingError("plan099_runtime_control_invalid") from exc
    validators = {
        "live-resource": validate_live_resource_receipt,
        "lifecycle": validate_pod_lifecycle_authorization,
        "segment": validate_paid_segment_authorization,
    }
    validated = validators[role](value)
    expected = Path("runtime-control") / role / (f"{validated['content_sha256']}.json")
    if (
        relative != expected
        or candidate.absolute() != root / expected
        or raw != pretty_json_bytes(validated)
        or (file_path.stat().st_mode & 0o777) != 0o600
    ):
        raise FullModelTrainingError("plan099_runtime_control_invalid")
    return validated


def validate_runtime_control_chain(
    resource: Any,
    lifecycle: Any,
    segment: Any,
) -> dict[str, dict[str, Any]]:
    """Validate the cross-hashes and immutable resource values for a worker call."""

    checked_resource = validate_live_resource_receipt(resource)
    checked_lifecycle = validate_pod_lifecycle_authorization(lifecycle)
    checked_segment = validate_paid_segment_authorization(segment)
    if (
        checked_lifecycle["live_resource_receipt_sha256"]
        != checked_resource["content_sha256"]
        or checked_lifecycle["pod_id"] != checked_resource["pod_id"]
        or checked_lifecycle["pod_name"] != checked_resource["pod_name"]
        or checked_lifecycle["task_prior_pod_wall_seconds"]
        != checked_resource["task_prior_pod_wall_seconds"]
        or checked_lifecycle["compute_rate_usd_per_hour"]
        != checked_resource["compute_rate_usd_per_hour"]
        or checked_lifecycle["container_rate_usd_per_hour"]
        != checked_resource["container_rate_usd_per_hour"]
        or checked_segment["pod_lifecycle_authorization_sha256"]
        != checked_lifecycle["content_sha256"]
        or checked_segment["pod_id"] != checked_lifecycle["pod_id"]
        or checked_segment["pod_name"] != checked_lifecycle["pod_name"]
        or checked_segment["termination_trigger_at"]
        != checked_lifecycle["termination_trigger_at"]
        or checked_segment["compute_rate_usd_per_hour"]
        != checked_lifecycle["compute_rate_usd_per_hour"]
        or checked_segment["container_rate_usd_per_hour"]
        != checked_lifecycle["container_rate_usd_per_hour"]
        or checked_lifecycle["cumulative_billable_seconds_upper_bound"]
        > MAXIMUM_TASK_POD_WALL_SECONDS
    ):
        raise FullModelTrainingError("plan099_runtime_control_chain_invalid")
    return {
        "resource": checked_resource,
        "lifecycle": checked_lifecycle,
        "segment": checked_segment,
    }


def _require_budget_capacity(
    budget: Mapping[str, Any], action_cost: float, upper_bound: float
) -> None:
    dynamic_budget = float(budget["stage_b_dynamic_budget_usd"])
    live_spendable = max(
        float(budget["current_available_balance_usd"])
        - float(budget["current_known_unsettled_usd"])
        - 6.0 * float(budget["current_volume_rate_usd_per_hour"]),
        0.0,
    )
    if (
        upper_bound > dynamic_budget + 1e-9
        or action_cost + float(budget["closure_reserve_usd"]) > live_spendable + 1e-9
    ):
        raise FullModelTrainingError("plan099_segment_budget_insufficient")


def _validate_model_contract(value: Any, root: Path) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "base",
        "student",
        "input",
    }:
        raise FullModelTrainingError("plan099_model_contract_invalid")
    base = value.get("base")
    student = value.get("student")
    model_input = value.get("input")
    if (
        value.get("schema") != "rondo-publication-critic-plan099-model-contract-v1"
        or not isinstance(base, Mapping)
        or base.get("repository") != MODEL_REPOSITORY
        or base.get("revision") != MODEL_REVISION
        or base.get("weight_sha256") != MODEL_WEIGHT_SHA256
        or base.get("original_num_labels") != 1
        or base.get("hidden_size") != 2048
        or base.get("pad_token_id") != 151654
        or base.get("eos_token_id") != 151645
        or base.get("bos_token_id") is not None
        or not isinstance(student, Mapping)
        or student.get("backbone_forward_count") != 1
        or student.get("logical_head_count") != 5
        or student.get("flat_logit_count") != 11
        or student.get("head_bias") is not False
        or student.get("layout")
        != {
            "useful_state_transfer": {
                "classes": ["PASS", "FAIL"],
                "start": 0,
                "stop": 2,
            },
            "honest_uncertainty": {
                "classes": ["PASS", "FAIL"],
                "start": 2,
                "stop": 4,
            },
            "conditional_continuity": {
                "classes": ["PASS", "FAIL", "N/A"],
                "start": 4,
                "stop": 7,
            },
            "scope_and_signal": {
                "classes": ["PASS", "FAIL"],
                "start": 7,
                "stop": 9,
            },
            "internal_consistency": {
                "classes": ["PASS", "FAIL"],
                "start": 9,
                "stop": 11,
            },
        }
        or student.get("initialization", {}).get("random_head_initialization")
        is not False
        or student.get("initialization", {}).get("legacy_scalar_head_retained")
        is not False
        or student.get("formal_output_schema_sha256")
        != sha256_file(root / student["formal_output_schema"])
        or not isinstance(model_input, Mapping)
        or model_input.get("adopted_window_tokens") != 16_384
        or model_input.get("padding_side") != "right"
        or model_input.get("candidate_truncation") != "forbidden"
        or model_input.get("pooling_parity_required") is not True
    ):
        raise FullModelTrainingError("plan099_model_contract_invalid")
    for path_key, digest_key in (
        ("input_contract", "input_contract_sha256"),
        ("rubric", "rubric_sha256"),
        ("render_contract", "render_contract_sha256"),
    ):
        if model_input.get(digest_key) != sha256_file(root / model_input[path_key]):
            raise FullModelTrainingError("plan099_input_identity_drifted")
    return json.loads(json.dumps(value))


def _validate_recipe(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "seed",
        "precision",
        "scope",
        "objective",
        "optimizer",
        "scheduler",
        "batching",
        "control",
        "retention",
    }:
        raise FullModelTrainingError("plan099_recipe_invalid")
    if value.get("schema") != "rondo-publication-critic-plan099-recipe-v1":
        raise FullModelTrainingError("plan099_recipe_invalid")
    scope = value.get("scope")
    objective = value.get("objective")
    control = value.get("control")
    precision = value.get("precision")
    optimizer = value.get("optimizer")
    batching = value.get("batching")
    if (
        not isinstance(scope, Mapping)
        or scope.get("trainable_parameter_elements") != 22_528
        or scope.get("backbone_trainable_parameter_elements") != 0
        or scope.get("head_trainable_parameter_elements") != 22_528
        or scope.get("update_method") != "replacement_five_head_only"
        or scope.get("backbone_mode") != "frozen_eval_no_grad"
        or scope.get("peft") is not False
        or scope.get("quantized_training") is not False
        or precision
        != {
            "backbone_parameter_dtype": "bfloat16",
            "pooled_feature_storage_dtype": "bfloat16",
            "head_parameter_dtype": "float32",
            "logit_and_loss_dtype": "float32",
            "allow_tf32": False,
            "float32_matmul_precision": "highest",
        }
        or not isinstance(objective, Mapping)
        or objective.get("component_weights")
        != {"dimension": 1.0, "gate": 0.25, "boundary": 0.5, "invariance": 0.25}
        or objective.get("soft_preference_qualification_weight") != 0.0
        or not isinstance(optimizer, Mapping)
        or optimizer.get("name") != "torch.optim.AdamW"
        or optimizer.get("learning_rate") != 0.0003
        or optimizer.get("fused") is not False
        or optimizer.get("foreach") is not False
        or not isinstance(batching, Mapping)
        or batching.get("macro_update") != "one_full_v10_train_cohort"
        or batching.get("shuffle") is not False
        or not isinstance(control, Mapping)
        or control.get("maximum_formal_updates") != 16
        or control.get("checkpoint_steps") != [2, 4, 8, 12, 16]
        or control.get("evaluation_steps") != [2, 4, 8, 12, 16]
        or control.get("fresh_process_recovery_step") != 8
        or control.get("formal_start") != "exact_base_empty_namespace"
    ):
        raise FullModelTrainingError("plan099_recipe_invalid")
    return json.loads(json.dumps(value))


def _validate_development_gate(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "validation",
        "eligibility",
        "decision_grid",
        "best_checkpoint_order",
        "undefined_denominator",
        "validation_claim",
    }:
        raise FullModelTrainingError("plan099_development_gate_invalid")
    validation = value.get("validation")
    grid = value.get("decision_grid")
    eligibility = value.get("eligibility")
    if (
        value.get("schema") != "rondo-publication-critic-plan099-development-gate-v1"
        or validation.get("candidate_rows") != 27
        or validation.get("pair_rows") != 12
        or validation.get("gate_gold_pass") != 12
        or validation.get("gate_gold_rewrite") != 15
        or not isinstance(eligibility, Mapping)
        or eligibility.get("maximum_gate_false_pass") != 3
        or eligibility.get("maximum_gate_false_rewrite") != 4
        or eligibility.get("minimum_gate_balanced_accuracy") != 0.75
        or eligibility.get("all_validation_pairs_closed") is not True
        or eligibility.get("decision_config_required") is not True
        or grid.get("candidate_count")
        != len(grid.get("shared_pass_over_fail_margins", ()))
        * len(grid.get("continuity_na_over_applicable_margins", ()))
        or grid["candidate_count"] > 1024
        or value.get("undefined_denominator") != "ineligible_fail_closed"
        or value.get("validation_claim") != "development_selection_only"
    ):
        raise FullModelTrainingError("plan099_development_gate_invalid")
    return json.loads(json.dumps(value))


def _validate_resource_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema") != (
        "rondo-publication-critic-plan099-resource-contract-v1"
    ):
        raise FullModelTrainingError("plan099_resource_contract_invalid")
    if (
        value.get("provider") != "RunPod"
        or value.get("cloud_type") != "SECURE"
        or value.get("data_center_id") != "US-TX-3"
        or value.get("gpu")
        != {"name": "NVIDIA L40S", "count": 1, "minimum_vram_gb": 48}
        or value["network_volume"].get("id") != "mwemzrn33y"
        or value["pods"].get("maximum_simultaneous_billing") != 1
        or value["pods"].get("maximum_total_wall_seconds") != 10800
        or value["pods"].get("maximum_lifecycle_seconds") != 10380
        or value["pods"].get("maximum_total_wall_formula")
        != "prior+maximum_lifecycle+worker_kill_grace+terminal_confirmation"
        or value["pods"].get("task_prior_pod_wall_seconds_definition")
        != "conservative_sum_from_provider_start_to_zero_pod_confirmation"
        or value["pods"].get("maximum_cumulative_created") != 2
        or value["network_volume"].get("maximum_new_volumes") != 0
        or value["budget"].get("recharge_allowed") is not False
        or value["budget"].get("absolute_deadline_guard")
        != {
            "profile": "plan099",
            "arm_within_authorization_seconds": 60,
            "termination_trigger_basis": (
                "pod_started_at_plus_maximum_lifecycle_seconds_plus_worker_kill_grace_seconds"
            ),
            "confirmation_deadline_basis": (
                "termination_trigger_at_plus_terminal_confirmation_seconds"
            ),
            "reviewer_approval_required_at_trigger": False,
            "normal_early_release_still_reviewer_gated": True,
        }
        or value.get("resource_end_state", {}).get("absolute_deadline_exception")
        != "automatic_exact_pod_stop_delete_and_zero_compute_confirmation"
    ):
        raise FullModelTrainingError("plan099_resource_contract_invalid")
    return json.loads(json.dumps(value))


def _validate_asset_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("schema") != (
        "rondo-publication-critic-plan099-asset-contract-v1"
    ):
        raise FullModelTrainingError("plan099_asset_contract_invalid")
    remote = value.get("remote_public_download_allowlist")
    if (
        not isinstance(remote, Mapping)
        or remote.get("repository") != MODEL_REPOSITORY
        or remote.get("revision") != MODEL_REVISION
        or "model.safetensors" not in remote.get("files", ())
        or value.get("local_namespace") != "eval-data/publication-critic/plan099"
        or value.get("upload_allowlist_scope") != "phase_a_static_only"
        or value.get("upload_allowlist")
        != [
            "phase-a/source-bundle.tar",
            "phase-a/source-bundle-receipt.json",
            "phase-a/data-bundle.tar",
            "phase-a/data-bundle-receipt.json",
        ]
        or value.get("runtime_control_upload_allowlist")
        != {
            "content_sha256_basis": "canonical_json_core_v1",
            "file_bytes": "pretty_json_bytes_v1",
            "file_mode": "0600",
            "maximum_file_bytes": MAXIMUM_RUNTIME_CONTROL_BYTES,
            "path_template": ("runtime-control/{role}/{content_sha256}.json"),
            "roles": [
                {"role": role, "schema": schema}
                for role, schema in RUNTIME_CONTROL_ROLES.items()
            ],
        }
        or ".env.local" not in value.get("forbidden", ())
    ):
        raise FullModelTrainingError("plan099_asset_contract_invalid")
    return json.loads(json.dumps(value))


def _validate_v10_identity(root: Path) -> None:
    paths = {
        "manifest.json": V10_MANIFEST_SHA256,
        "splits/train/candidates.jsonl": V10_TRAIN_CANDIDATES_SHA256,
        "splits/train/pairs.jsonl": V10_TRAIN_PAIRS_SHA256,
        "splits/validation/candidates.jsonl": V10_VALIDATION_CANDIDATES_SHA256,
        "splits/validation/pairs.jsonl": V10_VALIDATION_PAIRS_SHA256,
    }
    for relative, digest in paths.items():
        if sha256_file(root / V10_ROOT / relative) != digest:
            raise FullModelTrainingError("plan099_v10_identity_drifted", relative)


def _validate_metrics(value: Any, gate: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("plan099_metrics_invalid")
    if (
        set(value) != {"schema", "per_dimension", "gate"}
        or value.get("schema") != "rondo-publication-critic-qualification-metrics@v1"
        or not isinstance(value.get("per_dimension"), Mapping)
        or set(value["per_dimension"]) != set(HARD_DIMENSIONS)
        or not isinstance(value.get("gate"), Mapping)
        or set(value["gate"]) != {"total", "correct", "false_pass", "false_rewrite"}
    ):
        raise FullModelTrainingError("plan099_metrics_invalid")
    for dimension, support in gate["validation"]["gold_fail_support"].items():
        row = value["per_dimension"][dimension]
        classes = list(DIMENSION_CLASSES[dimension])
        expected_keys = {
            "classes",
            "confusion",
            "total",
            "correct",
            "gold_pass",
            "gold_fail",
            "fail_detected",
            "fail_to_pass",
            "fail_to_na",
            "pass_to_fail",
            "pass_to_na",
            "failure_recall",
        }
        if (
            not isinstance(row, Mapping)
            or set(row) != expected_keys
            or row.get("classes") != classes
            or row.get("total") != 27
            or row.get("gold_fail") != support
            or not isinstance(row.get("confusion"), Mapping)
            or set(row["confusion"]) != set(classes)
        ):
            raise FullModelTrainingError("plan099_metric_support_drifted")
        confusion = row["confusion"]
        if any(
            not isinstance(confusion[label], Mapping)
            or set(confusion[label]) != set(classes)
            or any(
                isinstance(count, bool) or not isinstance(count, int) or count < 0
                for count in confusion[label].values()
            )
            for label in classes
        ):
            raise FullModelTrainingError("plan099_metrics_invalid")
        if sum(sum(confusion[label].values()) for label in classes) != 27:
            raise FullModelTrainingError("plan099_metric_support_drifted")
        if row["correct"] != sum(confusion[label][label] for label in classes):
            raise FullModelTrainingError("plan099_metrics_not_canonical")
        if row["gold_pass"] != sum(confusion["PASS"].values()):
            raise FullModelTrainingError("plan099_metrics_not_canonical")
        if row["gold_fail"] != sum(confusion["FAIL"].values()):
            raise FullModelTrainingError("plan099_metrics_not_canonical")
        if row["fail_detected"] != confusion["FAIL"]["FAIL"]:
            raise FullModelTrainingError("plan099_metrics_not_canonical")
    gate_row = value["gate"]
    if (
        gate_row["total"] != 27
        or any(
            isinstance(gate_row[key], bool)
            or not isinstance(gate_row[key], int)
            or gate_row[key] < 0
            for key in ("correct", "false_pass", "false_rewrite")
        )
        or gate_row["correct"] + gate_row["false_pass"] + gate_row["false_rewrite"]
        != 27
    ):
        raise FullModelTrainingError("plan099_metric_support_drifted")
    return json.loads(json.dumps(value))


def _pair_closed(value: Any, expected_rows: int) -> bool:
    try:
        pairs = value["pairs"]
        return len(pairs) == expected_rows and all(
            pair["closed"] is True for pair in pairs
        )
    except (KeyError, TypeError):
        return False


def _failure_recall_fraction(metrics: Mapping[str, Any], dimension: str) -> Fraction:
    row = metrics["per_dimension"][dimension]
    denominator = int(row["gold_fail"])
    if denominator <= 0:
        raise FullModelTrainingError("plan099_required_denominator_unavailable")
    return Fraction(int(row["fail_detected"]), denominator)


def _class_recall_fraction(
    metrics: Mapping[str, Any], dimension: str, label: str
) -> Fraction:
    confusion = metrics["per_dimension"][dimension]["confusion"]
    denominator = sum(int(value) for value in confusion[label].values())
    if denominator <= 0:
        raise FullModelTrainingError("plan099_required_denominator_unavailable")
    return Fraction(int(confusion[label][label]), denominator)


def _macro_recall_fraction(metrics: Mapping[str, Any], dimension: str) -> Fraction:
    classes = metrics["per_dimension"][dimension]["classes"]
    recalls = [_class_recall_fraction(metrics, dimension, label) for label in classes]
    return sum(recalls, Fraction(0, 1)) / len(recalls)


def _gate_balanced_accuracy(metrics: Mapping[str, Any]) -> Fraction:
    gate = metrics["gate"]
    rewrite = 15
    passed = 12
    return (
        Fraction(rewrite - int(gate["false_pass"]), rewrite)
        + Fraction(passed - int(gate["false_rewrite"]), passed)
    ) / 2


def _nonnegative(value: Any, code: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) < 0.0
    ):
        raise FullModelTrainingError(code)
    return float(value)


def _timestamp(value: Any, code: str) -> datetime:
    if not isinstance(value, str):
        raise FullModelTrainingError(code)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FullModelTrainingError(code) from exc
    if parsed.tzinfo is None:
        raise FullModelTrainingError(code)
    return parsed.astimezone(timezone.utc)


def validate_source_identity(value: Any) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"commit", "source_archive_sha256", "freeze_sha256"}
        or _COMMIT.fullmatch(str(value.get("commit"))) is None
        or _SHA256.fullmatch(str(value.get("source_archive_sha256"))) is None
        or _SHA256.fullmatch(str(value.get("freeze_sha256"))) is None
    ):
        raise FullModelTrainingError("plan099_source_identity_invalid")
    return dict(value)


def validate_namespace(value: str, *, run_kind: str) -> str:
    if run_kind not in {"commissioning", "formal"}:
        raise FullModelTrainingError("plan099_run_kind_invalid")
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise FullModelTrainingError("plan099_namespace_invalid")
    required = f"rondo-plan099-{run_kind}-"
    if not value.startswith(required):
        raise FullModelTrainingError("plan099_namespace_invalid")
    return value


__all__ = [
    "ASSESSMENT_SCHEMA",
    "BUDGET_SCHEMA",
    "MAXIMUM_RUNTIME_CONTROL_BYTES",
    "MAXIMUM_TASK_POD_WALL_SECONDS",
    "MINIMUM_L40S_VISIBLE_MEMORY_BYTES",
    "MODEL_REPOSITORY",
    "MODEL_REVISION",
    "MODEL_WEIGHT_SHA256",
    "REPO_ROOT",
    "RUNTIME_CONTROL_ROLES",
    "SEGMENT_SCHEMA",
    "V10_MANIFEST_SHA256",
    "assess_development_checkpoint",
    "authorize_paid_segment",
    "authorize_pod_lifecycle",
    "checkpoint_selection_key",
    "create_budget_snapshot",
    "create_live_resource_receipt",
    "decision_margin_grid",
    "freeze_sha256",
    "load_freeze",
    "validate_budget_snapshot",
    "validate_live_resource_receipt",
    "validate_namespace",
    "validate_paid_segment_authorization",
    "validate_pod_lifecycle_authorization",
    "validate_runtime_control_chain",
    "validate_runtime_control_file",
    "validate_source_identity",
]
