"""Frozen identity and state for the Plan 056 bounded Local observation run.

This is deliberately a small, single-product campaign.  Plan 051's baseline
state machine owns two-sided comparison, replacement attempts and conditional
rounds; importing those semantics here would make a fixed 10-task x 2-round
measurement harder to reason about.  The low-level binary, budget, Docker and
trace facilities remain shared.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from ..config import RepoPaths, RuntimeConfig
from ..contracts import BinaryManifest, Product, ProviderProjection, RunOutcome
from ..harness_observation import validate_task_observation
from .__main__ import _load_manifest
from .baseline import CampaignIdentity, load_historical_campaign_identity
from .task_budget import (
    TaskBudgetIdentity,
    close_task_budget,
    load_task_budget,
    start_task_budget,
    task_budget_path,
    task_budget_status,
    verify_active_identity,
)
from .tasksets import FrozenTask

PLAN056_KIND = "rondo_direction1_bounded_observation"
PLAN056_SCHEMA_VERSION = 1
PLAN056_CAMPAIGN_ID = "plan056-direction1-bounded-observation-v1"
PLAN056_BATCH_ID = "plan056-direction1-bounded-observation-v1-batch"
PLAN056_TASK_BUDGET_ID = "plan-056-direction1-bounded-observation"
PLAN056_RESULT_NAMESPACE = "direction1-bounded-observation-v1"
PLAN056_LOCK_RELPATH = Path("eval/locks/plan056-direction1-bounded-observation-v1.json")
PLAN056_POINTER_RELPATH = Path(
    "eval/locks/plan056-direction1-bounded-observation-active.json"
)
PLAN056_PUBLIC_RESULT_RELPATH = Path(
    "eval/results/observations/plan056-direction1-bounded-observation-2026-08-22.json"
)
PLAN056_V28_RELPATH = Path("eval/locks/p2-b7-canary-baseline-v28.json")
PLAN056_V28_SHA256 = "a9567cb0ddeaa9c8e7cdfbd7253000a8453ec1ebbb03ca359deae2c048f7880b"
PLAN056_MODEL = "gpt-5.6-terra"
PLAN056_MAIN_EFFORT = "medium"
PLAN056_GUARDIAN_EFFORT = "low"
PLAN056_TASK_CAP_USD = Decimal("50.000000")
PLAN056_RUN_CAP_USD = Decimal("40.000000")
PLAN056_UNPRICED_FALLBACK_USD = Decimal("1.000000")
PLAN056_SLOT_COUNT = 20
PLAN056_ROUNDS = 2
PLAN056_TASK_COUNT = 10
PLAN056_OBSERVATION_SCHEMA_VERSION = 2
PLAN056_PAID_ACTION = "plan-056-authorized-paid-run"
_MAX_PRIVATE_JSON_BYTES = 32 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}\Z")
_TERMINAL_STATE = frozenset({"ready_to_finalize", "invalid", "finalized"})
_SLOT_STATUS = frozenset({"pending", "running", "published"})


class BoundedObservationError(RuntimeError):
    """The fixed Plan 056 contract cannot be advanced safely."""


@dataclass(frozen=True)
class BoundedObservationSlot:
    slot_id: str
    run_id: str
    round: int
    task_index: int
    task_id: str

    def validate(self) -> None:
        if (
            _SAFE_ID.fullmatch(self.slot_id) is None
            or _SAFE_ID.fullmatch(self.run_id) is None
            or self.round not in {1, 2}
            or isinstance(self.task_index, bool)
            or not 1 <= self.task_index <= PLAN056_TASK_COUNT
            or not isinstance(self.task_id, str)
            or not self.task_id.startswith("terminal-bench/")
        ):
            raise BoundedObservationError("Plan 056 slot identity is invalid")


@dataclass(frozen=True)
class BoundedObservationIdentity:
    path: Path
    lock_sha256: str
    value: Mapping[str, Any]
    reference: CampaignIdentity
    tasks: tuple[FrozenTask, ...]
    slots: tuple[BoundedObservationSlot, ...]

    @property
    def campaign_id(self) -> str:
        return str(self.value["campaign_id"])

    @property
    def batch_id(self) -> str:
        return str(self.value["batch_id"])

    @property
    def task_budget_id(self) -> str:
        return str(self.value["budget"]["task_budget_id"])

    @property
    def harness_commit(self) -> str:
        return str(self.value["harness_commit"])

    @property
    def result_namespace(self) -> str:
        return str(self.value["result_namespace"])

    @property
    def max_guardian_logical_requests(self) -> int:
        return int(self.value["provider"]["max_guardian_logical_requests"])

    @property
    def upstream_timeout_seconds(self) -> float:
        return float(self.value["provider"]["upstream_timeout_seconds"])

    @property
    def manifest_relative_path(self) -> str:
        return str(self.value["binary"]["manifest_path"])

    def slot(self, slot_id: str) -> BoundedObservationSlot:
        matches = tuple(slot for slot in self.slots if slot.slot_id == slot_id)
        if len(matches) != 1:
            raise BoundedObservationError("Plan 056 slot is not uniquely frozen")
        return matches[0]

    def task(self, task_id: str) -> FrozenTask:
        matches = tuple(task for task in self.tasks if task.task_id == task_id)
        if len(matches) != 1:
            raise BoundedObservationError("Plan 056 task is not uniquely frozen")
        return matches[0]

    def provider_projection(self, config: RuntimeConfig) -> ProviderProjection:
        provider = config.paid_provider_projection(
            model_id=PLAN056_MODEL,
            main_effort=PLAN056_MAIN_EFFORT,
            guardian_effort=PLAN056_GUARDIAN_EFFORT,
        )
        expected = dict(self.value["provider"]["public_profile"])
        if provider.to_public_dict() != expected:
            raise BoundedObservationError("Plan 056 provider profile drifted")
        return provider

    def manifest(self, paths: RepoPaths) -> BinaryManifest:
        manifest_path = paths.common_root / self.manifest_relative_path
        manifest = _load_manifest(manifest_path, paths.common_root)
        raw = _read_regular(manifest_path, max_bytes=2 * 1024 * 1024)
        binary = self.value["binary"]
        if (
            hashlib.sha256(raw).hexdigest() != binary["manifest_sha256"]
            or manifest.source_commit != binary["source_commit"]
            or manifest.source_commit != self.harness_commit
            or manifest.product != Product.RONDO_LOCAL.value
            or manifest.source_dirty
        ):
            raise BoundedObservationError("Plan 056 binary manifest drifted")
        return manifest

    def seccomp_profile(self, paths: RepoPaths) -> Path:
        expected = dict(self.value["seccomp"])
        if expected != self.reference.no_api_seccomp:
            raise BoundedObservationError("Plan 056 seccomp identity drifted from v28")
        try:
            return self.reference.validate_runtime_seccomp(
                project_root=paths.worktree_root
            )
        except ValueError as exc:
            raise BoundedObservationError("Plan 056 seccomp profile drifted") from exc

    def validate_runtime_checkout(self, paths: RepoPaths) -> None:
        """Allow identity-only descendants of the committed harness source."""

        root = paths.worktree_root
        head = _git(root, "rev-parse", "HEAD")
        if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
            raise BoundedObservationError("Plan 056 harness checkout is dirty")
        if _git_result(
            root, "merge-base", "--is-ancestor", self.harness_commit, head
        ).returncode:
            raise BoundedObservationError("Plan 056 harness commit is not an ancestor")
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
        result = _git_result(
            root,
            "diff",
            "--quiet",
            self.harness_commit,
            head,
            "--",
            *protected,
        )
        if result.returncode != 0:
            raise BoundedObservationError("Plan 056 executable projection drifted")


class BoundedObservationState:
    """Crash-safe single-writer state for the fixed preflight and paid slots."""

    def __init__(self, path: Path, *, identity: BoundedObservationIdentity) -> None:
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
            self._value = self._load()
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
            raise BoundedObservationError("Plan 056 preflight state is ambiguous")
        if running:
            row = running[0]
        else:
            row = next(
                (item for item in value["preflight"] if item["status"] == "pending"),
                None,
            )
            if row is None:
                return None
            row["status"] = "running"
        row["attempts"] += 1
        self._persist()
        return str(row["task_id"]), int(row["attempts"])

    def finish_preflight(self, task_id: str, *, receipt_sha256: str) -> None:
        if _SHA256.fullmatch(receipt_sha256) is None:
            raise BoundedObservationError("Plan 056 preflight digest is invalid")
        row = self._preflight_row(task_id)
        if row["status"] != "running":
            raise BoundedObservationError("Plan 056 preflight task is not running")
        row["status"] = "complete"
        row["receipt_sha256"] = receipt_sha256
        self._persist()

    def preflight_retry(self, task_id: str, *, reason: str) -> None:
        row = self._preflight_row(task_id)
        if row["status"] != "running" or not reason:
            raise BoundedObservationError("Plan 056 preflight retry is invalid")
        row["status"] = "pending"
        row["last_error"] = reason[:256]
        self._persist()

    def claim_or_resume_slot(self) -> tuple[BoundedObservationSlot, int] | None:
        value = self._require()
        if value["status"] != "running":
            return None
        if any(row["status"] != "complete" for row in value["preflight"]):
            raise BoundedObservationError("Plan 056 preflight is incomplete")
        running = [row for row in value["slots"] if row["status"] == "running"]
        if len(running) > 1:
            raise BoundedObservationError("Plan 056 paid state is ambiguous")
        if running:
            row = running[0]
        else:
            row = next(
                (item for item in value["slots"] if item["status"] == "pending"),
                None,
            )
            if row is None:
                value["status"] = "ready_to_finalize"
                self._persist()
                return None
            row["status"] = "running"
        if row["execution_attempts"] >= 3:
            self.invalidate("unsent_execution_attempt_bound_exceeded")
            return None
        row["execution_attempts"] += 1
        self._persist()
        return self.identity.slot(str(row["slot_id"])), int(row["execution_attempts"])

    def publish_slot(self, slot_id: str, *, record_sha256: str) -> None:
        if _SHA256.fullmatch(record_sha256) is None:
            raise BoundedObservationError("Plan 056 slot record digest is invalid")
        row = self._slot_row(slot_id)
        if row["status"] != "running":
            raise BoundedObservationError("Plan 056 slot is not running")
        row["status"] = "published"
        row["record_sha256"] = record_sha256
        if all(item["status"] == "published" for item in self._require()["slots"]):
            self._require()["status"] = "ready_to_finalize"
        self._persist()

    def mark_formal_boundary(self) -> None:
        value = self._require()
        if not value["formal_boundary"]:
            value["formal_boundary"] = True
            self._persist()

    def invalidate(self, reason: str) -> None:
        value = self._require()
        if value["status"] == "finalized":
            raise BoundedObservationError(
                "finalized Plan 056 state cannot be invalidated"
            )
        if not isinstance(reason, str) or not reason:
            raise BoundedObservationError("Plan 056 invalidation reason is missing")
        value["status"] = "invalid"
        value["invalid_reason"] = reason[:512]
        self._persist()

    def store_final_storage(self, receipt: Mapping[str, object]) -> None:
        value = self._require()
        if value["status"] not in _TERMINAL_STATE:
            raise BoundedObservationError("Plan 056 storage close is premature")
        if value.get("final_storage") is not None:
            if value["final_storage"] != receipt:
                raise BoundedObservationError("Plan 056 final storage receipt drifted")
            return
        value["final_storage"] = dict(receipt)
        self._persist()

    def finalize(self, *, outcome: str, selected_candidate: str | None) -> None:
        value = self._require()
        if value["status"] not in {"ready_to_finalize", "invalid", "finalized"}:
            raise BoundedObservationError("Plan 056 campaign is not terminal")
        if value["status"] == "finalized":
            if (
                value.get("outcome") != outcome
                or value.get("selected_candidate") != selected_candidate
            ):
                raise BoundedObservationError("Plan 056 final outcome drifted")
            return
        value["status"] = "finalized"
        value["outcome"] = outcome
        value["selected_candidate"] = selected_candidate
        self._persist()

    def _load(self) -> dict[str, Any]:
        value = _read_json(self.path)
        validate_state(value, identity=self.identity)
        return value

    def _require(self) -> dict[str, Any]:
        if self._value is None:
            raise BoundedObservationError("Plan 056 state is not locked")
        return self._value

    def _preflight_row(self, task_id: str) -> dict[str, Any]:
        matches = [
            row for row in self._require()["preflight"] if row["task_id"] == task_id
        ]
        if len(matches) != 1:
            raise BoundedObservationError("Plan 056 preflight task is ambiguous")
        return matches[0]

    def _slot_row(self, slot_id: str) -> dict[str, Any]:
        matches = [row for row in self._require()["slots"] if row["slot_id"] == slot_id]
        if len(matches) != 1:
            raise BoundedObservationError("Plan 056 slot state is ambiguous")
        return matches[0]

    def _persist(self) -> None:
        value = self._require()
        validate_state(value, identity=self.identity)
        _atomic_json(self.path, value, mode=0o600)

    def _release(self) -> None:
        handle = self._handle
        self._value = None
        self._handle = None
        if handle is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()


def campaign_root(paths: RepoPaths, identity: BoundedObservationIdentity) -> Path:
    return paths.common_root / "eval-data/campaigns" / identity.campaign_id


def state_path(paths: RepoPaths, identity: BoundedObservationIdentity) -> Path:
    return campaign_root(paths, identity) / "state.json"


def budget_path(paths: RepoPaths, identity: BoundedObservationIdentity) -> Path:
    return paths.common_root / "eval-data/budgets" / f"{identity.batch_id}.json"


def slot_root(
    paths: RepoPaths, identity: BoundedObservationIdentity, slot: BoundedObservationSlot
) -> Path:
    return campaign_root(paths, identity) / "slots" / slot.slot_id


def slot_record_path(
    paths: RepoPaths, identity: BoundedObservationIdentity, slot: BoundedObservationSlot
) -> Path:
    return slot_root(paths, identity, slot) / "record.json"


def preflight_receipt_path(
    paths: RepoPaths, identity: BoundedObservationIdentity, task: FrozenTask
) -> Path:
    return campaign_root(paths, identity) / "preflight" / f"{task.slug}.json"


def load_identity(
    paths: RepoPaths, *, allow_retired: bool = False
) -> BoundedObservationIdentity:
    pointer_path = paths.worktree_root / PLAN056_POINTER_RELPATH
    pointer = _read_json(pointer_path)
    if set(pointer) != {"schema_version", "kind", "active_lock", "active_lock_sha256"}:
        raise BoundedObservationError("Plan 056 active pointer schema is invalid")
    if pointer["schema_version"] != 1 or pointer["kind"] != PLAN056_KIND:
        raise BoundedObservationError("Plan 056 active pointer identity is invalid")
    active_lock = pointer["active_lock"]
    active_sha = pointer["active_lock_sha256"]
    if active_lock is None:
        if allow_retired:
            active_lock = PLAN056_LOCK_RELPATH.as_posix()
            raw = _read_regular(paths.worktree_root / PLAN056_LOCK_RELPATH)
            active_sha = hashlib.sha256(raw).hexdigest()
        else:
            raise BoundedObservationError("Plan 056 active pointer is retired")
    if (
        active_lock != PLAN056_LOCK_RELPATH.as_posix()
        or _SHA256.fullmatch(str(active_sha)) is None
    ):
        raise BoundedObservationError(
            "Plan 056 active pointer differs from its namespace"
        )
    lock_path = paths.worktree_root / str(active_lock)
    raw = _read_regular(lock_path)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != active_sha:
        raise BoundedObservationError("Plan 056 lock digest differs from its pointer")
    value = _decode_json(raw, "Plan 056 lock")
    reference = _load_v28_reference(paths)
    tasks = tuple(reference.catalog.tasks)
    slots = tuple(BoundedObservationSlot(**row) for row in value.get("slots", []))
    identity = BoundedObservationIdentity(
        lock_path, digest, value, reference, tasks, slots
    )
    validate_identity(identity, paths=paths)
    return identity


def initialize_identity(
    paths: RepoPaths,
    *,
    runtime_manifest: Path,
    run_id_date: str,
    run_id_sequence_base: int,
) -> BoundedObservationIdentity:
    """Freeze the one Plan 056 identity before any formal evidence is written."""

    lock_path = paths.worktree_root / PLAN056_LOCK_RELPATH
    pointer_path = paths.worktree_root / PLAN056_POINTER_RELPATH
    if any(path.exists() or path.is_symlink() for path in (lock_path, pointer_path)):
        raise BoundedObservationError("Plan 056 identity already exists")
    if not re.fullmatch(r"20[0-9]{6}", run_id_date):
        raise BoundedObservationError("Plan 056 run date is invalid")
    if (
        isinstance(run_id_sequence_base, bool)
        or not isinstance(run_id_sequence_base, int)
        or not 1 <= run_id_sequence_base <= 999_999_980
    ):
        raise BoundedObservationError("Plan 056 run sequence base is invalid")
    if _git(paths.worktree_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise BoundedObservationError("Plan 056 initialize requires a clean worktree")
    harness_commit = _git(paths.worktree_root, "rev-parse", "HEAD")
    if _COMMIT.fullmatch(harness_commit) is None:
        raise BoundedObservationError("Plan 056 harness commit is invalid")
    reference = _load_v28_reference(paths)
    raw_manifest = _read_regular(runtime_manifest, max_bytes=2 * 1024 * 1024)
    manifest = _load_manifest(runtime_manifest, paths.common_root)
    if (
        manifest.source_dirty
        or manifest.source_commit != harness_commit
        or manifest.product != Product.RONDO_LOCAL.value
    ):
        raise BoundedObservationError(
            "Plan 056 manifest does not bind clean Local source"
        )
    config = _load_runtime_config_without_secret(paths)
    provider = config.paid_provider_projection(
        model_id=PLAN056_MODEL,
        main_effort=PLAN056_MAIN_EFFORT,
        guardian_effort=PLAN056_GUARDIAN_EFFORT,
    )
    public_provider = provider.to_public_dict()
    v28_provider = {key: reference.selected_profile[key] for key in public_provider}
    if public_provider != v28_provider:
        raise BoundedObservationError("Plan 056 provider differs from frozen v28")
    tasks = tuple(reference.catalog.tasks)
    if len(tasks) != PLAN056_TASK_COUNT:
        raise BoundedObservationError("Plan 056 v28 task denominator drifted")
    slots = [
        asdict(slot)
        for slot in freeze_slots(
            tasks, run_id_date=run_id_date, run_id_sequence_base=run_id_sequence_base
        )
    ]
    try:
        manifest_relative = runtime_manifest.resolve(strict=True).relative_to(
            paths.common_root.resolve(strict=True)
        )
    except (OSError, ValueError) as exc:
        raise BoundedObservationError(
            "Plan 056 manifest is outside the common root"
        ) from exc
    value: dict[str, Any] = {
        "schema_version": PLAN056_SCHEMA_VERSION,
        "kind": PLAN056_KIND,
        "campaign_id": PLAN056_CAMPAIGN_ID,
        "batch_id": PLAN056_BATCH_ID,
        "result_namespace": PLAN056_RESULT_NAMESPACE,
        "harness_commit": harness_commit,
        "source": {
            "v28_lock_path": PLAN056_V28_RELPATH.as_posix(),
            "v28_lock_sha256": PLAN056_V28_SHA256,
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
        },
        "seccomp": dict(reference.no_api_seccomp),
        "budget": {
            "task_budget_id": PLAN056_TASK_BUDGET_ID,
            "task_budget_cap_usd": f"{PLAN056_TASK_CAP_USD:.6f}",
            "prior_estimated_usd": "0.000000",
            "campaign_cap_usd": f"{PLAN056_TASK_CAP_USD:.6f}",
            "run_cap_usd": f"{PLAN056_RUN_CAP_USD:.6f}",
            "max_runs": PLAN056_SLOT_COUNT,
            "unpriced_attempt_fallback_usd": f"{PLAN056_UNPRICED_FALLBACK_USD:.6f}",
            "unpriced_fallback_accounting": "per_upstream_attempt",
        },
        "observation": {
            "schema_version": PLAN056_OBSERVATION_SCHEMA_VERSION,
            "trace_root": "/logs/agent/rollout-trace",
            "body_free": True,
        },
        "candidate_contract": {
            "eligible": ["C1", "C2", "C11"],
            "c7": "unmeasurable",
            "c1_c2_min_tasks": 2,
            "c1_c2_required_rounds": [1, 2],
            "ranking": [
                "affected_task_count_desc",
                "failed_slot_count_desc",
                "timed_burden_slot_count_desc",
                "behavior_risk_asc",
                "candidate_id_asc",
            ],
            "behavior_risk": {"C2": 1, "C1": 2, "C11": 3},
        },
        "tasks": [asdict(task) for task in tasks],
        "slots": slots,
    }
    encoded = _json_bytes(value)
    _atomic_bytes(lock_path, encoded, mode=0o644)
    digest = hashlib.sha256(encoded).hexdigest()
    _atomic_json(
        pointer_path,
        {
            "schema_version": 1,
            "kind": PLAN056_KIND,
            "active_lock": PLAN056_LOCK_RELPATH.as_posix(),
            "active_lock_sha256": digest,
        },
        mode=0o644,
    )
    identity = load_identity(paths)
    root = campaign_root(paths, identity)
    root.mkdir(parents=True, exist_ok=False, mode=0o700)
    initial_state = {
        "schema_version": 1,
        "kind": PLAN056_KIND,
        "campaign_id": identity.campaign_id,
        "campaign_lock_sha256": identity.lock_sha256,
        "status": "running",
        "invalid_reason": None,
        "formal_boundary": False,
        "preflight": [
            {
                "task_id": task.task_id,
                "status": "pending",
                "attempts": 0,
                "receipt_sha256": None,
                "last_error": None,
            }
            for task in tasks
        ],
        "slots": [
            {
                "slot_id": slot.slot_id,
                "run_id": slot.run_id,
                "status": "pending",
                "execution_attempts": 0,
                "record_sha256": None,
            }
            for slot in identity.slots
        ],
        "final_storage": None,
        "outcome": None,
        "selected_candidate": None,
    }
    _atomic_json(state_path(paths, identity), initial_state, mode=0o600)
    start_task_budget(
        task_budget_path(paths.common_root, identity.task_budget_id),
        active=TaskBudgetIdentity(identity.campaign_id, identity.batch_id),
        task_budget_id=identity.task_budget_id,
        cap_usd=PLAN056_TASK_CAP_USD,
    )
    return identity


def freeze_slots(
    tasks: Iterable[FrozenTask],
    *,
    run_id_date: str,
    run_id_sequence_base: int,
) -> tuple[BoundedObservationSlot, ...]:
    """Return the immutable round-major 10 x 2 Plan 056 denominator."""

    values = tuple(tasks)
    if len(values) != PLAN056_TASK_COUNT or not re.fullmatch(
        r"20[0-9]{6}", run_id_date
    ):
        raise BoundedObservationError("Plan 056 slot input denominator is invalid")
    if (
        isinstance(run_id_sequence_base, bool)
        or not isinstance(run_id_sequence_base, int)
        or not 1 <= run_id_sequence_base <= 999_999_980
    ):
        raise BoundedObservationError("Plan 056 run sequence base is invalid")
    slots: list[BoundedObservationSlot] = []
    sequence = run_id_sequence_base
    for round_number in range(1, PLAN056_ROUNDS + 1):
        for task_index, task in enumerate(values, start=1):
            task.validate()
            slot = BoundedObservationSlot(
                slot_id=f"r{round_number:02d}-t{task_index:02d}-{task.slug}",
                run_id=f"{run_id_date}-{sequence:09d}-tb-rondo-plan056",
                round=round_number,
                task_index=task_index,
                task_id=task.task_id,
            )
            slot.validate()
            slots.append(slot)
            sequence += 1
    return tuple(slots)


def validate_identity(
    identity: BoundedObservationIdentity, *, paths: RepoPaths
) -> None:
    value = identity.value
    expected_keys = {
        "schema_version",
        "kind",
        "campaign_id",
        "batch_id",
        "result_namespace",
        "harness_commit",
        "source",
        "binary",
        "provider",
        "seccomp",
        "budget",
        "observation",
        "candidate_contract",
        "tasks",
        "slots",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise BoundedObservationError("Plan 056 identity schema is invalid")
    if (
        value["schema_version"] != PLAN056_SCHEMA_VERSION
        or value["kind"] != PLAN056_KIND
        or value["campaign_id"] != PLAN056_CAMPAIGN_ID
        or value["batch_id"] != PLAN056_BATCH_ID
        or value["result_namespace"] != PLAN056_RESULT_NAMESPACE
        or _COMMIT.fullmatch(str(value["harness_commit"])) is None
    ):
        raise BoundedObservationError("Plan 056 identity header is invalid")
    source = value["source"]
    if source != {
        "v28_lock_path": PLAN056_V28_RELPATH.as_posix(),
        "v28_lock_sha256": PLAN056_V28_SHA256,
        "taskset_sha256": identity.reference.taskset_sha256,
        "canary_catalog_sha256": identity.reference.canary_catalog_sha256,
        "terminal_bench_commit": identity.reference.terminal_bench_commit,
    }:
        raise BoundedObservationError("Plan 056 v28 source binding drifted")
    if value["seccomp"] != identity.reference.no_api_seccomp:
        raise BoundedObservationError("Plan 056 seccomp binding drifted")
    budget = value["budget"]
    if budget != {
        "task_budget_id": PLAN056_TASK_BUDGET_ID,
        "task_budget_cap_usd": "50.000000",
        "prior_estimated_usd": "0.000000",
        "campaign_cap_usd": "50.000000",
        "run_cap_usd": "40.000000",
        "max_runs": PLAN056_SLOT_COUNT,
        "unpriced_attempt_fallback_usd": "1.000000",
        "unpriced_fallback_accounting": "per_upstream_attempt",
    }:
        raise BoundedObservationError("Plan 056 budget contract drifted")
    if value["observation"] != {
        "schema_version": 2,
        "trace_root": "/logs/agent/rollout-trace",
        "body_free": True,
    }:
        raise BoundedObservationError("Plan 056 observation contract drifted")
    if value["candidate_contract"] != {
        "eligible": ["C1", "C2", "C11"],
        "c7": "unmeasurable",
        "c1_c2_min_tasks": 2,
        "c1_c2_required_rounds": [1, 2],
        "ranking": [
            "affected_task_count_desc",
            "failed_slot_count_desc",
            "timed_burden_slot_count_desc",
            "behavior_risk_asc",
            "candidate_id_asc",
        ],
        "behavior_risk": {"C2": 1, "C1": 2, "C11": 3},
    }:
        raise BoundedObservationError("Plan 056 candidate contract drifted")
    expected_tasks = [asdict(task) for task in identity.tasks]
    if value["tasks"] != expected_tasks or len(identity.tasks) != PLAN056_TASK_COUNT:
        raise BoundedObservationError("Plan 056 task freeze drifted")
    if len(identity.slots) != PLAN056_SLOT_COUNT:
        raise BoundedObservationError("Plan 056 slot denominator drifted")
    for slot in identity.slots:
        slot.validate()
    if (
        len({slot.slot_id for slot in identity.slots}) != PLAN056_SLOT_COUNT
        or len({slot.run_id for slot in identity.slots}) != PLAN056_SLOT_COUNT
    ):
        raise BoundedObservationError("Plan 056 slot identities are not unique")
    expected_order = [
        (round_number, index, task.task_id)
        for round_number in (1, 2)
        for index, task in enumerate(identity.tasks, start=1)
    ]
    actual_order = [
        (slot.round, slot.task_index, slot.task_id) for slot in identity.slots
    ]
    if actual_order != expected_order:
        raise BoundedObservationError("Plan 056 slot order drifted")
    if any(
        value["provider"]["public_profile"].get(key) != expected
        for key, expected in {
            "main_model": PLAN056_MODEL,
            "guardian_model": PLAN056_MODEL,
            "main_effort": PLAN056_MAIN_EFFORT,
            "guardian_effort": PLAN056_GUARDIAN_EFFORT,
        }.items()
    ):
        raise BoundedObservationError("Plan 056 model or effort drifted")
    expected_provider = {
        key: candidate
        for key, candidate in identity.reference.selected_profile.items()
        if key != "max_guardian_logical_requests"
    }
    if value["provider"] != {
        "public_profile": expected_provider,
        "max_guardian_logical_requests": identity.reference.max_guardian_logical_requests,
        "upstream_timeout_seconds": f"{identity.reference.upstream_timeout_seconds:.3f}",
    }:
        raise BoundedObservationError("Plan 056 provider contract drifted")
    binary = value["binary"]
    if (
        binary.get("product") != Product.RONDO_LOCAL.value
        or binary.get("source_commit") != value["harness_commit"]
        or any(
            _SHA256.fullmatch(str(binary.get(key))) is None
            for key in (
                "manifest_sha256",
                "binary_sha256",
                "code_mode_host_sha256",
                "bwrap_sha256",
            )
        )
    ):
        raise BoundedObservationError("Plan 056 binary identity is invalid")
    if not (paths.common_root / str(binary.get("manifest_path"))).is_relative_to(
        paths.common_root / "eval-data/bin"
    ):
        raise BoundedObservationError("Plan 056 binary manifest namespace is invalid")


def validate_state(value: object, *, identity: BoundedObservationIdentity) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "kind",
        "campaign_id",
        "campaign_lock_sha256",
        "status",
        "invalid_reason",
        "formal_boundary",
        "preflight",
        "slots",
        "final_storage",
        "outcome",
        "selected_candidate",
    }:
        raise BoundedObservationError("Plan 056 state schema is invalid")
    if (
        value["schema_version"] != 1
        or value["kind"] != PLAN056_KIND
        or value["campaign_id"] != identity.campaign_id
        or value["campaign_lock_sha256"] != identity.lock_sha256
        or value["status"]
        not in {"running", "ready_to_finalize", "invalid", "finalized"}
        or not isinstance(value["formal_boundary"], bool)
        or not isinstance(value["preflight"], list)
        or not isinstance(value["slots"], list)
    ):
        raise BoundedObservationError("Plan 056 state identity is invalid")
    if (
        len(value["preflight"]) != PLAN056_TASK_COUNT
        or len(value["slots"]) != PLAN056_SLOT_COUNT
    ):
        raise BoundedObservationError("Plan 056 state denominator drifted")
    for expected, row in zip(identity.tasks, value["preflight"], strict=True):
        if (
            not isinstance(row, dict)
            or set(row)
            != {"task_id", "status", "attempts", "receipt_sha256", "last_error"}
            or row["task_id"] != expected.task_id
            or row["status"] not in {"pending", "running", "complete"}
            or isinstance(row["attempts"], bool)
            or not isinstance(row["attempts"], int)
            or row["attempts"] < 0
            or (row["status"] == "complete")
            != (_SHA256.fullmatch(str(row["receipt_sha256"])) is not None)
        ):
            raise BoundedObservationError("Plan 056 preflight state is invalid")
    for expected, row in zip(identity.slots, value["slots"], strict=True):
        if (
            not isinstance(row, dict)
            or set(row)
            != {"slot_id", "run_id", "status", "execution_attempts", "record_sha256"}
            or row["slot_id"] != expected.slot_id
            or row["run_id"] != expected.run_id
            or row["status"] not in _SLOT_STATUS
            or isinstance(row["execution_attempts"], bool)
            or not isinstance(row["execution_attempts"], int)
            or not 0 <= row["execution_attempts"] <= 3
            or (row["status"] == "published")
            != (_SHA256.fullmatch(str(row["record_sha256"])) is not None)
        ):
            raise BoundedObservationError("Plan 056 slot state is invalid")
    if sum(row["status"] == "running" for row in value["slots"]) > 1:
        raise BoundedObservationError("Plan 056 has multiple running slots")
    if value["status"] == "ready_to_finalize" and any(
        row["status"] != "published" for row in value["slots"]
    ):
        raise BoundedObservationError("Plan 056 terminal denominator is incomplete")
    if value["status"] == "invalid" and not value["invalid_reason"]:
        raise BoundedObservationError("Plan 056 invalid state lacks a reason")
    if value["status"] == "finalized" and value["outcome"] not in {
        "candidate_selected",
        "no_candidate",
        "campaign_invalid",
    }:
        raise BoundedObservationError("Plan 056 final outcome is invalid")


def build_slot_record(
    *,
    identity: BoundedObservationIdentity,
    slot: BoundedObservationSlot,
    parsed: Any,
    observation: Mapping[str, Any],
    budget_run: Mapping[str, Any],
    docker_receipt: Mapping[str, Any],
    sources: Mapping[str, Any],
) -> dict[str, Any]:
    safe_observation = validate_task_observation(observation)
    try:
        outcome = RunOutcome(parsed.outcome)
    except (AttributeError, ValueError) as exc:
        raise BoundedObservationError(
            "Plan 056 Terminal-Bench outcome is invalid"
        ) from exc
    if (
        outcome is RunOutcome.COMPLETED
        and safe_observation["turn"]["status"] != "completed"
    ):
        raise BoundedObservationError(
            "completed Terminal-Bench slot has a non-completed trace"
        )
    _validate_budget_run(budget_run, observation=safe_observation)
    if (
        not isinstance(docker_receipt, Mapping)
        or docker_receipt.get("cleanup") != "verified_empty"
    ):
        raise BoundedObservationError("Plan 056 Docker receipt is incomplete")
    safe_sources = _validate_source_binding(sources, slot=slot)
    return {
        "schema_version": 1,
        "kind": PLAN056_KIND + "_slot",
        "campaign_id": identity.campaign_id,
        "campaign_lock_sha256": identity.lock_sha256,
        "slot": asdict(slot),
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
        "observation": safe_observation,
        "docker": dict(docker_receipt),
        "sources": safe_sources,
    }


def validate_slot_record(
    value: object,
    *,
    identity: BoundedObservationIdentity,
    slot: BoundedObservationSlot,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "kind",
        "campaign_id",
        "campaign_lock_sha256",
        "slot",
        "product",
        "binary_sha256",
        "terminal_bench",
        "budget",
        "observation",
        "docker",
        "sources",
    }:
        raise BoundedObservationError("Plan 056 slot record schema is invalid")
    if (
        value["schema_version"] != 1
        or value["kind"] != PLAN056_KIND + "_slot"
        or value["campaign_id"] != identity.campaign_id
        or value["campaign_lock_sha256"] != identity.lock_sha256
        or value["slot"] != asdict(slot)
        or value["product"] != Product.RONDO_LOCAL.value
        or value["binary_sha256"] != identity.value["binary"]["binary_sha256"]
    ):
        raise BoundedObservationError("Plan 056 slot record identity drifted")
    terminal = value["terminal_bench"]
    if not isinstance(terminal, dict) or set(terminal) != {
        "outcome",
        "task_outcome",
        "reward",
        "duration_seconds",
        "input_tokens",
        "cached_tokens",
        "output_tokens",
    }:
        raise BoundedObservationError("Plan 056 Terminal-Bench record is invalid")
    try:
        outcome = RunOutcome(terminal["outcome"])
    except ValueError as exc:
        raise BoundedObservationError(
            "Plan 056 Terminal-Bench outcome is invalid"
        ) from exc
    observation = validate_task_observation(value["observation"])
    if outcome is RunOutcome.COMPLETED and observation["turn"]["status"] != "completed":
        raise BoundedObservationError(
            "completed Terminal-Bench slot has a non-completed trace"
        )
    _validate_budget_run(value["budget"], observation=observation)
    docker = value["docker"]
    if not isinstance(docker, dict) or docker.get("cleanup") != "verified_empty":
        raise BoundedObservationError("Plan 056 Docker record is invalid")
    _validate_source_binding(value["sources"], slot=slot)
    return json.loads(json.dumps(value))


def _validate_source_binding(
    value: object, *, slot: BoundedObservationSlot
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "terminal_bench",
        "api_metadata",
        "native_trace",
    }:
        raise BoundedObservationError("Plan 056 private source binding is invalid")
    terminal = value["terminal_bench"]
    metadata = value["api_metadata"]
    trace = value["native_trace"]
    if (
        not isinstance(terminal, Mapping)
        or set(terminal) != {"path", "sha256", "host_returncode"}
        or not isinstance(metadata, Mapping)
        or set(metadata) != {"path", "sha256"}
        or not isinstance(trace, Mapping)
        or set(trace) != {"path", "tree_sha256", "file_count", "total_bytes"}
    ):
        raise BoundedObservationError("Plan 056 private source schema is invalid")
    paths = (terminal["path"], metadata["path"], trace["path"])
    prefix = f"slots/{slot.slot_id}/attempt-"
    if any(
        not isinstance(path, str)
        or not path.startswith(prefix)
        or Path(path).is_absolute()
        or ".." in Path(path).parts
        for path in paths
    ):
        raise BoundedObservationError("Plan 056 private source path is invalid")
    attempt_roots = {"/".join(str(path).split("/")[:3]) for path in paths}
    if len(attempt_roots) != 1:
        raise BoundedObservationError("Plan 056 private sources span attempts")
    if (
        _SHA256.fullmatch(str(terminal["sha256"])) is None
        or _SHA256.fullmatch(str(metadata["sha256"])) is None
        or _SHA256.fullmatch(str(trace["tree_sha256"])) is None
        or isinstance(terminal["host_returncode"], bool)
        or not isinstance(terminal["host_returncode"], int)
        or isinstance(trace["file_count"], bool)
        or not isinstance(trace["file_count"], int)
        or not 1 <= trace["file_count"] <= 100_000
        or isinstance(trace["total_bytes"], bool)
        or not isinstance(trace["total_bytes"], int)
        or not 1 <= trace["total_bytes"] <= 2 * 1024**3
    ):
        raise BoundedObservationError("Plan 056 private source digest is invalid")
    return json.loads(json.dumps(value))


def assess_candidates(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    values = list(records)
    if len(values) != PLAN056_SLOT_COUNT:
        raise BoundedObservationError("Plan 056 candidate denominator is not 20")
    candidates: dict[str, dict[str, Any]] = {}
    for candidate in ("C1", "C2", "C11"):
        affected = []
        for record in values:
            observation = validate_task_observation(record["observation"])
            terminal = record["terminal_bench"]
            tools = observation["tools"]
            errors = observation["errors"]
            if candidate == "C1":
                occurrence = (
                    tools["model_visible_presentation_truncations"]
                    + tools["model_visible_collection_omission_events"]
                )
                impact = tools["model_visible_collection_omitted_bytes"]
                hit = occurrence > 0 or impact > 0
            elif candidate == "C2":
                occurrence = tools["repeated_exact_commands"]
                impact = tools["repeated_exact_command_lifecycle_duration_ms"]
                hit = occurrence > 0 and impact > 0
            else:
                occurrence = errors["context_window_exceeded"]
                impact = occurrence
                hit = occurrence > 0 and (
                    terminal["task_outcome"] == "fail"
                    or observation["turn"]["status"] != "completed"
                )
            if hit:
                affected.append((record, occurrence, impact))
        task_ids = {item[0]["slot"]["task_id"] for item in affected}
        rounds = {item[0]["slot"]["round"] for item in affected}
        failed = sum(
            item[0]["terminal_bench"]["task_outcome"] == "fail" for item in affected
        )
        eligible = (
            bool(affected)
            if candidate == "C11"
            else rounds == {1, 2} and len(task_ids) >= 2
        )
        candidates[candidate] = {
            "eligible": eligible,
            "affected_slots": len(affected),
            "affected_tasks": len(task_ids),
            "rounds_observed": sorted(rounds),
            "failed_slots": failed,
            "timed_burden_slots": len(affected) if candidate == "C2" else 0,
            "occurrences": sum(item[1] for item in affected),
            "impact": sum(item[2] for item in affected),
        }
    risk = {"C2": 1, "C1": 2, "C11": 3}
    eligible = [name for name, facts in candidates.items() if facts["eligible"]]
    selected = (
        min(
            eligible,
            key=lambda name: (
                -candidates[name]["affected_tasks"],
                -candidates[name]["failed_slots"],
                -candidates[name]["timed_burden_slots"],
                risk[name],
                name,
            ),
        )
        if eligible
        else None
    )
    return {
        "selected_candidate": selected,
        "decision": "candidate_selected" if selected else "no_candidate",
        "candidates": candidates,
        "c7": {"status": "unmeasurable"},
    }


def load_slot_records(
    paths: RepoPaths,
    identity: BoundedObservationIdentity,
    state: Mapping[str, Any],
) -> list[dict[str, Any]]:
    rows = state.get("slots")
    if not isinstance(rows, list):
        raise BoundedObservationError("Plan 056 state has no slot rows")
    records = []
    for slot, row in zip(identity.slots, rows, strict=True):
        if row.get("status") != "published":
            raise BoundedObservationError("Plan 056 slot publication is incomplete")
        path = slot_record_path(paths, identity, slot)
        raw = _read_regular(path, max_bytes=_MAX_PRIVATE_JSON_BYTES)
        if hashlib.sha256(raw).hexdigest() != row.get("record_sha256"):
            raise BoundedObservationError("Plan 056 slot record digest drifted")
        records.append(
            validate_slot_record(
                _decode_json(raw, "Plan 056 slot record"), identity=identity, slot=slot
            )
        )
    return records


def public_result(
    *,
    identity: BoundedObservationIdentity,
    state: Mapping[str, Any],
    budget: Mapping[str, Any],
    records: Iterable[Mapping[str, Any]],
    snapshot_date: str,
) -> dict[str, Any]:
    try:
        date.fromisoformat(snapshot_date)
    except ValueError as exc:
        raise BoundedObservationError("Plan 056 snapshot date is invalid") from exc
    values = list(records)
    valid = state["status"] == "ready_to_finalize"
    assessment = assess_candidates(values) if valid else None
    spent = Decimal(str(budget["spent_usd"]))
    if spent > PLAN056_TASK_CAP_USD or Decimal(str(budget["reserved_usd"])) != 0:
        raise BoundedObservationError("Plan 056 budget is not terminally settled")
    outcome_counts = {outcome.value: 0 for outcome in RunOutcome}
    reward_passes = 0
    for record in values:
        outcome_counts[record["terminal_bench"]["outcome"]] += 1
        reward_passes += record["terminal_bench"]["task_outcome"] == "pass"
    result = {
        "schema_version": 1,
        "kind": PLAN056_KIND + "_result",
        "snapshot_date": snapshot_date,
        "campaign": {
            "campaign_id": identity.campaign_id,
            "campaign_lock_sha256": identity.lock_sha256,
            "v28_lock_sha256": PLAN056_V28_SHA256,
            "product": Product.RONDO_LOCAL.value,
            "model": PLAN056_MODEL,
            "main_effort": PLAN056_MAIN_EFFORT,
            "guardian_effort": PLAN056_GUARDIAN_EFFORT,
            "tasks": PLAN056_TASK_COUNT,
            "rounds": PLAN056_ROUNDS,
            "formal_denominator": PLAN056_SLOT_COUNT,
            "formal_slots_published": sum(
                row["status"] == "published" for row in state["slots"]
            ),
            "source_validated_slots": len(values),
        },
        "status": "valid" if valid else "invalid",
        "outcome": assessment["decision"] if assessment else "campaign_invalid",
        "selected_candidate": assessment["selected_candidate"] if assessment else None,
        "candidate_assessment": assessment,
        "terminal_bench": {
            "outcomes": outcome_counts,
            "task_passes": reward_passes,
            "task_failures": len(values) - reward_passes,
        },
        "budget": {
            "cap_usd": "50.000000",
            "estimated_usd": f"{spent:.6f}",
            "reserved_usd": "0.000000",
            "run_slots_used": int(budget["run_slots_used"]),
            "upstream_attempts": sum(
                int(request["attempt_count"])
                for run in budget["runs"].values()
                for request in run["requests"].values()
            ),
        },
        "resources": {
            "final_storage": state.get("final_storage"),
            "slot_docker_receipts": len(values),
        },
        "invalid_reason": state.get("invalid_reason") if not valid else None,
    }
    _validate_public_result(result)
    return result


def close_envelope_and_pointer(
    paths: RepoPaths,
    *,
    identity: BoundedObservationIdentity,
    terminal_status: str,
    spent_usd: Decimal,
) -> dict[str, object]:
    envelope_path = task_budget_path(paths.common_root, identity.task_budget_id)
    envelope = load_task_budget(
        envelope_path,
        task_budget_id=identity.task_budget_id,
        cap_usd=PLAN056_TASK_CAP_USD,
    )
    if envelope.get("active_identity") is not None:
        envelope = close_task_budget(
            envelope_path,
            active=TaskBudgetIdentity(identity.campaign_id, identity.batch_id),
            terminal_status=terminal_status,
            cumulative_settled_usd=spent_usd,
            task_budget_id=identity.task_budget_id,
            cap_usd=PLAN056_TASK_CAP_USD,
        )
    pointer_path = paths.worktree_root / PLAN056_POINTER_RELPATH
    retired = {
        "schema_version": 1,
        "kind": PLAN056_KIND,
        "active_lock": None,
        "active_lock_sha256": None,
    }
    existing = _read_json(pointer_path)
    if existing != retired:
        _atomic_json(pointer_path, retired, mode=0o644)
    return task_budget_status(envelope)


def verify_task_budget(
    paths: RepoPaths, identity: BoundedObservationIdentity
) -> dict[str, object]:
    return verify_active_identity(
        task_budget_path(paths.common_root, identity.task_budget_id),
        active=TaskBudgetIdentity(identity.campaign_id, identity.batch_id),
        prior_settled_usd=Decimal(0),
        task_budget_id=identity.task_budget_id,
        cap_usd=PLAN056_TASK_CAP_USD,
    )


def _validate_budget_run(run: object, *, observation: Mapping[str, Any]) -> None:
    if not isinstance(run, Mapping):
        raise BoundedObservationError("Plan 056 budget run is invalid")
    requests = run.get("requests")
    if not isinstance(requests, Mapping):
        raise BoundedObservationError("Plan 056 budget requests are invalid")
    meaningful = []
    total = Decimal(0)
    for request_id, request in requests.items():
        if not isinstance(request_id, str) or not isinstance(request, Mapping):
            raise BoundedObservationError("Plan 056 budget request is invalid")
        attempt_count = request.get("attempt_count")
        charged = Decimal(str(request.get("charged_usd")))
        if (
            request.get("status") != "settled"
            or isinstance(attempt_count, bool)
            or not isinstance(attempt_count, int)
        ):
            raise BoundedObservationError("Plan 056 budget request is unsettled")
        if attempt_count == 0:
            if (
                charged != 0
                or request.get("settlement_kind") != "not_sent_unbilled"
                or request.get("usage_valid") is not False
            ):
                raise BoundedObservationError(
                    "Plan 056 zero-attempt accounting is invalid"
                )
        else:
            meaningful.append(request)
        total += charged
    if total != Decimal(str(run.get("spent_usd"))):
        raise BoundedObservationError("Plan 056 budget run total is inconsistent")
    if len(meaningful) != observation["responses"]["total"]:
        raise BoundedObservationError(
            "Plan 056 budget and observation populations differ"
        )


def _validate_public_result(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "kind",
        "snapshot_date",
        "campaign",
        "status",
        "outcome",
        "selected_candidate",
        "candidate_assessment",
        "terminal_bench",
        "budget",
        "resources",
        "invalid_reason",
    }:
        raise BoundedObservationError("Plan 056 public result schema is invalid")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    forbidden = (
        '"prompt"',
        '"command"',
        '"output"',
        '"request_id"',
        '"run_id"',
        '"trace_id"',
        '"artifact_path"',
        '"metadata_path"',
        '"task_id"',
    )
    if any(marker in encoded for marker in forbidden):
        raise BoundedObservationError("Plan 056 public result is not body-free")


def _load_v28_reference(paths: RepoPaths) -> CampaignIdentity:
    raw = _read_regular(paths.worktree_root / PLAN056_V28_RELPATH)
    if hashlib.sha256(raw).hexdigest() != PLAN056_V28_SHA256:
        raise BoundedObservationError("Plan 056 v28 lock digest drifted")
    try:
        identity = load_historical_campaign_identity(paths, 28)
    except ValueError as exc:
        raise BoundedObservationError("Plan 056 v28 identity is unavailable") from exc
    if identity.lock_sha256 != PLAN056_V28_SHA256:
        raise BoundedObservationError("Plan 056 v28 identity digest drifted")
    return identity


def _load_runtime_config_without_secret(paths: RepoPaths) -> RuntimeConfig:
    from ..config import load_runtime_config

    return load_runtime_config(paths)


def _read_json(path: Path) -> dict[str, Any]:
    return _decode_json(_read_regular(path), path.name)


def _read_regular(path: Path, *, max_bytes: int = _MAX_PRIVATE_JSON_BYTES) -> bytes:
    try:
        metadata = path.lstat()
        size = metadata.st_size
    except OSError as exc:
        raise BoundedObservationError(f"{path.name} is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or size <= 0
        or size > max_bytes
    ):
        raise BoundedObservationError(f"{path.name} is unsafe")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise BoundedObservationError(f"{path.name} is unreadable") from exc


def _decode_json(raw: bytes, name: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BoundedObservationError(f"{name} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise BoundedObservationError(f"{name} is not an object")
    return value


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _atomic_json(path: Path, value: object, *, mode: int) -> None:
    _atomic_bytes(path, _json_bytes(value), mode=mode)


def _atomic_bytes(path: Path, value: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise BoundedObservationError(f"{path.name} destination is unsafe")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _git(root: Path, *args: str) -> str:
    result = _git_result(root, *args)
    if result.returncode != 0:
        raise BoundedObservationError("Plan 056 Git projection is unavailable")
    return result.stdout.strip()


def _git_result(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args), cwd=root, check=False, capture_output=True, text=True
    )


__all__ = [
    "PLAN056_BATCH_ID",
    "PLAN056_CAMPAIGN_ID",
    "PLAN056_LOCK_RELPATH",
    "PLAN056_PAID_ACTION",
    "PLAN056_POINTER_RELPATH",
    "PLAN056_PUBLIC_RESULT_RELPATH",
    "PLAN056_RUN_CAP_USD",
    "PLAN056_SLOT_COUNT",
    "PLAN056_TASK_BUDGET_ID",
    "PLAN056_TASK_CAP_USD",
    "PLAN056_UNPRICED_FALLBACK_USD",
    "BoundedObservationError",
    "BoundedObservationIdentity",
    "BoundedObservationSlot",
    "BoundedObservationState",
    "assess_candidates",
    "budget_path",
    "build_slot_record",
    "campaign_root",
    "close_envelope_and_pointer",
    "freeze_slots",
    "initialize_identity",
    "load_identity",
    "load_slot_records",
    "preflight_receipt_path",
    "public_result",
    "slot_record_path",
    "slot_root",
    "state_path",
    "validate_identity",
    "validate_slot_record",
    "verify_task_budget",
]
