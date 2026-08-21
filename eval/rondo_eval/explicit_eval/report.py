"""Deterministic, body-free paired case data for Plan 050."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from ..proactive_eval.store import assert_body_free


_PAIR_ID = re.compile(r"C0[1-3]\Z")
_SLOT_ID = re.compile(r"case-c0[1-3]-(?:codex|rondo)\Z")
_RUN_ID = re.compile(
    r"plan050-(?:rehearsal|paid)-case-c0[1-3]-(?:codex|rondo)-a[0-9]{2,3}\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_OUTCOMES = {"completed", "task_failed", "product_failed"}
_COLLABORATION = {"collaboration_observed", "policy_noncompliance"}
_OBSERVATION = {"available", "partial", "unsupported", "not_applicable"}
_IMPACT = {"observed", "not_observed", "unknown"}
_SIDES = ("codex", "rondo")


class ReportError(ValueError):
    """Raised when a report would overstate or leak its input evidence."""


def build_case_outputs(
    aggregate: Mapping[str, Any],
    *,
    impact_assessments: Mapping[str, str] | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Construct three paired cases and one overview from trusted body-free rows."""

    lock_id = _exact_string(
        aggregate.get("lock_id"), "multi-explicit-collaboration-v1", "lock id"
    )
    lock_sha = _digest(aggregate.get("lock_sha256"), "lock digest")
    policy_sha = _digest(aggregate.get("policy_sha256"), "policy digest")
    identity_class = _choice(
        aggregate.get("identity_class"), {"rehearsal", "paid"}, "identity class"
    )
    evidence_kind = _choice(
        aggregate.get("evidence_kind"), {"rehearsal", "real_api"}, "evidence kind"
    )
    raw_runs = aggregate.get("runs")
    if not isinstance(raw_runs, list):
        raise ReportError("aggregate runs are invalid")
    terminal: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in raw_runs:
        if not isinstance(raw, dict) or raw.get("counts_as_effective") is not True:
            continue
        row = _project_run(raw)
        key = (row["pair_id"], row["side"])
        if key in terminal:
            raise ReportError("paired case repeats an effective side")
        terminal[key] = row

    impact = dict(impact_assessments or {})
    if set(impact) - {row["slot_id"] for row in terminal.values()}:
        raise ReportError("impact assessment names an unknown slot")
    for slot_id, status in impact.items():
        _slot_id(slot_id)
        _choice(status, _IMPACT, "impact chain status")

    cases: dict[str, dict[str, Any]] = {}
    for pair_id in ("C01", "C02", "C03"):
        rows = [terminal.get((pair_id, side)) for side in _SIDES]
        present = [row for row in rows if row is not None]
        for row in present:
            row["impact_chain_status"] = impact.get(row["slot_id"], "unknown")
        case = {
            "schema_version": 1,
            "evidence_kind": evidence_kind,
            "identity_class": identity_class,
            "lock_id": lock_id,
            "lock_sha256": lock_sha,
            "policy_sha256": policy_sha,
            "pair_id": pair_id,
            "task_id": _pair_task(pair_id, present),
            "complete": len(present) == 2,
            "sides": present,
        }
        validate_case(case)
        cases[pair_id] = case

    all_rows = [row for pair in cases.values() for row in pair["sides"]]
    overview = {
        "schema_version": 1,
        "evidence_kind": evidence_kind,
        "identity_class": identity_class,
        "lock_id": lock_id,
        "lock_sha256": lock_sha,
        "policy_sha256": policy_sha,
        "case_count": 3,
        "complete_case_count": sum(case["complete"] for case in cases.values()),
        "effective_run_count": len(all_rows),
        "external_outcomes": {
            outcome: sum(row["external_outcome"] == outcome for row in all_rows)
            for outcome in sorted(_OUTCOMES)
        },
        "collaboration_statuses": {
            status: sum(row["collaboration_status"] == status for row in all_rows)
            for status in sorted(_COLLABORATION)
        },
        "impact_chain_statuses": {
            status: sum(row["impact_chain_status"] == status for row in all_rows)
            for status in sorted(_IMPACT)
        },
        "case_digests": {
            pair_id: hashlib.sha256(_canonical(case)).hexdigest()
            for pair_id, case in sorted(cases.items())
        },
    }
    validate_overview(overview)
    return cases, overview


def write_case_outputs(
    root: Path,
    cases: Mapping[str, Mapping[str, Any]],
    overview: Mapping[str, Any],
) -> dict[str, Any]:
    target = Path(root)
    if target.exists() and (target.is_symlink() or not target.is_dir()):
        raise ReportError("case output root is unsafe")
    target.mkdir(parents=True, mode=0o700, exist_ok=True)
    case_root = target / "cases"
    case_root.mkdir(mode=0o700, exist_ok=True)
    digests: dict[str, str] = {}
    for pair_id, case in sorted(cases.items()):
        validate_case(case)
        payload = _canonical(case)
        _write_or_verify(case_root / f"{pair_id}.json", payload)
        digests[pair_id] = hashlib.sha256(payload).hexdigest()
    validate_overview(overview)
    overview_payload = _canonical(overview)
    _write_or_verify(target / "overview.json", overview_payload)
    return {
        "case_digests": digests,
        "overview_sha256": hashlib.sha256(overview_payload).hexdigest(),
    }


