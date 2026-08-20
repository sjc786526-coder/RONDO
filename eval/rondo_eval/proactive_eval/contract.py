"""Strict loader for the frozen Plan 049 machine contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_UP
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_RELPATH = "eval/locks/multi-proactive-delegation-v1.json"


class ContractError(ValueError):
    """Raised before any campaign state or external side effect is created."""


@dataclass(frozen=True)
class CampaignContract:
    lock: dict[str, Any]
    taskset: dict[str, Any]
    catalog: dict[str, Any]
    policy: str
    lock_sha256: str

    @property
    def lock_id(self) -> str:
        return str(self.lock["lock_id"])

    @property
    def policy_sha256(self) -> str:
        return str(self.lock["policy"]["sha256"])

    @property
    def taskset_sha256(self) -> str:
        return str(self.lock["taskset"]["sha256"])


def load_contract(repo_root: Path = REPO_ROOT) -> CampaignContract:
    root = Path(repo_root).resolve()
    lock_path = root / LOCK_RELPATH
    lock_raw, lock = _read_json(lock_path, "campaign lock")
    _exact_keys(
        lock,
        {
            "schema_version",
            "lock_id",
            "status",
            "plan",
            "phase_a",
            "runtime",
            "taskset",
            "policy",
            "provider",
            "price_snapshot",
            "execution",
            "recovery",
            "budget",
            "artifacts",
            "activation",
        },
        "campaign lock",
    )
    if (
        lock.get("schema_version") != 1
        or lock.get("lock_id") != "multi-proactive-delegation-v1"
        or lock.get("status") != "frozen"
        or lock.get("plan") != "049"
    ):
        raise ContractError("Plan 049 lock identity is invalid")

    taskset_meta = _object(lock, "taskset")
    _exact_keys(
        taskset_meta,
        {"path", "sha256", "catalog_path", "catalog_sha256"},
        "taskset identity",
    )
    taskset_path = _tracked_file(root, taskset_meta.get("path"), "taskset")
    taskset_raw, taskset = _read_json(taskset_path, "taskset")
    _require_digest(taskset_raw, taskset_meta.get("sha256"), "taskset")
    _exact_keys(
        taskset,
        {
            "schema_version",
            "taskset_id",
            "catalog",
            "catalog_sha256",
            "pilot_pairs",
            "formal_pairs",
        },
        "taskset",
    )
    catalog_path = _tracked_file(root, taskset_meta.get("catalog_path"), "catalog")
    catalog_raw, catalog = _read_json(catalog_path, "catalog")
    _require_digest(catalog_raw, taskset_meta.get("catalog_sha256"), "catalog")
    if (
        taskset.get("schema_version") != 1
        or taskset.get("taskset_id") != "multi-proactive-delegation-v1"
        or taskset.get("catalog") != taskset_meta.get("catalog_path")
        or taskset.get("catalog_sha256") != taskset_meta.get("catalog_sha256")
    ):
        raise ContractError("Plan 049 taskset identity is invalid")

    policy_meta = _object(lock, "policy")
    _exact_keys(policy_meta, {"path", "sha256"}, "policy identity")
    policy_path = _tracked_file(root, policy_meta.get("path"), "policy")
    try:
        policy_raw = policy_path.read_bytes()
        policy = policy_raw.decode("utf-8").rstrip("\n")
    except (OSError, UnicodeError) as exc:
        raise ContractError("Plan 049 policy is unreadable") from exc
    _require_digest(policy_raw, policy_meta.get("sha256"), "policy")
    if not policy or len(policy_raw) > 16 * 1024:
        raise ContractError("Plan 049 policy is invalid")

    _validate_runtime(root, lock)
    _validate_semantics(lock, taskset, catalog)
    artifacts_meta = _object(lock, "artifacts")
    fixture_path = _tracked_file(
        root, artifacts_meta.get("replay_fixture"), "replay fixture"
    )
    fixture_raw, _fixture = _read_json(fixture_path, "replay fixture")
    _require_digest(
        fixture_raw, artifacts_meta.get("replay_fixture_sha256"), "replay fixture"
    )
    return CampaignContract(
        lock=lock,
        taskset=taskset,
        catalog=catalog,
        policy=policy,
        lock_sha256=hashlib.sha256(lock_raw).hexdigest(),
    )


def _validate_runtime(root: Path, lock: dict[str, Any]) -> None:
    runtime = _object(lock, "runtime")
    _exact_keys(
        runtime,
        {
            "lock",
            "lock_id",
            "rondo_binary_sha256",
            "codex_binary_sha256",
        },
        "runtime identity",
    )
    path = _tracked_file(root, runtime.get("lock"), "runtime lock")
    _raw, value = _read_json(path, "runtime lock")
    if value.get("lock_id") != runtime.get("lock_id") or value.get("status") != "frozen":
        raise ContractError("runtime lock identity differs")
    if (
        value.get("codex_sha256") != runtime.get("rondo_binary_sha256")
        or _object(value, "codex_baseline").get("codex_sha256")
        != runtime.get("codex_binary_sha256")
    ):
        raise ContractError("runtime binary identity differs")


def _validate_semantics(
    lock: dict[str, Any], taskset: dict[str, Any], catalog: dict[str, Any]
) -> None:
    provider = _object(lock, "provider")
    pricing = _object(lock, "price_snapshot")
    execution = _object(lock, "execution")
    recovery = _object(lock, "recovery")
    budget = _object(lock, "budget")
    phase_a = _object(lock, "phase_a")
    artifacts = _object(lock, "artifacts")
    activation = _object(lock, "activation")
    _exact_keys(
        phase_a,
        {"network", "docker", "provider", "identity_class"},
        "phase A",
    )
    _exact_keys(
        provider,
        {
            "name",
            "wire_api",
            "base_url",
            "root_model",
            "root_effort",
            "member_model",
            "member_effort",
            "guardian_model",
            "guardian_effort",
            "request_limit_per_run",
            "request_attempt_limit",
            "retry_backoff_seconds",
            "retry_statuses",
        },
        "provider",
    )
    _exact_keys(
        pricing,
        {
            "date",
            "source_url",
            "pricing_page_url",
            "model_id",
            "input_usd_per_million",
            "cached_input_usd_per_million",
            "output_usd_per_million",
            "long_context_threshold_tokens",
            "long_context_input_multiplier",
            "long_context_output_multiplier",
            "cache_write_input_multiplier",
        },
        "price snapshot",
    )
    _exact_keys(
        execution,
        {
            "terminal_bench_slot_concurrency",
            "max_concurrent_threads_per_session",
            "provider_request_concurrency",
            "approval_policy",
            "sandbox_mode",
            "network_access_in_phase_b",
            "rollout_trace_root",
            "codex_team_state",
            "rondo_team_state",
        },
        "execution",
    )
    _exact_keys(
        recovery,
        {
            "max_infra_attempts_per_slot",
            "max_infra_attempts_total",
            "valid_task_failure_is_terminal",
            "resume_only_untrusted_or_missing_side",
        },
        "recovery",
    )
    _exact_keys(
        budget,
        {
            "phase_b_hard_cap_usd",
            "minimum_confirmed_balance_usd",
            "formal_namespace",
            "rehearsal_namespace",
            "batch_id",
            "usage_envelope",
            "request_reservation_usd",
            "max_concurrent_main_requests",
            "guardian_reserved_slots",
            "max_guardian_logical_requests",
            "per_run_spend_allowance_usd",
            "per_run_cap_usd",
            "max_run_slots",
            "unpriced_stop_threshold",
        },
        "budget",
    )
    _exact_keys(
        artifacts,
        {
            "ignored_root",
            "per_run",
            "aggregate",
            "replay_fixture",
            "replay_fixture_sha256",
            "tracked_body_fields",
        },
        "artifacts",
    )
    _exact_keys(
        activation,
        {
            "pilot_run_count",
            "requires_all_valid_terminal",
            "requires_policy_hash_match",
            "requires_all_team_lens_outputs",
            "minimum_trace_backed_root_spawn_accepts",
        },
        "activation",
    )
    if phase_a != {
        "network": False,
        "docker": False,
        "provider": False,
        "identity_class": "rehearsal",
    }:
        raise ContractError("Phase A boundary differs")
    if (
        provider.get("root_model") != "gpt-5.6-terra"
        or provider.get("member_model") != provider.get("root_model")
        or provider.get("root_effort") != "medium"
        or provider.get("member_effort") != provider.get("root_effort")
        or provider.get("guardian_model") != provider.get("root_model")
        or provider.get("guardian_effort") != provider.get("root_effort")
        or provider.get("request_limit_per_run") != 80
        or provider.get("request_attempt_limit") != 5
        or provider.get("retry_backoff_seconds") != 2
        or provider.get("retry_statuses") != [429, 500, 502, 503, 504]
        or provider.get("name") != "relay"
        or provider.get("wire_api") != "responses"
        or provider.get("base_url") != "https://www.cctq.ai/v1"
    ):
        raise ContractError("provider fairness contract differs")
    if pricing != {
        "date": "2026-08-18",
        "source_url": "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        "pricing_page_url": "https://developers.openai.com/api/docs/pricing",
        "model_id": "gpt-5.6-terra",
        "input_usd_per_million": "2",
        "cached_input_usd_per_million": "0.2",
        "output_usd_per_million": "12",
        "long_context_threshold_tokens": 272000,
        "long_context_input_multiplier": "2",
        "long_context_output_multiplier": "1.5",
        "cache_write_input_multiplier": "1.25",
    }:
        raise ContractError("price snapshot differs")
    if (
        execution.get("terminal_bench_slot_concurrency") != 1
        or execution.get("max_concurrent_threads_per_session") != 4
        or execution.get("provider_request_concurrency") != 4
        or execution.get("codex_team_state") is not None
        or execution.get("rondo_team_state") is not True
        or execution.get("rollout_trace_root") != "/logs/agent/rollout-trace"
        or execution.get("approval_policy") != "on-request"
        or execution.get("sandbox_mode") != "workspace-write"
        or execution.get("network_access_in_phase_b") is not True
    ):
        raise ContractError("execution fairness contract differs")
    if (
        recovery.get("max_infra_attempts_per_slot") != 5
        or recovery.get("max_infra_attempts_total") != 40
        or budget.get("phase_b_hard_cap_usd") != "100.00"
        or budget.get("minimum_confirmed_balance_usd") != "100.00"
        or recovery.get("valid_task_failure_is_terminal") is not True
        or recovery.get("resume_only_untrusted_or_missing_side") is not True
    ):
        raise ContractError("recovery or budget contract differs")
    usage_envelope = budget.get("usage_envelope")
    if usage_envelope != {
        "max_input_tokens": 272000,
        "max_output_tokens": 128000,
    }:
        raise ContractError("budget usage envelope differs")
    # At exactly the frozen long-context threshold the long-context multiplier
    # does not apply. The most expensive legal input shape is cache-write input.
    maximum_request = (
        Decimal(usage_envelope["max_input_tokens"])
        * Decimal(pricing["input_usd_per_million"])
        * Decimal(pricing["cache_write_input_multiplier"])
        + Decimal(usage_envelope["max_output_tokens"])
        * Decimal(pricing["output_usd_per_million"])
    ) / Decimal(1_000_000)
    reservation = maximum_request.quantize(Decimal("0.01"), rounding=ROUND_UP)
    peak = reservation * Decimal(5)
    run_cap = peak + Decimal("4.00")
    if (
        budget.get("batch_id") != "plan-049-paid-v1"
        or budget.get("formal_namespace") != "plan-049-paid-v1"
        or budget.get("rehearsal_namespace") != "plan-049-rehearsal-v1"
        or Decimal(str(budget.get("request_reservation_usd"))) != reservation
        or budget.get("max_concurrent_main_requests") != 4
        or budget.get("guardian_reserved_slots") != 1
        or budget.get("max_guardian_logical_requests") != 3
        or Decimal(str(budget.get("per_run_spend_allowance_usd")))
        != Decimal("4.00")
        or Decimal(str(budget.get("per_run_cap_usd"))) != run_cap
        or budget.get("max_run_slots") != 66
        or budget.get("unpriced_stop_threshold") != 1
    ):
        raise ContractError("paid budget arithmetic or identity differs")
    if (
        artifacts.get("ignored_root") != "eval-data/plan-049"
        or artifacts.get("tracked_body_fields") is not False
        or artifacts.get("per_run")
        != [
            "rollout-trace",
            "execution.json",
            "api-metadata.json",
            "shared-model-catalog.json",
            "team_view.json",
            "team_report.html",
            "run.json",
        ]
        or artifacts.get("aggregate") != "aggregate.json"
        or artifacts.get("replay_fixture")
        != "eval/fixtures/multi-proactive-delegation-v1/body-free-replay-v1.json"
        or artifacts.get("replay_fixture_sha256")
        != "305c25db9eaee162ca529a820d53dedc0e91b71c530e669d9e569aa50426f2dd"
        or activation.get("pilot_run_count") != 6
        or activation.get("minimum_trace_backed_root_spawn_accepts") != 1
        or any(
            activation.get(name) is not True
            for name in (
                "requires_all_valid_terminal",
                "requires_policy_hash_match",
                "requires_all_team_lens_outputs",
            )
        )
    ):
        raise ContractError("artifact or activation contract differs")
    known_tasks = {
        item.get("task_id")
        for item in catalog.get("tasks", [])
        if isinstance(item, dict)
    }
    pilot = _pairs(taskset.get("pilot_pairs"), "pilot")
    formal = _pairs(taskset.get("formal_pairs"), "formal")
    if len(pilot) != 3 or len(formal) != 10:
        raise ContractError("Plan 049 pair count differs")
    if any(pair["task_id"] not in known_tasks for pair in (*pilot, *formal)):
        raise ContractError("Plan 049 task is absent from the frozen catalog")


def _pairs(value: object, label: str) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        raise ContractError(f"{label} pairs are invalid")
    pairs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"pair_id", "task_id", "side_order"}:
            raise ContractError(f"{label} pair is invalid")
        pair_id = item.get("pair_id")
        order = item.get("side_order")
        if (
            not isinstance(pair_id, str)
            or pair_id in seen
            or not isinstance(item.get("task_id"), str)
            or not isinstance(order, list)
            or sorted(order) != ["codex", "rondo"]
        ):
            raise ContractError(f"{label} pair identity is invalid")
        seen.add(pair_id)
        pairs.append(item)
    return tuple(pairs)


def _tracked_file(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.startswith("eval/") or ".." in value.split("/"):
        raise ContractError(f"{label} path is invalid")
    path = root / value
    try:
        resolved = path.resolve(strict=True)
        path.lstat()
    except OSError as exc:
        raise ContractError(f"{label} is unavailable") from exc
    if path.is_symlink() or not path.is_file() or not resolved.is_relative_to(root):
        raise ContractError(f"{label} is unsafe")
    return path


def _read_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} is not an object")
    return raw, value


def _require_digest(raw: bytes, expected: object, label: str) -> None:
    if not isinstance(expected, str) or hashlib.sha256(raw).hexdigest() != expected:
        raise ContractError(f"{label} digest differs")


def _object(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ContractError(f"{key} contract is invalid")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ContractError(f"{label} has unknown or missing fields")
