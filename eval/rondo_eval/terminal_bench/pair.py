"""Tracked P1 pair identity, shared preflight, and M1 aggregation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import fcntl
import json
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from ..contracts import (
    BinaryManifest,
    ModelPricing,
    ProviderProjection,
    RunOutcome,
    RunSpec,
    Side,
    assert_fair_pair,
)
from ..exit_codes import EVIDENCE_ERROR, INFRA_ERROR
from .freeze import (
    FIX_GIT_IMAGE_DIGEST,
    FIX_GIT_TASK_ID,
    HARBOR_PACKAGE,
    HARBOR_RELEASE_COMMIT,
    HARBOR_VERSION,
    HARBOR_WHEEL_SHA256,
    TERMINAL_BENCH_VERSION,
)
from .metrics import RunMetricsError, metrics_from_dict

if TYPE_CHECKING:
    from .runner import PreparedTerminalBenchRun


PAIR_LOCK_PATH = Path(__file__).resolve().parents[2] / "locks" / "p1-terminal-bench-pair-v7.json"
PREVIOUS_PAIR_LOCK_PATH = (
    Path(__file__).resolve().parents[2] / "locks" / "p1-terminal-bench-pair-v6.json"
)
CONSUMED_V12_PAIR_LOCK_PATH = (
    Path(__file__).resolve().parents[2] / "locks" / "p1-terminal-bench-pair-v5.json"
)
CONSUMED_V11_PAIR_LOCK_PATH = (
    Path(__file__).resolve().parents[2] / "locks" / "p1-terminal-bench-pair-v4.json"
)
CONSUMED_V10_PAIR_LOCK_PATH = (
    Path(__file__).resolve().parents[2] / "locks" / "p1-terminal-bench-pair-v3.json"
)
CONSUMED_V9_PAIR_LOCK_PATH = (
    Path(__file__).resolve().parents[2] / "locks" / "p1-terminal-bench-pair-v2.json"
)
LEGACY_PAIR_LOCK_PATH = (
    Path(__file__).resolve().parents[2] / "locks" / "p1-terminal-bench-pair-v1.json"
)
P1_PAIR_ID = "p1-fix-git-pair-v14"
PREVIOUS_P1_PAIR_ID = "p1-fix-git-pair-v13"
CONSUMED_V12_P1_PAIR_ID = "p1-fix-git-pair-v12"
CONSUMED_V11_P1_PAIR_ID = "p1-fix-git-pair-v11"
CONSUMED_V10_P1_PAIR_ID = "p1-fix-git-pair-v10"
CONSUMED_V9_P1_PAIR_ID = "p1-fix-git-pair-v9"
LEGACY_P1_PAIR_ID = "p1-fix-git-pair-v8"
_TEN_USD_PAIR_IDS = {
    P1_PAIR_ID,
    PREVIOUS_P1_PAIR_ID,
    CONSUMED_V12_P1_PAIR_ID,
    CONSUMED_V11_P1_PAIR_ID,
}
B2_NO_API_BATCH_ID = "p1-no-api-smoke"
_PAIR_LOCK_V1_KEYS = {
    "schema_version",
    "pair_id",
    "modes",
    "topology",
    "fairness",
    "harbor",
    "no_api_seccomp",
    "runtime_requirements",
    "bundles",
}
_PAIR_LOCK_V2_KEYS = _PAIR_LOCK_V1_KEYS | {"paid_budget", "selected_profile"}
_PAID_MODE_KEYS = {"enabled", "batch_id", "disabled_reason"}
_PAID_BUDGET_KEYS = {"per_side_usd", "pair_usd"}
_SLOT_KEYS = {"slot", "side", "round", "paid_run_id"}
_BUNDLE_KEYS = {
    "manifest_path",
    "manifest_sha256",
    "cli_sha256",
    "cli_size",
    "code_mode_host_sha256",
    "code_mode_host_size",
    "bwrap_sha256",
    "bwrap_size",
    "source_commit",
    "workspace_lock_normalization",
}
_FAIRNESS_V1_KEYS = {
    "task_id",
    "task_image_digest",
    "terminal_bench_version",
    "provider_id",
    "provider_api",
    "provider_api_key_env",
    "main_model",
    "guardian_model",
    "guardian_effort",
    "approvals_reviewer",
    "approval_policy",
    "sandbox_mode",
    "sandbox_network_access",
    "websocket",
    "code_mode_host",
    "timeout_seconds",
    "max_retries",
    "budget_usd",
}
_FAIRNESS_V2_KEYS = {
    "task_id",
    "task_image_digest",
    "terminal_bench_version",
    "approvals_reviewer",
    "approval_policy",
    "sandbox_mode",
    "sandbox_network_access",
    "websocket",
    "code_mode_host",
    "timeout_seconds",
    "max_retries",
    "budget_usd",
}
_PUBLIC_PROVIDER_KEYS = {
    "provider",
    "provider_api",
    "provider_profile_sha256",
    "provider_endpoint_sha256",
    "main_model",
    "main_effort",
    "guardian_model",
    "guardian_effort",
    "requested_main_model",
    "effective_main_model",
    "requested_guardian_model",
    "effective_guardian_model",
    "main_pricing",
    "guardian_pricing",
    "provider_max_attempts",
    "provider_retry_backoff_seconds",
    "provider_unbilled_retry_statuses",
}
_SELECTED_PROFILE_KEYS = _PUBLIC_PROVIDER_KEYS | {
    "frozen_codex_model_catalog_source_commit",
    "frozen_codex_model_catalog_sha256",
    "max_guardian_logical_requests",
}
_HARBOR_KEYS = {
    "package",
    "version",
    "release_commit",
    "wheel_sha256",
    "uv_lock_sha256",
    "console_script_normalized_sha256",
    "console_script_normalization",
    "key_files",
}
_SECCOMP_KEYS = {"profile_path", "source_sha256", "effective_sha256"}
_RUNTIME_REQUIREMENT_KEYS = {
    "paid_custom_seccomp_required",
    "m1_pair_ledger_required",
    "m1_container_metrics_required",
}


class PairIdentityError(ValueError):
    """Raised when a run cannot prove the tracked pair identity."""


class PairSequenceLedger:
    """Persistent two-slot order gate for paid runs only."""

    def __init__(
        self,
        path: Path,
        *,
        identity: PairIdentity,
        mode: str,
        persist_hook: Callable[[str], None] | None = None,
        read_only: bool = False,
    ) -> None:
        if mode != "paid":
            raise PairIdentityError("pair sequence ledger is paid-only")
        selected = identity.mode("paid")
        self.path = path
        self.identity = identity
        self.mode_name = mode
        self.batch_id = selected.batch_id
        self._lock_path = path.with_name(f"{path.name}.lock")
        self._handle: Any | None = None
        self._state: dict[str, Any] | None = None
        self._persist_hook = persist_hook or (lambda _point: None)
        self._read_only = read_only
        if (
            identity.schema_version != 2 or identity.pair_id != P1_PAIR_ID
        ) and not read_only:
            raise PairIdentityError("historical pair identity is read-only")

    def __enter__(self) -> PairSequenceLedger:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(self._lock_path, flags, 0o600)
            lock_stat = os.fstat(descriptor)
            if not stat.S_ISREG(lock_stat.st_mode):
                os.close(descriptor)
                raise PairIdentityError("pair sequence lock must be a regular file")
            os.fchmod(descriptor, 0o600)
            handle = os.fdopen(descriptor, "r+", encoding="utf-8")
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except OSError as exc:
            raise PairIdentityError("pair sequence ledger is unavailable") from exc
        self._handle = handle
        exists = self.path.exists() or self.path.is_symlink()
        if exists:
            try:
                metadata = self.path.lstat()
                if self.path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                    raise PairIdentityError("pair sequence ledger must be a regular file")
                raw = self.path.read_bytes()
                if not raw or len(raw) > 1024 * 1024:
                    raise PairIdentityError("pair sequence ledger is empty or oversized")
                state = json.loads(raw.decode("utf-8"))
            except PairIdentityError:
                self.__exit__(None, None, None)
                raise
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                self.__exit__(None, None, None)
                raise PairIdentityError("pair sequence ledger is unreadable") from exc
            try:
                _validate_sequence_state(
                    state,
                    identity=self.identity,
                    mode=self.mode_name,
                    batch_id=self.batch_id,
                )
            except PairIdentityError:
                self.__exit__(None, None, None)
                raise
            self._state = state
        else:
            if self._read_only:
                self.__exit__(None, None, None)
                raise PairIdentityError("read-only pair sequence ledger is unavailable")
            self._state = {
                "schema_version": 5,
                "pair_id": self.identity.pair_id,
                "pair_lock_sha256": self.identity.lock_sha256,
                "mode": self.mode_name,
                "batch_id": self.batch_id,
                "eval_harness_commit": None,
                "selected_profile_sha256": None,
                "selected_endpoint_sha256": None,
                "next_slot": 1,
                "blocked": False,
                "runs": [],
            }
            try:
                self._persist()
            except PairIdentityError:
                self.__exit__(None, None, None)
                raise
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        handle = self._handle
        self._handle = None
        self._state = None
        if handle is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def claim(
        self,
        *,
        side: Side,
        run_id: str,
        eval_harness_commit: str,
        provider: ProviderProjection,
    ) -> PairSlot:
        state = self._require_state()
        self._require_writable()
        active = [item for item in state["runs"] if item["status"] == "active"]
        if active:
            if len(active) != 1:
                raise PairIdentityError("pair sequence active state is ambiguous")
            raise PairIdentityError("pair sequence active slot requires reconciliation")
        if state["blocked"]:
            raise PairIdentityError("pair sequence is blocked by an earlier failed slot")
        _require_commit(eval_harness_commit, "eval harness commit")
        bound_commit = state["eval_harness_commit"]
        if bound_commit is None:
            state["eval_harness_commit"] = eval_harness_commit
        elif bound_commit != eval_harness_commit:
            raise PairIdentityError("pair slots require the same eval harness commit")
        slot = self.identity.slot_for(side)
        if slot.slot != state["next_slot"]:
            raise PairIdentityError("pair run attempted out of tracked slot order")
        if not run_id or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in run_id
        ):
            raise PairIdentityError("pair sequence run id is invalid")
        if slot.paid_run_id != run_id:
            raise PairIdentityError("paid run id differs from the tracked pair slot")
        if any(item["run_id"] == run_id for item in state["runs"]):
            raise PairIdentityError("pair sequence run id was already claimed")
        selected = self._bind_or_validate_provider(provider)
        state["runs"].append(
            {
                "slot": slot.slot,
                "side": side.value,
                "round": slot.round,
                "run_id": run_id,
                "status": "active",
                "eval_harness_commit": eval_harness_commit,
                "selected_profile_sha256": selected.profile_sha256,
                "selected_endpoint_sha256": selected.endpoint_sha256,
                "publication_sha256": None,
                "container_metrics": None,
            }
        )
        self._persist()
        return slot

    def finish(
        self,
        *,
        run_id: str,
        completed: bool,
        eval_harness_commit: str,
        publication_sha256: str | None = None,
        container_metrics: Mapping[str, object] | None = None,
        provider: ProviderProjection,
    ) -> None:
        state = self._require_state()
        self._require_writable()
        self._bind_or_validate_provider(provider)
        matches = [item for item in state["runs"] if item["run_id"] == run_id]
        if len(matches) != 1 or matches[0]["status"] not in {"active", "publishing"}:
            raise PairIdentityError("pair sequence active run is unavailable")
        _require_commit(eval_harness_commit, "eval harness commit")
        if (
            state["eval_harness_commit"] != eval_harness_commit
            or matches[0]["eval_harness_commit"] != eval_harness_commit
        ):
            raise PairIdentityError("pair finish harness identity differs from claim")
        if publication_sha256 is not None:
            _require_sha256(publication_sha256, "publication sha256")
        normalized_metrics = _container_metrics(container_metrics)
        if completed and (
            publication_sha256 is None or normalized_metrics is None
        ):
            raise PairIdentityError("completed paid slot lacks publication or container metrics")
        matches[0]["publication_sha256"] = publication_sha256
        matches[0]["container_metrics"] = normalized_metrics
        matches[0]["status"] = "completed" if completed else "failed"
        if completed:
            state["next_slot"] = matches[0]["slot"] + 1
        else:
            state["blocked"] = True
        self._persist()

    def stage_paid_publication(
        self,
        *,
        run_id: str,
        eval_harness_commit: str,
        container_metrics: Mapping[str, object],
        provider: ProviderProjection,
    ) -> None:
        """Durably retain metrics before the external result transaction begins."""

        state = self._require_state()
        self._require_writable()
        self._bind_or_validate_provider(provider)
        matches = [item for item in state["runs"] if item["run_id"] == run_id]
        if len(matches) != 1 or matches[0]["status"] != "active":
            raise PairIdentityError("pair sequence active run is unavailable")
        _require_commit(eval_harness_commit, "eval harness commit")
        if matches[0]["eval_harness_commit"] != eval_harness_commit:
            raise PairIdentityError("publication staging harness differs from claim")
        metrics = _container_metrics(container_metrics)
        if metrics is None:
            raise PairIdentityError("publication staging lacks container metrics")
        matches[0]["container_metrics"] = metrics
        matches[0]["status"] = "publishing"
        self._persist()

    def reconcile_paid_publication(
        self,
        *,
        run_id: str,
        eval_harness_commit: str,
        index_path: Path,
        provider: ProviderProjection,
    ) -> str:
        """Converge a staged slot after ArtifactWriter made its record durable."""

        state = self._require_state()
        self._require_writable()
        selected = self._bind_or_validate_provider(provider)
        matches = [item for item in state["runs"] if item["run_id"] == run_id]
        if len(matches) != 1 or matches[0]["status"] != "publishing":
            raise PairIdentityError("pair sequence publishing run is unavailable")
        record = _published_terminal_record(index_path, run_id=run_id)
        config = record.get("config")
        run = matches[0]
        published_profile = (
            {key: config.get(key) for key in _SELECTED_PROFILE_KEYS}
            if isinstance(config, Mapping)
            else None
        )
        if (
            record.get("outcome") != RunOutcome.COMPLETED.value
            or record.get("side") != run["side"]
            or not isinstance(config, Mapping)
            or config.get("pair_id") != self.identity.pair_id
            or config.get("pair_lock_sha256") != self.identity.lock_sha256
            or config.get("pair_slot") != run["slot"]
            or config.get("pair_round") != run["round"]
            or config.get("eval_harness_commit") != eval_harness_commit
            or config.get("provider_profile_sha256") != selected.profile_sha256
            or config.get("provider_endpoint_sha256") != selected.endpoint_sha256
            or published_profile != selected.to_dict()
        ):
            raise PairIdentityError("durable publication differs from the staged pair slot")
        digest = terminal_record_sha256(record)
        self.finish(
            run_id=run_id,
            completed=True,
            eval_harness_commit=eval_harness_commit,
            publication_sha256=digest,
            container_metrics=matches[0]["container_metrics"],
            provider=provider,
        )
        return digest

    def snapshot(self) -> dict[str, Any]:
        """Return a detached validated snapshot while holding the stable lock."""

        state = self._require_state()
        return json.loads(json.dumps(state, sort_keys=True, separators=(",", ":")))

    def _require_state(self) -> dict[str, Any]:
        if self._handle is None or self._state is None:
            raise PairIdentityError("pair sequence ledger is not locked")
        return self._state

    def _require_writable(self) -> None:
        if self._read_only:
            raise PairIdentityError("pair sequence ledger is read-only")

    def _bind_or_validate_provider(
        self, provider: ProviderProjection
    ) -> SelectedProfileIdentity:
        state = self._require_state()
        selected = self.identity.require_selected_profile()
        selected.validate_provider(provider)
        bound_profile = state["selected_profile_sha256"]
        bound_endpoint = state["selected_endpoint_sha256"]
        if bound_profile is None and bound_endpoint is None:
            if state["runs"]:
                raise PairIdentityError("pair profile binding is absent after slot claim")
            state["selected_profile_sha256"] = selected.profile_sha256
            state["selected_endpoint_sha256"] = selected.endpoint_sha256
        elif (
            bound_profile != selected.profile_sha256
            or bound_endpoint != selected.endpoint_sha256
        ):
            raise PairIdentityError("pair slots require the same selected provider profile")
        return selected

    def _persist(self) -> None:
        state = self._require_state()
        encoded = (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode()
        _atomic_replace_bytes(self.path, encoded, hook=self._persist_hook)


@dataclass(frozen=True)
class PairMode:
    enabled: bool
    batch_id: str | None
    disabled_reason: str | None = None


@dataclass(frozen=True)
class PairSlot:
    slot: int
    side: Side
    round: int
    paid_run_id: str | None


@dataclass(frozen=True)
class BundleIdentity:
    manifest_path: str
    manifest_sha256: str
    cli_sha256: str
    cli_size: int
    code_mode_host_sha256: str
    code_mode_host_size: int
    bwrap_sha256: str
    bwrap_size: int
    source_commit: str
    workspace_lock_normalization: str | None


@dataclass(frozen=True)
class HarborIdentity:
    package: str
    version: str
    release_commit: str
    wheel_sha256: str
    uv_lock_sha256: str
    console_script_normalized_sha256: str
    console_script_normalization: str
    key_files: Mapping[str, str]


@dataclass(frozen=True)
class NoApiSeccompIdentity:
    profile_path: str
    source_sha256: str
    effective_sha256: str


@dataclass(frozen=True)
class RuntimeRequirements:
    paid_custom_seccomp_required: bool
    m1_pair_ledger_required: bool
    m1_container_metrics_required: bool


@dataclass(frozen=True)
class PaidBudgetIdentity:
    per_side_usd: float
    pair_usd: float


@dataclass(frozen=True)
class SelectedProfileIdentity:
    provider_public: Mapping[str, object]
    frozen_codex_model_catalog_source_commit: str
    frozen_codex_model_catalog_sha256: str
    max_guardian_logical_requests: int

    def to_dict(self) -> dict[str, object]:
        return {
            **dict(self.provider_public),
            "frozen_codex_model_catalog_source_commit": (
                self.frozen_codex_model_catalog_source_commit
            ),
            "frozen_codex_model_catalog_sha256": (
                self.frozen_codex_model_catalog_sha256
            ),
            "max_guardian_logical_requests": self.max_guardian_logical_requests,
        }

    @property
    def profile_sha256(self) -> str:
        return str(self.provider_public["provider_profile_sha256"])

    @property
    def endpoint_sha256(self) -> str:
        return str(self.provider_public["provider_endpoint_sha256"])

    def validate_provider(self, provider: ProviderProjection) -> None:
        try:
            actual = provider.to_public_dict()
        except ValueError as exc:
            raise PairIdentityError("selected paid provider profile is invalid") from exc
        if actual != dict(self.provider_public):
            raise PairIdentityError("selected paid provider profile drifted from the pair lock")


@dataclass(frozen=True)
class PairIdentity:
    schema_version: int
    pair_id: str
    modes: Mapping[str, PairMode]
    topology: tuple[PairSlot, ...]
    fairness: Mapping[str, object]
    harbor: HarborIdentity
    no_api_seccomp: NoApiSeccompIdentity
    runtime_requirements: RuntimeRequirements
    bundles: Mapping[Side, BundleIdentity]
    lock_sha256: str
    selected_profile: SelectedProfileIdentity | None = None
    paid_budget: PaidBudgetIdentity | None = None

    def mode(self, name: str) -> PairMode:
        mode = self.modes.get(name)
        if mode is None:
            raise PairIdentityError("pair execution mode is unknown")
        if not mode.enabled:
            raise PairIdentityError(mode.disabled_reason or "pair execution mode is disabled")
        if not mode.batch_id:
            raise PairIdentityError("enabled pair execution mode lacks a batch id")
        return mode

    def slot_for(self, side: Side) -> PairSlot:
        matches = [slot for slot in self.topology if slot.side is side]
        if len(matches) != 1:
            raise PairIdentityError("pair topology does not contain exactly one slot per side")
        return matches[0]

    def require_selected_profile(self) -> SelectedProfileIdentity:
        if self.schema_version != 2 or self.selected_profile is None:
            raise PairIdentityError("legacy pair identity cannot be used for a new paid run")
        return self.selected_profile

    def validate_selected_profile(self, provider: ProviderProjection) -> None:
        self.require_selected_profile().validate_provider(provider)

    def validate_frozen_model_catalog(
        self,
        *,
        source_commit: str,
        sha256: str,
        main_model: str,
        guardian_model: str,
    ) -> None:
        selected = self.require_selected_profile()
        public = selected.provider_public
        if (
            source_commit != selected.frozen_codex_model_catalog_source_commit
            or sha256 != selected.frozen_codex_model_catalog_sha256
            or main_model != public["effective_main_model"]
            or guardian_model != public["effective_guardian_model"]
        ):
            raise PairIdentityError("frozen model catalog drifted from the pair lock")

    def validate_manifest(
        self,
        *,
        common_root: Path,
        side: Side,
        manifest_path: Path,
        manifest: BinaryManifest,
    ) -> None:
        expected = self.bundles[side]
        try:
            actual_path = manifest_path.resolve(strict=True)
            expected_path = (common_root / expected.manifest_path).resolve(strict=True)
        except OSError as exc:
            raise PairIdentityError("pair bundle manifest is unavailable") from exc
        if actual_path != expected_path:
            raise PairIdentityError("binary manifest path differs from the tracked pair")
        if _file_sha256(actual_path) != expected.manifest_sha256:
            raise PairIdentityError("binary manifest bytes differ from the tracked pair")
        actual = (
            manifest.sha256,
            manifest.code_mode_host_sha256,
            manifest.bwrap_sha256,
            manifest.source_commit,
            manifest.workspace_lock_normalization,
        )
        frozen = (
            expected.cli_sha256,
            expected.code_mode_host_sha256,
            expected.bwrap_sha256,
            expected.source_commit,
            expected.workspace_lock_normalization,
        )
        if actual != frozen:
            raise PairIdentityError("binary manifest identity differs from the tracked pair")
        bundle_root = expected_path.parent
        for relative, digest, size in (
            ("codex", expected.cli_sha256, expected.cli_size),
            (
                "codex-code-mode-host",
                expected.code_mode_host_sha256,
                expected.code_mode_host_size,
            ),
            ("codex-resources/bwrap", expected.bwrap_sha256, expected.bwrap_size),
        ):
            _validate_bundle_file(bundle_root / relative, digest=digest, size=size)

    def validate_spec(self, spec: RunSpec, *, mode: str) -> PairSlot:
        if mode == "paid":
            batch_id = self.mode("paid").batch_id
        elif mode == "no_api":
            batch_id = B2_NO_API_BATCH_ID
        else:
            raise PairIdentityError("pair execution mode is unknown")
        slot = self.slot_for(spec.side)
        if spec.batch_id != batch_id:
            raise PairIdentityError("RunSpec batch differs from the tracked pair mode")
        core_actual = {
            "task_id": spec.task_id,
            "task_image_digest": spec.task_image_digest,
            "terminal_bench_version": spec.terminal_bench_version,
            "approvals_reviewer": spec.approvals_reviewer,
            "approval_policy": spec.approval_policy,
            "sandbox_mode": spec.sandbox_mode,
            "sandbox_network_access": spec.sandbox_network_access,
            "websocket": spec.websocket,
            "code_mode_host": spec.code_mode_host,
            "timeout_seconds": spec.timeout_seconds,
            "max_retries": spec.max_retries,
            "budget_usd": spec.budget_usd,
        }
        if self.schema_version == 1:
            actual = {
                **core_actual,
                "provider_id": spec.provider.provider_id,
                "provider_api": spec.provider.api,
                "provider_api_key_env": spec.provider.api_key_env,
                "main_model": spec.provider.main_model,
                "guardian_model": spec.provider.guardian_model,
                "guardian_effort": spec.provider.guardian_effort,
            }
        else:
            actual = core_actual
        if actual != dict(self.fairness):
            raise PairIdentityError("RunSpec fairness fields differ from the tracked pair")
        if mode == "paid":
            self.validate_selected_profile(spec.provider)
            paid_budget = self.paid_budget
            if (
                paid_budget is None
                or spec.budget_usd != paid_budget.per_side_usd
                or paid_budget.pair_usd != paid_budget.per_side_usd * 2
            ):
                raise PairIdentityError("paid run budget differs from the tracked pair")
        counterpart = replace(
            spec,
            side=Side.RONDO if spec.side is Side.CODEX else Side.CODEX,
        )
        try:
            assert_fair_pair(spec, counterpart)
        except ValueError as exc:
            raise PairIdentityError("RunSpec fails the shared fair-pair contract") from exc
        if mode == "paid" and slot.paid_run_id is None:
            raise PairIdentityError("enabled paid pair lacks exact run ids")
        return slot

    def validate_prepared(
        self, prepared: PreparedTerminalBenchRun, *, mode: str
    ) -> PairSlot:
        prepared.validate()
        slot = self.validate_spec(prepared.spec, mode=mode)
        container = prepared.command.compose_contract.container
        if container.require_container_metrics is not True:
            raise PairIdentityError("pair container metrics are not enforced")
        if mode in {"no_api", "paid"}:
            materialized = prepared.materialized_task
            expected = self.no_api_seccomp
            if (
                materialized.seccomp_profile is None
                or materialized.seccomp_profile.as_posix()
                != str((Path(__file__).resolve().parents[3] / expected.profile_path).resolve())
                or materialized.seccomp_profile_source_sha256 != expected.source_sha256
                or materialized.seccomp_profile_effective_sha256 != expected.effective_sha256
                or container.seccomp_profile_sha256 != expected.effective_sha256
            ):
                raise PairIdentityError("custom seccomp projection differs from the pair lock")
        return slot

    def validate_no_api_seccomp(self, *, project_root: Path) -> Path:
        expected = self.no_api_seccomp
        try:
            root = project_root.resolve(strict=True)
            profile = (root / expected.profile_path).resolve(strict=True)
            metadata = profile.lstat()
        except OSError as exc:
            raise PairIdentityError("tracked no-API seccomp profile is unavailable") from exc
        if (
            profile != root / expected.profile_path
            or profile.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or _file_sha256(profile) != expected.source_sha256
        ):
            raise PairIdentityError("tracked no-API seccomp profile identity differs")
        try:
            from .namespace_diagnostic import (
                _EFFECTIVE_PROFILE_SHA256,
                _require_clean_tracked_file,
                _validate_frozen_profile,
            )

            _require_clean_tracked_file(root, profile)
            _validate_frozen_profile(profile.read_bytes())
        except Exception as exc:
            raise PairIdentityError("no-API seccomp profile is not clean and frozen") from exc
        if expected.effective_sha256 != _EFFECTIVE_PROFILE_SHA256:
            raise PairIdentityError("no-API effective seccomp identity differs")
        return profile

    def validate_runtime_seccomp(self, *, project_root: Path) -> Path:
        """Return the one tracked profile shared by no-API and future paid runs."""

        return self.validate_no_api_seccomp(project_root=project_root)


@dataclass(frozen=True)
class RunPublicationContext:
    pair_id: str
    pair_lock_sha256: str
    pair_slot: int
    pair_round: int
    metrics: Mapping[str, object]
    selected_profile: Mapping[str, object]

    def validate(self) -> None:
        if self.pair_id != P1_PAIR_ID:
            raise PairIdentityError("publication pair id is invalid")
        _require_sha256(self.pair_lock_sha256, "pair lock sha256")
        if self.pair_slot not in {1, 2} or self.pair_round != 1:
            raise PairIdentityError("publication pair topology is invalid")
        try:
            metrics_from_dict(self.metrics)
        except RunMetricsError as exc:
            raise PairIdentityError("publication metrics are invalid") from exc
        _parse_selected_profile(self.selected_profile)


def load_pair_identity(path: Path = PAIR_LOCK_PATH) -> PairIdentity:
    """Load only the active schema-v2 paid identity."""

    return _load_pair_identity(path, schema_version=2, pair_id=P1_PAIR_ID)


def load_legacy_pair_identity(path: Path = LEGACY_PAIR_LOCK_PATH) -> PairIdentity:
    """Load the consumed v8 identity for read-only historical assessment."""

    return _load_pair_identity(path, schema_version=1, pair_id=LEGACY_P1_PAIR_ID)


def load_previous_pair_identity(path: Path = PREVIOUS_PAIR_LOCK_PATH) -> PairIdentity:
    """Load the Guardian-failed v13 identity for read-only historical assessment."""

    return _load_pair_identity(path, schema_version=2, pair_id=PREVIOUS_P1_PAIR_ID)


def load_consumed_v12_pair_identity(
    path: Path = CONSUMED_V12_PAIR_LOCK_PATH,
) -> PairIdentity:
    """Load the canary-failed v12 identity for read-only historical assessment."""

    return _load_pair_identity(path, schema_version=2, pair_id=CONSUMED_V12_P1_PAIR_ID)


def load_consumed_v11_pair_identity(
    path: Path = CONSUMED_V11_PAIR_LOCK_PATH,
) -> PairIdentity:
    """Load the preflight-failed v11 identity for read-only historical assessment."""

    return _load_pair_identity(path, schema_version=2, pair_id=CONSUMED_V11_P1_PAIR_ID)


def load_consumed_v10_pair_identity(
    path: Path = CONSUMED_V10_PAIR_LOCK_PATH,
) -> PairIdentity:
    """Load the consumed v10 identity for read-only historical assessment."""

    return _load_pair_identity(path, schema_version=2, pair_id=CONSUMED_V10_P1_PAIR_ID)


def load_consumed_v9_pair_identity(
    path: Path = CONSUMED_V9_PAIR_LOCK_PATH,
) -> PairIdentity:
    """Load the consumed v9 identity for read-only historical assessment."""

    return _load_pair_identity(path, schema_version=2, pair_id=CONSUMED_V9_P1_PAIR_ID)


def _load_pair_identity(
    path: Path,
    *,
    schema_version: int,
    pair_id: str,
) -> PairIdentity:
    try:
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            raise PairIdentityError("pair lock must be a regular non-symlink file")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except PairIdentityError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PairIdentityError("pair lock is unreadable") from exc
    expected_keys = _PAIR_LOCK_V2_KEYS if schema_version == 2 else _PAIR_LOCK_V1_KEYS
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise PairIdentityError(f"pair lock differs from schema v{schema_version}")
    if value["schema_version"] != schema_version or value["pair_id"] != pair_id:
        raise PairIdentityError("pair lock identity differs from P1")
    modes = _parse_modes(value["modes"])
    topology = _parse_topology(value["topology"], modes=modes)
    fairness = _parse_fairness(
        value["fairness"],
        schema_version=schema_version,
        pair_id=pair_id,
    )
    harbor = _parse_harbor(value["harbor"])
    no_api_seccomp = _parse_no_api_seccomp(value["no_api_seccomp"])
    runtime_requirements = _parse_runtime_requirements(value["runtime_requirements"])
    bundles = _parse_bundles(value["bundles"])
    selected_profile = (
        _parse_selected_profile(value["selected_profile"])
        if schema_version == 2
        else None
    )
    paid_budget = (
        _parse_paid_budget(value["paid_budget"], pair_id=pair_id)
        if schema_version == 2
        else None
    )
    if (
        selected_profile is not None
        and selected_profile.frozen_codex_model_catalog_source_commit
        != bundles[Side.CODEX].source_commit
    ):
        raise PairIdentityError("frozen model catalog source differs from the Codex bundle")
    identity = PairIdentity(
        schema_version=schema_version,
        pair_id=value["pair_id"],
        modes=modes,
        topology=topology,
        fairness=fairness,
        harbor=harbor,
        no_api_seccomp=no_api_seccomp,
        runtime_requirements=runtime_requirements,
        bundles=bundles,
        lock_sha256=hashlib.sha256(raw).hexdigest(),
        selected_profile=selected_profile,
        paid_budget=paid_budget,
    )
    # Exercise the existing two-sided contract with synthetic specs only in
    # aggregation; runtime validation below compares every shared field.
    if tuple(slot.side for slot in topology) != (Side.RONDO, Side.CODEX):
        raise PairIdentityError("pair topology order must be RONDO then Codex")
    return identity


def validate_harbor_installation(
    identity: PairIdentity,
    *,
    executable: Path,
    distribution: importlib.metadata.Distribution | None = None,
    python_executable: Path | None = None,
) -> None:
    """Bind Harbor to the tracked lock, entry point, and key modules."""

    expected = identity.harbor
    if (
        expected.package != HARBOR_PACKAGE
        or expected.version != HARBOR_VERSION
        or expected.release_commit != HARBOR_RELEASE_COMMIT
        or expected.wheel_sha256 != HARBOR_WHEEL_SHA256
    ):
        raise PairIdentityError("tracked Harbor identity differs from the B1 freeze")
    try:
        dist = distribution or importlib.metadata.distribution(HARBOR_PACKAGE)
    except importlib.metadata.PackageNotFoundError as exc:
        raise PairIdentityError("frozen Harbor distribution is not installed") from exc
    if dist.version != expected.version:
        raise PairIdentityError("installed Harbor version differs from the pair lock")
    uv_lock = PAIR_LOCK_PATH.parents[1] / "uv.lock"
    if _file_sha256(uv_lock) != expected.uv_lock_sha256:
        raise PairIdentityError("eval uv.lock differs from the pair lock")
    for relative, digest in expected.key_files.items():
        path = Path(dist.locate_file(relative))
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise PairIdentityError("installed Harbor key file is unavailable") from exc
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or _file_sha256(path) != digest:
            raise PairIdentityError("installed Harbor key file differs from the pair lock")
    _validate_console_script(
        executable,
        python_executable=python_executable or Path(sys.executable),
        expected_normalized_sha256=expected.console_script_normalized_sha256,
        normalization=expected.console_script_normalization,
    )


def publication_context(
    identity: PairIdentity,
    *,
    side: Side,
    metrics: Mapping[str, object],
) -> RunPublicationContext:
    slot = identity.slot_for(side)
    context = RunPublicationContext(
        pair_id=identity.pair_id,
        pair_lock_sha256=identity.lock_sha256,
        pair_slot=slot.slot,
        pair_round=slot.round,
        metrics=dict(metrics),
        selected_profile=identity.require_selected_profile().to_dict(),
    )
    context.validate()
    return context


def assess_m1(
    records: Iterable[Mapping[str, Any]],
    identity: PairIdentity,
    *,
    pair_ledger_path: Path,
) -> dict[str, object]:
    """Evaluate M1 only when records and the durable paid ledger agree."""

    candidates = [
        record
        for record in records
        if isinstance(record.get("config"), dict)
        and record["config"].get("pair_id") == identity.pair_id
        and record["config"].get("pair_lock_sha256") == identity.lock_sha256
    ]
    result: dict[str, object] = {
        "schema_version": 1,
        "pair_id": identity.pair_id,
        "m1": "incomplete",
        "s2": "not_triggered",
        "reasons": [],
    }
    if len(candidates) != 2:
        result["reasons"] = ["pair_requires_exactly_two_records"]
        return result
    ordered = sorted(
        candidates,
        key=lambda item: (
            item.get("config", {}).get("pair_slot", 99)
            if isinstance(item.get("config"), Mapping)
            else 99
        ),
    )
    reasons: list[str] = []
    try:
        identity.mode("paid")
    except PairIdentityError:
        reasons.append("paid_pair_disabled")
        ledger: Mapping[str, Any] | None = None
    else:
        try:
            if not pair_ledger_path.exists() or pair_ledger_path.is_symlink():
                raise PairIdentityError("paid pair ledger is unavailable")
            with PairSequenceLedger(
                pair_ledger_path,
                identity=identity,
                mode="paid",
                read_only=True,
            ) as sequence:
                ledger = sequence.snapshot()
        except PairIdentityError:
            ledger = None
            reasons.append("paid_pair_ledger_invalid")
    ledger_runs: dict[int, Mapping[str, Any]] = {}
    if ledger is not None:
        raw_runs = ledger.get("runs")
        if (
            ledger.get("next_slot") != 3
            or ledger.get("blocked") is not False
            or not isinstance(raw_runs, list)
            or len(raw_runs) != 2
        ):
            reasons.append("paid_pair_ledger_not_completed")
        else:
            ledger_runs = {
                item["slot"]: item
                for item in raw_runs
                if isinstance(item, Mapping) and isinstance(item.get("slot"), int)
            }
    for record, slot in zip(ordered, identity.topology, strict=True):
        config = record.get("config")
        if not isinstance(config, dict) or (
            record.get("side") != slot.side.value
            or config.get("pair_slot") != slot.slot
            or config.get("pair_round") != slot.round
        ):
            reasons.append("pair_topology_mismatch")
            continue
        if (
            record.get("outcome") != RunOutcome.COMPLETED.value
            or record.get("git_dirty") is not False
            or record.get("artifacts") in {None, ""}
        ):
            reasons.append(f"{slot.side.value}_not_completed")
        try:
            metrics_from_dict(record.get("metrics"))
        except RunMetricsError:
            reasons.append(f"{slot.side.value}_metrics_invalid")
        summary = record.get("summary")
        roles = summary.get("api_request_roles") if isinstance(summary, dict) else None
        sequence = (
            summary.get("api_request_sequence") if isinstance(summary, dict) else None
        )
        if (
            not isinstance(summary, dict)
            or summary.get("metadata_ready") is not True
            or not isinstance(roles, dict)
            or set(roles) != {"main", "guardian"}
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for value in roles.values()
            )
            or roles.get("main") != (
                sequence.count("main") if isinstance(sequence, list) else -1
            )
            or roles.get("guardian") != (
                sequence.count("guardian") if isinstance(sequence, list) else -1
            )
            or not has_complete_guardian_approval_sequence(sequence)
        ):
            reasons.append(f"{slot.side.value}_guardian_approval_incomplete")
        ledger_run = ledger_runs.get(slot.slot)
        eval_commit = config.get("eval_harness_commit") if isinstance(config, dict) else None
        if (
            not isinstance(ledger_run, Mapping)
            or ledger_run.get("status") != "completed"
            or ledger_run.get("run_id") != record.get("run_id")
            or ledger_run.get("side") != slot.side.value
            or ledger_run.get("eval_harness_commit") != eval_commit
            or ledger_run.get("publication_sha256") != terminal_record_sha256(record)
        ):
            reasons.append(f"{slot.side.value}_pair_ledger_mismatch")
        try:
            if not isinstance(ledger_run, Mapping):
                raise PairIdentityError("ledger run is absent")
            _container_metrics(ledger_run.get("container_metrics"))
            if ledger_run.get("container_metrics") is None:
                raise PairIdentityError("container metrics are absent")
        except PairIdentityError:
            reasons.append(f"{slot.side.value}_container_metrics_missing")
    _compare_record_fairness(ordered, identity, reasons)
    rondo = next((item for item in candidates if item.get("side") == Side.RONDO.value), None)
    if isinstance(rondo, Mapping):
        summary = rondo.get("summary")
        roles = summary.get("api_request_roles") if isinstance(summary, Mapping) else None
        guardian = roles.get("guardian", 0) if isinstance(roles, Mapping) else 0
        evidence = summary.get("evidence") if isinstance(summary, Mapping) else None
        if guardian or evidence:
            result["s2"] = (
                "verified"
                if summary.get("s2_request_evidence_binding") == "verified"
                else "unbound"
            )
    result["reasons"] = sorted(set(reasons))
    result["m1"] = "passed" if not reasons else "failed"
    return result


def has_complete_guardian_approval_sequence(sequence: object) -> bool:
    """Accept one approval bracketed by one or more ordinary model turns."""

    if not isinstance(sequence, (list, tuple)) or len(sequence) < 3:
        return False
    if any(role not in {"main", "guardian"} for role in sequence):
        return False
    if sequence.count("guardian") != 1:
        return False
    guardian_index = sequence.index("guardian")
    return guardian_index > 0 and guardian_index < len(sequence) - 1


def terminal_record_sha256(record: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            dict(record),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PairIdentityError("Terminal-Bench record is not canonical JSON") from exc
    return hashlib.sha256(encoded).hexdigest()


def published_terminal_record_sha256(index_path: Path, *, run_id: str) -> str:
    """Read back one durable publication before completing its pair slot."""

    return terminal_record_sha256(_published_terminal_record(index_path, run_id=run_id))


def _published_terminal_record(index_path: Path, *, run_id: str) -> dict[str, Any]:

    try:
        metadata = index_path.lstat()
        if index_path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise PairIdentityError("Terminal-Bench result index is unsafe")
        if metadata.st_size > 64 * 1024 * 1024:
            raise PairIdentityError("Terminal-Bench result index is oversized")
        records = [json.loads(line) for line in index_path.read_text().splitlines() if line]
    except PairIdentityError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PairIdentityError("Terminal-Bench result index is unreadable") from exc
    matches = [
        record
        for record in records
        if isinstance(record, dict) and record.get("run_id") == run_id
    ]
    if len(matches) != 1:
        raise PairIdentityError("Terminal-Bench publication is not uniquely durable")
    return matches[0]


def _parse_modes(value: object) -> dict[str, PairMode]:
    if not isinstance(value, dict) or set(value) != {"paid"}:
        raise PairIdentityError("pair modes differ from schema v1")
    result: dict[str, PairMode] = {}
    for name, raw in value.items():
        if not isinstance(raw, dict) or set(raw) != _PAID_MODE_KEYS:
            raise PairIdentityError("pair mode differs from schema v1")
        enabled = raw["enabled"]
        batch_id = raw["batch_id"]
        reason = raw.get("disabled_reason")
        if not isinstance(enabled, bool) or (
            batch_id is not None and (not isinstance(batch_id, str) or not batch_id)
        ):
            raise PairIdentityError("pair mode values are invalid")
        if enabled != (batch_id is not None):
            raise PairIdentityError("pair mode enabled state and batch id disagree")
        if not enabled and (not isinstance(reason, str) or not reason):
            raise PairIdentityError("disabled paid mode requires a reason")
        result[name] = PairMode(enabled, batch_id, reason)
    return result


def _validate_sequence_state(
    value: object,
    *,
    identity: PairIdentity,
    mode: str,
    batch_id: str,
) -> None:
    expected_keys = {
        "schema_version",
        "pair_id",
        "pair_lock_sha256",
        "mode",
        "batch_id",
        "eval_harness_commit",
        "next_slot",
        "blocked",
        "runs",
    }
    if identity.schema_version == 2:
        expected_keys |= {
            "selected_profile_sha256",
            "selected_endpoint_sha256",
        }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise PairIdentityError("pair sequence ledger differs from its pair schema")
    expected_schema = 5 if identity.schema_version == 2 else 4
    if (
        value["schema_version"] != expected_schema
        or value["pair_id"] != identity.pair_id
        or value["pair_lock_sha256"] != identity.lock_sha256
        or value["mode"] != mode
        or value["batch_id"] != batch_id
        or value["next_slot"] not in {1, 2, 3}
        or not isinstance(value["blocked"], bool)
        or not isinstance(value["runs"], list)
        or len(value["runs"]) > 2
    ):
        raise PairIdentityError("pair sequence ledger identity is invalid")
    selected = identity.selected_profile
    if identity.schema_version == 2:
        profile_hash = value["selected_profile_sha256"]
        endpoint_hash = value["selected_endpoint_sha256"]
        if not value["runs"]:
            if profile_hash is not None or endpoint_hash is not None:
                raise PairIdentityError("unclaimed pair sequence already binds a profile")
        elif (
            selected is None
            or profile_hash != selected.profile_sha256
            or endpoint_hash != selected.endpoint_sha256
        ):
            raise PairIdentityError("pair sequence selected profile binding is invalid")
    harness_commit = value["eval_harness_commit"]
    if harness_commit is not None:
        _require_commit(harness_commit, "pair sequence eval harness commit")
    if bool(value["runs"]) != (harness_commit is not None):
        raise PairIdentityError("pair sequence harness binding is inconsistent")
    statuses: list[str] = []
    for index, item in enumerate(value["runs"], start=1):
        run_keys = {
            "slot",
            "side",
            "round",
            "run_id",
            "status",
            "eval_harness_commit",
            "publication_sha256",
            "container_metrics",
        }
        if identity.schema_version == 2:
            run_keys |= {
                "selected_profile_sha256",
                "selected_endpoint_sha256",
            }
        if not isinstance(item, dict) or set(item) != run_keys:
            raise PairIdentityError("pair sequence run differs from its pair schema")
        slot = identity.topology[index - 1]
        if (
            item["slot"] != slot.slot
            or item["side"] != slot.side.value
            or item["round"] != slot.round
            or not isinstance(item["run_id"], str)
            or not item["run_id"]
            or item["status"] not in {"active", "publishing", "completed", "failed"}
            or item["run_id"] != slot.paid_run_id
            or item["eval_harness_commit"] != harness_commit
        ):
            raise PairIdentityError("pair sequence run is invalid")
        if identity.schema_version == 2 and (
            selected is None
            or item["selected_profile_sha256"] != selected.profile_sha256
            or item["selected_endpoint_sha256"] != selected.endpoint_sha256
        ):
            raise PairIdentityError("pair sequence run profile binding is invalid")
        if item["publication_sha256"] is not None:
            _require_sha256(item["publication_sha256"], "pair publication sha256")
        metrics = _container_metrics(item["container_metrics"])
        if metrics != item["container_metrics"]:
            raise PairIdentityError("pair sequence container metrics are not canonical")
        if item["status"] == "completed" and (
            item["publication_sha256"] is None or metrics is None
        ):
            raise PairIdentityError("completed paid sequence lacks publication evidence")
        if item["status"] == "publishing" and metrics is None:
            raise PairIdentityError("pair publishing state lacks paid container metrics")
        statuses.append(item["status"])
    expected_next = 1 + sum(status == "completed" for status in statuses)
    if value["next_slot"] != expected_next:
        raise PairIdentityError("pair sequence next slot is inconsistent")
    in_progress = sum(status in {"active", "publishing"} for status in statuses)
    if in_progress > 1 or (
        in_progress == 1 and statuses[-1] not in {"active", "publishing"}
    ):
        raise PairIdentityError("pair sequence active state is inconsistent")
    failed = "failed" in statuses
    if value["blocked"] != failed or (failed and statuses[-1] != "failed"):
        raise PairIdentityError("pair sequence blocked state is inconsistent")


def _parse_topology(value: object, *, modes: Mapping[str, PairMode]) -> tuple[PairSlot, ...]:
    if not isinstance(value, list) or len(value) != 2:
        raise PairIdentityError("pair topology must have exactly two slots")
    slots: list[PairSlot] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _SLOT_KEYS:
            raise PairIdentityError("pair topology slot differs from schema v1")
        try:
            side = Side(raw["side"])
        except (TypeError, ValueError) as exc:
            raise PairIdentityError("pair topology side is invalid") from exc
        paid_run_id = raw["paid_run_id"]
        if (
            isinstance(raw["slot"], bool)
            or not isinstance(raw["slot"], int)
            or isinstance(raw["round"], bool)
            or not isinstance(raw["round"], int)
            or raw["round"] != 1
            or (paid_run_id is not None and (not isinstance(paid_run_id, str) or not paid_run_id))
        ):
            raise PairIdentityError("pair topology values are invalid")
        slots.append(PairSlot(raw["slot"], side, raw["round"], paid_run_id))
    if {slot.slot for slot in slots} != {1, 2} or {slot.side for slot in slots} != set(Side):
        raise PairIdentityError("pair topology must contain one slot per side")
    if modes["paid"].enabled and any(slot.paid_run_id is None for slot in slots):
        raise PairIdentityError("enabled paid mode requires exact run ids")
    if not modes["paid"].enabled and any(slot.paid_run_id is not None for slot in slots):
        raise PairIdentityError("disabled paid mode cannot reserve run ids")
    return tuple(sorted(slots, key=lambda slot: slot.slot))


def _parse_fairness(
    value: object,
    *,
    schema_version: int,
    pair_id: str,
) -> dict[str, object]:
    budget_usd = 10.0 if pair_id in _TEN_USD_PAIR_IDS else 5.0
    expected = {
        "task_id": FIX_GIT_TASK_ID,
        "task_image_digest": FIX_GIT_IMAGE_DIGEST,
        "terminal_bench_version": TERMINAL_BENCH_VERSION,
        "approvals_reviewer": "auto_review",
        "approval_policy": "on-request",
        "sandbox_mode": "workspace-write",
        "sandbox_network_access": True,
        "websocket": False,
        "code_mode_host": True,
        "timeout_seconds": 1800,
        "max_retries": 0,
        "budget_usd": budget_usd,
    }
    keys = _FAIRNESS_V2_KEYS
    if schema_version == 1:
        keys = _FAIRNESS_V1_KEYS
        expected |= {
            "provider_id": "openai",
            "provider_api": "responses",
            "provider_api_key_env": "OPENAI_API_KEY",
            "main_model": "gpt-5.6-sol",
            "guardian_model": "gpt-5.6-luna",
            "guardian_effort": "low",
        }
    if not isinstance(value, dict) or set(value) != keys:
        raise PairIdentityError(
            f"pair fairness fields differ from schema v{schema_version}"
        )
    if value != expected:
        raise PairIdentityError("pair fairness values differ from P1")
    return dict(value)


def _parse_paid_budget(value: object, *, pair_id: str) -> PaidBudgetIdentity:
    if not isinstance(value, dict) or set(value) != _PAID_BUDGET_KEYS:
        raise PairIdentityError("paid pair budget differs from schema v2")
    per_side = value["per_side_usd"]
    pair = value["pair_usd"]
    expected_per_side = 10.0 if pair_id in _TEN_USD_PAIR_IDS else 5.0
    expected_pair = expected_per_side * 2.0
    if (
        isinstance(per_side, bool)
        or not isinstance(per_side, (int, float))
        or isinstance(pair, bool)
        or not isinstance(pair, (int, float))
        or float(per_side) != expected_per_side
        or float(pair) != expected_pair
    ):
        raise PairIdentityError("paid pair budget differs from Plan 014")
    return PaidBudgetIdentity(float(per_side), float(pair))


def _parse_selected_profile(value: object) -> SelectedProfileIdentity:
    if not isinstance(value, dict) or set(value) != _SELECTED_PROFILE_KEYS:
        raise PairIdentityError("selected paid profile differs from schema v2")
    provider = value.get("provider")
    if (
        not isinstance(provider, str)
        or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", provider)
        or value.get("provider_api") != "responses"
    ):
        raise PairIdentityError("selected paid provider identity is invalid")
    for key in ("provider_profile_sha256", "provider_endpoint_sha256"):
        _require_sha256(value.get(key), key)
    for prefix in ("main", "guardian"):
        model = value.get(f"{prefix}_model")
        effort = value.get(f"{prefix}_effort")
        if (
            not isinstance(model, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", model)
            or effort not in {"none", "minimal", "low", "medium", "high", "xhigh"}
            or value.get(f"requested_{prefix}_model") != model
            or value.get(f"effective_{prefix}_model") != model
        ):
            raise PairIdentityError("selected paid model contract is invalid")
        pricing = _parse_public_pricing(value.get(f"{prefix}_pricing"))
        if pricing.model_id != model:
            raise PairIdentityError("selected paid model differs from its price card")
    attempts = value.get("provider_max_attempts")
    backoff = value.get("provider_retry_backoff_seconds")
    statuses = value.get("provider_unbilled_retry_statuses")
    if (
        isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or not 1 <= attempts <= 5
        or isinstance(backoff, bool)
        or not isinstance(backoff, (int, float))
        or not 0 <= float(backoff) <= 30
        or not isinstance(statuses, list)
        or any(
            isinstance(status, bool)
            or not isinstance(status, int)
            or not 400 <= status <= 599
            for status in statuses
        )
        or statuses != sorted(set(statuses))
        or (attempts > 1 and not statuses)
    ):
        raise PairIdentityError("selected paid retry contract is invalid")
    source_commit = value.get("frozen_codex_model_catalog_source_commit")
    catalog_sha256 = value.get("frozen_codex_model_catalog_sha256")
    _require_commit(source_commit, "frozen model catalog source commit")
    _require_sha256(catalog_sha256, "frozen model catalog sha256")
    if value.get("max_guardian_logical_requests") != 1:
        raise PairIdentityError("selected paid Guardian request limit is invalid")
    return SelectedProfileIdentity(
        provider_public={key: value[key] for key in _PUBLIC_PROVIDER_KEYS},
        frozen_codex_model_catalog_source_commit=source_commit,
        frozen_codex_model_catalog_sha256=catalog_sha256,
        max_guardian_logical_requests=1,
    )


def _parse_public_pricing(value: object) -> ModelPricing:
    expected_keys = {
        "model_id",
        "input_usd_per_million",
        "cached_input_usd_per_million",
        "output_usd_per_million",
        "long_context_threshold_tokens",
        "long_context_input_multiplier",
        "long_context_output_multiplier",
        "cache_write_input_multiplier",
        "price_snapshot_date",
        "price_source_url",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise PairIdentityError("selected paid price card differs from schema v2")
    try:
        pricing = ModelPricing(
            model_id=value["model_id"],
            input_usd_per_million=Decimal(value["input_usd_per_million"]),
            cached_input_usd_per_million=Decimal(value["cached_input_usd_per_million"]),
            output_usd_per_million=Decimal(value["output_usd_per_million"]),
            long_context_threshold_tokens=int(value["long_context_threshold_tokens"]),
            long_context_input_multiplier=Decimal(value["long_context_input_multiplier"]),
            long_context_output_multiplier=Decimal(value["long_context_output_multiplier"]),
            cache_write_input_multiplier=Decimal(value["cache_write_input_multiplier"]),
            price_snapshot_date=value["price_snapshot_date"],
            price_source_url=value["price_source_url"],
        )
        pricing.validate()
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PairIdentityError("selected paid price card is invalid") from exc
    if pricing.to_dict() != value:
        raise PairIdentityError("selected paid price card is not canonical")
    return pricing


def _parse_harbor(value: object) -> HarborIdentity:
    if not isinstance(value, dict) or set(value) != _HARBOR_KEYS:
        raise PairIdentityError("Harbor identity differs from schema v1")
    for key in (
        "wheel_sha256",
        "uv_lock_sha256",
        "console_script_normalized_sha256",
    ):
        _require_sha256(value[key], key)
    if (
        value["package"] != HARBOR_PACKAGE
        or value["version"] != HARBOR_VERSION
        or value["release_commit"] != HARBOR_RELEASE_COMMIT
        or value["wheel_sha256"] != HARBOR_WHEEL_SHA256
        or value["console_script_normalization"]
        != "absolute_shebang_to_#!<RONDO_EVAL_PYTHON>"
        or not isinstance(value["key_files"], dict)
        or set(value["key_files"]) != {
            "harbor/__init__.py",
            "harbor/cli/main.py",
            "harbor/agents/installed/base.py",
        }
    ):
        raise PairIdentityError("Harbor identity differs from the B1 freeze")
    for path, digest in value["key_files"].items():
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise PairIdentityError("Harbor key file path is invalid")
        _require_sha256(digest, "Harbor key file sha256")
    return HarborIdentity(**value)


def _parse_runtime_requirements(value: object) -> RuntimeRequirements:
    if not isinstance(value, dict) or set(value) != _RUNTIME_REQUIREMENT_KEYS:
        raise PairIdentityError("pair runtime requirements differ from schema v1")
    for key in _RUNTIME_REQUIREMENT_KEYS:
        if value[key] is not True:
            raise PairIdentityError("pair runtime requirement is not enabled")
    return RuntimeRequirements(**value)


def _parse_no_api_seccomp(value: object) -> NoApiSeccompIdentity:
    if not isinstance(value, dict) or set(value) != _SECCOMP_KEYS:
        raise PairIdentityError("no-API seccomp identity differs from schema v1")
    if value["profile_path"] != "eval/seccomp/plan008-userns-minimal-v0.2.3.json":
        raise PairIdentityError("no-API seccomp path differs from Plan 008")
    _require_sha256(value["source_sha256"], "seccomp source sha256")
    _require_sha256(value["effective_sha256"], "seccomp effective sha256")
    if (
        value["source_sha256"]
        != "9c5198e529f03d38babe9f270f663fa6867bda4e4d14a37a1f6680179d9bbd2f"
        or value["effective_sha256"]
        != "a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf"
    ):
        raise PairIdentityError("no-API seccomp digest differs from diagnosis")
    return NoApiSeccompIdentity(**value)


def _parse_bundles(value: object) -> dict[Side, BundleIdentity]:
    if not isinstance(value, dict) or set(value) != {side.value for side in Side}:
        raise PairIdentityError("pair bundles must contain both sides")
    result: dict[Side, BundleIdentity] = {}
    for side in Side:
        raw = value[side.value]
        if not isinstance(raw, dict) or set(raw) != _BUNDLE_KEYS:
            raise PairIdentityError("pair bundle differs from schema v1")
        path = raw["manifest_path"]
        if (
            not isinstance(path, str)
            or Path(path).is_absolute()
            or any(part in {"", ".", ".."} for part in Path(path).parts)
            or not path.startswith(f"eval-data/bin/{side.value}/")
            or not path.endswith("/manifest.json")
        ):
            raise PairIdentityError("pair bundle manifest path is invalid")
        for key in (
            "manifest_sha256",
            "cli_sha256",
            "code_mode_host_sha256",
            "bwrap_sha256",
        ):
            _require_sha256(raw[key], key)
        for key in ("cli_size", "code_mode_host_size", "bwrap_size"):
            if isinstance(raw[key], bool) or not isinstance(raw[key], int) or raw[key] <= 0:
                raise PairIdentityError("pair bundle size is invalid")
        _require_commit(raw["source_commit"], "bundle source commit")
        normalization = raw["workspace_lock_normalization"]
        if normalization is not None and (
            not isinstance(normalization, str) or not normalization
        ):
            raise PairIdentityError("bundle lock normalization is invalid")
        result[side] = BundleIdentity(**raw)
    if result[Side.CODEX].bwrap_sha256 != result[Side.RONDO].bwrap_sha256:
        raise PairIdentityError("both pair sides must use the same bwrap")
    return result


def _validate_console_script(
    executable: Path,
    *,
    python_executable: Path,
    expected_normalized_sha256: str,
    normalization: str,
) -> None:
    try:
        metadata = executable.lstat()
        raw = executable.read_bytes()
        contents = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise PairIdentityError("Harbor console script is unavailable") from exc
    first_line, separator, remainder = raw.partition(b"\n")
    if (
        executable.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or not metadata.st_mode & stat.S_IXUSR
        or metadata.st_size > 8192
        or not separator
        or normalization != "absolute_shebang_to_#!<RONDO_EVAL_PYTHON>"
    ):
        raise PairIdentityError("Harbor console script bytes differ from the pair lock")
    normalized = b"#!<RONDO_EVAL_PYTHON>\n" + remainder
    if hashlib.sha256(normalized).hexdigest() != expected_normalized_sha256:
        raise PairIdentityError("Harbor console script bytes differ from the pair lock")
    lines = contents.splitlines()
    try:
        shebang = Path(lines[0].removeprefix("#!")).resolve(strict=True)
        interpreter = python_executable.resolve(strict=True)
    except (IndexError, OSError) as exc:
        raise PairIdentityError("Harbor console script interpreter is unavailable") from exc
    if (
        not lines[0].startswith("#!")
        or shebang != interpreter
        or "from harbor.cli.main import app" not in lines
        or not any("app()" in line for line in lines)
    ):
        raise PairIdentityError("Harbor console script differs from the installed entry point")


def _validate_bundle_file(path: Path, *, digest: str, size: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise PairIdentityError("tracked pair bundle file is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size != size
        or not metadata.st_mode & stat.S_IXUSR
    ):
        raise PairIdentityError("tracked pair bundle file identity is unsafe")
    observed = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                observed.update(chunk)
                total += len(chunk)
    except OSError as exc:
        raise PairIdentityError("tracked pair bundle file is unreadable") from exc
    if total != size or observed.hexdigest() != digest:
        raise PairIdentityError("tracked pair bundle file differs from the pair lock")


def _compare_record_fairness(
    records: list[Mapping[str, Any]],
    identity: PairIdentity,
    reasons: list[str],
) -> None:
    core_keys = {
        "approvals_reviewer": "approvals_reviewer",
        "approval_policy": "approval_policy",
        "sandbox_mode": "sandbox_mode",
        "sandbox_network_access": "sandbox_network_access",
        "websocket": "websocket",
        "code_mode_host": "code_mode_host",
        "terminal_bench_version": "terminal_bench_version",
        "task_image_digest": "task_image_digest",
        "timeout_seconds": "timeout_seconds",
        "max_retries": "max_retries",
        "budget_usd": "budget_usd",
    }
    legacy_provider_keys = {
        "main_model": "main_model",
        "guardian_model": "guardian_model",
        "guardian_effort": "guardian_effort",
        "provider_id": "provider",
        "provider_api": "provider_api",
    }
    keys = (
        core_keys | legacy_provider_keys
        if identity.schema_version == 1
        else core_keys
    )
    projected: list[dict[str, object]] = []
    for record in records:
        config = record.get("config")
        if not isinstance(config, Mapping):
            reasons.append("pair_config_missing")
            return
        current = {fair_key: config.get(record_key) for fair_key, record_key in keys.items()}
        current["task_id"] = FIX_GIT_TASK_ID
        projected.append(current)
    expected = {key: identity.fairness[key] for key in keys} | {"task_id": FIX_GIT_TASK_ID}
    if projected[0] != projected[1] or projected[0] != expected:
        reasons.append("pair_fairness_mismatch")
    configs = [record["config"] for record in records]
    if identity.schema_version == 2:
        selected = identity.require_selected_profile().to_dict()
        projected_profiles = [
            {key: config.get(key) for key in _SELECTED_PROFILE_KEYS}
            for config in configs
        ]
        if projected_profiles[0] != projected_profiles[1]:
            reasons.append("pair_selected_profile_mismatch")
        if any(profile != selected for profile in projected_profiles):
            reasons.append("pair_selected_profile_lock_mismatch")
    else:
        main_efforts = [config.get("main_effort") for config in configs]
        if (
            any(not isinstance(effort, str) for effort in main_efforts)
            or main_efforts[0] != main_efforts[1]
        ):
            reasons.append("pair_main_effort_mismatch")
        profile_hashes = [config.get("provider_profile_sha256") for config in configs]
        endpoint_hashes = [config.get("provider_endpoint_sha256") for config in configs]
        if all(isinstance(value, str) for value in profile_hashes + endpoint_hashes):
            if profile_hashes[0] != profile_hashes[1]:
                reasons.append("pair_provider_profile_mismatch")
            if endpoint_hashes[0] != endpoint_hashes[1]:
                reasons.append("pair_provider_endpoint_mismatch")
        elif all(config.get("provider_base_url") is not None for config in configs):
            # Compatibility for append-only v8 records. New results never publish
            # the raw endpoint or whole local-config digest.
            if configs[0].get("provider_base_url") != configs[1].get(
                "provider_base_url"
            ):
                reasons.append("pair_provider_base_url_mismatch")
            if configs[0].get("provider_config_sha256") != configs[1].get(
                "provider_config_sha256"
            ):
                reasons.append("pair_provider_config_mismatch")
        else:
            reasons.append("pair_provider_profile_missing")
    for record in records:
        side = Side(record["side"])
        if record.get("binary_sha256") != identity.bundles[side].cli_sha256:
            reasons.append(f"{side.value}_bundle_mismatch")


def _require_sha256(value: object, label: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise PairIdentityError(f"{label} must be 64 lowercase hexadecimal characters")


def _require_commit(value: object, label: str) -> None:
    if not isinstance(value, str) or len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise PairIdentityError(f"{label} must be 40 lowercase hexadecimal characters")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PairIdentityError("pair identity file cannot be hashed") from exc
    return digest.hexdigest()


def _container_metrics(value: Mapping[str, object] | None) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "container_id",
        "cpu_usage_seconds",
        "peak_memory_bytes",
    }:
        raise PairIdentityError("container metrics differ from schema v1")
    container_id = value["container_id"]
    cpu = value["cpu_usage_seconds"]
    peak = value["peak_memory_bytes"]
    if (
        not isinstance(container_id, str)
        or not 12 <= len(container_id) <= 64
        or any(character not in "0123456789abcdef" for character in container_id)
        or isinstance(cpu, bool)
        or not isinstance(cpu, (int, float))
        or not float(cpu) >= 0
        or not float(cpu) < float("inf")
        or isinstance(peak, bool)
        or not isinstance(peak, int)
        or peak <= 0
    ):
        raise PairIdentityError("container metrics are invalid")
    return {
        "container_id": container_id,
        "cpu_usage_seconds": float(cpu),
        "peak_memory_bytes": peak,
    }


def _atomic_replace_bytes(
    path: Path,
    contents: bytes,
    *,
    hook: Callable[[str], None] | None = None,
) -> None:
    """Durably replace one bounded file while a caller-owned stable lock is held."""

    if len(contents) > 1024 * 1024:
        raise PairIdentityError("pair durable payload is oversized")
    callback = hook or (lambda _point: None)
    temporary: Path | None = None
    descriptor = -1
    try:
        descriptor, raw_name = tempfile.mkstemp(
            prefix=f".{path.name}.tmp-",
            dir=path.parent,
        )
        temporary = Path(raw_name)
        os.fchmod(descriptor, 0o600)
        offset = 0
        while offset < len(contents):
            written = os.write(descriptor, contents[offset:])
            if written <= 0:
                raise OSError("durable write made no progress")
            offset += written
        callback("after_temp_write")
        os.fsync(descriptor)
        callback("after_temp_fsync")
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, path)
        temporary = None
        callback("after_replace")
        parent_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        parent_fd = os.open(path.parent, parent_flags)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        callback("after_parent_fsync")
    except PairIdentityError:
        raise
    except OSError as exc:
        raise PairIdentityError("pair durable state cannot be persisted") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
