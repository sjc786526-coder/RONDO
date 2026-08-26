"""Freeze and terminal semantics for a clean Plan 082 formal run."""

from __future__ import annotations

from collections.abc import Mapping
import json
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
from .plan082_adapter import MODEL_LOCK_SHA256
from .plan082_bundle import SOURCE_BUNDLE_SCHEMA, verify_data_bundle
from .plan082_controller import (
    CONTROLLER_SCHEMA,
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
) -> dict[str, Any]:
    frozen = validate_formal_freeze(freeze)
    recovery = validate_recovery_receipt(recovery_receipt)
    if (controller is None) == (controller_state is None):
        raise FullModelTrainingError("plan082_formal_controller_state_invalid")
    if controller is not None:
        if not isinstance(controller, Plan082ContinuousTrainingController):
            raise FullModelTrainingError("plan082_formal_controller_required")
        state: Mapping[str, Any] = controller.state
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
        or len(state.get("updates", [])) != state.get("current_step")
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
    selection = state["selection"]
    observations = state["observations"]
    training_best = max(observations, key=lambda record: record["comparison_value"])
    checkpoint_observations = [
        record
        for record in observations
        if isinstance(record.get("checkpoint_id"), str)
    ]
    if not checkpoint_observations:
        raise FullModelTrainingError("plan082_formal_checkpoint_observation_missing")
    candidate = max(
        checkpoint_observations,
        key=lambda record: record["comparison_value"],
    )
    policy = ComparisonPolicy.from_value(frozen["run_spec"]["comparison_policy"])
    controller_improved = (
        compare_values(
            training_best["comparison_value"],
            state["base"]["comparison_value"],
            policy,
        )
        == "improved"
    )
    candidate_improved = (
        compare_values(
            candidate["comparison_value"],
            state["base"]["comparison_value"],
            policy,
        )
        == "improved"
    )
    expected_control_candidate = (
        training_best["snapshot_id"] if controller_improved else None
    )
    if (
        selection.get("training_best_snapshot_id") != training_best["snapshot_id"]
        or selection.get("latest_snapshot_id") != observations[-1]["snapshot_id"]
        or selection.get("control_candidate_snapshot_id") != expected_control_candidate
    ):
        raise FullModelTrainingError("plan082_formal_selection_invalid")
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
        "latest_checkpoint_id": state["latest_checkpoint_id"],
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
