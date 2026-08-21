"""Offline Phase-A readiness checks for Plan 050."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..proactive_eval.aggregate import aggregate
from ..proactive_eval.loopback import LoopbackError, loopback_output_root
from ..proactive_eval.store import assert_body_free
from ..team_lens.model import validate_team_view
from .contract import CampaignContract, require_common_v2_tool_projections
from .rehearsal import plan050_store
from .report import build_case_outputs, validate_case, validate_overview
from .schedule import slots


class ReadinessError(ValueError):
    """Raised when Phase-A evidence is absent, incomplete, or drifting."""


def require_phase_a_evidence(
    contract: CampaignContract,
    *,
    common_root: Path,
    rehearsal_namespace: str,
    loopback_namespace: str,
) -> dict[str, Any]:
    expected = slots(contract)
    store = plan050_store(
        contract, common_root=common_root, namespace=rehearsal_namespace
    )
    if store.root.is_symlink() or not store.root.is_dir():
        raise ReadinessError("Plan 050 rehearsal evidence is absent")
    records = store.records()
    expected_slots = {slot.slot_id for slot in expected}
    if (
        len(records) != 6
        or {row["slot_id"] for row in records} != expected_slots
        or any(row["terminal"] is not True for row in records)
    ):
        raise ReadinessError("Plan 050 rehearsal schedule is incomplete")
    try:
        run_entries = tuple(store.runs_root.iterdir())
    except OSError as exc:
        raise ReadinessError("Plan 050 rehearsal runs root is unreadable") from exc
    if (
        {entry.name for entry in run_entries} != {row["run_id"] for row in records}
        or any(entry.is_symlink() or not entry.is_dir() for entry in run_entries)
    ):
        raise ReadinessError("Plan 050 rehearsal publications are incomplete")

    ledger = _read_json(store.ledger_path, "rehearsal ledger")
    claims = ledger.get("claims")
    if (
        set(ledger)
        != {"schema_version", "evidence_kind", "identity_class", "cost_usd", "claims"}
        or ledger.get("schema_version") != 1
        or ledger.get("evidence_kind") != "rehearsal"
        or ledger.get("identity_class") != "rehearsal"
        or ledger.get("cost_usd") != "0.00"
        or not isinstance(claims, dict)
        or set(claims) != expected_slots
    ):
        raise ReadinessError("Plan 050 rehearsal ledger is incomplete")
    assert_body_free(ledger)

    views: dict[str, dict[str, Any]] = {}
    allowed_reasons = {
        None,
        "task_native_verifier_failed",
        "synthetic_product_terminal",
    }
    for row in records:
        if (
            row["phase"] != "case"
            or row["lock_id"] != contract.lock_id
            or row["lock_sha256"] != contract.lock_sha256
            or row["taskset_sha256"] != contract.taskset_sha256
            or row["policy_sha256"] != contract.policy_sha256
            or row["trace_status"] != "synthetic_fixture"
            or row["reason_code"] not in allowed_reasons
            or not str(row["run_id"]).startswith("plan050-rehearsal-case-")
        ):
            raise ReadinessError("Plan 050 rehearsal identity differs")
        run_root = store.runs_root / row["run_id"]
        if _read_json(run_root / "run.json", "run publication marker") != row:
            raise ReadinessError("Plan 050 run publication marker differs")
        if claims[row["slot_id"]] != {
            "attempt": row["attempt"],
            "run_id": row["run_id"],
            "status": "settled",
            "cost_usd": "0.00",
            "outcome": row["outcome"],
        }:
            raise ReadinessError("Plan 050 rehearsal ledger and archive differ")
        checkpoint = _read_json(run_root / "execution.json", "execution checkpoint")
        assert_body_free(checkpoint)
        if (
            checkpoint.get("lock_sha256") != contract.lock_sha256
            or checkpoint.get("run_id") != row["run_id"]
            or checkpoint.get("attempt") != row["attempt"]
            or checkpoint.get("outcome") != row["outcome"]
        ):
            raise ReadinessError("Plan 050 execution checkpoint differs")
        view_raw = _read_regular(run_root / "team_view.json", "Team View")
        report_raw = _read_regular(run_root / "team_report.html", "Team report")
        try:
            view = json.loads(view_raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReadinessError("Plan 050 Team View is unreadable") from exc
        assert_body_free(view)
        validate_team_view(view)
        if (
            hashlib.sha256(view_raw).hexdigest() != row["team_view_sha256"]
            or hashlib.sha256(report_raw).hexdigest() != row["team_report_sha256"]
        ):
            raise ReadinessError("Plan 050 Team Lens artifact digest differs")
        views[row["run_id"]] = view

    computed = aggregate(
        records,
        views,
        lock_id=contract.lock_id,
        lock_sha256=contract.lock_sha256,
        policy_sha256=contract.policy_sha256,
        expected_slots={slot.slot_id: slot.pair_id for slot in expected},
    )
    aggregate_raw = _read_regular(store.aggregate_path, "aggregate")
    if aggregate_raw != _canonical(computed):
        raise ReadinessError("Plan 050 aggregate is missing or nondeterministic")
    cases, overview = build_case_outputs(computed)
    for pair_id, case in cases.items():
        validate_case(case)
        if _read_regular(store.root / "cases" / f"{pair_id}.json", "paired case") != _canonical(case):
            raise ReadinessError("Plan 050 paired case is missing or nondeterministic")
    validate_overview(overview)
    overview_raw = _read_regular(store.root / "overview.json", "case overview")
    if overview_raw != _canonical(overview):
        raise ReadinessError("Plan 050 overview is missing or nondeterministic")

    try:
        loopback_root = loopback_output_root(
            contract, common_root=common_root, namespace=loopback_namespace
        )
    except LoopbackError as exc:
        raise ReadinessError("Plan 050 loopback namespace is invalid") from exc
    summary_raw = _read_regular(loopback_root / "loopback.json", "loopback summary")
    try:
        summary = json.loads(summary_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReadinessError("Plan 050 loopback summary is unreadable") from exc
    assert_body_free(summary)
    sides = summary.get("sides") if isinstance(summary, dict) else None
    if (
        not isinstance(summary, dict)
        or summary.get("schema_version") != 2
        or summary.get("evidence_kind") != "loopback"
        or summary.get("identity_class") != "rehearsal"
        or summary.get("lock_id") != contract.lock_id
        or summary.get("lock_sha256") != contract.lock_sha256
        or summary.get("policy_sha256") != contract.policy_sha256
        or summary.get("namespace") != loopback_namespace
        or not isinstance(sides, dict)
        or set(sides) != {"codex", "rondo"}
    ):
        raise ReadinessError("Plan 050 loopback identity differs")
    expected_projection = {
        "root_model": "gpt-5.6-terra",
        "root_effort": "high",
        "member_model": "gpt-5.6-terra",
        "member_effort": "high",
        "guardian_model": "gpt-5.6-terra",
        "guardian_effort": "high",
        "max_concurrent_threads_per_session": 4,
        "provider_request_concurrency": 4,
        "approval_policy": "on-request",
        "sandbox_mode": "workspace-write",
        "root_request_observed": True,
        "member_request_observed": False,
        "guardian_request_observed": False,
        "guardian_projection_source": "shared_model_catalog_override",
    }
    catalog_raw = _read_regular(
        loopback_root / "shared-model-catalog.json", "shared model catalog"
    )
    catalog_sha256 = hashlib.sha256(catalog_raw).hexdigest()
    for side in ("codex", "rondo"):
        row = sides[side]
        expected_binary = contract.lock["runtime"][f"{side}_binary_sha256"]
        expected_team_state = None if side == "codex" else True
        if (
            not isinstance(row, dict)
            or row.get("binary_sha256") != expected_binary
            or row.get("request_count") != 1
            or row.get("policy_sha256") != contract.policy_sha256
            or row.get("policy_matched") is not True
            or row.get("team_state") is not expected_team_state
            or row.get("trace_bundle_count") != 1
            or row.get("command_projection")
            != {**expected_projection, "model_catalog_sha256": catalog_sha256}
        ):
            raise ReadinessError("Plan 050 loopback side contract differs")
        view_raw = _read_regular(loopback_root / side / "team_view.json", "loopback Team View")
        report_raw = _read_regular(loopback_root / side / "team_report.html", "loopback Team report")
        try:
            view = json.loads(view_raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ReadinessError("Plan 050 loopback Team View is unreadable") from exc
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
            raise ReadinessError("Plan 050 loopback Team Lens evidence differs")
    try:
        require_common_v2_tool_projections(
            sides["codex"].get("registered_tool_projection"),
            sides["rondo"].get("registered_tool_projection"),
        )
    except Exception as exc:
        raise ReadinessError("Plan 050 loopback tool projection differs") from exc
    return {
        "rehearsal_namespace": rehearsal_namespace,
        "loopback_namespace": loopback_namespace,
        "run_count": 6,
        "aggregate_sha256": hashlib.sha256(aggregate_raw).hexdigest(),
        "overview_sha256": hashlib.sha256(overview_raw).hexdigest(),
        "loopback_summary_sha256": hashlib.sha256(summary_raw).hexdigest(),
        "replay_fixture_sha256": contract.lock["artifacts"]["replay_fixture_sha256"],
    }


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    raw = _read_regular(path, label)
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"Plan 050 {label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ReadinessError(f"Plan 050 {label} is invalid")
    return value


def _read_regular(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ReadinessError(f"Plan 050 {label} is absent or unsafe")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ReadinessError(f"Plan 050 {label} is unreadable") from exc
