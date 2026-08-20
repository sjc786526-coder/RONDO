"""Body-free Team Lens fixture generation and Plan 049 aggregation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..team_lens.model import CAPABILITY_NAMES, capability, dump_team_view, validate_team_view
from ..team_lens.report import render_report
from .store import assert_body_free


_USAGE = {
    "input_tokens": 0,
    "cached_input_tokens": 0,
    "cache_write_input_tokens": 0,
    "output_tokens": 0,
    "reasoning_output_tokens": 0,
    "total_tokens": 0,
}


def synthetic_team_view(*, side: str, run_id: str, ordinal: int) -> dict[str, Any]:
    """Build a minimal body-free replay view; it is never real-run evidence."""

    if side not in {"codex", "rondo"}:
        raise ValueError("unsupported Plan 049 side")
    product = "codex" if side == "codex" else "rondo-multi"
    root_id = f"{run_id}-root"
    started = ordinal * 1000
    available = {name: capability("available") for name in CAPABILITY_NAMES}
    if side == "codex":
        for name in CAPABILITY_NAMES:
            if name.startswith("team_"):
                available[name] = capability("not_applicable", "product_has_no_team_state")
        team = None
    else:
        for name in (
            "team_revisions",
            "team_projections",
            "team_events_versions",
            "team_routes",
            "team_facts",
        ):
            available[name] = capability("partial", "no_team_state_event_observed")
        team = {
            "revisions": [],
            "projections": [],
            "events": [],
            "versions": [],
            "routes": [],
            "facts": [],
            "attention": [],
        }
    view = {
        "schema_version": 1,
        "source": {
            "product": product,
            "trace_schema": {
                "manifest_version": 1,
                "raw_event_versions": [1],
                "reduced_state_version": None,
            },
            "trace_id": f"trace-{run_id}",
            "rollout_id": f"rollout-{run_id}",
            "root_thread_id": root_id,
        },
        "availability": available,
        "agents": [
            {
                "agent_id": root_id,
                "agent_path": "/root",
                "parent_agent_id": None,
                "role": "root",
                "started_seq": 1,
                "started_at_unix_ms": started,
                "ended_seq": 4,
                "ended_at_unix_ms": started + 3,
                "status": "completed",
            }
        ],
        "turns": [
            {
                "turn_id": f"{run_id}-turn",
                "agent_id": root_id,
                "started_seq": 2,
                "started_at_unix_ms": started + 1,
                "ended_seq": 4,
                "ended_at_unix_ms": started + 3,
                "status": "completed",
            }
        ],
        "inferences": [
            {
                "inference_id": f"{run_id}-inference",
                "agent_id": root_id,
                "turn_id": f"{run_id}-turn",
                "model": "gpt-5.6-terra",
                "provider": "loopback",
                "started_seq": 3,
                "started_at_unix_ms": started + 2,
                "ended_seq": 4,
                "ended_at_unix_ms": started + 3,
                "status": "completed",
                "usage": dict(_USAGE),
            }
        ],
        "tools": [],
        "terminal": [],
        "interactions": [],
        "team": team,
        "summary": {
            "agent_count": 1,
            "turn_count": 1,
            "inference_count": 1,
            "tool_count": 0,
            "terminal_count": 0,
            "interaction_count": 0,
            "wait_count": 0,
            "team_event_count": 0,
            "team_version_count": 0,
            "team_route_count": 0,
            "team_fact_count": 0,
            "started_at_unix_ms": started,
            "ended_at_unix_ms": started + 3,
            "duration_ms": 3,
            "usage": dict(_USAGE),
        },
    }
    validate_team_view(view)
    return view


def write_replay_artifacts(run_root: Path, view: dict[str, Any]) -> dict[str, str]:
    """Write deterministic Team View and HTML twice-identically."""

    validate_team_view(view)
    target = Path(run_root)
    if target.exists() and (target.is_symlink() or not target.is_dir()):
        raise ValueError("Plan 049 run root is unsafe")
    target.mkdir(parents=True, mode=0o700, exist_ok=True)
    view_bytes = dump_team_view(view)
    report_bytes = render_report(view)
    if view_bytes != dump_team_view(view) or report_bytes != render_report(view):
        raise ValueError("Team Lens output is nondeterministic")
    view_path = target / "team_view.json"
    report_path = target / "team_report.html"
    _write_or_verify(view_path, view_bytes)
    _write_or_verify(report_path, report_bytes)
    return {
        "team_view_sha256": hashlib.sha256(view_bytes).hexdigest(),
        "team_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
    }


def aggregate(
    records: Iterable[Mapping[str, Any]],
    views: Mapping[str, dict[str, Any]],
    *,
    lock_id: str,
    lock_sha256: str,
    policy_sha256: str,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda item: (str(item["slot_id"]), int(item["attempt"]))):
        if record["terminal"] is not True:
            continue
        view = views.get(str(record["run_id"]))
        if view is None:
            raise ValueError("trusted terminal record lacks a Team View")
        validate_team_view(view)
        spawn_tools = [tool for tool in view["tools"] if tool["kind"] == "spawn_agent"]
        accepted = [
            interaction
            for interaction in view["interactions"]
            if interaction["kind"] == "spawn_agent" and interaction["status"] == "completed"
        ]
        file_tools = [
            tool
            for tool in view["tools"]
            if tool["kind"] in {"apply_patch", "file_read", "file_write"}
        ]
        first_spawn = min(
            (interaction["started_at_unix_ms"] for interaction in accepted),
            default=None,
        )
        rows.append(
            {
                "phase": record["phase"],
                "pair_id": record["pair_id"],
                "slot_id": record["slot_id"],
                "run_id": record["run_id"],
                "task_id": record["task_id"],
                "side": record["side"],
                "product": record["product"],
                "outcome": record["outcome"],
                "trace_status": record["trace_status"],
                "team_state": None if record["side"] == "codex" else {
                    "availability": view["availability"]["team_events_versions"]["status"],
                    "event_count": view["summary"]["team_event_count"],
                },
                "agent_count": view["summary"]["agent_count"],
                "spawned_member_count": sum(
                    agent["role"] == "spawned" for agent in view["agents"]
                ),
                "spawn_attempt_count": len(spawn_tools),
                "root_spawn_accept_count": len(accepted),
                "first_spawn_offset_ms": (
                    None
                    if first_spawn is None
                    else max(0, first_spawn - view["summary"]["started_at_unix_ms"])
                ),
                "peak_agent_concurrency": _peak_agent_concurrency(view),
                "file_tool_count": len(file_tools),
                "file_activity_coverage": "typed_tools_only",
                "duration_ms": view["summary"]["duration_ms"],
                "usage": view["summary"]["usage"],
            }
        )
    value = {
        "schema_version": 1,
        "evidence_kind": "rehearsal",
        "identity_class": "rehearsal",
        "lock_id": lock_id,
        "lock_sha256": lock_sha256,
        "policy_sha256": policy_sha256,
        "run_count": len(rows),
        "valid_success_count": sum(row["outcome"] == "completed" for row in rows),
        "valid_failure_count": sum(row["outcome"] != "completed" for row in rows),
        "activation_observed": any(row["root_spawn_accept_count"] > 0 for row in rows),
        "runs": rows,
    }
    assert_body_free(value)
    return value


def _write_or_verify(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ValueError("Plan 049 artifact drifted on resume")
        return
    path.write_bytes(payload)


def _peak_agent_concurrency(view: dict[str, Any]) -> int:
    points: list[tuple[int, int]] = []
    fallback_end = view["summary"]["ended_at_unix_ms"]
    for agent in view["agents"]:
        start = agent["started_at_unix_ms"]
        end = agent["ended_at_unix_ms"]
        if end is None:
            end = fallback_end if fallback_end is not None else start
        points.append((start, 1))
        # End sorts after a start at the same instant, counting the overlap.
        points.append((end, -1))
    active = 0
    peak = 0
    for _time, delta in sorted(points, key=lambda item: (item[0], -item[1])):
        active += delta
        peak = max(peak, active)
    return peak
