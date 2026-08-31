"""Run-freeze identity for Plan 101 commissioning and formal namespaces."""

from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from ..structured_diagnostic.cost import PRICE_CARD_SHA256, decimal_text
from ..structured_diagnostic.release import CANDIDATES_SHA256, MANIFEST_SHA256, PAIRS_SHA256
from .archive import RUN_ID

FREEZE_SCHEMA = "rondo-publication-critic-plan101-run-freeze@v1"
REQUESTED_MODEL = "deepseek-v4-flash"
CONDITIONS = ("thinking_off", "thinking_on")
ARMS = ("A", "B", "C")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class ComparisonFreezeError(ValueError):
    """A Plan 101 source or request identity is incomplete or drifted."""


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
    thinking_off_repeats: int,
    thinking_on_repeats: int,
    missing_usage_rmb: Decimal,
    commissioning_binding_sha256: str | None,
) -> dict[str, Any]:
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
            "max_output_tokens": 8192,
            "response_format": "json_object",
            "stream": False,
            "max_attempts": 2,
            "request_timeout_ms": 120_000,
            "retry_backoff_ms": 1_000,
        },
        "matrix": {
            "conditions": list(CONDITIONS),
            "arm_order": list(ARMS),
            "thinking_off_repeats": thinking_off_repeats,
            "thinking_on_repeats": thinking_on_repeats,
            "candidate_order": "release_physical_jsonl_line_order",
            "same_packet_per_candidate": True,
            "provider_visible_difference": (
                "thinking_switch_and_output_instruction_and_exact_output_schema_only"
            ),
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
        "budget": {
            "currency": "RMB",
            "hard_limit": "20",
            "missing_usage_rmb": decimal_text(missing_usage_rmb),
            "price_card_sha256": PRICE_CARD_SHA256,
        },
        "commissioning_binding_sha256": commissioning_binding_sha256,
    }
    return validate_freeze(value)


def repeats_for(freeze: Mapping[str, Any], condition: str) -> int:
    matrix = freeze["matrix"]
    if condition == "thinking_off":
        return int(matrix["thinking_off_repeats"])
    if condition == "thinking_on":
        return int(matrix["thinking_on_repeats"])
    raise ComparisonFreezeError("unknown_condition")


def expected_observation_count(
    freeze: Mapping[str, Any],
    *,
    item_count: int,
    off_repeats: int | None = None,
    on_repeats: int | None = None,
) -> int:
    matrix = freeze["matrix"]
    off = int(matrix["thinking_off_repeats"] if off_repeats is None else off_repeats)
    on = int(matrix["thinking_on_repeats"] if on_repeats is None else on_repeats)
    return 3 * item_count * (off + on)


def validate_freeze(value: Any) -> dict[str, Any]:
    expected = {
        "schema",
        "mode",
        "run_id",
        "source",
        "provider",
        "request",
        "matrix",
        "release",
        "budget",
        "commissioning_binding_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ComparisonFreezeError("freeze_fields_invalid")
    mode = value.get("mode")
    match = RUN_ID.fullmatch(str(value.get("run_id")))
    if (
        value.get("schema") != FREEZE_SCHEMA
        or mode not in {"commissioning", "formal"}
        or match is None
        or match.group(1) != mode
    ):
        raise ComparisonFreezeError("freeze_identity_invalid")
    source = _exact(
        value.get("source"),
        {
            "git_commit",
            "tracked_source_clean",
            "diagnostic_contract_sha256",
            "diagnostic_executable_sha256",
            "descriptor_sha256",
        },
        "freeze_source_invalid",
    )
    if (
        source.get("tracked_source_clean") is not True
        or not isinstance(source.get("git_commit"), str)
        or _GIT_COMMIT.fullmatch(source["git_commit"]) is None
    ):
        raise ComparisonFreezeError("freeze_source_invalid")
    for name in (
        "diagnostic_contract_sha256",
        "diagnostic_executable_sha256",
        "descriptor_sha256",
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
        dict(_exact(value.get("provider"), set(expected_provider), "freeze_provider_invalid"))
        != expected_provider
    ):
        raise ComparisonFreezeError("freeze_provider_invalid")
    expected_request = {
        "temperature": 0.0,
        "max_output_tokens": 8192,
        "response_format": "json_object",
        "stream": False,
        "max_attempts": 2,
        "request_timeout_ms": 120_000,
        "retry_backoff_ms": 1_000,
    }
    request = _exact(value.get("request"), set(expected_request), "freeze_request_invalid")
    if dict(request) != expected_request or type(request["temperature"]) not in {
        int,
        float,
    }:
        raise ComparisonFreezeError("freeze_request_invalid")
    matrix = _exact(
        value.get("matrix"),
        {
            "conditions",
            "arm_order",
            "thinking_off_repeats",
            "thinking_on_repeats",
            "candidate_order",
            "same_packet_per_candidate",
            "provider_visible_difference",
        },
        "freeze_matrix_invalid",
    )
    off_repeats = matrix.get("thinking_off_repeats")
    on_repeats = matrix.get("thinking_on_repeats")
    shared_ok = (
        list(matrix.get("conditions") or ()) == list(CONDITIONS)
        and list(matrix.get("arm_order") or ()) == list(ARMS)
        and matrix.get("candidate_order") == "release_physical_jsonl_line_order"
        and matrix.get("same_packet_per_candidate") is True
        and matrix.get("provider_visible_difference")
        == "thinking_switch_and_output_instruction_and_exact_output_schema_only"
        and type(off_repeats) is int
        and type(on_repeats) is int
    )
    if mode == "commissioning":
        repeats_ok = off_repeats == 1 and on_repeats == 1
    else:
        repeats_ok = off_repeats == 3 and on_repeats == 3
    if not shared_ok or not repeats_ok:
        raise ComparisonFreezeError("freeze_matrix_invalid")
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
        dict(_exact(value.get("release"), set(expected_release), "freeze_release_invalid"))
        != expected_release
    ):
        raise ComparisonFreezeError("freeze_release_invalid")
    budget = _exact(
        value.get("budget"),
        {"currency", "hard_limit", "missing_usage_rmb", "price_card_sha256"},
        "freeze_budget_invalid",
    )
    if (
        budget.get("currency") != "RMB"
        or budget.get("hard_limit") != "20"
        or budget.get("price_card_sha256") != PRICE_CARD_SHA256
    ):
        raise ComparisonFreezeError("freeze_budget_invalid")
    try:
        missing = Decimal(str(budget.get("missing_usage_rmb")))
    except Exception as exc:
        raise ComparisonFreezeError("freeze_budget_invalid") from exc
    if not missing.is_finite() or missing <= 0:
        raise ComparisonFreezeError("freeze_budget_invalid")
    binding = value.get("commissioning_binding_sha256")
    if mode == "commissioning":
        if binding is not None:
            raise ComparisonFreezeError("freeze_binding_unexpected")
    else:
        _require_sha(binding, "freeze_binding_invalid")
    return dict(value)


def _exact(value: Any, expected: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ComparisonFreezeError(code)
    return value


def _require_sha(value: Any, code: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ComparisonFreezeError(code)
