"""Plan 097's bounded RONDO Multi Producer command and evidence projection.

The runner keeps using ``multi_m5.CaptureProxy`` and the rollout trace bundle;
this module adds no process, proxy, scorer, or Team State implementation.  Its
only output from a completed run is a body-free projection of harness-owned
tool dispatches bound to the captured Responses wire.
"""

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from ...multi_m5.collect import (
    EvidenceError,
    WAIT_TEAM_ACTIVITY_MARK,
    collect_gate1_evidence,
)
from ...multi_m5.command import build_multi_exec_command
from ...multi_m5.trace import NestedToolCall, RolloutTrace


INITIAL_SYNTHETIC_DRAFT = "Work was attempted."
FIXED_FEEDBACK_V1 = (
    "Publication Critic feedback v1: revise this candidate to satisfy the minimum "
    "publication qualification, then retry with the returned review_cycle_id."
)
FIXED_FEEDBACK_V2 = (
    "Publication Critic feedback v2 (final rewrite opportunity): make a focused "
    "correction to this candidate, then retry with the returned review_cycle_id; "
    "the next review is non-blocking."
)

PRODUCER_MEMBER_PROMPT = f"""You are the only Producer in a bounded synthetic Plan 097 engineering run.
Do not spawn another agent and do not ask Root to publish for you.
1. Your first action on the publication path must be one team_publish opening a new Event. Use a short synthetic title, omit event_id and review_cycle_id, and make the complete summary exactly: {INITIAL_SYNTHETIC_DRAFT}
2. Inspect the actual team_publish result. If and only if it has status rewrite_required, read its fixed feedback and autonomously write a materially revised, concise, self-contained synthetic summary. Retry from this same thread with the returned review_cycle_id and the same new-Event title. Do not prepare or copy a second draft before receiving feedback.
3. Repeat step 2 for at most the two blocking rewrite opportunities. The third review is non-blocking. Stop immediately when team_publish returns event_id, version_id, and revision; do not publish another Version.
4. End your assignment after the canonical commit. Never print or send the publication body to Root.
"""

PRODUCER_FORMAL_PROMPT = f"""Run one bounded synthetic Plan 097 Publication Critic engineering flow as Root.
1. Spawn exactly one member with task_name producer and give it the Producer task between <producer_task> tags below. Do not spawn any other member. Root must never call team_publish.
2. Immediately call wait_agent once and wait for the Producer's canonical Team State publish to wake Root. A blocked rewrite is not a publish and must not wake Root.
3. After the wake, call team_inspect exactly once with action dump and limit 50, then exactly once with action log and limit 50. Do not mutate Team State.
4. Stop after both inspections. Do not quote or summarize the publication body in the final response.

<producer_task>
{PRODUCER_MEMBER_PROMPT}</producer_task>
"""

_MAX_WIRE_REQUESTS = 128
_MAX_WIRE_LINE_BYTES = 8 * 1024 * 1024
_MAX_TIMEOUT_MS = 300_000
_TEAM_NAMESPACE = "collaboration"
_ALLOWED_FINAL_STATUSES = {"pass", "rewrite_exhausted"}


class ProducerEvidenceError(ValueError):
    """The Producer run did not prove the bounded canonical rewrite flow."""


