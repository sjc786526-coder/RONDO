"""Tracked P1 pair identity, shared preflight, and M1 aggregation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import fcntl
import json
import os
import stat
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable, Mapping

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from ..contracts import BinaryManifest, RunOutcome, RunSpec, Side, assert_fair_pair
from .freeze import (
    FIX_GIT_IMAGE_DIGEST,
    FIX_GIT_IMAGE_REF,
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


PAIR_LOCK_PATH = Path(__file__).resolve().parents[2] / "locks" / "p1-terminal-bench-pair-v1.json"
P1_PAIR_ID = "p1-fix-git-pair-v5"
_RETIRED_V4 = {
    "pair_id": "p1-fix-git-pair-v4",
    "terminal_status": "failed",
    "ledger_sha256": "23ceecfebfb058fe6dd814df09a217674f62374740d3e2282b90f4aff069edef",
    "eval_harness_commit": "07d0a487f8c498032a6da7ce4fd37a91c607bdac",
    "run_id": "tb-no-api-rondo-e2cd95f5bc72",
    "side": "rondo",
    "review_log_path": "agent_log/2026-08-10-172258-plan008-fourth-independent-review.md",
}
_PAIR_LOCK_KEYS = {
    "schema_version",
    "pair_id",
    "retired_pairs",
    "modes",
    "topology",
    "fairness",
    "harbor",
    "no_api_seccomp",
    "runtime_requirements",
    "bundles",
}
_RETIRED_PAIR_KEYS = {
    "pair_id",
    "terminal_status",
    "ledger_sha256",
    "eval_harness_commit",
    "run_id",
    "side",
    "review_log_path",
}
_MODE_KEYS = {"enabled", "batch_id"}
_PAID_MODE_KEYS = _MODE_KEYS | {"disabled_reason"}
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
_FAIRNESS_KEYS = {
    "task_id",
    "task_image_digest",
    "terminal_bench_version",
    "provider_id",
    "provider_api",
    "provider_base_url",
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
_HARBOR_KEYS = {
    "package",
    "version",
    "release_commit",
    "wheel_sha256",
    "installed_closure_sha256",
    "installed_closure_files",
    "console_script_normalized_sha256",
    "console_script_normalization",
    "dependency_closure_sha256",
    "dependency_closure_files",
    "dependency_versions",
}
_SECCOMP_KEYS = {"profile_path", "source_sha256", "effective_sha256"}
_RUNTIME_REQUIREMENT_KEYS = {
    "eval_harness_commit_binding",
    "paid_custom_seccomp_required",
    "m1_pair_ledger_required",
    "m1_container_metrics_required",
    "no_api_safe_summary_required",
}


class PairIdentityError(ValueError):
    """Raised when a run cannot prove the tracked pair identity."""


@dataclass(frozen=True)
class NoApiSummaryEvidence:
    sha256: str
    terminal_status: str


class PairSequenceLedger:
    """Persistent two-slot order gate shared by no-API pair and future paid runs."""

    def __init__(
        self,
        path: Path,
        *,
        identity: PairIdentity,
        mode: str,
        persist_hook: Callable[[str], None] | None = None,
    ) -> None:
        selected = identity.mode(mode)
        self.path = path
        self.identity = identity
        self.mode_name = mode
        self.batch_id = selected.batch_id
        self._lock_path = path.with_name(f"{path.name}.lock")
        self._handle: Any | None = None
        self._state: dict[str, Any] | None = None
        self._persist_hook = persist_hook or (lambda _point: None)

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
            if self.mode_name == "no_api":
                try:
                    for run in state["runs"]:
                        if run["status"] in {"completed", "failed"}:
                            evidence = self._read_no_api_summary(run)
                            if (
                                run["no_api_summary_sha256"] != evidence.sha256
                                or run["status"] != evidence.terminal_status
                            ):
                                raise PairIdentityError(
                                    "no-API sequence summary terminal evidence drifted"
                                )
                except PairIdentityError:
                    self.__exit__(None, None, None)
                    raise
        else:
            self._state = {
                "schema_version": 4,
                "pair_id": self.identity.pair_id,
                "pair_lock_sha256": self.identity.lock_sha256,
                "mode": self.mode_name,
                "batch_id": self.batch_id,
                "eval_harness_commit": None,
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

    def claim(self, *, side: Side, run_id: str, eval_harness_commit: str) -> PairSlot:
        state = self._require_state()
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
        if self.mode_name == "paid" and slot.paid_run_id != run_id:
            raise PairIdentityError("paid run id differs from the tracked pair slot")
        if any(item["run_id"] == run_id for item in state["runs"]):
            raise PairIdentityError("pair sequence run id was already claimed")
        state["runs"].append(
            {
                "slot": slot.slot,
                "side": side.value,
                "round": slot.round,
                "run_id": run_id,
                "status": "active",
                "eval_harness_commit": eval_harness_commit,
                "publication_sha256": None,
                "no_api_summary_sha256": None,
                "no_api_summary_path": (
                    _no_api_safe_summary_relative_path(self.identity, run_id)
                    if self.mode_name == "no_api"
                    else None
                ),
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
        no_api_summary_sha256: str | None = None,
        container_metrics: Mapping[str, object] | None = None,
    ) -> None:
        state = self._require_state()
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
        if no_api_summary_sha256 is not None:
            _require_sha256(no_api_summary_sha256, "no-API summary sha256")
        normalized_metrics = _container_metrics(container_metrics)
        if self.mode_name == "no_api":
            if publication_sha256 is not None or normalized_metrics is not None:
                raise PairIdentityError("no-API slot cannot claim paid publication evidence")
            evidence = self._read_no_api_summary(matches[0])
            expected_status = "completed" if completed else "failed"
            if evidence.terminal_status != expected_status:
                raise PairIdentityError("no-API summary terminal status differs from finish")
            if no_api_summary_sha256 is not None and no_api_summary_sha256 != evidence.sha256:
                raise PairIdentityError("no-API summary digest differs from durable bytes")
            no_api_summary_sha256 = evidence.sha256
        if completed and self.mode_name == "paid" and (
            publication_sha256 is None or normalized_metrics is None
        ):
            raise PairIdentityError("completed paid slot lacks publication or container metrics")
        matches[0]["publication_sha256"] = publication_sha256
        matches[0]["no_api_summary_sha256"] = no_api_summary_sha256
        matches[0]["container_metrics"] = normalized_metrics
        matches[0]["status"] = "completed" if completed else "failed"
        if completed:
            state["next_slot"] = matches[0]["slot"] + 1
        else:
            state["blocked"] = True
        self._persist()

    def reconcile_no_api_summary(self, *, requested_side: Side) -> dict[str, Any] | None:
        """Converge one durable safe summary without starting another Docker run."""

        if self.mode_name != "no_api":
            raise PairIdentityError("safe-summary reconciliation is no-API-only")
        state = self._require_state()
        active = [item for item in state["runs"] if item["status"] == "active"]
        if not active:
            return None
        if len(active) != 1:
            raise PairIdentityError("pair sequence active state is ambiguous")
        run = active[0]
        recovered_side = run.get("side")
        if recovered_side != requested_side.value:
            raise PairIdentityError(
                "no-API recovery side mismatch: "
                f"requested={requested_side.value},recovered={recovered_side}"
            )
        evidence = self._read_no_api_summary(run)
        run["no_api_summary_sha256"] = evidence.sha256
        run["status"] = evidence.terminal_status
        if evidence.terminal_status == "completed":
            state["next_slot"] = run["slot"] + 1
        else:
            state["blocked"] = True
        self._persist()
        recovered = json.loads(json.dumps(run, sort_keys=True, separators=(",", ":")))
        recovered["requested_side"] = requested_side.value
        recovered["recovered_side"] = recovered_side
        return recovered

    def stage_paid_publication(
        self,
        *,
        run_id: str,
        eval_harness_commit: str,
        container_metrics: Mapping[str, object],
    ) -> None:
        """Durably retain metrics before the external result transaction begins."""

        if self.mode_name != "paid":
            raise PairIdentityError("publication staging is paid-only")
        state = self._require_state()
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
    ) -> str:
        """Converge a staged slot after ArtifactWriter made its record durable."""

        if self.mode_name != "paid":
            raise PairIdentityError("publication reconciliation is paid-only")
        state = self._require_state()
        matches = [item for item in state["runs"] if item["run_id"] == run_id]
        if len(matches) != 1 or matches[0]["status"] != "publishing":
            raise PairIdentityError("pair sequence publishing run is unavailable")
        record = _published_terminal_record(index_path, run_id=run_id)
        config = record.get("config")
        run = matches[0]
        if (
            record.get("outcome") != RunOutcome.COMPLETED.value
            or record.get("side") != run["side"]
            or not isinstance(config, Mapping)
            or config.get("pair_id") != self.identity.pair_id
            or config.get("pair_lock_sha256") != self.identity.lock_sha256
            or config.get("pair_slot") != run["slot"]
            or config.get("pair_round") != run["round"]
            or config.get("eval_harness_commit") != eval_harness_commit
        ):
            raise PairIdentityError("durable publication differs from the staged pair slot")
        digest = terminal_record_sha256(record)
        self.finish(
            run_id=run_id,
            completed=True,
            eval_harness_commit=eval_harness_commit,
            publication_sha256=digest,
            container_metrics=matches[0]["container_metrics"],
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

    def _persist(self) -> None:
        state = self._require_state()
        encoded = (json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n").encode()
        _atomic_replace_bytes(self.path, encoded, hook=self._persist_hook)

    def _read_no_api_summary(self, run: Mapping[str, object]) -> NoApiSummaryEvidence:
        relative = run.get("no_api_summary_path")
        if not isinstance(relative, str):
            raise PairIdentityError("no-API sequence lacks its fixed safe summary path")
        expected = _no_api_safe_summary_relative_path(
            self.identity, str(run.get("run_id", ""))
        )
        if relative != expected:
            raise PairIdentityError("no-API sequence safe summary path drifted")
        try:
            side = Side(str(run.get("side", "")))
        except ValueError as exc:
            raise PairIdentityError("no-API sequence side is invalid") from exc
        return _read_no_api_safe_summary(
            self.path.parent / relative,
            identity=self.identity,
            side=side,
            run_id=str(run.get("run_id", "")),
            eval_harness_commit=str(run.get("eval_harness_commit", "")),
        )


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
    installed_closure_sha256: str
    installed_closure_files: int
    console_script_normalized_sha256: str
    console_script_normalization: str
    dependency_closure_sha256: str
    dependency_closure_files: int
    dependency_versions: tuple[str, ...]


@dataclass(frozen=True)
class NoApiSeccompIdentity:
    profile_path: str
    source_sha256: str
    effective_sha256: str


@dataclass(frozen=True)
class RuntimeRequirements:
    eval_harness_commit_binding: str
    paid_custom_seccomp_required: bool
    m1_pair_ledger_required: bool
    m1_container_metrics_required: bool
    no_api_safe_summary_required: bool


@dataclass(frozen=True)
class RetiredPairIdentity:
    pair_id: str
    terminal_status: str
    ledger_sha256: str
    eval_harness_commit: str
    run_id: str
    side: Side
    review_log_path: str


@dataclass(frozen=True)
class PairIdentity:
    pair_id: str
    retired_pairs: tuple[RetiredPairIdentity, ...]
    modes: Mapping[str, PairMode]
    topology: tuple[PairSlot, ...]
    fairness: Mapping[str, object]
    harbor: HarborIdentity
    no_api_seccomp: NoApiSeccompIdentity
    runtime_requirements: RuntimeRequirements
    bundles: Mapping[Side, BundleIdentity]
    lock_sha256: str

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
        selected_mode = self.mode(mode)
        slot = self.slot_for(spec.side)
        if spec.batch_id != selected_mode.batch_id:
            raise PairIdentityError("RunSpec batch differs from the tracked pair mode")
        actual = {
            "task_id": spec.task_id,
            "task_image_digest": spec.task_image_digest,
            "terminal_bench_version": spec.terminal_bench_version,
            "provider_id": spec.provider.provider_id,
            "provider_api": spec.provider.api,
            "provider_base_url": spec.provider.base_url,
            "provider_api_key_env": spec.provider.api_key_env,
            "main_model": spec.provider.main_model,
            "guardian_model": spec.provider.guardian_model,
            "guardian_effort": spec.provider.guardian_effort,
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
        if actual != dict(self.fairness):
            raise PairIdentityError("RunSpec fairness fields differ from the tracked pair")
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


def load_pair_identity(path: Path = PAIR_LOCK_PATH) -> PairIdentity:
    try:
        if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            raise PairIdentityError("pair lock must be a regular non-symlink file")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except PairIdentityError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PairIdentityError("pair lock is unreadable") from exc
    if not isinstance(value, dict) or set(value) != _PAIR_LOCK_KEYS:
        raise PairIdentityError("pair lock differs from schema v1")
    if value["schema_version"] != 1 or value["pair_id"] != P1_PAIR_ID:
        raise PairIdentityError("pair lock identity differs from P1")
    retired_pairs = _parse_retired_pairs(value["retired_pairs"], current=value["pair_id"])
    modes = _parse_modes(value["modes"])
    topology = _parse_topology(value["topology"], modes=modes)
    fairness = _parse_fairness(value["fairness"])
    harbor = _parse_harbor(value["harbor"])
    no_api_seccomp = _parse_no_api_seccomp(value["no_api_seccomp"])
    runtime_requirements = _parse_runtime_requirements(value["runtime_requirements"])
    bundles = _parse_bundles(value["bundles"])
    identity = PairIdentity(
        pair_id=value["pair_id"],
        retired_pairs=retired_pairs,
        modes=modes,
        topology=topology,
        fairness=fairness,
        harbor=harbor,
        no_api_seccomp=no_api_seccomp,
        runtime_requirements=runtime_requirements,
        bundles=bundles,
        lock_sha256=hashlib.sha256(raw).hexdigest(),
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
    """Bind the executing Harbor environment to the tracked wheel closure."""

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
    digest, count = _installed_harbor_closure(dist, expected.version)
    if digest != expected.installed_closure_sha256 or count != expected.installed_closure_files:
        raise PairIdentityError("installed Harbor files differ from the frozen wheel closure")
    dependency_digest, dependency_count, dependency_versions = (
        _installed_dependency_closure(dist)
    )
    if (
        dependency_digest != expected.dependency_closure_sha256
        or dependency_count != expected.dependency_closure_files
        or dependency_versions != expected.dependency_versions
    ):
        raise PairIdentityError("installed Harbor dependency closure differs from the pair lock")
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
        if (
            not isinstance(summary, dict)
            or summary.get("metadata_ready") is not True
            or not isinstance(roles, dict)
            or not isinstance(roles.get("main"), int)
            or roles["main"] < 1
        ):
            reasons.append(f"{slot.side.value}_real_api_evidence_missing")
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


def _encode_no_api_safe_summary(
    *,
    identity: PairIdentity,
    side: Side,
    run_id: str,
    eval_harness_commit: str,
    summary: Mapping[str, object],
) -> bytes:
    """Validate and encode one canonical redacted no-API observation."""

    _require_commit(eval_harness_commit, "eval harness commit")
    _require_run_id(run_id)
    required = {
        "schema_version",
        "side",
        "terminal_status",
        "outcome",
        "task_outcome",
        "reward",
        "fake_requests",
        "fake_contract_hits",
        "fake_contract_satisfied",
        "agent_json_events",
        "code_mode_tool_round_trip",
        "host_returncode",
        "pair_validation",
        "failure",
        "docker",
        "artifacts",
    }
    if set(summary) != required or summary.get("side") != side.value:
        raise PairIdentityError("no-API safe summary differs from schema v2")
    terminal_status = summary.get("terminal_status")
    if (
        summary.get("schema_version") != 2
        or summary.get("pair_validation") is not True
        or terminal_status not in {"completed", "failed"}
    ):
        raise PairIdentityError("no-API safe summary is not pair-validation evidence")
    for key in ("fake_requests", "fake_contract_hits", "agent_json_events"):
        value = summary.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PairIdentityError("no-API safe summary count is invalid")
    for key in ("fake_contract_satisfied", "code_mode_tool_round_trip"):
        if not isinstance(summary.get(key), bool):
            raise PairIdentityError("no-API safe summary boolean is invalid")
    reward = summary.get("reward")
    host_returncode = summary.get("host_returncode")
    if (
        summary.get("outcome") not in {item.value for item in RunOutcome}
        or summary.get("task_outcome") not in {None, "pass", "fail"}
        or isinstance(reward, bool)
        or not isinstance(reward, (int, float))
        or not 0 <= float(reward) <= 1
        or not float(reward) < float("inf")
        or isinstance(host_returncode, bool)
        or not isinstance(host_returncode, int)
        or not -255 <= host_returncode <= 255
        or summary.get("fake_contract_hits", 0) > summary.get("fake_requests", 0)
    ):
        raise PairIdentityError("no-API observation is invalid")
    if terminal_status == "completed" and (
        summary.get("outcome") != RunOutcome.COMPLETED.value
        or host_returncode != 0
        or summary.get("fake_requests") != 2
        or summary.get("fake_contract_hits") != 2
        or summary.get("fake_contract_satisfied") is not True
        or summary.get("agent_json_events", 0) <= 0
        or summary.get("code_mode_tool_round_trip") is not True
        or summary.get("failure") is not None
    ):
        raise PairIdentityError("no-API completed observation is invalid")
    failure = summary.get("failure")
    if terminal_status == "failed":
        if not isinstance(failure, Mapping) or set(failure) != {
            "stage",
            "command_id",
            "stderr_summary",
        }:
            raise PairIdentityError("no-API failure diagnostic is missing")
        if (
            failure["stage"]
            not in {
                "preflight",
                "prepare",
                "docker_supervision",
                "adapter_install",
                "adapter_run",
                "harbor",
                "result",
            }
            or not isinstance(failure["command_id"], str)
            or not failure["command_id"]
            or len(failure["command_id"]) > 64
            or any(
                char not in "abcdefghijklmnopqrstuvwxyz0123456789_.-"
                for char in failure["command_id"]
            )
            or failure["stderr_summary"]
            not in {"empty", "permission_denied", "not_found", "timeout", "other_redacted"}
        ):
            raise PairIdentityError("no-API failure diagnostic is invalid")
    docker = summary.get("docker")
    safe_docker: dict[str, object]
    docker_state = docker.get("state") if isinstance(docker, Mapping) else None
    if isinstance(docker, Mapping) and docker_state in {"observed", "observed_partial"}:
        safe_docker_keys = {
            "state",
            "sample_count",
            "baseline_total_bytes",
            "final_total_bytes",
            "baseline_task_bytes",
            "final_task_bytes",
            "baseline_data_root_free_bytes",
            "final_data_root_free_bytes",
            "image_identity",
            "desktop_vhdx",
            "container_metrics",
            "effective_seccomp",
            "runtime",
            "cleanup",
        }
        if set(docker) != safe_docker_keys:
            raise PairIdentityError("no-API Docker summary is incomplete")
        safe_docker = {key: docker[key] for key in sorted(safe_docker_keys)}
        counter_keys = safe_docker_keys - {
            "state",
            "image_identity",
            "desktop_vhdx",
            "container_metrics",
            "effective_seccomp",
            "runtime",
            "cleanup",
        }
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for key, value in safe_docker.items()
            if key in counter_keys
        ):
            raise PairIdentityError("no-API Docker summary counter is invalid")
        image = safe_docker["image_identity"]
        if image is not None and (not isinstance(image, Mapping) or set(image) != {
            "image_reference",
            "image_id",
        }):
            raise PairIdentityError("no-API daemon image evidence is missing")
        image_id = image["image_id"] if isinstance(image, Mapping) else None
        if image is not None and (
            image["image_reference"] != FIX_GIT_IMAGE_REF
            or not isinstance(image_id, str)
            or not image_id.startswith("sha256:")
            or len(image_id) != 71
            or any(character not in "0123456789abcdef" for character in image_id[7:])
        ):
            raise PairIdentityError("no-API daemon image evidence is invalid")
        vhdx = safe_docker["desktop_vhdx"]
        if vhdx is not None and (not isinstance(vhdx, Mapping) or set(vhdx) != {
            "baseline_bytes",
            "peak_bytes",
            "final_bytes",
            "peak_growth_bytes",
        }):
            raise PairIdentityError("no-API VHDX evidence is missing")
        if isinstance(vhdx, Mapping) and (any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in vhdx.values()
        ) or (
            vhdx["peak_bytes"] < max(vhdx["baseline_bytes"], vhdx["final_bytes"])
            or vhdx["peak_growth_bytes"]
            != vhdx["peak_bytes"] - vhdx["baseline_bytes"]
        )):
            raise PairIdentityError("no-API VHDX evidence is invalid")
        metrics = _container_metrics(safe_docker["container_metrics"])
        if safe_docker["container_metrics"] is not None and metrics is None:
            raise PairIdentityError("no-API container metrics are missing")
        seccomp = safe_docker["effective_seccomp"]
        if seccomp is not None and (not isinstance(seccomp, Mapping) or set(seccomp) != {
            "profile_kind",
            "profile_sha256",
        } or not (
            (seccomp["profile_kind"] == "builtin" and seccomp["profile_sha256"] is None)
            or (
                seccomp["profile_kind"] == "custom"
                and isinstance(seccomp["profile_sha256"], str)
                and len(seccomp["profile_sha256"]) == 64
                and all(char in "0123456789abcdef" for char in seccomp["profile_sha256"])
            )
        )):
            raise PairIdentityError("no-API effective seccomp evidence is invalid")
        if terminal_status == "completed" and (
            not isinstance(seccomp, Mapping)
            or seccomp["profile_kind"] != "custom"
            or seccomp["profile_sha256"] != identity.no_api_seccomp.effective_sha256
        ):
            raise PairIdentityError("no-API completed seccomp evidence differs from lock")
        safe_docker["image_identity"] = dict(image) if isinstance(image, Mapping) else None
        safe_docker["desktop_vhdx"] = dict(vhdx) if isinstance(vhdx, Mapping) else None
        safe_docker["container_metrics"] = metrics
        safe_docker["effective_seccomp"] = dict(seccomp) if isinstance(seccomp, Mapping) else None
        runtime = safe_docker["runtime"]
        if runtime is not None and (not isinstance(runtime, Mapping) or set(runtime) != {
            "privileged",
            "cap_add",
            "cap_drop",
            "security_opt",
            "cgroupns_mode",
            "memory_bytes",
            "memory_swap_bytes",
            "pids_limit",
            "mounts_sha256",
            "networks_sha256",
        } or not isinstance(runtime["privileged"], bool)
        or not all(
            isinstance(runtime[key], list)
            and all(isinstance(item, str) and 0 < len(item) <= 128 for item in runtime[key])
            for key in ("cap_add", "cap_drop", "security_opt")
        )
        or runtime["cgroupns_mode"] not in {"private", "host", "default", "empty"}):
            raise PairIdentityError("no-API effective runtime evidence is invalid")
        if isinstance(runtime, Mapping):
            for key in ("memory_bytes", "memory_swap_bytes", "pids_limit"):
                if (
                    isinstance(runtime[key], bool)
                    or not isinstance(runtime[key], int)
                    or runtime[key] <= 0
                ):
                    raise PairIdentityError("no-API effective runtime limit is invalid")
            for key in ("mounts_sha256", "networks_sha256"):
                _require_sha256(runtime[key], f"no-API runtime {key}")
        if terminal_status == "completed" and (
            not isinstance(runtime, Mapping)
            or runtime["privileged"] is not False
            or runtime["cap_add"] != []
            or runtime["cap_drop"] != ["ALL"]
            or runtime["security_opt"] != ["no-new-privileges:true"]
            or runtime["cgroupns_mode"] != "private"
        ):
            raise PairIdentityError("no-API completed runtime evidence differs from lock")
        cleanup = safe_docker["cleanup"]
        if not isinstance(cleanup, Mapping) or set(cleanup) != {
            "state", "container_count", "network_count", "volume_count"
        } or cleanup["state"] not in {"verified_empty", "unverified"}:
            raise PairIdentityError("no-API cleanup evidence is invalid")
        for key in ("container_count", "network_count", "volume_count"):
            if (
                isinstance(cleanup[key], bool)
                or not isinstance(cleanup[key], int)
                or cleanup[key] < 0
            ):
                raise PairIdentityError("no-API cleanup count is invalid")
        if cleanup["state"] == "verified_empty" and any(
            cleanup[key] for key in ("container_count", "network_count", "volume_count")
        ):
            raise PairIdentityError("no-API cleanup evidence is not empty")
        if docker_state == "observed" and (
            terminal_status == "completed"
            and any(value is None for value in (image, vhdx, metrics, seccomp, runtime))
            or cleanup["state"] != "verified_empty"
        ):
            raise PairIdentityError("no-API completed Docker evidence is incomplete")
        if docker_state == "observed_partial" and terminal_status != "failed":
            raise PairIdentityError("partial Docker evidence is failure-only")
        safe_docker["runtime"] = dict(runtime) if isinstance(runtime, Mapping) else None
        safe_docker["cleanup"] = dict(cleanup)
    elif isinstance(docker, Mapping) and docker.get("state") == "not_observed":
        if set(docker) != {"state", "reason", "cleanup"} or terminal_status != "failed":
            raise PairIdentityError("no-API Docker unavailable evidence is invalid")
        if docker["reason"] != "pre_daemon_failure":
            raise PairIdentityError("no-API Docker unavailable reason is invalid")
        cleanup = docker["cleanup"]
        if not isinstance(cleanup, Mapping) or cleanup != {
            "state": "not_observed",
            "container_count": None,
            "network_count": None,
            "volume_count": None,
        }:
            raise PairIdentityError("no-API unavailable cleanup evidence is invalid")
        safe_docker = {
            "state": docker["state"],
            "reason": docker["reason"],
            "cleanup": dict(cleanup),
        }
    else:
        raise PairIdentityError("no-API Docker evidence is required")
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, Mapping) or set(artifacts) != {
        "trial_result_sha256",
        "trial_exception_sha256",
        "watchdog_state",
        "watchdog_summary_sha256",
    }:
        raise PairIdentityError("no-API artifact evidence is invalid")
    for key in ("trial_result_sha256", "trial_exception_sha256", "watchdog_summary_sha256"):
        if artifacts[key] is not None:
            _require_sha256(artifacts[key], f"no-API {key}")
    if artifacts["watchdog_state"] not in {"parent_finalize_pending", "durable", "not_started"}:
        raise PairIdentityError("no-API watchdog evidence state is invalid")
    if (artifacts["watchdog_state"] == "durable") != (
        artifacts["watchdog_summary_sha256"] is not None
    ):
        raise PairIdentityError("no-API watchdog digest state is inconsistent")
    if terminal_status == "completed" and artifacts["trial_result_sha256"] is None:
        raise PairIdentityError("no-API completed trial digest is missing")
    identity_projection = {
        "pair_id": identity.pair_id,
        "pair_lock_sha256": identity.lock_sha256,
        "eval_harness_commit": eval_harness_commit,
        "side": side.value,
        "bundle_manifest_sha256": identity.bundles[side].manifest_sha256,
        "bundle_cli_sha256": identity.bundles[side].cli_sha256,
        "harbor_installed_closure_sha256": identity.harbor.installed_closure_sha256,
        "harbor_dependency_closure_sha256": identity.harbor.dependency_closure_sha256,
        "harbor_console_script_normalized_sha256": (
            identity.harbor.console_script_normalized_sha256
        ),
        "seccomp_source_sha256": identity.no_api_seccomp.source_sha256,
        "seccomp_effective_sha256": identity.no_api_seccomp.effective_sha256,
    }
    identity_sha = hashlib.sha256(
        json.dumps(identity_projection, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    observation = {
        key: summary[key]
        for key in (
            "outcome",
            "task_outcome",
            "reward",
            "fake_requests",
            "fake_contract_hits",
            "fake_contract_satisfied",
            "agent_json_events",
            "code_mode_tool_round_trip",
            "host_returncode",
            "failure",
            "artifacts",
        )
    }
    observation["docker"] = safe_docker
    payload = {
        "schema_version": 2,
        "run_id": run_id,
        "terminal_status": terminal_status,
        "identity": identity_projection,
        "identity_sha256": identity_sha,
        "observation": observation,
    }
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return encoded


def persist_no_api_safe_summary(
    path: Path,
    *,
    identity: PairIdentity,
    side: Side,
    run_id: str,
    eval_harness_commit: str,
    summary: Mapping[str, object],
) -> str:
    """Persist or idempotently verify one fixed, identity-bound safe summary."""

    encoded = _encode_no_api_safe_summary(
        identity=identity,
        side=side,
        run_id=run_id,
        eval_harness_commit=eval_harness_commit,
        summary=summary,
    )
    if path.exists() or path.is_symlink():
        evidence = _read_no_api_safe_summary(
            path,
            identity=identity,
            side=side,
            run_id=run_id,
            eval_harness_commit=eval_harness_commit,
        )
        if path.read_bytes() != encoded:
            raise PairIdentityError("no-API safe summary differs from durable bytes")
        return evidence.sha256
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic_replace_bytes(path, encoded)
    return hashlib.sha256(encoded).hexdigest()


def no_api_safe_summary_path(
    ledger_path: Path, *, identity: PairIdentity, run_id: str
) -> Path:
    """Return the sole durable safe-summary location for a claimed no-API run."""

    return ledger_path.parent / _no_api_safe_summary_relative_path(identity, run_id)


def _no_api_safe_summary_relative_path(identity: PairIdentity, run_id: str) -> str:
    _require_run_id(run_id)
    return f"{identity.pair_id}/no-api-safe/{run_id}.json"


def _read_no_api_safe_summary(
    path: Path,
    *,
    identity: PairIdentity,
    side: Side,
    run_id: str,
    eval_harness_commit: str,
) -> NoApiSummaryEvidence:
    try:
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
            raise PairIdentityError("no-API safe summary must be a regular file")
        if not 0 < metadata.st_size <= 1024 * 1024:
            raise PairIdentityError("no-API safe summary is empty or oversized")
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except PairIdentityError:
        raise
    except FileNotFoundError as exc:
        raise PairIdentityError("no-API safe summary is missing") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PairIdentityError("no-API safe summary is unreadable") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "run_id",
        "terminal_status",
        "identity",
        "identity_sha256",
        "observation",
    } or not isinstance(payload.get("observation"), Mapping):
        raise PairIdentityError("no-API safe summary differs from schema v2")
    summary = {
        "schema_version": 2,
        "side": side.value,
        "terminal_status": payload["terminal_status"],
        "pair_validation": True,
        **dict(payload["observation"]),
    }
    expected = _encode_no_api_safe_summary(
        identity=identity,
        side=side,
        run_id=run_id,
        eval_harness_commit=eval_harness_commit,
        summary=summary,
    )
    if raw != expected:
        raise PairIdentityError("no-API safe summary identity or canonical bytes drifted")
    return NoApiSummaryEvidence(
        sha256=hashlib.sha256(raw).hexdigest(),
        terminal_status=str(payload["terminal_status"]),
    )


def _parse_modes(value: object) -> dict[str, PairMode]:
    if not isinstance(value, dict) or set(value) != {"no_api", "paid"}:
        raise PairIdentityError("pair modes differ from schema v1")
    result: dict[str, PairMode] = {}
    for name, raw in value.items():
        expected_keys = _PAID_MODE_KEYS if name == "paid" else _MODE_KEYS
        if not isinstance(raw, dict) or set(raw) != expected_keys:
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
        if name == "paid" and not enabled and (
            not isinstance(reason, str) or not reason
        ):
            raise PairIdentityError("disabled paid mode requires a reason")
        result[name] = PairMode(enabled, batch_id, reason)
    return result


def _parse_retired_pairs(
    value: object, *, current: str
) -> tuple[RetiredPairIdentity, ...]:
    if not isinstance(value, list) or value != [_RETIRED_V4]:
        raise PairIdentityError("retired pair list differs from schema v1")
    result: list[RetiredPairIdentity] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != _RETIRED_PAIR_KEYS:
            raise PairIdentityError("retired pair differs from schema v1")
        pair_id = raw["pair_id"]
        run_id = raw["run_id"]
        review_path = raw["review_log_path"]
        if (
            not isinstance(pair_id, str)
            or not pair_id
            or pair_id == current
            or pair_id in seen
            or raw["terminal_status"] != "failed"
            or not isinstance(review_path, str)
            or not review_path.startswith("agent_log/")
            or not review_path.endswith(".md")
            or Path(review_path).is_absolute()
            or ".." in Path(review_path).parts
        ):
            raise PairIdentityError("retired pair identity is invalid")
        _require_sha256(raw["ledger_sha256"], "retired pair ledger sha256")
        _require_commit(raw["eval_harness_commit"], "retired pair harness commit")
        _require_run_id(run_id)
        try:
            side = Side(raw["side"])
        except (TypeError, ValueError) as exc:
            raise PairIdentityError("retired pair side is invalid") from exc
        seen.add(pair_id)
        result.append(
            RetiredPairIdentity(
                pair_id=pair_id,
                terminal_status="failed",
                ledger_sha256=raw["ledger_sha256"],
                eval_harness_commit=raw["eval_harness_commit"],
                run_id=run_id,
                side=side,
                review_log_path=review_path,
            )
        )
    return tuple(result)


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
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise PairIdentityError("pair sequence ledger differs from schema v4")
    if (
        value["schema_version"] != 4
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
    harness_commit = value["eval_harness_commit"]
    if harness_commit is not None:
        _require_commit(harness_commit, "pair sequence eval harness commit")
    if bool(value["runs"]) != (harness_commit is not None):
        raise PairIdentityError("pair sequence harness binding is inconsistent")
    statuses: list[str] = []
    for index, item in enumerate(value["runs"], start=1):
        if not isinstance(item, dict) or set(item) != {
            "slot",
            "side",
            "round",
            "run_id",
            "status",
            "eval_harness_commit",
            "publication_sha256",
            "no_api_summary_sha256",
            "no_api_summary_path",
            "container_metrics",
        }:
            raise PairIdentityError("pair sequence run differs from schema v4")
        slot = identity.topology[index - 1]
        if (
            item["slot"] != slot.slot
            or item["side"] != slot.side.value
            or item["round"] != slot.round
            or not isinstance(item["run_id"], str)
            or not item["run_id"]
            or item["status"] not in {"active", "publishing", "completed", "failed"}
            or (mode == "paid" and item["run_id"] != slot.paid_run_id)
            or item["eval_harness_commit"] != harness_commit
        ):
            raise PairIdentityError("pair sequence run is invalid")
        expected_safe_path = (
            _no_api_safe_summary_relative_path(identity, item["run_id"])
            if mode == "no_api"
            else None
        )
        if item["no_api_summary_path"] != expected_safe_path:
            raise PairIdentityError("pair sequence no-API summary path is invalid")
        for key in ("publication_sha256", "no_api_summary_sha256"):
            if item[key] is not None:
                _require_sha256(item[key], f"pair sequence {key}")
        metrics = _container_metrics(item["container_metrics"])
        if metrics != item["container_metrics"]:
            raise PairIdentityError("pair sequence container metrics are not canonical")
        if (
            mode == "no_api"
            and item["status"] in {"completed", "failed"}
            and item["no_api_summary_sha256"] is None
        ):
            raise PairIdentityError("terminal no-API sequence lacks summary evidence")
        if item["status"] in {"active", "publishing"} and item["no_api_summary_sha256"] is not None:
            raise PairIdentityError("unfinished pair sequence cannot claim summary evidence")
        if mode == "paid" and item["no_api_summary_sha256"] is not None:
            raise PairIdentityError("paid sequence cannot claim no-API summary evidence")
        if mode == "no_api" and (
            item["publication_sha256"] is not None or metrics is not None
        ):
            raise PairIdentityError("no-API sequence cannot claim paid evidence")
        if item["status"] == "completed" and mode == "paid" and (
            item["publication_sha256"] is None or metrics is None
        ):
            raise PairIdentityError("completed paid sequence lacks publication evidence")
        if item["status"] == "publishing" and (mode != "paid" or metrics is None):
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


def _parse_fairness(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _FAIRNESS_KEYS:
        raise PairIdentityError("pair fairness fields differ from schema v1")
    expected = {
        "task_id": FIX_GIT_TASK_ID,
        "task_image_digest": FIX_GIT_IMAGE_DIGEST,
        "terminal_bench_version": TERMINAL_BENCH_VERSION,
        "provider_id": "openai",
        "provider_api": "responses",
        "provider_base_url": "https://api.openai.com/v1",
        "provider_api_key_env": "OPENAI_API_KEY",
        "main_model": "gpt-5.6-luna",
        "guardian_model": "gpt-5.6-luna",
        "guardian_effort": "low",
        "approvals_reviewer": "auto_review",
        "approval_policy": "on-request",
        "sandbox_mode": "workspace-write",
        "sandbox_network_access": True,
        "websocket": False,
        "code_mode_host": True,
        "timeout_seconds": 1800,
        "max_retries": 0,
        "budget_usd": 5.0,
    }
    if value != expected:
        raise PairIdentityError("pair fairness values differ from P1")
    return dict(value)


def _parse_harbor(value: object) -> HarborIdentity:
    if not isinstance(value, dict) or set(value) != _HARBOR_KEYS:
        raise PairIdentityError("Harbor identity differs from schema v1")
    for key in (
        "wheel_sha256",
        "installed_closure_sha256",
        "console_script_normalized_sha256",
        "dependency_closure_sha256",
    ):
        _require_sha256(value[key], key)
    if (
        value["package"] != HARBOR_PACKAGE
        or value["version"] != HARBOR_VERSION
        or value["release_commit"] != HARBOR_RELEASE_COMMIT
        or value["wheel_sha256"] != HARBOR_WHEEL_SHA256
        or value["console_script_normalization"]
        != "absolute_shebang_to_#!<RONDO_EVAL_PYTHON>"
        or any(
            isinstance(value[key], bool)
            or not isinstance(value[key], int)
            or value[key] <= 0
            for key in (
                "installed_closure_files",
                "dependency_closure_files",
            )
        )
        or not isinstance(value["dependency_versions"], list)
        or not value["dependency_versions"]
        or value["dependency_versions"] != sorted(set(value["dependency_versions"]))
        or any(
            not isinstance(item, str) or "==" not in item or not item
            for item in value["dependency_versions"]
        )
    ):
        raise PairIdentityError("Harbor identity differs from the B1 freeze")
    return HarborIdentity(
        **{key: item for key, item in value.items() if key != "dependency_versions"},
        dependency_versions=tuple(value["dependency_versions"]),
    )


def _parse_runtime_requirements(value: object) -> RuntimeRequirements:
    if not isinstance(value, dict) or set(value) != _RUNTIME_REQUIREMENT_KEYS:
        raise PairIdentityError("pair runtime requirements differ from schema v1")
    if value["eval_harness_commit_binding"] != "first_claim_exact":
        raise PairIdentityError("pair eval harness binding is not fail-closed")
    for key in _RUNTIME_REQUIREMENT_KEYS - {"eval_harness_commit_binding"}:
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


def _installed_harbor_closure(
    distribution: importlib.metadata.Distribution, version: str
) -> tuple[str, int]:
    package_root = Path(distribution.locate_file("harbor"))
    dist_info_root = Path(distribution.locate_file(f"harbor-{version}.dist-info"))
    candidates: list[tuple[str, Path]] = []
    try:
        for path in package_root.rglob("*"):
            if path.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            relative = path.relative_to(package_root).as_posix()
            candidates.append((f"harbor/{relative}", path))
        for name in ("METADATA", "WHEEL", "entry_points.txt"):
            candidates.append((f"harbor-{version}.dist-info/{name}", dist_info_root / name))
        licenses = dist_info_root / "licenses"
        for path in licenses.rglob("*"):
            if path.is_file():
                relative = path.relative_to(dist_info_root).as_posix()
                candidates.append((f"harbor-{version}.dist-info/{relative}", path))
    except OSError as exc:
        raise PairIdentityError("installed Harbor closure is unavailable") from exc
    digest = hashlib.sha256()
    for name, path in sorted(candidates):
        try:
            metadata = path.lstat()
            contents = path.read_bytes()
        except OSError as exc:
            raise PairIdentityError("installed Harbor file is unreadable") from exc
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink() or len(contents) != metadata.st_size:
            raise PairIdentityError("installed Harbor closure contains an unsafe file")
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(len(contents)).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(contents).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), len(candidates)


def _installed_dependency_closure(
    harbor_distribution: importlib.metadata.Distribution,
) -> tuple[str, int, tuple[str, ...]]:
    """Hash Harbor's installed, marker-active transitive runtime dependencies."""

    pending = list(_active_requirements(harbor_distribution))
    distributions: dict[str, importlib.metadata.Distribution] = {}
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        if name in distributions:
            continue
        try:
            distribution = importlib.metadata.distribution(requirement.name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise PairIdentityError("Harbor runtime dependency is not installed") from exc
        if requirement.specifier and distribution.version not in requirement.specifier:
            raise PairIdentityError("Harbor runtime dependency version is incompatible")
        distributions[name] = distribution
        pending.extend(_active_requirements(distribution))

    digest = hashlib.sha256()
    file_count = 0
    versions: list[str] = []
    for name, distribution in sorted(distributions.items()):
        versions.append(f"{name}=={distribution.version}")
        files = distribution.files
        if files is None:
            raise PairIdentityError("Harbor dependency has no installed file manifest")
        included = 0
        for relative in sorted(files, key=lambda item: item.as_posix()):
            relative_text = relative.as_posix()
            if (
                ".." in relative.parts
                or "__pycache__" in relative.parts
                or relative_text.endswith(".pyc")
                or relative.name == "RECORD"
            ):
                continue
            path = Path(distribution.locate_file(relative))
            try:
                metadata = path.lstat()
                contents = path.read_bytes()
            except OSError as exc:
                raise PairIdentityError("Harbor dependency file is unreadable") from exc
            if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
                raise PairIdentityError("Harbor dependency closure contains an unsafe file")
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(relative_text.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(len(contents)).encode("ascii"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(contents).hexdigest().encode("ascii"))
            digest.update(b"\n")
            file_count += 1
            included += 1
        if included == 0:
            raise PairIdentityError("Harbor dependency closure is empty")
    if not distributions or file_count == 0:
        raise PairIdentityError("Harbor dependency closure is empty")
    return digest.hexdigest(), file_count, tuple(sorted(versions))


def _active_requirements(
    distribution: importlib.metadata.Distribution,
) -> tuple[Requirement, ...]:
    result: list[Requirement] = []
    for raw in distribution.requires or ():
        try:
            requirement = Requirement(raw)
        except InvalidRequirement as exc:
            raise PairIdentityError("Harbor dependency metadata is invalid") from exc
        if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
            result.append(requirement)
    return tuple(result)


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
    keys = {
        "main_model": "main_model",
        "guardian_model": "guardian_model",
        "guardian_effort": "guardian_effort",
        "approvals_reviewer": "approvals_reviewer",
        "approval_policy": "approval_policy",
        "sandbox_mode": "sandbox_mode",
        "sandbox_network_access": "sandbox_network_access",
        "websocket": "websocket",
        "code_mode_host": "code_mode_host",
        "terminal_bench_version": "terminal_bench_version",
        "provider_id": "provider",
        "provider_api": "provider_api",
        "provider_base_url": "provider_base_url",
        "provider_api_key_env": "provider_api_key_env",
        "task_image_digest": "task_image_digest",
        "timeout_seconds": "timeout_seconds",
        "max_retries": "max_retries",
        "budget_usd": "budget_usd",
    }
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
    if configs[0].get("provider_config_sha256") != configs[1].get("provider_config_sha256"):
        reasons.append("pair_provider_config_mismatch")
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


def _require_run_id(value: object) -> None:
    if not isinstance(value, str) or not value or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for character in value
    ):
        raise PairIdentityError("pair sequence run id is invalid")


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
