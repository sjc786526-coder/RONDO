"""Route and terminal result finalizers for the Plan 087 adaptive search."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    sha256_bytes,
)
from .plan081_artifacts import Plan081ArtifactStore
from .plan082_controller import validate_process_identity
from .plan087_contract import (
    TERMINAL_OUTCOMES,
    candidate_evidence,
    validate_cost_progression,
    validate_cost_sequence,
    validate_cost_snapshot,
    validate_process_receipt,
    validate_recovery_receipt,
    validate_route_context,
)
from .plan087_controller import CONTROLLER_SCHEMA
from .plan087_run import validate_run_spec

ROUTE_RESULT_SCHEMA = "rondo-publication-critic-plan087-route-result-v1"
TERMINAL_RESULT_SCHEMA = "rondo-publication-critic-plan087-terminal-result-v1"
_ASSESSMENT_KEYS = {
    "clear_ranking_or_pair_improvement",
    "key_metrics_not_materially_collapsed",
    "not_noise_offset_or_threshold_only",
    "reviewed_complete_metrics",
}


def finalize_route(
    *,
    controller_state: Mapping[str, Any],
    artifact_root: Path,
    selected_observation_id: str,
    selected_checkpoint_id: str,
    operator_disposition: str,
    operator_reason: str,
    operator_assessment: Mapping[str, Any],
    cost_snapshots: Sequence[Mapping[str, Any]],
    process_receipt: Mapping[str, Any],
    recovery_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify one completed route and record the operator's bounded judgment."""

    if (
        not isinstance(controller_state, Mapping)
        or controller_state.get("schema") != CONTROLLER_SCHEMA
        or controller_state.get("status") not in {"paused", "completed"}
        or operator_disposition not in {"promising", "not_promising"}
        or not isinstance(operator_reason, str)
        or not operator_reason.strip()
    ):
        raise FullModelTrainingError("plan087_route_result_invalid")
    plan087 = controller_state.get("plan087")
    if not isinstance(plan087, Mapping):
        raise FullModelTrainingError("plan087_route_result_invalid")
    route_context = validate_route_context(plan087.get("route_context"))
    process = validate_process_receipt(process_receipt)
    recovery = validate_recovery_receipt(recovery_receipt)
    store = Plan081ArtifactStore(Path(artifact_root))
    base = store.read_observation("base-step-000000")
    selected = next(
        (
            record
            for record in controller_state.get("observations", [])
            if record.get("observation_id") == selected_observation_id
            and record.get("checkpoint_id") == selected_checkpoint_id
        ),
        None,
    )
    if selected is None:
        raise FullModelTrainingError("plan087_selected_checkpoint_observation_mismatch")
    observation = store.read_observation(selected_observation_id)
    checkpoint = store.verify_checkpoint(selected_checkpoint_id)
    evidence = candidate_evidence(base, observation)
    assessment = _validate_operator_assessment(operator_assessment)
    current_step = controller_state.get("current_step")
    control_plan = controller_state.get("control_plan")
    maximum_updates = (
        control_plan.get("maximum_updates")
        if isinstance(control_plan, Mapping)
        else None
    )
    if operator_disposition == "not_promising" and current_step != maximum_updates:
        raise FullModelTrainingError("plan087_not_promising_route_incomplete")
    if operator_disposition == "promising" and (
        not all(assessment.values())
        or not evidence["ranking_improvement_signals"]
    ):
        raise FullModelTrainingError("plan087_promising_candidate_evidence_invalid")
    recovered = plan087.get("recovery_proven_checkpoints")
    fresh_process_recovery = (
        isinstance(recovered, Mapping)
        and recovered.get(selected_checkpoint_id) == checkpoint["content_sha256"]
    )
    runtime_identity = plan087.get("runtime_identity")
    process_identity = validate_process_identity(plan087.get("process_identity"))
    route_context_sha256 = sha256_bytes(canonical_json_bytes(route_context))
    runtime_identity_sha256 = sha256_bytes(canonical_json_bytes(runtime_identity))
    if (
        not fresh_process_recovery
        or selected_checkpoint_id != controller_state.get("latest_checkpoint_id")
        or observation.get("global_step") != current_step
        or process["global_step"] != current_step
        or process["process_identity"] != process_identity
        or process_identity["instance_id"] != recovery["recovery_process_id"]
        or process["source_process_id"] != recovery["source_process_id"]
        or process["runtime_identity_sha256"] != runtime_identity_sha256
        or recovery["runtime_identity_sha256"] != runtime_identity_sha256
        or process["route_context_sha256"] != route_context_sha256
        or recovery["route_context_sha256"] != route_context_sha256
        or recovery["checkpoint_id"] != selected_checkpoint_id
        or recovery["checkpoint_sha256"] != checkpoint["content_sha256"]
    ):
        raise FullModelTrainingError("plan087_selected_checkpoint_recovery_required")
    run_spec = plan087.get("run_spec")
    if not isinstance(run_spec, Mapping):
        raise FullModelTrainingError("plan087_route_result_invalid")
    run_spec_sha256 = sha256_bytes(canonical_json_bytes(run_spec))
    observation_sha256 = store.verify_observation(selected_observation_id)["sha256"]
    cost_progression = validate_cost_sequence(
        route_context["cost_snapshot"], cost_snapshots
    )
    result = {
        "schema": ROUTE_RESULT_SCHEMA,
        "route_context": route_context,
        "controller_state_sha256": sha256_bytes(
            canonical_json_bytes(controller_state)
        ),
        "selected_observation": {
            "observation_id": selected_observation_id,
            "sha256": observation_sha256,
            "global_step": observation["global_step"],
        },
        "selected_checkpoint": {
            "checkpoint_id": selected_checkpoint_id,
            "content_sha256": checkpoint["content_sha256"],
            "bytes": checkpoint["bytes"],
            "qualified_restore_probe": True,
            "fresh_process_recovery": fresh_process_recovery,
            "remote_only": True,
        },
        "base_validation_observation": base,
        "selected_validation_observation": observation,
        "run_spec": json.loads(json.dumps(run_spec)),
        "run_spec_content_sha256": run_spec_sha256,
        "candidate_evidence": evidence,
        "operator_disposition": operator_disposition,
        "operator_reason": operator_reason,
        "operator_assessment": assessment,
        "process_receipt": process,
        "recovery_receipt": recovery,
        "selection_binding": {
            "observation_sha256": observation_sha256,
            "checkpoint_content_sha256": checkpoint["content_sha256"],
            "run_spec_content_sha256": run_spec_sha256,
            "operator_disposition": operator_disposition,
            "operator_assessment": assessment,
            "controller_current_step": current_step,
            "controller_latest_checkpoint_id": selected_checkpoint_id,
            "recovery_process_id": recovery["recovery_process_id"],
            "runtime_identity_sha256": runtime_identity_sha256,
            "route_context_sha256": route_context_sha256,
        },
        "cost_progression": cost_progression,
        "cost_snapshot": cost_progression[-1],
        "claims": {
            "research_candidate": operator_disposition == "promising",
            "clean_formal_reproduction": False,
            "product_go": False,
            "m3_c2_evidence": False,
            "unseen_evidence": False,
        },
    }
    return {**result, "content_sha256": sha256_bytes(canonical_json_bytes(result))}