def build_producer_command(
    binary: Path,
    *,
    base_url: str,
    endpoint: str,
    expected_descriptor: Mapping[str, Any],
    call_timeout_ms: int,
    startup_timeout_ms: int,
    model: str,
    effort: str,
    member_model: str | None = None,
    member_effort: str | None = None,
    instruction: str = PRODUCER_FORMAL_PROMPT,
) -> list[str]:
    """Build the strict current ``codex exec`` command for one Producer run.

    ``base_url`` is expected to be the active ``CaptureProxy.base_url``.  The
    scorer remains an already-managed loopback service and is injected only as
    endpoint, full expected descriptor, and bounded client timeouts.
    """

    descriptor_json = _canonical_descriptor(expected_descriptor)
    _require_timeout(call_timeout_ms, "call_timeout_ms")
    _require_timeout(startup_timeout_ms, "startup_timeout_ms")
    host, separator, port = (
        endpoint.rpartition(":")
        if isinstance(endpoint, str)
        else ("", "", "")
    )
    if (
        host != "127.0.0.1"
        or separator != ":"
        or not port.isascii()
        or not port.isdecimal()
        or not 1 <= int(port) <= 65_535
    ):
        raise ValueError("endpoint must be a literal 127.0.0.1 socket address")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("instruction must be non-empty")

    command = build_multi_exec_command(
        Path(binary),
        base_url=base_url,
        instruction=instruction,
        model=model,
        effort=effort,
        member_model=member_model,
        member_effort=member_effort,
    )
    separator = command.index("--")
    critic_overrides = (
        f"features.multi_agent_v2.publication_critic.endpoint={json.dumps(endpoint)}",
        "features.multi_agent_v2.publication_critic.expected_descriptor_json="
        f"{json.dumps(descriptor_json)}",
        "features.multi_agent_v2.publication_critic.call_timeout_ms="
        f"{call_timeout_ms}",
        "features.multi_agent_v2.publication_critic.startup_timeout_ms="
        f"{startup_timeout_ms}",
    )
    injected: list[str] = []
    for override in critic_overrides:
        injected.extend(("-c", override))
    return [*command[:separator], *injected, *command[separator:]]


