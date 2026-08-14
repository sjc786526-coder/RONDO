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
from ..contracts import BinaryManifest, Product, ProviderProjection, RunSpec, Side
from ..fair_comparison import (
    AGGREGATION_STRICT_MAJORITY,
    CATALOG_PROJECTION_VERSION,
    ComparisonConditions,
    FairComparisonError,
    RepeatContract,
    aggregate_repeat_outcomes,
)
from ..frozen_model_catalog import (
    CATALOG_PROJECTION_ALGORITHM,
    RONDO_CATALOG_PATH,
    UPSTREAM_CATALOG_PATH,
)
from .runner import PreparedTerminalBenchRun
from .scoring import TaskOutcome
from .tasksets import FrozenCanaryCatalog, FrozenTask, load_frozen_canary_catalog


LEGACY_CAMPAIGN_CAP_USD = Decimal("600.000000")
LEGACY_CAMPAIGN_MAX_RUNS = 161
HISTORICAL_SCHEMA_V2_CAMPAIGN_CAP_USD = Decimal("700.000000")
HISTORICAL_SCHEMA_V3_CAMPAIGN_CAP_USD = Decimal("1000.000000")
HISTORICAL_SCHEMA_V4_CAMPAIGN_CAP_USD = Decimal("1300.000000")
CAMPAIGN_CAP_USD = Decimal("1600.000000")
CAMPAIGN_PRIOR_ESTIMATED_USD = Decimal("1136.113528")
CAMPAIGN_MAX_RUNS = 321
RUN_CAP_USD = Decimal("40.000000")
SOL_MAX_LEGAL_REQUEST_RESERVATION_USD = Decimal("18.885000")
LEGACY_UPSTREAM_TIMEOUT_SECONDS = Decimal("90.000")
CAMPAIGN_UPSTREAM_TIMEOUT_SECONDS = Decimal("180.000")
BASE_ROUNDS = (
    "aa-rondo-1",
    "aa-rondo-2",
    "ab-rondo-1",
    "ab-codex-1",
)
MAX_SIGMA = 2
MAX_REMAINING_INFRA_PER_ROUND = 2
# Campaign schema versions 1--6 are frozen history.  Every E-B8 fair-comparison
# rule -- shared catalog identity, frozen run conditions, task-interleaved
# order, layered assessment and pre-frozen repeats -- is introduced at v7 so
# the historical locks keep replaying byte for byte.
FAIR_COMPARISON_SCHEMA_VERSION = 7
HISTORICAL_SCHEMA_VERSIONS = (1, 2, 3, 4, 5, 6)
SUPPORTED_SCHEMA_VERSIONS = (
    *HISTORICAL_SCHEMA_VERSIONS,
    FAIR_COMPARISON_SCHEMA_VERSION,
)
EXECUTION_ORDER_TASK_INTERLEAVED = "task_interleaved"
EXECUTION_ORDER_ROUND_BLOCKED = "round_time_blocked"
ASSESSMENT_LAYERS = ("aa_consistency", "cross_side", "directional")
MECHANICAL_CIRCUIT_BREAKER_TASKS = 3
MIN_COMMON_VALID_TASKS = 8
CAMPAIGN_ACTIVE_POINTER_PATH = Path("eval/locks/p2-b7-active.json")
_CAMPAIGN_LOCK_NAME = re.compile(r"p2-b7-canary-baseline-v([1-9][0-9]*)\.json")
_CAMPAIGN_ID = re.compile(r"p2-b7-canary-baseline-v([1-9][0-9]*)")
_CAMPAIGN_BATCH_ID = re.compile(r"p2-b7-canary-sol-sol-v([1-9][0-9]*)")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_OBJECT = re.compile(r"[0-9a-f]{40}")
_MODEL_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
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


class MechanicalFailureCategory(str, Enum):
    """Bounded failure taxonomy used by the paid campaign circuit breaker."""

    PROVIDER_RESPONSE_INTEGRITY = "provider_response_integrity"
    DOCKER_RUNTIME = "docker_runtime"
    GUARDIAN_RUNTIME = "guardian_runtime"
    PUBLICATION_INTEGRITY = "publication_integrity"
    HARNESS_RUNTIME = "harness_runtime"
    BUDGET_CAPACITY = "budget_capacity"
    OPERATOR_INTERRUPTION = "operator_interruption"


class DiagnosisStatus(str, Enum):
    REQUIRED = "required"
    RESOLVED = "resolved"
    TASK_LOCAL_REPRODUCIBLE_INFRA = "task_local_reproducible_infra"


class DiagnosisDisposition(str, Enum):
    EXTERNAL_TRANSIENT = "external_transient"
    LOCAL_IMPLEMENTATION_DEFECT = "local_implementation_defect"
    SHARED_INFRASTRUCTURE_DEFECT = "shared_infrastructure_defect"


class DiagnosisEvidenceCode(str, Enum):
    PROVIDER_STREAM_ENDED_WITHOUT_TERMINAL_USAGE = (
        "provider_stream_ended_without_terminal_usage"
    )
    DOCKER_COUNTER_COMMAND_FAILURE = "docker_counter_command_failure"
    GUARDIAN_SESSION_FAILED_CLOSED = "guardian_session_failed_closed"
    PUBLICATION_CONTRACT_REJECTED = "publication_contract_rejected"
    HARNESS_PROCESS_FAILED = "harness_process_failed"
    LOCAL_CONTRACT_DEFECT_CONFIRMED = "local_contract_defect_confirmed"
    SHARED_INFRASTRUCTURE_DEFECT_CONFIRMED = (
        "shared_infrastructure_defect_confirmed"
    )


_EXTERNAL_DIAGNOSIS_EVIDENCE = {
    MechanicalFailureCategory.PROVIDER_RESPONSE_INTEGRITY: (
        DiagnosisEvidenceCode.PROVIDER_STREAM_ENDED_WITHOUT_TERMINAL_USAGE
    ),
    MechanicalFailureCategory.DOCKER_RUNTIME: (
        DiagnosisEvidenceCode.DOCKER_COUNTER_COMMAND_FAILURE
    ),
    MechanicalFailureCategory.GUARDIAN_RUNTIME: (
        DiagnosisEvidenceCode.GUARDIAN_SESSION_FAILED_CLOSED
    ),
    MechanicalFailureCategory.PUBLICATION_INTEGRITY: (
        DiagnosisEvidenceCode.PUBLICATION_CONTRACT_REJECTED
    ),
    MechanicalFailureCategory.HARNESS_RUNTIME: (
        DiagnosisEvidenceCode.HARNESS_PROCESS_FAILED
    ),
}


@dataclass(frozen=True)
class BaselineRun:
    task_id: str
    round_id: str
    side: Side
    attempt: int
    outcome: TaskOutcome
    run_id: str
    failure_category: MechanicalFailureCategory | None = None


@dataclass(frozen=True)
class ConditionalRun:
    task_id: str
    side: Side
    repeat: int
    attempt: int
    outcome: TaskOutcome
    run_id: str
    failure_category: MechanicalFailureCategory | None = None


