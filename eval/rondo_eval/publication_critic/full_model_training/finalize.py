"""Bind formal training evidence to settled billing and terminal resources."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from rondo_eval.budget_policy import BudgetPolicy, BudgetPolicyError, load_budget_policy

from .contract import (
    FullModelTrainingError,
    pretty_json_bytes,
    read_json,
    sha256_file,
    utc_now,
    validate_formal_pending_receipt,
    validate_formal_start_receipt,
    write_exclusive,
)


PROVIDER_FACTS_SCHEMA = "rondo-publication-critic-plan060-provider-terminal-facts-v2"
FINAL_RECEIPT_SCHEMA = "rondo-publication-critic-formal-training-receipt-v2"
ALLOWED_GPU_IDS = (
    "NVIDIA H100 PCIe",
    "NVIDIA H100 80GB HBM3",
)
LEGACY_ASSET_SOURCE_GPU_ID = "NVIDIA H100 PCIe"


def finalize_formal_receipt(
    *,
    formal_start_path: Path,
    formal_pending_path: Path,
    provider_facts_path: Path,
    budget_policy_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Create the one completed receipt after provider billing and cleanup settle."""

    try:
        budget_policy = load_budget_policy(budget_policy_path)
    except BudgetPolicyError as exc:
        raise FullModelTrainingError(exc.code) from exc
    start = validate_formal_start_receipt(read_json(formal_start_path))
    pending = validate_formal_pending_receipt(read_json(formal_pending_path))
    facts = _validate_provider_terminal_facts(
        read_json(provider_facts_path),
        hard_cap_usd=budget_policy.hard_cap_usd,
        training_identity=start["identity"],
    )
    start_sha256 = sha256_file(formal_start_path)
    pending_sha256 = sha256_file(formal_pending_path)
    if (
        pending["identity"] != start["identity"]
        or pending["coverage"] != start["coverage"]
        or pending["start_process"] != start["process"]
        or pending["formal_start_receipt_sha256"] != start_sha256
        or pending["checkpoint"].get("checkpoint_manifest_sha256")
        != start["checkpoint"].get("checkpoint_manifest_sha256")
    ):
        raise FullModelTrainingError("formal_finalization_training_binding_mismatch")
    try:
        start_created_at = _parse_utc(start["created_at"])
        pending_created_at = _parse_utc(pending["created_at"])
        provider_captured_at = _parse_utc(facts["captured_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FullModelTrainingError("formal_finalization_time_binding_invalid") from exc
    if not start_created_at <= pending_created_at <= provider_captured_at:
        raise FullModelTrainingError("formal_finalization_time_binding_invalid")
    actual_cost = float(facts["billing"]["actual_plan060_cost_usd"])
    remaining = 23.0 - actual_cost
    cost_projection = _build_m3_b1c_cost_projection(
        start=start,
        pending=pending,
        facts=facts,
        remaining_budget_usd=remaining,
    )
    if (
        facts["qualification_conclusion"]["recommendation"] == "GO_RECOMMENDED"
        and cost_projection["affordable_within_remaining_budget"] is not True
    ):
        raise FullModelTrainingError("m3_b1c_cost_projection_not_affordable")
    receipt = {
        "schema": FINAL_RECEIPT_SCHEMA,
        "status": "execution_complete_pending_independent_acceptance",
        "created_at": utc_now(),
        "identity": pending["identity"],
        "formal_start_receipt_sha256": start_sha256,
        "formal_pending_receipt_sha256": pending_sha256,
        "provider_terminal_facts_sha256": sha256_file(provider_facts_path),
        "provider_terminal_captured_at": facts["captured_at"],
        "training": {
            "coverage": start["coverage"],
            "stages": start["stages"],
            "optimizer_pre_checkpoint": start["optimizer_pre_checkpoint"],
            "continued_stage": pending["continued_stage"],
            "restored_optimizer_state": pending["restored_optimizer_state"],
            "restored_optimizer_runtime": pending["restored_optimizer_runtime"],
            "checkpoint": pending["checkpoint"],
            "start_timing": start["timing"],
            "resume_timing": pending["timing"],
            "new_os_process_confirmed": pending["new_os_process_confirmed"],
        },
        "billing": facts["billing"],
        "provider_task": facts["provider_task"],
        "resources": facts["resources"],
        "budget": {
            "runtime_policy": budget_policy.as_receipt(),
            "shared_budget_usd": 23.0,
            "actual_plan060_cost_usd": actual_cost,
            "m3_b1c_remaining_budget_usd": remaining,
        },
        "m3_b1c_cost_projection": cost_projection,
        "qualification_conclusion": facts["qualification_conclusion"],
    }
    _validate_final_receipt(receipt, budget_policy=budget_policy)
    write_exclusive(output_path, pretty_json_bytes(receipt))
    return receipt


def _validate_provider_terminal_facts(
    value: Any, *, hard_cap_usd: float, training_identity: Mapping[str, Any]
) -> Mapping[str, Any]:
    if not _finite_nonnegative(hard_cap_usd) or float(hard_cap_usd) <= 0:
        raise FullModelTrainingError("budget_policy_hard_cap_invalid")
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema",
            "captured_at",
            "provider_task",
            "billing",
            "resources",
            "m3_b1c_cost_projection_assumptions",
            "qualification_conclusion",
        }
        or value.get("schema") != PROVIDER_FACTS_SCHEMA
    ):
        raise FullModelTrainingError("provider_terminal_facts_invalid")
    billing = value.get("billing")
    provider_task = value.get("provider_task")
    resources = value.get("resources")
    conclusion = value.get("qualification_conclusion")
    assumptions = value.get("m3_b1c_cost_projection_assumptions")
    winner_lock = training_identity.get("winner_lock")
    winner_evidence = (
        winner_lock.get("evidence") if isinstance(winner_lock, Mapping) else None
    )
    expected_winner_volume_id = (
        winner_evidence.get("network_volume_id")
        if isinstance(winner_evidence, Mapping)
        else None
    )
    try:
        captured_at = _parse_utc(value.get("captured_at"))
    except (TypeError, ValueError):
        raise FullModelTrainingError("provider_terminal_facts_invalid") from None
    if (
        not isinstance(billing, Mapping)
        or not _valid_provider_task(
            provider_task,
            training_identity=training_identity,
            captured_at=captured_at,
        )
        or not _valid_billing(billing, hard_cap_usd=hard_cap_usd)
        or not _valid_resources(
            resources,
            selected_gpu=training_identity.get("selected_gpu"),
            expected_winner_volume_id=expected_winner_volume_id,
        )
        or not _valid_cost_projection_assumptions(assumptions)
        or not isinstance(conclusion, Mapping)
        or conclusion.get("recommendation")
        not in {"GO_RECOMMENDED", "NO_GO_RECOMMENDED", "BLOCKED_INCONCLUSIVE"}
        or not isinstance(conclusion.get("reason_codes"), list)
        or not conclusion["reason_codes"]
        or not all(isinstance(item, str) and item for item in conclusion["reason_codes"])
        or not isinstance(conclusion.get("formal_training_complete"), bool)
    ):
        raise FullModelTrainingError("provider_terminal_facts_invalid")
    if (
        conclusion["recommendation"] == "GO_RECOMMENDED"
        and conclusion["formal_training_complete"] is not True
    ):
        raise FullModelTrainingError("provider_terminal_facts_invalid")
    return json.loads(json.dumps(value))


