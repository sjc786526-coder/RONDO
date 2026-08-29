"""Run-freeze identity for Plan 100 commissioning and formal namespaces."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from .archive import RUN_ID
from .cost import (
    PRICE_CARD_SHA256,
    DiagnosticCostError,
    validate_task_budget_snapshot,
)
from .release import CANDIDATES_SHA256, MANIFEST_SHA256, PAIRS_SHA256

FREEZE_SCHEMA = "rondo-publication-critic-plan100-run-freeze@v1"
REQUESTED_MODEL = "deepseek-v4-flash"
CONTRACT_SCHEMA = "rondo-publication-critic-plan100-diagnostic-contract@v1"
COMMISSIONING_RESULT_SCHEMA = "rondo-publication-critic-plan100-commissioning-result@v1"
COMMISSIONING_BINDING_SCHEMA = (
    "rondo-publication-critic-plan100-commissioning-binding@v1"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class DiagnosticFreezeError(ValueError):
    """A commissioning/formal source or request identity is incomplete or drifted."""


def freeze_sha256(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(value)))


def build_freeze(
    *,
    mode: str,
    run_id: str,
    git_commit: str,
    diagnostic_contract_sha256: str,
    executable_sha256: str,
    descriptor_sha256: str,
    environment_lock_sha256: str,
    token_recounter_sha256: str,
    commissioning_binding_sha256: str | None,
) -> dict[str, Any]:
    """Build the small identity that B1 may refresh before its clean formal freeze."""

    value = {
        "schema": FREEZE_SCHEMA,
        "mode": mode,
        "run_id": run_id,
        "source": {
            "git_commit": git_commit,
            "tracked_source_clean": True,
            "diagnostic_contract_sha256": diagnostic_contract_sha256,
            "diagnostic_executable_sha256": executable_sha256,
            "descriptor_sha256": descriptor_sha256,
            "environment_lock_sha256": environment_lock_sha256,
            "token_recounter_sha256": token_recounter_sha256,
        },
        "provider": {
            "provider_identity": "deepseek-official",
            "api_shape": "chat-completions-json-object-v1",
            "requested_model": REQUESTED_MODEL,
            "serving_revision": "provider-managed-unverifiable",
            "response_model_policy": "required-exact-echo-reject-drift-v1",
        },
        "request": {
            "temperature": 0.0,
            "max_output_tokens": 256,
            "response_format": "json_object",
            "stream": False,
            "max_attempts": 2,
            "request_timeout_ms": 60_000,
            "retry_backoff_ms": 1_000,
        },
        "release": {
            "revision": "publication-critic-v10",
            "manifest_sha256": MANIFEST_SHA256,
            "validation_candidates_sha256": CANDIDATES_SHA256,
            "validation_pairs_sha256": PAIRS_SHA256,
            "candidate_rows": 27,
            "pair_rows": 12,
            "candidate_order": "physical_jsonl_line_order",
        },
        "comparison": {
            "arm_order": ["A", "B", "C"],
            "candidate_order": "release_physical_jsonl_line_order",
            "same_packet_per_candidate": True,
            "provider_visible_difference": "output_instruction_and_exact_output_schema_only",
        },
        "price_card_sha256": PRICE_CARD_SHA256,
        "commissioning_binding_sha256": commissioning_binding_sha256,
    }
    return validate_freeze(value)


def validate_freeze(value: Any) -> dict[str, Any]:
    expected = {
        "schema",
        "mode",
        "run_id",
        "source",
        "provider",
        "request",
        "release",
        "comparison",
        "price_card_sha256",
        "commissioning_binding_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise DiagnosticFreezeError("freeze_fields_invalid")
    mode = value.get("mode")
    match = RUN_ID.fullmatch(str(value.get("run_id")))
    if (
        value.get("schema") != FREEZE_SCHEMA
        or mode not in {"commissioning", "formal"}
        or match is None
        or match.group(1) != mode
    ):
        raise DiagnosticFreezeError("freeze_identity_invalid")
    source = _exact(
        value.get("source"),
        {
            "git_commit",
            "tracked_source_clean",
            "diagnostic_contract_sha256",
            "diagnostic_executable_sha256",
            "descriptor_sha256",
            "environment_lock_sha256",
            "token_recounter_sha256",
        },
        "freeze_source_invalid",
    )
    if (
        source.get("tracked_source_clean") is not True
        or not isinstance(source.get("git_commit"), str)
        or _GIT_COMMIT.fullmatch(source["git_commit"]) is None
    ):
        raise DiagnosticFreezeError("freeze_source_invalid")
    for name in (
        "diagnostic_contract_sha256",
        "diagnostic_executable_sha256",
        "descriptor_sha256",
        "environment_lock_sha256",
        "token_recounter_sha256",
    ):
        _require_sha(source.get(name), "freeze_source_invalid")
    expected_provider = {
        "provider_identity": "deepseek-official",
        "api_shape": "chat-completions-json-object-v1",
        "requested_model": REQUESTED_MODEL,
        "serving_revision": "provider-managed-unverifiable",
        "response_model_policy": "required-exact-echo-reject-drift-v1",
    }
    if (
        dict(
            _exact(
                value.get("provider"), set(expected_provider), "freeze_provider_invalid"
            )
        )
        != expected_provider
    ):
        raise DiagnosticFreezeError("freeze_provider_invalid")
    expected_request = {
        "temperature": 0.0,
        "max_output_tokens": 256,
        "response_format": "json_object",
        "stream": False,
        "max_attempts": 2,
        "request_timeout_ms": 60_000,
        "retry_backoff_ms": 1_000,
    }
    request = _exact(
        value.get("request"), set(expected_request), "freeze_request_invalid"
    )
    if dict(request) != expected_request or type(request["temperature"]) not in {
        int,
        float,
    }:
        raise DiagnosticFreezeError("freeze_request_invalid")
    expected_release = {
        "revision": "publication-critic-v10",
        "manifest_sha256": MANIFEST_SHA256,
        "validation_candidates_sha256": CANDIDATES_SHA256,
        "validation_pairs_sha256": PAIRS_SHA256,
        "candidate_rows": 27,
        "pair_rows": 12,
        "candidate_order": "physical_jsonl_line_order",
    }
    if (
        dict(
            _exact(
                value.get("release"), set(expected_release), "freeze_release_invalid"
            )
        )
        != expected_release
    ):
        raise DiagnosticFreezeError("freeze_release_invalid")
    expected_comparison = {
        "arm_order": ["A", "B", "C"],
        "candidate_order": "release_physical_jsonl_line_order",
        "same_packet_per_candidate": True,
        "provider_visible_difference": "output_instruction_and_exact_output_schema_only",
    }
    if (
        dict(
            _exact(
                value.get("comparison"),
                set(expected_comparison),
                "freeze_comparison_invalid",
            )
        )
        != expected_comparison
    ):
        raise DiagnosticFreezeError("freeze_comparison_invalid")
    if value.get("price_card_sha256") != PRICE_CARD_SHA256:
        raise DiagnosticFreezeError("freeze_price_card_invalid")
    commissioning = value.get("commissioning_binding_sha256")
    if mode == "formal":
        _require_sha(commissioning, "freeze_commissioning_binding_invalid")
    elif commissioning is not None:
        raise DiagnosticFreezeError("freeze_commissioning_binding_invalid")
    return {
        "schema": FREEZE_SCHEMA,
        "mode": mode,
        "run_id": value["run_id"],
        "source": dict(source),
        "provider": dict(value["provider"]),
        "request": dict(request),
        "release": dict(value["release"]),
        "comparison": dict(value["comparison"]),
        "price_card_sha256": PRICE_CARD_SHA256,
        "commissioning_binding_sha256": commissioning,
    }


def validate_commissioning_binding(
    value: Any, formal_freeze_value: Mapping[str, Any]
) -> dict[str, Any]:
    """Require a successful, calibrated 9/9 B1 bound to the final B2 identity."""

    binding = _exact(
        value,
        {
            "schema",
            "run_id",
            "commissioning_freeze",
            "freeze_sha256",
            "commissioning_result",
            "result_sha256",
        },
        "commissioning_binding_invalid",
    )
    if binding.get("schema") != COMMISSIONING_BINDING_SCHEMA:
        raise DiagnosticFreezeError("commissioning_binding_invalid")
    commissioning_freeze = validate_freeze(binding.get("commissioning_freeze"))
    formal_freeze = validate_freeze(formal_freeze_value)
    if (
        commissioning_freeze["mode"] != "commissioning"
        or formal_freeze["mode"] != "formal"
        or binding.get("run_id") != commissioning_freeze["run_id"]
        or binding.get("freeze_sha256") != freeze_sha256(commissioning_freeze)
    ):
        raise DiagnosticFreezeError("commissioning_binding_identity_invalid")
    result = _exact(
        binding.get("commissioning_result"),
        {
            "schema",
            "freeze_sha256",
            "complete",
            "terminal_observation_count",
            "expected_terminal_observation_count",
            "successful_terminal_observation_count",
            "parse_failure_count",
            "stopped",
            "calibration",
            "task_budget",
        },
        "commissioning_result_invalid",
    )
    calibration = _exact(
        result.get("calibration"),
        {
            "required",
            "usage_present_attempt_count",
            "calibrated_attempt_count",
            "mismatch_count",
            "unavailable_count",
            "token_recounter_sha256",
            "passed",
        },
        "commissioning_calibration_invalid",
    )
    usage_present = calibration.get("usage_present_attempt_count")
    calibrated = calibration.get("calibrated_attempt_count")
    if (
        result.get("schema") != COMMISSIONING_RESULT_SCHEMA
        or result.get("freeze_sha256") != binding.get("freeze_sha256")
        or result.get("complete") is not True
        or result.get("terminal_observation_count") != 9
        or result.get("expected_terminal_observation_count") != 9
        or result.get("successful_terminal_observation_count") != 9
        or result.get("parse_failure_count") != 0
        or result.get("stopped") is not None
        or calibration.get("required") is not True
        or type(usage_present) is not int
        or usage_present < 1
        or calibrated != usage_present
        or calibration.get("mismatch_count") != 0
        or calibration.get("unavailable_count") != 0
        or calibration.get("token_recounter_sha256")
        != commissioning_freeze["source"]["token_recounter_sha256"]
        or calibration.get("passed") is not True
        or binding.get("result_sha256")
        != sha256_bytes(canonical_json_bytes(dict(result)))
    ):
        raise DiagnosticFreezeError("commissioning_result_invalid")
    try:
        validate_task_budget_snapshot(result.get("task_budget"))
    except DiagnosticCostError as exc:
        raise DiagnosticFreezeError("commissioning_budget_invalid") from exc
    for name in (
        "source",
        "provider",
        "request",
        "release",
        "comparison",
        "price_card_sha256",
    ):
        if formal_freeze[name] != commissioning_freeze[name]:
            raise DiagnosticFreezeError("formal_identity_not_commissioned")
    return {
        "schema": COMMISSIONING_BINDING_SCHEMA,
        "run_id": binding["run_id"],
        "commissioning_freeze": commissioning_freeze,
        "freeze_sha256": binding["freeze_sha256"],
        "commissioning_result": dict(result),
        "result_sha256": binding["result_sha256"],
    }


def _exact(value: Any, fields: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise DiagnosticFreezeError(code)
    return value


def _require_sha(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise DiagnosticFreezeError(code)
    return value


__all__ = [
    "COMMISSIONING_BINDING_SCHEMA",
    "COMMISSIONING_RESULT_SCHEMA",
    "CONTRACT_SCHEMA",
    "FREEZE_SCHEMA",
    "REQUESTED_MODEL",
    "DiagnosticFreezeError",
    "build_freeze",
    "freeze_sha256",
    "validate_commissioning_binding",
    "validate_freeze",
]
