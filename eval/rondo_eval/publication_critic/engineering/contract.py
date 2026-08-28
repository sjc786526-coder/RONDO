"""Strict loader for the bounded Plan 097 engineering contract."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any

from ..identity import canonical_json_bytes, sha256_file


SCHEMA = "rondo-publication-critic-plan097-engineering-contract-v1"
CONTRACT_RELATIVE_PATH = Path(
    "eval/locks/publication-critic-plan097-engineering-contract-v1.json"
)
LOCAL_DESCRIPTOR = "eval/locks/publication-critic-plan097-local-descriptor-v1.json"
CLOUD_DESCRIPTOR = "eval/locks/publication-critic-plan096-cloud-descriptor-v1.json"

_MAX_JSON_BYTES = 256 * 1024
_MAX_PACKET_BYTES = 4 * 1024
_CASE_ID = re.compile(r"synthetic-[a-z0-9][a-z0-9-]{0,79}-v[1-9][0-9]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

_CONCLUSION_BOUNDARY = {
    "cloud_quality": "not_qualified",
    "local_quality": "no_go_pending_replacement",
    "product_default": "off",
    "product_value": "not_evaluated",
    "production": "disabled",
}
_QUALIFICATION = {
    "packet_schema": {"name": "rondo-publication-packet", "revision": "v1"},
    "rubric": {"name": "rondo-publication-qualification", "revision": "v1"},
}
_LOCAL_IDENTITY = {
    "protocol": "rondo_publication_critic_v1",
    "implementation": {
        "name": "rondo-publication-critic-real-service",
        "revision": "plan097-v1",
    },
    "qualification": _QUALIFICATION,
    "model": {
        "model": {
            "name": "skywork-reward-v2-qwen3-1.7b",
            "revision": "e51ea3e08fb81326-base",
        },
        "tokenizer": {
            "name": "skywork-reward-v2-qwen3-1.7b-tokenizer",
            "revision": "e51ea3e08fb81326-plan066-export-v1",
        },
    },
    "scoring": {
        "definition": {
            "name": "skywork-reward-scalar-higher-better",
            "revision": "plan068-cuda-bf16-v1",
        },
        "domain": {"max": 1.0, "min": 0.0},
        "input_template": {
            "name": "rondo-publication-packet-render",
            "revision": (
                "v3-sha256-"
                "dc3209af0d284dfe4be57403873717ba5f2790e2257cd4a39a2376de5696044c"
            ),
        },
        "pass_rule": "score_greater_than_or_equal_to_threshold",
        "scalar_projection": {
            "name": "stable-sigmoid-logits-index-0",
            "revision": "v1",
        },
        "threshold": 0.9350569011196121,
    },
}
_CLOUD_IDENTITY = {
    "protocol": "rondo_publication_critic_v1",
    "implementation": {
        "name": "rondo-publication-critic-cloud-service",
        "revision": "v1",
    },
    "qualification": _QUALIFICATION,
    "model": {
        "model": {
            "name": "deepseek-v4-flash",
            "revision": "serving-revision-unverifiable",
        },
        "tokenizer": {
            "name": "provider-managed-tokenizer",
            "revision": "unverifiable",
        },
    },
    "scoring": {
        "definition": {
            "name": "rondo-cloud-reference-deepseek-v4-flash",
            "revision": "v1",
        },
        "input_template": {
            "name": "rondo-publication-cloud-template",
            "revision": "v1",
        },
        "scalar_projection": {
            "name": "rondo-cloud-json-quality-scalar",
            "revision": "v1",
        },
        "domain": {"min": 0.0, "max": 1.0},
        "threshold": 0.5,
        "pass_rule": "score_greater_than_or_equal_to_threshold",
    },
}
_CLOUD_PROVIDER = {
    "api": "chat_completions",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "model": "deepseek-v4-flash",
    "served_model": "echoed",
    "response_format": "json_object",
    "max_output_tokens": 8192,
    "temperature": 0.0,
    "request_timeout_ms": 60000,
    "max_attempts": 2,
    "retry_backoff_ms": 1000,
}


class EngineeringContractError(RuntimeError):
    """Stable body-free Plan 097 contract validation error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class BackendContract:
    name: str
    descriptor: str
    descriptor_path: Path
    descriptor_sha256: str
    descriptor_document: Mapping[str, Any]
    service_descriptor: Mapping[str, Any]
    client_call_timeout_ms: int
    client_startup_timeout_ms: int