def _valid_provider_task(
    value: Any,
    *,
    training_identity: Mapping[str, Any],
    captured_at: datetime,
) -> bool:
    if not isinstance(training_identity, Mapping):
        return False
    selected_gpu = training_identity.get("selected_gpu")
    winner_lock_sha256 = training_identity.get("winner_lock_sha256")
    winner_lock = training_identity.get("winner_lock")
    hardware = training_identity.get("hardware")
    winner_pod = winner_lock.get("pod") if isinstance(winner_lock, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "provider",
            "winner_lock_sha256",
            "selected_gpu",
            "max_concurrent_task_gpu_count_observed",
            "pod_chain",
        }
        or value.get("provider") != "RunPod"
        or selected_gpu not in ALLOWED_GPU_IDS
        or not _is_sha256(winner_lock_sha256)
        or value.get("winner_lock_sha256") != winner_lock_sha256
        or value.get("selected_gpu") != selected_gpu
        or not isinstance(winner_lock, Mapping)
        or winner_lock.get("selected_gpu") != selected_gpu
        or not isinstance(winner_pod, Mapping)
        or set(winner_pod) != {"id", "name"}
        or not isinstance(winner_pod.get("id"), str)
        or not winner_pod["id"].strip()
        or not isinstance(winner_pod.get("name"), str)
        or not winner_pod["name"].strip()
        or not isinstance(hardware, Mapping)
        or hardware.get("device_count") != 1
        or hardware.get("device_name") != selected_gpu
        or hardware.get("selected_gpu") != selected_gpu
        or not isinstance(value.get("max_concurrent_task_gpu_count_observed"), int)
        or isinstance(value["max_concurrent_task_gpu_count_observed"], bool)
        or value["max_concurrent_task_gpu_count_observed"] != 1
    ):
        return False
    pod_chain = value.get("pod_chain")
    if not isinstance(pod_chain, list) or not pod_chain:
        return False
    pod_ids: set[str] = set()
    previous_end: datetime | None = None
    training_pod_seen = False
    winner_pod_seen = False
    for pod in pod_chain:
        if not isinstance(pod, Mapping) or set(pod) != {
            "pod_id",
            "pod_name",
            "gpu_id",
            "role",
            "billing_window",
        }:
            return False
        pod_id = pod.get("pod_id")
        pod_name = pod.get("pod_name")
        gpu_id = pod.get("gpu_id")
        role = pod.get("role")
        if (
            not isinstance(pod_id, str)
            or not pod_id.strip()
            or pod_id in pod_ids
            or not isinstance(pod_name, str)
            or not pod_name.startswith("rondo-plan060-")
            or gpu_id not in ALLOWED_GPU_IDS
            or role not in {"asset_source", "winner_preselection", "training"}
        ):
            return False
        is_winner_pod = (
            pod_id == winner_pod["id"] and pod_name == winner_pod["name"]
        )
        if pod_id == winner_pod["id"] or pod_name == winner_pod["name"]:
            if not is_winner_pod or role not in {"winner_preselection", "training"}:
                return False
            winner_pod_seen = True
        elif role == "winner_preselection":
            return False
        if role in {"winner_preselection", "training"}:
            if gpu_id != selected_gpu:
                return False
            if role == "training":
                training_pod_seen = True
        elif gpu_id != LEGACY_ASSET_SOURCE_GPU_ID:
            return False
        window = pod.get("billing_window")
        if not isinstance(window, Mapping) or set(window) != {"start_utc", "end_utc"}:
            return False
        try:
            start = _parse_utc(window["start_utc"])
            end = _parse_utc(window["end_utc"])
        except (KeyError, TypeError, ValueError):
            return False
        if (
            end <= start
            or end > captured_at
            or (previous_end is not None and start < previous_end)
        ):
            return False
        previous_end = end
        pod_ids.add(pod_id)
    return winner_pod_seen and training_pod_seen