def validate_case(value: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "evidence_kind",
        "identity_class",
        "lock_id",
        "lock_sha256",
        "policy_sha256",
        "pair_id",
        "task_id",
        "complete",
        "sides",
    }
    if set(value) != expected or value.get("schema_version") != 1:
        raise ReportError("case shape is invalid")
    _choice(value.get("evidence_kind"), {"rehearsal", "real_api"}, "evidence kind")
    _choice(value.get("identity_class"), {"rehearsal", "paid"}, "identity class")
    _exact_string(value.get("lock_id"), "multi-explicit-collaboration-v1", "lock id")
    _digest(value.get("lock_sha256"), "lock digest")
    _digest(value.get("policy_sha256"), "policy digest")
    pair_id = _pair_id(value.get("pair_id"))
    if not isinstance(value.get("task_id"), str) or not value["task_id"].startswith(
        "terminal-bench/"
    ):
        raise ReportError("case task identity is invalid")
    if not isinstance(value.get("complete"), bool) or not isinstance(value.get("sides"), list):
        raise ReportError("case completeness is invalid")
    sides = value["sides"]
    if [row.get("side") for row in sides] != [side for side in _SIDES if any(r.get("side") == side for r in sides)]:
        raise ReportError("case sides are not in stable order")
    for row in sides:
        _validate_run(
            row,
            pair_id=pair_id,
            task_id=value["task_id"],
            identity_class=str(value["identity_class"]),
        )
    if value["complete"] is not (len(sides) == 2):
        raise ReportError("case completeness differs")
    assert_body_free(dict(value))


def validate_overview(value: Mapping[str, Any]) -> None:
    expected = {
        "schema_version",
        "evidence_kind",
        "identity_class",
        "lock_id",
        "lock_sha256",
        "policy_sha256",
        "case_count",
        "complete_case_count",
        "effective_run_count",
        "external_outcomes",
        "collaboration_statuses",
        "impact_chain_statuses",
        "case_digests",
    }
    if set(value) != expected or value.get("schema_version") != 1:
        raise ReportError("overview shape is invalid")
    _choice(value.get("evidence_kind"), {"rehearsal", "real_api"}, "evidence kind")
    _choice(value.get("identity_class"), {"rehearsal", "paid"}, "identity class")
    _exact_string(value.get("lock_id"), "multi-explicit-collaboration-v1", "lock id")
    _digest(value.get("lock_sha256"), "lock digest")
    _digest(value.get("policy_sha256"), "policy digest")
    for key, upper in (("case_count", 3), ("complete_case_count", 3), ("effective_run_count", 6)):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= upper:
            raise ReportError("overview count is invalid")
    if value["case_count"] != 3:
        raise ReportError("overview case count differs")
    _count_map(value.get("external_outcomes"), _OUTCOMES)
    _count_map(value.get("collaboration_statuses"), _COLLABORATION)
    _count_map(value.get("impact_chain_statuses"), _IMPACT)
    if any(
        sum(value[key].values()) != value["effective_run_count"]
        for key in (
            "external_outcomes",
            "collaboration_statuses",
            "impact_chain_statuses",
        )
    ):
        raise ReportError("overview counts do not cover every effective run")
    digests = value.get("case_digests")
    if not isinstance(digests, dict) or set(digests) != {"C01", "C02", "C03"}:
        raise ReportError("overview case digests are invalid")
    for digest in digests.values():
        _digest(digest, "case digest")
    assert_body_free(dict(value))


def _project_run(raw: Mapping[str, Any]) -> dict[str, Any]:
    pair_id = _pair_id(raw.get("pair_id"))
    side = _choice(raw.get("side"), set(_SIDES), "side")
    external = _choice(raw.get("outcome"), _OUTCOMES, "external outcome")
    spawn = raw.get("root_spawn_accept_count")
    activity = raw.get("member_activity_observed")
    returned = raw.get("member_result_returned")
    if isinstance(spawn, bool) or not isinstance(spawn, int) or spawn < 0:
        raise ReportError("Root spawn evidence is invalid")
    if not isinstance(activity, bool) or not isinstance(returned, bool):
        raise ReportError("member contribution evidence is invalid")
    collaboration = (
        "collaboration_observed"
        if spawn > 0 and activity and returned
        else "policy_noncompliance"
    )
    trace = _choice(
        raw.get("trace_status"),
        {"available", "partial", "synthetic_fixture"},
        "trace status",
    )
    observation = {
        "available": "available",
        "partial": "partial",
        "synthetic_fixture": "unsupported",
    }[trace]
    team_state = raw.get("team_state")
    if side == "codex":
        if team_state is not None:
            raise ReportError("Codex Team State must be null")
        team_state_status = "not_applicable"
    else:
        if not isinstance(team_state, dict):
            raise ReportError("RONDO Team State metrics are unavailable")
        statuses = {
            item.get("availability")
            for item in team_state.values()
            if isinstance(item, dict)
        }
        if not statuses or not statuses.issubset(_OBSERVATION - {"not_applicable"}):
            raise ReportError("RONDO Team State availability is invalid")
        team_state_status = "available" if statuses == {"available"} else "partial"
    usage = raw.get("usage")
    if not isinstance(usage, dict):
        raise ReportError("run usage is invalid")
    safe_usage = {}
    for key in (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ):
        item = usage.get(key)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise ReportError("run usage count is invalid")
        safe_usage[key] = item
    return {
        "slot_id": _slot_id(raw.get("slot_id")),
        "run_id": _run_id(raw.get("run_id")),
        "pair_id": pair_id,
        "task_id": _task_id(raw.get("task_id")),
        "side": side,
        "product": None if side == "codex" else "rondo-multi",
        "external_outcome": external,
        "collaboration_status": collaboration,
        "observation_status": observation,
        "team_state_status": team_state_status,
        "impact_chain_status": "unknown",
        "cost_usd": _decimal_string(raw.get("cost_usd", "0.00")),
        "request_count": _nonnegative_int(raw.get("request_count", 0)),
        "duration_ms": _nullable_nonnegative_int(raw.get("duration_ms")),
        "usage": safe_usage,
    }