@dataclass(frozen=True)
class BudgetContract:
    cloud_scorer_rmb: Decimal
    producer_rmb: Decimal
    rmb_per_usd: Decimal
    total_rmb: Decimal


@dataclass(frozen=True)
class ProducerContract:
    model_alias: str
    reasoning_effort: str
    run_timeout_seconds: int
    max_input_tokens: int
    max_output_tokens: int


@dataclass(frozen=True)
class CommissioningCase:
    case_id: str
    expected_engineering_branch: str
    packet: Mapping[str, Any]


@dataclass(frozen=True)
class EngineeringContract:
    schema: str
    conclusion_boundary: Mapping[str, str]
    backends: Mapping[str, BackendContract]
    budgets: BudgetContract
    producer: ProducerContract
    commissioning_cases: tuple[CommissioningCase, ...]
    contract_path: Path
    contract_sha256: str


def load_contract(repo_root: Path) -> EngineeringContract:
    """Load and bind the tracked Plan 097 contract and both descriptors."""

    root = Path(repo_root).resolve()
    contract_path = root / CONTRACT_RELATIVE_PATH
    value = _load_json(contract_path, "contract")
    root_value = _exact_mapping(
        value,
        {
            "schema",
            "conclusion_boundary",
            "backends",
            "budgets",
            "producer",
            "commissioning_cases",
        },
        "contract_fields_invalid",
    )
    if root_value["schema"] != SCHEMA:
        raise EngineeringContractError("contract_schema_invalid")
    conclusion = _exact_mapping(
        root_value["conclusion_boundary"],
        set(_CONCLUSION_BOUNDARY),
        "conclusion_boundary_fields_invalid",
    )
    if dict(conclusion) != _CONCLUSION_BOUNDARY:
        raise EngineeringContractError("conclusion_boundary_invalid")

    backend_values = _exact_mapping(
        root_value["backends"], {"local", "cloud"}, "backends_fields_invalid"
    )
    backends = {
        name: _validate_backend(root, name, backend_values[name])
        for name in ("local", "cloud")
    }
    budgets = _validate_budgets(root_value["budgets"])
    producer = _validate_producer(root_value["producer"])
    cases = _validate_cases(root_value["commissioning_cases"])
    return EngineeringContract(
        schema=SCHEMA,
        conclusion_boundary=dict(conclusion),
        backends=backends,
        budgets=budgets,
        producer=producer,
        commissioning_cases=cases,
        contract_path=contract_path,
        contract_sha256=sha256_file(contract_path),
    )


def _validate_backend(root: Path, name: str, value: Any) -> BackendContract:
    backend = _exact_mapping(
        value,
        {"descriptor", "client_call_timeout_ms", "client_startup_timeout_ms"},
        f"{name}_backend_fields_invalid",
    )
    expected_relative = LOCAL_DESCRIPTOR if name == "local" else CLOUD_DESCRIPTOR
    if backend["descriptor"] != expected_relative:
        raise EngineeringContractError(f"{name}_descriptor_path_invalid")
    descriptor_path = root / expected_relative
    descriptor = _load_json(descriptor_path, f"{name}_descriptor")
    service_descriptor = _validate_descriptor(name, descriptor)
    call_timeout = _positive_int(
        backend["client_call_timeout_ms"], f"{name}_call_timeout_invalid"
    )
    startup_timeout = _positive_int(
        backend["client_startup_timeout_ms"], f"{name}_startup_timeout_invalid"
    )
    limits = _exact_mapping(
        service_descriptor["limits"],
        {
            "request_bytes",
            "response_bytes",
            "max_concurrency",
            "queue_capacity",
            "job_timeout_ms",
            "io_timeout_ms",
        },
        f"{name}_descriptor_limits_fields_invalid",
    )
    for field in limits:
        _positive_int(limits[field], f"{name}_descriptor_{field}_invalid")
    if call_timeout <= limits["job_timeout_ms"]:
        raise EngineeringContractError(f"{name}_call_timeout_not_above_job_budget")
    return BackendContract(
        name=name,
        descriptor=expected_relative,
        descriptor_path=descriptor_path,
        descriptor_sha256=sha256_file(descriptor_path),
        descriptor_document=deepcopy(dict(descriptor)),
        service_descriptor=deepcopy(dict(service_descriptor)),
        client_call_timeout_ms=call_timeout,
        client_startup_timeout_ms=startup_timeout,
    )