def finalize_search(
    *,
    route_results: Sequence[Mapping[str, Any]],
    outcome: str,
    reason: str,
    selected_route_id: str | None,
    terminal_cost_snapshots: Sequence[Mapping[str, Any]],
    resource_state: Mapping[str, Any],
) -> dict[str, Any]:
    """Close one of the three Plan 087 outcomes after the compute stop gate."""

    if (
        outcome not in TERMINAL_OUTCOMES
        or not isinstance(reason, str)
        or not reason.strip()
        or not isinstance(route_results, Sequence)
        or isinstance(route_results, (str, bytes, bytearray))
    ):
        raise FullModelTrainingError("plan087_terminal_result_invalid")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    search_id: str | None = None
    prior_cost: dict[str, Any] | None = None
    for expected_generation, value in enumerate(route_results, start=1):
        route = validate_route_result(value)
        context = route["route_context"]
        expected_history = [summarize_route_result(item) for item in normalized]
        if search_id is None:
            search_id = context["search_id"]
        if (
            context["route_generation"] != expected_generation
            or context["route_id"] in seen
            or context["prior_route_summaries"] != expected_history
            or context["search_id"] != search_id
        ):
            raise FullModelTrainingError("plan087_terminal_route_history_invalid")
        if prior_cost is not None:
            validate_cost_progression(prior_cost, context["cost_snapshot"])
        seen.add(context["route_id"])
        normalized.append(route)
        prior_cost = route["cost_snapshot"]
    promising = [
        route for route in normalized if route["operator_disposition"] == "promising"
    ]
    if outcome == "PROMISING_CANDIDATE_RETAINED":
        if (
            len(promising) != 1
            or selected_route_id
            != promising[0]["route_context"]["route_id"]
        ):
            raise FullModelTrainingError("plan087_terminal_candidate_invalid")
    elif selected_route_id is not None or promising:
        raise FullModelTrainingError("plan087_terminal_candidate_invalid")
    if prior_cost is None:
        if (
            not isinstance(terminal_cost_snapshots, Sequence)
            or isinstance(terminal_cost_snapshots, (str, bytes, bytearray))
            or not terminal_cost_snapshots
        ):
            raise FullModelTrainingError("plan087_cost_progression_invalid")
        first = validate_cost_snapshot(terminal_cost_snapshots[0])
        if (
            first["snapshot_index"] != 0
            or first["previous_snapshot_content_sha256"] is not None
        ):
            raise FullModelTrainingError("plan087_cost_progression_invalid")
        terminal_progression = [first]
        if len(terminal_cost_snapshots) > 1:
            terminal_progression.extend(
                validate_cost_sequence(first, terminal_cost_snapshots[1:])
            )
    else:
        terminal_progression = validate_cost_sequence(
            prior_cost, terminal_cost_snapshots
        )
    cost = terminal_progression[-1]
    if outcome == "BUDGET_EXHAUSTED_NO_CANDIDATE" and cost[
        "next_action_authorized"
    ]:
        raise FullModelTrainingError("plan087_budget_terminal_has_next_closure")
    resources = _validate_resource_state(resource_state)
    result = {
        "schema": TERMINAL_RESULT_SCHEMA,
        "outcome": outcome,
        "reason": reason,
        "selected_route_id": selected_route_id,
        "routes": normalized,
        "terminal_cost_progression": terminal_progression,
        "terminal_cost_snapshot": cost,
        "resources": resources,
        "claims": {
            "research_task_completed": outcome
            in {
                "PROMISING_CANDIDATE_RETAINED",
                "BUDGET_EXHAUSTED_NO_CANDIDATE",
            },
            "budget_search_no_candidate": outcome
            == "BUDGET_EXHAUSTED_NO_CANDIDATE",
            "model_route_failed": False,
            "infrastructure_inconclusive": outcome
            == "INCONCLUSIVE_INFRASTRUCTURE",
            "clean_formal_reproduction": False,
            "product_go": False,
            "m3_c2_evidence": False,
            "unseen_evidence": False,
        },
    }
    return {**result, "content_sha256": sha256_bytes(canonical_json_bytes(result))}


def validate_route_result(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "route_context",
        "controller_state_sha256",
        "selected_observation",
        "selected_checkpoint",
        "base_validation_observation",
        "selected_validation_observation",
        "run_spec",
        "run_spec_content_sha256",
        "candidate_evidence",
        "operator_disposition",
        "operator_reason",
        "operator_assessment",
        "process_receipt",
        "recovery_receipt",
        "selection_binding",
        "cost_progression",
        "cost_snapshot",
        "claims",
        "content_sha256",
    }:
        raise FullModelTrainingError("plan087_route_result_invalid")
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    if (
        value.get("schema") != ROUTE_RESULT_SCHEMA
        or value.get("content_sha256") != sha256_bytes(canonical_json_bytes(core))
        or value.get("operator_disposition") not in {"promising", "not_promising"}
        or not isinstance(value.get("operator_reason"), str)
        or not value["operator_reason"].strip()
    ):
        raise FullModelTrainingError("plan087_route_result_invalid")
    context = validate_route_context(value.get("route_context"))
    cost_progression = validate_cost_sequence(
        context["cost_snapshot"], value.get("cost_progression")
    )
    cost = cost_progression[-1]
    assessment = _validate_operator_assessment(value.get("operator_assessment"))
    process = validate_process_receipt(value.get("process_receipt"))
    recovery = validate_recovery_receipt(value.get("recovery_receipt"))
    run_spec = value.get("run_spec")
    selected_observation = value.get("selected_observation")
    selected_checkpoint = value.get("selected_checkpoint")
    selected_payload = value.get("selected_validation_observation")
    base_payload = value.get("base_validation_observation")
    binding = value.get("selection_binding")
    evidence = (
        candidate_evidence(base_payload, selected_payload)
        if isinstance(base_payload, Mapping)
        and isinstance(selected_payload, Mapping)
        else None
    )
    expected_claims = {
        "research_candidate": value.get("operator_disposition") == "promising",
        "clean_formal_reproduction": False,
        "product_go": False,
        "m3_c2_evidence": False,
        "unseen_evidence": False,
    }
    if (
        not isinstance(run_spec, Mapping)
        or validate_run_spec(run_spec)["route_context"] != context
        or value.get("run_spec_content_sha256")
        != sha256_bytes(canonical_json_bytes(run_spec))
        or not isinstance(selected_observation, Mapping)
        or not isinstance(selected_checkpoint, Mapping)
        or not isinstance(base_payload, Mapping)
        or not isinstance(selected_payload, Mapping)
        or selected_observation.get("sha256")
        != sha256_bytes(pretty_json_bytes(selected_payload))
        or selected_observation.get("global_step")
        != selected_payload.get("global_step")
        or value.get("candidate_evidence") != evidence
        or value.get("cost_progression") != cost_progression
        or value.get("cost_snapshot") != cost
        or value.get("claims") != expected_claims
        or not isinstance(binding, Mapping)
        or binding
        != {
            "observation_sha256": selected_observation.get("sha256"),
            "checkpoint_content_sha256": selected_checkpoint.get("content_sha256"),
            "run_spec_content_sha256": value.get("run_spec_content_sha256"),
            "operator_disposition": value.get("operator_disposition"),
            "operator_assessment": assessment,
            "controller_current_step": selected_observation.get("global_step"),
            "controller_latest_checkpoint_id": selected_checkpoint.get(
                "checkpoint_id"
            ),
            "recovery_process_id": recovery["recovery_process_id"],
            "runtime_identity_sha256": recovery["runtime_identity_sha256"],
            "route_context_sha256": recovery["route_context_sha256"],
        }
        or process["process_identity"]["instance_id"]
        != recovery["recovery_process_id"]
        or process["source_process_id"] != recovery["source_process_id"]
        or process["global_step"] != selected_observation.get("global_step")
        or process["runtime_identity_sha256"]
        != recovery["runtime_identity_sha256"]
        or process["route_context_sha256"]
        != recovery["route_context_sha256"]
        or recovery["route_context_sha256"]
        != sha256_bytes(canonical_json_bytes(context))
        or recovery["checkpoint_id"] != selected_checkpoint.get("checkpoint_id")
        or recovery["checkpoint_sha256"]
        != selected_checkpoint.get("content_sha256")
        or selected_checkpoint.get("fresh_process_recovery") is not True
        or (
            value.get("operator_disposition") == "not_promising"
            and selected_observation.get("global_step")
            != run_spec.get("control_plan", {}).get("maximum_updates")
        )
        or (
            value.get("operator_disposition") == "promising"
            and (
                not all(assessment.values())
                or not evidence["ranking_improvement_signals"]
            )
        )
    ):
        raise FullModelTrainingError("plan087_route_result_invalid")
    return json.loads(json.dumps(value))


def summarize_route_result(value: Any) -> dict[str, Any]:
    """Produce the exact compact lineage row accepted by the next route."""

    route = validate_route_result(value)
    if route["operator_disposition"] != "not_promising":
        raise FullModelTrainingError("plan087_promising_route_is_terminal")
    context = route["route_context"]
    return {
        "search_id": context["search_id"],
        "route_id": context["route_id"],
        "route_generation": context["route_generation"],
        "route_result_content_sha256": route["content_sha256"],
        "run_spec_content_sha256": route["run_spec_content_sha256"],
        "terminal_observation_id": route["selected_observation"]["observation_id"],
        "terminal_observation_sha256": route["selected_observation"]["sha256"],
        "selected_checkpoint_content_sha256": route["selected_checkpoint"][
            "content_sha256"
        ],
        "candidate_disposition": "not_promising",
        "reason": route["operator_reason"],
        "cost_snapshot_index": route["cost_snapshot"]["snapshot_index"],
        "cost_snapshot_content_sha256": route["cost_snapshot"]["content_sha256"],
        "baseline_balance_usd": route["cost_snapshot"]["baseline_balance_usd"],
        "current_balance_usd": route["cost_snapshot"]["current_balance_usd"],
        "conservative_task_cost_usd": route["cost_snapshot"][
            "conservative_task_cost_usd"
        ],
    }


def _validate_operator_assessment(value: Any) -> dict[str, bool]:
    if (
        not isinstance(value, Mapping)
        or set(value) != _ASSESSMENT_KEYS
        or any(type(item) is not bool for item in value.values())
    ):
        raise FullModelTrainingError("plan087_operator_assessment_invalid")
    return {key: bool(value[key]) for key in sorted(_ASSESSMENT_KEYS)}


def _validate_resource_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "captured_at",
        "pod_count",
        "compute_rate_usd_per_hour",
        "volumes",
    }:
        raise FullModelTrainingError("plan087_resource_state_invalid")
    volumes = value.get("volumes")
    if (
        not isinstance(value.get("captured_at"), str)
        or not value["captured_at"].strip()
        or value.get("pod_count") != 0
        or value.get("compute_rate_usd_per_hour") != 0
        or not isinstance(volumes, Sequence)
        or isinstance(volumes, (str, bytes, bytearray))
        or not volumes
    ):
        raise FullModelTrainingError("plan087_resource_state_invalid")
    normalized: list[dict[str, Any]] = []
    for volume in volumes:
        if (
            not isinstance(volume, Mapping)
            or set(volume)
            != {
                "id",
                "region",
                "size_gb",
                "role",
                "continuing_rate_usd_per_hour",
                "deleted",
            }
            or not isinstance(volume.get("id"), str)
            or not volume["id"]
            or not isinstance(volume.get("region"), str)
            or not volume["region"]
            or not isinstance(volume.get("size_gb"), int)
            or isinstance(volume["size_gb"], bool)
            or not 0 < volume["size_gb"] <= 60
            or not isinstance(volume.get("role"), str)
            or not volume["role"].strip()
            or not isinstance(volume.get("continuing_rate_usd_per_hour"), (int, float))
            or isinstance(volume["continuing_rate_usd_per_hour"], bool)
            or float(volume["continuing_rate_usd_per_hour"]) < 0
            or volume.get("deleted") is not False
        ):
            raise FullModelTrainingError("plan087_resource_state_invalid")
        normalized.append(dict(volume))
    return {**json.loads(json.dumps(value)), "volumes": normalized}
