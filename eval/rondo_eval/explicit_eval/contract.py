"""Strict loader for the frozen Plan 050 comparative case-study contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_UP
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
LOCK_RELPATH = "eval/locks/multi-explicit-collaboration-v1.json"
POLICY_TEXT = (
    "You must use teammates to carry out genuine multi-agent collaboration on this task. "
    "Delegate substantial and independently actionable work to teammates. When new evidence "
    "could affect another line of work, communicate it and adapt the approach or work division "
    "as warranted. Integrate and verify teammate contributions before finishing. Choose the "
    "team shape, timing, communication pattern, and tool sequence autonomously. Do not fabricate "
    "activity for observability or target Team State events, routes, facts, wakes, telemetry counts, "
    "participant counts, or call ordering. The Root remains responsible for the final solution and "
    "verifier outcome."
)
POLICY_SHA256 = "a4d90e09a9c0ff69816a6da4153a6fb78c3ad8695dd4076c9884a33eb3b90b49"
CATALOG_SHA256 = "00b83e4435218de730c25fcbc8fd69cebc0cee36db433a4b305076cb1e157ddf"
RUNTIME_LOCK_SHA256 = "7763dc4e29077576465187aed81c8231afac73a9cf22c6b67d5cc9266bd8f02c"
TERMINAL_BENCH_COMMIT = "ffccbe05ee73a9d59518217f294ad711bda39304"
TERMINAL_BENCH_TASKSET_SHA256 = (
    "2a9f9e3400f38606bacd71a220d8abb595a108ef3622556e8684dadbeb03a61b"
)
TASKSET_SHA256 = "ea50a232328b84a32e1aa843ddb665b940b4eb7c0a568d57789d0464bbf0308a"
REPLAY_FIXTURE_SHA256 = (
    "28ef4c848dc253ed18734a70b34a4342e00f4fa9e64871a8e42eacd76c481190"
)
COMMON_V2_TOOL_NAMES = frozenset(
    {
        "followup_task",
        "interrupt_agent",
        "list_agents",
        "send_message",
        "spawn_agent",
        "wait_agent",
    }
)
RONDO_TEAM_STATE_TOOL_NAMES = frozenset(
    {
        "team_evidence",
        "team_history",
        "team_inspect",
        "team_publish",
        "team_retire",
        "team_route",
        "team_route_update",
        "team_update",
    }
)

CASE_PAIRS = (
    {
        "pair_id": "C01",
        "task_id": "terminal-bench/sqlite-db-truncate",
        "side_order": ["codex", "rondo"],
    },
    {
        "pair_id": "C02",
        "task_id": "terminal-bench/headless-terminal",
        "side_order": ["rondo", "codex"],
    },
    {
        "pair_id": "C03",
        "task_id": "terminal-bench/extract-elf",
        "side_order": ["codex", "rondo"],
    },
)

_SELECTED_TASKS: dict[str, dict[str, Any]] = {
    "terminal-bench/sqlite-db-truncate": {
        "task_id": "terminal-bench/sqlite-db-truncate",
        "source_digest": "sha256:956f038b479cc3b9b493553b57a60a8ff4154526386c3914c0b99e93e1ab6e87",
        "image_tag": "alexgshaw/sqlite-db-truncate:20251031",
        "image_ref": "alexgshaw/sqlite-db-truncate@sha256:aabac93c93bd1f310e6a6fb893911d7735026ed18491c72133c9196a09092ca4",
        "workdir": "/app",
        "memory_mb": 2048,
        "timeout_seconds": 1800,
        "agent_timeout_seconds": 900,
        "verifier_timeout_seconds": 900,
        "build_timeout_seconds": 600,
        "requires_existing_git_repo": False,
        "pids_limit": 256,
    },
    "terminal-bench/headless-terminal": {
        "task_id": "terminal-bench/headless-terminal",
        "source_digest": "sha256:203953871ebdae4efbf163af9499849368dab5e219b70d447e5ee9701ad382d9",
        "image_tag": "alexgshaw/headless-terminal:20251031",
        "image_ref": "alexgshaw/headless-terminal@sha256:eb7e209672bf6cef2785fafd9e13509b10626c327bcc2b37f5bf40ca83eaf3aa",
        "workdir": "/app",
        "memory_mb": 2048,
        "timeout_seconds": 1800,
        "agent_timeout_seconds": 900,
        "verifier_timeout_seconds": 900,
        "build_timeout_seconds": 600,
        "requires_existing_git_repo": False,
        "pids_limit": 256,
    },
    "terminal-bench/extract-elf": {
        "task_id": "terminal-bench/extract-elf",
        "source_digest": "sha256:1ef31d566be4fe3459d5368621ae7ef7a31b23ef675737e473bbc43c8c7b3fce",
        "image_tag": "alexgshaw/extract-elf:20251031",
        "image_ref": "alexgshaw/extract-elf@sha256:6932e4cb318464307eacd497ef8dc617eaf551b6a90231f815ec0b911895cfed",
        "workdir": "/app",
        "memory_mb": 2048,
        "timeout_seconds": 1800,
        "agent_timeout_seconds": 900,
        "verifier_timeout_seconds": 900,
        "build_timeout_seconds": 600,
        "requires_existing_git_repo": False,
        "pids_limit": 256,
    },
}

_TASK_KEYS = {
    "task_id",
    "source_digest",
    "image_tag",
    "image_ref",
    "workdir",
    "memory_mb",
    "timeout_seconds",
    "agent_timeout_seconds",
    "verifier_timeout_seconds",
    "build_timeout_seconds",
    "requires_existing_git_repo",
    "pids_limit",
}


class ContractError(ValueError):
    """Raised before campaign state or an external side effect can be created."""


@dataclass(frozen=True)
class CampaignContract:
    lock: dict[str, Any]
    taskset: dict[str, Any]
    catalog: dict[str, Any]
    policy: str
    replay_fixture: dict[str, Any]
    lock_sha256: str
    actual_cap_usd: Decimal | None = None

    @property
    def lock_id(self) -> str:
        return str(self.lock["lock_id"])

    @property
    def policy_sha256(self) -> str:
        return str(self.lock["policy"]["sha256"])

    @property
    def taskset_sha256(self) -> str:
        return str(self.lock["taskset"]["sha256"])

    @property
    def maximum_authorizable_cap_usd(self) -> Decimal:
        return Decimal(str(self.lock["budget"]["maximum_authorizable_cap_usd"]))

    @property
    def campaign_cap_usd(self) -> Decimal:
        if self.actual_cap_usd is None:
            raise ContractError(
                "Plan 050 actual campaign cap requires a Phase B receipt binding"
            )
        return self.actual_cap_usd

    def bind_actual_cap(self, value: Decimal | str) -> CampaignContract:
        try:
            cap = Decimal(str(value))
        except InvalidOperation as exc:
            raise ContractError("Plan 050 actual campaign cap is invalid") from exc
        if not cap.is_finite():
            raise ContractError("Plan 050 actual campaign cap is outside the lock")
        try:
            cents = cap.quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise ContractError("Plan 050 actual campaign cap is invalid") from exc
        if (
            cap <= 0
            or cap != cents
            or cap > self.maximum_authorizable_cap_usd
        ):
            raise ContractError("Plan 050 actual campaign cap is outside the lock")
        return replace(self, actual_cap_usd=cents)

    def task_contract(self, task_id: str) -> dict[str, Any]:
        matches = [
            item
            for item in self.catalog["tasks"]
            if isinstance(item, dict) and item.get("task_id") == task_id
        ]
        if len(matches) != 1:
            raise ContractError("Plan 050 selected task is not uniquely frozen")
        return dict(matches[0])


def require_common_v2_tool_projections(
    codex_projection: object, rondo_projection: object
) -> None:
    projections: dict[str, set[str]] = {}
    for side, raw in (("codex", codex_projection), ("rondo", rondo_projection)):
        if (
            not isinstance(raw, list)
            or any(not isinstance(name, str) or not name for name in raw)
            or raw != sorted(set(raw))
        ):
            raise ContractError("Plan 050 observed tool projection is invalid")
        projections[side] = set(raw)
        if not COMMON_V2_TOOL_NAMES.issubset(projections[side]):
            raise ContractError(f"Plan 050 {side} common-V2 tools are incomplete")
    codex = projections["codex"]
    rondo = projections["rondo"]
    if codex & RONDO_TEAM_STATE_TOOL_NAMES:
        raise ContractError("Codex unexpectedly exposes RONDO Team State tools")
    if (
        rondo - RONDO_TEAM_STATE_TOOL_NAMES != codex
        or rondo - codex != RONDO_TEAM_STATE_TOOL_NAMES
    ):
        raise ContractError("Plan 050 common-V2 tool projections differ")


def load_contract(repo_root: Path = REPO_ROOT) -> CampaignContract:
    root = Path(repo_root).resolve()
    lock_path = _tracked_file(root, LOCK_RELPATH, "campaign lock")
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
            "case_study",
        },
        "campaign lock",
    )
    if (
        lock.get("schema_version") != 1
        or lock.get("lock_id") != "multi-explicit-collaboration-v1"
        or lock.get("status") != "frozen"
        or lock.get("plan") != "050"
    ):
        raise ContractError("Plan 050 lock identity is invalid")

    taskset_meta = _object(lock, "taskset")
    _exact_keys(
        taskset_meta,
        {
            "path",
            "sha256",
            "catalog_path",
            "catalog_sha256",
            "terminal_bench_commit",
            "terminal_bench_taskset_sha256",
        },
        "taskset identity",
    )
    if taskset_meta != {
        "path": "eval/tasksets/multi-explicit-collaboration-v1.json",
        "sha256": TASKSET_SHA256,
        "catalog_path": "eval/tasksets/p2-b7-canary-catalog-v4.json",
        "catalog_sha256": CATALOG_SHA256,
        "terminal_bench_commit": TERMINAL_BENCH_COMMIT,
        "terminal_bench_taskset_sha256": TERMINAL_BENCH_TASKSET_SHA256,
    }:
        raise ContractError("Plan 050 taskset lock identity differs")
    taskset_path = _tracked_file(root, taskset_meta.get("path"), "taskset")
    taskset_raw, taskset = _read_json(taskset_path, "taskset")
    _require_digest(taskset_raw, taskset_meta.get("sha256"), "taskset")
    _validate_taskset(taskset, taskset_meta)

    catalog_path = _tracked_file(root, taskset_meta.get("catalog_path"), "catalog")
    catalog_raw, catalog = _read_json(catalog_path, "catalog")
    _require_digest(catalog_raw, taskset_meta.get("catalog_sha256"), "catalog")
    _validate_catalog(catalog, taskset_meta)

    policy_meta = _object(lock, "policy")
    _exact_keys(
        policy_meta,
        {"path", "sha256", "encoding", "line_count", "trailing_lf"},
        "policy identity",
    )
    policy_path = _tracked_file(root, policy_meta.get("path"), "policy")
    try:
        policy_raw = policy_path.read_bytes()
        policy = policy_raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise ContractError("Plan 050 policy is unreadable") from exc
    _require_digest(policy_raw, policy_meta.get("sha256"), "policy")
    if (
        policy_meta
        != {
            "path": "eval/templates/multi-explicit-collaboration/explicit-collaboration-policy-v1.md",
            "sha256": POLICY_SHA256,
            "encoding": "utf-8",
            "line_count": 1,
            "trailing_lf": True,
        }
        or policy != POLICY_TEXT + "\n"
    ):
        raise ContractError("Plan 050 policy bytes differ")

    _validate_runtime(root, lock)
    _validate_semantics(lock)
    artifacts = _object(lock, "artifacts")
    fixture_path = _tracked_file(
        root, artifacts.get("replay_fixture"), "replay fixture"
    )
    fixture_raw, fixture = _read_json(fixture_path, "replay fixture")
    _require_digest(
        fixture_raw, artifacts.get("replay_fixture_sha256"), "replay fixture"
    )
    _validate_replay_fixture(fixture)
    return CampaignContract(
        lock=lock,
        taskset=taskset,
        catalog=catalog,
        policy=policy,
        replay_fixture=fixture,
        lock_sha256=hashlib.sha256(lock_raw).hexdigest(),
    )


def _validate_runtime(root: Path, lock: dict[str, Any]) -> None:
    runtime = _object(lock, "runtime")
    expected = {
        "lock": "eval/locks/multi-m5-runtime-v4.json",
        "lock_id": "multi-m5-runtime-v4",
        "lock_sha256": RUNTIME_LOCK_SHA256,
        "rondo_source_commit": "0eee6dc5ee69f0eca9e1db350148c423a2b2bf67",
        "rondo_binary_sha256": "c64ff001fe7bec20c84a6bbea84f077ffffdcddc8b796b2f663513d5d7a6c631",
        "codex_source_commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
        "codex_binary_sha256": "8bd5f096af8302c0d5bf272a15a563d243fe77e8b704b749321a437c815f1a80",
    }
    _exact_keys(runtime, set(expected), "runtime identity")
    if runtime != expected:
        raise ContractError("Plan 050 runtime identity differs")
    path = _tracked_file(root, runtime["lock"], "runtime lock")
    raw, value = _read_json(path, "runtime lock")
    _require_digest(raw, runtime["lock_sha256"], "runtime lock")
    _exact_keys(
        value,
        {
            "schema_version",
            "lock_id",
            "status",
            "product",
            "source_commit",
            "rust_target",
            "measurement_worktree",
            "bundle_dir_name",
            "bundle_relpath",
            "codex_sha256",
            "code_mode_host_sha256",
            "bwrap_sha256",
            "manifest_sha256",
            "supersedes",
            "supersedes_reason",
            "codex_baseline",
        },
        "runtime lock",
    )
    baseline = _object(value, "codex_baseline")
    _exact_keys(
        baseline,
        {
            "product",
            "source_commit",
            "bundle_dir_name",
            "bundle_relpath",
            "codex_sha256",
            "code_mode_host_sha256",
            "bwrap_sha256",
            "manifest_sha256",
        },
        "Codex runtime identity",
    )
    if (
        value.get("schema_version") != 1
        or value.get("lock_id") != runtime["lock_id"]
        or value.get("status") != "frozen"
        or value.get("product") != "rondo-multi"
        or value.get("source_commit") != runtime["rondo_source_commit"]
        or value.get("codex_sha256") != runtime["rondo_binary_sha256"]
        or baseline.get("product") != "codex"
        or baseline.get("source_commit") != runtime["codex_source_commit"]
        or baseline.get("codex_sha256") != runtime["codex_binary_sha256"]
    ):
        raise ContractError("Plan 050 runtime lock differs")


def _validate_taskset(taskset: dict[str, Any], meta: dict[str, Any]) -> None:
    _exact_keys(
        taskset,
        {
            "schema_version",
            "taskset_id",
            "catalog",
            "catalog_sha256",
            "terminal_bench_commit",
            "terminal_bench_taskset_sha256",
            "case_pairs",
        },
        "taskset",
    )
    if (
        taskset.get("schema_version") != 1
        or taskset.get("taskset_id") != "multi-explicit-collaboration-v1"
        or taskset.get("catalog") != meta.get("catalog_path")
        or taskset.get("catalog_sha256") != CATALOG_SHA256
        or taskset.get("catalog_sha256") != meta.get("catalog_sha256")
        or taskset.get("terminal_bench_commit") != TERMINAL_BENCH_COMMIT
        or taskset.get("terminal_bench_commit") != meta.get("terminal_bench_commit")
        or taskset.get("terminal_bench_taskset_sha256")
        != TERMINAL_BENCH_TASKSET_SHA256
        or taskset.get("terminal_bench_taskset_sha256")
        != meta.get("terminal_bench_taskset_sha256")
    ):
        raise ContractError("Plan 050 taskset identity differs")
    pairs = taskset.get("case_pairs")
    if not isinstance(pairs, list) or tuple(pairs) != CASE_PAIRS:
        raise ContractError("Plan 050 case pair schedule differs")
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ContractError("Plan 050 case pair is invalid")
        _exact_keys(pair, {"pair_id", "task_id", "side_order"}, "case pair")


def _validate_catalog(catalog: dict[str, Any], meta: dict[str, Any]) -> None:
    _exact_keys(
        catalog,
        {"schema_version", "terminal_bench_commit", "taskset_sha256", "tasks"},
        "catalog",
    )
    tasks = catalog.get("tasks")
    if (
        catalog.get("schema_version") != 2
        or catalog.get("terminal_bench_commit") != TERMINAL_BENCH_COMMIT
        or catalog.get("terminal_bench_commit") != meta.get("terminal_bench_commit")
        or catalog.get("taskset_sha256") != TERMINAL_BENCH_TASKSET_SHA256
        or catalog.get("taskset_sha256")
        != meta.get("terminal_bench_taskset_sha256")
        or not isinstance(tasks, list)
    ):
        raise ContractError("Plan 050 catalog identity differs")
    selected: dict[str, dict[str, Any]] = {}
    for raw in tasks:
        if not isinstance(raw, dict):
            raise ContractError("Plan 050 catalog task is invalid")
        _exact_keys(raw, _TASK_KEYS, "catalog task")
        task_id = raw.get("task_id")
        if task_id in _SELECTED_TASKS:
            if task_id in selected:
                raise ContractError("Plan 050 selected catalog task is duplicated")
            selected[str(task_id)] = raw
    if selected != _SELECTED_TASKS:
        raise ContractError("Plan 050 selected task contract differs")


def _validate_semantics(lock: dict[str, Any]) -> None:
    phase_a = _object(lock, "phase_a")
    provider = _object(lock, "provider")
    pricing = _object(lock, "price_snapshot")
    execution = _object(lock, "execution")
    recovery = _object(lock, "recovery")
    budget = _object(lock, "budget")
    artifacts = _object(lock, "artifacts")
    case_study = _object(lock, "case_study")

    expected_phase_a = {
        "network": False,
        "docker": False,
        "provider": False,
        "identity_class": "rehearsal",
    }
    expected_provider = {
        "name": "relay",
        "wire_api": "responses",
        "base_url": "https://www.cctq.ai/v1",
        "root_model": "gpt-5.6-terra",
        "root_effort": "high",
        "member_model": "gpt-5.6-terra",
        "member_effort": "high",
        "guardian_model": "gpt-5.6-terra",
        "guardian_effort": "high",
        "request_limit_per_run": 80,
        "request_attempt_limit": 5,
        "retry_backoff_seconds": 2,
        "retry_statuses": [429, 500, 502, 503, 504],
    }
    expected_pricing = {
        "date": "2026-08-21",
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
    }
    expected_execution = {
        "terminal_bench_slot_concurrency": 1,
        "max_concurrent_threads_per_session": 4,
        "provider_request_concurrency": 4,
        "approval_policy": "on-request",
        "sandbox_mode": "workspace-write",
        "network_access_in_phase_b": True,
        "rollout_trace_root": "/logs/agent/rollout-trace",
        "codex_team_state": None,
        "rondo_team_state": True,
    }
    expected_recovery = {
        "infra_attempt_limit_per_slot": None,
        "infra_attempt_limit_total": None,
        "retry_bound": "campaign_budget_and_resource_gates",
        "valid_terminal_is_immutable": True,
        "settled_result_reduction_only": True,
        "resume_only_incomplete_side": True,
        "unknown_request_or_usage": "principled_stop",
        "non_infra_terminal_missing_trace": "principled_stop",
    }
    expected_case_study = {
        "base_pair_count": 3,
        "base_run_count": 6,
        "external_outcomes": ["completed", "task_failed", "product_failed"],
        "collaboration_statuses": [
            "collaboration_observed",
            "policy_noncompliance",
        ],
        "observation_statuses": [
            "available",
            "partial",
            "unsupported",
            "not_applicable",
        ],
        "impact_chain_statuses": ["observed", "not_observed", "unknown"],
        "valid_failure_is_terminal": True,
        "policy_noncompliance_is_terminal": True,
        "requires_unique_exec_root": True,
        "guardian_excluded_from_team_metrics": True,
    }
    for value, expected, label in (
        (phase_a, expected_phase_a, "Phase A"),
        (provider, expected_provider, "provider"),
        (pricing, expected_pricing, "price snapshot"),
        (execution, expected_execution, "execution"),
        (recovery, expected_recovery, "recovery"),
        (case_study, expected_case_study, "case study"),
    ):
        _exact_keys(value, set(expected), label)
        if value != expected:
            raise ContractError(f"Plan 050 {label} contract differs")

    expected_budget_keys = {
        "maximum_authorizable_cap_usd",
        "actual_cap_usd",
        "actual_cap_binding",
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
    }
    _exact_keys(budget, expected_budget_keys, "budget")
    usage = budget.get("usage_envelope")
    if usage != {"max_input_tokens": 272000, "max_output_tokens": 128000}:
        raise ContractError("Plan 050 budget usage envelope differs")
    maximum_request = (
        Decimal(usage["max_input_tokens"])
        * Decimal(expected_pricing["input_usd_per_million"])
        * Decimal(expected_pricing["cache_write_input_multiplier"])
        + Decimal(usage["max_output_tokens"])
        * Decimal(expected_pricing["output_usd_per_million"])
    ) / Decimal(1_000_000)
    reservation = maximum_request.quantize(Decimal("0.01"), rounding=ROUND_UP)
    run_cap = reservation * Decimal(5) + Decimal("4.00")
    if (
        budget.get("maximum_authorizable_cap_usd") != "100.00"
        or budget.get("actual_cap_usd") is not None
        or budget.get("actual_cap_binding") != "phase_b_receipt"
        or budget.get("formal_namespace") != "plan-050-paid-v1"
        or budget.get("rehearsal_namespace") != "plan-050-rehearsal-v1"
        or budget.get("batch_id") != "plan-050-paid-v1"
        or Decimal(str(budget.get("request_reservation_usd"))) != reservation
        or budget.get("max_concurrent_main_requests") != 4
        or budget.get("guardian_reserved_slots") != 1
        or budget.get("max_guardian_logical_requests") != 3
        or budget.get("per_run_spend_allowance_usd") != "4.00"
        or Decimal(str(budget.get("per_run_cap_usd"))) != run_cap
        or budget.get("max_run_slots") != 256
        or budget.get("unpriced_stop_threshold") != 1
    ):
        raise ContractError("Plan 050 budget arithmetic or identity differs")

    expected_artifacts = {
        "ignored_root": "eval-data/plan-050",
        "per_run": [
            "rollout-trace",
            "settled.json",
            "execution.json",
            "api-metadata.json",
            "shared-model-catalog.json",
            "team_view.json",
            "team_report.html",
            "run.json",
        ],
        "aggregate": "aggregate.json",
        "case_directory": "cases",
        "case_file_pattern": "{pair_id}.json",
        "overview": "overview.json",
        "replay_fixture": "eval/fixtures/multi-explicit-collaboration-v1/body-free-replay-v1.json",
        "replay_fixture_sha256": REPLAY_FIXTURE_SHA256,
        "tracked_body_fields": False,
    }
    _exact_keys(artifacts, set(expected_artifacts), "artifacts")
    if artifacts != expected_artifacts:
        raise ContractError("Plan 050 artifact contract differs")


def _validate_replay_fixture(value: dict[str, Any]) -> None:
    _exact_keys(
        value,
        {"schema_version", "evidence_kind", "identity_class", "records"},
        "replay fixture",
    )
    records = value.get("records")
    if (
        value.get("schema_version") != 1
        or value.get("evidence_kind") != "synthetic_body_free_replay"
        or value.get("identity_class") != "rehearsal"
        or not isinstance(records, list)
        or len(records) != 6
    ):
        raise ContractError("Plan 050 replay fixture identity differs")
    expected_slots = [
        ("case-c01-codex", "codex"),
        ("case-c01-rondo", "rondo"),
        ("case-c02-rondo", "rondo"),
        ("case-c02-codex", "codex"),
        ("case-c03-codex", "codex"),
        ("case-c03-rondo", "rondo"),
    ]
    record_keys = {
        "slot_id",
        "side",
        "product",
        "outcome",
        "collaboration_status",
        "impact_chain_status",
        "trace_status",
        "observation_status",
        "team_state",
        "root_spawn_accept_count",
        "returned_member_count",
    }
    for record, (slot_id, side) in zip(records, expected_slots, strict=True):
        if not isinstance(record, dict):
            raise ContractError("Plan 050 replay record is invalid")
        _exact_keys(record, record_keys, "replay record")
        team_state = record.get("team_state")
        if isinstance(team_state, dict):
            _exact_keys(team_state, {"status", "event_count"}, "replay Team State")
            if (
                team_state.get("status")
                not in {"available", "partial", "unsupported", "not_applicable"}
                or not isinstance(team_state.get("event_count"), int)
                or isinstance(team_state.get("event_count"), bool)
                or team_state["event_count"] < 0
            ):
                raise ContractError("Plan 050 replay Team State contract differs")
        if (
            record.get("slot_id") != slot_id
            or record.get("side") != side
            or record.get("product")
            != (None if side == "codex" else "rondo-multi")
            or record.get("outcome")
            not in {"completed", "task_failed", "product_failed"}
            or record.get("collaboration_status")
            not in {"collaboration_observed", "policy_noncompliance"}
            or record.get("impact_chain_status")
            not in {"observed", "not_observed", "unknown"}
            or record.get("trace_status") not in {"available", "partial"}
            or record.get("observation_status")
            not in {"available", "partial", "unsupported", "not_applicable"}
            or (side == "codex" and team_state is not None)
            or (side == "rondo" and not isinstance(team_state, dict))
            or not isinstance(record.get("root_spawn_accept_count"), int)
            or not isinstance(record.get("returned_member_count"), int)
            or isinstance(record.get("root_spawn_accept_count"), bool)
            or isinstance(record.get("returned_member_count"), bool)
            or record["root_spawn_accept_count"] < 0
            or record["returned_member_count"] < 0
            or (
                record.get("collaboration_status") == "collaboration_observed"
                and (
                    record["root_spawn_accept_count"] < 1
                    or record["returned_member_count"] < 1
                )
            )
        ):
            raise ContractError("Plan 050 replay record contract differs")


def _tracked_file(root: Path, value: object, label: str) -> Path:
    if (
        not isinstance(value, str)
        or not value.startswith("eval/")
        or ".." in value.split("/")
    ):
        raise ContractError(f"Plan 050 {label} path is invalid")
    path = root / value
    try:
        resolved = path.resolve(strict=True)
        path.lstat()
    except OSError as exc:
        raise ContractError(f"Plan 050 {label} is unavailable") from exc
    if path.is_symlink() or not path.is_file() or not resolved.is_relative_to(root):
        raise ContractError(f"Plan 050 {label} is unsafe")
    return path


def _read_json(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        if path.stat().st_size > 1_000_000:
            raise ContractError(f"Plan 050 {label} is implausibly large")
        raw = path.read_bytes()
        value = json.loads(raw)
    except ContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"Plan 050 {label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ContractError(f"Plan 050 {label} is not an object")
    return raw, value


def _require_digest(raw: bytes, expected: object, label: str) -> None:
    if not isinstance(expected, str) or hashlib.sha256(raw).hexdigest() != expected:
        raise ContractError(f"Plan 050 {label} digest differs")


def _object(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ContractError(f"Plan 050 {key} is not an object")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise ContractError(f"Plan 050 {label} has unknown or missing fields")
