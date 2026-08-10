"""Tracked P1 pair identity, shared preflight, and M1 aggregation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import fcntl
import json
import os
import stat
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping

from ..contracts import BinaryManifest, RunOutcome, RunSpec, Side, assert_fair_pair
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


PAIR_LOCK_PATH = Path(__file__).resolve().parents[2] / "locks" / "p1-terminal-bench-pair-v1.json"
P1_PAIR_ID = "p1-fix-git-pair-v2"
_PAIR_LOCK_KEYS = {
    "schema_version",
    "pair_id",
    "modes",
    "topology",
    "fairness",
    "harbor",
    "no_api_seccomp",
    "bundles",
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
}
_SECCOMP_KEYS = {"profile_path", "source_sha256", "effective_sha256"}


class PairIdentityError(ValueError):
    """Raised when a run cannot prove the tracked pair identity."""


class PairSequenceLedger:
    """Persistent two-slot order gate shared by no-API pair and future paid runs."""

    def __init__(self, path: Path, *, identity: PairIdentity, mode: str) -> None:
        selected = identity.mode(mode)
        self.path = path
        self.identity = identity
        self.mode_name = mode
        self.batch_id = selected.batch_id
        self._handle: Any | None = None
        self._state: dict[str, Any] | None = None

    def __enter__(self) -> PairSequenceLedger:
        if self.path.is_symlink():
            raise PairIdentityError("pair sequence ledger must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            handle = self.path.open("a+", encoding="utf-8")
            os.chmod(self.path, 0o600)
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.seek(0)
            text = handle.read()
        except OSError as exc:
            raise PairIdentityError("pair sequence ledger is unavailable") from exc
        self._handle = handle
        if text.strip():
            try:
                state = json.loads(text)
            except json.JSONDecodeError as exc:
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
            self._state = {
                "schema_version": 1,
                "pair_id": self.identity.pair_id,
                "pair_lock_sha256": self.identity.lock_sha256,
                "mode": self.mode_name,
                "batch_id": self.batch_id,
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

    def claim(self, *, side: Side, run_id: str) -> PairSlot:
        state = self._require_state()
        if state["blocked"]:
            raise PairIdentityError("pair sequence is blocked by an earlier failed slot")
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
            }
        )
        self._persist()
        return slot

    def finish(self, *, run_id: str, completed: bool) -> None:
        state = self._require_state()
        matches = [item for item in state["runs"] if item["run_id"] == run_id]
        if len(matches) != 1 or matches[0]["status"] != "active":
            raise PairIdentityError("pair sequence active run is unavailable")
        matches[0]["status"] = "completed" if completed else "failed"
        if completed:
            state["next_slot"] = matches[0]["slot"] + 1
        else:
            state["blocked"] = True
        self._persist()

    def _require_state(self) -> dict[str, Any]:
        if self._handle is None or self._state is None:
            raise PairIdentityError("pair sequence ledger is not locked")
        return self._state

    def _persist(self) -> None:
        state = self._require_state()
        encoded = json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n"
        handle = self._handle
        assert handle is not None
        try:
            handle.seek(0)
            handle.truncate(0)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        except OSError as exc:
            raise PairIdentityError("pair sequence ledger cannot be persisted") from exc


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


@dataclass(frozen=True)
class NoApiSeccompIdentity:
    profile_path: str
    source_sha256: str
    effective_sha256: str


@dataclass(frozen=True)
class PairIdentity:
    pair_id: str
    modes: Mapping[str, PairMode]
    topology: tuple[PairSlot, ...]
    fairness: Mapping[str, object]
    harbor: HarborIdentity
    no_api_seccomp: NoApiSeccompIdentity
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
        if mode == "no_api":
            materialized = prepared.materialized_task
            expected = self.no_api_seccomp
            if (
                materialized.seccomp_profile is None
                or materialized.seccomp_profile.as_posix()
                != str((Path(__file__).resolve().parents[3] / expected.profile_path).resolve())
                or materialized.seccomp_profile_source_sha256 != expected.source_sha256
                or materialized.seccomp_profile_effective_sha256 != expected.effective_sha256
                or prepared.command.compose_contract.container.seccomp_profile_sha256
                != expected.effective_sha256
            ):
                raise PairIdentityError("no-API seccomp projection differs from the pair lock")
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
    modes = _parse_modes(value["modes"])
    topology = _parse_topology(value["topology"], modes=modes)
    fairness = _parse_fairness(value["fairness"])
    harbor = _parse_harbor(value["harbor"])
    no_api_seccomp = _parse_no_api_seccomp(value["no_api_seccomp"])
    bundles = _parse_bundles(value["bundles"])
    identity = PairIdentity(
        pair_id=value["pair_id"],
        modes=modes,
        topology=topology,
        fairness=fairness,
        harbor=harbor,
        no_api_seccomp=no_api_seccomp,
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
    _validate_console_script(
        executable,
        python_executable=python_executable or Path(sys.executable),
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


def assess_m1(records: Iterable[Mapping[str, Any]], identity: PairIdentity) -> dict[str, object]:
    """Evaluate Terminal-Bench M1 without treating S2 as an M1 condition."""

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
    ordered = sorted(candidates, key=lambda item: item.get("created_at", ""))
    reasons: list[str] = []
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
        "next_slot",
        "blocked",
        "runs",
    }
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise PairIdentityError("pair sequence ledger differs from schema v1")
    if (
        value["schema_version"] != 1
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
    statuses: list[str] = []
    for index, item in enumerate(value["runs"], start=1):
        if not isinstance(item, dict) or set(item) != {
            "slot",
            "side",
            "round",
            "run_id",
            "status",
        }:
            raise PairIdentityError("pair sequence run differs from schema v1")
        slot = identity.topology[index - 1]
        if (
            item["slot"] != slot.slot
            or item["side"] != slot.side.value
            or item["round"] != slot.round
            or not isinstance(item["run_id"], str)
            or not item["run_id"]
            or item["status"] not in {"active", "completed", "failed"}
            or (mode == "paid" and item["run_id"] != slot.paid_run_id)
        ):
            raise PairIdentityError("pair sequence run is invalid")
        statuses.append(item["status"])
    expected_next = 1 + sum(status == "completed" for status in statuses)
    if value["next_slot"] != expected_next:
        raise PairIdentityError("pair sequence next slot is inconsistent")
    if statuses.count("active") > 1 or (
        "active" in statuses and statuses[-1] != "active"
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
    for key in ("wheel_sha256", "installed_closure_sha256"):
        _require_sha256(value[key], key)
    if (
        value["package"] != HARBOR_PACKAGE
        or value["version"] != HARBOR_VERSION
        or value["release_commit"] != HARBOR_RELEASE_COMMIT
        or value["wheel_sha256"] != HARBOR_WHEEL_SHA256
        or isinstance(value["installed_closure_files"], bool)
        or not isinstance(value["installed_closure_files"], int)
        or value["installed_closure_files"] <= 0
    ):
        raise PairIdentityError("Harbor identity differs from the B1 freeze")
    return HarborIdentity(**value)


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


def _validate_console_script(executable: Path, *, python_executable: Path) -> None:
    try:
        metadata = executable.lstat()
        contents = executable.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PairIdentityError("Harbor console script is unavailable") from exc
    if (
        executable.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or not metadata.st_mode & stat.S_IXUSR
        or metadata.st_size > 8192
    ):
        raise PairIdentityError("Harbor console script is unsafe")
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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PairIdentityError("pair identity file cannot be hashed") from exc
    return digest.hexdigest()