def _valid_billing(value: Any, *, hard_cap_usd: float) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "provider_bill_settled",
        "all_task_pods_and_volumes_included",
        "actual_plan060_cost_usd",
        "task_pod_cost_usd",
        "task_standard_network_volume_cost_usd",
        "actual_gpu_hourly_rate_usd",
        "account_current_spend_per_hr_usd",
    }:
        return False
    actual = value.get("actual_plan060_cost_usd")
    pod_cost = value.get("task_pod_cost_usd")
    volume_cost = value.get("task_standard_network_volume_cost_usd")
    return (
        value.get("provider_bill_settled") is True
        and value.get("all_task_pods_and_volumes_included") is True
        and _finite_nonnegative(actual)
        and float(actual) <= float(hard_cap_usd)
        and _finite_nonnegative(pod_cost)
        and _finite_nonnegative(volume_cost)
        and math.isclose(
            float(actual),
            float(pod_cost) + float(volume_cost),
            rel_tol=0.0,
            abs_tol=1e-6,
        )
        and _finite_nonnegative(value.get("actual_gpu_hourly_rate_usd"))
        and float(value["actual_gpu_hourly_rate_usd"]) > 0
        and _finite_nonnegative(value.get("account_current_spend_per_hr_usd"))
    )


def _valid_resources(
    value: Any, *, selected_gpu: Any, expected_winner_volume_id: Any
) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "all_compute_pods_terminated",
        "task_gpu_active_cost_usd_per_hr",
        "task_cpu_active_cost_usd_per_hr",
        "task_standard_network_volumes",
        "retained_canonical_winner_volume_id",
        "continuing_storage_cost_usd_per_hr",
        "formal_remote_disk_peak_bytes",
        "full_smoke_checkpoint_deleted",
        "retained_full_checkpoint_count",
    }:
        return False
    volumes = value.get("task_standard_network_volumes")
    peak = value.get("formal_remote_disk_peak_bytes")
    if (
        value.get("all_compute_pods_terminated") is not True
        or not _finite_nonnegative(value.get("task_gpu_active_cost_usd_per_hr"))
        or float(value["task_gpu_active_cost_usd_per_hr"]) != 0.0
        or not _finite_nonnegative(value.get("task_cpu_active_cost_usd_per_hr"))
        or float(value["task_cpu_active_cost_usd_per_hr"]) != 0.0
        or not isinstance(volumes, list)
        or not 1 <= len(volumes) <= 2
        or not _finite_nonnegative(value.get("continuing_storage_cost_usd_per_hr"))
        or not isinstance(peak, int)
        or isinstance(peak, bool)
        or peak <= 0
        or value.get("full_smoke_checkpoint_deleted") is not True
        or not isinstance(value.get("retained_full_checkpoint_count"), int)
        or isinstance(value["retained_full_checkpoint_count"], bool)
        or value["retained_full_checkpoint_count"] != 0
    ):
        return False
    volume_ids: set[str] = set()
    retained: list[Mapping[str, Any]] = []
    for volume in volumes:
        if not isinstance(volume, Mapping) or set(volume) != {
            "volume_id",
            "volume_name",
            "gpu_id",
            "data_center_id",
            "storage_class",
            "size_gb",
            "terminal_state",
            "canonical_assets_verified",
        }:
            return False
        volume_id = volume.get("volume_id")
        if (
            not isinstance(volume_id, str)
            or not volume_id.strip()
            or volume_id in volume_ids
            or not isinstance(volume.get("volume_name"), str)
            or not volume["volume_name"].startswith("rondo-plan060-")
            or volume.get("gpu_id") not in ALLOWED_GPU_IDS
            or not isinstance(volume.get("data_center_id"), str)
            or not volume["data_center_id"].strip()
            or volume.get("storage_class") != "STANDARD"
            or not isinstance(volume.get("size_gb"), int)
            or isinstance(volume["size_gb"], bool)
            or not 1 <= volume["size_gb"] <= 60
            or volume.get("terminal_state") not in {"retained_canonical", "deleted"}
            or not isinstance(volume.get("canonical_assets_verified"), bool)
        ):
            return False
        volume_ids.add(volume_id)
        if volume["terminal_state"] == "retained_canonical":
            retained.append(volume)
    retained_id = value.get("retained_canonical_winner_volume_id")
    return (
        isinstance(expected_winner_volume_id, str)
        and bool(expected_winner_volume_id.strip())
        and retained_id == expected_winner_volume_id
        and len(retained) == 1
        and retained[0]["volume_id"] == retained_id
        and retained[0]["gpu_id"] == selected_gpu
        and retained[0]["canonical_assets_verified"] is True
        and float(value["continuing_storage_cost_usd_per_hr"]) > 0.0
        and all(
            volume["terminal_state"] == "deleted"
            for volume in volumes
            if volume["volume_id"] != retained_id
        )
    )


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("utc timestamp required")
    parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("utc timestamp required")
    return parsed


