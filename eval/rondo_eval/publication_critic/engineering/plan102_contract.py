"""Strict loader for the Plan 102 five-dimension cloud-seam contract."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any

from ..identity import sha256_file
from .cloud_budget_proxy import CloudBudgetIdentity


SCHEMA = "rondo-publication-critic-plan102-engineering-contract-v1"
CONTRACT_RELATIVE_PATH = Path(
    "eval/locks/publication-critic-plan102-engineering-contract-v1.json"
)
CLOUD_DESCRIPTOR = "eval/locks/publication-critic-plan102-cloud-descriptor-v1.json"
PROXY_KEY_ENV = "RONDO_PLAN102_DEEPSEEK_PROXY_KEY"

_MAX_JSON_BYTES = 256 * 1024
_MAX_PACKET_BYTES = 4 * 1024
_CASE_ID = re.compile(r"synthetic-[a-z0-9][a-z0-9-]{0,79}-v[1-9][0-9]*\Z")

_QUALIFICATION = {
    "packet_schema": {"name": "rondo-publication-packet", "revision": "v1"},
    "rubric": {"name": "rondo-publication-qualification", "revision": "v1"},
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
            "name": "rondo-publication-cloud-five-dimension-template",
            "revision": "v1",
        },
        "decision_projection": {
            "name": "rondo-cloud-json-five-dimension-decisions",
            "revision": "v1",
        },
        "pass_rule": "discrete_non_compensating_conjunction",
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
_FORBIDDEN_SCORING_FIELDS = {
    "scalar_projection",
    "domain",
    "threshold",
}

CLOUD_BUDGET_IDENTITY = CloudBudgetIdentity(
    schema="rondo-publication-critic-plan102-cloud-budget-v1",
    attempt_reservation_rmb=Decimal("1"),
    unknown_charge_rmb=Decimal("0.1"),
    downstream_key_prefix="rondo-plan102-",
    thread_name="rondo-plan102-cloud-budget-proxy",
    max_cap_rmb=Decimal("10"),
)


class Plan102ContractError(RuntimeError):
    """Stable body-free Plan 102 contract validation error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Plan102BudgetContract:
    judge_rmb: Decimal
    producer_usd: Decimal
    judge_missing_usage_rmb: Decimal
    judge_reservation_rmb: Decimal
    thinking_off_completion_token_max: int


@dataclass(frozen=True)
class Plan102ProducerContract:
    model_alias: str
    reasoning_effort: str
    run_timeout_seconds: int
    max_runs: int
    run_cap_usd: Decimal
    max_input_tokens: int
    max_output_tokens: int


@dataclass(frozen=True)
class Plan102DirectCase:
    case_id: str
    packet: Mapping[str, Any]


@dataclass(frozen=True)
class Plan102BackendContract:
    descriptor: str
    descriptor_path: Path
    descriptor_sha256: str
    descriptor_document: Mapping[str, Any]
    service_descriptor: Mapping[str, Any]
    client_call_timeout_ms: int
    client_startup_timeout_ms: int


@dataclass(frozen=True)
class Plan102Contract:
    schema: str
    purpose: str
    product_default: str
    quality_evaluation: str
    qualification: str
    backend: Plan102BackendContract
    budgets: Plan102BudgetContract
    producer: Plan102ProducerContract
    cloud_budget_identity: CloudBudgetIdentity
    direct_cases: tuple[Plan102DirectCase, ...]
    contract_path: Path
    contract_sha256: str


def load_plan102_contract(repo_root: Path) -> Plan102Contract:
    """Load and bind the tracked Plan 102 contract and five-dimension descriptor."""

    root = Path(repo_root).resolve()
    contract_path = root / CONTRACT_RELATIVE_PATH
    value = _load_json(contract_path, "contract")
    root_value = _exact_mapping(
        value,
        {
            "schema",
            "purpose",
            "product_default",
            "quality_evaluation",
            "qualification",
            "backend",
            "budgets",
            "producer",
            "direct_cases",
        },
        "contract_fields_invalid",
    )
    if (
        root_value["schema"] != SCHEMA
        or root_value["purpose"] != "five_dimension_cloud_seam_engineering"
        or root_value["product_default"] != "off"
        or root_value["quality_evaluation"] != "not_in_scope"
        or root_value["qualification"] != "not_in_scope"
    ):
        raise Plan102ContractError("contract_identity_invalid")
    return Plan102Contract(
        schema=SCHEMA,
        purpose="five_dimension_cloud_seam_engineering",
        product_default="off",
        quality_evaluation="not_in_scope",
        qualification="not_in_scope",
        backend=_validate_backend(root, root_value["backend"]),
        budgets=_validate_budgets(root_value["budgets"]),
        producer=_validate_producer(root_value["producer"]),
        cloud_budget_identity=CLOUD_BUDGET_IDENTITY,
        direct_cases=_validate_cases(root_value["direct_cases"]),
        contract_path=contract_path,
        contract_sha256=sha256_file(contract_path),
    )


