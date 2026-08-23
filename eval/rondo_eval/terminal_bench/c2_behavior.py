"""Plan 058 C2 commissioning/diagnostic/formal campaign contract.

This module owns only Plan 058 identity, crash-safe logical-slot state, the
typed whole-slot transport retry decision, and body-free publication.  Docker,
Terminal-Bench, API accounting, native traces, and task-budget envelopes stay
owned by their existing shared modules.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from ..api_budget_proxy import (
    MAX_INPUT_TOKENS,
    MAX_OUTPUT_TOKENS,
    UsageEnvelope,
    maximum_usage_cost,
)
from ..config import RepoPaths, RuntimeConfig, load_runtime_config
from ..contracts import (
    BinaryManifest,
    ModelPricing,
    Product,
    ProviderProjection,
    RunOutcome,
)
from ..harness_observation import validate_task_observation
from .__main__ import _load_manifest
from .baseline import CampaignIdentity, load_historical_campaign_identity
from .bounded_observation import (
    _atomic_json,
    _git,
    _git_result,
    _read_json,
    _read_regular,
    _validate_binary_source_relation,
)
from .task_budget import (
    TaskBudgetIdentity,
    activate_closed_task_budget,
    close_task_budget,
    load_task_budget,
    start_task_budget,
    task_budget_path,
    task_budget_status,
    verify_active_identity,
)
from .tasksets import FrozenTask


PLAN058_KIND = "rondo_direction1_c2_behavior"
PLAN058_SCHEMA_VERSION = 1
PLAN058_POINTER_RELPATH = Path("eval/locks/plan058-direction1-c2-active.json")
PLAN058_V28_RELPATH = Path("eval/locks/p2-b7-canary-baseline-v28.json")
PLAN058_V28_SHA256 = (
    "a9567cb0ddeaa9c8e7cdfbd7253000a8453ec1ebbb03ca359deae2c048f7880b"
)
PLAN058_TASK_BUDGET_ID = "plan-058-direction1-c2-behavior"
PLAN058_TASK_CAP_USD = Decimal("50.000000")
PLAN058_PHYSICAL_RUN_BUDGET_USD = Decimal("40.000000")
PLAN058_UNPRICED_FALLBACK_USD = Decimal("1.000000")
PLAN058_MODEL = "gpt-5.6-terra"
PLAN058_MAIN_EFFORT = "medium"
PLAN058_GUARDIAN_EFFORT = "low"
PLAN058_FORMAL_TASKS = 10
PLAN058_FORMAL_ROUNDS = 2
PLAN058_FORMAL_SLOTS = 20
PLAN058_FORMAL_EXECUTION_ORDER = (
    8,
    18,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    19,
    20,
)
PLAN058_LEGACY_FORMAL_V1_CAMPAIGN_ID = "plan058-direction1-c2-formal-v1"
PLAN058_LEGACY_FORMAL_V1_SHA256 = (
    "f23c6b8cf361112be60b484d8458324276f9bee63077e176386d1a29b5010d95"
)
PLAN058_DIAGNOSTIC_SLOT_MIN = 1
PLAN058_DIAGNOSTIC_SLOT_MAX = 20
PLAN058_OBSERVATION_SCHEMA_VERSION = 2
PLAN058_PAID_ACTION = "plan-058-authorized-paid-run"
PLAN058_REFINED_BASELINE = 1
PLAN058_REFINED_TARGET = 0

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_LOGICAL_RUN_ID = re.compile(
    r"(?P<date>20[0-9]{6})-(?P<sequence>[0-9]{9})-tb-rondo-plan058\Z"
)
_CAMPAIGN_PREFIX = "plan058-direction1-c2-"
_TERMINAL_STATUSES = frozenset({"ready_to_finalize", "invalid", "finalized"})
_SLOT_STATUSES = frozenset({"pending", "running", "retry_pending", "published"})
_TRANSIENT_HTTP_STATUSES = frozenset({408, 425, 500, 502, 503, 504})
_TRANSIENT_STREAM_ENDS = frozenset({"open_error", "read_error", "clean_eof"})
_TRANSIENT_TERMINAL_ERROR_CODES = frozenset({"upstream_error"})
_NON_TRANSIENT_CODE_FRAGMENTS = (
    "auth",
    "billing",
    "config",
    "context",
    "invalid",
    "model",
    "permission",
    "quota",
    "rate_limit",
    "usage_limit",
)


class C2BehaviorError(RuntimeError):
    """Plan 058 cannot advance without changing its frozen semantics."""


@dataclass(frozen=True)
class C2BehaviorSlot:
    slot_id: str
    logical_run_id: str
    round: int
    task_index: int
    task_id: str

    def validate(self, *, task_count: int, rounds: int) -> None:
        if (
            _SAFE_ID.fullmatch(self.slot_id) is None
            or _SAFE_ID.fullmatch(self.logical_run_id) is None
            or isinstance(self.round, bool)
            or not 1 <= self.round <= rounds
            or isinstance(self.task_index, bool)
            or not 1 <= self.task_index <= task_count
            or not isinstance(self.task_id, str)
            or not self.task_id.startswith("terminal-bench/")
        ):
            raise C2BehaviorError("Plan 058 slot identity is invalid")

    def attempt_run_id(self, attempt: int) -> str:
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise C2BehaviorError("Plan 058 physical attempt is invalid")
        value = f"{self.logical_run_id}-a{attempt}"
        if _SAFE_ID.fullmatch(value) is None:
            raise C2BehaviorError("Plan 058 physical run identity is invalid")
        return value


@dataclass(frozen=True)
class C2BehaviorIdentity:
    path: Path
    lock_sha256: str
    value: Mapping[str, Any]
    reference: CampaignIdentity
    tasks: tuple[FrozenTask, ...]
    slots: tuple[C2BehaviorSlot, ...]

    @property
    def campaign_id(self) -> str:
        return str(self.value["campaign_id"])

    @property
    def batch_id(self) -> str:
        return str(self.value["batch_id"])

    @property
    def campaign_mode(self) -> str:
        return str(self.value["campaign_mode"])

    @property
    def result_namespace(self) -> str:
        return str(self.value["result_namespace"])

    @property
    def harness_commit(self) -> str:
        return str(self.value["harness_commit"])

    @property
    def task_budget_id(self) -> str:
        return str(self.value["budget"]["task_budget_id"])

    @property
    def prior_settled_usd(self) -> Decimal:
        return Decimal(str(self.value["budget"]["prior_estimated_usd"]))

    @property
    def campaign_cap_usd(self) -> Decimal:
        return Decimal(str(self.value["budget"]["campaign_cap_usd"]))

    @property
    def request_reservation_usd(self) -> Decimal:
        return Decimal(
            str(self.value["budget"]["reliable_usage_request_reservation_usd"])
        )

    @property
    def usage_envelope(self) -> UsageEnvelope:
        value = self.value["budget"]["usage_envelope"]
        envelope = UsageEnvelope(
            max_input_tokens=int(value["max_input_tokens"]),
            max_output_tokens=int(value["max_output_tokens"]),
        )
        envelope.validate()
        return envelope

    @property
    def max_guardian_logical_requests(self) -> int:
        return int(self.value["provider"]["max_guardian_logical_requests"])

    @property
    def upstream_timeout_seconds(self) -> float:
        return float(self.value["provider"]["upstream_timeout_seconds"])

    @property
    def public_result_relative_path(self) -> str:
        return str(self.value["public_result_path"])

    def task(self, task_id: str) -> FrozenTask:
        matches = tuple(task for task in self.tasks if task.task_id == task_id)
        if len(matches) != 1:
            raise C2BehaviorError("Plan 058 task is not uniquely frozen")
        return matches[0]

    @property
    def preflight_tasks(self) -> tuple[FrozenTask, ...]:
        scheduled = {slot.task_id for slot in self.slots}
        return tuple(task for task in self.tasks if task.task_id in scheduled)

    @property
    def diagnostic_slot_range(self) -> tuple[int, int] | None:
        value = self.value.get("diagnostic_slot_range")
        if value is None:
            return None
        return int(value["start"]), int(value["end"])

    def slot(self, slot_id: str) -> C2BehaviorSlot:
        matches = tuple(slot for slot in self.slots if slot.slot_id == slot_id)
        if len(matches) != 1:
            raise C2BehaviorError("Plan 058 slot is not uniquely frozen")
        return matches[0]

    def provider_projection(self, config: RuntimeConfig) -> ProviderProjection:
        provider = config.paid_provider_projection(
            model_id=PLAN058_MODEL,
            main_effort=PLAN058_MAIN_EFFORT,
            guardian_effort=PLAN058_GUARDIAN_EFFORT,
        )
        if provider.to_public_dict() != self.value["provider"]["public_profile"]:
            raise C2BehaviorError("Plan 058 provider profile drifted")
        return provider

    def manifest(self, paths: RepoPaths) -> BinaryManifest:
        manifest_path = paths.common_root / str(self.value["binary"]["manifest_path"])
        raw = _read_regular(manifest_path, max_bytes=2 * 1024 * 1024)
        manifest = _load_manifest(manifest_path, paths.common_root)
        binary = self.value["binary"]
        if (
            hashlib.sha256(raw).hexdigest() != binary["manifest_sha256"]
            or manifest.source_commit != binary["source_commit"]
            or manifest.sha256 != binary["binary_sha256"]
            or manifest.product != Product.RONDO_LOCAL.value
            or manifest.source_dirty
        ):
            raise C2BehaviorError("Plan 058 binary manifest drifted")
        _validate_binary_source_relation(
            paths.worktree_root,
            binary_commit=manifest.source_commit,
            harness_commit=self.harness_commit,
            campaign_mode=("formal" if self.campaign_mode == "formal" else "rehearsal"),
        )
        return manifest

    def seccomp_profile(self, paths: RepoPaths) -> Path:
        if self.value["seccomp"] != self.reference.no_api_seccomp:
            raise C2BehaviorError("Plan 058 seccomp identity drifted")
        try:
            return self.reference.validate_runtime_seccomp(
                project_root=paths.worktree_root
            )
        except ValueError as exc:
            raise C2BehaviorError("Plan 058 seccomp profile drifted") from exc

    def validate_runtime_checkout(self, paths: RepoPaths) -> None:
        root = paths.worktree_root
        head = _git(root, "rev-parse", "HEAD")
        if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
            raise C2BehaviorError("Plan 058 runtime checkout is dirty")
        if _git_result(root, "merge-base", "--is-ancestor", self.harness_commit, head).returncode:
            raise C2BehaviorError("Plan 058 harness commit is not an ancestor")
        protected = (
            "eval/rondo_eval",
            "eval/pyproject.toml",
            "eval/seccomp",
            "eval/tasksets",
            "eval/templates",
            "eval/uv.lock",
            "justfile",
            "scripts/build-watchdog-lib.sh",
            "scripts/with-build-lock.sh",
            "mydev",
        )
        if _git_result(root, "diff", "--quiet", self.harness_commit, head, "--", *protected).returncode:
            raise C2BehaviorError("Plan 058 executable projection drifted")


class C2BehaviorState:
    """Single-writer logical-slot state; transport retries never replace a slot."""

    def __init__(self, path: Path, *, identity: C2BehaviorIdentity) -> None:
        self.path = path
        self.identity = identity
        self._lock_path = path.with_suffix(path.suffix + ".lock")
        self._handle: Any | None = None
        self._value: dict[str, Any] | None = None

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._lock_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "r+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        self._handle = handle
        try:
            self._value = _read_json(self.path)
            validate_state(self._value, identity=self.identity)
        except BaseException:
            self._release()
            raise
        return self

    def __exit__(self, _type: object, _value: object, _trace: object) -> None:
        self._release()

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._require()))

    def claim_preflight(self) -> tuple[str, int] | None:
        value = self._require()
        if value["status"] != "running":
            return None
        running = [row for row in value["preflight"] if row["status"] == "running"]
        if len(running) > 1:
            raise C2BehaviorError("Plan 058 preflight state is ambiguous")
        row = running[0] if running else next(
            (item for item in value["preflight"] if item["status"] == "pending"),
            None,
        )
        if row is None:
            return None
        if row["status"] == "pending":
            row["status"] = "running"
            row["attempts"] += 1
            self._persist()
        return str(row["task_id"]), int(row["attempts"])

    def finish_preflight(self, task_id: str, *, receipt_sha256: str) -> None:
        if _SHA256.fullmatch(receipt_sha256) is None:
            raise C2BehaviorError("Plan 058 preflight digest is invalid")
        row = self._preflight_row(task_id)
        if row["status"] != "running":
            raise C2BehaviorError("Plan 058 preflight task is not running")
        row.update(status="complete", receipt_sha256=receipt_sha256, last_error=None)
        self._persist()

    def preflight_retry(self, task_id: str, *, reason: str) -> None:
        row = self._preflight_row(task_id)
        if row["status"] != "running" or not reason:
            raise C2BehaviorError("Plan 058 preflight retry is invalid")
        row.update(status="pending", last_error=reason[:256])
        self._persist()

    def fail_preflight(self, task_id: str, *, reason: str) -> None:
        """Retry setup faults outside formal; formal identity fails closed."""

        if self.identity.campaign_mode in {"commissioning", "diagnostic"}:
            self.preflight_retry(task_id, reason=reason)
            return
        row = self._preflight_row(task_id)
        if row["status"] != "running" or not reason:
            raise C2BehaviorError("Plan 058 formal preflight failure is invalid")
        row["last_error"] = reason[:256]
        self.invalidate(f"formal_preflight_failed:{reason}"[:512])

    def claim_or_resume_slot(self) -> tuple[C2BehaviorSlot, int, str] | None:
        value = self._require()
        if value["status"] != "running":
            return None
        if any(row["status"] != "complete" for row in value["preflight"]):
            raise C2BehaviorError("Plan 058 preflight is incomplete")
        running = [row for row in value["slots"] if row["status"] == "running"]
        if len(running) > 1:
            raise C2BehaviorError("Plan 058 paid state is ambiguous")
        if running:
            row = running[0]
        else:
            row = next(
                (item for item in value["slots"] if item["status"] in {"pending", "retry_pending"}),
                None,
            )
            if row is None:
                value["status"] = "ready_to_finalize"
                self._persist()
                return None
            row["execution_attempts"] += 1
            row["status"] = "running"
            slot = self.identity.slot(str(row["slot_id"]))
            row["current_attempt_run_id"] = slot.attempt_run_id(
                int(row["execution_attempts"])
            )
            self._persist()
        slot = self.identity.slot(str(row["slot_id"]))
        return slot, int(row["execution_attempts"]), str(row["current_attempt_run_id"])

    def mark_transport_retry(
        self,
        slot_id: str,
        *,
        attempt: int,
        attempt_run_id: str,
        evidence: Mapping[str, Any],
    ) -> None:
        row = self._slot_row(slot_id)
        if (
            row["status"] != "running"
            or row["execution_attempts"] != attempt
            or row["current_attempt_run_id"] != attempt_run_id
        ):
            raise C2BehaviorError("Plan 058 transport retry does not own the slot")
        safe = validate_transport_retry_evidence(evidence)
        if safe["attempt"] != attempt or safe["attempt_run_id"] != attempt_run_id:
            raise C2BehaviorError("Plan 058 transport evidence identity drifted")
        previous = row["transport_retries"][-1] if row["transport_retries"] else None
        if (
            safe["prior_budget_run_sha256"]
            != (previous["budget_run_sha256"] if previous is not None else None)
        ):
            raise C2BehaviorError("Plan 058 transport evidence chain drifted")
        row["transport_retries"].append(safe)
        row["status"] = "retry_pending"
        row["current_attempt_run_id"] = None
        self._persist()

    def publish_slot(
        self,
        slot_id: str,
        *,
        attempt: int,
        attempt_run_id: str,
        record_sha256: str,
    ) -> None:
        if _SHA256.fullmatch(record_sha256) is None:
            raise C2BehaviorError("Plan 058 slot record digest is invalid")
        row = self._slot_row(slot_id)
        if (
            row["status"] != "running"
            or row["execution_attempts"] != attempt
            or row["current_attempt_run_id"] != attempt_run_id
        ):
            raise C2BehaviorError("Plan 058 publication does not own the slot")
        row.update(
            status="published",
            published_attempt=attempt,
            published_attempt_run_id=attempt_run_id,
            current_attempt_run_id=None,
            record_sha256=record_sha256,
        )
        if all(item["status"] == "published" for item in self._require()["slots"]):
            self._require()["status"] = "ready_to_finalize"
        self._persist()

    def mark_paid_boundary(self) -> None:
        if not self._require()["paid_boundary"]:
            self._require()["paid_boundary"] = True
            self._persist()

    def invalidate(self, reason: str) -> None:
        value = self._require()
        if value["status"] == "finalized":
            raise C2BehaviorError("finalized Plan 058 state cannot be invalidated")
        if not isinstance(reason, str) or not reason:
            raise C2BehaviorError("Plan 058 invalidation reason is missing")
        value["status"] = "invalid"
        value["invalid_reason"] = reason[:512]
        self._persist()

    def store_final_storage(self, receipt: Mapping[str, Any]) -> None:
        value = self._require()
        if value["status"] not in _TERMINAL_STATUSES:
            raise C2BehaviorError("Plan 058 storage close is premature")
        if value["final_storage"] is not None and value["final_storage"] != receipt:
            raise C2BehaviorError("Plan 058 final storage receipt drifted")
        if value["final_storage"] is None:
            if (
                value["status"] == "ready_to_finalize"
                and receipt.get("final_sample_status") != "complete"
            ):
                reason = str(
                    receipt.get("final_sample_reason")
                    or "resource_sample_unavailable"
                )
                value["status"] = "invalid"
                value["invalid_reason"] = (
                    f"final_resource_sample_unavailable:{reason}"[:512]
                )
            value["final_storage"] = dict(receipt)
            self._persist()

    def finalize(self, *, outcome: str) -> None:
        value = self._require()
        if value["status"] not in {"ready_to_finalize", "invalid", "finalized"}:
            raise C2BehaviorError("Plan 058 campaign is not terminal")
        if value["status"] == "finalized":
            if value["outcome"] != outcome:
                raise C2BehaviorError("Plan 058 final outcome drifted")
            return
        value.update(status="finalized", outcome=outcome)
        self._persist()

    def _require(self) -> dict[str, Any]:
        if self._value is None:
            raise C2BehaviorError("Plan 058 state is not locked")
        return self._value

    def _preflight_row(self, task_id: str) -> dict[str, Any]:
        rows = [row for row in self._require()["preflight"] if row["task_id"] == task_id]
        if len(rows) != 1:
            raise C2BehaviorError("Plan 058 preflight task is ambiguous")
        return rows[0]

    def _slot_row(self, slot_id: str) -> dict[str, Any]:
        rows = [row for row in self._require()["slots"] if row["slot_id"] == slot_id]
        if len(rows) != 1:
            raise C2BehaviorError("Plan 058 slot state is ambiguous")
        return rows[0]

    def _persist(self) -> None:
        validate_state(self._require(), identity=self.identity)
        _atomic_json(self.path, self._require(), mode=0o600)

    def _release(self) -> None:
        handle = self._handle
        self._value = None
        self._handle = None
        if handle is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def campaign_root(paths: RepoPaths, identity: C2BehaviorIdentity) -> Path:
    return paths.common_root / "eval-data/campaigns" / identity.campaign_id


def state_path(paths: RepoPaths, identity: C2BehaviorIdentity) -> Path:
    return campaign_root(paths, identity) / "state.json"


def budget_path(paths: RepoPaths, identity: C2BehaviorIdentity) -> Path:
    return paths.common_root / "eval-data/budgets" / f"{identity.batch_id}.json"


def slot_root(paths: RepoPaths, identity: C2BehaviorIdentity, slot: C2BehaviorSlot) -> Path:
    return campaign_root(paths, identity) / "slots" / slot.slot_id


def slot_record_path(
    paths: RepoPaths, identity: C2BehaviorIdentity, slot: C2BehaviorSlot
) -> Path:
    return slot_root(paths, identity, slot) / "record.json"


def preflight_receipt_path(
    paths: RepoPaths, identity: C2BehaviorIdentity, task: FrozenTask
) -> Path:
    return campaign_root(paths, identity) / "preflight" / f"{task.slug}.json"


def plan058_usage_envelope() -> UsageEnvelope:
    envelope = UsageEnvelope(
        max_input_tokens=MAX_INPUT_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    envelope.validate()
    return envelope


def _pricing_from_public(value: Mapping[str, Any]) -> ModelPricing:
    try:
        pricing = ModelPricing(
            model_id=str(value["model_id"]),
            input_usd_per_million=Decimal(str(value["input_usd_per_million"])),
            cached_input_usd_per_million=Decimal(
                str(value["cached_input_usd_per_million"])
            ),
            output_usd_per_million=Decimal(str(value["output_usd_per_million"])),
            long_context_threshold_tokens=int(
                value["long_context_threshold_tokens"]
            ),
            long_context_input_multiplier=Decimal(
                str(value["long_context_input_multiplier"])
            ),
            long_context_output_multiplier=Decimal(
                str(value["long_context_output_multiplier"])
            ),
            cache_write_input_multiplier=Decimal(
                str(value["cache_write_input_multiplier"])
            ),
            price_snapshot_date=str(value["price_snapshot_date"]),
            price_source_url=str(value["price_source_url"]),
        )
        pricing.validate()
    except (ArithmeticError, KeyError, TypeError, ValueError) as exc:
        raise C2BehaviorError("Plan 058 frozen pricing is invalid") from exc
    return pricing


def plan058_request_reservation(public_provider: Mapping[str, Any]) -> Decimal:
    envelope = plan058_usage_envelope()
    try:
        prices = (
            _pricing_from_public(public_provider["main_pricing"]),
            _pricing_from_public(public_provider["guardian_pricing"]),
        )
    except (KeyError, TypeError) as exc:
        raise C2BehaviorError("Plan 058 provider pricing is incomplete") from exc
    return max(maximum_usage_cost(pricing, envelope) for pricing in prices)


def freeze_slots(
    tasks: Iterable[FrozenTask],
    *,
    run_id_date: str,
    run_id_sequence_base: int,
    rounds: int,
) -> tuple[C2BehaviorSlot, ...]:
    values = tuple(tasks)
    if (
        not values
        or len(values) > PLAN058_FORMAL_TASKS
        or rounds not in {1, 2}
        or not re.fullmatch(r"20[0-9]{6}", run_id_date)
        or isinstance(run_id_sequence_base, bool)
        or not 1 <= run_id_sequence_base <= 999_999_980
    ):
        raise C2BehaviorError("Plan 058 slot denominator is invalid")
    sequence = run_id_sequence_base
    slots: list[C2BehaviorSlot] = []
    for round_number in range(1, rounds + 1):
        for task_index, task in enumerate(values, start=1):
            task.validate()
            slot = C2BehaviorSlot(
                slot_id=f"r{round_number:02d}-t{task_index:02d}-{task.slug}",
                logical_run_id=f"{run_id_date}-{sequence:09d}-tb-rondo-plan058",
                round=round_number,
                task_index=task_index,
                task_id=task.task_id,
            )
            slot.validate(task_count=len(values), rounds=rounds)
            slots.append(slot)
            sequence += 1
    return tuple(slots)


def freeze_diagnostic_slots(
    tasks: Iterable[FrozenTask],
    *,
    run_id_date: str,
    run_id_sequence_base: int,
    slot_start: int,
    slot_end: int,
) -> tuple[C2BehaviorSlot, ...]:
    if (
        isinstance(slot_start, bool)
        or not isinstance(slot_start, int)
        or isinstance(slot_end, bool)
        or not isinstance(slot_end, int)
        or not PLAN058_DIAGNOSTIC_SLOT_MIN
        <= slot_start
        <= slot_end
        <= PLAN058_DIAGNOSTIC_SLOT_MAX
    ):
        raise C2BehaviorError("Plan 058 diagnostic slot range is invalid")
    formal = freeze_slots(
        tasks,
        run_id_date=run_id_date,
        run_id_sequence_base=run_id_sequence_base,
        rounds=PLAN058_FORMAL_ROUNDS,
    )
    if len(formal) != PLAN058_FORMAL_SLOTS:
        raise C2BehaviorError("Plan 058 diagnostic formal order drifted")
    selected = formal[slot_start - 1 : slot_end]
    slots = tuple(
        C2BehaviorSlot(
            slot_id=slot.slot_id,
            logical_run_id=(
                f"{run_id_date}-{run_id_sequence_base + offset:09d}-"
                "tb-rondo-plan058"
            ),
            round=slot.round,
            task_index=slot.task_index,
            task_id=slot.task_id,
        )
        for offset, slot in enumerate(selected)
    )
    for slot in slots:
        slot.validate(
            task_count=PLAN058_FORMAL_TASKS,
            rounds=PLAN058_FORMAL_ROUNDS,
        )
    return slots


def freeze_formal_slots(
    tasks: Iterable[FrozenTask],
    *,
    run_id_date: str,
    run_id_sequence_base: int,
) -> tuple[C2BehaviorSlot, ...]:
    """Freeze the one Plan 058 post-diagnostic formal execution order."""

    canonical = freeze_slots(
        tasks,
        run_id_date=run_id_date,
        run_id_sequence_base=run_id_sequence_base,
        rounds=PLAN058_FORMAL_ROUNDS,
    )
    if len(canonical) != PLAN058_FORMAL_SLOTS:
        raise C2BehaviorError("Plan 058 formal denominator drifted")
    slots = tuple(
        C2BehaviorSlot(
            slot_id=canonical[position - 1].slot_id,
            logical_run_id=(
                f"{run_id_date}-{run_id_sequence_base + offset:09d}-"
                "tb-rondo-plan058"
            ),
            round=canonical[position - 1].round,
            task_index=canonical[position - 1].task_index,
            task_id=canonical[position - 1].task_id,
        )
        for offset, position in enumerate(PLAN058_FORMAL_EXECUTION_ORDER)
    )
    for slot in slots:
        slot.validate(
            task_count=PLAN058_FORMAL_TASKS,
            rounds=PLAN058_FORMAL_ROUNDS,
        )
    return slots


def _load_v28_reference(paths: RepoPaths) -> CampaignIdentity:
    raw = _read_regular(paths.worktree_root / PLAN058_V28_RELPATH)
    if hashlib.sha256(raw).hexdigest() != PLAN058_V28_SHA256:
        raise C2BehaviorError("Plan 058 v28 reference drifted")
    try:
        identity = load_historical_campaign_identity(paths, 28)
    except ValueError as exc:
        raise C2BehaviorError("Plan 058 v28 identity is unavailable") from exc
    if identity.lock_sha256 != PLAN058_V28_SHA256:
        raise C2BehaviorError("Plan 058 v28 identity digest drifted")
    return identity


def initialize_identity(
    paths: RepoPaths,
    *,
    campaign_id: str,
    batch_id: str,
    campaign_mode: str,
    result_namespace: str,
    public_result_path: Path,
    runtime_manifest: Path,
    run_id_date: str,
    run_id_sequence_base: int,
    commissioning_task_id: str | None = None,
    diagnostic_slot_start: int | None = None,
    diagnostic_slot_end: int | None = None,
) -> C2BehaviorIdentity:
    """Create or exactly resume one initialization under its campaign lease."""

    if (
        not isinstance(campaign_id, str)
        or not campaign_id.startswith(_CAMPAIGN_PREFIX)
        or _SAFE_ID.fullmatch(campaign_id) is None
    ):
        raise C2BehaviorError("Plan 058 initialization identity is invalid")
    from .baseline_cli import CampaignExecutionLease

    lease_path = (
        paths.common_root
        / "eval-data/campaigns"
        / campaign_id
        / "executor.lock"
    )
    with CampaignExecutionLease(lease_path):
        return _initialize_identity_locked(
            paths,
            campaign_id=campaign_id,
            batch_id=batch_id,
            campaign_mode=campaign_mode,
            result_namespace=result_namespace,
            public_result_path=public_result_path,
            runtime_manifest=runtime_manifest,
            run_id_date=run_id_date,
            run_id_sequence_base=run_id_sequence_base,
            commissioning_task_id=commissioning_task_id,
            diagnostic_slot_start=diagnostic_slot_start,
            diagnostic_slot_end=diagnostic_slot_end,
        )


def _initialize_identity_locked(
    paths: RepoPaths,
    *,
    campaign_id: str,
    batch_id: str,
    campaign_mode: str,
    result_namespace: str,
    public_result_path: Path,
    runtime_manifest: Path,
    run_id_date: str,
    run_id_sequence_base: int,
    commissioning_task_id: str | None = None,
    diagnostic_slot_start: int | None = None,
    diagnostic_slot_end: int | None = None,
) -> C2BehaviorIdentity:
    if (
        not campaign_id.startswith(_CAMPAIGN_PREFIX)
        or _SAFE_ID.fullmatch(campaign_id) is None
        or _SAFE_ID.fullmatch(batch_id) is None
        or not batch_id.startswith(campaign_id)
        or _SAFE_ID.fullmatch(result_namespace) is None
        or result_namespace != campaign_id
        or campaign_mode not in {"commissioning", "diagnostic", "formal"}
    ):
        raise C2BehaviorError("Plan 058 initialization identity is invalid")
    if public_result_path.is_absolute() or ".." in public_result_path.parts:
        raise C2BehaviorError("Plan 058 public result path is invalid")
    expected_result_parent = Path("eval/results/observations")
    if (
        public_result_path.parent != expected_result_parent
        or public_result_path.name != f"{campaign_id}.json"
    ):
        raise C2BehaviorError("Plan 058 public result namespace is invalid")
    lock_relpath = Path("eval/locks") / f"{campaign_id}.json"
    lock_path = paths.worktree_root / lock_relpath
    pointer_path = paths.worktree_root / PLAN058_POINTER_RELPATH
    if lock_path.exists() or lock_path.is_symlink():
        return _resume_identity_initialization(
            paths,
            lock_relpath=lock_relpath,
            campaign_id=campaign_id,
            batch_id=batch_id,
            campaign_mode=campaign_mode,
            result_namespace=result_namespace,
            public_result_path=public_result_path,
            runtime_manifest=runtime_manifest,
            run_id_date=run_id_date,
            run_id_sequence_base=run_id_sequence_base,
            commissioning_task_id=commissioning_task_id,
            diagnostic_slot_start=diagnostic_slot_start,
            diagnostic_slot_end=diagnostic_slot_end,
        )
    if pointer_path.exists() or pointer_path.is_symlink():
        pointer = _read_json(pointer_path)
        if pointer.get("active_lock") is not None:
            raise C2BehaviorError("Plan 058 predecessor identity is still active")
    if _git(paths.worktree_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise C2BehaviorError("Plan 058 initialize requires a clean worktree")
    harness_commit = _git(paths.worktree_root, "rev-parse", "HEAD")
    if _COMMIT.fullmatch(harness_commit) is None:
        raise C2BehaviorError("Plan 058 harness commit is invalid")
    reference = _load_v28_reference(paths)
    all_tasks = tuple(reference.catalog.tasks)
    if len(all_tasks) != PLAN058_FORMAL_TASKS:
        raise C2BehaviorError("Plan 058 v28 task denominator drifted")
    if campaign_mode == "formal":
        if (
            commissioning_task_id is not None
            or diagnostic_slot_start is not None
            or diagnostic_slot_end is not None
        ):
            raise C2BehaviorError("Plan 058 formal identity cannot select a subset")
        tasks = all_tasks
        rounds = PLAN058_FORMAL_ROUNDS
    elif campaign_mode == "diagnostic":
        if commissioning_task_id is not None:
            raise C2BehaviorError("Plan 058 diagnostic identity cannot select one task")
        if diagnostic_slot_start is None or diagnostic_slot_end is None:
            raise C2BehaviorError("Plan 058 diagnostic slot range is required")
        tasks = all_tasks
        rounds = PLAN058_FORMAL_ROUNDS
    else:
        if diagnostic_slot_start is not None or diagnostic_slot_end is not None:
            raise C2BehaviorError(
                "Plan 058 commissioning identity cannot select diagnostic slots"
            )
        matches = tuple(task for task in all_tasks if task.task_id == commissioning_task_id)
        if len(matches) != 1:
            raise C2BehaviorError("Plan 058 commissioning task is not frozen in v28")
        tasks = matches
        rounds = 1
    raw_manifest = _read_regular(runtime_manifest, max_bytes=2 * 1024 * 1024)
    manifest = _load_manifest(runtime_manifest, paths.common_root)
    if manifest.source_dirty or manifest.product != Product.RONDO_LOCAL.value:
        raise C2BehaviorError("Plan 058 manifest does not bind clean Local source")
    _validate_binary_source_relation(
        paths.worktree_root,
        binary_commit=manifest.source_commit,
        harness_commit=harness_commit,
        campaign_mode=("formal" if campaign_mode == "formal" else "rehearsal"),
    )
    try:
        manifest_relative = runtime_manifest.resolve(strict=True).relative_to(
            paths.common_root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise C2BehaviorError("Plan 058 manifest is outside common root") from exc
    config = load_runtime_config(paths)
    provider = config.paid_provider_projection(
        model_id=PLAN058_MODEL,
        main_effort=PLAN058_MAIN_EFFORT,
        guardian_effort=PLAN058_GUARDIAN_EFFORT,
    )
    public_provider = provider.to_public_dict()
    request_reservation = plan058_request_reservation(public_provider)
    v28_provider = {key: reference.selected_profile[key] for key in public_provider}
    if public_provider != v28_provider:
        raise C2BehaviorError("Plan 058 provider differs from frozen v28")
    envelope_path = task_budget_path(paths.common_root, PLAN058_TASK_BUDGET_ID)
    active = TaskBudgetIdentity(campaign_id, batch_id)
    if envelope_path.exists() or envelope_path.is_symlink():
        envelope = load_task_budget(
            envelope_path,
            task_budget_id=PLAN058_TASK_BUDGET_ID,
            cap_usd=PLAN058_TASK_CAP_USD,
        )
        if envelope["active_identity"] is not None:
            raise C2BehaviorError("Plan 058 task budget is already active")
        prior = Decimal(str(envelope["prior_settled_usd"]))
    else:
        envelope = None
        prior = Decimal(0)
    campaign_cap = PLAN058_TASK_CAP_USD - prior
    if campaign_cap < request_reservation:
        raise C2BehaviorError("Plan 058 budget cannot reserve one reliable request")
    if campaign_mode == "formal":
        slots = freeze_formal_slots(
            tasks,
            run_id_date=run_id_date,
            run_id_sequence_base=run_id_sequence_base,
        )
    elif campaign_mode == "diagnostic":
        slots = freeze_diagnostic_slots(
            tasks,
            run_id_date=run_id_date,
            run_id_sequence_base=run_id_sequence_base,
            slot_start=diagnostic_slot_start,
            slot_end=diagnostic_slot_end,
        )
    else:
        slots = freeze_slots(
            tasks,
            run_id_date=run_id_date,
            run_id_sequence_base=run_id_sequence_base,
            rounds=rounds,
        )
    value: dict[str, Any] = {
        "schema_version": PLAN058_SCHEMA_VERSION,
        "kind": PLAN058_KIND,
        "campaign_id": campaign_id,
        "batch_id": batch_id,
        "campaign_mode": campaign_mode,
        "rounds": rounds,
        "result_namespace": result_namespace,
        "public_result_path": public_result_path.as_posix(),
        "harness_commit": harness_commit,
        "source": {
            "v28_lock_path": PLAN058_V28_RELPATH.as_posix(),
            "v28_lock_sha256": PLAN058_V28_SHA256,
            "taskset_sha256": reference.taskset_sha256,
            "canary_catalog_sha256": reference.canary_catalog_sha256,
            "terminal_bench_commit": reference.terminal_bench_commit,
        },
        "binary": {
            "product": Product.RONDO_LOCAL.value,
            "manifest_path": manifest_relative.as_posix(),
            "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
            "source_commit": manifest.source_commit,
            "binary_sha256": manifest.sha256,
            "code_mode_host_sha256": manifest.code_mode_host_sha256,
            "bwrap_sha256": manifest.bwrap_sha256,
        },
        "provider": {
            "public_profile": public_provider,
            "max_guardian_logical_requests": reference.max_guardian_logical_requests,
            "upstream_timeout_seconds": f"{reference.upstream_timeout_seconds:.3f}",
            "proxy_max_attempts_per_physical_run": 1,
        },
        "product_variable": {
            "name": "exec_command_repeat_guidance",
            "enabled": True,
            "runtime_suppression": False,
            "guardian_changed": False,
        },
        "seccomp": dict(reference.no_api_seccomp),
        "budget": {
            "task_budget_id": PLAN058_TASK_BUDGET_ID,
            "task_budget_cap_usd": f"{PLAN058_TASK_CAP_USD:.6f}",
            "prior_estimated_usd": f"{prior:.6f}",
            "campaign_cap_usd": f"{campaign_cap:.6f}",
            "logical_run_cap_usd": f"{campaign_cap:.6f}",
            "physical_terminal_bench_budget_usd": (
                f"{PLAN058_PHYSICAL_RUN_BUDGET_USD:.6f}"
            ),
            "max_logical_runs": len(slots),
            "transport_retry_limit": None,
            "unpriced_attempt_fallback_usd": f"{PLAN058_UNPRICED_FALLBACK_USD:.6f}",
            "unpriced_fallback_accounting": "per_upstream_attempt",
            "minimum_next_request_reservation_usd": "1.000000",
            "usage_envelope": {
                "max_input_tokens": MAX_INPUT_TOKENS,
                "max_output_tokens": MAX_OUTPUT_TOKENS,
            },
            "reliable_usage_request_reservation_usd": (
                f"{request_reservation:.6f}"
            ),
        },
        "observation": {
            "schema_version": PLAN058_OBSERVATION_SCHEMA_VERSION,
            "trace_root": "/logs/agent/rollout-trace",
            "body_free": True,
            "refined_classification": "private_manual_frozen_rules",
        },
        "decision_contract": {
            "primary_metric": "refined_harmful_occurrences",
            "baseline": PLAN058_REFINED_BASELINE,
            "retain_at_most": PLAN058_REFINED_TARGET,
            "formal_denominator": PLAN058_FORMAL_SLOTS,
            "valid_failures_are_results": True,
        },
        "tasks": [asdict(task) for task in tasks],
        "slots": [asdict(slot) for slot in slots],
    }
    if campaign_mode == "diagnostic":
        value["diagnostic_slot_range"] = {
            "start": diagnostic_slot_start,
            "end": diagnostic_slot_end,
        }
    elif campaign_mode == "formal":
        value["formal_execution_order"] = list(
            PLAN058_FORMAL_EXECUTION_ORDER
        )
    _atomic_json(lock_path, value, mode=0o644)
    raw_lock = _read_regular(lock_path)
    digest = hashlib.sha256(raw_lock).hexdigest()
    pointer = {
        "schema_version": 1,
        "kind": PLAN058_KIND,
        "active_lock": lock_relpath.as_posix(),
        "active_lock_sha256": digest,
        "last_lock": lock_relpath.as_posix(),
        "last_lock_sha256": digest,
    }
    _atomic_json(pointer_path, pointer, mode=0o644)
    identity = load_identity(paths)
    _ensure_initialization_state_and_budget(paths, identity)
    return identity


def _initial_state(identity: C2BehaviorIdentity) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": PLAN058_KIND,
        "campaign_id": identity.campaign_id,
        "campaign_lock_sha256": identity.lock_sha256,
        "status": "running",
        "invalid_reason": None,
        "paid_boundary": False,
        "preflight": [
            {
                "task_id": task.task_id,
                "status": "pending",
                "attempts": 0,
                "receipt_sha256": None,
                "last_error": None,
            }
            for task in identity.preflight_tasks
        ],
        "slots": [
            {
                "slot_id": slot.slot_id,
                "logical_run_id": slot.logical_run_id,
                "status": "pending",
                "execution_attempts": 0,
                "current_attempt_run_id": None,
                "transport_retries": [],
                "published_attempt": None,
                "published_attempt_run_id": None,
                "record_sha256": None,
            }
            for slot in identity.slots
        ],
        "final_storage": None,
        "outcome": None,
    }


def _resume_identity_initialization(
    paths: RepoPaths,
    *,
    lock_relpath: Path,
    campaign_id: str,
    batch_id: str,
    campaign_mode: str,
    result_namespace: str,
    public_result_path: Path,
    runtime_manifest: Path,
    run_id_date: str,
    run_id_sequence_base: int,
    commissioning_task_id: str | None,
    diagnostic_slot_start: int | None,
    diagnostic_slot_end: int | None,
) -> C2BehaviorIdentity:
    lock_path = paths.worktree_root / lock_relpath
    if lock_path.is_symlink() or not lock_path.is_file():
        raise C2BehaviorError("Plan 058 recovery lock path is unsafe")
    allowed_dirty = {
        lock_relpath.as_posix(),
        PLAN058_POINTER_RELPATH.as_posix(),
    }
    status = _git(
        paths.worktree_root, "status", "--porcelain=v1", "--untracked-files=all"
    )
    dirty_paths = {
        line[3:]
        for line in status.splitlines()
        if len(line) >= 4 and line[3:]
    }
    if not dirty_paths.issubset(allowed_dirty):
        raise C2BehaviorError("Plan 058 initialization recovery worktree drifted")
    raw_lock = _read_regular(lock_path)
    digest = hashlib.sha256(raw_lock).hexdigest()
    identity = _load_identity_from_lock(paths, lock_path=lock_path, digest=digest)
    try:
        manifest_relative = runtime_manifest.resolve(strict=True).relative_to(
            paths.common_root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise C2BehaviorError("Plan 058 recovery manifest is unavailable") from exc
    raw_manifest = _read_regular(runtime_manifest, max_bytes=2 * 1024 * 1024)
    if identity.campaign_mode == "diagnostic":
        if diagnostic_slot_start is None or diagnostic_slot_end is None:
            raise C2BehaviorError("Plan 058 diagnostic recovery range is missing")
        expected_slots = freeze_diagnostic_slots(
            identity.tasks,
            run_id_date=run_id_date,
            run_id_sequence_base=run_id_sequence_base,
            slot_start=diagnostic_slot_start,
            slot_end=diagnostic_slot_end,
        )
        expected_diagnostic_range: Mapping[str, int] | None = {
            "start": diagnostic_slot_start,
            "end": diagnostic_slot_end,
        }
    elif identity.campaign_mode == "formal" and identity.value.get(
        "formal_execution_order"
    ) is not None:
        expected_slots = freeze_formal_slots(
            identity.tasks,
            run_id_date=run_id_date,
            run_id_sequence_base=run_id_sequence_base,
        )
        expected_diagnostic_range = None
    else:
        expected_slots = freeze_slots(
            identity.tasks,
            run_id_date=run_id_date,
            run_id_sequence_base=run_id_sequence_base,
            rounds=int(identity.value["rounds"]),
        )
        expected_diagnostic_range = None
    expected_commissioning_task = (
        identity.tasks[0].task_id if identity.campaign_mode == "commissioning" else None
    )
    if (
        identity.campaign_id != campaign_id
        or identity.batch_id != batch_id
        or identity.campaign_mode != campaign_mode
        or identity.result_namespace != result_namespace
        or identity.public_result_relative_path != public_result_path.as_posix()
        or manifest_relative.as_posix()
        != identity.value["binary"]["manifest_path"]
        or hashlib.sha256(raw_manifest).hexdigest()
        != identity.value["binary"]["manifest_sha256"]
        or expected_slots != identity.slots
        or commissioning_task_id != expected_commissioning_task
        or identity.value.get("diagnostic_slot_range")
        != expected_diagnostic_range
        or (
            identity.campaign_mode != "diagnostic"
            and (diagnostic_slot_start is not None or diagnostic_slot_end is not None)
        )
    ):
        raise C2BehaviorError("Plan 058 recovery inputs differ from frozen identity")
    _require_open_initialization_recovery(
        paths,
        identity=identity,
        lock_relpath=lock_relpath,
        digest=digest,
    )
    _reconcile_initialization_pointer(paths, lock_relpath=lock_relpath, digest=digest)
    _ensure_initialization_state_and_budget(paths, identity)
    return identity


def _require_open_initialization_recovery(
    paths: RepoPaths,
    *,
    identity: C2BehaviorIdentity,
    lock_relpath: Path,
    digest: str,
) -> None:
    """Reject retired identities and state/pointer histories outside init recovery."""

    pointer_path = paths.worktree_root / PLAN058_POINTER_RELPATH
    if pointer_path.exists() or pointer_path.is_symlink():
        pointer = _read_json(pointer_path)
        if (
            pointer.get("active_lock") is None
            and pointer.get("last_lock") == lock_relpath.as_posix()
            and pointer.get("last_lock_sha256") == digest
        ):
            raise C2BehaviorError("Plan 058 retired identity cannot be reinitialized")
    existing_state = state_path(paths, identity)
    if existing_state.exists() or existing_state.is_symlink():
        state = _read_json(existing_state)
        validate_state(state, identity=identity)
        if state["status"] != "running":
            raise C2BehaviorError("Plan 058 terminal identity cannot be reinitialized")
        expected_active = (
            pointer.get("active_lock") == lock_relpath.as_posix()
            and pointer.get("active_lock_sha256") == digest
            if pointer_path.exists() or pointer_path.is_symlink()
            else False
        )
        if not expected_active:
            raise C2BehaviorError(
                "Plan 058 initialized state differs from its active pointer"
            )


def _reconcile_initialization_pointer(
    paths: RepoPaths, *, lock_relpath: Path, digest: str
) -> None:
    if _SHA256.fullmatch(digest) is None:
        raise C2BehaviorError("Plan 058 recovery lock digest is invalid")
    pointer_path = paths.worktree_root / PLAN058_POINTER_RELPATH
    expected_pointer = {
        "schema_version": 1,
        "kind": PLAN058_KIND,
        "active_lock": lock_relpath.as_posix(),
        "active_lock_sha256": digest,
        "last_lock": lock_relpath.as_posix(),
        "last_lock_sha256": digest,
    }
    if pointer_path.exists() or pointer_path.is_symlink():
        observed_pointer = _read_json(pointer_path)
        if observed_pointer != expected_pointer:
            if (
                not isinstance(observed_pointer, dict)
                or set(observed_pointer) != set(expected_pointer)
                or observed_pointer.get("schema_version") != 1
                or observed_pointer.get("kind") != PLAN058_KIND
                or observed_pointer.get("active_lock") is not None
                or observed_pointer.get("active_lock_sha256") is not None
                or not isinstance(observed_pointer.get("last_lock"), str)
                or not str(observed_pointer["last_lock"]).startswith(
                    "eval/locks/plan058-direction1-c2-"
                )
                or _SHA256.fullmatch(
                    str(observed_pointer.get("last_lock_sha256"))
                )
                is None
            ):
                raise C2BehaviorError(
                    "Plan 058 recovery pointer differs from its lock"
                )
            _atomic_json(pointer_path, expected_pointer, mode=0o644)
    else:
        _atomic_json(pointer_path, expected_pointer, mode=0o644)


def _ensure_initialization_state_and_budget(
    paths: RepoPaths, identity: C2BehaviorIdentity
) -> None:
    root = campaign_root(paths, identity)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or not root.is_dir():
        raise C2BehaviorError("Plan 058 campaign root is unsafe")
    state_file = state_path(paths, identity)
    if state_file.exists() or state_file.is_symlink():
        validate_state(_read_json(state_file), identity=identity)
    else:
        unexpected = {
            child.name for child in root.iterdir() if child.name != "executor.lock"
        }
        if unexpected:
            raise C2BehaviorError("Plan 058 partial campaign root is ambiguous")
        _atomic_json(state_file, _initial_state(identity), mode=0o600)
    envelope_path = task_budget_path(paths.common_root, PLAN058_TASK_BUDGET_ID)
    active = TaskBudgetIdentity(identity.campaign_id, identity.batch_id)
    if not envelope_path.exists() and not envelope_path.is_symlink():
        if identity.prior_settled_usd != 0:
            raise C2BehaviorError("Plan 058 task budget history is missing")
        start_task_budget(
            envelope_path,
            active=active,
            task_budget_id=PLAN058_TASK_BUDGET_ID,
            cap_usd=PLAN058_TASK_CAP_USD,
        )
        return
    envelope = load_task_budget(
        envelope_path,
        task_budget_id=PLAN058_TASK_BUDGET_ID,
        cap_usd=PLAN058_TASK_CAP_USD,
    )
    if envelope["active_identity"] is not None:
        verify_active_identity(
            envelope_path,
            active=active,
            prior_settled_usd=identity.prior_settled_usd,
            task_budget_id=PLAN058_TASK_BUDGET_ID,
            cap_usd=PLAN058_TASK_CAP_USD,
        )
        return
    if Decimal(str(envelope["prior_settled_usd"])) != identity.prior_settled_usd:
        raise C2BehaviorError("Plan 058 closed task budget prior drifted")
    activate_closed_task_budget(
        envelope_path,
        successor=active,
        task_budget_id=PLAN058_TASK_BUDGET_ID,
        cap_usd=PLAN058_TASK_CAP_USD,
    )


def load_identity(paths: RepoPaths, *, allow_retired: bool = False) -> C2BehaviorIdentity:
    pointer = _read_json(paths.worktree_root / PLAN058_POINTER_RELPATH)
    expected_keys = {
        "schema_version",
        "kind",
        "active_lock",
        "active_lock_sha256",
        "last_lock",
        "last_lock_sha256",
    }
    if set(pointer) != expected_keys or pointer["schema_version"] != 1 or pointer["kind"] != PLAN058_KIND:
        raise C2BehaviorError("Plan 058 active pointer schema is invalid")
    lock_rel = pointer["active_lock"]
    digest = pointer["active_lock_sha256"]
    if lock_rel is None:
        if not allow_retired:
            raise C2BehaviorError("Plan 058 active pointer is retired")
        lock_rel = pointer["last_lock"]
        digest = pointer["last_lock_sha256"]
    if (
        not isinstance(lock_rel, str)
        or not lock_rel.startswith("eval/locks/plan058-direction1-c2-")
        or _SHA256.fullmatch(str(digest)) is None
    ):
        raise C2BehaviorError("Plan 058 pointer identity is invalid")
    lock_path = paths.worktree_root / lock_rel
    return _load_identity_from_lock(paths, lock_path=lock_path, digest=str(digest))


def _load_identity_from_lock(
    paths: RepoPaths, *, lock_path: Path, digest: str
) -> C2BehaviorIdentity:
    raw = _read_regular(lock_path)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise C2BehaviorError("Plan 058 lock digest differs from pointer")
    value = json.loads(raw)
    reference = _load_v28_reference(paths)
    tasks = tuple(FrozenTask(**row) for row in value.get("tasks", []))
    slots = tuple(C2BehaviorSlot(**row) for row in value.get("slots", []))
    identity = C2BehaviorIdentity(lock_path, str(digest), value, reference, tasks, slots)
    validate_identity(identity, paths=paths)
    return identity


def validate_identity(identity: C2BehaviorIdentity, *, paths: RepoPaths) -> None:
    value = identity.value
    required = {
        "schema_version", "kind", "campaign_id", "batch_id", "campaign_mode",
        "rounds", "result_namespace", "public_result_path", "harness_commit",
        "source", "binary", "provider", "product_variable", "seccomp", "budget",
        "observation", "decision_contract", "tasks", "slots",
    }
    if isinstance(value, Mapping) and value.get("campaign_mode") == "diagnostic":
        required.add("diagnostic_slot_range")
    if (
        isinstance(value, Mapping)
        and value.get("campaign_mode") == "formal"
        and "formal_execution_order" in value
    ):
        required.add("formal_execution_order")
    if not isinstance(value, Mapping) or set(value) != required:
        raise C2BehaviorError("Plan 058 identity schema is invalid")
    if (
        value["schema_version"] != 1
        or value["kind"] != PLAN058_KIND
        or not str(value["campaign_id"]).startswith(_CAMPAIGN_PREFIX)
        or _SAFE_ID.fullmatch(str(value["campaign_id"])) is None
        or _SAFE_ID.fullmatch(str(value["batch_id"])) is None
        or value["campaign_mode"] not in {"commissioning", "diagnostic", "formal"}
        or _COMMIT.fullmatch(str(value["harness_commit"])) is None
        or value["result_namespace"] != value["campaign_id"]
        or value["public_result_path"]
        != f"eval/results/observations/{value['campaign_id']}.json"
    ):
        raise C2BehaviorError("Plan 058 identity header is invalid")
    if value["campaign_mode"] == "formal" and "formal_execution_order" not in value:
        if (
            identity.campaign_id != PLAN058_LEGACY_FORMAL_V1_CAMPAIGN_ID
            or identity.lock_sha256 != PLAN058_LEGACY_FORMAL_V1_SHA256
        ):
            raise C2BehaviorError(
                "Plan 058 new formal identity lacks its execution order"
            )
    if value["source"] != {
        "v28_lock_path": PLAN058_V28_RELPATH.as_posix(),
        "v28_lock_sha256": PLAN058_V28_SHA256,
        "taskset_sha256": identity.reference.taskset_sha256,
        "canary_catalog_sha256": identity.reference.canary_catalog_sha256,
        "terminal_bench_commit": identity.reference.terminal_bench_commit,
    }:
        raise C2BehaviorError("Plan 058 v28 source binding drifted")
    if value["product_variable"] != {
        "name": "exec_command_repeat_guidance",
        "enabled": True,
        "runtime_suppression": False,
        "guardian_changed": False,
    }:
        raise C2BehaviorError("Plan 058 product variable drifted")
    if value["seccomp"] != identity.reference.no_api_seccomp:
        raise C2BehaviorError("Plan 058 seccomp binding drifted")
    prior = Decimal(str(value["budget"].get("prior_estimated_usd")))
    campaign_cap = Decimal(str(value["budget"].get("campaign_cap_usd")))
    request_reservation = plan058_request_reservation(
        value["provider"]["public_profile"]
    )
    expected_budget = {
        "task_budget_id": PLAN058_TASK_BUDGET_ID,
        "task_budget_cap_usd": "50.000000",
        "prior_estimated_usd": f"{prior:.6f}",
        "campaign_cap_usd": f"{campaign_cap:.6f}",
        "logical_run_cap_usd": f"{campaign_cap:.6f}",
        "physical_terminal_bench_budget_usd": "40.000000",
        "max_logical_runs": len(identity.slots),
        "transport_retry_limit": None,
        "unpriced_attempt_fallback_usd": "1.000000",
        "unpriced_fallback_accounting": "per_upstream_attempt",
        "minimum_next_request_reservation_usd": "1.000000",
        "usage_envelope": {
            "max_input_tokens": MAX_INPUT_TOKENS,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        },
        "reliable_usage_request_reservation_usd": f"{request_reservation:.6f}",
    }
    if (
        value["budget"] != expected_budget
        or prior < 0
        or prior + campaign_cap != PLAN058_TASK_CAP_USD
        or campaign_cap < request_reservation
    ):
        raise C2BehaviorError("Plan 058 budget contract drifted")
    if value["observation"] != {
        "schema_version": 2,
        "trace_root": "/logs/agent/rollout-trace",
        "body_free": True,
        "refined_classification": "private_manual_frozen_rules",
    }:
        raise C2BehaviorError("Plan 058 observation contract drifted")
    if value["decision_contract"] != {
        "primary_metric": "refined_harmful_occurrences",
        "baseline": 1,
        "retain_at_most": 0,
        "formal_denominator": 20,
        "valid_failures_are_results": True,
    }:
        raise C2BehaviorError("Plan 058 decision contract drifted")
    full_denominator = identity.campaign_mode in {"diagnostic", "formal"}
    expected_task_count = PLAN058_FORMAL_TASKS if full_denominator else 1
    expected_rounds = PLAN058_FORMAL_ROUNDS if full_denominator else 1
    if identity.campaign_mode == "diagnostic":
        diagnostic_range = value["diagnostic_slot_range"]
        if (
            not isinstance(diagnostic_range, Mapping)
            or set(diagnostic_range) != {"start", "end"}
            or isinstance(diagnostic_range["start"], bool)
            or not isinstance(diagnostic_range["start"], int)
            or isinstance(diagnostic_range["end"], bool)
            or not isinstance(diagnostic_range["end"], int)
            or not PLAN058_DIAGNOSTIC_SLOT_MIN
            <= diagnostic_range["start"]
            <= diagnostic_range["end"]
            <= PLAN058_DIAGNOSTIC_SLOT_MAX
        ):
            raise C2BehaviorError("Plan 058 diagnostic slot range drifted")
        expected_positions = range(
            diagnostic_range["start"], diagnostic_range["end"] + 1
        )
        expected_slot_count = diagnostic_range["end"] - diagnostic_range["start"] + 1
    elif identity.campaign_mode == "formal" and "formal_execution_order" in value:
        execution_order = value["formal_execution_order"]
        if (
            not isinstance(execution_order, list)
            or any(
                isinstance(position, bool) or not isinstance(position, int)
                for position in execution_order
            )
            or tuple(execution_order) != PLAN058_FORMAL_EXECUTION_ORDER
        ):
            raise C2BehaviorError("Plan 058 formal execution order drifted")
        expected_positions = execution_order
        expected_slot_count = PLAN058_FORMAL_SLOTS
    else:
        expected_positions = range(1, expected_task_count * expected_rounds + 1)
        expected_slot_count = expected_task_count * expected_rounds
    if (
        len(identity.tasks) != expected_task_count
        or len(identity.slots) != expected_slot_count
        or value["rounds"] != expected_rounds
    ):
        raise C2BehaviorError("Plan 058 campaign denominator drifted")
    reference_tasks = tuple(identity.reference.catalog.tasks)
    if (
        full_denominator
        and identity.tasks != reference_tasks
        or not full_denominator
        and identity.tasks[0] not in reference_tasks
    ):
        raise C2BehaviorError("Plan 058 campaign tasks drifted from v28")
    expected_order = [
        (
            f"r{(position - 1) // expected_task_count + 1:02d}-"
            f"t{(position - 1) % expected_task_count + 1:02d}-"
            f"{identity.tasks[(position - 1) % expected_task_count].slug}",
            (position - 1) // expected_task_count + 1,
            (position - 1) % expected_task_count + 1,
            identity.tasks[(position - 1) % expected_task_count].task_id,
        )
        for position in expected_positions
    ]
    if [
        (slot.slot_id, slot.round, slot.task_index, slot.task_id)
        for slot in identity.slots
    ] != expected_order:
        raise C2BehaviorError("Plan 058 slot order drifted")
    if len({slot.slot_id for slot in identity.slots}) != len(identity.slots) or len({slot.logical_run_id for slot in identity.slots}) != len(identity.slots):
        raise C2BehaviorError("Plan 058 slot identities are duplicated")
    logical_parts = [
        _LOGICAL_RUN_ID.fullmatch(slot.logical_run_id) for slot in identity.slots
    ]
    if (
        any(part is None for part in logical_parts)
        or len({part.group("date") for part in logical_parts if part is not None})
        != 1
        or [
            int(part.group("sequence"))
            for part in logical_parts
            if part is not None
        ]
        != list(
            range(
                int(logical_parts[0].group("sequence")),
                int(logical_parts[0].group("sequence")) + len(identity.slots),
            )
        )
    ):
        raise C2BehaviorError("Plan 058 logical run sequence drifted")
    for slot in identity.slots:
        slot.validate(task_count=expected_task_count, rounds=expected_rounds)
    provider = value["provider"]
    if any(provider["public_profile"].get(key) != expected for key, expected in {
        "main_model": PLAN058_MODEL,
        "guardian_model": PLAN058_MODEL,
        "main_effort": PLAN058_MAIN_EFFORT,
        "guardian_effort": PLAN058_GUARDIAN_EFFORT,
    }.items()):
        raise C2BehaviorError("Plan 058 model or effort drifted")
    if provider != {
        "public_profile": {
            key: candidate
            for key, candidate in identity.reference.selected_profile.items()
            if key != "max_guardian_logical_requests"
        },
        "max_guardian_logical_requests": identity.reference.max_guardian_logical_requests,
        "upstream_timeout_seconds": f"{identity.reference.upstream_timeout_seconds:.3f}",
        "proxy_max_attempts_per_physical_run": 1,
    }:
        raise C2BehaviorError("Plan 058 provider contract drifted")
    if not (paths.common_root / str(value["binary"].get("manifest_path"))).is_relative_to(paths.common_root / "eval-data/bin"):
        raise C2BehaviorError("Plan 058 binary manifest namespace is invalid")
    if value["binary"].get("product") != Product.RONDO_LOCAL.value or any(
        _SHA256.fullmatch(str(value["binary"].get(key))) is None
        for key in ("manifest_sha256", "binary_sha256", "code_mode_host_sha256", "bwrap_sha256")
    ):
        raise C2BehaviorError("Plan 058 binary identity is invalid")


def validate_transport_retry_evidence(value: object) -> dict[str, Any]:
    required = {
        "attempt", "attempt_run_id", "classification", "reason_code",
        "api_metadata_sha256", "budget_run_sha256", "prior_budget_run_sha256",
        "ledger_stop_reason", "upstream_attempts", "logical_request_count",
        "logical_upstream_attempts", "charged_usd",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise C2BehaviorError("Plan 058 transport retry evidence schema is invalid")
    if (
        isinstance(value["attempt"], bool)
        or not isinstance(value["attempt"], int)
        or value["attempt"] < 1
        or _SAFE_ID.fullmatch(str(value["attempt_run_id"])) is None
        or value["classification"] != "typed_pure_transport"
        or value["reason_code"] not in {
            "upstream_open_error",
            "upstream_read_error",
            "upstream_transient_http",
            "upstream_clean_eof",
            "upstream_terminal_failed",
        }
        or _SHA256.fullmatch(str(value["api_metadata_sha256"])) is None
        or _SHA256.fullmatch(str(value["budget_run_sha256"])) is None
        or (
            value["prior_budget_run_sha256"] is not None
            and _SHA256.fullmatch(str(value["prior_budget_run_sha256"])) is None
        )
        or not isinstance(value["ledger_stop_reason"], str)
        or _SAFE_ID.fullmatch(value["ledger_stop_reason"]) is None
        or isinstance(value["upstream_attempts"], bool)
        or not isinstance(value["upstream_attempts"], int)
        or value["upstream_attempts"] < 1
        or isinstance(value["logical_request_count"], bool)
        or not isinstance(value["logical_request_count"], int)
        or value["logical_request_count"] < 1
        or isinstance(value["logical_upstream_attempts"], bool)
        or not isinstance(value["logical_upstream_attempts"], int)
        or value["logical_upstream_attempts"] < value["upstream_attempts"]
        or Decimal(str(value["charged_usd"])) < 0
    ):
        raise C2BehaviorError("Plan 058 transport retry evidence is invalid")
    return json.loads(json.dumps(value))


def classify_pure_transport_retry(
    *,
    attempt: int,
    attempt_run_id: str,
    api_metadata: Mapping[str, Any],
    budget_run: Mapping[str, Any],
    logical_budget_run: Mapping[str, Any] | None = None,
    prior_retry_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return body-free evidence when every non-success terminal is transient.

    Earlier successful responses are expected in a multi-turn logical slot.
    Auth, quota/rate-limit, model/config, bad requests, and missing terminal
    accounting all fail closed as non-transport.
    """

    requests = api_metadata.get("requests")
    budget_requests = budget_run.get("requests")
    if not isinstance(requests, list) or not requests or not isinstance(budget_requests, Mapping):
        return None
    reason_codes: set[str] = set()
    request_ids: set[str] = set()
    for request in requests:
        if not isinstance(request, Mapping):
            return None
        request_id = request.get("request_id")
        status = request.get("upstream_status")
        end = request.get("stream_end_kind")
        event = request.get("terminal_event_type")
        terminal_status = request.get("terminal_response_status")
        code = str(request.get("terminal_error_code") or "").lower()
        attempts = request.get("attempt_count")
        if (
            not isinstance(request_id, str)
            or not request_id
            or request_id in request_ids
            or isinstance(attempts, bool)
            or not isinstance(attempts, int)
            or attempts < 1
            or any(fragment in code for fragment in _NON_TRANSIENT_CODE_FRAGMENTS)
        ):
            return None
        request_ids.add(request_id)
        successful = request.get("usage_valid") is True and (
            (
                request.get("stream") is True
                and end == "terminal"
                and event == "response.completed"
                and terminal_status == "completed"
                and status == 200
            )
            or (
                request.get("stream") is False
                and isinstance(status, int)
                and 200 <= status < 300
            )
        )
        if successful:
            continue
        if request.get("usage_valid") is not False:
            return None
        if end == "open_error" and status == 0:
            reason_codes.add("upstream_open_error")
        elif end == "read_error":
            reason_codes.add("upstream_read_error")
        elif end == "clean_eof" and request.get("terminal_event_type") is None:
            reason_codes.add("upstream_clean_eof")
        elif status in _TRANSIENT_HTTP_STATUSES:
            reason_codes.add("upstream_transient_http")
        elif (
            status == 200
            and end == "terminal"
            and event == "response.failed"
            and terminal_status == "failed"
            and code in _TRANSIENT_TERMINAL_ERROR_CODES
        ):
            reason_codes.add("upstream_terminal_failed")
        else:
            return None
    if not reason_codes:
        return None
    meaningful_budget = {
        str(request_id): row
        for request_id, row in budget_requests.items()
        if isinstance(row, Mapping) and int(row.get("attempt_count", 0)) >= 1
    }
    if set(meaningful_budget) != request_ids or any(
        row.get("status") != "settled" for row in meaningful_budget.values()
    ):
        return None
    upstream_attempts = sum(int(row["attempt_count"]) for row in meaningful_budget.values())
    charged = Decimal(str(budget_run.get("spent_usd")))
    logical_run = logical_budget_run or budget_run
    logical_requests = logical_run.get("requests")
    if not isinstance(logical_requests, Mapping):
        return None
    meaningful_logical = {
        str(request_id): row
        for request_id, row in logical_requests.items()
        if isinstance(row, Mapping) and int(row.get("attempt_count", 0)) >= 1
    }
    if (
        len(meaningful_logical) != len(logical_requests)
        or not request_ids.issubset(meaningful_logical)
        or any(row.get("status") != "settled" for row in meaningful_logical.values())
    ):
        return None
    logical_upstream_attempts = sum(
        int(row["attempt_count"]) for row in meaningful_logical.values()
    )
    if prior_retry_evidence is None:
        prior_digest = None
        prior_request_count = 0
        prior_upstream_attempts = 0
    else:
        try:
            prior = validate_transport_retry_evidence(prior_retry_evidence)
        except (ArithmeticError, C2BehaviorError, TypeError, ValueError):
            return None
        if prior["attempt"] != attempt - 1:
            return None
        prior_digest = prior["budget_run_sha256"]
        prior_request_count = prior["logical_request_count"]
        prior_upstream_attempts = prior["logical_upstream_attempts"]
    if (
        len(meaningful_logical) != prior_request_count + len(meaningful_budget)
        or logical_upstream_attempts != prior_upstream_attempts + upstream_attempts
    ):
        return None
    stop_reason = logical_run.get("stop_reason")
    if (
        charged < 0
        or logical_run.get("stopped") is not True
        or not isinstance(logical_run.get("infra_taint"), Mapping)
        or not isinstance(stop_reason, str)
        or _SAFE_ID.fullmatch(stop_reason) is None
    ):
        return None
    reason = next(
        candidate
        for candidate in (
            "upstream_open_error",
            "upstream_read_error",
            "upstream_transient_http",
            "upstream_clean_eof",
            "upstream_terminal_failed",
        )
        if candidate in reason_codes
    )
    encoded_metadata = json.dumps(api_metadata, sort_keys=True, separators=(",", ":")).encode()
    encoded_budget = json.dumps(logical_run, sort_keys=True, separators=(",", ":")).encode()
    return validate_transport_retry_evidence({
        "attempt": attempt,
        "attempt_run_id": attempt_run_id,
        "classification": "typed_pure_transport",
        "reason_code": reason,
        "api_metadata_sha256": hashlib.sha256(encoded_metadata).hexdigest(),
        "budget_run_sha256": hashlib.sha256(encoded_budget).hexdigest(),
        "prior_budget_run_sha256": prior_digest,
        "ledger_stop_reason": stop_reason,
        "upstream_attempts": upstream_attempts,
        "logical_request_count": len(meaningful_logical),
        "logical_upstream_attempts": logical_upstream_attempts,
        "charged_usd": f"{charged:.6f}",
    })