@dataclass(frozen=True)
class AssessmentLayer:
    """One independently reported sub-gate.

    The three layers answer different questions and are never collapsed into a
    single "performance gate": A/A behavioural consistency, cross-side
    difference, and the directional-regression backstop.
    """

    name: str
    status: BaselineStatus
    reasons: tuple[str, ...] = ()
    metrics: tuple[tuple[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "reasons": list(self.reasons),
            "metrics": {key: value for key, value in self.metrics},
        }


@dataclass(frozen=True)
class BaselineAssessment:
    status: BaselineStatus
    reasons: tuple[str, ...]
    sigma: int | None
    delta: int | None
    common_valid_tasks: tuple[str, ...]
    conditional_tasks: tuple[str, ...]
    effective_base_runs: tuple[BaselineRun, ...]
    effective_conditional_runs: tuple[ConditionalRun, ...]
    # Populated only under the E-B8 repeat contract; historical campaigns keep
    # the single ``reasons`` tuple they were assessed with.
    layers: tuple[AssessmentLayer, ...] = ()
    aggregated_outcomes: tuple[tuple[str, str, TaskOutcome], ...] = ()

    def layer(self, name: str) -> AssessmentLayer:
        matches = tuple(item for item in self.layers if item.name == name)
        if len(matches) != 1:
            raise BaselineError("assessment layer is not uniquely reported")
        return matches[0]


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
class CampaignLockRegistration:
    version: int
    path: Path
    campaign_id: str
    batch_id: str
    run_id_date: str
    run_id_sequence_base: int
    max_run_slots: int
    lock_sha256: str


@dataclass(frozen=True)
class ContinuationReference:
    chain_id: str
    source_campaign_id: str
    source_campaign_lock_sha256: str
    source_slot_id: str
    source_run_id: str
    source_result_record_sha256: str
    source_upstream_timeout_seconds: Decimal


@dataclass(frozen=True)
class CampaignIdentity:
    schema_version: int
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
    continuation: tuple[ContinuationReference, ...] = ()
    # The frozen fair-comparison block; present from schema v7 only.
    comparison: dict[str, object] | None = None

    @property
    def max_attempts(self) -> int:
        if self.schema_version == 1:
            return 2
        if self.schema_version in {2, 3, 4, 5, 6, FAIR_COMPARISON_SCHEMA_VERSION}:
            return 4
        raise BaselineError("campaign identity version is unsupported")

    @property
    def enforces_fair_comparison(self) -> bool:
        return self.schema_version >= FAIR_COMPARISON_SCHEMA_VERSION

    def _comparison_block(self) -> dict[str, object]:
        if not self.enforces_fair_comparison or not isinstance(self.comparison, dict):
            raise BaselineError("campaign fair-comparison contract is not frozen")
        return self.comparison

    @property
    def repeat_contract(self) -> RepeatContract:
        """Return the repeat rules frozen before any paid data was produced."""

        try:
            return RepeatContract.from_dict(self._comparison_block().get("repeat_contract"))
        except FairComparisonError as exc:
            raise BaselineError(f"campaign repeat contract is invalid: {exc}") from exc

    @property
    def comparison_conditions(self) -> ComparisonConditions:
        try:
            return ComparisonConditions.from_dict(
                self._comparison_block().get("comparison_conditions")
            )
        except FairComparisonError as exc:
            raise BaselineError(f"campaign run conditions are invalid: {exc}") from exc

    @property
    def catalog_identity(self) -> dict[str, object]:
        value = self._comparison_block().get("catalog_identity")
        if not isinstance(value, dict) or not value:
            raise BaselineError("campaign catalog identity is not frozen")
        return value

    @property
    def product(self) -> Product:
        """Which RONDO product this campaign evaluates.

        The field exists so the facility stops assuming a single product; the
        actual Multi wiring belongs to the Multi baseline work package.
        """

        value = self._comparison_block().get("product")
        try:
            return Product(str(value))
        except ValueError as exc:
            raise BaselineError("campaign product identity is invalid") from exc

    def actual_conditions(self, *, eval_harness_commit: str | None = None) -> ComparisonConditions:
        """Rebuild the run conditions from the lock's own authoritative fields.

        ``eval_harness_commit`` is the only one that is a runtime fact; when it
        is not supplied the declared value is carried through so this stays
        usable at load time, and the runtime check happens where the real
        commit is known.
        """

        declared = self._comparison_block().get("comparison_conditions")
        if not isinstance(declared, dict):
            raise BaselineError("campaign run conditions are not frozen")
        try:
            return ComparisonConditions(
                eval_harness_commit=str(
                    eval_harness_commit
                    if eval_harness_commit is not None
                    else declared.get("eval_harness_commit")
                ),
                upstream_timeout_seconds=str(
                    self.baseline.get("upstream_timeout_seconds")
                ),
                provider_profile_sha256=str(
                    self.selected_profile.get("provider_profile_sha256")
                ),
                catalog_artifact_sha256=str(self.catalog_identity["sha256"]),
                task_image_digests=tuple(
                    sorted(
                        (item.task_id, item.image_digest) for item in self.catalog.tasks
                    )
                ),
            )
        except FairComparisonError as exc:
            raise BaselineError(f"campaign run conditions are invalid: {exc}") from exc

    def require_declared_conditions(
        self, *, eval_harness_commit: str | None = None
    ) -> ComparisonConditions:
        """Fail closed unless the declared conditions match the real ones."""

        declared = self.comparison_conditions
        try:
            declared.require_match(
                self.actual_conditions(eval_harness_commit=eval_harness_commit)
            )
        except FairComparisonError as exc:
            raise BaselineError(
                "campaign run conditions differ from the frozen campaign: "
                + ";".join(exc.reasons)
            ) from exc
        return declared

    @property
    def conditional_repeats_per_side(self) -> int:
        """Repeats executed *in addition to* the base A/B observation.

        The frozen contract counts total observations per side, and the base
        A/B run is one of them, so the conditional slots carry the remainder.
        """

        return self.repeat_contract.repeats_per_task - 1

    @property
    def upstream_timeout_seconds(self) -> float:
        if self.schema_version < 3:
            return float(LEGACY_UPSTREAM_TIMEOUT_SECONDS)
        value = self.baseline.get("upstream_timeout_seconds")
        try:
            timeout = Decimal(str(value))
        except ArithmeticError as exc:
            raise BaselineError("campaign upstream timeout is invalid") from exc
        if timeout != CAMPAIGN_UPSTREAM_TIMEOUT_SECONDS:
            raise BaselineError("campaign upstream timeout differs from the freeze")
        return float(timeout)

    def continuation_for(self, chain_id: str) -> ContinuationReference | None:
        matches = tuple(item for item in self.continuation if item.chain_id == chain_id)
        if len(matches) > 1:
            raise BaselineError("campaign continuation chain is duplicated")
        return matches[0] if matches else None

    @property
    def max_run_slots(self) -> int:
        value = self.budget.get("max_run_slots")
        if isinstance(value, bool) or not isinstance(value, int):
            raise BaselineError("campaign run-slot limit is invalid")
        return value

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
        """Validate the Codex-only projection replayed by v1--v6 campaigns."""

        if self.enforces_fair_comparison:
            raise BaselineError(
                "a fair-comparison campaign uses the shared catalog artifact"
            )
        selected = self.selected_profile
        if (
            source_commit
            != selected.get("frozen_codex_model_catalog_source_commit")
            or sha256 != selected.get("frozen_codex_model_catalog_sha256")
            or main_model != selected.get("effective_main_model")
            or guardian_model != selected.get("effective_guardian_model")
        ):
            raise BaselineError("frozen model catalog drifted from the campaign lock")

    def validate_shared_model_catalog(self, identity: object) -> None:
        """Fail closed unless the artifact matches every frozen identity field.

        The artifact digest alone would only prove that nothing drifted; the
        recorded source commits, paths and blob IDs are what prove the bytes
        came from the right two places.
        """

        frozen = self.catalog_identity
        if not isinstance(identity, dict):
            raise BaselineError("shared model catalog identity is invalid")
        if identity != frozen:
            raise BaselineError("shared model catalog drifted from the campaign lock")
        conditions = self.comparison_conditions
        if conditions.catalog_artifact_sha256 != frozen["sha256"]:
            raise BaselineError("shared model catalog digest differs from run conditions")

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
    def base_round_order(self) -> tuple[tuple[str, str], ...]:
        """Return the frozen (task_id, round_id) execution order.

        Historical campaigns ran one whole round at a time, which put the two
        sides in different hours and left provider-side drift inseparable from
        model noise.  From v7 the order is task-major, so both sides see each
        task within the same window.
        """

        tasks = tuple(item.task_id for item in self.catalog.tasks)
        if self.enforces_fair_comparison:
            return tuple(
                (task_id, round_id) for task_id in tasks for round_id in BASE_ROUNDS
            )
        return tuple(
            (task_id, round_id) for round_id in BASE_ROUNDS for task_id in tasks
        )

    @property
    def conditional_repeat_range(self) -> tuple[int, ...]:
        if self.enforces_fair_comparison:
            return tuple(range(1, self.conditional_repeats_per_side + 1))
        return (1, 2)

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
        repeats = self.conditional_repeat_range
        for attempt in range(1, self.max_attempts + 1):
            kind = "base" if attempt == 1 else "base_replacement"
            for task_id, round_id in self.base_round_order:
                side = round_sides[round_id]
                values.append(
                    self._slot(
                        index=index,
                        slot_id=f"base:{round_id}:{task_id}:a{attempt}",
                        kind=kind,
                        task_id=task_id,
                        side=side,
                        round_id=round_id,
                        repeat=None,
                        attempt=attempt,
                    )
                )
                index += 1
        for attempt in range(1, self.max_attempts + 1):
            kind = "conditional" if attempt == 1 else "conditional_replacement"
            for task_id in tasks:
                for side in (Side.RONDO, Side.CODEX):
                    for repeat in repeats:
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
        if index != self.max_run_slots:
            raise BaselineError("campaign slot plan differs from the frozen maximum")
        if (
            len(values) != self.max_run_slots
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


def campaign_slot_chain_id(slot: CampaignSlotPlan) -> str:
    if slot.kind == "wire_canary" or slot.attempt < 1:
        raise BaselineError("wire canary has no task attempt chain")
    suffix = f":a{slot.attempt}"
    if not slot.slot_id.endswith(suffix):
        raise BaselineError("campaign slot attempt suffix is invalid")
    return slot.slot_id[: -len(suffix)]


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
        if self.identity.schema_version >= 2:
            for diagnosis in state["diagnoses"]:
                if diagnosis["status"] == DiagnosisStatus.REQUIRED.value:
                    raise BaselineError("campaign has an unresolved diagnosis hold")
                if diagnosis.get("disposition") in {
                    DiagnosisDisposition.LOCAL_IMPLEMENTATION_DEFECT.value,
                    DiagnosisDisposition.SHARED_INFRASTRUCTURE_DEFECT.value,
                }:
                    raise BaselineError("campaign diagnosis requires terminal stop")
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

    def retire_blocked(self, *, reason: str) -> None:
        """Atomically retire an idle identity after a confirmed local defect."""

        if re.fullmatch(r"[a-z0-9_.:-]{1,256}", reason) is None:
            raise BaselineError("campaign retirement reason is invalid")
        state = self._require_state()
        if state["status"] != "running":
            raise BaselineError("campaign state is already terminal")
        if any(row["status"] == CampaignSlotStatus.RUNNING.value for row in state["slots"]):
            raise BaselineError("campaign cannot retire with a running slot")
        if not any(
            row["status"] in {
                CampaignSlotStatus.COMPLETED.value,
                CampaignSlotStatus.FAILED.value,
            }
            for row in state["slots"]
        ):
            raise BaselineError("campaign retirement has no durable execution fact")
        finished_at = int(time.time())
        for row in state["slots"]:
            if row["status"] == CampaignSlotStatus.PLANNED.value:
                row["status"] = CampaignSlotStatus.SKIPPED.value
                row["reason"] = "campaign_retired_after_local_defect"
                row["finished_at_unix"] = finished_at
        state["status"] = BaselineStatus.BLOCKED.value
        state["terminal_reason"] = reason
        self._persist(state)

    def require_diagnosis(
        self,
        *,
        chain_id: str,
        category: MechanicalFailureCategory,
        trigger_slot_ids: tuple[str, ...],
    ) -> dict[str, object]:
        if self.identity.schema_version < 2:
            raise BaselineError("diagnosis holds are unavailable for historical campaigns")
        if len(trigger_slot_ids) < 2 or len(set(trigger_slot_ids)) != len(trigger_slot_ids):
            raise BaselineError("diagnosis trigger slots are invalid")
        state = self._require_state()
        matches = [
            item
            for item in state["diagnoses"]
            if item["chain_id"] == chain_id and item["category"] == category.value
        ]
        if matches:
            if len(matches) != 1 or tuple(matches[0]["trigger_slot_ids"]) != trigger_slot_ids:
                raise BaselineError("diagnosis hold drifted from its triggering attempts")
            return json.loads(json.dumps(matches[0]))
        diagnosis = {
            "chain_id": chain_id,
            "category": category.value,
            "trigger_slot_ids": list(trigger_slot_ids),
            "status": DiagnosisStatus.REQUIRED.value,
            "disposition": None,
            "evidence_code": None,
            "created_at_unix": int(time.time()),
            "resolved_at_unix": None,
        }
        state["diagnoses"].append(diagnosis)
        self._persist(state)
        return json.loads(json.dumps(diagnosis))

    def resolve_diagnosis(
        self,
        *,
        chain_id: str,
        category: MechanicalFailureCategory,
        disposition: DiagnosisDisposition,
        evidence_code: DiagnosisEvidenceCode,
    ) -> None:
        if self.identity.schema_version < 2:
            raise BaselineError("diagnosis holds are unavailable for historical campaigns")
        allowed_codes = {
            DiagnosisDisposition.EXTERNAL_TRANSIENT: {
                _EXTERNAL_DIAGNOSIS_EVIDENCE.get(category)
            },
            DiagnosisDisposition.LOCAL_IMPLEMENTATION_DEFECT: {
                DiagnosisEvidenceCode.LOCAL_CONTRACT_DEFECT_CONFIRMED,
            },
            DiagnosisDisposition.SHARED_INFRASTRUCTURE_DEFECT: {
                DiagnosisEvidenceCode.SHARED_INFRASTRUCTURE_DEFECT_CONFIRMED,
            },
        }
        if evidence_code not in allowed_codes[disposition]:
            raise BaselineError("diagnosis evidence code disagrees with its disposition")
        state = self._require_state()
        matches = [
            item
            for item in state["diagnoses"]
            if item["chain_id"] == chain_id and item["category"] == category.value
        ]
        if len(matches) != 1 or matches[0]["status"] != DiagnosisStatus.REQUIRED.value:
            raise BaselineError("diagnosis hold is not uniquely resolvable")
        matches[0].update(
            {
                "status": DiagnosisStatus.RESOLVED.value,
                "disposition": disposition.value,
                "evidence_code": evidence_code.value,
                "resolved_at_unix": int(time.time()),
            }
        )
        self._persist(state)

    def mark_task_local_reproducible(
        self,
        *,
        chain_id: str,
        category: MechanicalFailureCategory,
        trigger_slot_ids: tuple[str, ...],
    ) -> None:
        if self.identity.schema_version < 2 or len(trigger_slot_ids) != 3:
            raise BaselineError("task-local reproducible failure is invalid")
        state = self._require_state()
        matches = [
            item
            for item in state["diagnoses"]
            if item["chain_id"] == chain_id and item["category"] == category.value
        ]
        if (
            len(matches) != 1
            or matches[0]["status"] != DiagnosisStatus.RESOLVED.value
            or matches[0]["disposition"]
            != DiagnosisDisposition.EXTERNAL_TRANSIENT.value
            or tuple(matches[0]["trigger_slot_ids"]) != trigger_slot_ids[:2]
        ):
            raise BaselineError("task-local failure lacks its resolved diagnosis")
        matches[0]["status"] = DiagnosisStatus.TASK_LOCAL_REPRODUCIBLE_INFRA.value
        matches[0]["trigger_slot_ids"] = list(trigger_slot_ids)
        matches[0]["resolved_at_unix"] = int(time.time())
        self._persist(state)

    def diagnosis(
        self,
        *,
        chain_id: str,
        category: MechanicalFailureCategory,
    ) -> dict[str, object] | None:
        state = self._require_state()
        if self.identity.schema_version < 2:
            return None
        matches = [
            item
            for item in state["diagnoses"]
            if item["chain_id"] == chain_id and item["category"] == category.value
        ]
        if len(matches) > 1:
            raise BaselineError("campaign diagnosis identity is duplicated")
        return json.loads(json.dumps(matches[0])) if matches else None

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
            "schema_version": self.identity.schema_version,
            "campaign_id": self.identity.campaign_id,
            "campaign_lock_sha256": self.identity.lock_sha256,
            "status": "running",
            "actual_usd": None,
            "terminal_reason": None,
            **({"diagnoses": []} if self.identity.schema_version >= 2 else {}),
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
        expected_keys = {
            "schema_version",
            "campaign_id",
            "campaign_lock_sha256",
            "status",
            "actual_usd",
            "terminal_reason",
            "slots",
        }
        if self.identity.schema_version >= 2:
            expected_keys.add("diagnoses")
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise BaselineError("campaign state ledger schema is invalid")
        slots = value["slots"]
        if (
            value["schema_version"] != self.identity.schema_version
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
        if self.identity.schema_version >= 2:
            self._validate_diagnoses(value["diagnoses"], slots=slots)

    def _validate_diagnoses(self, value: object, *, slots: list[object]) -> None:
        if not isinstance(value, list) or len(value) > len(self.identity.slots):
            raise BaselineError("campaign diagnosis list is invalid")
        expected_slots = {item.slot_id: item for item in self.identity.slots}
        state_rows = {
            item["slot_id"]: item for item in slots if isinstance(item, dict)
        }
        identities: set[tuple[str, str]] = set()
        for item in value:
            if not isinstance(item, dict) or set(item) != {
                "chain_id",
                "category",
                "trigger_slot_ids",
                "status",
                "disposition",
                "evidence_code",
                "created_at_unix",
                "resolved_at_unix",
            }:
                raise BaselineError("campaign diagnosis schema is invalid")
            try:
                category = MechanicalFailureCategory(item["category"])
                status = DiagnosisStatus(item["status"])
                disposition = (
                    None
                    if item["disposition"] is None
                    else DiagnosisDisposition(item["disposition"])
                )
                evidence_code = (
                    None
                    if item["evidence_code"] is None
                    else DiagnosisEvidenceCode(item["evidence_code"])
                )
            except (TypeError, ValueError) as exc:
                raise BaselineError("campaign diagnosis enum is invalid") from exc
            trigger_ids = item["trigger_slot_ids"]
            if (
                not isinstance(item["chain_id"], str)
                or not item["chain_id"]
                or len(item["chain_id"]) > 512
                or not isinstance(trigger_ids, list)
                or len(trigger_ids) not in {2, 3}
                or len(set(trigger_ids)) != len(trigger_ids)
                or any(slot_id not in expected_slots for slot_id in trigger_ids)
                or any(
                    state_rows[slot_id]["status"]
                    not in {
                        CampaignSlotStatus.COMPLETED.value,
                        CampaignSlotStatus.FAILED.value,
                    }
                    or state_rows[slot_id]["reason"] != category.value
                    for slot_id in trigger_ids
                )
                or any(
                    campaign_slot_chain_id(expected_slots[slot_id]) != item["chain_id"]
                    for slot_id in trigger_ids
                )
                or [expected_slots[slot_id].attempt for slot_id in trigger_ids]
                != sorted(expected_slots[slot_id].attempt for slot_id in trigger_ids)
                or isinstance(item["created_at_unix"], bool)
                or not isinstance(item["created_at_unix"], int)
                or item["created_at_unix"] < 0
            ):
                raise BaselineError("campaign diagnosis identity is invalid")
            identity = (item["chain_id"], category.value)
            if identity in identities:
                raise BaselineError("campaign diagnosis identity is duplicated")
            identities.add(identity)
            if status is DiagnosisStatus.REQUIRED:
                if disposition is not None or evidence_code is not None or item["resolved_at_unix"] is not None:
                    raise BaselineError("required diagnosis contains a resolution")
            else:
                if (
                    disposition is None
                    or evidence_code is None
                    or isinstance(item["resolved_at_unix"], bool)
                    or not isinstance(item["resolved_at_unix"], int)
                    or item["resolved_at_unix"] < item["created_at_unix"]
                ):
                    raise BaselineError("resolved diagnosis lacks bounded evidence")
            if (
                status is DiagnosisStatus.TASK_LOCAL_REPRODUCIBLE_INFRA
                and (len(trigger_ids) != 3 or disposition is not DiagnosisDisposition.EXTERNAL_TRANSIENT)
            ):
                raise BaselineError("task-local diagnosis is inconsistent")
            if status is not DiagnosisStatus.REQUIRED:
                expected_evidence = {
                    DiagnosisDisposition.EXTERNAL_TRANSIENT: (
                        _EXTERNAL_DIAGNOSIS_EVIDENCE.get(category)
                    ),
                    DiagnosisDisposition.LOCAL_IMPLEMENTATION_DEFECT: (
                        DiagnosisEvidenceCode.LOCAL_CONTRACT_DEFECT_CONFIRMED
                    ),
                    DiagnosisDisposition.SHARED_INFRASTRUCTURE_DEFECT: (
                        DiagnosisEvidenceCode.SHARED_INFRASTRUCTURE_DEFECT_CONFIRMED
                    ),
                }[disposition]
                if evidence_code is not expected_evidence:
                    raise BaselineError("diagnosis evidence disagrees with its category")

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


def campaign_lock_registry(paths: RepoPaths) -> tuple[CampaignLockRegistration, ...]:
    """Discover immutable historical locks and reject every identity collision."""

    root = paths.worktree_root / "eval/locks"
    values: list[CampaignLockRegistration] = []
    for path in root.glob("p2-b7-canary-baseline-v*.json"):
        match = _CAMPAIGN_LOCK_NAME.fullmatch(path.name)
        if match is None:
            continue
        raw = _read_regular_lock(path)
        try:
            lock = json.loads(raw)
            budget = lock["budget"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise BaselineError("historical campaign lock is invalid") from exc
        version = int(match.group(1))
        campaign_match = _CAMPAIGN_ID.fullmatch(str(lock.get("campaign_id")))
        batch_match = _CAMPAIGN_BATCH_ID.fullmatch(str(lock.get("batch_id")))
        max_slots = budget.get("max_run_slots")
        if (
            campaign_match is None
            or batch_match is None
            or int(campaign_match.group(1)) != version
            or int(batch_match.group(1)) != version
            or not isinstance(lock.get("run_id_date"), str)
            or re.fullmatch(r"[0-9]{8}", lock["run_id_date"]) is None
            or isinstance(lock.get("run_id_sequence_base"), bool)
            or not isinstance(lock.get("run_id_sequence_base"), int)
            or isinstance(max_slots, bool)
            or not isinstance(max_slots, int)
            or max_slots < 1
        ):
            raise BaselineError("historical campaign identity is invalid")
        values.append(
            CampaignLockRegistration(
                version=version,
                path=path.relative_to(paths.worktree_root),
                campaign_id=lock["campaign_id"],
                batch_id=lock["batch_id"],
                run_id_date=lock["run_id_date"],
                run_id_sequence_base=lock["run_id_sequence_base"],
                max_run_slots=max_slots,
                lock_sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
    values.sort(key=lambda item: item.version)
    if not values:
        raise BaselineError("campaign lock registry is empty")
    if [item.version for item in values] != list(range(1, len(values) + 1)):
        raise BaselineError("campaign lock versions are not contiguous")
    if len({item.campaign_id for item in values}) != len(values) or len(
        {item.batch_id for item in values}
    ) != len(values):
        raise BaselineError("campaign identities are duplicated")
    run_ids: set[tuple[str, int]] = set()
    for item in values:
        current = {
            (item.run_id_date, item.run_id_sequence_base + index)
            for index in range(item.max_run_slots)
        }
        if run_ids.intersection(current):
            raise BaselineError("campaign run ID ranges collide")
        run_ids.update(current)
    return tuple(values)


def load_campaign_identity(paths: RepoPaths) -> CampaignIdentity:
    """Load only the explicitly active P2 lock; historical locks are read-only."""

    pointer_path = paths.worktree_root / CAMPAIGN_ACTIVE_POINTER_PATH
    raw = _read_regular_lock(pointer_path)
    try:
        pointer = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BaselineError("active campaign pointer is invalid") from exc
    if not isinstance(pointer, dict) or set(pointer) != {"schema_version", "active_lock"}:
        raise BaselineError("active campaign pointer schema is invalid")
    if pointer["schema_version"] != 1:
        raise BaselineError("active campaign pointer version is invalid")
    active = pointer["active_lock"]
    if active is None:
        raise BaselineError("no paid B7 campaign identity is active")
    if not isinstance(active, str):
        raise BaselineError("active campaign lock path is invalid")
    registry = campaign_lock_registry(paths)
    matches = [item for item in registry if item.path.as_posix() == active]
    if len(matches) != 1:
        raise BaselineError("active campaign lock is not registered")
    if matches[0] != registry[-1]:
        raise BaselineError("active campaign lock is historical")
    return load_campaign_identity_path(paths, matches[0].path)


def load_historical_campaign_identity(
    paths: RepoPaths,
    version: int,
) -> CampaignIdentity:
    matches = [item for item in campaign_lock_registry(paths) if item.version == version]
    if len(matches) != 1:
        raise BaselineError("historical campaign version is not registered")
    return load_campaign_identity_path(paths, matches[0].path)


def load_campaign_identity_path(paths: RepoPaths, relative_path: Path) -> CampaignIdentity:
    """Load one current-contract lock without making it executable."""

    if relative_path.is_absolute() or relative_path.parent != Path("eval/locks"):
        raise BaselineError("campaign lock path is outside the registry")
    path = paths.worktree_root / relative_path
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
    if isinstance(value, dict) and value.get("schema_version") in {
        3,
        4,
        5,
        6,
        FAIR_COMPARISON_SCHEMA_VERSION,
    }:
        expected_keys.add("continuation")
    if (
        isinstance(value, dict)
        and value.get("schema_version") == FAIR_COMPARISON_SCHEMA_VERSION
    ):
        expected_keys.add("comparison")
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise BaselineError("campaign lock schema is invalid")
    schema_version = value["schema_version"]
    catalog_sha256 = value.get("canary_catalog_sha256")
    if not isinstance(catalog_sha256, str):
        raise BaselineError("campaign catalog identity is invalid")
    try:
        catalog = load_frozen_canary_catalog(
            paths,
            expected_sha256=catalog_sha256,
        )
    except ValueError as exc:
        raise BaselineError("campaign catalog identity is invalid") from exc
    comparison = _parse_comparison_block(value, schema_version=schema_version)
    if comparison is None:
        expected_baseline = campaign_baseline_contract(schema_version)
        expected_max_run_slots = None
    else:
        repeats = RepeatContract.from_dict(comparison["repeat_contract"])
        expected_baseline = campaign_baseline_contract(
            schema_version,
            conditional_repeats_per_side=repeats.repeats_per_task - 1,
        )
        expected_max_run_slots = campaign_slot_total(
            task_count=len(catalog.tasks),
            max_attempts=4,
            conditional_repeats_per_side=repeats.repeats_per_task - 1,
        )
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version not in SUPPORTED_SCHEMA_VERSIONS
        or _CAMPAIGN_ID.fullmatch(str(value["campaign_id"])) is None
        or _CAMPAIGN_BATCH_ID.fullmatch(str(value["batch_id"])) is None
        or _CAMPAIGN_ID.fullmatch(value["campaign_id"]).group(1)
        != _CAMPAIGN_BATCH_ID.fullmatch(value["batch_id"]).group(1)
        or re.fullmatch(r"[0-9]{8}", str(value["run_id_date"])) is None
        or isinstance(value["run_id_sequence_base"], bool)
        or not isinstance(value["run_id_sequence_base"], int)
        or value["taskset_sha256"] != catalog.taskset_sha256
        or catalog_sha256 != catalog.catalog_sha256
        or value["terminal_bench_commit"] != catalog.terminal_bench_commit
        or not isinstance(value["selected_profile"], dict)
        or not isinstance(value["bundles"], dict)
        or not isinstance(value["no_api_seccomp"], dict)
        or not _valid_campaign_budget(
            value["budget"],
            schema_version=schema_version,
            expected_max_run_slots=expected_max_run_slots,
        )
        or value["baseline"] != expected_baseline
    ):
        raise BaselineError("campaign lock differs from the frozen B7 contract")
    selected = value["selected_profile"]
    required_selected = {
        "provider_profile_sha256",
        "provider_endpoint_sha256",
        "frozen_codex_model_catalog_sha256",
    }
    if comparison is not None:
        # From v7 the catalog artifact is no longer a Codex-only projection, so
        # its identity lives in the comparison block instead.
        required_selected.discard("frozen_codex_model_catalog_sha256")
    if any(
        not isinstance(selected.get(key), str)
        or _SHA256.fullmatch(selected[key]) is None
        for key in required_selected
    ):
        raise BaselineError("campaign selected profile hashes are invalid")
    continuation = _parse_continuation_references(
        value.get("continuation", []),
        schema_version=schema_version,
        successor_timeout=Decimal(
            str(value["baseline"].get("upstream_timeout_seconds", LEGACY_UPSTREAM_TIMEOUT_SECONDS))
        ),
    )
    identity = CampaignIdentity(
        schema_version=schema_version,
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
        continuation=continuation,
        comparison=comparison,
    )
    if comparison is not None:
        # Touch every frozen accessor so a malformed block fails at load time
        # rather than in the middle of a campaign, then require the declared
        # conditions to equal the ones the rest of the lock already implies.
        # Otherwise the block could freeze a comparison contract that
        # contradicts the campaign it belongs to.
        _ = (
            identity.repeat_contract,
            identity.catalog_identity,
            identity.product,
        )
        identity.require_declared_conditions()
    _validate_continuation_topology(identity)
    _ = identity.slots
    if not any(
        item.path == relative_path and item.lock_sha256 == identity.lock_sha256
        for item in campaign_lock_registry(paths)
    ):
        raise BaselineError("campaign lock is not registered")
    return identity


def _parse_comparison_block(
    value: dict[str, object],
    *,
    schema_version: object,
) -> dict[str, object] | None:
    """Return the frozen fair-comparison block, or ``None`` before v7.

    A v7 campaign may not be created until the repeat count, the aggregation
    formula, the run conditions and the shared catalog identity are all frozen
    in the lock, so every one of them is required here.
    """

    if schema_version != FAIR_COMPARISON_SCHEMA_VERSION:
        if "comparison" in value:
            raise BaselineError(
                "historical campaign locks cannot carry a fair-comparison block"
            )
        return None
    block = value.get("comparison")
    if not isinstance(block, dict) or set(block) != {
        "repeat_contract",
        "comparison_conditions",
        "catalog_identity",
        "product",
    }:
        raise BaselineError("campaign fair-comparison contract is not frozen")
    try:
        RepeatContract.from_dict(block["repeat_contract"])
        ComparisonConditions.from_dict(block["comparison_conditions"])
    except FairComparisonError as exc:
        raise BaselineError(f"campaign fair-comparison contract is invalid: {exc}") from exc
    identity = block["catalog_identity"]
    if not isinstance(identity, dict) or set(identity) != {
        "sha256",
        "projection_algorithm",
        "projection_version",
        "main_model",
        "guardian_model",
        "override_target_slug",
        "model_slugs",
        "sources",
    }:
        raise BaselineError("campaign catalog identity is not frozen")
    sources = identity["sources"]
    if (
        not isinstance(sources, list)
        or len(sources) != 2
        or {item.get("side") for item in sources if isinstance(item, dict)}
        != {"upstream", "rondo"}
        or any(
            not isinstance(item, dict)
            or set(item) != {"side", "commit", "path", "blob_id"}
            for item in sources
        )
    ):
        raise BaselineError("campaign catalog provenance is incomplete")
    if _SHA256.fullmatch(str(identity["sha256"])) is None:
        raise BaselineError("campaign catalog artifact digest is invalid")
    # Every provenance field must be well formed, not merely present: a lock
    # that records "commit: zzz" proves nothing about where the bytes came from.
    by_side = {str(item["side"]): item for item in sources}
    for side, expected_path in (
        ("upstream", UPSTREAM_CATALOG_PATH),
        ("rondo", RONDO_CATALOG_PATH),
    ):
        item = by_side[side]
        if (
            _GIT_OBJECT.fullmatch(str(item["commit"])) is None
            or _GIT_OBJECT.fullmatch(str(item["blob_id"])) is None
            or str(item["path"]) != expected_path
        ):
            raise BaselineError("campaign catalog provenance is invalid")
    if by_side["upstream"]["blob_id"] != by_side["rondo"]["blob_id"]:
        raise BaselineError("campaign catalog sources record different blobs")
    slugs = identity["model_slugs"]
    if (
        identity["projection_algorithm"] != CATALOG_PROJECTION_ALGORITHM
        or identity["projection_version"] != CATALOG_PROJECTION_VERSION
        or not isinstance(slugs, list)
        or not slugs
        or len(set(slugs)) != len(slugs)
        or any(_MODEL_SLUG.fullmatch(str(slug)) is None for slug in slugs)
    ):
        raise BaselineError("campaign catalog projection is invalid")
    for key in ("main_model", "guardian_model", "override_target_slug"):
        if _MODEL_SLUG.fullmatch(str(identity[key])) is None:
            raise BaselineError("campaign catalog model identity is invalid")
    if (
        identity["override_target_slug"] != identity["main_model"]
        or identity["override_target_slug"] not in slugs
        or identity["guardian_model"] not in slugs
    ):
        raise BaselineError("campaign catalog override target is invalid")
    try:
        Product(str(block["product"]))
    except ValueError as exc:
        raise BaselineError("campaign product identity is invalid") from exc
    return dict(block)


def campaign_slot_total(
    *,
    task_count: int,
    max_attempts: int,
    conditional_repeats_per_side: int,
) -> int:
    """Return the exact slot count a campaign plan must produce."""

    if task_count <= 0 or max_attempts <= 0 or conditional_repeats_per_side <= 0:
        raise BaselineError("campaign slot geometry is invalid")
    base = len(BASE_ROUNDS) * task_count * max_attempts
    conditional = task_count * 2 * conditional_repeats_per_side * max_attempts
    return 1 + base + conditional


def campaign_baseline_contract(
    schema_version: int,
    *,
    conditional_repeats_per_side: int = 2,
) -> dict[str, object]:
    common: dict[str, object] = {
        "base_rounds": list(BASE_ROUNDS),
        "max_sigma": MAX_SIGMA,
        "max_remaining_infra_per_round": MAX_REMAINING_INFRA_PER_ROUND,
        "mechanical_circuit_breaker_tasks": MECHANICAL_CIRCUIT_BREAKER_TASKS,
        "mechanical_failure_categories": [
            item.value for item in MechanicalFailureCategory
        ],
        "minimum_common_valid_tasks": MIN_COMMON_VALID_TASKS,
        "conditional_repeats_per_side": (
            conditional_repeats_per_side
            if schema_version >= FAIR_COMPARISON_SCHEMA_VERSION
            else 2
        ),
        "docker_concurrency": 1,
        "api_max_retries": 0,
    }
    if schema_version == 1:
        return {
            **common,
            "base_replacement_policy": "targeted_infra_only",
            "max_base_replacement_attempts": 1,
            "max_conditional_replacement_attempts": 1,
        }
    if schema_version == 2:
        return {
            **common,
            "base_replacement_policy": "bounded_infra_only_with_diagnosis",
            "max_base_attempts": 4,
            "max_conditional_attempts": 4,
            "same_category_diagnosis_attempts": 2,
            "task_local_reproducible_infra_attempts": 3,
        }
    if schema_version == 3:
        return {
            **common,
            "base_replacement_policy": "cross_identity_infra_only_continuation",
            "max_base_attempts": 4,
            "max_conditional_attempts": 4,
            "same_category_diagnosis_attempts": 2,
            "task_local_reproducible_infra_attempts": 3,
            "provider_response_integrity_circuit_breaker": False,
            "upstream_timeout_seconds": f"{CAMPAIGN_UPSTREAM_TIMEOUT_SECONDS:.3f}",
            "timeout_compatibility": "monotonic_extension",
        }
    if schema_version == 4:
        return {
            **campaign_baseline_contract(3),
            "concurrent_guardian_capacity_admission": (
                "main_plus_guardian_max_reservation"
            ),
            "continuation_compatibility": "monotonic_budget_admission_fix",
        }
    if schema_version == 5:
        return {
            **campaign_baseline_contract(4),
            "guardian_evidence_input_scanning": (
                "exact_runtime_secret_then_structured_untrusted_input"
            ),
            "provider_terminal_diagnostics": "bounded_protocol_facts_v1",
            "continuation_compatibility": (
                "monotonic_publication_scanner_and_terminal_diagnostics"
            ),
        }
    if schema_version == 6:
        return {
            **campaign_baseline_contract(5),
            "campaign_ledger_capacity": "authorized_remaining_cap_up_to_1600_usd",
            "continuation_compatibility": "monotonic_campaign_ledger_capacity_fix",
        }
    if schema_version == FAIR_COMPARISON_SCHEMA_VERSION:
        return {
            **campaign_baseline_contract(6),
            "conditional_repeats_per_side": conditional_repeats_per_side,
            "execution_order": EXECUTION_ORDER_TASK_INTERLEAVED,
            "assessment_layers": list(ASSESSMENT_LAYERS),
            "conditional_aggregation": AGGREGATION_STRICT_MAJORITY,
            "shared_model_catalog": "both_sides_load_one_artifact",
            "task_independent_request_preflight": "required_before_upstream",
            "continuation_compatibility": "fair_comparison_contract_v1",
        }
    raise BaselineError("campaign baseline contract version is unsupported")


def _valid_campaign_budget(
    value: object,
    *,
    schema_version: int,
    expected_max_run_slots: int | None = None,
) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "campaign_cap_usd",
        "prior_estimated_usd",
        "run_cap_usd",
        "max_run_slots",
        "maximum_legal_request_reservation_usd",
        "actual_usd",
    }:
        return False
    try:
        cap = Decimal(value["campaign_cap_usd"])
        prior = Decimal(value["prior_estimated_usd"])
    except (ArithmeticError, TypeError):
        return False
    if expected_max_run_slots is not None:
        expected_slots = expected_max_run_slots
    else:
        expected_slots = (
            LEGACY_CAMPAIGN_MAX_RUNS if schema_version == 1 else CAMPAIGN_MAX_RUNS
        )
    valid_caps = {
        1: {LEGACY_CAMPAIGN_CAP_USD},
        2: {
            HISTORICAL_SCHEMA_V2_CAMPAIGN_CAP_USD,
            HISTORICAL_SCHEMA_V3_CAMPAIGN_CAP_USD,
        },
        3: {HISTORICAL_SCHEMA_V3_CAMPAIGN_CAP_USD},
        4: {HISTORICAL_SCHEMA_V4_CAMPAIGN_CAP_USD},
        5: {CAMPAIGN_CAP_USD},
        6: {CAMPAIGN_CAP_USD},
    }.get(schema_version, set())
    if schema_version == FAIR_COMPARISON_SCHEMA_VERSION:
        # A fair-comparison campaign carries no continuation, so it starts with
        # no inherited spend and its own separately authorized cap.  The
        # historical envelope stays the ceiling so a typo cannot widen it.
        cap_valid = (
            Decimal(0) < cap <= CAMPAIGN_CAP_USD
            and value["campaign_cap_usd"] == _money(cap)
            and prior == Decimal(0)
        )
    else:
        cap_valid = cap in valid_caps and Decimal(0) <= prior < cap
    return (
        cap_valid
        and value["run_cap_usd"] == _money(RUN_CAP_USD)
        and value["max_run_slots"] == expected_slots
        and value["maximum_legal_request_reservation_usd"]
        == _money(SOL_MAX_LEGAL_REQUEST_RESERVATION_USD)
        and value["actual_usd"] is None
    )


def _parse_continuation_references(
    value: object,
    *,
    schema_version: int,
    successor_timeout: Decimal,
) -> tuple[ContinuationReference, ...]:
    if schema_version < 3:
        if value != []:
            raise BaselineError("historical campaign unexpectedly has continuation data")
        return ()
    if schema_version == FAIR_COMPARISON_SCHEMA_VERSION:
        # No v1--v22 result was produced under the fair-comparison conditions,
        # so none of them may enter a v7 aggregate.
        if value != []:
            raise BaselineError(
                "fair-comparison campaigns cannot inherit historical continuation"
            )
        return ()
    if not isinstance(value, list) or len(value) > 80:
        raise BaselineError("campaign continuation list is invalid")
    values: list[ContinuationReference] = []
    expected_keys = {
        "chain_id",
        "source_campaign_id",
        "source_campaign_lock_sha256",
        "source_slot_id",
        "source_run_id",
        "source_result_record_sha256",
        "source_upstream_timeout_seconds",
    }
    for item in value:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise BaselineError("campaign continuation reference schema is invalid")
        try:
            source_timeout = Decimal(str(item["source_upstream_timeout_seconds"]))
        except ArithmeticError as exc:
            raise BaselineError("campaign continuation timeout is invalid") from exc
        if (
            not isinstance(item["chain_id"], str)
            or not item["chain_id"]
            or len(item["chain_id"]) > 512
            or _CAMPAIGN_ID.fullmatch(str(item["source_campaign_id"])) is None
            or not isinstance(item["source_slot_id"], str)
            or not item["source_slot_id"]
            or len(item["source_slot_id"]) > 512
            or _RUN_ID.fullmatch(str(item["source_run_id"])) is None
            or any(
                _SHA256.fullmatch(str(item[key])) is None
                for key in (
                    "source_campaign_lock_sha256",
                    "source_result_record_sha256",
                )
            )
            or source_timeout < LEGACY_UPSTREAM_TIMEOUT_SECONDS
            or source_timeout > successor_timeout
        ):
            raise BaselineError("campaign continuation reference is invalid")
        values.append(
            ContinuationReference(
                chain_id=item["chain_id"],
                source_campaign_id=item["source_campaign_id"],
                source_campaign_lock_sha256=item["source_campaign_lock_sha256"],
                source_slot_id=item["source_slot_id"],
                source_run_id=item["source_run_id"],
                source_result_record_sha256=item["source_result_record_sha256"],
                source_upstream_timeout_seconds=source_timeout,
            )
        )
    if (
        len({item.chain_id for item in values}) != len(values)
        or len({item.source_run_id for item in values}) != len(values)
    ):
        raise BaselineError("campaign continuation identity is duplicated")
    return tuple(values)


def _validate_continuation_topology(identity: CampaignIdentity) -> None:
    if identity.schema_version < 3:
        if identity.continuation:
            raise BaselineError("historical campaign continuation is invalid")
        return
    chains = {
        campaign_slot_chain_id(slot)
        for slot in identity.slots
        if slot.kind != "wire_canary"
    }
    for reference in identity.continuation:
        if (
            reference.chain_id not in chains
            or not reference.source_slot_id.startswith(reference.chain_id + ":a")
            or reference.source_campaign_id == identity.campaign_id
        ):
            raise BaselineError("campaign continuation topology is invalid")


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
    remaining_before_successor_canary = (
        CAMPAIGN_CAP_USD - CAMPAIGN_PRIOR_ESTIMATED_USD
    )
    return {
        "schema_version": 2,
        "currency": "USD",
        "actual_usd": None,
        "campaign_cap_usd": _money(CAMPAIGN_CAP_USD),
        "prior_estimated_usd": _money(CAMPAIGN_PRIOR_ESTIMATED_USD),
        "remaining_before_successor_canary_usd": _money(
            remaining_before_successor_canary
        ),
        "base_runs": 40,
        "maximum_conditional_runs": 40,
        "maximum_infra_reproduction_runs": 240,
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
        "feasible_from_observed_shape": (
            observed_shape_stress < remaining_before_successor_canary
        ),
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
    *,
    max_attempts: int = 2,
    repeat_contract: RepeatContract | None = None,
) -> BaselineAssessment:
    """Select bounded infra replacements and apply the frozen B7 gates.

    Without ``repeat_contract`` this replays the historical single-``reasons``
    assessment exactly.  With one, the three sub-gates are reported separately
    and the frozen repeats are aggregated into the per-task outcome that the
    cross-side comparison actually uses.
    """

    if repeat_contract is not None:
        repeat_contract.validate()
    repeats = (
        tuple(range(1, repeat_contract.repeats_per_task))
        if repeat_contract is not None
        else (1, 2)
    )
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
            max_attempts=max_attempts,
        )
        effective_base.extend(selected)
        remaining_infra = sum(
            item.outcome is TaskOutcome.INFRA for item in selected
        )
        if remaining_infra > MAX_REMAINING_INFRA_PER_ROUND:
            blocked.append(f"{round_id}_infra_threshold_exceeded")

    by_round = {
        round_id: {item.task_id: item.outcome for item in effective_base if item.round_id == round_id}
        for round_id in BASE_ROUNDS
    }
    common_valid_tasks = tuple(
        task_id
        for task_id in task_ids
        if all(
            by_round[round_id][task_id] is not TaskOutcome.INFRA
            for round_id in BASE_ROUNDS
        )
    )
    if len(common_valid_tasks) < MIN_COMMON_VALID_TASKS:
        blocked.append("common_valid_task_count_below_minimum")
    if blocked:
        return BaselineAssessment(
            BaselineStatus.BLOCKED,
            tuple(blocked),
            None,
            None,
            common_valid_tasks,
            (),
            tuple(effective_base),
            (),
        )
    sigma = sum(
        by_round["aa-rondo-1"][task_id]
        is not by_round["aa-rondo-2"][task_id]
        for task_id in common_valid_tasks
    )
    delta = sum(
        by_round["ab-rondo-1"][task_id]
        is not by_round["ab-codex-1"][task_id]
        for task_id in common_valid_tasks
    )
    # Under a frozen repeat contract every cross-side disagreement is repeated,
    # in both directions.  The historical one-way trigger meant a
    # RONDO-pass/Codex-fail task silently stayed a single observation while its
    # mirror image got three, so `delta` mixed the two.  The directional
    # backstop below stays one-way -- it detects regressions, not differences.
    if repeat_contract is not None:
        triggers = tuple(
            task_id
            for task_id in common_valid_tasks
            if by_round["ab-rondo-1"][task_id] is not by_round["ab-codex-1"][task_id]
        )
    else:
        triggers = tuple(
            task_id
            for task_id in common_valid_tasks
            if by_round["ab-rondo-1"][task_id] is TaskOutcome.FAIL
            and by_round["ab-codex-1"][task_id] is TaskOutcome.PASS
        )
    effective_conditional: list[ConditionalRun] = []
    for task_id in triggers:
        for side in (Side.RONDO, Side.CODEX):
            for repeat in repeats:
                selected = _select_conditional(
                    task_id,
                    side,
                    repeat,
                    conditional_runs,
                    max_attempts=max_attempts,
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
            common_valid_tasks,
            triggers,
            tuple(effective_base),
            tuple(effective_conditional),
        )

    def _side_observations(task_id: str, side: Side) -> list[TaskOutcome]:
        base_round = "ab-rondo-1" if side is Side.RONDO else "ab-codex-1"
        return [
            by_round[base_round][task_id],
            *(
                item.outcome
                for item in effective_conditional
                if item.task_id == task_id and item.side is side
            ),
        ]

    reasons: list[str] = []
    if sigma > MAX_SIGMA:
        reasons.append("aa_sigma_exceeds_frozen_stability_limit")
    if delta > sigma:
        reasons.append("ab_delta_exceeds_aa_sigma")
    directional: list[str] = []
    for task_id in triggers:
        rondo = _side_observations(task_id, Side.RONDO)
        codex = _side_observations(task_id, Side.CODEX)
        # Regression detection stays deliberately one-way: RONDO failing every
        # frozen repeat while the frozen upstream passes every one.
        if all(item is TaskOutcome.FAIL for item in rondo) and all(
            item is TaskOutcome.PASS for item in codex
        ):
            directional.append(f"stable_directional_regression:{task_id}")
    reasons.extend(directional)
    if repeat_contract is None:
        status = BaselineStatus.FAILED if reasons else BaselineStatus.PASSED
        return BaselineAssessment(
            status,
            tuple(reasons),
            sigma,
            delta,
            common_valid_tasks,
            triggers,
            tuple(effective_base),
            tuple(effective_conditional),
        )

    # The frozen repeats are part of the result, not a side channel: every
    # triggered task's per-side outcome is the strict majority over its frozen
    # observations, and that aggregate is what the cross-side gate compares.
    aggregated: list[tuple[str, str, TaskOutcome]] = []
    aggregation_reasons: list[str] = []
    effective_delta = 0
    for task_id in common_valid_tasks:
        per_side: dict[Side, TaskOutcome] = {}
        for side in (Side.RONDO, Side.CODEX):
            observations = tuple(_side_observations(task_id, side))
            if task_id in triggers:
                try:
                    outcome = aggregate_repeat_outcomes(
                        observations,
                        contract=repeat_contract,
                        pass_value=TaskOutcome.PASS,
                        fail_value=TaskOutcome.FAIL,
                    )
                except FairComparisonError as exc:
                    aggregation_reasons.extend(
                        f"{reason}:{task_id}:{side.value}" for reason in exc.reasons
                    )
                    outcome = observations[0]
            else:
                outcome = observations[0]
            per_side[side] = outcome
            aggregated.append((task_id, side.value, outcome))
        if per_side[Side.RONDO] is not per_side[Side.CODEX]:
            effective_delta += 1

    if aggregation_reasons:
        return BaselineAssessment(
            BaselineStatus.BLOCKED,
            tuple(aggregation_reasons),
            sigma,
            effective_delta,
            common_valid_tasks,
            triggers,
            tuple(effective_base),
            tuple(effective_conditional),
            (),
            tuple(aggregated),
        )

    aa_reasons = (
        ("aa_sigma_exceeds_frozen_stability_limit",) if sigma > MAX_SIGMA else ()
    )
    cross_reasons = ("ab_delta_exceeds_aa_sigma",) if effective_delta > sigma else ()
    layers = (
        AssessmentLayer(
            "aa_consistency",
            BaselineStatus.FAILED if aa_reasons else BaselineStatus.PASSED,
            aa_reasons,
            (("sigma", sigma), ("max_sigma", MAX_SIGMA)),
        ),
        AssessmentLayer(
            "cross_side",
            BaselineStatus.FAILED if cross_reasons else BaselineStatus.PASSED,
            cross_reasons,
            (
                ("delta", effective_delta),
                ("base_delta", delta),
                ("sigma", sigma),
                ("repeats_per_task", repeat_contract.repeats_per_task),
                ("aggregation", repeat_contract.aggregation),
            ),
        ),
        AssessmentLayer(
            "directional",
            BaselineStatus.FAILED if directional else BaselineStatus.PASSED,
            tuple(directional),
            (("repeated_tasks", len(triggers)),),
        ),
    )
    layer_reasons = tuple(
        reason for layer in layers for reason in layer.reasons
    )
    status = BaselineStatus.FAILED if layer_reasons else BaselineStatus.PASSED
    return BaselineAssessment(
        status,
        layer_reasons,
        sigma,
        effective_delta,
        common_valid_tasks,
        triggers,
        tuple(effective_base),
        tuple(effective_conditional),
        layers,
        tuple(aggregated),
    )


def _select_round(
    task_ids: tuple[str, ...],
    values: tuple[BaselineRun, ...],
    *,
    expected_side: Side,
    label: str,
    max_attempts: int,
) -> tuple[BaselineRun, ...]:
    if max_attempts not in {2, 4}:
        raise BaselineError("campaign attempt limit is invalid")
    if any(
        item.side is not expected_side
        or item.attempt not in set(range(1, max_attempts + 1))
        or item.task_id not in task_ids
        for item in values
    ):
        raise BaselineError(f"{label} contains an invalid run")
    _require_unique_runs(values)
    selected: dict[str, BaselineRun] = {}
    for task_id in task_ids:
        attempts = sorted(
            (item for item in values if item.task_id == task_id),
            key=lambda item: item.attempt,
        )
        if not attempts or [item.attempt for item in attempts] != list(
            range(1, len(attempts) + 1)
        ):
            raise BaselineError(f"{label} attempt chain is incomplete")
        if any(item.outcome is not TaskOutcome.INFRA for item in attempts[:-1]):
            raise BaselineError(f"{label} retried a non-infra result")
        last = attempts[-1]
        if last.outcome is TaskOutcome.INFRA and len(attempts) < max_attempts:
            category_counts = {
                category: sum(item.failure_category is category for item in attempts)
                for category in MechanicalFailureCategory
            }
            if max_attempts == 2 or max(category_counts.values(), default=0) < 3:
                raise BaselineError(f"{label} infra attempt chain stopped early")
        selected[task_id] = last
    return tuple(selected[task_id] for task_id in task_ids)


def _select_conditional(
    task_id: str,
    side: Side,
    repeat: int,
    values: tuple[ConditionalRun, ...],
    *,
    max_attempts: int,
) -> ConditionalRun | None:
    matches = tuple(
        item
        for item in values
        if item.task_id == task_id and item.side is side and item.repeat == repeat
    )
    if max_attempts not in {2, 4} or not matches or any(
        item.attempt not in set(range(1, max_attempts + 1)) for item in matches
    ):
        raise BaselineError("conditional run is missing or invalid")
    _require_unique_runs(matches)
    attempts = sorted(matches, key=lambda item: item.attempt)
    if [item.attempt for item in attempts] != list(range(1, len(attempts) + 1)):
        raise BaselineError("conditional attempt chain is incomplete")
    if any(item.outcome is not TaskOutcome.INFRA for item in attempts[:-1]):
        raise BaselineError("conditional retried a non-infra result")
    last = attempts[-1]
    if last.outcome is not TaskOutcome.INFRA:
        return last
    if len(attempts) < max_attempts:
        category_counts = {
            category: sum(item.failure_category is category for item in attempts)
            for category in MechanicalFailureCategory
        }
        if max_attempts == 2 or max(category_counts.values(), default=0) < 3:
            raise BaselineError("conditional infra attempt chain stopped early")
    return None


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
