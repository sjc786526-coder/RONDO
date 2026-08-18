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
)


@dataclass(frozen=True)
class CollaborationVerdict:
    passed: bool
    predicates: dict[str, bool]
    reasons: tuple[str, ...]


def evaluate_collaboration(
    dump: Mapping[str, Any],
    *,
    workspace: Path,
    finding_line: str,
    report_filename: str = "TEAM_REPORT.md",
    max_members: int = 1,
) -> CollaborationVerdict:
    """Judge gate 1 from a team dump plus the workspace artifact.

    ``dump`` is a ``team_inspect`` dump page (``entries`` tagged by ``entry``).
    Task completion (report exists and quotes the finding) is required in
    addition to the six collaboration predicates. ``spawn_member`` requires
    at least one member and no more than ``max_members``.
    """

    entries = dump.get("entries")
    rows = tuple(entries) if isinstance(entries, list) else ()
    participants = [row for row in rows if _entry(row) == "participant"]
    events = [row for row in rows if _entry(row) == "event"]
    versions = [row for row in rows if _entry(row) == "version"]
    routes = [row for row in rows if _entry(row) == "route"]
    facts = [row for row in rows if _entry(row) in {"version_fact", "fact"}]

    members = [
        row
        for row in participants
        if isinstance(row, dict) and str(row.get("label") or "") not in {"", "/root", "root"}
        and str(row.get("role") or "") != "root"
    ]
    if not members:
        members = [
            row
            for row in participants
            if isinstance(row, dict) and str(row.get("label") or "").startswith("/root/")
        ]

    two_versions = any(
        isinstance(row, dict) and int(row.get("version_count") or 0) >= 2 for row in events
    )
    if not two_versions:
        by_event: dict[str, int] = {}
        for row in versions:
            if not isinstance(row, dict):
                continue
            event_id = row.get("event_id")
            if isinstance(event_id, str) and event_id:
                by_event[event_id] = by_event.get(event_id, 0) + 1
        two_versions = any(count >= 2 for count in by_event.values())
    authors = {
        str(row.get("author"))
        for row in versions
        if isinstance(row, dict) and row.get("author")
    }
    evidence = any(
        isinstance(row, dict) and int(row.get("fact_ref_count") or 0) >= 1 for row in versions
    ) or bool(facts)
    resolved = any(
        isinstance(row, dict) and str(row.get("root_state") or "") == "resolved"
        for row in versions
    )

    predicates = {
        "spawn_member": 1 <= len(members) <= max_members,
        "event_with_two_versions": two_versions,
        "two_authors": len(authors) >= 2,
        "team_route": bool(routes),
        "team_evidence": evidence,
        "root_resolved": resolved,
    }
    report = workspace / report_filename
    report_ok = report.is_file() and not report.is_symlink()
    finding_ok = False
    if report_ok:
        text = report.read_text("utf-8")
        finding_ok = finding_line in text
    reasons: list[str] = []
    for name, ok in predicates.items():
        if not ok:
            reasons.append(f"predicate:{name}")
    if not report_ok:
        reasons.append("task:report_missing")
    elif not finding_ok:
        reasons.append("task:finding_missing")
    passed = (not reasons) and all(predicates.values()) and report_ok and finding_ok
    return CollaborationVerdict(passed=passed, predicates=predicates, reasons=tuple(reasons))


def _entry(row: object) -> str:
    if isinstance(row, dict) and isinstance(row.get("entry"), str):
        return row["entry"]
    return ""