def _validate_descriptor(name: str, value: Any) -> Mapping[str, Any]:
    if name == "local":
        descriptor = _exact_mapping(
            value,
            {
                "worker_protocol",
                "object_id",
                "deployment_artifact_sha256",
                "qualification_freeze_sha256",
                "service_descriptor",
            },
            "local_descriptor_fields_invalid",
        )
        if (
            descriptor["worker_protocol"]
            != "rondo-publication-critic-worker-v1"
            or descriptor["object_id"] != "skywork-base-e51ea3e0-plan097"
            or descriptor["deployment_artifact_sha256"]
            != "117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9"
            or descriptor["qualification_freeze_sha256"]
            != "02fbb85d9eb3c76a6761fd86b495d46a01720e13ced4fbac0b74e3cd8e831616"
        ):
            raise EngineeringContractError("local_descriptor_runtime_identity_invalid")
        for field in ("deployment_artifact_sha256", "qualification_freeze_sha256"):
            if not isinstance(descriptor[field], str) or _SHA256.fullmatch(
                descriptor[field]
            ) is None:
                raise EngineeringContractError("local_descriptor_runtime_identity_invalid")
        service = descriptor["service_descriptor"]
        expected_identity = _LOCAL_IDENTITY
    else:
        descriptor = _exact_mapping(
            value,
            {"backend_protocol", "provider", "service_descriptor"},
            "cloud_descriptor_fields_invalid",
        )
        if descriptor["backend_protocol"] != "rondo-publication-critic-cloud-v1":
            raise EngineeringContractError("cloud_descriptor_runtime_identity_invalid")
        provider = _exact_mapping(
            descriptor["provider"], set(_CLOUD_PROVIDER), "cloud_provider_fields_invalid"
        )
        if dict(provider) != _CLOUD_PROVIDER:
            raise EngineeringContractError("cloud_provider_identity_invalid")
        service = descriptor["service_descriptor"]
        expected_identity = _CLOUD_IDENTITY
    service_value = _exact_mapping(
        service, {"identity", "limits"}, f"{name}_service_descriptor_fields_invalid"
    )
    identity = _exact_mapping(
        service_value["identity"],
        {"protocol", "implementation", "qualification", "model", "scoring"},
        f"{name}_service_identity_fields_invalid",
    )
    if dict(identity) != expected_identity:
        raise EngineeringContractError(f"{name}_service_identity_invalid")
    return service_value


def _validate_budgets(value: Any) -> BudgetContract:
    budgets = _exact_mapping(
        value,
        {"cloud_scorer_rmb", "producer_rmb", "rmb_per_usd", "total_rmb"},
        "budgets_fields_invalid",
    )
    cloud = _decimal(budgets["cloud_scorer_rmb"], "cloud_scorer_budget_invalid")
    producer = _decimal(budgets["producer_rmb"], "producer_budget_invalid")
    conversion = _decimal(budgets["rmb_per_usd"], "currency_conversion_invalid")
    total = _decimal(budgets["total_rmb"], "total_budget_invalid")
    if (
        cloud != Decimal("12")
        or producer != Decimal("18")
        or conversion != Decimal("7.5")
        or total != Decimal("30")
        or cloud + producer != total
    ):
        raise EngineeringContractError("budget_identity_invalid")
    return BudgetContract(cloud, producer, conversion, total)


def _validate_producer(value: Any) -> ProducerContract:
    producer = _exact_mapping(
        value,
        {"model_alias", "reasoning_effort", "run_timeout_seconds", "usage_envelope"},
        "producer_fields_invalid",
    )
    envelope = _exact_mapping(
        producer["usage_envelope"],
        {"max_input_tokens", "max_output_tokens"},
        "producer_usage_envelope_fields_invalid",
    )
    run_timeout = _positive_int(
        producer["run_timeout_seconds"], "producer_run_timeout_invalid"
    )
    max_input = _positive_int(
        envelope["max_input_tokens"], "producer_max_input_tokens_invalid"
    )
    max_output = _positive_int(
        envelope["max_output_tokens"], "producer_max_output_tokens_invalid"
    )
    if (
        producer["model_alias"] != "luna"
        or producer["reasoning_effort"] != "low"
        or run_timeout != 600
        or max_input != 96000
        or max_output != 16000
    ):
        raise EngineeringContractError("producer_identity_invalid")
    return ProducerContract("luna", "low", run_timeout, max_input, max_output)


