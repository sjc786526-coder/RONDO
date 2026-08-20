"""Boolean-only local readiness checks for Plan 049 Phase B."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

from ..config import ConfigError, RepoPaths, load_provider_secret, load_runtime_config
from ..team_lens.model import validate_team_view
from .aggregate import aggregate
from .contract import CampaignContract
from .schedule import slots
from .store import RehearsalStore, assert_body_free


class ReadinessError(ValueError):
    """Raised when the frozen Phase A evidence set is absent or inconsistent."""


def secret_readiness(paths: RepoPaths, *, provider_name: str) -> dict[str, bool]:
    """Inspect no secret content unless the file boundary is already safe.

    The strict project loader parses KEY=VALUE data and returns the requested
    value in-process. This function immediately reduces that result to one
    boolean and never returns a name, value, error detail, or file content.
    """

    path = paths.common_root / ".env.local"
    try:
        metadata = path.lstat()
    except OSError:
        return {
            "exists": False,
            "regular_file": False,
            "non_symlink": False,
            "mode_0600": False,
            "phase_b_required_values_nonempty": False,
        }
    regular = stat.S_ISREG(metadata.st_mode)
    non_symlink = not stat.S_ISLNK(metadata.st_mode)
    mode_ok = stat.S_IMODE(metadata.st_mode) == 0o600
    values_ok = False
    if regular and non_symlink and mode_ok:
        try:
            config = load_runtime_config(paths)
            _discarded_name, secret = load_provider_secret(config, provider_name)
            values_ok = bool(secret)
        except ConfigError:
            values_ok = False
    return {
        "exists": True,
        "regular_file": regular,
        "non_symlink": non_symlink,
        "mode_0600": mode_ok,
        "phase_b_required_values_nonempty": values_ok,
    }


def require_phase_a_evidence(
    contract: CampaignContract,
    *,
    common_root: Path,
    rehearsal_namespace: str,
    loopback_namespace: str,
) -> dict[str, Any]:
    """Validate the complete offline receipt set without reading raw trace bodies."""

    expected_schedule = slots(contract)
    rehearsal_root = (
        Path(common_root).resolve()
        / "eval-data"
        / "plan-049"
        / "rehearsal"
        / rehearsal_namespace
    )
    if not rehearsal_root.is_dir() or rehearsal_root.is_symlink():
        raise ReadinessError("Plan 049 rehearsal evidence is absent")
    store = RehearsalStore(common_root, rehearsal_namespace)
    records = store.records()
    if (
        len(records) != len(expected_schedule)
        or any(record["terminal"] is not True for record in records)
        or {record["slot_id"] for record in records}
        != {slot.slot_id for slot in expected_schedule}
    ):
        raise ReadinessError("Plan 049 rehearsal schedule is incomplete")
    views: dict[str, dict[str, Any]] = {}
    for record in records:
        if (
            record["lock_id"] != contract.lock_id
            or record["lock_sha256"] != contract.lock_sha256
            or record["taskset_sha256"] != contract.taskset_sha256
            or record["policy_sha256"] != contract.policy_sha256
            or record["trace_status"] != "synthetic_fixture"
        ):
            raise ReadinessError("Plan 049 rehearsal identity differs")
        run_root = store.runs_root / record["run_id"]
        checkpoint = _read_json(run_root / "execution.json", "execution checkpoint")
        assert_body_free(checkpoint)
        if (
            checkpoint.get("lock_sha256") != contract.lock_sha256
            or checkpoint.get("run_id") != record["run_id"]
            or checkpoint.get("attempt") != record["attempt"]
            or checkpoint.get("outcome") != record["outcome"]
        ):
            raise ReadinessError("Plan 049 execution checkpoint differs")
        view_path = run_root / "team_view.json"
        report_path = run_root / "team_report.html"
        view_raw = _read_regular_bytes(view_path, "Team View")
        report_raw = _read_regular_bytes(report_path, "Team report")
        try:
            view = json.loads(view_raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReadinessError("Plan 049 Team View is unreadable") from exc
        assert_body_free(view)
        validate_team_view(view)
        if (
            hashlib.sha256(view_raw).hexdigest() != record["team_view_sha256"]
            or hashlib.sha256(report_raw).hexdigest() != record["team_report_sha256"]
        ):
            raise ReadinessError("Plan 049 Team Lens artifact digest differs")
        views[record["run_id"]] = view
    computed = aggregate(
        records,
        views,
        lock_id=contract.lock_id,
        lock_sha256=contract.lock_sha256,
        policy_sha256=contract.policy_sha256,
        expected_slots={slot.slot_id: slot.pair_id for slot in expected_schedule},
    )
    aggregate_raw = _read_regular_bytes(store.aggregate_path, "aggregate")
    expected_aggregate = (
        json.dumps(computed, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if aggregate_raw != expected_aggregate:
        raise ReadinessError("Plan 049 aggregate is missing or nondeterministic")

    loopback_root = (
        Path(common_root).resolve()
        / "eval-data"
        / "plan-049"
        / "loopback"
        / loopback_namespace
    )
    summary_raw = _read_regular_bytes(loopback_root / "loopback.json", "loopback summary")
    try:
        summary = json.loads(summary_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReadinessError("Plan 049 loopback summary is unreadable") from exc
    assert_body_free(summary)
    sides = summary.get("sides") if isinstance(summary, dict) else None
    if (
        not isinstance(summary, dict)
        or summary.get("evidence_kind") != "loopback"
        or summary.get("identity_class") != "rehearsal"
        or summary.get("lock_id") != contract.lock_id
        or summary.get("lock_sha256") != contract.lock_sha256
        or summary.get("policy_sha256") != contract.policy_sha256
        or summary.get("namespace") != loopback_namespace
        or not isinstance(sides, dict)
        or set(sides) != {"codex", "rondo"}
    ):
        raise ReadinessError("Plan 049 loopback identity differs")
    required_tools = ["list_agents", "send_message", "spawn_agent", "wait_agent"]
    for side in ("codex", "rondo"):
        row = sides[side]
        if not isinstance(row, dict):
            raise ReadinessError("Plan 049 loopback side contract differs")
        expected_binary = contract.lock["runtime"][f"{side}_binary_sha256"]
        expected_team_state = None if side == "codex" else True
        if (
            row.get("binary_sha256") != expected_binary
            or row.get("request_count") != 1
            or row.get("policy_sha256") != contract.policy_sha256
            or row.get("policy_matched") is not True
            or row.get("registered_common_tools") != required_tools
            or row.get("team_state") is not expected_team_state
            or row.get("trace_bundle_count") != 1
        ):
            raise ReadinessError("Plan 049 loopback side contract differs")
        side_root = loopback_root / side
        view_raw = _read_regular_bytes(side_root / "team_view.json", "loopback Team View")
        report_raw = _read_regular_bytes(side_root / "team_report.html", "loopback report")
        try:
            view = json.loads(view_raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReadinessError("Plan 049 loopback Team View is unreadable") from exc
        assert_body_free(view)
        validate_team_view(view)
        if (
            hashlib.sha256(view_raw).hexdigest() != row.get("team_view_sha256")
            or hashlib.sha256(report_raw).hexdigest() != row.get("team_report_sha256")
            or (side == "codex" and view.get("team") is not None)
            or (
                side == "codex"
                and view["availability"]["team_events_versions"]["status"]
                != "not_applicable"
            )
            or (side == "rondo" and not isinstance(view.get("team"), dict))
        ):
            raise ReadinessError("Plan 049 loopback Team Lens evidence differs")
    return {
        "rehearsal_namespace": rehearsal_namespace,
        "loopback_namespace": loopback_namespace,
        "run_count": len(records),
        "aggregate_sha256": hashlib.sha256(aggregate_raw).hexdigest(),
        "loopback_summary_sha256": hashlib.sha256(summary_raw).hexdigest(),
        "replay_fixture_sha256": contract.lock["artifacts"][
            "replay_fixture_sha256"
        ],
    }


def _read_json(path: Path, label: str) -> dict[str, Any]:
    raw = _read_regular_bytes(path, label)
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"Plan 049 {label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"Plan 049 {label} is invalid")
    return value


def _read_regular_bytes(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ReadinessError(f"Plan 049 {label} is absent or unsafe")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ReadinessError(f"Plan 049 {label} is unreadable") from exc
