"""Locked Plan 049 paid runner built from the shared budget and TB primitives.

Nothing in this module grants authorization.  :mod:`paid` is the sole caller
that may construct these paths with the real namespace, and it does so only
after all Phase-B gates have passed.  Phase A exercises the same state machine
only below temporary test directories with injected executors.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Protocol

from ..api_budget_proxy import (
    ApiBudgetProxyError,
    BudgetStopped,
    PersistentBudgetLedger,
    UsageEnvelope,
    canonical_request_sha256,
    stop_reason_class,
)
from ..config import RepoPaths, RuntimeConfig, load_runtime_config
from ..contracts import Product, ProviderProjection, RunOutcome, Side
from ..docker_supervisor import (
    DockerCounter,
    DockerResourceStop,
    HeavyLockGuard,
    HeavyLockLease,
)
from ..frozen_model_catalog import load_shared_model_catalog
from ..multi_m5.budget import (
    REQUEST_LIMIT_STOP_REASON,
    RequestCappedLedger,
    run_infra_taint,
    run_stop_reason,
)
from ..multi_m5.bundle import load_side_manifest
from ..multi_m5.load import load_runtime_identity
from ..multi_m5.loopback import collect_registered_tool_names
from ..multi_m5.resume import (
    ResumeError,
    claimed_run_disposition,
    ensure_formal_receipt,
    require_archived_runs_in_ledger,
    require_formal_receipt,
    require_single_unarchived_run,
)
from ..multi_m5.trace import find_trace_bundle
from ..team_lens.model import dump_team_view, validate_team_view
from ..team_lens.reducer import reduce_bundle
from ..team_lens.report import render_report
from ..terminal_bench.live import run_budgeted_terminal_bench_core
from ..terminal_bench.results import HarborResultError, parse_single_task_result
from ..terminal_bench.runner import (
    PreparedTerminalBenchRun,
    TaskMaterializer,
    TerminalBenchRequest,
    TerminalBenchRunError,
)
from ..terminal_bench.tasksets import SOURCE_DIRECTORY, load_successor_canary_catalog
from .aggregate import aggregate
from .contract import CampaignContract
from .schedule import Slot, slots
from .store import assert_body_free


_RUN_ID = re.compile(
    r"plan049-paid-(?:pilot|formal)-(?:p|f)[0-9]{2}-(?:codex|rondo)-a0[1-5]\Z"
)
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_REQUIRED_TOOLS = {"list_agents", "send_message", "spawn_agent", "wait_agent"}
_SECCOMP_RELPATH = "eval/seccomp/plan008-userns-minimal-v0.2.3.json"
_SECCOMP_SOURCE_SHA256 = "9c5198e529f03d38babe9f270f663fa6867bda4e4d14a37a1f6680179d9bbd2f"
_SECCOMP_EFFECTIVE_SHA256 = "a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf"
_TERMINAL = {"completed", "task_failed", "product_failed"}
_OUTCOMES = _TERMINAL | {"infra_failed", "budget_stopped"}
_RECORD_KEYS = {
    "schema_version",
    "evidence_kind",
    "identity_class",
    "formal_identity_sha256",
    "lock_id",
    "lock_sha256",
    "policy_sha256",
    "taskset_sha256",
    "phase",
    "pair_id",
    "slot_id",
    "run_id",
    "budget_run_id",
    "attempt",
    "task_id",
    "side",
    "product",
    "outcome",
    "terminal",
    "counts_as_effective",
    "cost_usd",
    "request_count",
    "trace_status",
    "team_view_sha256",
    "team_report_sha256",
    "request_preflight_sha256",
    "reason_code",
}


class FormalError(RuntimeError):
    """The paid campaign state cannot be advanced safely."""


@dataclass(frozen=True)
class FormalPaths:
    root: Path
    receipt: Path
    ledger: Path
    archive: Path
    aggregate: Path
    runs: Path


@dataclass(frozen=True)
class FormalExecutionResult:
    outcome: str
    trace_status: str
    team_view_sha256: str
    team_report_sha256: str
    request_preflight_sha256: str
    reason_code: str | None = None


class FormalExecutor(Protocol):
    def execute(
        self, slot: Slot, *, attempt: int, run_id: str, run_root: Path
    ) -> FormalExecutionResult: ...


def formal_paths(common_root: Path, contract: CampaignContract) -> FormalPaths:
    namespace = str(contract.lock["budget"]["formal_namespace"])
    root = (
        Path(common_root).resolve()
        / "eval-data"
        / "plan-049"
        / "paid"
        / namespace
    )
    return FormalPaths(
        root=root,
        receipt=root / "activation-receipt.json",
        ledger=root / "budget-ledger.json",
        archive=root / "records.jsonl",
        aggregate=root / "aggregate.json",
        runs=root / "runs",
    )


def usage_envelope(contract: CampaignContract) -> UsageEnvelope:
    raw = contract.lock["budget"]["usage_envelope"]
    value = UsageEnvelope(
        max_input_tokens=int(raw["max_input_tokens"]),
        max_output_tokens=int(raw["max_output_tokens"]),
    )
    value.validate()
    return value


def request_reservation_usd(contract: CampaignContract) -> Decimal:
    return Decimal(str(contract.lock["budget"]["request_reservation_usd"]))


def run_cap_usd(contract: CampaignContract) -> Decimal:
    return Decimal(str(contract.lock["budget"]["per_run_cap_usd"]))


def open_paid_ledger(path: Path, contract: CampaignContract) -> PersistentBudgetLedger:
    budget = contract.lock["budget"]
    return PersistentBudgetLedger(
        path,
        batch_id=str(budget["batch_id"]),
        total_cap_usd=str(budget["phase_b_hard_cap_usd"]),
        max_runs=int(budget["max_run_slots"]),
        default_run_cap_usd=str(budget["per_run_cap_usd"]),
        usage_envelope=usage_envelope(contract),
        unpriced_stop_threshold=int(budget["unpriced_stop_threshold"]),
    )


def plan049_provider_projection(
    config: RuntimeConfig, contract: CampaignContract
) -> ProviderProjection:
    """Resolve mutable machine config, then freeze both paid roles to the lock."""

    provider = contract.lock["provider"]
    projected = config.paid_provider_projection(
        str(provider["name"]), model_id=str(provider["root_model"])
    )
    projected = replace(
        projected,
        guardian_model=str(provider["guardian_model"]),
        guardian_effort=str(provider["guardian_effort"]),
        guardian_pricing=projected.main_pricing,
        retry_backoff_seconds=float(provider["retry_backoff_seconds"]),
    )
    projected.validate()
    price = contract.lock["price_snapshot"]
    if (
        projected.provider_id != provider["name"]
        or projected.api != provider["wire_api"]
        or projected.base_url.rstrip("/") != str(provider["base_url"]).rstrip("/")
        or projected.main_model != provider["root_model"]
        or projected.main_effort != provider["root_effort"]
        or projected.guardian_model != provider["guardian_model"]
        or projected.guardian_effort != provider["guardian_effort"]
        or projected.max_attempts != provider["request_attempt_limit"]
        or list(projected.unbilled_retry_statuses) != provider["retry_statuses"]
        or projected.main_pricing.to_dict()
        != {
            "model_id": price["model_id"],
            "input_usd_per_million": price["input_usd_per_million"],
            "cached_input_usd_per_million": price["cached_input_usd_per_million"],
            "output_usd_per_million": price["output_usd_per_million"],
            "long_context_threshold_tokens": str(
                price["long_context_threshold_tokens"]
            ),
            "long_context_input_multiplier": price[
                "long_context_input_multiplier"
            ],
            "long_context_output_multiplier": price[
                "long_context_output_multiplier"
            ],
            "cache_write_input_multiplier": price[
                "cache_write_input_multiplier"
            ],
            "price_snapshot_date": price["date"],
            "price_source_url": price["source_url"],
        }
    ):
        raise FormalError("Plan 049 provider projection differs from the lock")
    return projected


def provider_identity(provider: ProviderProjection) -> dict[str, Any]:
    return {
        "provider_id": provider.provider_id,
        "provider_api": provider.api,
        "provider_base_url": provider.base_url,
        "main_model": provider.main_model,
        "main_effort": provider.main_effort,
        "guardian_model": provider.guardian_model,
        "guardian_effort": provider.guardian_effort,
        "provider_profile_sha256": provider.profile_sha256,
        "provider_config_sha256": provider.config_sha256,
        "main_pricing": provider.main_pricing.to_dict(),
        "guardian_pricing": provider.guardian_pricing.to_dict(),
    }


def formal_identity(
    contract: CampaignContract,
    *,
    provider: ProviderProjection,
    harness_commit: str,
) -> dict[str, Any]:
    if not isinstance(harness_commit, str) or _COMMIT.fullmatch(harness_commit) is None:
        raise FormalError("Plan 049 formal identity requires a clean commit")
    value = {
        "identity_class": "paid",
        "budget_batch_id": contract.lock["budget"]["batch_id"],
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "taskset_sha256": contract.taskset_sha256,
        "policy_sha256": contract.policy_sha256,
        "runtime_lock_id": contract.lock["runtime"]["lock_id"],
        "provider_identity": provider_identity(provider),
        "harness_commit": harness_commit,
        "harness_dirty": False,
        "campaign_cap_usd": contract.lock["budget"]["phase_b_hard_cap_usd"],
    }
    assert_body_free(value)
    return value


def formal_identity_sha256(identity: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(dict(identity))).hexdigest()


class Plan049RequestPreflight:
    """Reject policy/tool/slot drift before the proxy reserves or forwards."""

    def __init__(
        self, *, contract: CampaignContract, side: Side, task_id: str
    ) -> None:
        self._contract = contract
        self._side = side
        self._task_id = task_id
        self._observed: list[dict[str, Any]] = []

    def register(
        self,
        *,
        task_id: str,
        role: str,
        side: Side,
        request: Mapping[str, Any],
    ) -> None:
        if task_id != self._task_id or side is not self._side:
            raise FormalError("Plan 049 paid request slot binding differs")
        if role not in {"main", "guardian"} or not isinstance(request, Mapping):
            raise FormalError("Plan 049 paid request role is invalid")
        if role == "main":
            tools = collect_registered_tool_names(dict(request))
            if not _REQUIRED_TOOLS.issubset(tools):
                raise FormalError("Plan 049 paid request lacks common V2 tools")
            if not _contains_exact_string(request, self._contract.policy):
                raise FormalError("Plan 049 paid request lacks the frozen policy")
        self._observed.append(
            {
                "sequence": len(self._observed) + 1,
                "side": side.value,
                "task_id": task_id,
                "role": role,
                "full_request_sha256": canonical_request_sha256(dict(request)),
                "policy_sha256": (
                    self._contract.policy_sha256 if role == "main" else None
                ),
            }
        )

    def digest(self) -> str:
        if not self._observed or not any(
            row["role"] == "main" for row in self._observed
        ):
            raise FormalError("Plan 049 paid request preflight observed no main request")
        value = {"schema_version": 1, "observed": self._observed}
        assert_body_free(value)
        return hashlib.sha256(_canonical(value)).hexdigest()


class FormalStore:
    def __init__(
        self,
        paths: FormalPaths,
        identity: Mapping[str, Any],
        *,
        create: bool = True,
    ) -> None:
        self.paths = paths
        self.identity = dict(identity)
        self.identity_sha256 = formal_identity_sha256(self.identity)
        self._prepare(create=create)

    def ensure_receipt(self) -> None:
        ensure_formal_receipt(self.paths.receipt, self.identity)

    def require_receipt(self) -> None:
        require_formal_receipt(self.paths.receipt, self.identity)

    def records(self) -> tuple[dict[str, Any], ...]:
        self.require_receipt()
        if not self.paths.archive.exists():
            return ()
        _regular(self.paths.archive, "formal archive")
        rows: list[dict[str, Any]] = []
        try:
            lines = self.paths.archive.read_text("utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise FormalError("Plan 049 formal archive is unreadable") from exc
        for line in lines:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise FormalError("Plan 049 formal archive is invalid JSONL") from exc
            self.validate_record(row)
            rows.append(row)
        _validate_record_sequence(rows)
        return tuple(rows)

    def append(self, record: Mapping[str, Any]) -> None:
        row = dict(record)
        self.validate_record(row)
        existing = self.records()
        for old in existing:
            if old["run_id"] == row["run_id"]:
                if old == row:
                    return
                raise FormalError("Plan 049 formal run identity drifted")
        payload = _canonical(row) + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.paths.archive, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def marker(self, run_id: str) -> dict[str, Any] | None:
        path = self.run_root(run_id) / "run.json"
        if not path.exists() and not path.is_symlink():
            return None
        row = _read_json(path, "formal run publication marker")
        self.validate_record(row)
        if row["run_id"] != run_id:
            raise FormalError("Plan 049 formal publication marker identity differs")
        return row

    def execution(
        self, run_id: str, *, slot: Slot, attempt: int
    ) -> FormalExecutionResult | None:
        path = self.run_root(run_id) / "execution.json"
        if not path.exists() and not path.is_symlink():
            return None
        value = _read_json(path, "formal execution checkpoint")
        expected = {
            "schema_version": 1,
            "evidence_kind": "real_api",
            "identity_class": "paid",
            "formal_identity_sha256": self.identity_sha256,
            "lock_id": self.identity["lock_id"],
            "lock_sha256": self.identity["lock_sha256"],
            "policy_sha256": self.identity["policy_sha256"],
            "taskset_sha256": self.identity["taskset_sha256"],
            "slot_id": slot.slot_id,
            "run_id": run_id,
            "attempt": attempt,
        }
        if not isinstance(value, dict) or any(
            value.get(key) != item for key, item in expected.items()
        ):
            raise FormalError("Plan 049 formal execution checkpoint identity differs")
        result_keys = {
            "outcome",
            "trace_status",
            "team_view_sha256",
            "team_report_sha256",
            "request_preflight_sha256",
            "reason_code",
        }
        if set(value) != {*expected, *result_keys}:
            raise FormalError("Plan 049 formal execution checkpoint shape differs")
        result = FormalExecutionResult(
            outcome=value["outcome"],
            trace_status=value["trace_status"],
            team_view_sha256=value["team_view_sha256"],
            team_report_sha256=value["team_report_sha256"],
            request_preflight_sha256=value["request_preflight_sha256"],
            reason_code=value["reason_code"],
        )
        _validate_execution_result(result)
        view = self.run_root(run_id) / "team_view.json"
        report = self.run_root(run_id) / "team_report.html"
        if (
            hashlib.sha256(_read_regular_bytes(view, "formal Team View")).hexdigest()
            != result.team_view_sha256
            or hashlib.sha256(
                _read_regular_bytes(report, "formal Team report")
            ).hexdigest()
            != result.team_report_sha256
        ):
            raise FormalError("Plan 049 formal execution artifacts differ")
        return result

    def write_execution(
        self,
        run_id: str,
        *,
        slot: Slot,
        attempt: int,
        result: FormalExecutionResult,
    ) -> None:
        _validate_execution_result(result)
        value = {
            "schema_version": 1,
            "evidence_kind": "real_api",
            "identity_class": "paid",
            "formal_identity_sha256": self.identity_sha256,
            "lock_id": self.identity["lock_id"],
            "lock_sha256": self.identity["lock_sha256"],
            "policy_sha256": self.identity["policy_sha256"],
            "taskset_sha256": self.identity["taskset_sha256"],
            "slot_id": slot.slot_id,
            "run_id": run_id,
            "attempt": attempt,
            "outcome": result.outcome,
            "trace_status": result.trace_status,
            "team_view_sha256": result.team_view_sha256,
            "team_report_sha256": result.team_report_sha256,
            "request_preflight_sha256": result.request_preflight_sha256,
            "reason_code": result.reason_code,
        }
        assert_body_free(value)
        _write_or_verify(self.run_root(run_id) / "execution.json", _canonical(value) + b"\n")

    def publish(self, record: Mapping[str, Any]) -> None:
        row = dict(record)
        self.validate_record(row)
        root = self.run_root(str(row["run_id"]))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _write_or_verify(root / "run.json", _canonical(row) + b"\n")

    def run_root(self, run_id: str) -> Path:
        if _RUN_ID.fullmatch(run_id) is None:
            raise FormalError("Plan 049 formal run id is invalid")
        return self.paths.runs / run_id

    def write_aggregate(self, value: Mapping[str, Any]) -> None:
        assert_body_free(value)
        _write_atomic(self.paths.aggregate, _canonical(dict(value)) + b"\n")

    def validate_record(self, value: object) -> None:
        if not isinstance(value, dict) or set(value) != _RECORD_KEYS:
            raise FormalError("Plan 049 formal record shape differs")
        assert_body_free(value)
        outcome = value.get("outcome")
        terminal = outcome in _TERMINAL
        if (
            value.get("schema_version") != 1
            or value.get("evidence_kind") != "real_api"
            or value.get("identity_class") != "paid"
            or value.get("formal_identity_sha256") != self.identity_sha256
            or value.get("budget_run_id") != value.get("run_id")
            or _RUN_ID.fullmatch(str(value.get("run_id"))) is None
            or value.get("side") not in {"codex", "rondo"}
            or value.get("product")
            != (None if value.get("side") == "codex" else "rondo-multi")
            or outcome not in _OUTCOMES
            or value.get("terminal") is not terminal
            or value.get("counts_as_effective") is not terminal
            or isinstance(value.get("attempt"), bool)
            or not isinstance(value.get("attempt"), int)
            or not 1 <= value["attempt"] <= 5
            or isinstance(value.get("request_count"), bool)
            or not isinstance(value.get("request_count"), int)
            or value["request_count"] < 0
        ):
            raise FormalError("Plan 049 formal record identity is invalid")
        if terminal and value.get("trace_status") not in {"available", "partial"}:
            raise FormalError("Plan 049 terminal paid record lacks trace evidence")
        if not terminal and value.get("trace_status") not in {"missing", "partial"}:
            raise FormalError("Plan 049 infra paid record trace status is invalid")
        for key in ("lock_id", "lock_sha256", "policy_sha256", "taskset_sha256"):
            if value.get(key) != self.identity.get(key):
                raise FormalError(f"Plan 049 formal record {key} differs")

    def _prepare(self, *, create: bool) -> None:
        root = self.paths.root
        eval_data = root.parents[2]
        if eval_data.name != "eval-data":
            raise FormalError("Plan 049 formal root escaped eval-data")
        if eval_data.exists() and (eval_data.is_symlink() or not eval_data.is_dir()):
            raise FormalError("Plan 049 eval-data root is unsafe")
        if create:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.paths.runs.mkdir(exist_ok=True, mode=0o700)
        elif (
            root.is_symlink()
            or not root.is_dir()
            or self.paths.runs.is_symlink()
            or not self.paths.runs.is_dir()
        ):
            raise FormalError("Plan 049 existing formal root is unsafe")
        if root.is_symlink() or not root.resolve().is_relative_to(eval_data.resolve()):
            raise FormalError("Plan 049 formal root is unsafe")


def require_safe_formal_prefix(
    paths: FormalPaths,
    identity: Mapping[str, Any],
    contract: CampaignContract,
) -> None:
    """Read-only validation before Docker, secret loading, or state creation."""

    if not paths.root.exists() and not paths.root.is_symlink():
        return
    store = FormalStore(paths, identity, create=False)
    run_entries = list(paths.runs.iterdir())
    material_state = (
        paths.ledger.exists()
        or paths.ledger.is_symlink()
        or paths.archive.exists()
        or paths.archive.is_symlink()
        or paths.aggregate.exists()
        or paths.aggregate.is_symlink()
        or bool(run_entries)
    )
    if not paths.receipt.exists() and not paths.receipt.is_symlink():
        if material_state:
            raise FormalError("Plan 049 formal state exists without a receipt")
        return
    store.require_receipt()
    records = list(store.records())
    schedule = slots(contract)
    _validate_paid_prefix(records, schedule)
    allowed_ids = {
        slot.run_id(attempt).replace("rehearsal", "paid")
        for slot in schedule
        for attempt in range(1, 6)
    }
    _require_known_run_roots(store, allowed_ids)
    if not paths.ledger.exists() and not paths.ledger.is_symlink():
        if (
            records
            or run_entries
            or paths.archive.exists()
            or paths.archive.is_symlink()
            or paths.aggregate.exists()
            or paths.aggregate.is_symlink()
        ):
            raise FormalError("Plan 049 formal artifacts exist without a ledger")
        return
    ledger = _read_json(paths.ledger, "formal budget ledger")
    budget = contract.lock["budget"]
    runs = ledger.get("runs")
    if (
        ledger.get("schema_version") != 1
        or ledger.get("batch_id") != budget["batch_id"]
        or Decimal(str(ledger.get("total_cap_usd")))
        != Decimal(str(budget["phase_b_hard_cap_usd"]))
        or ledger.get("max_runs") != budget["max_run_slots"]
        or Decimal(str(ledger.get("default_run_cap_usd")))
        != Decimal(str(budget["per_run_cap_usd"]))
        or not isinstance(runs, dict)
        or any(run_id not in allowed_ids for run_id in runs)
    ):
        raise FormalError("Plan 049 formal ledger identity differs")
    archived = {row["run_id"] for row in records}
    if any(run_id not in runs for run_id in archived):
        raise FormalError("Plan 049 formal archive names an unclaimed run")
    unarchived = sorted(set(runs) - archived)
    if len(unarchived) > 1:
        raise FormalError("Plan 049 formal ledger has conflicting unarchived runs")
    expected_unarchived: str | None = None
    for slot in schedule:
        slot_rows = [row for row in records if row["slot_id"] == slot.slot_id]
        if any(row["terminal"] is True for row in slot_rows):
            continue
        expected_unarchived = slot.run_id(len(slot_rows) + 1).replace(
            "rehearsal", "paid"
        )
        break
    if unarchived and unarchived != [expected_unarchived]:
        raise FormalError("Plan 049 formal ledger unarchived run is not next")
    assert_body_free(ledger)


class Plan049TerminalBenchExecutor:
    """One real slot through the existing proxy, Harbor runner and Team Lens."""

    def __init__(
        self,
        *,
        contract: CampaignContract,
        common_root: Path,
        repo_root: Path,
        ledger: PersistentBudgetLedger,
        api_key: str,
        counter: DockerCounter,
        lock_guard: HeavyLockGuard,
        lease: HeavyLockLease,
        config: RuntimeConfig | None = None,
        materializer: TaskMaterializer | None = None,
        formal_identity_sha256: str | None = None,
    ) -> None:
        self.contract = contract
        self.common_root = Path(common_root).resolve()
        self.repo_root = Path(repo_root).resolve()
        self.paths = RepoPaths(self.common_root, self.repo_root)
        self.config = config or load_runtime_config(self.paths)
        self.provider = plan049_provider_projection(self.config, contract)
        self.ledger = ledger
        self.api_key = api_key
        self.counter = counter
        self.lock_guard = lock_guard
        self.lease = lease
        self.materializer = materializer
        self.formal_identity_sha256 = formal_identity_sha256
        self.runtime = load_runtime_identity(
            self.repo_root / contract.lock["runtime"]["lock"],
            require_frozen=True,
            common_root=self.common_root,
        )
        self.catalog = load_successor_canary_catalog(self.paths)

    def build_request(self, slot: Slot, *, run_id: str) -> TerminalBenchRequest:
        side = Side(slot.side)
        task = self.catalog.task(slot.task_id)
        manifest = load_side_manifest(self.runtime, side, common_root=self.common_root)
        seccomp = self.repo_root / _SECCOMP_RELPATH
        if (
            seccomp.is_symlink()
            or not seccomp.is_file()
            or hashlib.sha256(seccomp.read_bytes()).hexdigest()
            != _SECCOMP_SOURCE_SHA256
        ):
            raise FormalError("Plan 049 seccomp profile differs")
        run_root = formal_paths(self.common_root, self.contract).runs / run_id
        return TerminalBenchRequest(
            side=side,
            batch_id=str(self.contract.lock["budget"]["batch_id"]),
            binary=manifest,
            product=None if side is Side.CODEX else Product.RONDO_MULTI,
            image_digest=task.image_digest,
            source_checkout=str(
                self.common_root / "eval-data" / "sources" / SOURCE_DIRECTORY
            ),
            staging_root=str(run_root / "staging"),
            docker_task_id=run_id,
            memory_bytes=task.memory_mb * 1024**2,
            memory_swap_bytes=(task.memory_mb + 1024) * 1024**2,
            pids_limit=task.pids_limit,
            provider_transport_base_url="http://host.docker.internal:9/v1",
            provider_name=str(self.contract.lock["provider"]["name"]),
            timeout_seconds=task.timeout_seconds,
            max_retries=0,
            budget_usd=float(run_cap_usd(self.contract)),
            seccomp_profile_path=str(seccomp),
            seccomp_profile_source_sha256=_SECCOMP_SOURCE_SHA256,
            seccomp_profile_effective_sha256=_SECCOMP_EFFECTIVE_SHA256,
            require_container_metrics=True,
            frozen_task=task,
            team_state_enabled=True,
            pinned_model_id=str(self.contract.lock["provider"]["root_model"]),
            pinned_subagent_model=str(
                self.contract.lock["provider"]["member_model"]
            ),
            pinned_subagent_effort=str(
                self.contract.lock["provider"]["member_effort"]
            ),
            common_multi_agent_v2=True,
            multi_agent_max_concurrency=int(
                self.contract.lock["execution"][
                    "max_concurrent_threads_per_session"
                ]
            ),
            developer_instructions_path=str(
                self.repo_root / self.contract.lock["policy"]["path"]
            ),
            developer_instructions_sha256=self.contract.policy_sha256,
            rollout_trace_root=str(
                self.contract.lock["execution"]["rollout_trace_root"]
            ),
        )

    def execute(
        self, slot: Slot, *, attempt: int, run_id: str, run_root: Path
    ) -> FormalExecutionResult:
        # Refuse before preparing Docker or forwarding a request if this
        # executor was not bound to the already-created formal receipt.
        _require_sha256(
            self.formal_identity_sha256,
            "Plan 049 formal executor lacks receipt identity",
        )
        request = self.build_request(slot, run_id=run_id)
        preflight = Plan049RequestPreflight(
            contract=self.contract, side=request.side, task_id=slot.task_id
        )

        def project_request(value: TerminalBenchRequest) -> TerminalBenchRequest:
            sources = {
                "upstream": str(self.runtime.baseline["source_commit"]),
                "rondo": self.runtime.source_commit,
            }
            if value.binary.source_commit != sources[
                "upstream" if value.side is Side.CODEX else "rondo"
            ]:
                raise FormalError("Plan 049 binary/catalog provenance differs")
            shared = load_shared_model_catalog(
                self.common_root,
                upstream_source_commit=sources["upstream"],
                rondo_source_commit=sources["rondo"],
                main_model=self.provider.main_model,
                guardian_model=self.provider.guardian_model,
                product=Product.RONDO_MULTI,
            )
            catalog_path = run_root / "shared-model-catalog.json"
            run_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            shared.write_private(catalog_path)
            return replace(
                value,
                frozen_model_catalog_path=str(catalog_path),
                frozen_model_catalog_sha256=shared.sha256,
                frozen_model_catalog_provenance_sha256=canonical_request_sha256(
                    shared.identity()
                ),
            )

        def validate_prepared(prepared: PreparedTerminalBenchRun) -> None:
            adapter = prepared.adapter
            if (
                prepared.spec.side is not request.side
                or prepared.spec.task_id != slot.task_id
                or prepared.spec.provider.main_model
                != self.contract.lock["provider"]["root_model"]
                or adapter._common_multi_agent_v2 is not True
                or adapter._multi_agent_max_concurrency
                != self.contract.lock["execution"][
                    "max_concurrent_threads_per_session"
                ]
                or adapter._subagent_model
                != self.contract.lock["provider"]["member_model"]
                or adapter._subagent_effort
                != self.contract.lock["provider"]["member_effort"]
                or adapter._developer_instructions_sha256
                != self.contract.policy_sha256
                or adapter._rollout_trace_root
                != self.contract.lock["execution"]["rollout_trace_root"]
            ):
                raise FormalError("Plan 049 prepared run differs from common V2")

        try:
            result = asyncio.run(
                run_budgeted_terminal_bench_core(
                    self.config,
                    request,
                    api_key=self.api_key,
                    ledger=RequestCappedLedger(
                        self.ledger,
                        max_requests_per_run=int(
                            self.contract.lock["provider"]["request_limit_per_run"]
                        ),
                    ),
                    metadata_path=run_root / "api-metadata.json",
                    counter=self.counter,
                    lock_guard=self.lock_guard,
                    lease=self.lease,
                    provider=self.provider,
                    max_guardian_logical_requests=int(
                        self.contract.lock["budget"][
                            "max_guardian_logical_requests"
                        ]
                    ),
                    timeout_seconds=90.0,
                    request_preflight=preflight,
                    preflight_task_id=slot.task_id,
                    project_request=project_request,
                    validate_prepared=validate_prepared,
                    retry_backoff_seconds=float(
                        self.contract.lock["provider"]["retry_backoff_seconds"]
                    ),
                    request_reservation_usd=request_reservation_usd(self.contract),
                    run_cap_usd=run_cap_usd(self.contract),
                    max_concurrent_main=int(
                        self.contract.lock["budget"][
                            "max_concurrent_main_requests"
                        ]
                    ),
                    usage_envelope=usage_envelope(self.contract),
                    materializer=self.materializer,
                )
            )
            stopped = run_stop_reason(self.ledger, run_id)
            if stopped is not None:
                if stopped in {
                    REQUEST_LIMIT_STOP_REASON,
                    "guardian_logical_request_limit_exceeded",
                }:
                    raise FormalError(f"paid request path stopped: {stopped}")
                if stop_reason_class(stopped) == "budget":
                    raise BudgetStopped(stopped)
                raise FormalError(f"paid request path stopped: {stopped}")
            if run_infra_taint(self.ledger, run_id) is not None:
                raise FormalError("paid request path has provider infra taint")
            parsed = parse_single_task_result(
                result.harbor.trial_dir,
                host_returncode=result.harbor.returncode,
                expected_task_id=slot.task_id,
            )
            if parsed.outcome is RunOutcome.INFRA_FAILED:
                raise FormalError("Terminal-Bench returned an infra outcome")
            trace_root = result.harbor.trial_dir / "agent" / "rollout-trace"
            bundle = find_trace_bundle(trace_root)
            view = reduce_bundle(
                bundle, "codex" if slot.side == "codex" else "rondo-multi"
            )
            validate_team_view(view)
            view_bytes = dump_team_view(view)
            report_bytes = render_report(view)
            _write_or_verify(run_root / "team_view.json", view_bytes)
            _write_or_verify(run_root / "team_report.html", report_bytes)
        except (ApiBudgetProxyError, HarborResultError, TerminalBenchRunError) as exc:
            raise FormalError(str(exc)) from exc
        if parsed.outcome is RunOutcome.COMPLETED:
            outcome = "completed" if parsed.reward > 0 else "task_failed"
        else:
            outcome = "product_failed"
        formal_result = FormalExecutionResult(
            outcome=outcome,
            trace_status="available",
            team_view_sha256=hashlib.sha256(view_bytes).hexdigest(),
            team_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
            request_preflight_sha256=preflight.digest(),
            reason_code=(
                None
                if outcome == "completed"
                else (
                    "task_native_verifier_failed"
                    if outcome == "task_failed"
                    else "product_terminal_failure"
                )
            ),
        )
        _write_execution_file(
            run_root,
            formal_result,
            formal_identity_sha256=self.formal_identity_sha256,
            contract=self.contract,
            slot=slot,
            attempt=attempt,
            run_id=run_id,
        )
        return formal_result


def run_formal_campaign(
    contract: CampaignContract,
    *,
    store: FormalStore,
    ledger: PersistentBudgetLedger,
    executor: FormalExecutor,
    phase: str,
) -> dict[str, Any]:
    """Advance pilot or formal slots without ever repeating a requested run."""

    if phase not in {"pilot", "formal"}:
        raise FormalError("Plan 049 paid phase is invalid")
    store.require_receipt()
    schedule = slots(contract)
    allowed_ids = {
        slot.run_id(attempt).replace("rehearsal", "paid")
        for slot in schedule
        for attempt in range(1, 6)
    }
    _require_known_run_roots(store, allowed_ids)
    records = list(store.records())
    # run.json is the atomic publication marker. If JSONL append was the only
    # interrupted operation, repair it before looking at the ledger.
    archived_ids = {row["run_id"] for row in records}
    for run_id in sorted(allowed_ids):
        marker = store.marker(run_id)
        if marker is not None and run_id not in archived_ids:
            store.append(marker)
            records.append(marker)
            archived_ids.add(run_id)
    records = list(store.records())
    _validate_paid_prefix(records, schedule)
    try:
        require_archived_runs_in_ledger(records, ledger)
    except ResumeError as exc:
        raise FormalError(str(exc)) from exc
    if phase == "formal":
        _require_pilot_activation(contract, records, store)

    infra_total = sum(row["outcome"] == "infra_failed" for row in records)
    for slot in schedule:
        if slot.phase != phase:
            continue
        slot_rows = [row for row in records if row["slot_id"] == slot.slot_id]
        if any(row["terminal"] is True for row in slot_rows):
            continue
        for attempt in range(len(slot_rows) + 1, 6):
            if infra_total >= int(
                contract.lock["recovery"]["max_infra_attempts_total"]
            ):
                return _formal_aggregate(contract, records, store)
            run_id = slot.run_id(attempt).replace("rehearsal", "paid")
            checkpoint = store.execution(run_id, slot=slot, attempt=attempt)
            if checkpoint is not None:
                if run_id not in ledger.snapshot().get("runs", {}):
                    raise FormalError(
                        "Plan 049 execution checkpoint has no budget run"
                    )
                row = _formal_record(
                    contract,
                    store,
                    ledger,
                    slot,
                    attempt,
                    run_id,
                    outcome=checkpoint.outcome,
                    trace_status=checkpoint.trace_status,
                    team_view_sha256=checkpoint.team_view_sha256,
                    team_report_sha256=checkpoint.team_report_sha256,
                    request_preflight_sha256=checkpoint.request_preflight_sha256,
                    reason_code=checkpoint.reason_code,
                )
                _publish_and_append(store, row)
                records.append(row)
                break
            try:
                require_single_unarchived_run(
                    records, ledger, expected_run_id=run_id
                )
                disposition = claimed_run_disposition(
                    ledger,
                    run_id,
                    cap_usd=run_cap_usd(contract),
                    verified_owned_artifacts=False,
                )
            except ResumeError as exc:
                raise FormalError(str(exc)) from exc
            if disposition.kind == "terminal_budget":
                row = _formal_record(
                    contract,
                    store,
                    ledger,
                    slot,
                    attempt,
                    run_id,
                    outcome="budget_stopped",
                    trace_status="missing",
                    reason_code=disposition.stop_reason or "budget_stopped",
                )
                _publish_and_append(store, row)
                records.append(row)
                return _formal_aggregate(contract, records, store)
            if disposition.kind in {"abandon", "abandon_pristine"}:
                row = _formal_record(
                    contract,
                    store,
                    ledger,
                    slot,
                    attempt,
                    run_id,
                    outcome="infra_failed",
                    trace_status="missing",
                    reason_code="resume_requested_run_without_publication",
                )
                _publish_and_append(store, row)
                records.append(row)
                infra_total += 1
                continue
            if disposition.kind == "new":
                try:
                    ledger.claim_run(run_id, cap_usd=run_cap_usd(contract))
                except BudgetStopped as exc:
                    raise FormalError(str(exc)) from exc
            try:
                result = executor.execute(
                    slot,
                    attempt=attempt,
                    run_id=run_id,
                    run_root=store.run_root(run_id),
                )
                if result.outcome not in _TERMINAL:
                    raise FormalError("Plan 049 executor returned a non-terminal result")
                store.write_execution(
                    run_id, slot=slot, attempt=attempt, result=result
                )
                row = _formal_record(
                    contract,
                    store,
                    ledger,
                    slot,
                    attempt,
                    run_id,
                    outcome=result.outcome,
                    trace_status=result.trace_status,
                    team_view_sha256=result.team_view_sha256,
                    team_report_sha256=result.team_report_sha256,
                    request_preflight_sha256=result.request_preflight_sha256,
                    reason_code=result.reason_code,
                )
            except DockerResourceStop:
                row = _formal_record(
                    contract,
                    store,
                    ledger,
                    slot,
                    attempt,
                    run_id,
                    outcome="infra_failed",
                    trace_status="missing",
                    reason_code="docker_resource_stop",
                )
                _publish_and_append(store, row)
                records.append(row)
                return _formal_aggregate(contract, records, store)
            except BudgetStopped as exc:
                row = _formal_record(
                    contract,
                    store,
                    ledger,
                    slot,
                    attempt,
                    run_id,
                    outcome="budget_stopped",
                    trace_status="missing",
                    reason_code=str(exc) or "budget_stopped",
                )
                _publish_and_append(store, row)
                records.append(row)
                return _formal_aggregate(contract, records, store)
            except Exception:
                row = _formal_record(
                    contract,
                    store,
                    ledger,
                    slot,
                    attempt,
                    run_id,
                    outcome="infra_failed",
                    trace_status="missing",
                    reason_code="paid_executor_failed",
                )
                _publish_and_append(store, row)
                records.append(row)
                infra_total += 1
                continue
            _publish_and_append(store, row)
            records.append(row)
            break
    return _formal_aggregate(contract, records, store)


def _formal_record(
    contract: CampaignContract,
    store: FormalStore,
    ledger: PersistentBudgetLedger,
    slot: Slot,
    attempt: int,
    run_id: str,
    *,
    outcome: str,
    trace_status: str,
    reason_code: str | None,
    team_view_sha256: str | None = None,
    team_report_sha256: str | None = None,
    request_preflight_sha256: str | None = None,
) -> dict[str, Any]:
    run = ledger.snapshot().get("runs", {}).get(run_id, {})
    spent = str(run.get("spent_usd", "0.00")) if isinstance(run, dict) else "0.00"
    requests = run.get("requests", {}) if isinstance(run, dict) else {}
    request_count = len(requests) if isinstance(requests, dict) else 0
    terminal = outcome in _TERMINAL
    return {
        "schema_version": 1,
        "evidence_kind": "real_api",
        "identity_class": "paid",
        "formal_identity_sha256": store.identity_sha256,
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "policy_sha256": contract.policy_sha256,
        "taskset_sha256": contract.taskset_sha256,
        "phase": slot.phase,
        "pair_id": slot.pair_id,
        "slot_id": slot.slot_id,
        "run_id": run_id,
        "budget_run_id": run_id,
        "attempt": attempt,
        "task_id": slot.task_id,
        "side": slot.side,
        "product": None if slot.side == "codex" else "rondo-multi",
        "outcome": outcome,
        "terminal": terminal,
        "counts_as_effective": terminal,
        "cost_usd": spent,
        "request_count": request_count,
        "trace_status": trace_status,
        "team_view_sha256": team_view_sha256,
        "team_report_sha256": team_report_sha256,
        "request_preflight_sha256": request_preflight_sha256,
        "reason_code": reason_code,
    }


def _publish_and_append(store: FormalStore, row: Mapping[str, Any]) -> None:
    store.publish(row)
    store.append(row)


def _validate_execution_result(result: FormalExecutionResult) -> None:
    if (
        not isinstance(result, FormalExecutionResult)
        or result.outcome not in _TERMINAL
        or result.trace_status not in {"available", "partial"}
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in (
                result.team_view_sha256,
                result.team_report_sha256,
                result.request_preflight_sha256,
            )
        )
        or (result.reason_code is not None and not isinstance(result.reason_code, str))
    ):
        raise FormalError("Plan 049 formal execution result is invalid")


def _require_sha256(value: object, message: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise FormalError(message)
    return value


def _write_execution_file(
    run_root: Path,
    result: FormalExecutionResult,
    *,
    formal_identity_sha256: str | None,
    contract: CampaignContract,
    slot: Slot,
    attempt: int,
    run_id: str,
) -> None:
    """Actual executor checkpoint, written before control returns to orchestration."""

    _validate_execution_result(result)
    formal_identity_sha256 = _require_sha256(
        formal_identity_sha256,
        "Plan 049 formal executor lacks receipt identity",
    )
    value = {
        "schema_version": 1,
        "evidence_kind": "real_api",
        "identity_class": "paid",
        "formal_identity_sha256": formal_identity_sha256,
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "policy_sha256": contract.policy_sha256,
        "taskset_sha256": contract.taskset_sha256,
        "slot_id": slot.slot_id,
        "run_id": run_id,
        "attempt": attempt,
        "outcome": result.outcome,
        "trace_status": result.trace_status,
        "team_view_sha256": result.team_view_sha256,
        "team_report_sha256": result.team_report_sha256,
        "request_preflight_sha256": result.request_preflight_sha256,
        "reason_code": result.reason_code,
    }
    assert_body_free(value)
    _write_or_verify(run_root / "execution.json", _canonical(value) + b"\n")


def _formal_aggregate(
    contract: CampaignContract,
    records: list[dict[str, Any]],
    store: FormalStore,
) -> dict[str, Any]:
    views: dict[str, dict[str, Any]] = {}
    for row in records:
        if row["terminal"] is not True:
            continue
        value = _read_json(
            store.run_root(row["run_id"]) / "team_view.json", "formal Team View"
        )
        assert_body_free(value)
        validate_team_view(value)
        views[row["run_id"]] = value
    value = aggregate(
        records,
        views,
        lock_id=contract.lock_id,
        lock_sha256=contract.lock_sha256,
        policy_sha256=contract.policy_sha256,
        expected_slots={slot.slot_id: slot.pair_id for slot in slots(contract)},
        evidence_kind="real_api",
        identity_class="paid",
    )
    store.write_aggregate(value)
    return value


def _require_pilot_activation(
    contract: CampaignContract,
    records: list[dict[str, Any]],
    store: FormalStore,
) -> None:
    pilot_slots = [slot for slot in slots(contract) if slot.phase == "pilot"]
    pilot = [row for row in records if row["phase"] == "pilot" and row["terminal"]]
    if len(pilot) != len(pilot_slots):
        raise FormalError("Plan 049 formal phase requires six terminal pilot runs")
    result = _formal_aggregate(contract, records, store)
    if result["activation_observed"] is not True:
        raise FormalError("Plan 049 pilot did not observe a Root-owned spawn")


def _validate_paid_prefix(records: list[dict[str, Any]], schedule: tuple[Slot, ...]) -> None:
    order = {slot.slot_id: index for index, slot in enumerate(schedule)}
    previous = -1
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        slot_order = order.get(str(row["slot_id"]))
        if slot_order is None or slot_order < previous:
            raise FormalError("Plan 049 formal archive is not a schedule prefix")
        previous = slot_order
        grouped.setdefault(str(row["slot_id"]), []).append(row)
    gap = False
    for slot in schedule:
        rows = grouped.get(slot.slot_id, [])
        if gap and rows:
            raise FormalError("Plan 049 formal archive skips an earlier slot")
        attempts = [row["attempt"] for row in rows]
        if attempts != list(range(1, len(rows) + 1)):
            raise FormalError("Plan 049 formal attempts are not contiguous")
        terminals = [row for row in rows if row["terminal"] is True]
        if len(terminals) > 1 or (terminals and terminals[0] is not rows[-1]):
            raise FormalError("Plan 049 formal archive continues after terminal")
        if not terminals:
            gap = True


def _validate_record_sequence(records: list[dict[str, Any]]) -> None:
    run_ids: set[str] = set()
    terminal_slots: set[str] = set()
    for row in records:
        if row["run_id"] in run_ids:
            raise FormalError("Plan 049 formal archive repeats a run id")
        run_ids.add(row["run_id"])
        if row["terminal"]:
            if row["slot_id"] in terminal_slots:
                raise FormalError("Plan 049 formal archive repeats a terminal slot")
            terminal_slots.add(row["slot_id"])


def _require_known_run_roots(store: FormalStore, allowed: set[str]) -> None:
    for child in store.paths.runs.iterdir():
        if child.name not in allowed or child.is_symlink() or not child.is_dir():
            raise FormalError("Plan 049 formal runs root contains an unknown entry")


def _contains_exact_string(value: object, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, Mapping):
        return any(_contains_exact_string(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_exact_string(item, expected) for item in value)
    return False


def _read_json(path: Path, label: str) -> dict[str, Any]:
    _regular(path, label)
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FormalError(f"Plan 049 {label} is unreadable") from exc
    if not isinstance(value, dict):
        raise FormalError(f"Plan 049 {label} is invalid")
    return value


def _regular(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise FormalError(f"Plan 049 {label} is unsafe")


def _read_regular_bytes(path: Path, label: str) -> bytes:
    _regular(path, label)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise FormalError(f"Plan 049 {label} is unreadable") from exc


def _write_or_verify(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise FormalError("Plan 049 formal artifact drifted")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        _regular(path, "formal state file")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
