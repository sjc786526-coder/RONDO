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
    "root_woken",
)


@dataclass(frozen=True)
class CollaborationVerdict:
    passed: bool
    predicates: dict[str, bool]
    reasons: tuple[str, ...]
    event_id: str | None = None
    #: Tools that produced team-shaped payloads without being `team_inspect` or
    #: `wait_agent`. Never judged; kept so a failing gate 1 can be explained
    #: (either the model fabricated evidence, or the wire shape moved).
    ignored_evidence: tuple[str, ...] = ()


def evaluate_collaboration(
    dump: Mapping[str, Any],
    *,
    workspace: Path,
    finding_line: str,
    report_filename: str = "TEAM_REPORT.md",
    max_members: int = 1,
    jsonl: str | None = None,
    trace: Any | None = None,
) -> CollaborationVerdict:
    """Judge gate 1 from harness-owned team evidence plus the workspace artifact.

    ``dump`` is a ``team_inspect`` dump page. When ``trace`` is provided it and
    the captured ``jsonl`` are the only evidence: a caller-supplied dump cannot
    leak a fabricated collaboration in. Rows come from the frozen binary's own
    tool-dispatch record and are attributed to the tool the registry actually
    ran, and each dispatch is tied back to a model call the capture contains;
    see ``collect_gate1_evidence``.
    Event membership follows dump order: Version / VersionFact / Route rows
    after an Event belong to that Event until the next Event or a non-nested
    row. That matches the real dump schema, which does not put ``event_id`` on
    Version rows.

    Event-local predicates must all hold on **one** Event. ``root_resolved``
    requires a member-authored Version on that Event. ``root_woken`` requires a
    completed Root-thread ``wait_agent`` whose returned result carries the
    TeamActivity marker. A member wait or a store-only wake log cannot satisfy
    the predicate.
    """

    if trace is not None:
        from .collect import collect_gate1_evidence

        dump = collect_gate1_evidence(
            jsonl or "",
            trace,
            required_inspect_actions=("dump", "log"),
        )

    entries = dump.get("entries")
    rows = tuple(entries) if isinstance(entries, list) else ()
    participants = [row for row in rows if _entry(row) == "participant"]
    members = _members(participants)
    events = _events_from_dump(rows)
    member_labels = {str(row.get("label")) for row in members}
    member_threads = {
        str(row.get("thread_id")): str(row.get("label"))
        for row in members
        if row.get("thread_id") and row.get("label")
    }
    evidence_calls = dump.get("team_evidence_calls")
    calls = tuple(evidence_calls) if isinstance(evidence_calls, list) else ()
    publish_items = dump.get("team_publish_calls")
    publish_calls = tuple(publish_items) if isinstance(publish_items, list) else ()
    route_items = dump.get("team_route_calls")
    route_calls = tuple(route_items) if isinstance(route_items, list) else ()
    update_items = dump.get("team_update_calls")
    update_calls = tuple(update_items) if isinstance(update_items, list) else ()
    wait_items = dump.get("wait_calls")
    wait_calls = tuple(wait_items) if isinstance(wait_items, list) else ()
    log_items = dump.get("log")
    log_entries = tuple(log_items) if isinstance(log_items, list) else ()
    root_thread_id = str(dump.get("root_thread_id") or "")

    spawn_ok = 1 <= len(members) <= max_members
    local_flags = [
        _event_flags(
            event,
            member_labels,
            member_threads,
            calls,
            publish_calls,
            route_calls,
            update_calls,
            wait_calls,
            log_entries,
            root_thread_id,
            finding_line,
        )
        for event in events
    ]
    best_index = _best_event_index(local_flags)
    best_flags = (
        local_flags[best_index]
        if best_index is not None
        else {name: False for name in _EVENT_LOCAL}
    )
    event_id = events[best_index]["event_id"] if best_index is not None else None
    same_event = bool(local_flags) and all(best_flags.values())
    predicates = {
        "spawn_member": spawn_ok,
        **best_flags,
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
    ignored = dump.get("unattributed")
    passed = not reasons
    return CollaborationVerdict(
        passed=passed,
        predicates=predicates,
        reasons=tuple(reasons),
        event_id=event_id if same_event else None,
        ignored_evidence=tuple(str(item) for item in ignored)
        if isinstance(ignored, list)
        else (),
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
    event: Mapping[str, Any],
    member_labels: set[str],
    member_threads: Mapping[str, str],
    evidence_calls: tuple[object, ...],
    publish_calls: tuple[object, ...],
    route_calls: tuple[object, ...],
    update_calls: tuple[object, ...],
    wait_calls: tuple[object, ...],
    log_entries: tuple[object, ...],
    root_thread_id: str,
    finding_line: str,
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
    root_versions = [
        row for row in versions if _is_root_label(str(row.get("author") or ""))
    ]
    facts_by_version: dict[str, set[str]] = {}
    for row in facts:
        version_id = str(row.get("version_id") or "")
        fact_id = str(row.get("fact_id") or "")
        if version_id in member_ids and fact_id:
            facts_by_version.setdefault(version_id, set()).add(fact_id)
    resolved_member_ids = {
        str(row.get("version_id"))
        for row in member_versions
        if row.get("version_id") and row.get("root_state") == "resolved"
    }
    member_route_ids = {
        str(row.get("route_id"))
        for row in routes
        if row.get("route_id") and str(row.get("target") or "") in member_labels
    }
    protocol = _valid_member_protocol(
        event_id=str(event.get("event_id") or ""),
        versions=versions,
        member_threads=member_threads,
        facts_by_version=facts_by_version,
        resolved_member_ids=resolved_member_ids,
        member_route_ids=member_route_ids,
        publish_calls=publish_calls,
        route_calls=route_calls,
        update_calls=update_calls,
        evidence_calls=evidence_calls,
        wait_calls=wait_calls,
        log_entries=log_entries,
        root_thread_id=root_thread_id,
        finding_line=finding_line,
    )
    return {
        "event_with_two_versions": (
            len(versions) >= 3
            and bool(root_versions)
            and len(member_versions) >= 2
        ),
        "two_authors": len(authors) >= 2 and bool(root_versions) and bool(member_versions),
        "team_route": protocol["route"],
        "team_evidence": protocol["evidence"],
        "root_resolved": protocol["resolved"],
        "root_woken": protocol["woken"],
    }


def _valid_member_protocol(
    *,
    event_id: str,
    versions: list[dict[str, Any]],
    member_threads: Mapping[str, str],
    facts_by_version: Mapping[str, set[str]],
    resolved_member_ids: set[str],
    member_route_ids: set[str],
    publish_calls: tuple[object, ...],
    route_calls: tuple[object, ...],
    update_calls: tuple[object, ...],
    evidence_calls: tuple[object, ...],
    wait_calls: tuple[object, ...],
    log_entries: tuple[object, ...],
    root_thread_id: str,
    finding_line: str,
) -> dict[str, bool]:
    version_authors = {
        str(row.get("version_id")): str(row.get("author") or "")
        for row in versions
        if row.get("version_id")
    }
    publishes = [call for call in publish_calls if _completed_result(call)]
    routes = [call for call in route_calls if _completed_result(call)]
    updates = [call for call in update_calls if _completed_result(call)]
    evidences = [call for call in evidence_calls if _completed_result(call)]
    waits = [call for call in wait_calls if _completed_result(call)]
    for first in publishes:
        assert isinstance(first, dict)
        member = member_threads.get(str(first.get("thread_id") or ""))
        first_result = first["result"]
        if member is None or first_result.get("event_id") != event_id:
            continue
        first_version = str(first_result.get("version_id") or "")
        if version_authors.get(first_version) != member:
            continue
        first_refs = {
            str(item) for item in first_result.get("evidence_refs") or () if item
        }
        first_revision = _matching_log_revision(
            log_entries,
            kind="publish",
            target=first_version,
            actor=member,
            actor_thread_id=str(first.get("thread_id") or ""),
            wake_target="/root",
            wake_thread_id=root_thread_id,
            wake_rule="member_publish",
        )
        if not first_revision:
            continue
        for wait in waits:
            assert isinstance(wait, dict)
            wait_result = wait["result"]
            if (
                not root_thread_id
                or wait.get("thread_id") != root_thread_id
                or WAIT_TEAM_ACTIVITY_MARK
                not in str(wait_result.get("message") or "")
                or not (
                    _seq(wait)
                    < _seq(first)
                    < _end_seq(first)
                    < _end_seq(wait)
                )
            ):
                continue
            for root_publish in publishes:
                assert isinstance(root_publish, dict)
                root_result = root_publish["result"]
                root_version = str(root_result.get("version_id") or "")
                if (
                    root_publish.get("thread_id") != root_thread_id
                    or root_result.get("event_id") != event_id
                    or not _is_root_label(version_authors.get(root_version, ""))
                    or _end_seq(wait) >= _seq(root_publish)
                ):
                    continue
                root_revision = _matching_log_revision(
                    log_entries,
                    kind="publish",
                    target=root_version,
                    actor="/root",
                    actor_thread_id=root_thread_id,
                )
                if root_revision <= first_revision:
                    continue
                for route in routes:
                    assert isinstance(route, dict)
                    route_result = route["result"]
                    if (
                        route.get("thread_id") != root_thread_id
                        or _end_seq(root_publish) >= _seq(route)
                        or route_result.get("event_id") != event_id
                        or str(route_result.get("route_id") or "")
                        not in member_route_ids
                        or str(route_result.get("target") or "")
                        != str(first.get("thread_id") or "")
                        or route_result.get("delivery") != "delivered"
                    ):
                        continue
                    route_revision = _matching_log_revision(
                        log_entries,
                        kind="route",
                        target=str(route_result.get("route_id") or ""),
                        actor="/root",
                        actor_thread_id=root_thread_id,
                    )
                    if route_revision <= root_revision:
                        continue
                    for evidence in evidences:
                        assert isinstance(evidence, dict)
                        if (
                            evidence.get("thread_id") != first.get("thread_id")
                            or _end_seq(route) >= _seq(evidence)
                        ):
                            continue
                        if not _valid_member_evidence_call(
                            evidence,
                            member=member,
                            member_fact_ids=facts_by_version.get(first_version, set())
                            & first_refs,
                            finding_line=finding_line,
                        ):
                            continue
                        for second in publishes:
                            assert isinstance(second, dict)
                            second_result = second["result"]
                            second_version = str(
                                second_result.get("version_id") or ""
                            )
                            if (
                                second is first
                                or second.get("thread_id")
                                != first.get("thread_id")
                                or second_result.get("event_id") != event_id
                                or version_authors.get(second_version) != member
                                or second_version == first_version
                                or _end_seq(evidence) >= _seq(second)
                            ):
                                continue
                            second_revision = _matching_log_revision(
                                log_entries,
                                kind="publish",
                                target=second_version,
                                actor=member,
                                actor_thread_id=str(second.get("thread_id") or ""),
                                wake_target="/root",
                                wake_thread_id=root_thread_id,
                                wake_rule="member_publish",
                            )
                            if second_revision <= route_revision:
                                continue
                            for update in updates:
                                assert isinstance(update, dict)
                                resolved_version = _resolved_version_id(
                                    update,
                                    member_version_ids=resolved_member_ids,
                                )
                                update_revision = _matching_log_revision(
                                    log_entries,
                                    kind="set_root_state",
                                    target=resolved_version or "",
                                    actor="/root",
                                    actor_thread_id=root_thread_id,
                                )
                                if (
                                    update.get("thread_id") == root_thread_id
                                    and resolved_version is not None
                                    and _end_seq(second) < _seq(update)
                                    and update_revision > second_revision
                                ):
                                    return {
                                        "route": True,
                                        "evidence": True,
                                        "woken": True,
                                        "resolved": True,
                                    }
    return {
        "route": False,
        "evidence": False,
        "woken": False,
        "resolved": False,
    }


def _completed_result(call: object) -> bool:
    return (
        isinstance(call, dict)
        and call.get("status") == "completed"
        and isinstance(call.get("result"), dict)
    )


def _resolved_version_id(
    call: Mapping[str, Any], *, member_version_ids: set[str]
) -> str | None:
    arguments = call.get("arguments")
    result = call.get("result")
    if not isinstance(arguments, dict) or not isinstance(result, dict):
        return None
    targets = arguments.get("targets")
    updated = result.get("updated")
    if not isinstance(targets, list) or not isinstance(updated, list):
        return None
    requested = [item for item in targets if isinstance(item, dict)]
    returned = [item for item in updated if isinstance(item, dict)]
    if len(requested) != 1 or len(returned) != 1:
        return None
    requested_id = str(requested[0].get("version_id") or "")
    returned_id = str(returned[0].get("version_id") or "")
    if (
        requested_id
        and requested_id == returned_id
        and requested_id in member_version_ids
        and requested[0].get("set_root_state") == "resolved"
        and returned[0].get("root_state") == "resolved"
    ):
        return requested_id
    return None


def _matching_log_revision(
    entries: tuple[object, ...],
    *,
    kind: str,
    target: str,
    actor: str,
    actor_thread_id: str,
    wake_target: str | None = None,
    wake_thread_id: str | None = None,
    wake_rule: str | None = None,
) -> int:
    matches: list[Mapping[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if (
            entry.get("kind") != kind
            or str(entry.get("target") or "") != target
            or str(entry.get("actor_thread_id") or "") != actor_thread_id
            or str(entry.get("actor") or "") != actor
        ):
            continue
        if wake_target is not None:
            wake = entry.get("wake")
            if not isinstance(wake, dict) or (
                wake.get("decision") != "signalled"
                or wake.get("target") != wake_target
                or wake.get("target_thread_id") != wake_thread_id
                or wake.get("rule") != wake_rule
            ):
                continue
        matches.append(entry)
    if len(matches) != 1:
        return 0
    return _as_int(matches[0].get("revision"))


def _seq(call: Mapping[str, Any]) -> int:
    return _as_int(call.get("seq"))


def _end_seq(call: Mapping[str, Any]) -> int:
    return _as_int(call.get("end_seq"))


def _valid_member_evidence_call(
    call: Mapping[str, Any],
    *,
    member: str,
    member_fact_ids: set[str],
    finding_line: str,
) -> bool:
    arguments = call.get("arguments")
    result = call.get("result")
    if not isinstance(arguments, dict) or not isinstance(result, dict):
        return False
    fact_id = str(arguments.get("fact_id") or "")
    observation = result.get("observation")
    return (
        fact_id in member_fact_ids
        and str(result.get("fact_id") or "") == fact_id
        and result.get("availability") == "available"
        and result.get("producer") == member
        and result.get("tool") == "exec"
        and result.get("category") == "tool_result_success"
        and result.get("truncated") is False
        and isinstance(observation, str)
        and bool(observation.strip())
        and finding_line in observation
    )


def _best_event_index(local_flags: list[dict[str, bool]]) -> int | None:
    if not local_flags:
        return None
    return max(
        range(len(local_flags)),
        key=lambda index: sum(local_flags[index].values()),
    )


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
