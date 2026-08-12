"""P2 B6 cost model and B7 canary-baseline aggregation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
import fcntl
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Iterable

from ..config import RepoPaths
from ..contracts import BinaryManifest, ProviderProjection, RunSpec, Side
from .runner import PreparedTerminalBenchRun
from .scoring import TaskOutcome
from .tasksets import FrozenCanaryCatalog, FrozenTask, load_frozen_canary_catalog


CAMPAIGN_CAP_USD = Decimal("200.000000")
CAMPAIGN_MAX_RUNS = 161
RUN_CAP_USD = Decimal("40.000000")
SOL_MAX_LEGAL_REQUEST_RESERVATION_USD = Decimal("18.885000")
BASE_ROUNDS = (
    "aa-rondo-1",
    "aa-rondo-2",
    "ab-rondo-1",
    "ab-codex-1",
)
MAX_SIGMA = 2
CAMPAIGN_LOCK_PATH = Path("eval/locks/p2-b7-canary-baseline-v4.json")
RETIRED_CAMPAIGN_LOCK_PATHS = (
    Path("eval/locks/p2-b7-canary-baseline-v1.json"),
    Path("eval/locks/p2-b7-canary-baseline-v2.json"),
    Path("eval/locks/p2-b7-canary-baseline-v3.json"),
)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RUN_ID = re.compile(
    r"[0-9]{8}-[0-9]{9}-tb-(?:rondo|codex)-r[1-9][0-9]*"
)


class BaselineError(ValueError):
    """Raised when a campaign record is partial or contradictory."""


class BaselineStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class CampaignSlotStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class BaselineRun:
    task_id: str
    round_id: str
    side: Side
    attempt: int
    outcome: TaskOutcome
    run_id: str


@dataclass(frozen=True)
class ConditionalRun:
    task_id: str
    side: Side
    repeat: int
    attempt: int
    outcome: TaskOutcome
    run_id: str


@dataclass(frozen=True)
class BaselineAssessment:
    status: BaselineStatus
    reasons: tuple[str, ...]
    sigma: int | None
    delta: int | None
    conditional_tasks: tuple[str, ...]
    effective_base_runs: tuple[BaselineRun, ...]
    effective_conditional_runs: tuple[ConditionalRun, ...]


@dataclass(frozen=True)
class CampaignSlotPlan:
    slot_id: str
    index: int
    kind: str
    task_id: str | None
    side: Side
    round_id: str | None
    repeat: int | None
    attempt: int
    run_id: str


@dataclass(frozen=True)
class CampaignIdentity:
    campaign_id: str
    batch_id: str
    run_id_date: str
    run_id_sequence_base: int
    taskset_sha256: str
    canary_catalog_sha256: str
    terminal_bench_commit: str
    selected_profile: dict[str, object]
    bundles: dict[str, dict[str, str]]
    no_api_seccomp: dict[str, str]
    budget: dict[str, object]
    baseline: dict[str, object]
    lock_sha256: str
    catalog: FrozenCanaryCatalog

    @property
    def max_guardian_logical_requests(self) -> int:
        value = self.selected_profile.get("max_guardian_logical_requests")
        if isinstance(value, bool) or not isinstance(value, int) or value != 3:
            raise BaselineError("campaign Guardian request limit is invalid")
        return value

    def validate_provider(self, provider: ProviderProjection) -> None:
        expected = {
            key: value
            for key, value in self.selected_profile.items()
            if key
            not in {
                "frozen_codex_model_catalog_source_commit",
                "frozen_codex_model_catalog_sha256",
                "max_guardian_logical_requests",
            }
        }
        if provider.to_public_dict() != expected:
            raise BaselineError("selected provider profile drifted from the campaign lock")

    def validate_frozen_model_catalog(
        self,
        *,
        source_commit: str,
        sha256: str,
        main_model: str,
        guardian_model: str,
    ) -> None:
        selected = self.selected_profile
        if (
            source_commit
            != selected.get("frozen_codex_model_catalog_source_commit")
            or sha256 != selected.get("frozen_codex_model_catalog_sha256")
            or main_model != selected.get("effective_main_model")
            or guardian_model != selected.get("effective_guardian_model")
        ):
            raise BaselineError("frozen model catalog drifted from the campaign lock")

    def validate_manifest(
        self,
        *,
        common_root: Path,
        side: Side,
        manifest_path: Path,
        manifest: BinaryManifest,
    ) -> None:
        manifest.validate()
        expected = self.bundles.get(side.value)
        if not isinstance(expected, dict) or set(expected) != {
            "manifest_path",
            "manifest_sha256",
        }:
            raise BaselineError("campaign bundle identity is invalid")
        try:
            actual_path = manifest_path.resolve(strict=True)
            expected_path = (common_root / expected["manifest_path"]).resolve(strict=True)
        except OSError as exc:
            raise BaselineError("campaign bundle manifest is unavailable") from exc
        if (
            actual_path != expected_path
            or _file_sha256(actual_path) != expected["manifest_sha256"]
        ):
            raise BaselineError("campaign bundle manifest drifted from the lock")

    def validate_spec(
        self,
        spec: RunSpec,
        *,
        slot: CampaignSlotPlan,
        task: "FrozenTask",
    ) -> None:
        spec.validate()
        self.validate_provider(spec.provider)
        if (
            slot.task_id != task.task_id
            or spec.side is not slot.side
            or spec.batch_id != self.batch_id
            or spec.task_id != task.task_id
            or spec.task_image_digest != task.image_digest
            or spec.timeout_seconds != task.timeout_seconds
            or spec.max_retries != 0
            or spec.budget_usd != float(RUN_CAP_USD)
        ):
            raise BaselineError("campaign RunSpec differs from its frozen slot")

    def validate_prepared(
        self,
        prepared: PreparedTerminalBenchRun,
        *,
        slot: CampaignSlotPlan,
        task: "FrozenTask",
        seccomp_profile: Path,
    ) -> None:
        prepared.validate()
        self.validate_spec(prepared.spec, slot=slot, task=task)
        materialized = prepared.materialized_task
        container = prepared.command.compose_contract.container
        expected_seccomp = self.no_api_seccomp
        if (
            materialized.frozen_task != task
            or materialized.source_digest != task.source_digest
            or materialized.runtime_image_ref != task.image_ref
            or materialized.seccomp_profile != seccomp_profile
            or materialized.seccomp_profile_source_sha256
            != expected_seccomp.get("source_sha256")
            or materialized.seccomp_profile_effective_sha256
            != expected_seccomp.get("effective_sha256")
            or container.seccomp_profile_sha256
            != expected_seccomp.get("effective_sha256")
            or container.require_container_metrics is not True
        ):
            raise BaselineError("prepared campaign run drifted from its frozen task")

    def validate_runtime_seccomp(self, *, project_root: Path) -> Path:
        value = self.no_api_seccomp
        if set(value) != {"profile_path", "source_sha256", "effective_sha256"}:
            raise BaselineError("campaign seccomp identity is invalid")
        try:
            root = project_root.resolve(strict=True)
            path = (root / value["profile_path"]).resolve(strict=True)
            metadata = path.lstat()
        except OSError as exc:
            raise BaselineError("campaign seccomp profile is unavailable") from exc
        if (
            path != root / value["profile_path"]
            or path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or _file_sha256(path) != value["source_sha256"]
        ):
            raise BaselineError("campaign seccomp profile drifted from the lock")
        from .namespace_diagnostic import (
            _EFFECTIVE_PROFILE_SHA256,
            _require_clean_tracked_file,
            _validate_frozen_profile,
        )

        _require_clean_tracked_file(root, path)
        _validate_frozen_profile(path.read_bytes())
        if value["effective_sha256"] != _EFFECTIVE_PROFILE_SHA256:
            raise BaselineError("campaign effective seccomp identity drifted")
        return path

    @property
    def slots(self) -> tuple[CampaignSlotPlan, ...]:
        tasks = tuple(item.task_id for item in self.catalog.tasks)
        values: list[CampaignSlotPlan] = [
            self._slot(
                index=0,
                slot_id="wire-canary",
                kind="wire_canary",
                task_id=None,
                side=Side.CODEX,
                round_id=None,
                repeat=None,
                attempt=1,
            )
        ]
        index = 1
        round_sides = {
            "aa-rondo-1": Side.RONDO,
            "aa-rondo-2": Side.RONDO,
            "ab-rondo-1": Side.RONDO,
            "ab-codex-1": Side.CODEX,
        }
        for round_id in BASE_ROUNDS:
            side = round_sides[round_id]
            for task_id in tasks:
                values.append(
                    self._slot(
                        index=index,
                        slot_id=f"base:{round_id}:{task_id}:a1",
                        kind="base",
                        task_id=task_id,
                        side=side,
                        round_id=round_id,
                        repeat=None,
                        attempt=1,
                    )
                )
                index += 1
        for round_id in BASE_ROUNDS:
            side = round_sides[round_id]
            for task_id in tasks:
                values.append(
                    self._slot(
                        index=index,
                        slot_id=f"base:{round_id}:{task_id}:a2",
                        kind="base_replacement",
                        task_id=task_id,
                        side=side,
                        round_id=round_id,
                        repeat=None,
                        attempt=2,
                    )
                )
                index += 1
        for attempt, kind in ((1, "conditional"), (2, "conditional_replacement")):
            for task_id in tasks:
                for side in (Side.RONDO, Side.CODEX):
                    for repeat in (1, 2):
                        values.append(
                            self._slot(
                                index=index,
                                slot_id=(
                                    f"conditional:{task_id}:{side.value}:"
                                    f"repeat{repeat}:a{attempt}"
                                ),
                                kind=kind,
                                task_id=task_id,
                                side=side,
                                round_id="conditional",
                                repeat=repeat,
                                attempt=attempt,
                            )
                        )
                        index += 1
        if index != CAMPAIGN_MAX_RUNS:
            raise BaselineError("campaign slot plan differs from the frozen maximum")
        if (
            len(values) != CAMPAIGN_MAX_RUNS
            or len({item.slot_id for item in values}) != len(values)
            or len({item.run_id for item in values}) != len(values)
        ):
            raise BaselineError("campaign slot identities are not unique")
        return tuple(values)

    def slot(self, slot_id: str) -> CampaignSlotPlan:
        matches = tuple(item for item in self.slots if item.slot_id == slot_id)
        if len(matches) != 1:
            raise BaselineError("campaign slot is not uniquely frozen")
        return matches[0]

    def _slot(
        self,
        *,
        index: int,
        slot_id: str,
        kind: str,
        task_id: str | None,
        side: Side,
        round_id: str | None,
        repeat: int | None,
        attempt: int,
    ) -> CampaignSlotPlan:
        sequence = self.run_id_sequence_base + index
        run_id = f"{self.run_id_date}-{sequence:09d}-tb-{side.value}-r{attempt}"
        if _RUN_ID.fullmatch(run_id) is None:
            raise BaselineError("campaign run ID is invalid")
        return CampaignSlotPlan(
            slot_id,
            index,
            kind,
            task_id,
            side,
            round_id,
            repeat,
            attempt,
            run_id,
        )


class CampaignStateLedger:
    """Small crash-safe state ledger for one frozen campaign slot graph."""

    def __init__(
        self,
        path: Path,
        *,
        identity: CampaignIdentity,
        allow_interrupted_recovery: bool = False,
    ) -> None:
        self.path = path
        self.identity = identity
        self._allow_interrupted_recovery = allow_interrupted_recovery
        self._lock_path = path.with_suffix(path.suffix + ".lock")
        self._lock_handle: object | None = None
        self._state: dict[str, object] | None = None

    def __enter__(self) -> "CampaignStateLedger":
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(self._lock_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "r+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        self._lock_handle = handle
        try:
            self._state = self._load_or_initialize()
        except BaseException:
            self._lock_handle = None
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            raise
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        del exc_type, exc, traceback
        handle = self._lock_handle
        self._state = None
        self._lock_handle = None
        if handle is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def snapshot(self) -> dict[str, object]:
        return json.loads(json.dumps(self._require_state()))

    def claim(self, slot_id: str) -> CampaignSlotPlan:
        state = self._require_state()
        slot = self.identity.slot(slot_id)
        row = self._row(state, slot_id)
        if row["status"] != CampaignSlotStatus.PLANNED.value:
            raise BaselineError("campaign slot is not claimable")
        if any(
            item["status"] == CampaignSlotStatus.RUNNING.value
            for item in state["slots"]
        ):
            raise BaselineError("another campaign slot is already running")
        row["status"] = CampaignSlotStatus.RUNNING.value
        row["claimed_at_unix"] = int(time.time())
        self._persist(state)
        return slot

    def finish(
        self,
        slot_id: str,
        *,
        status: CampaignSlotStatus,
        outcome: str,
        estimated_usd: str,
        artifact_path: str | None,
        result_record_sha256: str | None,
        reason: str | None,
    ) -> None:
        if status not in {CampaignSlotStatus.COMPLETED, CampaignSlotStatus.FAILED}:
            raise BaselineError("campaign terminal slot status is invalid")
        if not re.fullmatch(r"[0-9]+\.[0-9]{6}", estimated_usd):
            raise BaselineError("campaign slot cost is invalid")
        if result_record_sha256 is not None and _SHA256.fullmatch(result_record_sha256) is None:
            raise BaselineError("campaign result digest is invalid")
        state = self._require_state()
        row = self._row(state, slot_id)
        if row["status"] != CampaignSlotStatus.RUNNING.value:
            raise BaselineError("campaign slot is not running")
        row.update(
            {
                "status": status.value,
                "outcome": outcome,
                "estimated_usd": estimated_usd,
                "artifact_path": artifact_path,
                "result_record_sha256": result_record_sha256,
                "reason": reason,
                "finished_at_unix": int(time.time()),
            }
        )
        self._persist(state)

    def fail_interrupted(self, *, estimated_usd: str, reason: str) -> str:
        """Close the one crash-interrupted slot before retiring its identity."""

        if not self._allow_interrupted_recovery:
            raise BaselineError("campaign interruption recovery is not enabled")
        if not re.fullmatch(r"[0-9]+\.[0-9]{6}", estimated_usd) or not reason:
            raise BaselineError("campaign interruption recovery is invalid")
        state = self._require_state()
        running = [row for row in state["slots"] if row["status"] == "running"]
        if len(running) != 1:
            raise BaselineError("campaign interruption recovery is ambiguous")
        row = running[0]
        row.update(
            {
                "status": CampaignSlotStatus.FAILED.value,
                "outcome": "infra_failed",
                "estimated_usd": estimated_usd,
                "artifact_path": None,
                "result_record_sha256": None,
                "reason": reason,
                "finished_at_unix": int(time.time()),
            }
        )
        self._persist(state)
        return row["slot_id"]

    def skip(self, slot_id: str, *, reason: str) -> None:
        if not reason:
            raise BaselineError("campaign skip reason is invalid")
        state = self._require_state()
        row = self._row(state, slot_id)
        if row["status"] != CampaignSlotStatus.PLANNED.value:
            raise BaselineError("only a planned campaign slot can be skipped")
        row["status"] = CampaignSlotStatus.SKIPPED.value
        row["reason"] = reason
        row["finished_at_unix"] = int(time.time())
        self._persist(state)

    def finalize(self, status: BaselineStatus, *, reason: str | None) -> None:
        state = self._require_state()
        if state["status"] != "running":
            raise BaselineError("campaign state is already terminal")
        running = [
            row for row in state["slots"] if row["status"] == "running"
        ]
        if running:
            raise BaselineError("campaign cannot finalize with a running slot")
        if status is BaselineStatus.PASSED and any(
            row["status"] == CampaignSlotStatus.PLANNED.value
            for row in state["slots"]
        ):
            raise BaselineError("passing campaign still has planned slots")
        state["status"] = status.value
        state["terminal_reason"] = reason
        self._persist(state)

    def _load_or_initialize(self) -> dict[str, object]:
        if self.path.exists():
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise BaselineError("campaign state ledger is unreadable") from exc
            self._validate_state(value)
            if not self._allow_interrupted_recovery and any(
                row["status"] == CampaignSlotStatus.RUNNING.value
                for row in value["slots"]
            ):
                raise BaselineError(
                    "campaign has a crash-interrupted running slot; reconcile it before resume"
                )
            return value
        value: dict[str, object] = {
            "schema_version": 1,
            "campaign_id": self.identity.campaign_id,
            "campaign_lock_sha256": self.identity.lock_sha256,
            "status": "running",
            "actual_usd": None,
            "terminal_reason": None,
            "slots": [
                {
                    "slot_id": slot.slot_id,
                    "run_id": slot.run_id,
                    "status": CampaignSlotStatus.PLANNED.value,
                    "outcome": None,
                    "estimated_usd": "0.000000",
                    "artifact_path": None,
                    "result_record_sha256": None,
                    "reason": None,
                    "claimed_at_unix": None,
                    "finished_at_unix": None,
                }
                for slot in self.identity.slots
            ],
        }
        self._persist(value)
        return value

    def _validate_state(self, value: object) -> None:
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "campaign_id",
            "campaign_lock_sha256",
            "status",
            "actual_usd",
            "terminal_reason",
            "slots",
        }:
            raise BaselineError("campaign state ledger schema is invalid")
        slots = value["slots"]
        if (
            value["schema_version"] != 1
            or value["campaign_id"] != self.identity.campaign_id
            or value["campaign_lock_sha256"] != self.identity.lock_sha256
            or value["status"] not in {"running", "passed", "failed", "blocked"}
            or value["actual_usd"] is not None
            or (
                value["terminal_reason"] is not None
                and not isinstance(value["terminal_reason"], str)
            )
            or not isinstance(slots, list)
            or len(slots) != len(self.identity.slots)
        ):
            raise BaselineError("campaign state ledger identity is invalid")
        expected = {slot.slot_id: slot.run_id for slot in self.identity.slots}
        observed: dict[str, str] = {}
        for row in slots:
            if not isinstance(row, dict) or set(row) != {
                "slot_id",
                "run_id",
                "status",
                "outcome",
                "estimated_usd",
                "artifact_path",
                "result_record_sha256",
                "reason",
                "claimed_at_unix",
                "finished_at_unix",
            }:
                raise BaselineError("campaign state slot schema is invalid")
            if row["status"] not in {item.value for item in CampaignSlotStatus}:
                raise BaselineError("campaign state slot status is invalid")
            observed[row["slot_id"]] = row["run_id"]
        if observed != expected or len(observed) != len(slots):
            raise BaselineError("campaign state slots drifted from the lock")

    def _persist(self, value: dict[str, object]) -> None:
        self._validate_state(value)
        payload = (
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        temporary = self.path.with_name(f".{self.path.name}.tmp-{os.getpid()}")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except BaseException:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
            raise
        self._state = value

    def _require_state(self) -> dict[str, object]:
        if self._state is None or self._lock_handle is None:
            raise BaselineError("campaign state ledger is not open")
        return self._state

    @staticmethod
    def _row(state: dict[str, object], slot_id: str) -> dict[str, object]:
        matches = [row for row in state["slots"] if row["slot_id"] == slot_id]
        if len(matches) != 1:
            raise BaselineError("campaign state slot is not unique")
        return matches[0]


def load_campaign_identity(paths: RepoPaths) -> CampaignIdentity:
    """Load the immutable P2 lock and bind it to tasksets/catalog bytes."""

    path = paths.worktree_root / CAMPAIGN_LOCK_PATH
    raw = _read_regular_lock(path)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineError("campaign lock is invalid JSON") from exc
    expected_keys = {
        "schema_version",
        "campaign_id",
        "batch_id",
        "run_id_date",
        "run_id_sequence_base",
        "taskset_sha256",
        "canary_catalog_sha256",
        "terminal_bench_commit",
        "selected_profile",
        "bundles",
        "no_api_seccomp",
        "budget",
        "baseline",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise BaselineError("campaign lock schema is invalid")
    catalog = load_frozen_canary_catalog(paths)
    if (
        value["schema_version"] != 1
        or value["campaign_id"] != "p2-b7-canary-baseline-v4"
        or value["batch_id"] != "p2-b7-canary-sol-sol-v4"
        or value["run_id_date"] != "20260811"
        or value["run_id_sequence_base"] != 240000000
        or value["taskset_sha256"] != catalog.taskset_sha256
        or value["canary_catalog_sha256"] != catalog.catalog_sha256
        or value["terminal_bench_commit"] != catalog.terminal_bench_commit
        or not isinstance(value["selected_profile"], dict)
        or not isinstance(value["bundles"], dict)
        or not isinstance(value["no_api_seccomp"], dict)
        or value["budget"]
        != {
            "campaign_cap_usd": "200.000000",
            "prior_estimated_usd": "58.689250",
            "run_cap_usd": "40.000000",
            "max_run_slots": 161,
            "maximum_legal_request_reservation_usd": "18.885000",
            "actual_usd": None,
        }
        or value["baseline"]
        != {
            "base_rounds": list(BASE_ROUNDS),
            "max_sigma": MAX_SIGMA,
            "infra_round_invalid_threshold": 0.2,
            "max_base_replacement_attempts": 1,
            "max_conditional_replacement_attempts": 1,
            "conditional_repeats_per_side": 2,
            "docker_concurrency": 1,
            "api_max_retries": 0,
        }
    ):
        raise BaselineError("campaign lock differs from the frozen B7 contract")
    selected = value["selected_profile"]
    required_selected = {
        "provider_profile_sha256",
        "provider_endpoint_sha256",
        "frozen_codex_model_catalog_sha256",
    }
    if any(
        not isinstance(selected.get(key), str)
        or _SHA256.fullmatch(selected[key]) is None
        for key in required_selected
    ):
        raise BaselineError("campaign selected profile hashes are invalid")
    identity = CampaignIdentity(
        campaign_id=value["campaign_id"],
        batch_id=value["batch_id"],
        run_id_date=value["run_id_date"],
        run_id_sequence_base=value["run_id_sequence_base"],
        taskset_sha256=value["taskset_sha256"],
        canary_catalog_sha256=value["canary_catalog_sha256"],
        terminal_bench_commit=value["terminal_bench_commit"],
        selected_profile=dict(selected),
        bundles={key: dict(item) for key, item in value["bundles"].items()},
        no_api_seccomp=dict(value["no_api_seccomp"]),
        budget=dict(value["budget"]),
        baseline=dict(value["baseline"]),
        lock_sha256=hashlib.sha256(raw).hexdigest(),
        catalog=catalog,
    )
    _ = identity.slots
    return identity


def _read_regular_lock(path: Path) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise BaselineError("campaign lock is unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 2_000_000:
        raise BaselineError("campaign lock path is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            raw = os.read(descriptor, 2_000_001)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise BaselineError("campaign lock cannot be read safely") from exc
    if len(raw) != metadata.st_size:
        raise BaselineError("campaign lock changed while reading")
    return raw


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise BaselineError("frozen campaign file is unavailable") from exc
    return digest.hexdigest()


def cost_forecast() -> dict[str, object]:
    """Return the frozen, recomputable B6 estimate without claiming a worst-case guarantee."""

    rondo_v19 = Decimal("0.456082")
    codex_v19 = Decimal("0.414705")
    wire_canary = Decimal("0.284300")
    base_point = 30 * rondo_v19 + 10 * codex_v19
    conditional_per_task = 2 * rondo_v19 + 2 * codex_v19
    full_point = base_point + 10 * conditional_per_task + wire_canary
    historical_40 = (Decimal("16.588200"), Decimal("18.243280"))
    historical_80 = (Decimal("33.176400"), Decimal("36.486560"))
    historical_160 = (Decimal("66.352800"), Decimal("72.973120"))
    observed_shape_stress = Decimal("173.653100")
    return {
        "schema_version": 1,
        "currency": "USD",
        "actual_usd": None,
        "campaign_cap_usd": _money(CAMPAIGN_CAP_USD),
        "base_runs": 40,
        "maximum_conditional_runs": 40,
        "maximum_infra_replacement_runs": 80,
        "v19_rondo_run_usd": _money(rondo_v19),
        "v19_codex_run_usd": _money(codex_v19),
        "wire_canary_usd": _money(wire_canary),
        "base_point_estimate_usd": _money(base_point),
        "full_condition_point_estimate_usd": _money(full_point),
        "historical_40_run_range_usd": [_money(item) for item in historical_40],
        "historical_80_run_range_usd": [_money(item) for item in historical_80],
        "historical_160_run_range_usd": [_money(item) for item in historical_160],
        "v19_shape_stress_with_canary_usd": _money(observed_shape_stress),
        "maximum_legal_request_reservation_usd": _money(
            SOL_MAX_LEGAL_REQUEST_RESERVATION_USD
        ),
        "feasible_from_observed_shape": observed_shape_stress < CAMPAIGN_CAP_USD,
        "mathematical_all_legal_usage_guarantee": False,
        "stop_rule": (
            "do not start a request unless its maximum legal reservation fits the "
            "remaining campaign budget"
        ),
    }


def assess_baseline(
    task_ids: tuple[str, ...],
    base_runs: tuple[BaselineRun, ...],
    conditional_runs: tuple[ConditionalRun, ...],
) -> BaselineAssessment:
    """Select bounded infra replacements and apply the frozen B7 gates."""

    if len(task_ids) != 10 or len(set(task_ids)) != 10:
        raise BaselineError("B7 requires ten unique canary tasks")
    expected_sides = {
        "aa-rondo-1": Side.RONDO,
        "aa-rondo-2": Side.RONDO,
        "ab-rondo-1": Side.RONDO,
        "ab-codex-1": Side.CODEX,
    }
    effective_base: list[BaselineRun] = []
    blocked: list[str] = []
    for round_id in BASE_ROUNDS:
        candidates = tuple(item for item in base_runs if item.round_id == round_id)
        selected = _select_round(
            task_ids,
            candidates,
            expected_side=expected_sides[round_id],
            label=round_id,
        )
        if selected is None:
            blocked.append(f"{round_id}_infra_replacement_exhausted")
        else:
            effective_base.extend(selected)
    if blocked:
        return BaselineAssessment(
            BaselineStatus.BLOCKED,
            tuple(blocked),
            None,
            None,
            (),
            tuple(effective_base),
            (),
        )

    by_round = {
        round_id: {item.task_id: item.outcome for item in effective_base if item.round_id == round_id}
        for round_id in BASE_ROUNDS
    }
    sigma = sum(
        by_round["aa-rondo-1"][task_id]
        is not by_round["aa-rondo-2"][task_id]
        for task_id in task_ids
    )
    delta = sum(
        by_round["ab-rondo-1"][task_id]
        is not by_round["ab-codex-1"][task_id]
        for task_id in task_ids
    )
    triggers = tuple(
        task_id
        for task_id in task_ids
        if by_round["ab-rondo-1"][task_id] is TaskOutcome.FAIL
        and by_round["ab-codex-1"][task_id] is TaskOutcome.PASS
    )
    effective_conditional: list[ConditionalRun] = []
    for task_id in triggers:
        for side in (Side.RONDO, Side.CODEX):
            for repeat in (1, 2):
                selected = _select_conditional(
                    task_id,
                    side,
                    repeat,
                    conditional_runs,
                )
                if selected is None:
                    blocked.append(
                        f"conditional_{side.value}_{repeat}_{task_id}_infra_replacement_exhausted"
                    )
                else:
                    effective_conditional.append(selected)
    if blocked:
        return BaselineAssessment(
            BaselineStatus.BLOCKED,
            tuple(blocked),
            sigma,
            delta,
            triggers,
            tuple(effective_base),
            tuple(effective_conditional),
        )

    reasons: list[str] = []
    if sigma > MAX_SIGMA:
        reasons.append("aa_sigma_exceeds_frozen_stability_limit")
    if delta > sigma:
        reasons.append("ab_delta_exceeds_aa_sigma")
    for task_id in triggers:
        rondo = [
            by_round["ab-rondo-1"][task_id],
            *(
                item.outcome
                for item in effective_conditional
                if item.task_id == task_id and item.side is Side.RONDO
            ),
        ]
        codex = [
            by_round["ab-codex-1"][task_id],
            *(
                item.outcome
                for item in effective_conditional
                if item.task_id == task_id and item.side is Side.CODEX
            ),
        ]
        if all(item is TaskOutcome.FAIL for item in rondo) and all(
            item is TaskOutcome.PASS for item in codex
        ):
            reasons.append(f"stable_directional_regression:{task_id}")
    status = BaselineStatus.FAILED if reasons else BaselineStatus.PASSED
    return BaselineAssessment(
        status,
        tuple(reasons),
        sigma,
        delta,
        triggers,
        tuple(effective_base),
        tuple(effective_conditional),
    )


def _select_round(
    task_ids: tuple[str, ...],
    values: tuple[BaselineRun, ...],
    *,
    expected_side: Side,
    label: str,
) -> tuple[BaselineRun, ...] | None:
    if any(
        item.side is not expected_side
        or item.attempt not in {1, 2}
        or item.task_id not in task_ids
        for item in values
    ):
        raise BaselineError(f"{label} contains an invalid run")
    _require_unique_runs(values)
    first = {item.task_id: item for item in values if item.attempt == 1}
    if set(first) != set(task_ids):
        raise BaselineError(f"{label} first attempt is incomplete")
    infra_ids = {task_id for task_id, item in first.items() if item.outcome is TaskOutcome.INFRA}
    second = {item.task_id: item for item in values if item.attempt == 2}
    expected_second = set(task_ids) if len(infra_ids) > 2 else infra_ids
    if set(second) != expected_second:
        raise BaselineError(f"{label} replacement set differs from the frozen rule")
    selected = second if len(infra_ids) > 2 else {**first, **second}
    if any(item.outcome is TaskOutcome.INFRA for item in selected.values()):
        return None
    return tuple(selected[task_id] for task_id in task_ids)


def _select_conditional(
    task_id: str,
    side: Side,
    repeat: int,
    values: tuple[ConditionalRun, ...],
) -> ConditionalRun | None:
    matches = tuple(
        item
        for item in values
        if item.task_id == task_id and item.side is side and item.repeat == repeat
    )
    if not matches or any(item.attempt not in {1, 2} for item in matches):
        raise BaselineError("conditional run is missing or invalid")
    _require_unique_runs(matches)
    by_attempt = {item.attempt: item for item in matches}
    first = by_attempt.get(1)
    if first is None:
        raise BaselineError("conditional first attempt is missing")
    if first.outcome is TaskOutcome.INFRA:
        second = by_attempt.get(2)
        if set(by_attempt) != {1, 2}:
            raise BaselineError("conditional infra replacement is incomplete")
        if second is None or second.outcome is TaskOutcome.INFRA:
            return None
        return second
    if set(by_attempt) != {1}:
        raise BaselineError("conditional replacement was activated without infra")
    return first


def _require_unique_runs(values: Iterable[BaselineRun | ConditionalRun]) -> None:
    run_ids = tuple(item.run_id for item in values)
    keys = tuple(
        (item.task_id, item.side, getattr(item, "round_id", None), getattr(item, "repeat", None), item.attempt)
        for item in values
    )
    if len(run_ids) != len(set(run_ids)) or len(keys) != len(set(keys)):
        raise BaselineError("campaign run identities are duplicated")


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")