def evaluate_producer_evidence(jsonl: str, trace: RolloutTrace) -> dict[str, Any]:
    """Validate and project one Producer flow without retaining publication bodies."""

    wire_request_count = _strict_wire_request_count(jsonl)
    try:
        evidence = collect_gate1_evidence(
            jsonl,
            trace,
            required_inspect_actions=("dump", "log"),
        )
    except EvidenceError as exc:
        raise ProducerEvidenceError("trace_wire_binding_invalid") from exc
    if evidence["unattributed"]:
        raise ProducerEvidenceError("unattributed_team_evidence")

    root_thread_id = trace.root_thread_id
    spawns = _team_calls(trace, "spawn_agent")
    if len(spawns) != 1:
        raise ProducerEvidenceError("spawn_count_invalid")
    spawn = spawns[0]
    spawn_args = _arguments(spawn.arguments)
    if (
        spawn.thread_id != root_thread_id
        or spawn.status != "completed"
        or spawn_args.get("task_name") != "producer"
        or not isinstance(spawn_args.get("message"), str)
        or not spawn_args["message"].strip()
    ):
        raise ProducerEvidenceError("producer_spawn_invalid")

    publishes = sorted(evidence["team_publish_calls"], key=lambda row: row["seq"])
    if not 2 <= len(publishes) <= 3:
        raise ProducerEvidenceError("publish_attempt_count_invalid")
    producer_threads = {row["thread_id"] for row in publishes}
    if len(producer_threads) != 1 or root_thread_id in producer_threads:
        raise ProducerEvidenceError("producer_thread_invalid")
    producer_thread_id = producer_threads.pop()
    if any(row["status"] != "completed" for row in publishes):
        raise ProducerEvidenceError("publish_attempt_incomplete")

    commit_indexes = [
        index
        for index, row in enumerate(publishes)
        if _is_commit_result(row.get("result"))
    ]
    if commit_indexes != [len(publishes) - 1]:
        raise ProducerEvidenceError("canonical_commit_count_invalid")

    first_args = publishes[0]["arguments"]
    title = first_args.get("title")
    if (
        first_args.get("summary") != INITIAL_SYNTHETIC_DRAFT
        or not isinstance(title, str)
        or not title.strip()
        or first_args.get("event_id") is not None
        or first_args.get("review_cycle_id") is not None
    ):
        raise ProducerEvidenceError("initial_candidate_invalid")

    expected_cycle: str | None = None
    feedback_versions: list[str] = []
    for index, row in enumerate(publishes[:-1]):
        args = row["arguments"]
        result = row["result"]
        if not isinstance(result, Mapping) or result.get("status") != "rewrite_required":
            raise ProducerEvidenceError("rewrite_result_invalid")
        expected_feedback = FIXED_FEEDBACK_V1 if index == 0 else FIXED_FEEDBACK_V2
        expected_version = "v1" if index == 0 else "v2"
        cycle = result.get("review_cycle_id")
        if (
            result.get("feedback") != expected_feedback
            or result.get("feedback_version") != expected_version
            or result.get("review_attempt") != index + 1
            or result.get("blocking_rewrite_count") != index + 1
            or not isinstance(cycle, str)
            or not cycle
            or cycle == expected_cycle
        ):
            raise ProducerEvidenceError("rewrite_contract_invalid")
        if index == 0:
            if args.get("review_cycle_id") is not None:
                raise ProducerEvidenceError("cycle_chain_invalid")
        elif args.get("review_cycle_id") != expected_cycle:
            raise ProducerEvidenceError("cycle_chain_invalid")
        expected_cycle = cycle
        feedback_versions.append(expected_version)

    final_args = publishes[-1]["arguments"]
    if (
        final_args.get("review_cycle_id") != expected_cycle
        or final_args.get("event_id") is not None
        or final_args.get("title") != title
        or not isinstance(final_args.get("summary"), str)
        or not final_args["summary"].strip()
        or final_args["summary"] == INITIAL_SYNTHETIC_DRAFT
    ):
        raise ProducerEvidenceError("final_candidate_or_cycle_invalid")
    for row in publishes[1:-1]:
        args = row["arguments"]
        if (
            args.get("event_id") is not None
            or args.get("title") != title
            or not isinstance(args.get("summary"), str)
            or not args["summary"].strip()
            or args["summary"] == INITIAL_SYNTHETIC_DRAFT
        ):
            raise ProducerEvidenceError("revised_candidate_invalid")

    commit = publishes[-1]["result"]
    review = commit["publication_review"]
    rewrite_count = len(publishes) - 1
    final_status = review.get("status")
    if (
        commit.get("revision") != 1
        or commit.get("deduplicated") is not False
        or final_status not in _ALLOWED_FINAL_STATUSES
        or (final_status == "rewrite_exhausted" and rewrite_count != 2)
        or review.get("review_attempt") != len(publishes)
        or review.get("blocking_rewrite_count") != rewrite_count
        or review.get("failure_kind") is not None
    ):
        raise ProducerEvidenceError("final_commit_invalid")
    event_id = commit["event_id"]
    version_id = commit["version_id"]

    _validate_dump(
        evidence["entries"],
        event_id=event_id,
        version_id=version_id,
        root_thread_id=root_thread_id,
        producer_thread_id=producer_thread_id,
    )
    _validate_log(
        evidence["log"],
        version_id=version_id,
        root_thread_id=root_thread_id,
        producer_thread_id=producer_thread_id,
    )
    wait, inspections = _validate_root_observation(
        trace,
        spawn=spawn,
        commit_end_seq=publishes[-1]["end_seq"],
    )
    if not all(
        isinstance(call.result, Mapping)
        and call.result.get("revision") == 1
        and call.result.get("action") == action
        for action, call in inspections.items()
    ):
        raise ProducerEvidenceError("inspect_snapshot_invalid")
    instances = {call.result.get("instance") for call in inspections.values()}
    if len(instances) != 1 or None in instances:
        raise ProducerEvidenceError("inspect_instance_invalid")

    return {
        "schema_version": 1,
        "status": "passed",
        "root_thread_id": root_thread_id,
        "producer_thread_id": producer_thread_id,
        "wire_request_count": wire_request_count,
        "trace_cell_count": evidence["cells"],
        "trace_nested_call_count": evidence["nested_calls"],
        "publish_attempt_count": len(publishes),
        "rewrite_count": rewrite_count,
        "cycle_hop_count": rewrite_count,
        "feedback_versions": feedback_versions,
        "final_review_status": final_status,
        "canonical_commit_count": 1,
        "event_count": 1,
        "version_count": 1,
        "publish_mutation_count": 1,
        "revision": 1,
        "event_id": event_id,
        "version_id": version_id,
        "root_wake": wait.result.get("message") == WAIT_TEAM_ACTIVITY_MARK,
        "inspect_actions": ["dump", "log"],
    }