def classify_provider_hard_stop(api_metadata: Mapping[str, Any]) -> str | None:
    """Classify provider conditions that require repair/stop, never a product row."""

    requests = api_metadata.get("requests")
    if not isinstance(requests, list):
        return None
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        status = request.get("upstream_status")
        code = str(request.get("terminal_error_code") or "").lower()
        if status in {401, 403} or code in {
            "authentication_error",
            "invalid_api_key",
            "permission_denied",
        }:
            return "provider_authentication_or_access"
        if status == 429 or code in {
            "billing_hard_limit_reached",
            "insufficient_quota",
            "rate_limit_exceeded",
            "usage_limit_reached",
        }:
            return "provider_quota_or_rate_limit"
        if status == 404 or code in {
            "model_not_found",
            "model_unavailable",
            "unsupported_model",
        }:
            return "provider_model_unavailable"
    return None


def validate_state(value: object, *, identity: C2BehaviorIdentity) -> None:
    required = {
        "schema_version", "kind", "campaign_id", "campaign_lock_sha256", "status",
        "invalid_reason", "paid_boundary", "preflight", "slots", "final_storage", "outcome",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise C2BehaviorError("Plan 058 state schema is invalid")
    if (
        value["schema_version"] != 1
        or value["kind"] != PLAN058_KIND
        or value["campaign_id"] != identity.campaign_id
        or value["campaign_lock_sha256"] != identity.lock_sha256
        or value["status"] not in {"running", "ready_to_finalize", "invalid", "finalized"}
        or not isinstance(value["paid_boundary"], bool)
        or len(value["preflight"]) != len(identity.preflight_tasks)
        or len(value["slots"]) != len(identity.slots)
    ):
        raise C2BehaviorError("Plan 058 state identity is invalid")
    for expected, row in zip(identity.preflight_tasks, value["preflight"], strict=True):
        if (
            not isinstance(row, dict)
            or set(row) != {"task_id", "status", "attempts", "receipt_sha256", "last_error"}
            or row["task_id"] != expected.task_id
            or row["status"] not in {"pending", "running", "complete"}
            or isinstance(row["attempts"], bool)
            or not isinstance(row["attempts"], int)
            or row["attempts"] < 0
            or (row["status"] == "complete") != (_SHA256.fullmatch(str(row["receipt_sha256"])) is not None)
        ):
            raise C2BehaviorError("Plan 058 preflight state is invalid")
    for expected, row in zip(identity.slots, value["slots"], strict=True):
        required_slot = {
            "slot_id", "logical_run_id", "status", "execution_attempts",
            "current_attempt_run_id", "transport_retries", "published_attempt",
            "published_attempt_run_id", "record_sha256",
        }
        if (
            not isinstance(row, dict)
            or set(row) != required_slot
            or row["slot_id"] != expected.slot_id
            or row["logical_run_id"] != expected.logical_run_id
            or row["status"] not in _SLOT_STATUSES
            or isinstance(row["execution_attempts"], bool)
            or not isinstance(row["execution_attempts"], int)
            or row["execution_attempts"] < 0
            or not isinstance(row["transport_retries"], list)
            or len(row["transport_retries"]) > row["execution_attempts"]
        ):
            raise C2BehaviorError("Plan 058 slot state is invalid")
        retries = [validate_transport_retry_evidence(item) for item in row["transport_retries"]]
        if [item["attempt"] for item in retries] != list(range(1, len(retries) + 1)):
            raise C2BehaviorError("Plan 058 transport retry sequence is invalid")
        if any(
            item["attempt_run_id"] != expected.attempt_run_id(item["attempt"])
            for item in retries
        ):
            raise C2BehaviorError("Plan 058 transport retry identity drifted")
        if any(
            item["prior_budget_run_sha256"]
            != (retries[index - 1]["budget_run_sha256"] if index else None)
            for index, item in enumerate(retries)
        ):
            raise C2BehaviorError("Plan 058 transport retry chain drifted")
        expected_retries = {
            "pending": 0,
            "running": row["execution_attempts"] - 1,
            "retry_pending": row["execution_attempts"],
            "published": row["execution_attempts"] - 1,
        }[row["status"]]
        if expected_retries < 0 or len(retries) != expected_retries:
            raise C2BehaviorError("Plan 058 slot lifecycle is inconsistent")
        if row["status"] == "pending" and row["execution_attempts"] != 0:
            raise C2BehaviorError("Plan 058 pending slot already consumed an attempt")
        if row["status"] == "running":
            if row["current_attempt_run_id"] != expected.attempt_run_id(row["execution_attempts"]):
                raise C2BehaviorError("Plan 058 running attempt identity drifted")
        elif row["current_attempt_run_id"] is not None:
            raise C2BehaviorError("Plan 058 inactive slot retains an attempt")
        published = row["status"] == "published"
        if published != (_SHA256.fullmatch(str(row["record_sha256"])) is not None):
            raise C2BehaviorError("Plan 058 publication digest is invalid")
        if published:
            if (
                row["published_attempt"] != row["execution_attempts"]
                or row["published_attempt_run_id"] != expected.attempt_run_id(row["published_attempt"])
                or len(retries) != row["published_attempt"] - 1
            ):
                raise C2BehaviorError("Plan 058 published attempt identity is invalid")
        elif row["published_attempt"] is not None or row["published_attempt_run_id"] is not None:
            raise C2BehaviorError("Plan 058 unpublished slot has publication identity")
    if sum(row["status"] == "running" for row in value["slots"]) > 1:
        raise C2BehaviorError("Plan 058 has multiple running slots")
    if value["status"] == "ready_to_finalize" and any(row["status"] != "published" for row in value["slots"]):
        raise C2BehaviorError("Plan 058 denominator is incomplete")
    if (
        value["status"] == "ready_to_finalize"
        and value["final_storage"] is not None
        and (
            not isinstance(value["final_storage"], Mapping)
            or value["final_storage"].get("final_sample_status") != "complete"
        )
    ):
        raise C2BehaviorError("Plan 058 ready campaign lacks final resource evidence")
    if value["status"] == "invalid" and not value["invalid_reason"]:
        raise C2BehaviorError("Plan 058 invalid state lacks a reason")
    if value["status"] == "finalized" and value["outcome"] not in {
        "commissioning_complete", "diagnostic_complete", "retain", "withdraw",
        "campaign_invalid",
    }:
        raise C2BehaviorError("Plan 058 final outcome is invalid")
    if (
        value["status"] == "finalized"
        and value["outcome"] != "campaign_invalid"
        and (
            not isinstance(value["final_storage"], Mapping)
            or value["final_storage"].get("final_sample_status") != "complete"
        )
    ):
        raise C2BehaviorError("Plan 058 valid final outcome lacks resource evidence")


def build_slot_record(
    *,
    identity: C2BehaviorIdentity,
    slot: C2BehaviorSlot,
    attempt: int,
    attempt_run_id: str,
    transport_retries: Iterable[Mapping[str, Any]],
    parsed: Any,
    observation: Mapping[str, Any],
    budget_run: Mapping[str, Any],
    logical_budget: Mapping[str, Any],
    docker_receipt: Mapping[str, Any],
    sources: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind the one published physical attempt to one logical result."""

    from .bounded_observation import _validate_budget_run

    safe_observation = validate_task_observation(observation)
    try:
        outcome = RunOutcome(parsed.outcome)
    except (AttributeError, ValueError) as exc:
        raise C2BehaviorError("Plan 058 Terminal-Bench outcome is invalid") from exc
    if outcome is RunOutcome.COMPLETED and safe_observation["turn"]["status"] != "completed":
        raise C2BehaviorError("completed Plan 058 result has a non-completed trace")
    _validate_budget_run(budget_run, observation=safe_observation)
    if not isinstance(docker_receipt, Mapping) or docker_receipt.get("cleanup") != "verified_empty":
        raise C2BehaviorError("Plan 058 Docker receipt is incomplete")
    safe_sources = _validate_c2_source_binding(sources, slot=slot)
    safe_logical_budget = validate_logical_budget_summary(
        logical_budget, logical_run_id=slot.logical_run_id
    )
    safe_retries = [validate_transport_retry_evidence(item) for item in transport_retries]
    if (
        attempt_run_id != slot.attempt_run_id(attempt)
        or [item["attempt"] for item in safe_retries] != list(range(1, attempt))
        or any(
            item["attempt_run_id"] != slot.attempt_run_id(item["attempt"])
            for item in safe_retries
        )
    ):
        raise C2BehaviorError("Plan 058 published attempt sequence is invalid")
    execution = safe_sources["agent_execution"]
    agent_exit = execution["exit_code"]
    guardian_limit_stop = budget_run.get("stop_reason") == (
        "guardian_logical_request_limit_exceeded"
    )
    if agent_exit == 0:
        if (
            outcome is not RunOutcome.COMPLETED
            or guardian_limit_stop
            or execution["tee_exit_code"] != 0
            or execution["execution_id"] != attempt_run_id
        ):
            raise C2BehaviorError("Plan 058 successful agent exit projection is invalid")
    elif (
        agent_exit != 1
        or outcome is not RunOutcome.AGENT_FAILED
        or not guardian_limit_stop
        or execution["tee_exit_code"] != 0
        or execution["execution_id"] != attempt_run_id
    ):
        raise C2BehaviorError("Plan 058 typed agent failure projection is invalid")
    return {
        "schema_version": 1,
        "kind": PLAN058_KIND + "_slot",
        "campaign_id": identity.campaign_id,
        "campaign_lock_sha256": identity.lock_sha256,
        "slot": asdict(slot),
        "published_attempt": attempt,
        "published_attempt_run_id": attempt_run_id,
        "transport_retries": safe_retries,
        "product": Product.RONDO_LOCAL.value,
        "binary_sha256": identity.value["binary"]["binary_sha256"],
        "terminal_bench": {
            "outcome": outcome.value,
            "task_outcome": str(parsed.task_outcome),
            "reward": float(parsed.reward),
            "duration_seconds": float(parsed.duration_seconds),
            "input_tokens": int(parsed.input_tokens),
            "cached_tokens": int(parsed.cached_tokens),
            "output_tokens": int(parsed.output_tokens),
        },
        "budget": json.loads(json.dumps(budget_run)),
        "logical_budget": safe_logical_budget,
        "observation": safe_observation,
        "docker": dict(docker_receipt),
        "sources": safe_sources,
    }


def validate_slot_record(
    value: object,
    *,
    identity: C2BehaviorIdentity,
    slot: C2BehaviorSlot,
) -> dict[str, Any]:
    from .bounded_observation import _validate_budget_run

    keys = {
        "schema_version", "kind", "campaign_id", "campaign_lock_sha256", "slot",
        "published_attempt", "published_attempt_run_id", "transport_retries",
        "product", "binary_sha256", "terminal_bench", "budget", "observation",
        "logical_budget", "docker", "sources",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise C2BehaviorError("Plan 058 slot record schema is invalid")
    attempt = value["published_attempt"]
    if (
        value["schema_version"] != 1
        or value["kind"] != PLAN058_KIND + "_slot"
        or value["campaign_id"] != identity.campaign_id
        or value["campaign_lock_sha256"] != identity.lock_sha256
        or value["slot"] != asdict(slot)
        or value["product"] != Product.RONDO_LOCAL.value
        or value["binary_sha256"] != identity.value["binary"]["binary_sha256"]
        or isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or attempt < 1
        or value["published_attempt_run_id"] != slot.attempt_run_id(attempt)
        or not isinstance(value["transport_retries"], list)
    ):
        raise C2BehaviorError("Plan 058 slot record identity drifted")
    retries = [validate_transport_retry_evidence(item) for item in value["transport_retries"]]
    if [item["attempt"] for item in retries] != list(range(1, attempt)) or any(
        item["attempt_run_id"] != slot.attempt_run_id(item["attempt"])
        for item in retries
    ):
        raise C2BehaviorError("Plan 058 slot retry history is incomplete")
    terminal = value["terminal_bench"]
    terminal_keys = {
        "outcome", "task_outcome", "reward", "duration_seconds", "input_tokens",
        "cached_tokens", "output_tokens",
    }
    if not isinstance(terminal, dict) or set(terminal) != terminal_keys:
        raise C2BehaviorError("Plan 058 Terminal-Bench record is invalid")
    try:
        outcome = RunOutcome(terminal["outcome"])
    except ValueError as exc:
        raise C2BehaviorError("Plan 058 Terminal-Bench outcome is invalid") from exc
    observation = validate_task_observation(value["observation"])
    if outcome is RunOutcome.COMPLETED and observation["turn"]["status"] != "completed":
        raise C2BehaviorError("completed Plan 058 record has a non-completed trace")
    _validate_budget_run(value["budget"], observation=observation)
    validate_logical_budget_summary(
        value["logical_budget"], logical_run_id=slot.logical_run_id
    )
    if not isinstance(value["docker"], dict) or value["docker"].get("cleanup") != "verified_empty":
        raise C2BehaviorError("Plan 058 Docker record is invalid")
    sources = _validate_c2_source_binding(value["sources"], slot=slot)
    execution = sources["agent_execution"]
    agent_exit = execution["exit_code"]
    guardian_limit_stop = value["budget"].get("stop_reason") == (
        "guardian_logical_request_limit_exceeded"
    )
    if agent_exit == 0:
        if (
            outcome is not RunOutcome.COMPLETED
            or guardian_limit_stop
            or execution["tee_exit_code"] != 0
            or execution["execution_id"] != value["published_attempt_run_id"]
        ):
            raise C2BehaviorError("Plan 058 successful agent exit record is invalid")
    elif (
        agent_exit != 1
        or outcome is not RunOutcome.AGENT_FAILED
        or not guardian_limit_stop
        or execution["tee_exit_code"] != 0
        or execution["execution_id"] != value["published_attempt_run_id"]
    ):
        raise C2BehaviorError("Plan 058 typed agent failure record is invalid")
    return json.loads(json.dumps(value))


def _validate_c2_source_binding(
    value: object, *, slot: C2BehaviorSlot
) -> dict[str, Any]:
    """Extend the shared source binding with Plan 058's true agent exit."""

    from .bounded_observation import _validate_source_binding

    if not isinstance(value, Mapping) or set(value) != {
        "terminal_bench",
        "api_metadata",
        "native_trace",
        "agent_execution",
        "guardian_evidence",
    }:
        raise C2BehaviorError("Plan 058 private source binding is invalid")
    base = {
        key: value[key]
        for key in ("terminal_bench", "api_metadata", "native_trace")
    }
    safe_base = _validate_source_binding(base, slot=slot)  # type: ignore[arg-type]
    execution = value["agent_execution"]
    if not isinstance(execution, Mapping) or set(execution) != {
        "path",
        "sha256",
        "execution_id",
        "exit_code",
        "tee_exit_code",
    }:
        raise C2BehaviorError("Plan 058 agent execution source is invalid")
    path = execution["path"]
    exit_code = execution["exit_code"]
    tee_exit_code = execution["tee_exit_code"]
    execution_id = execution["execution_id"]
    terminal_path = Path(safe_base["terminal_bench"]["path"])
    expected_receipt = (
        terminal_path.parent / "agent" / "rondo-agent-execution.json"
    ).as_posix()
    if (
        not isinstance(path, str)
        or path != expected_receipt
        or Path(path).is_absolute()
        or ".." in Path(path).parts
        or _SHA256.fullmatch(str(execution["sha256"])) is None
        or not isinstance(execution_id, str)
        or not execution_id
        or isinstance(exit_code, bool)
        or not isinstance(exit_code, int)
        or not 0 <= exit_code <= 255
        or isinstance(tee_exit_code, bool)
        or not isinstance(tee_exit_code, int)
        or not 0 <= tee_exit_code <= 255
    ):
        raise C2BehaviorError("Plan 058 agent execution source identity is invalid")
    guardian_evidence = value["guardian_evidence"]
    if not isinstance(guardian_evidence, list) or len(guardian_evidence) > 4:
        raise C2BehaviorError("Plan 058 Guardian evidence source is invalid")
    safe_guardian: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for binding in guardian_evidence:
        if not isinstance(binding, Mapping) or set(binding) != {
            "e_final_path",
            "e_final_sha256",
            "meta_path",
            "meta_sha256",
        }:
            raise C2BehaviorError("Plan 058 Guardian evidence source is invalid")
        e_final_path = binding["e_final_path"]
        meta_path = binding["meta_path"]
        if (
            not isinstance(e_final_path, str)
            or not isinstance(meta_path, str)
            or Path(e_final_path).parent != Path(meta_path).parent
            or Path(e_final_path).name != "E_final.json"
            or Path(meta_path).name != "meta.json"
            or Path(e_final_path).parent.parent.name != "guardian-evidence"
            or not Path(e_final_path).is_relative_to(terminal_path.parent / "agent")
            or Path(e_final_path).is_absolute()
            or ".." in Path(e_final_path).parts
            or ".." in Path(meta_path).parts
            or _SHA256.fullmatch(str(binding["e_final_sha256"])) is None
            or _SHA256.fullmatch(str(binding["meta_sha256"])) is None
            or e_final_path in seen_paths
        ):
            raise C2BehaviorError("Plan 058 Guardian evidence source identity is invalid")
        seen_paths.add(e_final_path)
        safe_guardian.append({key: str(binding[key]) for key in binding})
    return {
        **safe_base,
        "agent_execution": {
            "path": path,
            "sha256": str(execution["sha256"]),
            "execution_id": execution_id,
            "exit_code": exit_code,
            "tee_exit_code": tee_exit_code,
        },
        "guardian_evidence": safe_guardian,
    }


def load_slot_records(
    paths: RepoPaths,
    identity: C2BehaviorIdentity,
    state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for slot, row in zip(identity.slots, state["slots"], strict=True):
        if row["status"] != "published":
            raise C2BehaviorError("Plan 058 logical denominator is incomplete")
        raw = _read_regular(slot_record_path(paths, identity, slot))
        if hashlib.sha256(raw).hexdigest() != row["record_sha256"]:
            raise C2BehaviorError("Plan 058 slot record digest drifted")
        record = validate_slot_record(json.loads(raw), identity=identity, slot=slot)
        if (
            record["published_attempt"] != row["published_attempt"]
            or record["published_attempt_run_id"] != row["published_attempt_run_id"]
            or record["transport_retries"] != row["transport_retries"]
        ):
            raise C2BehaviorError("Plan 058 slot state and record differ")
        records.append(record)
    return records


def validate_logical_budget_summary(
    value: object, *, logical_run_id: str
) -> dict[str, Any]:
    required = {
        "logical_run_id",
        "run_sha256",
        "spent_usd",
        "request_count",
        "upstream_attempts",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise C2BehaviorError("Plan 058 logical budget summary schema is invalid")
    try:
        spent = Decimal(str(value["spent_usd"]))
    except ArithmeticError as exc:
        raise C2BehaviorError("Plan 058 logical budget spend is invalid") from exc
    if (
        value["logical_run_id"] != logical_run_id
        or _SHA256.fullmatch(str(value["run_sha256"])) is None
        or spent < 0
        or isinstance(value["request_count"], bool)
        or not isinstance(value["request_count"], int)
        or value["request_count"] < 1
        or isinstance(value["upstream_attempts"], bool)
        or not isinstance(value["upstream_attempts"], int)
        or value["upstream_attempts"] < 1
    ):
        raise C2BehaviorError("Plan 058 logical budget summary is invalid")
    return {
        "logical_run_id": logical_run_id,
        "run_sha256": str(value["run_sha256"]),
        "spent_usd": f"{spent:.6f}",
        "request_count": int(value["request_count"]),
        "upstream_attempts": int(value["upstream_attempts"]),
    }


def validate_refined_assessment(
    records: Iterable[Mapping[str, Any]], value: object
) -> dict[str, Any]:
    records_by_slot = {str(record["slot"]["slot_id"]): record for record in records}
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "kind",
        "slots",
        "no_harm",
    }:
        raise C2BehaviorError("Plan 058 refined assessment schema is invalid")
    if value["schema_version"] != 1 or value["kind"] != "plan058_c2_refined_classification" or not isinstance(value["slots"], list):
        raise C2BehaviorError("Plan 058 refined assessment identity is invalid")
    rows: list[dict[str, Any]] = []
    for row in value["slots"]:
        keys = {"slot_id", "harmful", "reasonable", "insufficient", "harmful_duration_ms", "reasonable_duration_ms", "insufficient_duration_ms"}
        if not isinstance(row, Mapping) or set(row) != keys or row["slot_id"] not in records_by_slot:
            raise C2BehaviorError("Plan 058 refined slot classification is invalid")
        counts = (row["harmful"], row["reasonable"], row["insufficient"])
        durations = (row["harmful_duration_ms"], row["reasonable_duration_ms"], row["insufficient_duration_ms"])
        if any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in (*counts, *durations)):
            raise C2BehaviorError("Plan 058 refined classification count is invalid")
        observation = validate_task_observation(records_by_slot[str(row["slot_id"])]["observation"])
        tools = observation["tools"]
        if sum(counts) != tools["repeated_exact_commands"] or sum(durations) != tools["repeated_exact_command_lifecycle_duration_ms"]:
            raise C2BehaviorError("Plan 058 refined classification does not reconcile raw C2")
        rows.append(dict(row))
    if set(records_by_slot) != {str(row["slot_id"]) for row in rows} or len(rows) != len(records_by_slot):
        raise C2BehaviorError("Plan 058 refined classification denominator is incomplete")
    no_harm = value["no_harm"]
    no_harm_keys = {
        "reasonable_repeats_preserved",
        "recovery_and_user_control_preserved",
        "tools_remain_executable",
        "no_material_task_harm",
    }
    if (
        not isinstance(no_harm, Mapping)
        or set(no_harm) != no_harm_keys
        or any(not isinstance(no_harm[key], bool) for key in no_harm_keys)
    ):
        raise C2BehaviorError("Plan 058 no-harm assessment is incomplete")
    return {
        "method": "private_manual_frozen_rules",
        "harmful_occurrences": sum(row["harmful"] for row in rows),
        "reasonable_occurrences": sum(row["reasonable"] for row in rows),
        "insufficient_occurrences": sum(row["insufficient"] for row in rows),
        "harmful_duration_ms": sum(row["harmful_duration_ms"] for row in rows),
        "reasonable_duration_ms": sum(row["reasonable_duration_ms"] for row in rows),
        "insufficient_duration_ms": sum(row["insufficient_duration_ms"] for row in rows),
        "no_harm": dict(no_harm),
        "no_harm_passed": all(no_harm.values()),
    }


def public_result(
    *,
    identity: C2BehaviorIdentity,
    state: Mapping[str, Any],
    budget: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    refined_assessment: Mapping[str, Any] | None,
    snapshot_date: str,
) -> dict[str, Any]:
    try:
        date.fromisoformat(snapshot_date)
    except ValueError as exc:
        raise C2BehaviorError("Plan 058 snapshot date is invalid") from exc
    values = list(records)
    complete = state["status"] == "ready_to_finalize"
    if complete and len(values) != len(identity.slots):
        raise C2BehaviorError("Plan 058 result denominator is incomplete")
    if complete and int(budget["run_slots_used"]) != len(identity.slots):
        raise C2BehaviorError("Plan 058 logical budget denominator is incomplete")
    spent = Decimal(str(budget["spent_usd"]))
    if spent > identity.campaign_cap_usd or Decimal(str(budget["reserved_usd"])) != 0:
        raise C2BehaviorError("Plan 058 budget is not terminally settled")
    refined = (
        validate_refined_assessment(values, refined_assessment)
        if complete and refined_assessment is not None
        else None
    )
    if complete and refined is None:
        raise C2BehaviorError("Plan 058 complete result requires refined classification")
    outcome_counts = {outcome.value: 0 for outcome in RunOutcome}
    passes = 0
    raw_occurrences = 0
    raw_duration = 0
    for record in values:
        outcome_counts[record["terminal_bench"]["outcome"]] += 1
        passes += record["terminal_bench"]["task_outcome"] == "pass"
        observation = validate_task_observation(record["observation"])
        raw_occurrences += observation["tools"]["repeated_exact_commands"]
        raw_duration += observation["tools"]["repeated_exact_command_lifecycle_duration_ms"]
    valid = complete
    if not valid:
        outcome = "campaign_invalid"
    elif identity.campaign_mode == "commissioning":
        outcome = "commissioning_complete"
    elif identity.campaign_mode == "diagnostic":
        outcome = "diagnostic_complete"
    else:
        assert refined is not None
        outcome = (
            "retain"
            if refined["harmful_occurrences"] <= PLAN058_REFINED_TARGET
            and refined["no_harm_passed"]
            else "withdraw"
        )
    return {
        "schema_version": 1,
        "kind": PLAN058_KIND + "_result",
        "snapshot_date": snapshot_date,
        "campaign": {
            "campaign_id": identity.campaign_id,
            "campaign_mode": identity.campaign_mode,
            "campaign_lock_sha256": identity.lock_sha256,
            "v28_lock_sha256": PLAN058_V28_SHA256,
            "product": Product.RONDO_LOCAL.value,
            "model": PLAN058_MODEL,
            "main_effort": PLAN058_MAIN_EFFORT,
            "guardian_effort": PLAN058_GUARDIAN_EFFORT,
            "tasks": len(identity.preflight_tasks),
            "rounds": int(identity.value["rounds"]),
            **(
                {
                    "diagnostic_slot_range": identity.value[
                        "diagnostic_slot_range"
                    ]
                }
                if identity.campaign_mode == "diagnostic"
                else {}
            ),
            "logical_denominator": len(identity.slots),
            "logical_results_published": len(values),
            "source_validated_slots": len(values),
        },
        "status": "valid" if valid else "invalid",
        "outcome": outcome,
        "c2": {
            "raw_occurrences": raw_occurrences,
            "raw_duration_ms": raw_duration,
            "refined": refined,
            "baseline_harmful_occurrences": PLAN058_REFINED_BASELINE,
            "retain_at_most": PLAN058_REFINED_TARGET,
        },
        "terminal_bench": {
            "outcomes": outcome_counts,
            "task_passes": passes,
            "task_failures": len(values) - passes,
        },
        "budget": {
            "task_cap_usd": "50.000000",
            "prior_estimated_usd": f"{identity.prior_settled_usd:.6f}",
            "campaign_estimated_usd": f"{spent:.6f}",
            "task_estimated_usd": f"{identity.prior_settled_usd + spent:.6f}",
            "reserved_usd": "0.000000",
            "logical_runs_used": int(budget["run_slots_used"]),
            "upstream_attempts": sum(
                int(request["attempt_count"])
                for run in budget["runs"].values()
                for request in run["requests"].values()
            ),
        },
        "resources": {
            "final_storage": state.get("final_storage"),
            "transport_retries": sum(len(row["transport_retries"]) for row in state["slots"]),
        },
        "invalid_reason": state.get("invalid_reason") if not valid else None,
    }


def verify_task_budget(paths: RepoPaths, identity: C2BehaviorIdentity) -> dict[str, object]:
    return verify_active_identity(
        task_budget_path(paths.common_root, identity.task_budget_id),
        active=TaskBudgetIdentity(identity.campaign_id, identity.batch_id),
        prior_settled_usd=identity.prior_settled_usd,
        task_budget_id=PLAN058_TASK_BUDGET_ID,
        cap_usd=PLAN058_TASK_CAP_USD,
    )


def close_envelope_and_pointer(
    paths: RepoPaths,
    *,
    identity: C2BehaviorIdentity,
    terminal_status: str,
    spent_usd: Decimal,
) -> dict[str, object]:
    envelope_path = task_budget_path(paths.common_root, PLAN058_TASK_BUDGET_ID)
    envelope = load_task_budget(
        envelope_path,
        task_budget_id=PLAN058_TASK_BUDGET_ID,
        cap_usd=PLAN058_TASK_CAP_USD,
    )
    if envelope["active_identity"] is not None:
        envelope = close_task_budget(
            envelope_path,
            active=TaskBudgetIdentity(identity.campaign_id, identity.batch_id),
            terminal_status=terminal_status,
            cumulative_settled_usd=identity.prior_settled_usd + spent_usd,
            task_budget_id=PLAN058_TASK_BUDGET_ID,
            cap_usd=PLAN058_TASK_CAP_USD,
        )
    pointer_path = paths.worktree_root / PLAN058_POINTER_RELPATH
    pointer = _read_json(pointer_path)
    if pointer["active_lock"] is not None:
        pointer["active_lock"] = None
        pointer["active_lock_sha256"] = None
        _atomic_json(pointer_path, pointer, mode=0o644)
    return task_budget_status(envelope)
