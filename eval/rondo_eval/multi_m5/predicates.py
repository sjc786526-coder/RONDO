"""Mechanical collaboration predicates for Multi M-5 gate 1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


REQUIRED_PREDICATE_IDS = (
    "spawn_member",
    "event_with_two_versions",
    "two_authors",
    "team_route",
    "team_evidence",
    "root_resolved",
    "root_woken",
)
WAIT_TEAM_ACTIVITY_MARK = (
    "Wait completed: the team world state changed. The current active view is in this request."
)
_ROOT_LABELS = {"/root", "root"}
_EVENT_LOCAL = (
    "event_with_two_versions",
    "two_authors",
    "team_route",
    "team_evidence",
    "root_resolved",
)


@dataclass(frozen=True)
class CollaborationVerdict:
    passed: bool
    predicates: dict[str, bool]
    reasons: tuple[str, ...]
    event_id: str | None = None


def evaluate_collaboration(
    dump: Mapping[str, Any],
    *,
    workspace: Path,
    finding_line: str,
    report_filename: str = "TEAM_REPORT.md",
    max_members: int = 1,
    jsonl: str | None = None,
) -> CollaborationVerdict:
    """Judge gate 1 from harness-owned team evidence plus the workspace artifact.

    ``dump`` is a ``team_inspect`` dump page. When ``jsonl`` is provided it is
    the only evidence: caller dump cannot leak a fabricated collaboration in.
    Event membership follows dump order: Version / VersionFact / Route rows
    after an Event belong to that Event until the next Event or a non-nested
    row. That matches the real dump schema, which does not put ``event_id`` on
    Version rows.

    Event-local predicates must all hold on **one** Event. ``root_resolved``
    requires a member-authored Version on that Event. ``root_woken`` requires a
    change-log ``signalled`` wake targeting Root, or a ``wait_agent`` TeamActivity
    message from JSONL tool output.
    """

    if jsonl is not None:
        from .collect import collect_gate1_evidence

        dump = collect_gate1_evidence(jsonl)

    entries = dump.get("entries")
    rows = tuple(entries) if isinstance(entries, list) else ()
    participants = [row for row in rows if _entry(row) == "participant"]
    members = _members(participants)
    events = _events_from_dump(rows)
    member_labels = {str(row.get("label")) for row in members}

    spawn_ok = 1 <= len(members) <= max_members
    local_flags = [_event_flags(event, member_labels) for event in events]
    best_index = _best_event_index(local_flags)
    best_flags = (
        local_flags[best_index]
        if best_index is not None
        else {name: False for name in _EVENT_LOCAL}
    )
    event_id = events[best_index]["event_id"] if best_index is not None else None
    same_event = bool(local_flags) and all(best_flags.values())
    woken = _root_was_woken(dump)
    predicates = {
        "spawn_member": spawn_ok,
        **best_flags,
        "root_woken": woken,
    }

    report = workspace / report_filename
    report_ok = report.is_file() and not report.is_symlink()
    finding_ok = False
    if report_ok:
        finding_ok = finding_line in report.read_text("utf-8")
    reasons: list[str] = []
    for name, ok in predicates.items():
        if not ok:
            reasons.append(f"predicate:{name}")
    if not report_ok:
        reasons.append("task:report_missing")
    elif not finding_ok:
        reasons.append("task:finding_missing")
    passed = not reasons
    return CollaborationVerdict(
        passed=passed,
        predicates=predicates,
        reasons=tuple(reasons),
        event_id=event_id if same_event else None,
    )


def _members(participants: list[object]) -> list[dict[str, Any]]:
    members = [
        row
        for row in participants
        if isinstance(row, dict)
        and not _is_root_label(str(row.get("label") or ""))
        and str(row.get("role") or "") != "root"
    ]
    if members:
        return members
    return [
        row
        for row in participants
        if isinstance(row, dict) and str(row.get("label") or "").startswith("/root/")
    ]


def _events_from_dump(rows: tuple[object, ...]) -> list[dict[str, Any]]:
    """Group dump rows the way ``TeamStore::dump_entries`` emits them."""

    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        kind = _entry(row)
        if not isinstance(row, dict):
            continue
        if kind == "event":
            event_id = row.get("event_id")
            current = {
                "event_id": event_id if isinstance(event_id, str) else "",
                "versions": [],
                "facts": [],
                "routes": [],
            }
            events.append(current)
            continue
        if current is None:
            continue
        if kind == "version":
            current["versions"].append(row)
        elif kind == "version_fact":
            current["facts"].append(row)
        elif kind == "route":
            current["routes"].append(row)
        elif kind in {
            "participant",
            "fact",
            "visibility",
            "activity",
            "publication",
        }:
            current = None
    return events


def _event_flags(
    event: Mapping[str, Any], member_labels: set[str]
) -> dict[str, bool]:
    versions = [row for row in event["versions"] if isinstance(row, dict)]
    routes = [row for row in event["routes"] if isinstance(row, dict)]
    facts = [row for row in event["facts"] if isinstance(row, dict)]
    authors = {
        str(row.get("author"))
        for row in versions
        if row.get("author")
    }
    member_versions = [
        row for row in versions if str(row.get("author") or "") in member_labels
    ]
    member_ids = {
        str(row.get("version_id"))
        for row in member_versions
        if row.get("version_id")
    }
    evidence_on_member = any(
        _as_int(row.get("fact_ref_count")) >= 1 for row in member_versions
    ) or any(
        isinstance(row, dict) and str(row.get("version_id") or "") in member_ids
        for row in facts
    )
    route_to_member = any(
        str(row.get("target") or "") in member_labels for row in routes
    )
    member_resolved = any(
        str(row.get("root_state") or "") == "resolved" for row in member_versions
    )
    return {
        "event_with_two_versions": len(versions) >= 2,
        "two_authors": len(authors) >= 2 and bool(member_versions),
        "team_route": route_to_member,
        "team_evidence": evidence_on_member,
        "root_resolved": member_resolved,
    }


def _best_event_index(local_flags: list[dict[str, bool]]) -> int | None:
    if not local_flags:
        return None
    return max(
        range(len(local_flags)),
        key=lambda index: sum(local_flags[index].values()),
    )


def _root_was_woken(dump: Mapping[str, Any]) -> bool:
    log = dump.get("log") or dump.get("change_log") or ()
    if isinstance(log, list):
        for row in log:
            if not isinstance(row, dict):
                continue
            wake = row.get("wake")
            if not isinstance(wake, dict):
                continue
            if str(wake.get("decision") or "") != "signalled":
                continue
            if _is_root_label(str(wake.get("target") or "")):
                return True
    signals = dump.get("jsonl_signals") or ()
    if isinstance(signals, list):
        return any(WAIT_TEAM_ACTIVITY_MARK in str(item) for item in signals)
    return False


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _is_root_label(label: str) -> bool:
    return label in _ROOT_LABELS


def _entry(row: object) -> str:
    if isinstance(row, dict) and isinstance(row.get("entry"), str):
        return row["entry"]
    return ""
