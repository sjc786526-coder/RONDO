"""Fail-closed Standard/Lite E_final parsing for static approval consumers."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping


STATIC_SCHEMA_VERSION = 1
StaticApprovalConsumer = Literal["luna-static", "sol-static", "local-static"]
STATIC_APPROVAL_CONSUMERS: tuple[StaticApprovalConsumer, ...] = (
    "luna-static",
    "sol-static",
    "local-static",
)
STATIC_INSTRUCTIONS = (
    "Judge only from the supplied policy and evidence. Do not call tools or request "
    "additional evidence. Return one object matching output_schema."
)
STATIC_DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "outcome": {"type": "string", "enum": ["allow", "deny"]},
        "rationale": {"type": "string", "minLength": 1},
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
    payload = StaticApprovalPayload(identity, canonical, logical)
    validate_static_payload(payload)
    return payload


def validate_static_payload(payload: StaticApprovalPayload) -> None:
    """Validate the final provider-neutral payload at a consumer boundary."""

    if not isinstance(payload, StaticApprovalPayload):
        raise EvidenceError("static approval payload has an invalid type")
    logical = payload.logical_payload
    if not isinstance(logical, Mapping) or set(logical) != {
        "schema_version",
        "instructions",
        "guardian_policy",
        "input",
        "output_schema",
    }:
        raise EvidenceError("static approval payload fields do not match schema v1")
    if logical["schema_version"] != STATIC_SCHEMA_VERSION or isinstance(
        logical["schema_version"], bool
    ):
        raise EvidenceError("static approval payload schema version is invalid")
    if logical["instructions"] != STATIC_INSTRUCTIONS:
        raise EvidenceError("static approval instructions differ from schema v1")
    policy = logical["guardian_policy"]
    if not isinstance(policy, str) or not policy:
        raise EvidenceError("static approval guardian policy is invalid")
    if not isinstance(logical["input"], list):
        raise EvidenceError("static approval input must be an array")
    if logical["output_schema"] != STATIC_DECISION_SCHEMA:
        raise EvidenceError("static approval output schema differs from schema v1")
    _reject_private_transport(logical)

    identity = payload.policy_identity
    expected_sha256 = hashlib.sha256(policy.encode("utf-8")).hexdigest()
    if (
        not isinstance(identity, PolicyIdentity)
        or identity.schema_version != STATIC_SCHEMA_VERSION
        or identity.request_shape not in {"standard", "responses_lite"}
        or identity.status != "known"
        or identity.reason is not None
        or identity.sha256 != expected_sha256
    ):
        raise EvidenceError("static approval policy identity is invalid")
    try:
        canonical = json.dumps(
            logical,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise EvidenceError("static approval payload cannot be canonicalized") from exc
    if not isinstance(payload.canonical_bytes, bytes) or payload.canonical_bytes != canonical:
        raise EvidenceError("static approval canonical bytes do not match the logical payload")


def static_payload_bytes_for_consumer(
    payload: StaticApprovalPayload,
    consumer: StaticApprovalConsumer,
) -> bytes:
    """Project identical canonical bytes to one named static consumer."""

    if consumer not in STATIC_APPROVAL_CONSUMERS:
        raise EvidenceError("static approval consumer is invalid")
    validate_static_payload(payload)
    return payload.canonical_bytes


def validate_static_decision(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvidenceError("static decision must be an object")
    if set(value) != {"outcome", "rationale", "risk_tags"}:
        raise EvidenceError("static decision fields do not match schema v1")
    if not isinstance(value["outcome"], str) or value["outcome"] not in {"allow", "deny"}:
        raise EvidenceError("static decision outcome is invalid")
    if not isinstance(value["rationale"], str) or not value["rationale"]:
        raise EvidenceError("static decision rationale must be a non-empty string")
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
    if (
        not isinstance(value, Mapping)
        or value.get("type") != "message"
        or value.get("role") != "developer"
    ):
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


def _reject_private_transport(value: Any) -> None:
    if isinstance(value, list):
        for item in value:
            _reject_private_transport(item)
        return
    if not isinstance(value, Mapping):
        return
    if value.get("type") == "additional_tools":
        raise EvidenceError("static approval payload contains additional_tools")
    if "tools" in value and (
        value.get("type") != "tool_search_output" or not isinstance(value["tools"], list)
    ):
        raise EvidenceError("static approval payload contains a tool authorization field")
    if "encrypted_function_args" in value:
        raise EvidenceError("static approval payload contains encrypted_function_args")
    metadata = value.get("internal_chat_message_metadata_passthrough")
    if isinstance(metadata, Mapping) and "executed_tool_calls" in metadata:
        raise EvidenceError("static approval payload contains executed_tool_calls")
    for item in value.values():
        _reject_private_transport(item)
