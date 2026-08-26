"""Small adaptive-search, budget, and candidate contracts for Plan 087."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    sha256_bytes,
)
from .plan082_controller import validate_process_identity

ROUTE_CONTEXT_SCHEMA = "rondo-publication-critic-plan087-route-context-v1"
COST_SNAPSHOT_SCHEMA = "rondo-publication-critic-plan087-cost-snapshot-v1"
PROCESS_RECEIPT_SCHEMA = "rondo-publication-critic-plan087-process-receipt-v1"
RECOVERY_RECEIPT_SCHEMA = "rondo-publication-critic-plan087-recovery-receipt-v1"
RECOVERY_ROLES = frozenset({"none", "necessary_recovery_point", "promising_candidate"})
TERMINAL_OUTCOMES = frozenset(
    {
        "PROMISING_CANDIDATE_RETAINED",
        "BUDGET_EXHAUSTED_NO_CANDIDATE",
        "INCONCLUSIVE_INFRASTRUCTURE",
    }
)
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,95}\Z")


def validate_route_context(value: Any) -> dict[str, Any]:
    """Bind one route checkpoint to the search history that selected it."""

    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "search_id",
        "route_id",
        "route_generation",
        "start_state",
        "decision",
        "prior_route_summaries",
        "cost_snapshot",
    }:
        raise FullModelTrainingError("plan087_route_context_invalid")
    decision = value.get("decision")
    summaries = value.get("prior_route_summaries")
    if (
        value.get("schema") != ROUTE_CONTEXT_SCHEMA
        or not _identifier(value.get("search_id"))
        or not _identifier(value.get("route_id"))
        or not isinstance(value.get("route_generation"), int)
        or isinstance(value["route_generation"], bool)
        or value["route_generation"] < 1
        or value.get("start_state") != "exact_base"
        or not isinstance(decision, Mapping)
        or set(decision) != {"reason", "evidence_observation_id", "changes"}
        or not _text(decision.get("reason"))
        or not _optional_identifier(decision.get("evidence_observation_id"))
        or not isinstance(decision.get("changes"), Sequence)
        or isinstance(decision["changes"], (str, bytes, bytearray))
        or not decision["changes"]
        or any(not _text(item) for item in decision["changes"])
        or not isinstance(summaries, Sequence)
        or isinstance(summaries, (str, bytes, bytearray))
        or len(summaries) != value["route_generation"] - 1
    ):
        raise FullModelTrainingError("plan087_route_context_invalid")
    normalized_summaries: list[dict[str, Any]] = []
    seen_routes: set[str] = set()
    for index, summary in enumerate(summaries, start=1):
        if (
            not isinstance(summary, Mapping)
            or set(summary)
            != {
                "search_id",
                "route_id",
                "route_generation",
                "route_result_content_sha256",
                "run_spec_content_sha256",
                "terminal_observation_id",
                "terminal_observation_sha256",
                "selected_checkpoint_content_sha256",
                "candidate_disposition",
                "reason",
                "cost_snapshot_index",
                "cost_snapshot_content_sha256",
                "baseline_balance_usd",
                "current_balance_usd",
                "conservative_task_cost_usd",
            }
            or not _identifier(summary.get("search_id"))
            or summary["search_id"] != value["search_id"]
            or not _identifier(summary.get("route_id"))
            or summary["route_id"] in seen_routes
            or summary.get("route_generation") != index
            or not _sha256(summary.get("route_result_content_sha256"))
            or not _sha256(summary.get("run_spec_content_sha256"))
            or not _identifier(summary.get("terminal_observation_id"))
            or not _sha256(summary.get("terminal_observation_sha256"))
            or not _sha256(summary.get("selected_checkpoint_content_sha256"))
            or summary.get("candidate_disposition")
            not in {"not_promising", "invalid", "incomplete"}
            or not _text(summary.get("reason"))
            or not isinstance(summary.get("cost_snapshot_index"), int)
            or isinstance(summary["cost_snapshot_index"], bool)
            or summary["cost_snapshot_index"] < 0
            or not _sha256(summary.get("cost_snapshot_content_sha256"))
            or any(
                not isinstance(summary.get(key), (int, float))
                or isinstance(summary[key], bool)
                or not math.isfinite(float(summary[key]))
                or float(summary[key]) < 0
                for key in (
                    "baseline_balance_usd",
                    "current_balance_usd",
                    "conservative_task_cost_usd",
                )
            )
        ):
            raise FullModelTrainingError("plan087_route_history_invalid")
        seen_routes.add(str(summary["route_id"]))
        normalized_summaries.append(dict(summary))
    if value["route_id"] in seen_routes:
        raise FullModelTrainingError("plan087_route_history_invalid")
    cost = validate_cost_snapshot(value.get("cost_snapshot"))
    if not normalized_summaries:
        if (
            decision["evidence_observation_id"] is not None
            or cost["snapshot_index"] != 0
            or cost["previous_snapshot_content_sha256"] is not None
        ):
            raise FullModelTrainingError("plan087_route_history_invalid")
    else:
        previous = normalized_summaries[-1]
        if (
            decision["evidence_observation_id"] != previous["terminal_observation_id"]
            or cost["snapshot_index"] != previous["cost_snapshot_index"] + 1
            or cost["previous_snapshot_content_sha256"]
            != previous["cost_snapshot_content_sha256"]
            or cost["baseline_balance_usd"] != previous["baseline_balance_usd"]
            or cost["current_balance_usd"] > previous["current_balance_usd"] + 1e-9
            or cost["conservative_task_cost_usd"] + 1e-9
            < previous["conservative_task_cost_usd"]
        ):
            raise FullModelTrainingError("plan087_route_history_invalid")
    return {
        **json.loads(json.dumps(value)),
        "prior_route_summaries": normalized_summaries,
        "cost_snapshot": cost,
    }


def validate_cost_snapshot(value: Any) -> dict[str, Any]:
    """Validate a conservative live budget snapshot and derive its action gate."""

    base_fields = {
        "schema",
        "captured_at",
        "snapshot_index",
        "previous_snapshot_content_sha256",
        "baseline_balance_usd",
        "current_balance_usd",
        "provider_task_billing_usd",
        "cost_entries",
        "initial_available_usd",
        "projected_next_increment_usd",
    }
    derived_fields = {
        "balance_delta_usd",
        "cost_entry_total_usd",
        "conservative_task_cost_usd",
        "task_remaining_usd",
        "account_remaining_after_reserve_usd",
        "action_headroom_usd",
        "next_action_authorized",
        "content_sha256",
    }
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("plan087_cost_snapshot_invalid")
    fields = set(value)
    if fields != base_fields and fields != base_fields | derived_fields:
        raise FullModelTrainingError("plan087_cost_snapshot_invalid")
    snapshot_index = value.get("snapshot_index")
    previous_sha256 = value.get("previous_snapshot_content_sha256")
    if (
        value.get("schema") != COST_SNAPSHOT_SCHEMA
        or not _text(value.get("captured_at"))
        or not isinstance(snapshot_index, int)
        or isinstance(snapshot_index, bool)
        or snapshot_index < 0
        or (snapshot_index == 0 and previous_sha256 is not None)
        or (snapshot_index > 0 and not _sha256(previous_sha256))
    ):
        raise FullModelTrainingError("plan087_cost_snapshot_invalid")
    entries = value.get("cost_entries")
    if not isinstance(entries, Sequence) or isinstance(
        entries, (str, bytes, bytearray)
    ):
        raise FullModelTrainingError("plan087_cost_snapshot_invalid")
    normalized_entries: list[dict[str, Any]] = []
    seen_entries: set[str] = set()
    for entry in entries:
        if (
            not isinstance(entry, Mapping)
            or set(entry) != {"entry_id", "category", "amount_usd", "basis"}
            or not _identifier(entry.get("entry_id"))
            or entry["entry_id"] in seen_entries
            or entry.get("category")
            not in {
                "compute_pod",
                "container_disk",
                "network_volume_holding",
                "network_volume_expansion",
                "network_volume_creation",
                "small_result_transfer",
            }
            or not _text(entry.get("basis"))
        ):
            raise FullModelTrainingError("plan087_cost_entry_invalid")
        amount = _nonnegative_number(entry.get("amount_usd"))
        seen_entries.add(str(entry["entry_id"]))
        normalized_entries.append({**dict(entry), "amount_usd": amount})
    numbers = {
        key: _nonnegative_number(value.get(key))
        for key in (
            "baseline_balance_usd",
            "current_balance_usd",
            "provider_task_billing_usd",
            "initial_available_usd",
            "projected_next_increment_usd",
        )
    }
    baseline = numbers["baseline_balance_usd"]
    current = numbers["current_balance_usd"]
    expected_available = min(9.0, baseline - 0.14)
    if (
        baseline < 0.14
        or current > baseline + 1e-9
        or not math.isclose(
            numbers["initial_available_usd"],
            expected_available,
            rel_tol=0.0,
            abs_tol=1e-9,
        )
    ):
        raise FullModelTrainingError("plan087_cost_baseline_invalid")
    balance_delta = max(0.0, baseline - current)
    conservative = max(
        balance_delta,
        numbers["provider_task_billing_usd"],
        sum(entry["amount_usd"] for entry in normalized_entries),
    )
    task_remaining = max(0.0, expected_available - conservative)
    account_remaining = max(0.0, current - 0.14)
    action_headroom = min(task_remaining, account_remaining)
    projected = numbers["projected_next_increment_usd"]
    base = {key: value[key] for key in base_fields}
    result = {
        **json.loads(json.dumps(base)),
        "cost_entries": normalized_entries,
        "balance_delta_usd": balance_delta,
        "cost_entry_total_usd": sum(
            entry["amount_usd"] for entry in normalized_entries
        ),
        "conservative_task_cost_usd": conservative,
        "task_remaining_usd": task_remaining,
        "account_remaining_after_reserve_usd": account_remaining,
        "action_headroom_usd": action_headroom,
        "next_action_authorized": projected <= action_headroom + 1e-9,
    }
    result["content_sha256"] = sha256_bytes(canonical_json_bytes(result))
    if fields == base_fields | derived_fields and any(
        value[key] != result[key] for key in derived_fields
    ):
        raise FullModelTrainingError("plan087_cost_snapshot_derived_invalid")
    return result


def validate_cost_progression(previous: Any, current: Any) -> dict[str, Any]:
    """Require one immutable cumulative budget ledger to advance exactly once."""

    before = validate_cost_snapshot(previous)
    after = validate_cost_snapshot(current)
    old_entries = before["cost_entries"]
    new_entries = after["cost_entries"]
    if (
        after["snapshot_index"] != before["snapshot_index"] + 1
        or after["previous_snapshot_content_sha256"] != before["content_sha256"]
        or after["baseline_balance_usd"] != before["baseline_balance_usd"]
        or after["initial_available_usd"] != before["initial_available_usd"]
        or after["current_balance_usd"] > before["current_balance_usd"] + 1e-9
        or after["provider_task_billing_usd"] + 1e-9
        < before["provider_task_billing_usd"]
        or len(new_entries) < len(old_entries)
        or new_entries[: len(old_entries)] != old_entries
        or after["conservative_task_cost_usd"] + 1e-9
        < before["conservative_task_cost_usd"]
    ):
        raise FullModelTrainingError("plan087_cost_progression_invalid")
    return after


def validate_cost_sequence(previous: Any, values: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes, bytearray))
        or not values
    ):
        raise FullModelTrainingError("plan087_cost_progression_invalid")
    cursor = validate_cost_snapshot(previous)
    normalized: list[dict[str, Any]] = []
    for value in values:
        cursor = validate_cost_progression(cursor, value)
        normalized.append(cursor)
    return normalized


def validate_process_receipt(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema",
            "process_identity",
            "source_process_id",
            "status",
            "global_step",
            "runtime_identity_sha256",
            "route_context_sha256",
            "source",
        }
        or value.get("schema") != PROCESS_RECEIPT_SCHEMA
        or value.get("status") != "started"
        or not isinstance(value.get("global_step"), int)
        or isinstance(value["global_step"], bool)
        or value["global_step"] < 0
        or not _sha256(value.get("runtime_identity_sha256"))
        or not _sha256(value.get("route_context_sha256"))
        or not isinstance(value.get("source"), Mapping)
    ):
        raise FullModelTrainingError("plan087_process_receipt_invalid")
    identity = validate_process_identity(value.get("process_identity"))
    source_process_id = value.get("source_process_id")
    if source_process_id is not None and (
        not isinstance(source_process_id, str)
        or len(source_process_id) != 32
        or any(character not in "0123456789abcdef" for character in source_process_id)
        or source_process_id == identity["instance_id"]
    ):
        raise FullModelTrainingError("plan087_process_receipt_invalid")
    return json.loads(json.dumps(value))


def validate_recovery_receipt(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema",
            "checkpoint_id",
            "checkpoint_sha256",
            "runtime_identity_sha256",
            "route_context_sha256",
            "source_process_id",
            "recovery_process_id",
            "fresh_adapter",
            "model_loaded",
            "optimizer_scheduler_rng_data_equal",
            "probe_update_completed",
            "checkpoint_reuse_verified",
        }
        or value.get("schema") != RECOVERY_RECEIPT_SCHEMA
        or not _identifier(value.get("checkpoint_id"))
        or not _sha256(value.get("checkpoint_sha256"))
        or not _sha256(value.get("runtime_identity_sha256"))
        or not _sha256(value.get("route_context_sha256"))
        or not isinstance(value.get("source_process_id"), str)
        or not isinstance(value.get("recovery_process_id"), str)
        or value["source_process_id"] == value["recovery_process_id"]
        or any(
            value.get(key) is not True
            for key in (
                "fresh_adapter",
                "model_loaded",
                "optimizer_scheduler_rng_data_equal",
                "checkpoint_reuse_verified",
            )
        )
        or value.get("probe_update_completed") is not False
    ):
        raise FullModelTrainingError("plan087_recovery_receipt_invalid")
    for process_id in (value["source_process_id"], value["recovery_process_id"]):
        if len(process_id) != 32 or any(
            character not in "0123456789abcdef" for character in process_id
        ):
            raise FullModelTrainingError("plan087_recovery_receipt_invalid")
    return json.loads(json.dumps(value))


def candidate_evidence(
    base_observation: Mapping[str, Any], candidate_observation: Mapping[str, Any]
) -> dict[str, Any]:
    """Summarize broad evidence guards without pretending to be a product gate."""

    base = _observation_metrics(base_observation)
    candidate = _observation_metrics(candidate_observation)
    if base["validation_identity_sha256"] != candidate["validation_identity_sha256"]:
        raise FullModelTrainingError("plan087_candidate_cohort_mismatch")
    deltas = {
        key: candidate[key] - base[key]
        for key in (
            "roc_auc",
            "balanced_accuracy",
            "false_pass_rate",
            "boundary_strict_win_rate",
            "boundary_mean_margin",
            "within_pass_strict_win_rate",
            "within_pass_mean_margin",
        )
    }
    changed_pair_signals = [
        key
        for key in (
            "boundary_strict_win_rate",
            "boundary_mean_margin",
            "within_pass_strict_win_rate",
            "within_pass_mean_margin",
        )
        if deltas[key] != 0.0
    ]
    improving_pair_signals = [key for key in changed_pair_signals if deltas[key] > 0.0]
    ranking_improvement_signals = list(improving_pair_signals)
    if deltas["roc_auc"] > 0.0:
        ranking_improvement_signals.append("roc_auc")
    return {
        "validation_identity_sha256": base["validation_identity_sha256"],
        "base_global_step": base["global_step"],
        "candidate_global_step": candidate["global_step"],
        "metric_deltas": deltas,
        "changed_pair_signals": changed_pair_signals,
        "improving_pair_signals": improving_pair_signals,
        "ranking_improvement_signals": ranking_improvement_signals,
        "companion_metric_deltas": {
            key: deltas[key]
            for key in ("roc_auc", "balanced_accuracy", "false_pass_rate")
        },
        "uniform_logit_offset_alone_sufficient": False,
        "machine_promising_decision": None,
        "operator_judgment_required": True,
    }


def _observation_metrics(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        metrics = value["metrics"]
        overall = metrics["overall"]
        pair_margins = value["pair_margins"]
        validation_identity = value["validation"]["identity_sha256"]
        global_step = value["global_step"]
        boundary = [row for row in pair_margins if row["kind"] == "boundary"]
        within = [row for row in pair_margins if row["kind"] == "within_pass"]
        result = {
            "validation_identity_sha256": validation_identity,
            "global_step": global_step,
            "roc_auc": metrics["roc_auc"],
            "balanced_accuracy": overall["balanced_accuracy"],
            "false_pass_rate": overall["false_pass_rate"],
            "boundary_strict_win_rate": sum(
                row["signed_raw_margin"] > 0 for row in boundary
            )
            / len(boundary),
            "boundary_mean_margin": sum(row["signed_raw_margin"] for row in boundary)
            / len(boundary),
            "within_pass_strict_win_rate": sum(
                row["signed_raw_margin"] > 0 for row in within
            )
            / len(within),
            "within_pass_mean_margin": sum(row["signed_raw_margin"] for row in within)
            / len(within),
        }
    except (KeyError, TypeError, ZeroDivisionError) as exc:
        raise FullModelTrainingError("plan087_candidate_observation_invalid") from exc
    if (
        not _sha256(validation_identity)
        or not isinstance(global_step, int)
        or isinstance(global_step, bool)
        or global_step < 0
        or any(
            not isinstance(result[key], (int, float))
            or isinstance(result[key], bool)
            or not math.isfinite(float(result[key]))
            for key in result
            if key not in {"validation_identity_sha256", "global_step"}
        )
    ):
        raise FullModelTrainingError("plan087_candidate_observation_invalid")
    return result


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTIFIER.fullmatch(value))


def _optional_identifier(value: Any) -> bool:
    return value is None or _identifier(value)


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonnegative_number(value: Any) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise FullModelTrainingError("plan087_cost_snapshot_invalid")
    return float(value)