def _validate_backend(root: Path, value: Any) -> Plan102BackendContract:
    backend = _exact_mapping(
        value,
        {"descriptor", "client_call_timeout_ms", "client_startup_timeout_ms"},
        "backend_fields_invalid",
    )
    if backend["descriptor"] != CLOUD_DESCRIPTOR:
        raise Plan102ContractError("descriptor_path_invalid")
    descriptor_path = root / CLOUD_DESCRIPTOR
    descriptor = _load_json(descriptor_path, "cloud_descriptor")
    service_descriptor = _validate_descriptor(descriptor)
    call_timeout = _positive_int(backend["client_call_timeout_ms"], "call_timeout_invalid")
    startup_timeout = _positive_int(
        backend["client_startup_timeout_ms"], "startup_timeout_invalid"
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
        "descriptor_limits_fields_invalid",
    )
    for field in limits:
        _positive_int(limits[field], f"descriptor_{field}_invalid")
    if call_timeout <= limits["job_timeout_ms"]:
        raise Plan102ContractError("call_timeout_not_above_job_budget")
    return Plan102BackendContract(
        descriptor=CLOUD_DESCRIPTOR,
        descriptor_path=descriptor_path,
        descriptor_sha256=sha256_file(descriptor_path),
        descriptor_document=deepcopy(dict(descriptor)),
        service_descriptor=deepcopy(dict(service_descriptor)),
        client_call_timeout_ms=call_timeout,
        client_startup_timeout_ms=startup_timeout,
    )


def _validate_descriptor(value: Any) -> Mapping[str, Any]:
    descriptor = _exact_mapping(
        value,
        {"backend_protocol", "provider", "service_descriptor"},
        "cloud_descriptor_fields_invalid",
    )
    if descriptor["backend_protocol"] != "rondo-publication-critic-cloud-v1":
        raise Plan102ContractError("cloud_descriptor_runtime_identity_invalid")
    provider = _exact_mapping(
        descriptor["provider"], set(_CLOUD_PROVIDER), "cloud_provider_fields_invalid"
    )
    if dict(provider) != _CLOUD_PROVIDER:
        raise Plan102ContractError("cloud_provider_identity_invalid")
    service = descriptor["service_descriptor"]
    service_value = _exact_mapping(
        service, {"identity", "limits"}, "service_descriptor_fields_invalid"
    )
    identity = _exact_mapping(
        service_value["identity"],
        {"protocol", "implementation", "qualification", "model", "scoring"},
        "service_identity_fields_invalid",
    )
    if dict(identity) != _CLOUD_IDENTITY:
        raise Plan102ContractError("service_identity_invalid")
    scoring = identity["scoring"]
    if not isinstance(scoring, Mapping) or set(scoring) & _FORBIDDEN_SCORING_FIELDS:
        raise Plan102ContractError("five_dimension_scoring_carries_threshold")
    return service_value


def _validate_budgets(value: Any) -> Plan102BudgetContract:
    budgets = _exact_mapping(
        value,
        {
            "judge_rmb",
            "producer_usd",
            "judge_missing_usage_rmb",
            "judge_reservation_rmb",
            "thinking_off_completion_token_max",
        },
        "budgets_fields_invalid",
    )
    judge = _decimal(budgets["judge_rmb"], "judge_budget_invalid")
    producer = _decimal(budgets["producer_usd"], "producer_budget_invalid")
    missing = _decimal(
        budgets["judge_missing_usage_rmb"], "judge_missing_usage_invalid"
    )
    reservation = _decimal(
        budgets["judge_reservation_rmb"], "judge_reservation_invalid"
    )
    thinking_max = budgets["thinking_off_completion_token_max"]
    if (
        judge != Decimal("10")
        or producer != Decimal("50")
        or missing != Decimal("0.1")
        or reservation != Decimal("1")
        or thinking_max != 512
    ):
        raise Plan102ContractError("budget_identity_invalid")
    if (
        CLOUD_BUDGET_IDENTITY.max_cap_rmb != judge
        or CLOUD_BUDGET_IDENTITY.unknown_charge_rmb != missing
        or CLOUD_BUDGET_IDENTITY.attempt_reservation_rmb != reservation
    ):
        raise Plan102ContractError("budget_identity_proxy_mismatch")
    return Plan102BudgetContract(judge, producer, missing, reservation, thinking_max)