def _valid_cost_projection_assumptions(value: Any) -> bool:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "m3_b1c_total_update_range",
            "retry_multiplier",
            "non_step_overhead_seconds",
            "storage_and_cleanup_upper_usd",
            "basis",
        }
    ):
        return False
    updates = value.get("m3_b1c_total_update_range")
    retry = value.get("retry_multiplier")
    return (
        isinstance(updates, list)
        and len(updates) == 2
        and all(isinstance(item, int) and not isinstance(item, bool) for item in updates)
        and 0 < updates[0] <= updates[1]
        and isinstance(retry, (int, float))
        and not isinstance(retry, bool)
        and math.isfinite(float(retry))
        and float(retry) >= 1.0
        and _finite_nonnegative(value.get("non_step_overhead_seconds"))
        and _finite_nonnegative(value.get("storage_and_cleanup_upper_usd"))
        and isinstance(value.get("basis"), str)
        and bool(value["basis"].strip())
    )


def _build_m3_b1c_cost_projection(
    *,
    start: Mapping[str, Any],
    pending: Mapping[str, Any],
    facts: Mapping[str, Any],
    remaining_budget_usd: float,
) -> dict[str, Any]:
    assumptions = facts["m3_b1c_cost_projection_assumptions"]
    update_low, update_high = assumptions["m3_b1c_total_update_range"]
    retry = float(assumptions["retry_multiplier"])
    overhead = float(assumptions["non_step_overhead_seconds"])
    storage_upper = float(assumptions["storage_and_cleanup_upper_usd"])
    rate = float(facts["billing"]["actual_gpu_hourly_rate_usd"])
    measured_steps = [
        float(start["stages"][1]["elapsed_seconds"]),
        float(start["stages"][2]["elapsed_seconds"]),
        float(pending["continued_stage"]["elapsed_seconds"]),
    ]
    measured_tps = [
        float(start["stages"][1]["tokens_per_second"]),
        float(start["stages"][2]["tokens_per_second"]),
        float(pending["continued_stage"]["tokens_per_second"]),
    ]
    step_low = min(measured_steps)
    step_high = max(measured_steps)
    step_mid = sum(measured_steps) / len(measured_steps)
    update_mid = (update_low + update_high) / 2.0
    low_hours = (overhead + update_low * step_low) / 3600.0
    mid_hours = (overhead + update_mid * step_mid * retry) / 3600.0
    conservative_hours = (overhead + update_high * step_high * retry) / 3600.0
    low_cost = low_hours * rate
    mid_cost = mid_hours * rate + storage_upper / 2.0
    conservative_cost = conservative_hours * rate + storage_upper
    usable_gpu_usd = max(0.0, remaining_budget_usd - storage_upper)
    remaining_hours = usable_gpu_usd / rate
    remaining_seconds_after_overhead = max(0.0, remaining_hours * 3600.0 - overhead)
    remaining_updates = math.floor(remaining_seconds_after_overhead / (step_high * retry))
    return {
        "assumptions": assumptions,
        "formal_measurement": {
            "steady_step_seconds": measured_steps,
            "steady_tokens_per_second": measured_tps,
            "conservative_step_seconds": step_high,
            "actual_gpu_hourly_rate_usd": rate,
        },
        "estimated_gpu_hours": {
            "low": low_hours,
            "mid": mid_hours,
            "conservative": conservative_hours,
        },
        "estimated_cost_usd": {
            "low": low_cost,
            "mid": mid_cost,
            "conservative": conservative_cost,
        },
        "remaining_gpu_hours_at_observed_rate": remaining_hours,
        "remaining_updates_conservative": remaining_updates,
        "risk_margin_usd": remaining_budget_usd - conservative_cost,
        "affordable_within_remaining_budget": conservative_cost <= remaining_budget_usd,
    }


