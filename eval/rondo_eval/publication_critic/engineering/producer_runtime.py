"""Plan 097's bounded RONDO Multi Producer command and evidence projection.

The runner keeps using ``multi_m5.CaptureProxy`` and the rollout trace bundle;
this module adds no process, proxy, scorer, or Team State implementation.  Its
only output from a completed run is a body-free projection of harness-owned
tool dispatches bound to the captured Responses wire.
"""

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
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
Your assignment is complete only after team_publish returns the canonical event_id, version_id, and revision. A rewrite_required result is never a terminal result: do not send a final response or end your assignment after one.
1. Your first action on the publication path must be one team_publish opening a new Event. Use a short synthetic title, omit event_id and review_cycle_id, and make the complete summary exactly: {INITIAL_SYNTHETIC_DRAFT}
2. Use exactly one fresh code cell for each team_publish attempt. That cell must contain exactly one awaited team_publish call and no second publish call. End the cell immediately after the awaited result; when it is rewrite_required, you MUST continue in the next model turn and make the required revised attempt. Never prewrite, duplicate, batch, or parallelize publish attempts.
3. Inspect the actual team_publish result. If and only if it has status rewrite_required, read its fixed feedback and autonomously write a materially revised, concise, self-contained synthetic summary. Retry from this same thread with the returned review_cycle_id and the same new-Event title. Do not prepare or copy a second draft before receiving feedback.
4. The first team_publish is the only call that may omit review_cycle_id. Every later team_publish MUST include the exact non-empty review_cycle_id returned by the immediately preceding rewrite_required result. Before each retry, verify that argument is present. If it is unavailable, stop with an error; never open a second Event and never issue a retry without it.
5. Repeat steps 3-4 for at most the two blocking rewrite opportunities. The third review is non-blocking. Stop immediately when team_publish returns event_id, version_id, and revision; do not publish another Version.
6. End your assignment after the canonical commit. Never print or send the publication body to Root.
"""

PRODUCER_FORMAL_PROMPT = """Run one bounded synthetic Plan 097 Publication Critic engineering flow as Root.
1. Spawn exactly one member with task_name producer and the exact user task: Complete the full Producer rewrite cycle and do not finish until canonical commit. The runtime supplies that member its complete detailed task as developer instructions, so add no other task detail. Do not spawn any other member. Root must never call team_publish.
2. Immediately call wait_agent once and wait for the Producer's canonical Team State publish to wake Root. A blocked rewrite is not a publish and must not wake Root.
3. After the wake, call team_inspect exactly once with action dump and limit 50, then exactly once with action log and limit 50. Do not mutate Team State.
4. Stop after both inspections. Do not quote or summarize the publication body in the final response.
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
        "features.multi_agent_v2.subagent_developer_instructions="
        f"{json.dumps(PRODUCER_MEMBER_PROMPT)}",
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
    publishes = sorted(evidence["team_publish_calls"], key=lambda row: row["seq"])
    if not 2 <= len(publishes) <= 3:
        raise ProducerEvidenceError("publish_attempt_count_invalid")
    producer_threads = {row["thread_id"] for row in publishes}
    if len(producer_threads) != 1 or root_thread_id in producer_threads:
        raise ProducerEvidenceError("producer_thread_invalid")
    producer_thread_id = producer_threads.pop()
    if any(row["status"] != "completed" for row in publishes):
        raise ProducerEvidenceError("publish_attempt_incomplete")

    publish_calls = sorted(_team_calls(trace, "team_publish"), key=lambda call: call.seq)
    if [call.seq for call in publish_calls] != [row["seq"] for row in publishes]:
        raise ProducerEvidenceError("publish_trace_projection_mismatch")
    _validate_publish_turns(trace, publish_calls)

    expected_cycle_sha1: str | None = None
    title_sha1: str | None = None
    previous_summary_sha1: str | None = None
    feedback_versions: list[str] = []
    initial_summary_sha1 = _text_sha1(INITIAL_SYNTHETIC_DRAFT)
    for index, row in enumerate(publishes):
        result = row["result"]
        if not isinstance(result, Mapping):
            raise ProducerEvidenceError("publish_result_invalid")
        observed_title_sha1 = result.get("candidate_title_sha1")
        observed_summary_sha1 = result.get("candidate_summary_sha1")
        if (
            result.get("mode") != "publication_critic"
            or not _is_sha1(observed_title_sha1)
            or not _is_sha1(observed_summary_sha1)
            or result.get("candidate_handoff_sha1") is not None
        ):
            raise ProducerEvidenceError("candidate_observation_invalid")
        if index == 0:
            if (
                observed_summary_sha1 != initial_summary_sha1
                or result.get("continuation_sha1") is not None
            ):
                raise ProducerEvidenceError("initial_candidate_invalid")
            title_sha1 = observed_title_sha1
        elif (
            result.get("continuation_sha1") != expected_cycle_sha1
            or observed_title_sha1 != title_sha1
            or observed_summary_sha1 == initial_summary_sha1
            or observed_summary_sha1 == previous_summary_sha1
        ):
            raise ProducerEvidenceError("autonomous_rewrite_or_cycle_invalid")
        previous_summary_sha1 = observed_summary_sha1

        is_final = index == len(publishes) - 1
        if not is_final:
            expected_version = "v1" if index == 0 else "v2"
            next_cycle_sha1 = result.get("next_review_cycle_sha1")
            if (
                result.get("status") != "rewrite_required"
                or result.get("commit_outcome") != "blocked"
                or result.get("feedback_version") != expected_version
                or result.get("review_attempt") != index + 1
                or result.get("blocking_rewrite_count") != index + 1
                or result.get("failure_kind") is not None
                or not _is_sha1(next_cycle_sha1)
                or next_cycle_sha1 == expected_cycle_sha1
            ):
                raise ProducerEvidenceError("rewrite_contract_invalid")
            expected_cycle_sha1 = next_cycle_sha1
            feedback_versions.append(expected_version)

    commit = publishes[-1]["result"]
    rewrite_count = len(publishes) - 1
    final_status = commit.get("status")
    if (
        commit.get("commit_outcome") != "committed"
        or final_status not in _ALLOWED_FINAL_STATUSES
        or (final_status == "rewrite_exhausted" and rewrite_count != 2)
        or commit.get("review_attempt") != len(publishes)
        or commit.get("blocking_rewrite_count") != rewrite_count
        or commit.get("failure_kind") is not None
        or commit.get("next_review_cycle_sha1") is not None
    ):
        raise ProducerEvidenceError("final_commit_invalid")

    event_id, version_id = _validate_dump(
        evidence["entries"],
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
    previous_summary_sha1: object = None
    previous_cycle_sha1: object = None
    for row in publishes:
        raw_result = row.get("result")
        dispatch_error_kind = _classify_dispatch_error(raw_result)
        if dispatch_error_kind is not None:
            result: dict[str, Any] = {}
            failure_kind: object = dispatch_error_kind
        else:
            result = raw_result if isinstance(raw_result, Mapping) else {}
            failure_kind = result.get("failure_kind")
        args = row.get("arguments")
        args = args if isinstance(args, Mapping) else {}
        sent_continuation_sha1 = _observation_sha1(args, result, "continuation_sha1")
        sent_summary_sha1 = _observation_sha1(args, result, "candidate_summary_sha1")
        if result.get("status") == "rewrite_required":
            result_kind = "rewrite_required"
        elif _is_commit_result(result):
            result_kind = "canonical_commit"
        else:
            result_kind = "other"
        if previous_cycle_sha1 is None:
            continuation_matches_previous: object = sent_continuation_sha1 is None
        elif sent_continuation_sha1 is None:
            continuation_matches_previous = None
        else:
            continuation_matches_previous = sent_continuation_sha1 == previous_cycle_sha1
        if previous_summary_sha1 is None:
            candidate_changed_from_previous: object = None
        elif sent_summary_sha1 is None:
            candidate_changed_from_previous = None
        else:
            candidate_changed_from_previous = sent_summary_sha1 != previous_summary_sha1
        attempts.append(
            {
                "thread_role": (
                    "root" if row.get("thread_id") == trace.root_thread_id else "member"
                ),
                "dispatch_status": row.get("status"),
                "result_kind": result_kind,
                "review_status": result.get("status"),
                "review_attempt": result.get("review_attempt"),
                "blocking_rewrite_count": result.get("blocking_rewrite_count"),
                "commit_outcome": result.get("commit_outcome"),
                "failure_kind": failure_kind,
                "error_returned_to_model": _error_returned_to_model(
                    row.get("status"), dispatch_error_kind
                ),
                "continuation_matches_previous": continuation_matches_previous,
                "candidate_changed_from_previous": candidate_changed_from_previous,
                "result_fields": sorted(
                    key
                    for key in result
                    if isinstance(key, str) and key.replace("_", "").isalnum()
                ),
            }
        )
        if _is_sha1(sent_summary_sha1):
            previous_summary_sha1 = sent_summary_sha1
        next_cycle_sha1 = result.get("next_review_cycle_sha1")
        if result.get("status") == "rewrite_required" and _is_sha1(next_cycle_sha1):
            previous_cycle_sha1 = next_cycle_sha1
    waits = _team_calls(trace, "wait_agent")
    first_publish_seq = publishes[0]["seq"] if publishes else None
    commit_end_seq = publishes[-1]["end_seq"] if publishes else None
    wait_projection = []
    for wait in waits:
        result = wait.result if isinstance(wait.result, Mapping) else {}
        wait_projection.append(
            {
                "thread_role": (
                    "root" if wait.thread_id == trace.root_thread_id else "member"
                ),
                "dispatch_status": wait.status,
                "timed_out": result.get("timed_out"),
                "wake_message_matches": (
                    result.get("message") == WAIT_TEAM_ACTIVITY_MARK
                ),
                "started_before_first_publish": (
                    wait.seq < first_publish_seq
                    if isinstance(first_publish_seq, int)
                    else None
                ),
                "started_before_commit": (
                    wait.seq < commit_end_seq
                    if isinstance(commit_end_seq, int)
                    else None
                ),
                "ended_after_commit": (
                    commit_end_seq < wait.end_seq
                    if isinstance(commit_end_seq, int)
                    else None
                ),
            }
        )
    last_publish_failed = bool(publishes) and publishes[-1].get("status") != "completed"
    producer_followup = _producer_followup_after_last_publish(trace, publishes)
    return {
        "schema": "rondo-publication-critic-plan097-producer-failure-v1",
        "wire_request_count": wire_request_count,
        "trace_cell_count": evidence["cells"],
        "trace_nested_call_count": evidence["nested_calls"],
        "publish_attempt_count": len(attempts),
        "attempts": attempts,
        "wait_call_count": len(evidence["wait_calls"]),
        "waits": wait_projection,
        "inspect_actions": list(evidence["inspect_actions"]),
        "unattributed_count": len(evidence["unattributed"]),
        "last_publish_failed": last_publish_failed,
        "producer_followup_after_last_publish": producer_followup,
        "ended_after_failed_dispatch": last_publish_failed and not producer_followup,
    }


def _validate_dump(
    entries: object,
    *,
    root_thread_id: str,
    producer_thread_id: str,
) -> tuple[str, str]:
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
    event_id = event.get("event_id")
    version_id = version.get("version_id")
    if (
        len(participants) != 2
        or not isinstance(event_id, str)
        or not event_id
        or not isinstance(version_id, str)
        or not version_id
        or event.get("created_by_thread_id") != producer_thread_id
        or event.get("version_count") != 1
        or version.get("version_id") != version_id
        or version.get("author_thread_id") != producer_thread_id
        or roles.get(root_thread_id) != "root"
        or roles.get(producer_thread_id) != "member"
    ):
        raise ProducerEvidenceError("canonical_dump_invalid")
    return event_id, version_id


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
        or not wait.seq < commit_end_seq < wait.end_seq
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


def _validate_publish_turns(
    trace: RolloutTrace, publishes: list[NestedToolCall]
) -> None:
    previous_end = 0
    cells: set[tuple[str, str]] = set()
    for call in publishes:
        cell_id = call.runtime_cell_id
        key = (call.thread_id, cell_id or "")
        cell = trace.cells.get(key)
        if (
            call.requester != "code_cell"
            or not cell_id
            or cell is None
            or key in cells
            or not previous_end < cell.seq < call.seq
        ):
            raise ProducerEvidenceError("publish_turn_separation_invalid")
        cells.add(key)
        previous_end = call.end_seq


def _team_calls(trace: RolloutTrace, name: str) -> list[NestedToolCall]:
    return [
        call
        for call in trace.calls
        if call.tool_namespace == _TEAM_NAMESPACE and call.tool_name == name
    ]


_DISPATCH_ERROR_KINDS = {
    "review_cycle_id must match the active publication review cycle": "cycle_mismatch",
    "review_cycle_id does not name an active publication review cycle": "cycle_not_active",
    "publication review cycle belongs to a different actor": "cycle_wrong_actor",
    "publication review target cannot change within a cycle": "cycle_target_changed",
    "publication review cycle is no longer valid for this team turn": "cycle_turn_invalid",
    "publication review cycle ended unexpectedly": "cycle_ended",
    "publication review cycle advanced unexpectedly": "cycle_advanced",
    "failed to parse Publication Critic team_publish arguments": "arguments_unparseable",
    "invalid Publication Critic team_publish target; nothing was published": (
        "invalid_target"
    ),
    "publication review preparation failed; nothing was published": (
        "invalid_preparation"
    ),
    "publication review was cancelled before commit; nothing was published": (
        "cancelled"
    ),
    "title is required when opening a new event": "missing_title",
}


def _classify_dispatch_error(result: object) -> str | None:
    if not isinstance(result, Mapping) or result.get("type") != "error":
        return None
    message = result.get("error")
    if not isinstance(message, str) or not message:
        return "dispatch_error_unclassified"
    if message.startswith("Fatal error:"):
        return "fatal"
    kind = _DISPATCH_ERROR_KINDS.get(message)
    if kind is not None:
        return kind
    if "retry identity" in message:
        return "retry_identity_conflict"
    return "dispatch_error_unclassified"


def _observation_sha1(
    args: Mapping[str, Any], result: Mapping[str, Any], field: str
) -> object:
    if field in args:
        value = args.get(field)
        if value is None or _is_sha1(value):
            return value
    value = result.get(field)
    if value is None or _is_sha1(value):
        return value
    return None


def _error_returned_to_model(status: object, dispatch_error_kind: str | None) -> object:
    if dispatch_error_kind == "fatal":
        return False
    if dispatch_error_kind is not None:
        return True
    if status != "completed":
        return None
    return False


def _producer_followup_after_last_publish(
    trace: RolloutTrace, publishes: list[Any]
) -> bool:
    if not publishes:
        return False
    last_end = publishes[-1].get("end_seq")
    producer_threads = {
        row.get("thread_id")
        for row in publishes
        if row.get("thread_id") != trace.root_thread_id
    }
    if not isinstance(last_end, int) or not producer_threads:
        return False
    return any(
        call.thread_id in producer_threads and call.seq > last_end
        for call in trace.calls
    )


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
        and value.get("mode") == "publication_critic"
        and value.get("commit_outcome") == "committed"
        and value.get("status") in _ALLOWED_FINAL_STATUSES
    )


def _text_sha1(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def _is_sha1(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


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
