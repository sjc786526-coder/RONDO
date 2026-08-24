"""Strict Plan 066 recipe and receipt contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from typing import Any

from .contract import (
    FullModelTrainingError,
    RECIPE_SCHEMA,
    STAGES,
    resume_receipt_evidence_matches_coverage,
    start_receipt_evidence_matches_coverage,
    valid_checkpoint_receipt,
    valid_full_parameter_coverage,
    valid_stage_receipt,
    validate_recipe,
)
from .plan066_artifacts import CANDIDATE_SCHEMA


PLAN066_RECIPE_SCHEMA = "rondo-publication-critic-plan066-recipe-v1"


def validate_plan066_recipe(value: Any, *, require_frozen: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("plan066_recipe_not_object")
    extras = {"formal_data", "validation", "resume_probe", "unseen_test"}
    core = {key: item for key, item in value.items() if key not in extras}
    if set(value) != set(core) | extras or core.get("schema") != PLAN066_RECIPE_SCHEMA:
        raise FullModelTrainingError("plan066_recipe_contract_invalid")
    validate_recipe({**core, "schema": RECIPE_SCHEMA}, require_frozen=require_frozen)
    if value.get("formal_data") != {
        "binary_candidates": 128,
        "c2_boundary_pairs": 50,
        "c3_within_pass_pairs": 8,
        "one_full_pass_per_stage": True,
    }:
        raise FullModelTrainingError("plan066_recipe_data_invalid")
    if value.get("validation") != {
        "candidate_count": 55,
        "boundary_pairs": 19,
        "within_pass_pairs": 7,
        "after_each_stage": True,
        "gradient_access": False,
        "feeds_training_decisions": False,
        "threshold": 0.0,
    }:
        raise FullModelTrainingError("plan066_recipe_validation_invalid")
    if value.get("unseen_test") != {"run": False, "feeds_training_decisions": False}:
        raise FullModelTrainingError("plan066_recipe_unseen_invalid")
    if value.get("resume_probe") != {
        "data_role": "v8_commissioning_smoke",
        "binary_candidates": 6,
        "boundary_pairs": 1,
        "within_pass_pairs": 1,
        "updates": 1,
        "does_not_replace_formal_candidate": True,
    }:
        raise FullModelTrainingError("plan066_recipe_resume_probe_invalid")
    return json.loads(json.dumps(value))


def validate_plan066_start_receipt(value: Any, *, formal: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("plan066_start_receipt_invalid")
    expected_keys = {
        "schema", "status", "created_at", "process", "identity", "coverage",
        "stages", "checkpoint", "optimizer_pre_checkpoint", "global_step",
        "resume_required", "timing",
    }
    if formal:
        expected_keys |= {"candidates", "validation", "holdout"}
    schema = (
        "rondo-publication-critic-plan066-formal-start-v1"
        if formal
        else "rondo-publication-critic-plan066-commissioning-start-v1"
    )
    status = (
        "pending_new_process_resume"
        if formal
        else "commissioning_only_pending_new_process_resume"
    )
    components = (
        {
            "C1": {"binary": 128},
            "C2": {"binary": 128, "boundary": 50},
            "C3": {"binary": 128, "boundary": 50, "within_pass": 8},
        }
        if formal
        else {
            "C1": {"binary": 6},
            "C2": {"binary": 6, "boundary": 1},
            "C3": {"binary": 6, "boundary": 1, "within_pass": 1},
        }
    )
    if (
        set(value) != expected_keys
        or value.get("schema") != schema
        or value.get("status") != status
        or value.get("global_step") != 3
        or value.get("resume_required")
        != (
            {
                "stage": "C3", "updates": 1, "new_os_process": True,
                "data_role": "v8_commissioning_smoke",
                "does_not_replace_formal_candidate": True,
            }
            if formal
            else {"stage": "C3", "updates": 1, "new_os_process": True}
        )
        or not valid_full_parameter_coverage(value.get("coverage"))
        or not _valid_stages(value.get("stages"), components)
        or not start_receipt_evidence_matches_coverage(value)
        or not valid_checkpoint_receipt(value.get("checkpoint"), status="saved_manifest_built")
        or value["checkpoint"].get("process") != value.get("process")
        or not _finite_timing(value.get("timing"))
    ):
        raise FullModelTrainingError("plan066_start_receipt_invalid")
    if formal and (
        not _valid_candidates(value.get("candidates"), identity=value.get("identity"))
        or not _valid_validation(value.get("validation"))
        or value.get("holdout")
        != {
            "validation_gradient_access": False,
            "validation_feeds_training_decisions": False,
            "unseen_test_exported": False,
            "unseen_test_run": False,
        }
    ):
        raise FullModelTrainingError("plan066_formal_artifacts_invalid")
    return json.loads(json.dumps(value))


def validate_plan066_resume_receipt(value: Any, *, formal: bool) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("plan066_resume_receipt_invalid")
    expected = {
        "schema", "status", "created_at", "identity", "start_process",
        "resume_process", "new_os_process_confirmed", "restored_from_global_step",
        "continued_global_step", "continued_stage", "coverage",
        "restored_optimizer_state", "restored_optimizer_runtime", "checkpoint",
        "timing",
    }
    if formal:
        expected |= {
            "formal_start_receipt_sha256", "billing",
            "remote_resource_terminal_state", "qualification_conclusion",
            "continued_data",
        }
    schema = (
        "rondo-publication-critic-plan066-formal-pending-v1"
        if formal
        else "rondo-publication-critic-plan066-commissioning-resume-v1"
    )
    status = (
        "pending_billing_and_resource_cleanup"
        if formal
        else "commissioning_only_complete_not_formal_evidence"
    )
    stage = value.get("continued_stage")
    if (
        set(value) != expected
        or value.get("schema") != schema
        or value.get("status") != status
        or value.get("new_os_process_confirmed") is not True
        or value.get("restored_from_global_step") != 3
        or value.get("continued_global_step") != 4
        or not valid_full_parameter_coverage(value.get("coverage"))
        or not isinstance(stage, Mapping)
        or not valid_stage_receipt(
            stage,
            stage="C3",
            global_step=4,
            expected_components={"binary": 6, "boundary": 1, "within_pass": 1},
        )
        or not valid_checkpoint_receipt(value.get("checkpoint"), status="verified")
        or value["checkpoint"].get("process") != value.get("start_process")
        or not resume_receipt_evidence_matches_coverage(value)
        or not _finite_timing(value.get("timing"))
    ):
        raise FullModelTrainingError("plan066_resume_receipt_invalid")
    if formal and (
        not isinstance(value.get("formal_start_receipt_sha256"), str)
        or len(value["formal_start_receipt_sha256"]) != 64
        or value.get("billing") is not None
        or value.get("remote_resource_terminal_state") is not None
        or value.get("qualification_conclusion") is not None
        or not _valid_continued_data(
            value.get("continued_data"), identity=value.get("identity")
        )
    ):
        raise FullModelTrainingError("plan066_formal_pending_fields_invalid")
    return json.loads(json.dumps(value))


def _valid_stages(value: Any, components: Mapping[str, Mapping[str, int]]) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 3
        and all(
            valid_stage_receipt(
                item,
                stage=stage,
                global_step=index,
                expected_components=components[stage],
            )
            for index, (stage, item) in enumerate(zip(STAGES, value), start=1)
        )
    )


def _valid_continued_data(value: Any, *, identity: Any) -> bool:
    probe = identity.get("resume_probe") if isinstance(identity, Mapping) else None
    return (
        isinstance(value, Mapping)
        and set(value)
        == {
            "data_role", "binary_candidates", "boundary_pairs",
            "within_pass_pairs", "does_not_replace_formal_candidate",
            "membership_sha256",
        }
        and value.get("data_role") == "v8_commissioning_smoke"
        and value.get("binary_candidates") == 6
        and value.get("boundary_pairs") == 1
        and value.get("within_pass_pairs") == 1
        and value.get("does_not_replace_formal_candidate") is True
        and isinstance(probe, Mapping)
        and value.get("membership_sha256") == probe.get("membership_sha256")
        and isinstance(value.get("membership_sha256"), str)
        and len(value["membership_sha256"]) == 64
    )


def _valid_candidates(value: Any, *, identity: Any) -> bool:
    from .contract import canonical_json_bytes, sha256_bytes

    identity_sha256 = (
        sha256_bytes(canonical_json_bytes(identity))
        if isinstance(identity, Mapping)
        else None
    )
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 3
        and [item.get("stage") for item in value if isinstance(item, Mapping)] == list(STAGES)
        and all(
            isinstance(item, Mapping)
            and set(item)
            == {
                "schema", "status", "stage", "global_step",
                "candidate_manifest_sha256", "content_sha256", "identity_sha256",
                "bytes", "file_count", "save_seconds",
            }
            and item.get("schema") == CANDIDATE_SCHEMA
            and item.get("status") == "verified"
            and item.get("global_step") == index
            and item.get("identity_sha256") == identity_sha256
            and isinstance(item.get("bytes"), int)
            and item["bytes"] > 0
            and isinstance(item.get("file_count"), int)
            and item["file_count"] > 1
            and _sha256(item.get("candidate_manifest_sha256"))
            and _sha256(item.get("content_sha256"))
            and _finite_nonnegative(item.get("save_seconds"))
            for index, item in enumerate(value, start=1)
        )
    )


def _valid_validation(value: Any) -> bool:
    return (
        isinstance(value, Sequence)
        and not isinstance(value, (str, bytes, bytearray))
        and len(value) == 3
        and [item.get("stage") for item in value if isinstance(item, Mapping)] == list(STAGES)
        and all(_valid_validation_item(item) for item in value)
    )


def _valid_validation_item(value: Any) -> bool:
    expected = {
        "schema", "stage", "gradient_access", "feeds_training_decisions",
        "candidate_count", "token_count", "elapsed_seconds", "binary", "pairs",
        "optimizer_state_unchanged", "scheduler_state_unchanged",
        "all_parameter_grads_none",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("schema") != "rondo-publication-critic-plan066-validation-v1"
        or value.get("stage") not in STAGES
        or value.get("gradient_access") is not False
        or value.get("feeds_training_decisions") is not False
        or value.get("candidate_count") != 55
        or not isinstance(value.get("token_count"), int)
        or value["token_count"] <= 0
        or not _finite_nonnegative(value.get("elapsed_seconds"))
        or value.get("optimizer_state_unchanged") is not True
        or value.get("scheduler_state_unchanged") is not True
        or value.get("all_parameter_grads_none") is not True
    ):
        return False
    binary = value.get("binary")
    pairs = value.get("pairs")
    if (
        not isinstance(binary, Mapping)
        or set(binary)
        != {"count", "mean_loss", "zero_threshold_correct", "zero_threshold_accuracy"}
        or binary.get("count") != 55
        or not _finite_nonnegative(binary.get("mean_loss"))
        or not isinstance(binary.get("zero_threshold_correct"), int)
        or not 0 <= binary["zero_threshold_correct"] <= 55
        or not _finite_nonnegative(binary.get("zero_threshold_accuracy"))
        or float(binary["zero_threshold_accuracy"]) > 1
        or not isinstance(pairs, Mapping)
        or set(pairs) != {"boundary", "within_pass"}
    ):
        return False
    for kind, count in (("boundary", 19), ("within_pass", 7)):
        item = pairs[kind]
        if (
            not isinstance(item, Mapping)
            or set(item) != {"count", "mean_loss", "preferred_wins", "ties"}
            or item.get("count") != count
            or not _finite_nonnegative(item.get("mean_loss"))
            or not isinstance(item.get("preferred_wins"), int)
            or not isinstance(item.get("ties"), int)
            or item["preferred_wins"] < 0
            or item["ties"] < 0
            or item["preferred_wins"] + item["ties"] > count
        ):
            return False
    return True


def _finite_timing(value: Any) -> bool:
    if not isinstance(value, Mapping) or not value:
        return False
    def visit(item: Any) -> bool:
        if isinstance(item, Mapping):
            return all(visit(child) for child in item.values())
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            return math.isfinite(float(item)) and float(item) >= 0
        if isinstance(item, bool) or isinstance(item, str) or item is None:
            return True
        return False
    return visit(value)


def _finite_nonnegative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
