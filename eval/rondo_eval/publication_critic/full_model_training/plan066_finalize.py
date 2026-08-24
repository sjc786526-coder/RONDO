"""Finalize Plan 066 against the continuous Plan 060+066 budget and resources."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from rondo_eval.budget_policy import BudgetPolicyError, load_budget_policy

from .contract import (
    FullModelTrainingError,
    pretty_json_bytes,
    read_json,
    sha256_file,
    utc_now,
    write_exclusive,
)
from .plan066_contract import (
    validate_plan066_resume_receipt,
    validate_plan066_start_receipt,
)


PROVIDER_FACTS_SCHEMA = "rondo-publication-critic-plan066-provider-terminal-facts-v1"
PROVIDER_FACTS_CONSOLE_SCHEMA = (
    "rondo-publication-critic-plan066-provider-terminal-facts-v2"
)
FINAL_RECEIPT_SCHEMA = "rondo-publication-critic-plan066-final-receipt-v1"
FINAL_RECEIPT_CONSOLE_SCHEMA = "rondo-publication-critic-plan066-final-receipt-v2"
PLAN060_BASELINE_BALANCE_USD = 23.5953643966
PLAN066_POD_ID = "oe6gbptvq5yhja"
PLAN066_POD_NAME = "rondo-plan060-pcie-replacement-01"


def finalize_plan066_receipt(
    *,
    formal_start_path: Path,
    formal_pending_path: Path,
    provider_facts_path: Path,
    budget_policy_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    try:
        policy = load_budget_policy(budget_policy_path)
    except BudgetPolicyError as exc:
        raise FullModelTrainingError(exc.code) from exc
    start = validate_plan066_start_receipt(read_json(formal_start_path), formal=True)
    pending = validate_plan066_resume_receipt(read_json(formal_pending_path), formal=True)
    facts = validate_plan066_provider_facts(
        read_json(provider_facts_path),
        identity=start["identity"],
        candidate_receipts=start["candidates"],
        hard_cap_usd=policy.hard_cap_usd,
    )
    start_sha = sha256_file(formal_start_path)
    if (
        pending.get("identity") != start.get("identity")
        or pending.get("coverage") != start.get("coverage")
        or pending.get("start_process") != start.get("process")
        or pending.get("formal_start_receipt_sha256") != start_sha
        or pending.get("checkpoint", {}).get("checkpoint_manifest_sha256")
        != start.get("checkpoint", {}).get("checkpoint_manifest_sha256")
    ):
        raise FullModelTrainingError("plan066_final_training_binding_mismatch")
    if not (
        _parse_utc(start["created_at"])
        <= _parse_utc(pending["created_at"])
        <= _parse_utc(facts["captured_at"])
    ):
        raise FullModelTrainingError("plan066_final_time_binding_invalid")
    console_billing = facts["schema"] == PROVIDER_FACTS_CONSOLE_SCHEMA
    budget = {
        "runtime_policy": policy.as_receipt(),
        "actual_plan060_plan066_cost_usd": facts["billing"][
            "actual_plan060_plan066_cost_usd"
        ],
        "conservative_continuous_cost_usd": facts["billing"][
            "conservative_continuous_cost_usd"
        ],
        "remaining_to_hard_cap_usd": policy.hard_cap_usd
        - facts["billing"]["conservative_continuous_cost_usd"],
    }
    if console_billing:
        budget.update(
            {
                "authoritative_cost_source": facts["billing"][
                    "authoritative_cost_source"
                ],
                "provider_console_period_date": facts["billing"][
                    "provider_console_breakdown"
                ]["date"],
            }
        )
    else:
        budget["continuous_baseline_balance_usd"] = PLAN060_BASELINE_BALANCE_USD
    receipt = {
        "schema": (
            FINAL_RECEIPT_CONSOLE_SCHEMA if console_billing else FINAL_RECEIPT_SCHEMA
        ),
        "status": "execution_complete_pending_independent_acceptance",
        "created_at": utc_now(),
        "identity": start["identity"],
        "formal_start_receipt_sha256": start_sha,
        "formal_pending_receipt_sha256": sha256_file(formal_pending_path),
        "provider_terminal_facts_sha256": sha256_file(provider_facts_path),
        "training": {
            "coverage": start["coverage"],
            "stages": start["stages"],
            "candidates": start["candidates"],
            "validation": start["validation"],
            "holdout": start["holdout"],
            "checkpoint": pending["checkpoint"],
            "continued_stage": pending["continued_stage"],
            "continued_data": pending["continued_data"],
            "new_os_process_confirmed": pending["new_os_process_confirmed"],
            "start_timing": start["timing"],
            "resume_timing": pending["timing"],
        },
        "budget": budget,
        "provider": facts["provider"],
        "billing": facts["billing"],
        "resources": facts["resources"],
        "conclusion": facts["conclusion"],
    }
    write_exclusive(output_path, pretty_json_bytes(receipt))
    return receipt


def validate_plan066_provider_facts(
    value: Any,
    *,
    identity: Mapping[str, Any],
    candidate_receipts: Any,
    hard_cap_usd: float,
) -> dict[str, Any]:
    expected = {"schema", "captured_at", "provider", "billing", "resources", "conclusion"}
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("schema")
        not in {PROVIDER_FACTS_SCHEMA, PROVIDER_FACTS_CONSOLE_SCHEMA}
    ):
        raise FullModelTrainingError("plan066_provider_facts_invalid")
    try:
        _parse_utc(value["captured_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FullModelTrainingError("plan066_provider_facts_invalid") from exc
    winner = identity.get("winner_lock") if isinstance(identity, Mapping) else None
    winner_evidence = winner.get("evidence") if isinstance(winner, Mapping) else None
    provider = value.get("provider")
    billing = value.get("billing")
    resources = value.get("resources")
    conclusion = value.get("conclusion")
    if (
        not _valid_provider(
            provider,
            winner_lock_sha256=identity.get("winner_lock_sha256"),
            selected_gpu=identity.get("selected_gpu"),
        )
        or not _valid_billing(
            billing,
            hard_cap_usd=hard_cap_usd,
            provider_facts_schema=value.get("schema"),
        )
        or not _valid_resources(
            resources,
            winner_volume_id=(
                winner_evidence.get("network_volume_id")
                if isinstance(winner_evidence, Mapping)
                else None
            ),
            candidate_receipts=candidate_receipts,
        )
        or not isinstance(conclusion, Mapping)
        or set(conclusion) != {"recommendation", "reason_codes"}
        or conclusion.get("recommendation")
        not in {"GO_RECOMMENDED", "NO_GO_RECOMMENDED", "BLOCKED_INCONCLUSIVE"}
        or not isinstance(conclusion.get("reason_codes"), list)
        or not conclusion["reason_codes"]
        or any(not isinstance(item, str) or not item for item in conclusion["reason_codes"])
    ):
        raise FullModelTrainingError("plan066_provider_facts_invalid")
    return json.loads(json.dumps(value))


def _valid_provider(
    value: Any, *, winner_lock_sha256: Any, selected_gpu: Any
) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value)
        == {
            "name", "pod_id", "pod_name", "gpu_id", "gpu_count",
            "data_center_id", "cuda_version", "gpu_hourly_rate_usd",
            "winner_lock_sha256",
        }
        and value.get("name") == "RunPod"
        and value.get("pod_id") == PLAN066_POD_ID
        and value.get("pod_name") == PLAN066_POD_NAME
        and value.get("winner_lock_sha256") == winner_lock_sha256
        and _sha256(winner_lock_sha256)
        and value.get("gpu_id") == selected_gpu == "NVIDIA H100 PCIe"
        and value.get("gpu_count") == 1
        and value.get("data_center_id") == "US-KS-2"
        and isinstance(value.get("cuda_version"), str)
        and bool(value["cuda_version"])
        and _finite_positive(value.get("gpu_hourly_rate_usd"))
    )


def _valid_billing(
    value: Any, *, hard_cap_usd: float, provider_facts_schema: Any
) -> bool:
    legacy_keys = {
        "provider_bill_settled",
        "continuous_baseline_balance_usd",
        "captured_balance_usd",
        "balance_delta_cost_usd",
        "actual_plan060_plan066_cost_usd",
        "conservative_continuous_cost_usd",
        "account_current_spend_per_hr_usd",
    }
    if not isinstance(value, Mapping):
        return False
    if provider_facts_schema == PROVIDER_FACTS_CONSOLE_SCHEMA:
        return _valid_console_billing(value, hard_cap_usd=hard_cap_usd)
    if provider_facts_schema != PROVIDER_FACTS_SCHEMA or set(value) != legacy_keys:
        return False
    if value.get("provider_bill_settled") is not True:
        return False
    numbers = [
        value.get("continuous_baseline_balance_usd"),
        value.get("captured_balance_usd"),
        value.get("balance_delta_cost_usd"),
        value.get("actual_plan060_plan066_cost_usd"),
        value.get("conservative_continuous_cost_usd"),
        value.get("account_current_spend_per_hr_usd"),
    ]
    if any(not _finite_nonnegative(item) for item in numbers):
        return False
    balance_delta = PLAN060_BASELINE_BALANCE_USD - float(value["captured_balance_usd"])
    actual = float(value["actual_plan060_plan066_cost_usd"])
    conservative = float(value["conservative_continuous_cost_usd"])
    return (
        float(value["continuous_baseline_balance_usd"])
        == PLAN060_BASELINE_BALANCE_USD
        and abs(float(value["balance_delta_cost_usd"]) - balance_delta) <= 0.01
        and abs(conservative - max(balance_delta, actual)) <= 0.01
        and conservative <= float(hard_cap_usd)
    )


def _valid_console_billing(value: Mapping[str, Any], *, hard_cap_usd: float) -> bool:
    expected = {
        "provider_bill_settled",
        "authoritative_cost_source",
        "provider_console_breakdown",
        "captured_balance_usd",
        "account_balance_context_only",
        "actual_plan060_plan066_cost_usd",
        "conservative_continuous_cost_usd",
        "account_current_spend_per_hr_usd",
    }
    breakdown = value.get("provider_console_breakdown")
    if (
        set(value) != expected
        or value.get("provider_bill_settled") is not True
        or value.get("authoritative_cost_source")
        != "provider_console_task_period_total"
        or value.get("account_balance_context_only") is not True
        or not isinstance(breakdown, Mapping)
        or set(breakdown)
        != {"date", "total_usd", "cloud_gpu_usd", "storage_usd", "other_usd"}
        or breakdown.get("date") != "2026-08-24"
    ):
        return False
    numbers = [
        value.get("captured_balance_usd"),
        value.get("actual_plan060_plan066_cost_usd"),
        value.get("conservative_continuous_cost_usd"),
        value.get("account_current_spend_per_hr_usd"),
        breakdown.get("total_usd"),
        breakdown.get("cloud_gpu_usd"),
        breakdown.get("storage_usd"),
        breakdown.get("other_usd"),
    ]
    if any(not _finite_nonnegative(item) for item in numbers):
        return False
    total = float(breakdown["total_usd"])
    component_total = sum(
        float(breakdown[key])
        for key in ("cloud_gpu_usd", "storage_usd", "other_usd")
    )
    actual = float(value["actual_plan060_plan066_cost_usd"])
    conservative = float(value["conservative_continuous_cost_usd"])
    return (
        abs(total - component_total) <= 1e-9
        and abs(actual - total) <= 1e-9
        and abs(conservative - total) <= 1e-9
        and conservative <= float(hard_cap_usd)
    )


def _valid_resources(
    value: Any, *, winner_volume_id: Any, candidate_receipts: Any
) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "legacy_pod_deleted", "loser_volume_deleted", "compute_pod_terminal_state",
        "task_compute_cost_usd_per_hr", "winner_volume", "candidate_retention",
        "full_checkpoint_terminal_state",
    }:
        return False
    volume = value.get("winner_volume")
    retention = value.get("candidate_retention")
    if (
        value.get("legacy_pod_deleted") is not True
        or value.get("loser_volume_deleted") is not True
        or value.get("compute_pod_terminal_state") != "TERMINATED"
        or value.get("task_compute_cost_usd_per_hr") != 0
        or value.get("full_checkpoint_terminal_state") not in {"deleted", "retained_verified"}
        or not isinstance(volume, Mapping)
        or set(volume)
        != {"id", "terminal_state", "continuing_storage_cost_usd_per_hr"}
        or volume.get("id") != winner_volume_id
        or volume.get("terminal_state") not in {"deleted", "retained_candidate_assets"}
        or not _finite_nonnegative(volume.get("continuing_storage_cost_usd_per_hr"))
        or not isinstance(retention, Mapping)
        or set(retention) != {"C1", "C2", "C3"}
    ):
        return False
    for item in retention.values():
        if (
            not isinstance(item, Mapping)
            or set(item) != {"candidate_manifest_sha256", "location", "verified"}
            or not _sha256(item.get("candidate_manifest_sha256"))
            or item.get("location") not in {"local_ignored", "winner_volume"}
            or item.get("verified") is not True
        ):
            return False
    locations = {item["location"] for item in retention.values()}
    if (
        not isinstance(candidate_receipts, list)
        or len(candidate_receipts) != 3
        or {
            item.get("stage"): item.get("candidate_manifest_sha256")
            for item in candidate_receipts
            if isinstance(item, Mapping)
        }
        != {
            stage: retention[stage]["candidate_manifest_sha256"]
            for stage in ("C1", "C2", "C3")
        }
    ):
        return False
    if "winner_volume" in locations:
        return (
            volume["terminal_state"] == "retained_candidate_assets"
            and float(volume["continuing_storage_cost_usd_per_hr"]) > 0
        )
    return (
        volume["terminal_state"] == "deleted"
        and float(volume["continuing_storage_cost_usd_per_hr"]) == 0
    )


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be UTC Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise ValueError("timestamp must be UTC")
    return parsed


def _finite_nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _finite_positive(value: Any) -> bool:
    return _finite_nonnegative(value) and float(value) > 0


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