def _validate_run(
    value: object, *, pair_id: str, task_id: str, identity_class: str
) -> None:
    keys = {
        "slot_id", "run_id", "pair_id", "task_id", "side", "product",
        "external_outcome", "collaboration_status", "observation_status",
        "team_state_status", "impact_chain_status", "cost_usd", "request_count",
        "duration_ms", "usage",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise ReportError("case run shape is invalid")
    if value.get("pair_id") != pair_id or value.get("task_id") != task_id:
        raise ReportError("case run identity differs")
    slot_id = _slot_id(value.get("slot_id"))
    run_id = _run_id(value.get("run_id"))
    _task_id(value.get("task_id"))
    side = _choice(value.get("side"), set(_SIDES), "side")
    if slot_id != f"case-{pair_id.lower()}-{side}" or not run_id.startswith(
        f"plan050-{identity_class}-{slot_id}-"
    ):
        raise ReportError("case run identity is cross-wired")
    if value.get("product") != (None if side == "codex" else "rondo-multi"):
        raise ReportError("case product identity differs")
    _choice(value.get("external_outcome"), _OUTCOMES, "external outcome")
    _choice(value.get("collaboration_status"), _COLLABORATION, "collaboration status")
    _choice(value.get("observation_status"), _OBSERVATION, "observation status")
    expected_team = "not_applicable" if side == "codex" else {"available", "partial", "unsupported"}
    if isinstance(expected_team, str):
        _exact_string(value.get("team_state_status"), expected_team, "Team State status")
    else:
        _choice(value.get("team_state_status"), expected_team, "Team State status")
    _choice(value.get("impact_chain_status"), _IMPACT, "impact chain status")
    _decimal_string(value.get("cost_usd")); _nonnegative_int(value.get("request_count"))
    _nullable_nonnegative_int(value.get("duration_ms"))
    usage = value.get("usage")
    usage_keys = {
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    }
    if not isinstance(usage, dict) or set(usage) != usage_keys:
        raise ReportError("case usage shape is invalid")
    for item in usage.values():
        _nonnegative_int(item)


def _pair_task(pair_id: str, rows: list[dict[str, Any]]) -> str:
    expected = {
        "C01": "terminal-bench/sqlite-db-truncate",
        "C02": "terminal-bench/headless-terminal",
        "C03": "terminal-bench/extract-elf",
    }[pair_id]
    if any(row["task_id"] != expected for row in rows):
        raise ReportError("paired task identity differs")
    return expected


def _write_or_verify(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ReportError("case output drifted")
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _pair_id(value: object) -> str:
    if not isinstance(value, str) or _PAIR_ID.fullmatch(value) is None:
        raise ReportError("pair identity is invalid")
    return value


def _slot_id(value: object) -> str:
    if not isinstance(value, str) or _SLOT_ID.fullmatch(value) is None:
        raise ReportError("slot identity is invalid")
    return value


def _run_id(value: object) -> str:
    if not isinstance(value, str) or _RUN_ID.fullmatch(value) is None:
        raise ReportError("run identity is invalid")
    return value


def _task_id(value: object) -> str:
    allowed = {
        "terminal-bench/sqlite-db-truncate",
        "terminal-bench/headless-terminal",
        "terminal-bench/extract-elf",
    }
    return _choice(value, allowed, "task identity")


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReportError(f"{label} is invalid")
    return value


def _choice(value: object, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ReportError(f"{label} is invalid")
    return value


def _exact_string(value: object, expected: str, label: str) -> str:
    if value != expected:
        raise ReportError(f"{label} differs")
    return expected


def _decimal_string(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?", value) is None:
        raise ReportError("cost is invalid")
    return value


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReportError("count is invalid")
    return value


def _nullable_nonnegative_int(value: object) -> int | None:
    return None if value is None else _nonnegative_int(value)


def _count_map(value: object, keys: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != keys:
        raise ReportError("overview count map is invalid")
    for item in value.values():
        _nonnegative_int(item)
