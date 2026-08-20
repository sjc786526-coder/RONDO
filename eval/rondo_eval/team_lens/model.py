"""The normalized, body-free Team Lens data contract."""

import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
PRODUCTS = {"codex", "rondo-multi"}
CAPABILITY_STATUSES = {"available", "partial", "unsupported", "not_applicable"}
EXECUTION_STATUSES = {"running", "completed", "failed", "cancelled", "aborted", "unknown"}
CAPABILITY_NAMES = (
    "agents",
    "turns",
    "inferences",
    "usage",
    "tools",
    "terminal",
    "interactions",
    "timing",
    "team_revisions",
    "team_projections",
    "team_events_versions",
    "team_routes",
    "team_facts",
)
MAX_TEAM_VIEW_BYTES = 32 * 1024 * 1024

_TOP_LEVEL_KEYS = {
    "schema_version",
    "source",
    "availability",
    "agents",
    "turns",
    "inferences",
    "tools",
    "terminal",
    "interactions",
    "team",
    "summary",
}
_SOURCE_KEYS = {"product", "trace_schema", "trace_id", "rollout_id", "root_thread_id"}
_TRACE_SCHEMA_KEYS = {"manifest_version", "raw_event_versions", "reduced_state_version"}
_CAPABILITY_KEYS = {"status", "reason_codes"}
_ITEM_KEYS = {
    "agents": {
        "agent_id",
        "agent_path",
        "parent_agent_id",
        "role",
        "started_seq",
        "started_at_unix_ms",
        "ended_seq",
        "ended_at_unix_ms",
        "status",
    },
    "turns": {
        "turn_id",
        "agent_id",
        "started_seq",
        "started_at_unix_ms",
        "ended_seq",
        "ended_at_unix_ms",
        "status",
    },
    "inferences": {
        "inference_id",
        "agent_id",
        "turn_id",
        "model",
        "provider",
        "started_seq",
        "started_at_unix_ms",
        "ended_seq",
        "ended_at_unix_ms",
        "status",
        "usage",
    },
    "tools": {
        "tool_id",
        "agent_id",
        "turn_id",
        "name",
        "namespace",
        "requester",
        "kind",
        "started_seq",
        "started_at_unix_ms",
        "ended_seq",
        "ended_at_unix_ms",
        "status",
    },
    "terminal": {
        "operation_id",
        "terminal_id",
        "tool_id",
        "agent_id",
        "kind",
        "started_seq",
        "started_at_unix_ms",
        "ended_seq",
        "ended_at_unix_ms",
        "status",
        "exit_code",
        "duration_ms",
    },
    "interactions": {
        "interaction_id",
        "kind",
        "source_agent_id",
        "target_agent_id",
        "tool_id",
        "started_seq",
        "started_at_unix_ms",
        "ended_seq",
        "ended_at_unix_ms",
        "status",
    },
}
_USAGE_KEYS = {
    "input_tokens",
    "cached_input_tokens",
    "cache_write_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
}
_TEAM_KEYS = {"revisions", "projections", "events", "versions", "routes", "facts", "attention"}
_TEAM_ITEM_KEYS = {
    "revisions": {"revision", "tool_id", "seq"},
    "projections": {"inference_id", "team_instance", "revision", "seq"},
    "events": {
        "event_id",
        "created_by_agent_id",
        "version_ids",
        "route_ids",
        "first_seq",
        "last_seq",
    },
    "versions": {
        "version_id",
        "event_id",
        "author_agent_id",
        "revision",
        "producer_state",
        "root_state",
        "retired",
        "authored_on_stale_view",
        "fact_ids",
        "fact_ref_count",
        "first_seq",
        "last_seq",
    },
    "routes": {
        "route_id",
        "event_id",
        "target_agent_id",
        "duty",
        "delivery",
        "revision",
        "first_seq",
        "last_seq",
    },
    "facts": {
        "fact_id",
        "producer_agent_id",
        "category",
        "tool",
        "availability",
        "version_ids",
        "first_seq",
        "last_seq",
    },
    "attention": {
        "agent_id",
        "event_id",
        "visible",
        "active",
        "reasons",
        "revision",
        "seq",
    },
}
_SUMMARY_KEYS = {
    "agent_count",
    "turn_count",
    "inference_count",
    "tool_count",
    "terminal_count",
    "interaction_count",
    "wait_count",
    "team_event_count",
    "team_version_count",
    "team_route_count",
    "team_fact_count",
    "started_at_unix_ms",
    "ended_at_unix_ms",
    "duration_ms",
    "usage",
}