def _validate_producer(value: Any) -> Plan102ProducerContract:
    producer = _exact_mapping(
        value,
        {
            "model_alias",
            "reasoning_effort",
            "run_timeout_seconds",
            "max_runs",
            "run_cap_usd",
            "usage_envelope",
        },
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
    max_runs = _positive_int(producer["max_runs"], "producer_max_runs_invalid")
    run_cap = _decimal(producer["run_cap_usd"], "producer_run_cap_invalid")
    max_input = _positive_int(
        envelope["max_input_tokens"], "producer_max_input_tokens_invalid"
    )
    max_output = _positive_int(
        envelope["max_output_tokens"], "producer_max_output_tokens_invalid"
    )
    if (
        producer["model_alias"] != "terra"
        or producer["reasoning_effort"] != "low"
        or run_timeout != 600
        or max_runs != 6
        or run_cap != Decimal("15")
        or max_input != 32000
        or max_output != 2000
    ):
        raise Plan102ContractError("producer_identity_invalid")
    return Plan102ProducerContract(
        "terra", "low", run_timeout, max_runs, run_cap, max_input, max_output
    )


def _validate_cases(value: Any) -> tuple[Plan102DirectCase, ...]:
    if not isinstance(value, list) or not 2 <= len(value) <= 6:
        raise Plan102ContractError("direct_case_count_invalid")
    cases: list[Plan102DirectCase] = []
    identifiers: set[str] = set()
    for raw_case in value:
        case = _exact_mapping(
            raw_case, {"case_id", "packet"}, "direct_case_fields_invalid"
        )
        if "expected_engineering_branch" in raw_case:
            raise Plan102ContractError("direct_case_must_not_expect_quality")
        case_id = case["case_id"]
        if (
            not isinstance(case_id, str)
            or _CASE_ID.fullmatch(case_id) is None
            or case_id in identifiers
        ):
            raise Plan102ContractError("direct_case_id_invalid")
        packet = _validate_packet(case["packet"])
        identifiers.add(case_id)
        cases.append(Plan102DirectCase(case_id, deepcopy(dict(packet))))
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
        raise Plan102ContractError("qualification_identity_invalid")
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
        raise Plan102ContractError("packet_identity_invalid")
    try:
        size = len(json.dumps(dict(packet), separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise Plan102ContractError("packet_encoding_invalid") from exc
    if size > _MAX_PACKET_BYTES:
        raise Plan102ContractError("packet_size_invalid")
    return packet


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise Plan102ContractError(f"{label}_missing_or_unsafe")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Plan102ContractError(f"{label}_unreadable") from exc
    if not 0 < len(raw) <= _MAX_JSON_BYTES:
        raise Plan102ContractError(f"{label}_size_invalid")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise Plan102ContractError(f"{label}_duplicate_key")
            result[key] = item
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except Plan102ContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Plan102ContractError(f"{label}_json_invalid") from exc
    if not isinstance(value, Mapping):
        raise Plan102ContractError(f"{label}_json_invalid")
    return value


def _exact_mapping(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise Plan102ContractError(code)
    return value


def _positive_int(value: Any, code: str) -> int:
    if type(value) is not int or not 0 < value <= 600_000:
        raise Plan102ContractError(code)
    return value


def _decimal(value: Any, code: str) -> Decimal:
    if not isinstance(value, str):
        raise Plan102ContractError(code)
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise Plan102ContractError(code) from exc
    if not number.is_finite() or number <= 0:
        raise Plan102ContractError(code)
    return number


def _bounded_text(value: Any, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value.encode("utf-8")) <= maximum
        and "\x00" not in value
    )


__all__ = [
    "CLOUD_BUDGET_IDENTITY",
    "CLOUD_DESCRIPTOR",
    "CONTRACT_RELATIVE_PATH",
    "PROXY_KEY_ENV",
    "SCHEMA",
    "Plan102BackendContract",
    "Plan102BudgetContract",
    "Plan102Contract",
    "Plan102ContractError",
    "Plan102DirectCase",
    "Plan102ProducerContract",
    "load_plan102_contract",
]
