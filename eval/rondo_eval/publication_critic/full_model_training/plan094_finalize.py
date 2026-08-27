"""Terminal classification and zero-compute closure for Plan 094."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contract import FullModelTrainingError, canonical_json_bytes, sha256_bytes
from .plan094_artifacts import Plan094ArtifactStore
from .plan094_contract import (
    assess_material,
    decide_stop,
    freeze_sha256,
    validate_budget_snapshot,
    validate_freeze,
    validate_run_spec,
)
from .plan094_controller import CONTROLLER_SCHEMA, validate_runtime_identity

TERMINAL_SCHEMA = "rondo-publication-critic-plan094-terminal-result-v1"
CHECKPOINT_QUALIFICATION_SCHEMA = (
    "rondo-publication-critic-plan094-terminal-checkpoint-qualification-v1"
)
MODEL_OUTCOMES = {
    "ROUTE_O_MATERIAL_CANDIDATE_RETAINED",
    "ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT",
}
OUTCOMES = MODEL_OUTCOMES | {"INCONCLUSIVE"}


def finalize_terminal(
    *,
    freeze: Mapping[str, Any],
    controller_state: Mapping[str, Any],
    artifact_root: Path,
    resource_state: Mapping[str, Any],
    terminal_budget_snapshot: Mapping[str, Any],
    checkpoint_qualification: Mapping[str, Any] | None = None,
    outcome: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    contract = validate_freeze(freeze)
    store = Plan094ArtifactStore(Path(artifact_root))
    state = _validate_controller_state(
        contract, controller_state, store
    )
    resources = validate_resource_state(resource_state)
    budget = validate_budget_snapshot(terminal_budget_snapshot)
    launch_budget = validate_budget_snapshot(
        state["plan094"].get("launch_budget_snapshot")
    )
    if (
        launch_budget["stage_b_baseline_balance_usd"]
        != budget["stage_b_baseline_balance_usd"]
        or launch_budget["stage_b_baseline_known_unsettled_usd"]
        != budget["stage_b_baseline_known_unsettled_usd"]
        or budget["conservative_task_cost_usd"] + 1e-12
        < launch_budget["conservative_task_cost_usd"]
    ):
        raise FullModelTrainingError("plan094_terminal_budget_history_invalid")
    decision = state["plan094"]["stop_decision"]
    selected_outcome = outcome or (
        decision["outcome"] if isinstance(decision, Mapping) else None
    )
    if selected_outcome not in OUTCOMES:
        raise FullModelTrainingError("plan094_terminal_outcome_invalid")
    if selected_outcome in MODEL_OUTCOMES:
        if (
            state["status"] != "terminal"
            or not isinstance(decision, Mapping)
            or decision.get("terminal") is not True
            or decision.get("outcome") != selected_outcome
            or not state["plan094"]["recovery_proven_checkpoints"]
            or state["plan094"]["terminal_deferred_for_recovery"] is not False
        ):
            raise FullModelTrainingError("plan094_terminal_model_closure_incomplete")
        terminal_reason = str(decision["reason"])
    else:
        if isinstance(decision, Mapping) and decision.get("terminal") is True:
            raise FullModelTrainingError(
                "plan094_infrastructure_cannot_override_model_result"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise FullModelTrainingError("plan094_inconclusive_reason_required")
        terminal_reason = reason.strip()
    if reason is not None and selected_outcome in MODEL_OUTCOMES:
        if reason != terminal_reason:
            raise FullModelTrainingError("plan094_terminal_reason_drifted")

    roles = state["plan094"]["checkpoint_roles"]
    selected_checkpoint_id = (
        roles.get("material_candidate")
        if selected_outcome == "ROUTE_O_MATERIAL_CANDIDATE_RETAINED"
        else roles.get("latest")
    )
    results_by_checkpoint = {
        checkpoint_id: store.read_evaluation_result(checkpoint_id)
        for checkpoint_id in state["plan094"]["evaluation_overlays"]
    }
    selected_result = results_by_checkpoint.get(selected_checkpoint_id)
    if selected_outcome in MODEL_OUTCOMES:
        if (
            selected_result is None
            or selected_result["checkpoint"].get("source_external") is not False
        ):
            raise FullModelTrainingError("plan094_terminal_checkpoint_missing")
        if checkpoint_qualification is not None:
            checkpoint_qualification = _validate_checkpoint_qualification(
                checkpoint_qualification,
                contract=contract,
                state=state,
                results_by_checkpoint=results_by_checkpoint,
                selected_checkpoint_id=selected_checkpoint_id,
            )
        else:
            _verify_live_terminal_checkpoints(
                contract=contract,
                state=state,
                store=store,
                results_by_checkpoint=results_by_checkpoint,
                selected_checkpoint_id=selected_checkpoint_id,
            )
    core = {
        "schema": TERMINAL_SCHEMA,
        "outcome": selected_outcome,
        "reason": terminal_reason,
        "freeze_sha256": freeze_sha256(contract),
        "run_spec": state["plan094"]["run_spec"],
        "launch_budget_snapshot": state["plan094"]["launch_budget_snapshot"],
        "continuation_origin": state["plan094"]["continuation_origin"],
        "global_step": state["current_step"],
        "evaluated_checkpoint_ids": list(
            state["plan094"]["evaluation_overlays"]
        ),
        "checkpoint_roles": roles,
        "selected_checkpoint_id": selected_checkpoint_id,
        "selected_assessment": (
            selected_result["assessment"] if selected_result is not None else None
        ),
        "recovery_proven_checkpoints": state["plan094"][
            "recovery_proven_checkpoints"
        ],
        "runtime_identity": state["plan094"]["runtime_identity"],
        "resource_state": resources,
        "terminal_budget_snapshot": budget,
        "claims": {
            "same_frozen_validation_selection_only": True,
            "checkpoint_first_observations": True,
            "fresh_process_restore_and_continue": bool(
                state["plan094"]["recovery_proven_checkpoints"]
            ),
            "route_o_material_candidate": selected_outcome
            == "ROUTE_O_MATERIAL_CANDIDATE_RETAINED",
            "valid_no_material_trajectory": selected_outcome
            == "ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT",
            "seed_sensitive_stability_tested": False,
            "independent_cohort_generalization": False,
            "unseen_evidence": False,
            "product_go": False,
            "m3_c1_or_m3_c2": False,
            "m3_d_unlocked": False,
            "all_task_pods_released": True,
        },
    }
    if checkpoint_qualification is not None:
        core["checkpoint_qualification"] = checkpoint_qualification
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def _verify_live_terminal_checkpoints(
    *,
    contract: Mapping[str, Any],
    state: Mapping[str, Any],
    store: Plan094ArtifactStore,
    results_by_checkpoint: Mapping[str, Mapping[str, Any]],
    selected_checkpoint_id: str,
) -> None:
    selected_result = results_by_checkpoint[selected_checkpoint_id]
    try:
        selected_checkpoint = store.verify_checkpoint(selected_checkpoint_id)
    except FullModelTrainingError as exc:
        raise FullModelTrainingError("plan094_terminal_checkpoint_missing") from exc
    if (
        selected_checkpoint["content_sha256"]
        != selected_result["checkpoint"]["content_sha256"]
    ):
        raise FullModelTrainingError("plan094_terminal_checkpoint_missing")
    owned = store.verified_checkpoint_ids()
    if len(owned) > contract["retention"]["maximum_owned_full_checkpoints"]:
        raise FullModelTrainingError("plan094_terminal_retention_exceeded")
    roles = state["plan094"]["checkpoint_roles"]
    hard_role_ids = [
        roles.get("material_candidate"),
        roles.get("latest"),
        roles.get("fresh_process_recovery"),
        *roles.get("turning_points", []),
    ]
    for checkpoint_id in {
        identifier for identifier in hard_role_ids if isinstance(identifier, str)
    }:
        retained_result = results_by_checkpoint.get(checkpoint_id)
        if (
            retained_result is None
            or retained_result["checkpoint"].get("source_external") is not False
        ):
            raise FullModelTrainingError(
                "plan094_terminal_retained_checkpoint_missing"
            )
        try:
            retained_checkpoint = store.verify_checkpoint(checkpoint_id)
        except FullModelTrainingError as exc:
            raise FullModelTrainingError(
                "plan094_terminal_retained_checkpoint_missing"
            ) from exc
        if (
            retained_checkpoint["content_sha256"]
            != retained_result["checkpoint"]["content_sha256"]
        ):
            raise FullModelTrainingError(
                "plan094_terminal_retained_checkpoint_missing"
            )
    for checkpoint_id, digest in state["plan094"][
        "recovery_proven_checkpoints"
    ].items():
        try:
            recovered_checkpoint = store.verify_checkpoint(checkpoint_id)
        except FullModelTrainingError as exc:
            raise FullModelTrainingError("plan094_terminal_recovery_missing") from exc
        if recovered_checkpoint["content_sha256"] != digest:
            raise FullModelTrainingError("plan094_terminal_recovery_missing")


def qualify_terminal_checkpoints(
    *,
    freeze: Mapping[str, Any],
    controller_state: Mapping[str, Any],
    artifact_root: Path,
) -> dict[str, Any]:
    """Deep-verify retained weights before zero-Pod closure and freeze a small receipt."""

    contract = validate_freeze(freeze)
    store = Plan094ArtifactStore(Path(artifact_root))
    state = _validate_controller_state(contract, controller_state, store)
    decision = state["plan094"].get("stop_decision")
    if (
        state.get("status") != "terminal"
        or not isinstance(decision, Mapping)
        or decision.get("terminal") is not True
        or decision.get("outcome") not in MODEL_OUTCOMES
        or not state["plan094"].get("recovery_proven_checkpoints")
        or state["plan094"].get("terminal_deferred_for_recovery") is not False
    ):
        raise FullModelTrainingError("plan094_terminal_model_closure_incomplete")
    roles = state["plan094"]["checkpoint_roles"]
    selected_checkpoint_id = (
        roles.get("material_candidate")
        if decision["outcome"] == "ROUTE_O_MATERIAL_CANDIDATE_RETAINED"
        else roles.get("latest")
    )
    results_by_checkpoint = {
        checkpoint_id: store.read_evaluation_result(checkpoint_id)
        for checkpoint_id in state["plan094"]["evaluation_overlays"]
    }
    expected = _required_terminal_checkpoints(
        state,
        results_by_checkpoint=results_by_checkpoint,
        selected_checkpoint_id=selected_checkpoint_id,
    )
    _verify_live_terminal_checkpoints(
        contract=contract,
        state=state,
        store=store,
        results_by_checkpoint=results_by_checkpoint,
        selected_checkpoint_id=selected_checkpoint_id,
    )
    owned = store.verified_checkpoint_ids()
    if any(checkpoint_id not in results_by_checkpoint for checkpoint_id in owned):
        raise FullModelTrainingError(
            "plan094_terminal_checkpoint_qualification_invalid"
        )
    verified = {
        checkpoint_id: results_by_checkpoint[checkpoint_id]["checkpoint"][
            "content_sha256"
        ]
        for checkpoint_id in owned
    }
    if any(
        verified.get(identifier) != digest
        for identifier, digest in expected.items()
    ):
        raise FullModelTrainingError(
            "plan094_terminal_checkpoint_qualification_invalid"
        )
    core = {
        "schema": CHECKPOINT_QUALIFICATION_SCHEMA,
        "freeze_sha256": freeze_sha256(contract),
        "controller_state_sha256": sha256_bytes(canonical_json_bytes(state)),
        "artifact_namespace": state["plan094"]["run_spec"]["artifact_namespace"],
        "owned_checkpoints": verified,
        "required_checkpoint_ids": sorted(expected),
    }
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def _required_terminal_checkpoints(
    state: Mapping[str, Any],
    *,
    results_by_checkpoint: Mapping[str, Mapping[str, Any]],
    selected_checkpoint_id: Any,
) -> dict[str, str]:
    if not isinstance(selected_checkpoint_id, str):
        raise FullModelTrainingError("plan094_terminal_checkpoint_missing")
    roles = state["plan094"]["checkpoint_roles"]
    identifiers = {
        identifier
        for identifier in (
            selected_checkpoint_id,
            roles.get("material_candidate"),
            roles.get("latest"),
            roles.get("fresh_process_recovery"),
            *roles.get("turning_points", []),
            *state["plan094"]["recovery_proven_checkpoints"],
        )
        if isinstance(identifier, str)
    }
    expected: dict[str, str] = {}
    for checkpoint_id in identifiers:
        result = results_by_checkpoint.get(checkpoint_id)
        if (
            result is None
            or result["checkpoint"].get("source_external") is not False
        ):
            raise FullModelTrainingError("plan094_terminal_checkpoint_missing")
        digest = result["checkpoint"].get("content_sha256")
        recovered = state["plan094"]["recovery_proven_checkpoints"].get(
            checkpoint_id
        )
        if recovered is not None and recovered != digest:
            raise FullModelTrainingError("plan094_terminal_recovery_missing")
        expected[checkpoint_id] = digest
    return expected


def _validate_checkpoint_qualification(
    value: Any,
    *,
    contract: Mapping[str, Any],
    state: Mapping[str, Any],
    results_by_checkpoint: Mapping[str, Mapping[str, Any]],
    selected_checkpoint_id: Any,
) -> dict[str, Any]:
    required_fields = {
        "schema",
        "freeze_sha256",
        "controller_state_sha256",
        "artifact_namespace",
        "owned_checkpoints",
        "required_checkpoint_ids",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required_fields:
        raise FullModelTrainingError(
            "plan094_terminal_checkpoint_qualification_invalid"
        )
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    owned = value.get("owned_checkpoints")
    if (
        value.get("schema") != CHECKPOINT_QUALIFICATION_SCHEMA
        or value.get("content_sha256") != sha256_bytes(canonical_json_bytes(core))
        or value.get("freeze_sha256") != freeze_sha256(contract)
        or value.get("controller_state_sha256")
        != sha256_bytes(canonical_json_bytes(state))
        or value.get("artifact_namespace")
        != state["plan094"]["run_spec"]["artifact_namespace"]
        or not isinstance(owned, Mapping)
        or len(owned) > contract["retention"]["maximum_owned_full_checkpoints"]
        or any(
            not isinstance(key, str) or not _sha256(digest)
            for key, digest in owned.items()
        )
    ):
        raise FullModelTrainingError(
            "plan094_terminal_checkpoint_qualification_invalid"
        )
    expected = _required_terminal_checkpoints(
        state,
        results_by_checkpoint=results_by_checkpoint,
        selected_checkpoint_id=selected_checkpoint_id,
    )
    if (
        value.get("required_checkpoint_ids") != sorted(expected)
        or any(
            owned.get(identifier) != digest
            for identifier, digest in expected.items()
        )
        or any(
            checkpoint_id not in results_by_checkpoint
            or results_by_checkpoint[checkpoint_id]["checkpoint"].get("content_sha256")
            != digest
            for checkpoint_id, digest in owned.items()
        )
    ):
        raise FullModelTrainingError(
            "plan094_terminal_checkpoint_qualification_invalid"
        )
    return json.loads(json.dumps(value))


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_controller_state(
    freeze: Mapping[str, Any],
    value: Mapping[str, Any],
    store: Plan094ArtifactStore,
) -> dict[str, Any]:
    plan094 = value.get("plan094") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or value.get("schema") != CONTROLLER_SCHEMA
        or not isinstance(plan094, Mapping)
        or plan094.get("freeze") != freeze
        or plan094.get("freeze_sha256") != freeze_sha256(freeze)
        or validate_run_spec(plan094.get("run_spec"), freeze=freeze)
        != plan094.get("run_spec")
        or plan094["run_spec"].get("run_kind") != "formal"
        or not isinstance(plan094.get("continuation_origin"), Mapping)
        or plan094["continuation_origin"].get("mode")
        != plan094["run_spec"].get("continuation_mode")
        or validate_runtime_identity(
            plan094.get("runtime_identity"), run_spec=plan094["run_spec"]
        )
        != plan094.get("runtime_identity")
        or not isinstance(value.get("base"), Mapping)
        or plan094.get("pending_checkpoint") is not None
        or not isinstance(value.get("observations"), list)
        or not isinstance(plan094.get("evaluation_overlays"), list)
        or len(value["observations"]) != len(plan094["evaluation_overlays"])
        or any(not isinstance(row, Mapping) for row in value["observations"])
        or [row.get("checkpoint_id") for row in value["observations"]]
        != plan094["evaluation_overlays"]
    ):
        raise FullModelTrainingError("plan094_terminal_controller_invalid")
    results = [
        store.read_evaluation_result(identifier)
        for identifier in plan094["evaluation_overlays"]
    ]
    if results:
        base = store.read_observation("base-step-000000")
        assessments = [
            assess_material(
                freeze,
                base_validation=base,
                candidate_validation=result["validation_observation"],
                candidate_eligible=result["checkpoint"].get("source_external")
                is not True,
            )
            for result in results
        ]
        if (
            [row["assessment"] for row in results] != assessments
            or plan094.get("stop_decision") != decide_stop(freeze, assessments)
            or results[-1].get("stop_decision") != plan094.get("stop_decision")
            or results[-1].get("checkpoint_roles_after")
            != plan094.get("checkpoint_roles")
        ):
            raise FullModelTrainingError("plan094_terminal_controller_invalid")
    return json.loads(json.dumps(value))


def validate_resource_state(value: Any) -> dict[str, Any]:
    required = {
        "captured_at",
        "pod_count",
        "compute_rate_usd_per_hour",
        "volume",
    }
    volume = value.get("volume") if isinstance(value, Mapping) else None
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or not isinstance(value.get("captured_at"), str)
        or not value["captured_at"].strip()
        or value.get("pod_count") != 0
        or not _zero(value.get("compute_rate_usd_per_hour"))
        or not isinstance(volume, Mapping)
        or set(volume) != {"id", "region", "size_gb", "deleted", "rate_usd_per_hour"}
        or volume.get("id") != "mwemzrn33y"
        or volume.get("region") != "US-TX-3"
        or volume.get("deleted") is not False
        or not isinstance(volume.get("size_gb"), int)
        or isinstance(volume["size_gb"], bool)
        or not 57 <= volume["size_gb"] <= 80
        or not _nonnegative(volume.get("rate_usd_per_hour"))
    ):
        raise FullModelTrainingError("plan094_terminal_resource_state_invalid")
    return json.loads(json.dumps(value))


def _zero(value: Any) -> bool:
    return _nonnegative(value) and float(value) == 0.0


def _nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


__all__ = [
    "CHECKPOINT_QUALIFICATION_SCHEMA",
    "MODEL_OUTCOMES",
    "OUTCOMES",
    "TERMINAL_SCHEMA",
    "finalize_terminal",
    "qualify_terminal_checkpoints",
    "validate_resource_state",
]