class TeamViewError(ValueError):
    """Raised when normalized input does not match the Team View contract."""


def capability(status: str, *reason_codes: str) -> dict[str, Any]:
    """Build one deterministic availability row."""

    if status not in CAPABILITY_STATUSES:
        raise TeamViewError("invalid capability status")
    reasons = sorted(set(reason_codes))
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise TeamViewError("invalid capability reason code")
    return {"status": status, "reason_codes": reasons}


def dump_team_view(view: dict[str, Any]) -> bytes:
    """Serialize a validated Team View deterministically."""

    validate_team_view(view)
    return (
        json.dumps(view, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", ": "))
        + "\n"
    ).encode("utf-8")


def load_team_view(path: Path) -> dict[str, Any]:
    """Read only a normalized Team View JSON file."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise TeamViewError("team view input is not a regular file")
    if source.stat().st_size > MAX_TEAM_VIEW_BYTES:
        raise TeamViewError("team view input is implausibly large")
    try:
        value = json.loads(source.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TeamViewError("team view input is unreadable") from exc
    if not isinstance(value, dict):
        raise TeamViewError("team view input is not an object")
    validate_team_view(value)
    return value


def validate_team_view(view: dict[str, Any]) -> None:
    """Fail closed on unknown fields before JSON or HTML rendering."""

    _exact_keys(view, _TOP_LEVEL_KEYS, "team view")
    if view.get("schema_version") != SCHEMA_VERSION:
        raise TeamViewError("unsupported team view schema")

    source = _dict(view.get("source"), "source")
    _exact_keys(source, _SOURCE_KEYS, "source")
    if source.get("product") not in PRODUCTS:
        raise TeamViewError("unsupported source product")
    for key in ("trace_id", "rollout_id", "root_thread_id"):
        _nonempty_string(source.get(key), f"source {key}")
    trace_schema = _dict(source.get("trace_schema"), "trace schema")
    _exact_keys(trace_schema, _TRACE_SCHEMA_KEYS, "trace schema")
    _integer(trace_schema.get("manifest_version"), "manifest version", minimum=1)
    versions = _list(trace_schema.get("raw_event_versions"), "raw event versions")
    if not versions:
        raise TeamViewError("raw event versions are empty")
    for version in versions:
        _integer(version, "raw event version", minimum=1)
    if trace_schema.get("reduced_state_version") is not None:
        _integer(trace_schema["reduced_state_version"], "reduced state version", minimum=1)

    availability = _dict(view.get("availability"), "availability")
    _exact_keys(availability, set(CAPABILITY_NAMES), "availability")
    for name in CAPABILITY_NAMES:
        row = _dict(availability.get(name), f"availability {name}")
        _exact_keys(row, _CAPABILITY_KEYS, f"availability {name}")
        if row.get("status") not in CAPABILITY_STATUSES:
            raise TeamViewError("invalid availability status")
        reasons = _list(row.get("reason_codes"), "availability reasons")
        for reason in reasons:
            _nonempty_string(reason, "availability reason")
        if row["status"] == "available" and reasons:
            raise TeamViewError("available capability has reason codes")
        if row["status"] != "available" and not reasons:
            raise TeamViewError("degraded capability has no reason code")

    normalized_rows: dict[str, list[dict[str, Any]]] = {}
    for collection, keys in _ITEM_KEYS.items():
        rows = _list(view.get(collection), collection)
        normalized_rows[collection] = []
        for row in rows:
            item = _dict(row, collection)
            _exact_keys(item, keys, collection)
            normalized_rows[collection].append(item)
    _validate_common_availability(normalized_rows, availability)
    common_ids = _validate_common_rows(normalized_rows, source)
    for inference in normalized_rows["inferences"]:
        usage = inference.get("usage")
        if usage is not None:
            _validate_usage(usage)
    if availability["usage"]["status"] == "available" and any(
        inference["usage"] is None for inference in normalized_rows["inferences"]
    ):
        raise TeamViewError("usage capability contradicts missing inference usage")

    product = source["product"]
    team = view.get("team")
    if product == "codex":
        if team is not None:
            raise TeamViewError("codex team state must be null")
        for name in CAPABILITY_NAMES:
            if name.startswith("team_") and availability[name]["status"] != "not_applicable":
                raise TeamViewError("codex team capability must be not applicable")
    else:
        team_object = _dict(team, "team")
        _exact_keys(team_object, _TEAM_KEYS, "team")
        team_rows: dict[str, list[dict[str, Any]]] = {}
        for collection, keys in _TEAM_ITEM_KEYS.items():
            rows = _list(team_object.get(collection), f"team {collection}")
            team_rows[collection] = []
            for row in rows:
                item = _dict(row, f"team {collection}")
                _exact_keys(item, keys, f"team {collection}")
                team_rows[collection].append(item)
        _validate_team_rows(team_rows, common_ids)
        _validate_team_availability(team_rows, availability)

    summary = _dict(view.get("summary"), "summary")
    _exact_keys(summary, _SUMMARY_KEYS, "summary")
    _validate_usage(summary.get("usage"))
    _validate_summary(summary, normalized_rows, team)


def _validate_common_rows(
    rows: dict[str, list[dict[str, Any]]], source: dict[str, Any]
) -> dict[str, set[str]]:
    agent_ids = _unique_ids(rows["agents"], "agent_id", "agent")
    agent_parents = {agent["agent_id"]: agent["parent_agent_id"] for agent in rows["agents"]}
    agent_roles = {agent["agent_id"]: agent["role"] for agent in rows["agents"]}
    if source["root_thread_id"] not in agent_ids:
        raise TeamViewError("source root thread is not an agent")
    for agent in rows["agents"]:
        _nonempty_string(agent["agent_path"], "agent path")
        parent = _optional_string(agent["parent_agent_id"], "agent parent")
        if parent is not None and parent not in agent_ids:
            raise TeamViewError("agent parent is unknown")
        if agent["role"] not in {"root", "spawned"}:
            raise TeamViewError("agent role is invalid")
        if (agent["agent_id"] == source["root_thread_id"]) != (agent["role"] == "root"):
            raise TeamViewError("agent root identity and role disagree")
        if agent["role"] == "root" and parent is not None:
            raise TeamViewError("root agent has a parent")
        _validate_window(agent)

    turn_ids = _unique_ids(rows["turns"], "turn_id", "turn")
    turn_owners = {turn["turn_id"]: turn["agent_id"] for turn in rows["turns"]}
    for turn in rows["turns"]:
        if _nonempty_string(turn["agent_id"], "turn agent") not in agent_ids:
            raise TeamViewError("turn agent is unknown")
        _validate_window(turn)

    inference_ids = _unique_ids(rows["inferences"], "inference_id", "inference")
    for inference in rows["inferences"]:
        if _nonempty_string(inference["agent_id"], "inference agent") not in agent_ids:
            raise TeamViewError("inference agent is unknown")
        inference_turn = _nonempty_string(inference["turn_id"], "inference turn")
        if inference_turn not in turn_ids:
            raise TeamViewError("inference turn is unknown")
        if turn_owners[inference_turn] != inference["agent_id"]:
            raise TeamViewError("inference agent and turn owner disagree")
        _nonempty_string(inference["model"], "inference model")
        _nonempty_string(inference["provider"], "inference provider")
        _validate_window(inference)

    tool_ids = _unique_ids(rows["tools"], "tool_id", "tool")
    tools_by_id = {tool["tool_id"]: tool for tool in rows["tools"]}
    for tool in rows["tools"]:
        if _nonempty_string(tool["agent_id"], "tool agent") not in agent_ids:
            raise TeamViewError("tool agent is unknown")
        turn_id = _optional_string(tool["turn_id"], "tool turn")
        if turn_id is not None and turn_id not in turn_ids:
            raise TeamViewError("tool turn is unknown")
        if turn_id is not None and turn_owners[turn_id] != tool["agent_id"]:
            raise TeamViewError("tool agent and turn owner disagree")
        _nonempty_string(tool["name"], "tool name")
        _optional_string(tool["namespace"], "tool namespace")
        if tool["requester"] not in {"model", "code_cell"}:
            raise TeamViewError("tool requester is invalid")
        _nonempty_string(tool["kind"], "tool kind")
        _validate_window(tool)

    _unique_ids(rows["terminal"], "operation_id", "terminal operation")
    for terminal in rows["terminal"]:
        _optional_string(terminal["terminal_id"], "terminal id")
        terminal_tool_id = _nonempty_string(terminal["tool_id"], "terminal tool")
        if terminal_tool_id not in tool_ids:
            raise TeamViewError("terminal tool is unknown")
        terminal_agent = _nonempty_string(terminal["agent_id"], "terminal agent")
        if terminal_agent not in agent_ids:
            raise TeamViewError("terminal agent is unknown")
        terminal_kind = _nonempty_string(terminal["kind"], "terminal kind")
        tool = tools_by_id[terminal_tool_id]
        if terminal_agent != tool["agent_id"] or terminal_kind != tool["kind"]:
            raise TeamViewError("terminal and tool ownership disagree")
        _optional_integer(terminal["exit_code"], "terminal exit code")
        _optional_integer(terminal["duration_ms"], "terminal duration", minimum=0)
        _validate_window(terminal)

    _unique_ids(rows["interactions"], "interaction_id", "interaction")
    for interaction in rows["interactions"]:
        _nonempty_string(interaction["kind"], "interaction kind")
        if _nonempty_string(interaction["source_agent_id"], "interaction source") not in agent_ids:
            raise TeamViewError("interaction source is unknown")
        if _nonempty_string(interaction["target_agent_id"], "interaction target") not in agent_ids:
            raise TeamViewError("interaction target is unknown")
        tool_id = _optional_string(interaction["tool_id"], "interaction tool")
        if tool_id is not None and tool_id not in tool_ids:
            raise TeamViewError("interaction tool is unknown")
        if tool_id is not None:
            tool = tools_by_id[tool_id]
            if interaction["source_agent_id"] != tool["agent_id"] or interaction["kind"] != tool["kind"]:
                raise TeamViewError("interaction and tool ownership disagree")
            if interaction["kind"] == "spawn_agent":
                source = interaction["source_agent_id"]
                target = interaction["target_agent_id"]
                parent = agent_parents[target]
                if (
                    source == target
                    or agent_roles[target] != "spawned"
                    or (parent is not None and parent != source)
                ):
                    raise TeamViewError("spawn interaction endpoint disagrees with agent parent")
        elif interaction["kind"] != "agent_result":
            raise TeamViewError("tool-free interaction kind is unsupported")
        else:
            source = interaction["source_agent_id"]
            target = interaction["target_agent_id"]
            parent = agent_parents[source]
            if (
                source == target
                or agent_roles[source] != "spawned"
                or (parent is not None and parent != target)
            ):
                raise TeamViewError("agent result endpoint disagrees with agent parent")
        _validate_window(interaction)
    return {
        "agents": agent_ids,
        "turns": turn_ids,
        "inferences": inference_ids,
        "tools": tool_ids,
    }


def _validate_common_availability(
    rows: dict[str, list[dict[str, Any]]],
    availability: dict[str, dict[str, Any]],
) -> None:
    common_names = (
        "agents",
        "turns",
        "inferences",
        "usage",
        "tools",
        "terminal",
        "interactions",
        "timing",
    )
    for name in common_names:
        if availability[name]["status"] == "not_applicable":
            raise TeamViewError("common capability cannot be not applicable")
    for name in ("agents", "turns", "inferences", "tools", "terminal", "interactions"):
        if availability[name]["status"] == "unsupported" and rows[name]:
            raise TeamViewError("unsupported common capability has normalized data")
    if availability["usage"]["status"] == "unsupported" and any(
        inference["usage"] is not None for inference in rows["inferences"]
    ):
        raise TeamViewError("unsupported usage capability has normalized data")
    if availability["timing"]["status"] == "unsupported" and any(
        rows[name] for name in ("agents", "turns", "inferences", "tools", "terminal", "interactions")
    ):
        raise TeamViewError("unsupported timing capability has normalized data")


def _validate_team_rows(
    rows: dict[str, list[dict[str, Any]]], common_ids: dict[str, set[str]]
) -> None:
    agent_ids = common_ids["agents"]
    event_ids = _unique_ids(rows["events"], "event_id", "team event")
    version_ids = _unique_ids(rows["versions"], "version_id", "team version")
    route_ids = _unique_ids(rows["routes"], "route_id", "team route")
    fact_ids = _unique_ids(rows["facts"], "fact_id", "team fact")

    for revision in rows["revisions"]:
        _integer(revision["revision"], "team revision", minimum=0)
        if _nonempty_string(revision["tool_id"], "team revision tool") not in common_ids["tools"]:
            raise TeamViewError("team revision tool is unknown")
        _integer(revision["seq"], "team revision sequence", minimum=1)
    projection_inferences: set[str] = set()
    for projection in rows["projections"]:
        inference_id = _nonempty_string(projection["inference_id"], "team projection inference")
        if inference_id not in common_ids["inferences"]:
            raise TeamViewError("team projection inference is unknown")
        if inference_id in projection_inferences:
            raise TeamViewError("team projection inference is duplicated")
        projection_inferences.add(inference_id)
        _nonempty_string(projection["team_instance"], "team projection instance")
        _integer(projection["revision"], "team projection revision", minimum=0)
        _integer(projection["seq"], "team projection sequence", minimum=1)
    for event in rows["events"]:
        creator = _optional_string(event["created_by_agent_id"], "event creator")
        if creator is not None and creator not in agent_ids:
            raise TeamViewError("event creator is unknown")
        _string_refs(event["version_ids"], version_ids, "event versions")
        _string_refs(event["route_ids"], route_ids, "event routes")
        _validate_sequence_span(event)
    for version in rows["versions"]:
        event_id = _optional_string(version["event_id"], "version event")
        if event_id is not None and event_id not in event_ids:
            raise TeamViewError("version event is unknown")
        author = _optional_string(version["author_agent_id"], "version author")
        if author is not None and author not in agent_ids:
            raise TeamViewError("version author is unknown")
        _optional_integer(version["revision"], "version revision", minimum=0)
        _optional_string(version["producer_state"], "version producer state")
        _optional_string(version["root_state"], "version root state")
        _optional_boolean(version["retired"], "version retired")
        _optional_boolean(version["authored_on_stale_view"], "version stale flag")
        _string_refs(version["fact_ids"], fact_ids, "version facts")
        _integer(version["fact_ref_count"], "version fact count", minimum=0)
        if version["fact_ref_count"] < len(version["fact_ids"]):
            raise TeamViewError("version fact count is inconsistent")
        _validate_sequence_span(version)
    for route in rows["routes"]:
        event_id = _optional_string(route["event_id"], "route event")
        if event_id is not None and event_id not in event_ids:
            raise TeamViewError("route event is unknown")
        target = _optional_string(route["target_agent_id"], "route target")
        if target is not None and target not in agent_ids:
            raise TeamViewError("route target is unknown")
        _optional_string(route["duty"], "route duty")
        _optional_string(route["delivery"], "route delivery")
        _optional_integer(route["revision"], "route revision", minimum=0)
        _validate_sequence_span(route)
    for fact in rows["facts"]:
        producer = _optional_string(fact["producer_agent_id"], "fact producer")
        if producer is not None and producer not in agent_ids:
            raise TeamViewError("fact producer is unknown")
        _optional_string(fact["category"], "fact category")
        _optional_string(fact["tool"], "fact tool")
        _optional_string(fact["availability"], "fact availability")
        _string_refs(fact["version_ids"], version_ids, "fact versions")
        _validate_sequence_span(fact)
    for attention in rows["attention"]:
        if _nonempty_string(attention["agent_id"], "attention agent") not in agent_ids:
            raise TeamViewError("attention agent is unknown")
        if _nonempty_string(attention["event_id"], "attention event") not in event_ids:
            raise TeamViewError("attention event is unknown")
        _optional_boolean(attention["visible"], "attention visibility")
        _optional_boolean(attention["active"], "attention activity")
        reasons = _list(attention["reasons"], "attention reasons")
        for reason in reasons:
            _nonempty_string(reason, "attention reason")
        _integer(attention["revision"], "attention revision", minimum=0)
        _integer(attention["seq"], "attention sequence", minimum=1)

    events = {row["event_id"]: row for row in rows["events"]}
    versions = {row["version_id"]: row for row in rows["versions"]}
    routes = {row["route_id"]: row for row in rows["routes"]}
    facts = {row["fact_id"]: row for row in rows["facts"]}
    _require_observation_order(rows["events"], "event_id", "team events")
    _require_observation_order(rows["versions"], "version_id", "team versions")
    _require_observation_order(rows["routes"], "route_id", "team routes")
    _require_observation_order(rows["facts"], "fact_id", "team facts")
    for event in rows["events"]:
        _require_relation_order(event["version_ids"], versions, "event versions")
        _require_relation_order(event["route_ids"], routes, "event routes")
        for version_id in event["version_ids"]:
            if versions[version_id]["event_id"] != event["event_id"]:
                raise TeamViewError("event and version relation disagree")
        for route_id in event["route_ids"]:
            if routes[route_id]["event_id"] != event["event_id"]:
                raise TeamViewError("event and route relation disagree")
    for version in rows["versions"]:
        event_id = version["event_id"]
        if event_id is not None and version["version_id"] not in events[event_id]["version_ids"]:
            raise TeamViewError("version and event relation disagree")
        _require_relation_order(version["fact_ids"], facts, "version facts")
        for fact_id in version["fact_ids"]:
            if version["version_id"] not in facts[fact_id]["version_ids"]:
                raise TeamViewError("version and fact relation disagree")
    for route in rows["routes"]:
        event_id = route["event_id"]
        if event_id is not None and route["route_id"] not in events[event_id]["route_ids"]:
            raise TeamViewError("route and event relation disagree")
    for fact in rows["facts"]:
        _require_relation_order(fact["version_ids"], versions, "fact versions")
        for version_id in fact["version_ids"]:
            if fact["fact_id"] not in versions[version_id]["fact_ids"]:
                raise TeamViewError("fact and version relation disagree")


def _validate_team_availability(
    rows: dict[str, list[dict[str, Any]]],
    availability: dict[str, dict[str, Any]],
) -> None:
    for name in (
        "team_revisions",
        "team_projections",
        "team_events_versions",
        "team_routes",
        "team_facts",
    ):
        if availability[name]["status"] == "not_applicable":
            raise TeamViewError("RONDO team capability cannot be not applicable")
    for name in ("team_revisions", "team_events_versions", "team_routes", "team_facts"):
        if availability[name]["status"] == "unsupported":
            raise TeamViewError("RONDO team capability cannot be unsupported")
    if availability["team_projections"]["status"] == "unsupported" and rows["projections"]:
        raise TeamViewError("unsupported team projection capability has normalized data")
    if availability["team_revisions"]["status"] == "available" and not rows["revisions"]:
        raise TeamViewError("team revision capability contradicts empty data")
    if availability["team_events_versions"]["status"] == "available" and any(
        version["event_id"] is None for version in rows["versions"]
    ):
        raise TeamViewError("team event capability contradicts missing relations")
    if availability["team_routes"]["status"] == "available" and any(
        route["event_id"] is None or route["target_agent_id"] is None
        for route in rows["routes"]
    ):
        raise TeamViewError("team route capability contradicts missing relations")
    if availability["team_facts"]["status"] == "available" and any(
        fact["producer_agent_id"] is None
        or fact["category"] is None
        or fact["availability"] is None
        for fact in rows["facts"]
    ):
        raise TeamViewError("team fact capability contradicts missing observations")


def _validate_summary(
    summary: dict[str, Any],
    rows: dict[str, list[dict[str, Any]]],
    team: object,
) -> None:
    expected = {
        "agent_count": len(rows["agents"]),
        "turn_count": len(rows["turns"]),
        "inference_count": len(rows["inferences"]),
        "tool_count": len(rows["tools"]),
        "terminal_count": len(rows["terminal"]),
        "interaction_count": len(rows["interactions"]),
        "wait_count": sum(tool["kind"] == "wait_agent" for tool in rows["tools"]),
        "team_event_count": len(team["events"]) if isinstance(team, dict) else 0,
        "team_version_count": len(team["versions"]) if isinstance(team, dict) else 0,
        "team_route_count": len(team["routes"]) if isinstance(team, dict) else 0,
        "team_fact_count": len(team["facts"]) if isinstance(team, dict) else 0,
    }
    for key, count in expected.items():
        if summary.get(key) != count:
            raise TeamViewError("summary count is inconsistent")
    started = _integer(summary["started_at_unix_ms"], "summary start time")
    ended = _optional_integer(summary["ended_at_unix_ms"], "summary end time")
    duration = _optional_integer(summary["duration_ms"], "summary duration", minimum=0)
    if ended is None:
        if duration is not None:
            raise TeamViewError("running summary has a duration")
    elif duration != max(0, ended - started):
        raise TeamViewError("summary duration is inconsistent")
    expected_usage = {key: 0 for key in _USAGE_KEYS}
    for inference in rows["inferences"]:
        usage = inference["usage"]
        if usage is None:
            continue
        for key in _USAGE_KEYS:
            expected_usage[key] += usage[key]
    if summary["usage"] != expected_usage:
        raise TeamViewError("summary usage is inconsistent")


def _validate_window(row: dict[str, Any]) -> None:
    started_seq = _integer(row["started_seq"], "window start sequence", minimum=1)
    _integer(row["started_at_unix_ms"], "window start time")
    ended_seq = _optional_integer(row["ended_seq"], "window end sequence", minimum=1)
    _optional_integer(row["ended_at_unix_ms"], "window end time")
    if (ended_seq is None) != (row["ended_at_unix_ms"] is None):
        raise TeamViewError("window end metadata is inconsistent")
    if ended_seq is not None and ended_seq < started_seq:
        raise TeamViewError("window sequence runs backwards")
    if row["status"] not in EXECUTION_STATUSES:
        raise TeamViewError("window status is invalid")


def _validate_sequence_span(row: dict[str, Any]) -> None:
    first = _integer(row["first_seq"], "first sequence", minimum=1)
    last = _integer(row["last_seq"], "last sequence", minimum=1)
    if last < first:
        raise TeamViewError("sequence span runs backwards")


def _require_observation_order(
    rows: list[dict[str, Any]], identity_key: str, label: str
) -> None:
    identities = [row[identity_key] for row in rows]
    expected = [
        row[identity_key]
        for row in sorted(rows, key=lambda row: (row["first_seq"], row[identity_key]))
    ]
    if identities != expected:
        raise TeamViewError(f"{label} are not in canonical observation order")


def _require_relation_order(
    identities: list[str], rows: dict[str, dict[str, Any]], label: str
) -> None:
    expected = sorted(identities, key=lambda identity: (rows[identity]["first_seq"], identity))
    if identities != expected:
        raise TeamViewError(f"{label} are not in canonical observation order")


def _unique_ids(rows: list[dict[str, Any]], key: str, label: str) -> set[str]:
    values = [_nonempty_string(row[key], f"{label} id") for row in rows]
    if len(values) != len(set(values)):
        raise TeamViewError(f"{label} id is duplicated")
    return set(values)


def _string_refs(value: object, known: set[str], label: str) -> None:
    refs = _list(value, label)
    validated = [_nonempty_string(ref, label) for ref in refs]
    if len(validated) != len(set(validated)):
        raise TeamViewError(f"{label} contains a duplicate identity")
    for ref in validated:
        if ref not in known:
            raise TeamViewError(f"{label} contains an unknown identity")


def _validate_usage(value: object) -> None:
    usage = _dict(value, "usage")
    _exact_keys(usage, _USAGE_KEYS, "usage")
    for key in _USAGE_KEYS:
        _integer(usage.get(key), f"usage {key}", minimum=0)


def _exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise TeamViewError(f"{label} has unknown or missing fields")


def _dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TeamViewError(f"{label} is not an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TeamViewError(f"{label} is not an array")
    return value


def _nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TeamViewError(f"{label} is not a non-empty string")
    return value


def _integer(value: object, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TeamViewError(f"{label} is not an integer")
    if minimum is not None and value < minimum:
        raise TeamViewError(f"{label} is below its minimum")
    return value


def _optional_integer(
    value: object, label: str, *, minimum: int | None = None
) -> int | None:
    if value is None:
        return None
    return _integer(value, label, minimum=minimum)


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, label)


def _optional_boolean(value: object, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TeamViewError(f"{label} is not a boolean")
    return value