def project_producer_attempts(jsonl: str, trace: RolloutTrace) -> dict[str, Any]:
    """Project body-free publish control flow for a failed commissioning run."""

    wire_request_count = _strict_wire_request_count(jsonl)
    try:
        evidence = collect_gate1_evidence(jsonl, trace)
    except EvidenceError as exc:
        raise ProducerEvidenceError("trace_wire_binding_invalid") from exc
    publishes = sorted(evidence["team_publish_calls"], key=lambda row: row["seq"])
    attempts = []
    for row in publishes:
        arguments = row.get("arguments")
        result = row.get("result")
        arguments = arguments if isinstance(arguments, Mapping) else {}
        result = result if isinstance(result, Mapping) else {}
        review = result.get("publication_review")
        review = review if isinstance(review, Mapping) else {}
        if result.get("status") == "rewrite_required":
            result_kind = "rewrite_required"
        elif _is_commit_result(result):
            result_kind = "canonical_commit"
        else:
            result_kind = "other"
        attempts.append(
            {
                "thread_role": (
                    "root" if row.get("thread_id") == trace.root_thread_id else "member"
                ),
                "dispatch_status": row.get("status"),
                "result_kind": result_kind,
                "review_status": review.get("status"),
                "review_cycle_present": bool(arguments.get("review_cycle_id")),
                "event_id_present": bool(arguments.get("event_id")),
            }
        )
    return {
        "schema": "rondo-publication-critic-plan097-producer-failure-v1",
        "wire_request_count": wire_request_count,
        "trace_cell_count": evidence["cells"],
        "trace_nested_call_count": evidence["nested_calls"],
        "publish_attempt_count": len(attempts),
        "attempts": attempts,
        "wait_call_count": len(evidence["wait_calls"]),
        "inspect_actions": list(evidence["inspect_actions"]),
        "unattributed_count": len(evidence["unattributed"]),
    }


def _validate_dump(
    entries: object,
    *,
    event_id: str,
    version_id: str,
    root_thread_id: str,
    producer_thread_id: str,
) -> None:
    if not isinstance(entries, list):
        raise ProducerEvidenceError("dump_invalid")
    events = [row for row in entries if _entry_kind(row) == "event"]
    versions = [row for row in entries if _entry_kind(row) == "version"]
    participants = [row for row in entries if _entry_kind(row) == "participant"]
    event = events[0] if len(events) == 1 else {}
    version = versions[0] if len(versions) == 1 else {}
    roles = {
        row.get("thread_id"): row.get("role")
        for row in participants
        if isinstance(row, Mapping)
    }
    if (
        event.get("event_id") != event_id
        or event.get("created_by_thread_id") != producer_thread_id
        or event.get("version_count") != 1
        or version.get("version_id") != version_id
        or version.get("author_thread_id") != producer_thread_id
        or roles.get(root_thread_id) != "root"
        or roles.get(producer_thread_id) != "member"
    ):
        raise ProducerEvidenceError("canonical_dump_invalid")


def _validate_log(
    entries: object,
    *,
    version_id: str,
    root_thread_id: str,
    producer_thread_id: str,
) -> None:
    if not isinstance(entries, list) or len(entries) != 1:
        raise ProducerEvidenceError("publish_mutation_count_invalid")
    row = entries[0]
    wake = row.get("wake") if isinstance(row, Mapping) else None
    if (
        not isinstance(row, Mapping)
        or row.get("kind") != "publish"
        or row.get("revision") != 1
        or row.get("actor_thread_id") != producer_thread_id
        or row.get("target") != version_id
        or not isinstance(wake, Mapping)
        or wake.get("decision") != "signalled"
        or wake.get("target_thread_id") != root_thread_id
        or wake.get("rule") != "member_publish"
    ):
        raise ProducerEvidenceError("canonical_publish_mutation_invalid")