def _validate_cases(value: Any) -> tuple[CommissioningCase, ...]:
    if not isinstance(value, list) or not 2 <= len(value) <= 4:
        raise EngineeringContractError("commissioning_case_count_invalid")
    cases: list[CommissioningCase] = []
    identifiers: set[str] = set()
    branches: set[str] = set()
    for raw_case in value:
        case = _exact_mapping(
            raw_case,
            {"case_id", "expected_engineering_branch", "packet"},
            "commissioning_case_fields_invalid",
        )
        case_id = case["case_id"]
        if (
            not isinstance(case_id, str)
            or _CASE_ID.fullmatch(case_id) is None
            or case_id in identifiers
        ):
            raise EngineeringContractError("commissioning_case_id_invalid")
        branch = case["expected_engineering_branch"]
        if branch not in {"pass", "rewrite"}:
            raise EngineeringContractError("commissioning_case_branch_invalid")
        packet = _validate_packet(case["packet"])
        identifiers.add(case_id)
        branches.add(branch)
        cases.append(CommissioningCase(case_id, branch, deepcopy(dict(packet))))
    if branches != {"pass", "rewrite"}:
        raise EngineeringContractError("commissioning_case_branches_incomplete")
    return tuple(cases)


def _validate_packet(value: Any) -> Mapping[str, Any]:
    packet = _exact_mapping(
        value,
        {
            "qualification",
            "actor_role",
            "target_kind",
            "local_scope",
            "candidate",
            "continuity",
            "evidence_v1",
        },
        "packet_fields_invalid",
    )
    qualification = _exact_mapping(
        packet["qualification"], {"packet_schema", "rubric"}, "qualification_fields_invalid"
    )
    if dict(qualification) != _QUALIFICATION:
        raise EngineeringContractError("qualification_identity_invalid")
    scope = _exact_mapping(packet["local_scope"], {"title"}, "local_scope_fields_invalid")
    candidate = _exact_mapping(
        packet["candidate"], {"summary", "handoff"}, "candidate_fields_invalid"
    )
    continuity = _exact_mapping(
        packet["continuity"], {"state"}, "continuity_fields_invalid"
    )
    evidence = _exact_mapping(
        packet["evidence_v1"],
        {"semantic_entailment", "candidate_window"},
        "evidence_fields_invalid",
    )
    if (
        packet["actor_role"] != "member"
        or packet["target_kind"] != "new_event"
        or not _bounded_text(scope["title"], 128)
        or not _bounded_text(candidate["summary"], 1024)
        or candidate["handoff"] is not None
        or continuity["state"] != "not_applicable"
        or evidence["semantic_entailment"] != "not_evaluated"
        or evidence["candidate_window"] != "not_frozen_before_commit"
    ):
        raise EngineeringContractError("packet_identity_invalid")
    try:
        size = len(canonical_json_bytes(dict(packet)))
    except (TypeError, ValueError) as exc:
        raise EngineeringContractError("packet_encoding_invalid") from exc
    if size > _MAX_PACKET_BYTES:
        raise EngineeringContractError("packet_size_invalid")
    return packet


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EngineeringContractError(f"{label}_missing_or_unsafe")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EngineeringContractError(f"{label}_unreadable") from exc
    if not 0 < len(raw) <= _MAX_JSON_BYTES:
        raise EngineeringContractError(f"{label}_size_invalid")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise EngineeringContractError(f"{label}_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except EngineeringContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EngineeringContractError(f"{label}_json_invalid") from exc
    if not isinstance(value, Mapping):
        raise EngineeringContractError(f"{label}_json_invalid")
    return value


def _exact_mapping(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise EngineeringContractError(code)
    return value


def _positive_int(value: Any, code: str) -> int:
    if type(value) is not int or not 0 < value <= 600_000:
        raise EngineeringContractError(code)
    return value


def _decimal(value: Any, code: str) -> Decimal:
    if not isinstance(value, str):
        raise EngineeringContractError(code)
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise EngineeringContractError(code) from exc
    if not number.is_finite() or number <= 0:
        raise EngineeringContractError(code)
    return number


def _bounded_text(value: Any, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value.encode("utf-8")) <= maximum
        and "\x00" not in value
    )
