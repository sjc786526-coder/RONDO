"""Fail-closed Standard/Lite E_final parsing for static approval consumers."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


STATIC_SCHEMA_VERSION = 1
STATIC_INSTRUCTIONS = (
    "Judge only from the supplied policy and evidence. Do not call tools or request "
    "additional evidence. Return one object matching output_schema."
)
STATIC_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "outcome": {"type": "string", "enum": ["allow", "deny"]},
        "rationale": {"type": "string"},
        "risk_tags": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 16,
            "uniqueItems": True,
        },
    },
    "required": ["outcome", "rationale", "risk_tags"],
}


class EvidenceError(ValueError):
    """Raised when E_final cannot be mapped to one unambiguous static payload."""


@dataclass(frozen=True)
class PolicyIdentity:
    schema_version: int
    request_shape: str
    sha256: str | None
    status: str
    reason: str | None = None

    @property
    def aggregatable(self) -> bool:
        return self.status == "known" and self.sha256 is not None


@dataclass(frozen=True)
class StaticApprovalPayload:
    policy_identity: PolicyIdentity
    canonical_bytes: bytes
    logical_payload: dict[str, Any]


def policy_identity(e_final: Mapping[str, Any]) -> PolicyIdentity:
    try:
        shape, policy, _ = _extract(e_final)
    except EvidenceError as exc:
        return PolicyIdentity(STATIC_SCHEMA_VERSION, "unknown", None, "unknown", str(exc))
    digest = hashlib.sha256(policy.encode("utf-8")).hexdigest()
    return PolicyIdentity(STATIC_SCHEMA_VERSION, shape, digest, "known")


def build_static_payload(e_final: Mapping[str, Any]) -> StaticApprovalPayload:
    shape, policy, task_input = _extract(e_final)
    identity = PolicyIdentity(
        STATIC_SCHEMA_VERSION,
        shape,
        hashlib.sha256(policy.encode("utf-8")).hexdigest(),
        "known",
    )
    cleaned_input = [_strip_transport_metadata(item) for item in task_input]
    logical = {
        "schema_version": STATIC_SCHEMA_VERSION,
        "instructions": STATIC_INSTRUCTIONS,
        "guardian_policy": policy,
        "input": cleaned_input,
        "output_schema": copy.deepcopy(STATIC_DECISION_SCHEMA),
    }
    try:
        canonical = json.dumps(
            logical,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise EvidenceError("E_final contains a value that cannot be canonicalized") from exc
    return StaticApprovalPayload(identity, canonical, logical)


def validate_static_decision(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceError("static decision must be an object")
    if set(value) != {"outcome", "rationale", "risk_tags"}:
        raise EvidenceError("static decision fields do not match schema v1")
    if not isinstance(value["outcome"], str) or value["outcome"] not in {"allow", "deny"}:
        raise EvidenceError("static decision outcome is invalid")
    if not isinstance(value["rationale"], str):
        raise EvidenceError("static decision rationale must be a string")
    tags = value["risk_tags"]
    if (
        not isinstance(tags, list)
        or len(tags) > 16
        or any(not isinstance(tag, str) or not tag for tag in tags)
        or len(tags) != len(set(tags))
    ):
        raise EvidenceError("static decision risk_tags are invalid")
    return {"outcome": value["outcome"], "rationale": value["rationale"], "risk_tags": tags}


def _extract(e_final: Mapping[str, Any]) -> tuple[str, str, list[Any]]:
    if not isinstance(e_final, Mapping):
        raise EvidenceError("E_final must be a JSON object")
    raw_input = e_final.get("input")
    if not isinstance(raw_input, list):
        raise EvidenceError("E_final input must be an array")
    instructions = e_final.get("instructions")
    has_standard_policy = isinstance(instructions, str) and bool(instructions)
    marker_indexes = [
        index
        for index, item in enumerate(raw_input)
        if isinstance(item, Mapping) and item.get("type") == "additional_tools"
    ]
    has_lite_prefix = marker_indexes == [0] and _is_additional_tools(raw_input[0])
    if has_standard_policy and has_lite_prefix:
        raise EvidenceError("E_final has conflicting Standard and Lite policy signals")
    if has_standard_policy:
        if marker_indexes:
            raise EvidenceError("Standard E_final contains Lite additional_tools")
        return "standard", instructions, copy.deepcopy(raw_input)
    if instructions not in (None, ""):
        raise EvidenceError("E_final instructions must be a string, null, or absent")
    if marker_indexes and not has_lite_prefix:
        raise EvidenceError("Lite additional_tools is malformed, misplaced, or repeated")
    if not has_lite_prefix or len(raw_input) < 2:
        raise EvidenceError("E_final has no unambiguous policy")
    if e_final.get("tools") not in (None, [], {}):
        raise EvidenceError("Lite E_final unexpectedly has top-level tools")
    policy_item = raw_input[1]
    policy = _developer_text(policy_item)
    if policy is None or not policy:
        raise EvidenceError("Lite E_final policy developer message is invalid")
    task_input = raw_input[2:]
    return "responses_lite", policy, copy.deepcopy(task_input)


def _is_additional_tools(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and value.get("type") == "additional_tools"
        and value.get("role") == "developer"
        and isinstance(value.get("tools"), list)
    )


def _developer_text(value: Any) -> str | None:
    if not isinstance(value, Mapping) or value.get("role") != "developer":
        return None
    content = value.get("content")
    if not isinstance(content, list) or len(content) != 1:
        return None
    item = content[0]
    if not isinstance(item, Mapping) or item.get("type") != "input_text":
        return None
    text = item.get("text")
    return text if isinstance(text, str) else None


def _strip_transport_metadata(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_transport_metadata(item) for item in value]
    if not isinstance(value, Mapping):
        return copy.deepcopy(value)
    result: dict[Any, Any] = {}
    for key, item in value.items():
        if key in {"additional_tools", "encrypted_function_args"}:
            continue
        if key == "internal_chat_message_metadata_passthrough" and isinstance(item, Mapping):
            item = {
                nested_key: nested_value
                for nested_key, nested_value in item.items()
                if nested_key != "executed_tool_calls"
            }
        result[key] = _strip_transport_metadata(item)
    return result