def _validate_final_receipt(
    value: Any, *, budget_policy: BudgetPolicy
) -> None:
    budget = value.get("budget") if isinstance(value, Mapping) else None
    identity = value.get("identity") if isinstance(value, Mapping) else None
    billing = value.get("billing") if isinstance(value, Mapping) else None
    winner_lock = identity.get("winner_lock") if isinstance(identity, Mapping) else None
    winner_evidence = (
        winner_lock.get("evidence") if isinstance(winner_lock, Mapping) else None
    )
    expected_winner_volume_id = (
        winner_evidence.get("network_volume_id")
        if isinstance(winner_evidence, Mapping)
        else None
    )
    try:
        provider_captured_at = _parse_utc(
            value.get("provider_terminal_captured_at")
            if isinstance(value, Mapping)
            else None
        )
    except (TypeError, ValueError) as exc:
        raise FullModelTrainingError("formal_final_receipt_invalid") from exc
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != FINAL_RECEIPT_SCHEMA
        or value.get("status") != "execution_complete_pending_independent_acceptance"
        or not isinstance(identity, Mapping)
        or not isinstance(value.get("training"), Mapping)
        or value["training"].get("new_os_process_confirmed") is not True
        or not _is_sha256(value.get("provider_terminal_facts_sha256"))
        or not _valid_provider_task(
            value.get("provider_task"),
            training_identity=identity,
            captured_at=provider_captured_at,
        )
        or not _valid_billing(billing, hard_cap_usd=budget_policy.hard_cap_usd)
        or not _valid_resources(
            value.get("resources"),
            selected_gpu=identity.get("selected_gpu"),
            expected_winner_volume_id=expected_winner_volume_id,
        )
        or not isinstance(budget, Mapping)
        or budget.get("runtime_policy") != budget_policy.as_receipt()
        or budget.get("shared_budget_usd") != 23.0
        or not _finite_nonnegative(budget.get("actual_plan060_cost_usd"))
        or budget.get("actual_plan060_cost_usd")
        != billing.get("actual_plan060_cost_usd")
        or not _finite_nonnegative(budget.get("m3_b1c_remaining_budget_usd"))
        or not math.isclose(
            float(budget["m3_b1c_remaining_budget_usd"]),
            23.0 - float(budget["actual_plan060_cost_usd"]),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        or not isinstance(value.get("m3_b1c_cost_projection"), Mapping)
        or not isinstance(
            value["m3_b1c_cost_projection"].get("affordable_within_remaining_budget"),
            bool,
        )
    ):
        raise FullModelTrainingError("formal_final_receipt_invalid")


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _finite_nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )
