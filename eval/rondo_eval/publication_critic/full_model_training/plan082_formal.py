"""Freeze and terminal semantics for a clean Plan 082 formal run."""

from __future__ import annotations

from collections.abc import Mapping
import json
import math
from pathlib import Path
import re
from typing import Any

from .contract import (
    MODEL_REPOSITORY,
    MODEL_REVISION,
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    sha256_bytes,
    sha256_file,
    write_exclusive,
)
from .plan081_contract import ComparisonPolicy, compare_values, validate_route_contract
from .plan081_artifacts import Plan081ArtifactStore
from .plan081_controller import _selection_from_records, _turning_points_from_records
from .plan082_adapter import MODEL_LOCK_SHA256
from .plan082_bundle import SOURCE_BUNDLE_SCHEMA, verify_data_bundle
from .plan082_controller import (
    CONTROLLER_SCHEMA,
    REAL_RUNTIME_PROFILE,
    Plan082ContinuousTrainingController,
    validate_process_identity,
    validate_runtime_identity,
)
from .plan082_run import frozen_scope_history, validate_run_spec


FREEZE_SCHEMA = "rondo-publication-critic-plan082-formal-freeze-v1"
RECOVERY_SCHEMA = "rondo-publication-critic-plan082-recovery-receipt-v1"
RESULT_SCHEMA = "rondo-publication-critic-plan082-formal-result-v1"
TERMINALS = frozenset({"TRAINING_IMPROVEMENT_FOUND", "VALID_NO_IMPROVEMENT"})
_RUN_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_OID = re.compile(r"[0-9a-f]{40}\Z")
_PROCESS_ID = re.compile(r"[0-9a-f]{32}\Z")


def create_formal_freeze(
    destination: Path,
    *,
    run_id: str,
    formal_namespace: Path,
    source_receipt: Mapping[str, Any],
    data_bundle_root: Path,
    route_contract: Mapping[str, Any],
    runtime_identity: Mapping[str, Any],
    parameter_inventory: Mapping[str, Any],
    run_spec: Mapping[str, Any],
    retention: Mapping[str, Any],
) -> dict[str, Any]:
    """Write the freeze before the formal output namespace can exist."""

    target = Path(destination).resolve()
    namespace = Path(formal_namespace).resolve()
    if (
        target.exists()
        or target.is_symlink()
        or namespace.exists()
        or namespace.is_symlink()
        or target == namespace
        or target.is_relative_to(namespace)
    ):
        raise FullModelTrainingError("plan082_formal_namespace_not_pristine")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise FullModelTrainingError("plan082_formal_run_id_invalid")
    route = validate_route_contract(route_contract)
    runtime = validate_runtime_identity(runtime_identity)
    run_spec_value = validate_run_spec(run_spec)
    inventory = _freeze_parameter_inventory(parameter_inventory, runtime)
    _validate_formal_scope_bounds(runtime, run_spec_value, inventory)
    control = run_spec_value["control_plan"]
    recovery_steps = [
        step
        for step in control["checkpoint_steps"]
        if step < control["maximum_updates"]
    ]
    if not recovery_steps:
        raise FullModelTrainingError("plan082_formal_recovery_step_missing")
    recovery_checkpoint_step = max(recovery_steps)
    if runtime["recipe_sha256"] != sha256_bytes(
        canonical_json_bytes(run_spec_value["recipe"])
    ):
        raise FullModelTrainingError("plan082_freeze_recipe_runtime_mismatch")
    data_receipt = verify_data_bundle(data_bundle_root)
    source = _validate_source_receipt(source_receipt)
    retention_value = _validate_retention(retention)
    body = {
        "schema": FREEZE_SCHEMA,
        "run_id": run_id,
        "formal_namespace": str(namespace),
        "source": source,
        "model": {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "model_lock_sha256": MODEL_LOCK_SHA256,
            "snapshot_content_sha256": runtime["snapshot_content_sha256"],
        },
        "data": data_receipt,
        "route_contract_sha256": sha256_bytes(canonical_json_bytes(route)),
        "runtime_identity": runtime,
        "parameter_inventory": inventory,
        "run_spec": run_spec_value,
        "recovery_checkpoint_step": recovery_checkpoint_step,
        "retention": retention_value,
        "formal_results_observed_before_freeze": False,
    }
    value = {
        **body,
        "freeze_content_sha256": sha256_bytes(canonical_json_bytes(body)),
    }
    write_exclusive(target, pretty_json_bytes(value))
    return {
        "freeze": value,
        "path": str(target),
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
    }


def load_formal_freeze(path: Path) -> dict[str, Any]:
    return validate_formal_freeze(read_json(Path(path)))


def validate_formal_freeze(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "run_id",
        "formal_namespace",
        "source",
        "model",
        "data",
        "route_contract_sha256",
        "runtime_identity",
        "parameter_inventory",
        "run_spec",
        "recovery_checkpoint_step",
        "retention",
        "formal_results_observed_before_freeze",
        "freeze_content_sha256",
    }:
        raise FullModelTrainingError("plan082_formal_freeze_fields_invalid")
    body = {key: value[key] for key in value if key != "freeze_content_sha256"}
    if (
        value.get("schema") != FREEZE_SCHEMA
        or not isinstance(value.get("run_id"), str)
        or _RUN_ID.fullmatch(value["run_id"]) is None
        or not isinstance(value.get("formal_namespace"), str)
        or not Path(value["formal_namespace"]).is_absolute()
        or value.get("formal_results_observed_before_freeze") is not False
        or value.get("freeze_content_sha256")
        != sha256_bytes(canonical_json_bytes(body))
        or _SHA256.fullmatch(str(value.get("route_contract_sha256"))) is None
    ):
        raise FullModelTrainingError("plan082_formal_freeze_invalid")
    _validate_source_receipt(value["source"])
    runtime = validate_runtime_identity(value["runtime_identity"])
    run_spec = validate_run_spec(value["run_spec"])
    inventory = _validate_frozen_parameter_inventory(
        value["parameter_inventory"], runtime
    )
    _validate_formal_scope_bounds(runtime, run_spec, inventory)
    recovery_step = value.get("recovery_checkpoint_step")
    control = run_spec["control_plan"]
    intermediate_steps = [
        step
        for step in control["checkpoint_steps"]
        if step < control["maximum_updates"]
    ]
    if (
        not intermediate_steps
        or not isinstance(recovery_step, int)
        or isinstance(recovery_step, bool)
        or recovery_step >= control["maximum_updates"]
        or recovery_step not in control["checkpoint_steps"]
        or recovery_step != max(intermediate_steps)
    ):
        raise FullModelTrainingError("plan082_formal_recovery_step_invalid")
    if value.get("model") != {
        "repository": MODEL_REPOSITORY,
        "revision": MODEL_REVISION,
        "model_lock_sha256": MODEL_LOCK_SHA256,
        "snapshot_content_sha256": runtime["snapshot_content_sha256"],
    } or runtime["recipe_sha256"] != sha256_bytes(
        canonical_json_bytes(run_spec["recipe"])
    ):
        raise FullModelTrainingError("plan082_formal_freeze_identity_invalid")
    _validate_data_receipt(value["data"])
    _validate_retention(value["retention"])
    return json.loads(json.dumps(value))


def validate_recovery_receipt(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema",
            "checkpoint_id",
            "checkpoint_sha256",
            "formal_freeze_sha256",
            "run_id",
            "formal_namespace",
            "runtime_identity_sha256",
            "source_process_id",
            "recovery_process_id",
            "fresh_adapter",
            "model_loaded",
            "optimizer_scheduler_rng_data_equal",
            "probe_update_completed",
        }
        or value.get("schema") != RECOVERY_SCHEMA
        or not isinstance(value.get("checkpoint_id"), str)
        or not value["checkpoint_id"]
        or _SHA256.fullmatch(str(value.get("checkpoint_sha256"))) is None
        or _SHA256.fullmatch(str(value.get("formal_freeze_sha256"))) is None
        or not isinstance(value.get("run_id"), str)
        or _RUN_ID.fullmatch(value["run_id"]) is None
        or not isinstance(value.get("formal_namespace"), str)
        or not Path(value["formal_namespace"]).is_absolute()
        or _SHA256.fullmatch(str(value.get("runtime_identity_sha256"))) is None
        or _PROCESS_ID.fullmatch(str(value.get("source_process_id"))) is None
        or _PROCESS_ID.fullmatch(str(value.get("recovery_process_id"))) is None
        or value.get("source_process_id") == value.get("recovery_process_id")
        or any(
            value.get(key) is not True
            for key in (
                "fresh_adapter",
                "model_loaded",
                "optimizer_scheduler_rng_data_equal",
                "probe_update_completed",
            )
        )
    ):
        raise FullModelTrainingError("plan082_recovery_receipt_invalid")
    return json.loads(json.dumps(value))


def finalize_formal_run(
    *,
    freeze: Mapping[str, Any],
    controller: Plan082ContinuousTrainingController | None = None,
    controller_state: Mapping[str, Any] | None = None,
    recovery_receipt: Mapping[str, Any],
    artifact_store: Plan081ArtifactStore,
) -> dict[str, Any]:
    frozen = validate_formal_freeze(freeze)
    recovery = validate_recovery_receipt(recovery_receipt)
    if not isinstance(artifact_store, Plan081ArtifactStore):
        raise FullModelTrainingError("plan082_formal_artifact_store_required")
    if (controller is None) == (controller_state is None):
        raise FullModelTrainingError("plan082_formal_controller_state_invalid")
    if controller is not None:
        if not isinstance(controller, Plan082ContinuousTrainingController):
            raise FullModelTrainingError("plan082_formal_controller_required")
        state: Mapping[str, Any] = controller.state
        if controller.artifact_store is not artifact_store:
            raise FullModelTrainingError("plan082_formal_artifact_store_mismatch")
    elif isinstance(controller_state, Mapping):
        state = controller_state
    else:
        raise FullModelTrainingError("plan082_formal_controller_state_invalid")
    plan082_state = state.get("plan082")
    if not isinstance(plan082_state, Mapping):
        raise FullModelTrainingError("plan082_formal_state_not_frozen")
    try:
        process_identity = validate_process_identity(
            plan082_state.get("process_identity")
        )
    except FullModelTrainingError as error:
        raise FullModelTrainingError("plan082_formal_state_not_frozen") from error
    if (
        state.get("schema") != CONTROLLER_SCHEMA
        or state.get("status") != "completed"
        or state.get("evidence_kind") != "torch_real_direct_original_parameters"
        or plan082_state.get("runtime_identity") != frozen["runtime_identity"]
        or plan082_state.get("formal_freeze_sha256") != frozen["freeze_content_sha256"]
        or state.get("route_contract_sha256") != frozen["route_contract_sha256"]
        or state.get("control_plan") != frozen["run_spec"]["control_plan"]
        or state.get("comparison_policy") != frozen["run_spec"]["comparison_policy"]
        or state.get("report_threshold") != frozen["run_spec"]["report_threshold"]
        or state.get("scope_history") != frozen_scope_history(frozen["run_spec"])
        or state.get("current_step")
        != frozen["run_spec"]["control_plan"]["maximum_updates"]
        or not isinstance(state.get("updates"), list)
        or len(state.get("updates", [])) != state.get("current_step")
        or not isinstance(state.get("observations"), list)
        or any(
            not isinstance(record, Mapping)
            for record in state.get("observations", [])
        )
        or [record.get("global_step") for record in state.get("observations", [])]
        != frozen["run_spec"]["control_plan"]["observation_steps"]
        or [
            record.get("global_step")
            for record in state.get("observations", [])
            if isinstance(record.get("checkpoint_id"), str)
        ]
        != frozen["run_spec"]["control_plan"]["checkpoint_steps"]
        or any(
            record.get("checkpoint_id") is not None
            and not isinstance(record.get("checkpoint_id"), str)
            for record in state.get("observations", [])
        )
        or not isinstance(state.get("base"), Mapping)
        or not isinstance(state.get("latest_checkpoint_id"), str)
        or recovery["checkpoint_id"]
        not in {record.get("checkpoint_id") for record in state.get("observations", [])}
        or not any(
            record.get("checkpoint_id") == recovery["checkpoint_id"]
            and record.get("global_step") == frozen["recovery_checkpoint_step"]
            for record in state.get("observations", [])
        )
        or not isinstance(plan082_state.get("recovery_proven_checkpoints"), Mapping)
        or plan082_state.get("recovery_proven_checkpoints", {}).get(
            recovery["checkpoint_id"]
        )
        != recovery["checkpoint_sha256"]
        or process_identity["instance_id"] != recovery["recovery_process_id"]
        or recovery["formal_freeze_sha256"] != frozen["freeze_content_sha256"]
        or recovery["run_id"] != frozen["run_id"]
        or recovery["formal_namespace"] != frozen["formal_namespace"]
        or recovery["runtime_identity_sha256"]
        != sha256_bytes(canonical_json_bytes(frozen["runtime_identity"]))
    ):
        raise FullModelTrainingError("plan082_formal_state_not_frozen")
    artifact_state = _validate_formal_artifacts(
        state=state,
        frozen=frozen,
        recovery=recovery,
        artifact_store=artifact_store,
    )
    selection = state["selection"]
    candidate = artifact_state["checkpoint_backed_best"]
    policy = ComparisonPolicy.from_value(frozen["run_spec"]["comparison_policy"])
    candidate_improved = (
        compare_values(
            candidate["comparison_value"],
            state["base"]["comparison_value"],
            policy,
        )
        == "improved"
    )
    terminal = (
        "TRAINING_IMPROVEMENT_FOUND" if candidate_improved else "VALID_NO_IMPROVEMENT"
    )
    return {
        "schema": RESULT_SCHEMA,
        "terminal": terminal,
        "run_id": frozen["run_id"],
        "freeze_content_sha256": frozen["freeze_content_sha256"],
        "base_snapshot_id": selection["base_incumbent_snapshot_id"],
        "training_best_snapshot_id": selection["training_best_snapshot_id"],
        "latest_snapshot_id": selection["latest_snapshot_id"],
        "research_candidate_snapshot_id": (
            candidate["snapshot_id"] if candidate_improved else None
        ),
        "research_candidate_checkpoint_id": (
            candidate["checkpoint_id"] if candidate_improved else None
        ),
        "research_candidate_checkpoint_sha256": (
            artifact_state["checkpoint_content_sha256"][candidate["checkpoint_id"]]
            if candidate_improved
            else None
        ),
        "checkpoint_backed_best_snapshot_id": candidate["snapshot_id"],
        "checkpoint_backed_best_checkpoint_id": candidate["checkpoint_id"],
        "latest_checkpoint_id": state["latest_checkpoint_id"],
        "retention": artifact_state["retention"],
        "recovery": recovery,
        "observation_count": len(state["observations"]),
        "claims": {
            "valid_clean_formal_run": True,
            "better_than_same_cohort_base": candidate_improved,
            "unseen_evidence": False,
            "product_go": False,
            "m3_c2_evidence": False,
        },
    }


def _validate_formal_artifacts(
    *,
    state: Mapping[str, Any],
    frozen: Mapping[str, Any],
    recovery: Mapping[str, Any],
    artifact_store: Plan081ArtifactStore,
) -> dict[str, Any]:
    if artifact_store.root.resolve() != Path(frozen["formal_namespace"]).resolve():
        raise FullModelTrainingError("plan082_formal_artifact_root_mismatch")
    base = state.get("base")
    if (
        not isinstance(base, Mapping)
        or set(base)
        != {"role", "model", "snapshot_id", "observation", "comparison_value"}
        or base.get("role") != "base_incumbent"
        or base.get("model")
        != {"repository": MODEL_REPOSITORY, "revision": MODEL_REVISION}
        or base.get("snapshot_id") != "exact-base-incumbent"
        or base.get("observation")
        != artifact_store.verify_observation("base-step-000000")
    ):
        raise FullModelTrainingError("plan082_formal_base_invalid")
    stored_base = artifact_store.read_observation("base-step-000000")
    if (
        stored_base.get("global_step") != 0
        or stored_base.get("scope") != frozen["run_spec"]["initial_scope"]
        or stored_base.get("comparison_value") != base.get("comparison_value")
        or stored_base.get("validation", {}).get("identity_sha256")
        != state.get("validation_identity_sha256")
        or stored_base.get("evidence")
        != {
            "kind": "torch_real_direct_original_parameters",
            "research_candidate_eligible": False,
            "real_quality_claim": True,
        }
    ):
        raise FullModelTrainingError("plan082_formal_base_invalid")

    observations = state["observations"]
    observation_fields = {
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
    checkpoint_steps = set(frozen["run_spec"]["control_plan"]["checkpoint_steps"])
    scopes = frozen_scope_history(frozen["run_spec"])
    for record in observations:
        step = record.get("global_step")
        generation = record.get("artifact_generation")
        if (
            not isinstance(step, int)
            or isinstance(step, bool)
            or not isinstance(generation, int)
            or isinstance(generation, bool)
            or generation < 0
        ):
            raise FullModelTrainingError("plan082_formal_observation_invalid")
        observation_id = f"observation-attempt-{generation:03d}-step-{step:06d}"
        snapshot_id = f"snapshot-attempt-{generation:03d}-step-{step:06d}"
        checkpoint_id = (
            f"checkpoint-attempt-{generation:03d}-step-{step:06d}"
            if step in checkpoint_steps
            else None
        )
        active_scope = max(
            (item for item in scopes if item["effective_before_update"] <= step),
            key=lambda item: item["effective_before_update"],
        )["scope"]
        if (
            set(record) != observation_fields
            or record.get("observation_id") != observation_id
            or record.get("snapshot_id") != snapshot_id
            or record.get("checkpoint_id") != checkpoint_id
            or record.get("scope") != active_scope
            or record.get("observation")
            != artifact_store.verify_observation(observation_id)
        ):
            raise FullModelTrainingError("plan082_formal_observation_invalid")
        stored = artifact_store.read_observation(observation_id)
        if (
            stored.get("global_step") != step
            or stored.get("scope") != record.get("scope")
            or stored.get("comparison_value") != record.get("comparison_value")
            or stored.get("comparisons") != record.get("comparisons")
            or stored.get("validation", {}).get("identity_sha256")
            != state.get("validation_identity_sha256")
            or stored.get("evidence")
            != {
                "kind": "torch_real_direct_original_parameters",
                "research_candidate_eligible": False,
                "real_quality_claim": True,
            }
        ):
            raise FullModelTrainingError("plan082_formal_observation_invalid")

    _validate_formal_completed_history(state=state, frozen=frozen)
    expected_selection = _selection_from_records(
        base=base,
        observations=observations,
        policy=ComparisonPolicy.from_value(frozen["run_spec"]["comparison_policy"]),
        profile=REAL_RUNTIME_PROFILE,
    )
    if state.get("selection") != expected_selection:
        raise FullModelTrainingError("plan082_formal_selection_invalid")
    checkpoint_observations = [
        record
        for record in observations
        if isinstance(record.get("checkpoint_id"), str)
    ]
    if not checkpoint_observations:
        raise FullModelTrainingError("plan082_formal_checkpoint_observation_missing")
    training_best = max(observations, key=lambda record: record["comparison_value"])
    checkpoint_backed_best = max(
        checkpoint_observations, key=lambda record: record["comparison_value"]
    )
    latest_checkpoint = checkpoint_observations[-1]["checkpoint_id"]
    if state.get("latest_checkpoint_id") != latest_checkpoint:
        raise FullModelTrainingError("plan082_formal_latest_checkpoint_invalid")
    expected_terminal_state = json.loads(json.dumps(state))
    expected_terminal_state["status"] = "running"
    try:
        terminal_checkpoint_state = artifact_store.read_checkpoint_controller_state(
            latest_checkpoint
        )
    except FullModelTrainingError as error:
        raise FullModelTrainingError(
            "plan082_formal_terminal_checkpoint_invalid"
        ) from error
    if terminal_checkpoint_state != expected_terminal_state:
        raise FullModelTrainingError("plan082_formal_terminal_state_mismatch")

    checkpoint_roles: dict[str, set[str]] = {}
    snapshot_roles: dict[str, set[str]] = {}
    observation_roles: dict[str, set[str]] = {
        "base-step-000000": {"base_observation"}
    }

    def add_role(target: dict[str, set[str]], artifact_id: Any, role: str) -> None:
        if isinstance(artifact_id, str):
            target.setdefault(artifact_id, set()).add(role)

    add_role(checkpoint_roles, latest_checkpoint, "latest_checkpoint")
    add_role(snapshot_roles, observations[-1]["snapshot_id"], "latest_snapshot")
    add_role(snapshot_roles, training_best["snapshot_id"], "training_best_snapshot")
    add_role(
        checkpoint_roles,
        next(
            (
                record["checkpoint_id"]
                for record in observations
                if record["snapshot_id"] == training_best["snapshot_id"]
            ),
            None,
        ),
        "training_best_checkpoint",
    )
    add_role(
        checkpoint_roles,
        checkpoint_backed_best["checkpoint_id"],
        "checkpoint_backed_best",
    )
    add_role(
        snapshot_roles,
        checkpoint_backed_best["snapshot_id"],
        "checkpoint_backed_best",
    )
    for turning in state.get("turning_points", []):
        if not isinstance(turning, Mapping):
            raise FullModelTrainingError("plan082_formal_retention_invalid")
        add_role(snapshot_roles, turning.get("snapshot_id"), "turning_point")
        add_role(checkpoint_roles, turning.get("checkpoint_id"), "turning_point")
    for checkpoint_id in state["plan082"]["recovery_proven_checkpoints"]:
        add_role(checkpoint_roles, checkpoint_id, "recovery_proven")
    for record in observations:
        roles = {"validation_observation"}
        if isinstance(record.get("checkpoint_id"), str):
            roles.add("checkpoint_observation")
        observation_roles[record["observation_id"]] = roles

    if set(artifact_store.verified_checkpoint_ids()) != set(checkpoint_roles):
        raise FullModelTrainingError("plan082_formal_retained_checkpoint_invalid")
    if set(artifact_store.verified_snapshot_ids()) != set(snapshot_roles):
        raise FullModelTrainingError("plan082_formal_retained_snapshot_invalid")
    if set(artifact_store.verified_observation_ids()) != set(observation_roles):
        raise FullModelTrainingError("plan082_formal_retained_observation_invalid")
    checkpoint_receipts = {
        artifact_id: artifact_store.verify_checkpoint(artifact_id)
        for artifact_id in sorted(checkpoint_roles)
    }
    snapshot_receipts = {
        artifact_id: artifact_store.verify_snapshot(artifact_id)
        for artifact_id in sorted(snapshot_roles)
    }
    observation_receipts = {
        artifact_id: artifact_store.verify_observation(artifact_id)
        for artifact_id in sorted(observation_roles)
    }
    if (
        checkpoint_receipts[recovery["checkpoint_id"]]["content_sha256"]
        != recovery["checkpoint_sha256"]
        or any(
            checkpoint_id not in checkpoint_receipts
            or checkpoint_receipts[checkpoint_id]["content_sha256"]
            != content_sha256
            for checkpoint_id, content_sha256 in state["plan082"][
                "recovery_proven_checkpoints"
            ].items()
        )
    ):
        raise FullModelTrainingError("plan082_formal_recovery_artifact_invalid")
    artifact_store.verify_retention_complete(latest_checkpoint)
    retention = {
        "observations": [
            {
                "artifact_id": artifact_id,
                "sha256": observation_receipts[artifact_id]["sha256"],
                "roles": sorted(observation_roles[artifact_id]),
            }
            for artifact_id in sorted(observation_roles)
        ],
        "checkpoints": [
            {
                "artifact_id": artifact_id,
                "content_sha256": checkpoint_receipts[artifact_id]["content_sha256"],
                "roles": sorted(checkpoint_roles[artifact_id]),
            }
            for artifact_id in sorted(checkpoint_roles)
        ],
        "snapshots": [
            {
                "artifact_id": artifact_id,
                "content_sha256": snapshot_receipts[artifact_id]["content_sha256"],
                "roles": sorted(snapshot_roles[artifact_id]),
            }
            for artifact_id in sorted(snapshot_roles)
        ],
    }
    return {
        "training_best": training_best,
        "checkpoint_backed_best": checkpoint_backed_best,
        "checkpoint_content_sha256": {
            key: value["content_sha256"] for key, value in checkpoint_receipts.items()
        },
        "retention": retention,
    }


def _validate_formal_completed_history(
    *, state: Mapping[str, Any], frozen: Mapping[str, Any]
) -> None:
    scopes = frozen_scope_history(frozen["run_spec"])
    observations = state.get("observations")
    if not isinstance(observations, list):
        raise FullModelTrainingError("plan082_formal_history_invalid")
    observations_by_step = {
        record.get("global_step"): record
        for record in observations
        if isinstance(record, Mapping)
    }
    expected_decisions = []
    for item in frozen["run_spec"]["scope_schedule"]:
        step = item["after_observation_step"]
        observation = observations_by_step.get(step)
        if not isinstance(observation, Mapping):
            raise FullModelTrainingError("plan082_formal_history_invalid")
        expected_decisions.append(
            {
                "decided_after_observation_id": observation.get("observation_id"),
                "before_update": step + 1,
                "scope": item["scope"],
            }
        )
    if (
        state.get("scope_decisions") != expected_decisions
        or state.get("current_scope") != scopes[-1]["scope"]
    ):
        raise FullModelTrainingError("plan082_formal_history_invalid")

    updates = state.get("updates")
    expected_update_fields = {
        "global_step",
        "training_split",
        "validation_candidates_consumed",
        "unseen_candidates_consumed",
        "training_identity_sha256",
        "training_candidate_count",
        "training_pair_count",
        "scope",
        "data_cursor",
        "parameter_change",
    }
    if not isinstance(updates, list):
        raise FullModelTrainingError("plan082_formal_history_invalid")
    for step, update in enumerate(updates, start=1):
        scope = max(
            (item for item in scopes if item["effective_before_update"] <= step),
            key=lambda item: item["effective_before_update"],
        )["scope"]
        change = update.get("parameter_change") if isinstance(update, Mapping) else None
        if (
            not isinstance(update, Mapping)
            or set(update) != expected_update_fields
            or update.get("global_step") != step
            or update.get("training_split") != "train"
            or update.get("validation_candidates_consumed") != 0
            or update.get("unseen_candidates_consumed") != 0
            or update.get("training_identity_sha256")
            != state.get("training_identity_sha256")
            or update.get("training_candidate_count")
            != frozen["data"]["train_candidate_count"]
            or update.get("training_pair_count")
            != frozen["data"]["train_pair_count"]
            or update.get("scope") != scope
            or not isinstance(update.get("data_cursor"), Mapping)
            or not isinstance(change, Mapping)
            or set(change)
            != {
                "method",
                "parameter_name",
                "parameter_elements",
                "maximum_absolute_change",
            }
            or change.get("method")
            != "torch.equal_selected_nonzero_gradient_parameter"
            or change.get("parameter_name") not in scope["parameter_names"]
            or not isinstance(change.get("parameter_elements"), int)
            or isinstance(change["parameter_elements"], bool)
            or change["parameter_elements"] <= 0
            or not isinstance(change.get("maximum_absolute_change"), (int, float))
            or isinstance(change["maximum_absolute_change"], bool)
            or not math.isfinite(float(change["maximum_absolute_change"]))
            or float(change["maximum_absolute_change"]) <= 0
        ):
            raise FullModelTrainingError("plan082_formal_history_invalid")

    expected_turning = _turning_points_from_records(
        observations,
        expansion_steps={item["before_update"] for item in expected_decisions},
        limit=frozen["run_spec"]["control_plan"]["turning_point_limit"],
    )
    if state.get("turning_points") != expected_turning:
        raise FullModelTrainingError("plan082_formal_history_invalid")


def _validate_formal_scope_bounds(
    runtime: Mapping[str, Any],
    run_spec: Mapping[str, Any],
    inventory: Mapping[str, Any],
) -> None:
    total = runtime["parameter_elements"]
    elements_by_name = {row["name"]: row["elements"] for row in inventory["parameters"]}
    scopes = [
        run_spec["initial_scope"],
        *[item["scope"] for item in run_spec["scope_schedule"]],
    ]
    for index, scope in enumerate(scopes):
        names = scope["parameter_names"]
        if (
            any(name not in elements_by_name for name in names)
            or sum(elements_by_name[name] for name in names)
            != scope["trainable_parameter_elements"]
            or scope["trainable_parameter_elements"] > total
            or (index == 0 and scope["trainable_parameter_elements"] >= total)
        ):
            raise FullModelTrainingError("plan082_formal_scope_bounds_invalid")


def _freeze_parameter_inventory(
    value: Any, runtime: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not {
        "parameter_tensors",
        "parameter_elements",
        "parameters",
        "inventory_sha256",
    } <= set(value):
        raise FullModelTrainingError("plan082_parameter_inventory_invalid")
    parameters = value.get("parameters")
    if not isinstance(parameters, list):
        raise FullModelTrainingError("plan082_parameter_inventory_invalid")
    rows: list[dict[str, Any]] = []
    for item in parameters:
        if (
            not isinstance(item, Mapping)
            or not {"name", "elements", "dtype"} <= set(item)
            or not isinstance(item.get("name"), str)
            or not item["name"]
            or not isinstance(item.get("elements"), int)
            or isinstance(item["elements"], bool)
            or item["elements"] <= 0
            or not isinstance(item.get("dtype"), str)
            or not item["dtype"]
        ):
            raise FullModelTrainingError("plan082_parameter_inventory_invalid")
        rows.append(
            {
                "name": item["name"],
                "elements": item["elements"],
                "dtype": item["dtype"],
            }
        )
    frozen = {
        "parameter_tensors": len(rows),
        "parameter_elements": sum(row["elements"] for row in rows),
        "parameters": rows,
        "inventory_sha256": sha256_bytes(canonical_json_bytes(rows)),
    }
    return _validate_frozen_parameter_inventory(frozen, runtime)


def _validate_frozen_parameter_inventory(
    value: Any, runtime: Mapping[str, Any]
) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "parameter_tensors",
            "parameter_elements",
            "parameters",
            "inventory_sha256",
        }
        or not isinstance(value.get("parameters"), list)
    ):
        raise FullModelTrainingError("plan082_parameter_inventory_invalid")
    rows = value["parameters"]
    if (
        any(
            not isinstance(row, Mapping)
            or set(row) != {"name", "elements", "dtype"}
            or not isinstance(row.get("name"), str)
            or not row["name"]
            or not isinstance(row.get("elements"), int)
            or isinstance(row["elements"], bool)
            or row["elements"] <= 0
            or not isinstance(row.get("dtype"), str)
            or not row["dtype"]
            for row in rows
        )
        or len({row["name"] for row in rows}) != len(rows)
        or value.get("parameter_tensors") != len(rows)
        or value.get("parameter_elements") != sum(row["elements"] for row in rows)
        or value.get("inventory_sha256") != sha256_bytes(canonical_json_bytes(rows))
        or value["parameter_tensors"] != runtime["parameter_tensors"]
        or value["parameter_elements"] != runtime["parameter_elements"]
        or value["inventory_sha256"] != runtime["parameter_inventory_sha256"]
    ):
        raise FullModelTrainingError("plan082_parameter_inventory_invalid")
    return json.loads(json.dumps(value))


def _validate_source_receipt(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "schema",
            "commit",
            "archive_bytes",
            "archive_sha256",
            "source_content_sha256",
            "file_count",
            "directory_count",
        }
        or value.get("schema") != SOURCE_BUNDLE_SCHEMA
        or not isinstance(value.get("commit"), str)
        or _GIT_OID.fullmatch(value["commit"]) is None
        or not isinstance(value.get("archive_bytes"), int)
        or isinstance(value["archive_bytes"], bool)
        or value["archive_bytes"] <= 0
        or _SHA256.fullmatch(str(value.get("archive_sha256"))) is None
        or _SHA256.fullmatch(str(value.get("source_content_sha256"))) is None
        or any(
            not isinstance(value.get(key), int)
            or isinstance(value[key], bool)
            or value[key] <= 0
            for key in ("file_count", "directory_count")
        )
    ):
        raise FullModelTrainingError("plan082_source_receipt_invalid")
    return dict(value)


def _validate_data_receipt(value: Any) -> None:
    required = {
        "schema",
        "status",
        "bundle_manifest_sha256",
        "content_sha256",
        "data_export_sha256",
        "file_count",
        "train_candidate_count",
        "train_pair_count",
        "validation_candidate_count",
        "validation_pair_count",
        "commissioning_candidate_count",
        "commissioning_pair_count",
        "unseen_test_rows",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != required
        or value.get("status") != "verified"
        or value.get("unseen_test_rows") != 0
        or any(
            _SHA256.fullmatch(str(value.get(key))) is None
            for key in (
                "bundle_manifest_sha256",
                "content_sha256",
                "data_export_sha256",
            )
        )
    ):
        raise FullModelTrainingError("plan082_data_receipt_invalid")


def _validate_retention(value: Any) -> dict[str, Any]:
    expected = {
        "observations": "all_small_records",
        "snapshots": [
            "training_best",
            "latest",
            "turning_points",
            "best_checkpoint_observation",
        ],
        "checkpoints": [
            "latest",
            "best_checkpoint_observation",
            "turning_points",
            "recovery_proven",
        ],
    }
    if value != expected:
        raise FullModelTrainingError("plan082_retention_invalid")
    return json.loads(json.dumps(expected))