def _validate_root_observation(
    trace: RolloutTrace,
    *,
    spawn: NestedToolCall,
    commit_end_seq: int,
) -> tuple[NestedToolCall, dict[str, NestedToolCall]]:
    waits = _team_calls(trace, "wait_agent")
    if len(waits) != 1:
        raise ProducerEvidenceError("root_wait_count_invalid")
    wait = waits[0]
    if (
        wait.thread_id != trace.root_thread_id
        or wait.status != "completed"
        or not isinstance(wait.result, Mapping)
        or wait.result.get("timed_out") is not False
        or wait.result.get("message") != WAIT_TEAM_ACTIVITY_MARK
        or not spawn.end_seq < wait.seq < commit_end_seq < wait.end_seq
    ):
        raise ProducerEvidenceError("root_wake_invalid")

    inspect_calls = sorted(_team_calls(trace, "team_inspect"), key=lambda call: call.seq)
    if len(inspect_calls) != 2:
        raise ProducerEvidenceError("inspect_call_count_invalid")
    actions: dict[str, NestedToolCall] = {}
    previous = wait.end_seq
    for call in inspect_calls:
        args = _arguments(call.arguments)
        action = args.get("action")
        if (
            call.thread_id != trace.root_thread_id
            or call.status != "completed"
            or action not in {"dump", "log"}
            or action in actions
            or call.seq <= previous
        ):
            raise ProducerEvidenceError("root_inspect_invalid")
        actions[action] = call
        previous = call.end_seq
    if list(actions) != ["dump", "log"]:
        raise ProducerEvidenceError("inspect_order_invalid")
    return wait, actions


def _team_calls(trace: RolloutTrace, name: str) -> list[NestedToolCall]:
    return [
        call
        for call in trace.calls
        if call.tool_namespace == _TEAM_NAMESPACE and call.tool_name == name
    ]


def _arguments(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    if value.get("type") == "function":
        raw = value.get("arguments")
        if not isinstance(raw, str):
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return dict(value)


def _entry_kind(value: object) -> object:
    return value.get("entry") if isinstance(value, Mapping) else None


def _is_commit_result(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("event_id"), str)
        and bool(value["event_id"])
        and isinstance(value.get("version_id"), str)
        and bool(value["version_id"])
        and isinstance(value.get("publication_review"), Mapping)
    )


def _strict_wire_request_count(jsonl: str) -> int:
    if not isinstance(jsonl, str):
        raise ProducerEvidenceError("wire_capture_invalid")
    count = 0
    for raw_line in jsonl.splitlines():
        if not raw_line.strip():
            continue
        if len(raw_line.encode("utf-8")) > _MAX_WIRE_LINE_BYTES:
            raise ProducerEvidenceError("wire_capture_line_too_large")
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ProducerEvidenceError("wire_capture_invalid") from exc
        if not isinstance(value, Mapping):
            raise ProducerEvidenceError("wire_capture_invalid")
        count += 1
        if count > _MAX_WIRE_REQUESTS:
            raise ProducerEvidenceError("wire_capture_unbounded")
    if count == 0:
        raise ProducerEvidenceError("wire_capture_empty")
    return count


def _canonical_descriptor(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("expected_descriptor must be a non-empty object")
    try:
        return json.dumps(
            dict(value),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_descriptor must be JSON-encodable") from exc


def _require_timeout(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_TIMEOUT_MS:
        raise ValueError(f"{name} must be an integer from 1 through {_MAX_TIMEOUT_MS}")


__all__ = [
    "FIXED_FEEDBACK_V1",
    "FIXED_FEEDBACK_V2",
    "INITIAL_SYNTHETIC_DRAFT",
    "PRODUCER_FORMAL_PROMPT",
    "PRODUCER_MEMBER_PROMPT",
    "ProducerEvidenceError",
    "build_producer_command",
    "evaluate_producer_evidence",
    "project_producer_attempts",
]
