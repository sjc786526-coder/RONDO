"""Read-only, body-free census of delivered RONDO Local harness assets."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .artifacts import read_validated_tracked_run_records
from .artifacts import strict_json_equal
from .config import RepoPaths
from .contracts import Side
from .terminal_bench.baseline import load_historical_campaign_identity


class HarnessCensusError(ValueError):
    """Raised without exposing a private artifact value or path."""


class _PrivateArtifactMissing(HarnessCensusError):
    pass


_CAMPAIGN_VERSION = 28
_CAMPAIGN_ID = "p2-b7-canary-baseline-v28"
_PRODUCT = "rondo-local"
_SNAPSHOT_DATE = "2026-08-22"
_RAW_OUTPUT_POLICY_BYTES = 10_000
_MAX_JSON_BYTES = 8 * 1024 * 1024
_MAX_EXEC_BYTES = 32 * 1024 * 1024
_MAX_EXEC_LINES = 20_000
_MAX_REQUESTS_PER_RUN = 128
_MAX_PRIVATE_SUMMARY_BYTES = 1024 * 1024
_SAFE_PUBLIC_STRING = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_CANDIDATE_STATUSES = {
    "observed_material",
    "observed_weak",
    "not_observed",
    "unmeasurable",
}


@dataclass
class ApiStats:
    requests: int = 0
    main_requests: int = 0
    guardian_requests: int = 0
    terminal_completed: int = 0
    valid_usage: int = 0
    missing_or_invalid_usage: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: "ApiStats") -> None:
        for name in self.__dataclass_fields__:
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass
class ExecStats:
    events: int = 0
    turns_completed: int = 0
    turns_failed: int = 0
    top_level_errors: int = 0
    commands: int = 0
    commands_completed: int = 0
    commands_failed: int = 0
    commands_other_terminal: int = 0
    file_changes: int = 0
    agent_messages: int = 0
    repeated_exact_commands: int = 0
    repeated_after_failure: int = 0
    max_command_output_bytes: int = 0
    command_output_sizes: list[int] = field(default_factory=list)
    unknown_events: int = 0

    def add(self, other: "ExecStats") -> None:
        for name in self.__dataclass_fields__:
            if name == "command_output_sizes":
                self.command_output_sizes.extend(other.command_output_sizes)
            elif name == "max_command_output_bytes":
                self.max_command_output_bytes = max(
                    self.max_command_output_bytes, other.max_command_output_bytes
                )
            else:
                setattr(self, name, getattr(self, name) + getattr(other, name))


def _read_regular_beneath(root: Path, relative: Path, *, limit: int) -> bytes:
    """Read one bounded regular file without following any path-component link."""

    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
        or not hasattr(os, "O_NOFOLLOW")
    ):
        raise HarnessCensusError("eligible private artifact path is unsafe")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(root, directory_flags))
        for part in relative.parts[:-1]:
            descriptors.append(
                os.open(part, directory_flags, dir_fd=descriptors[-1])
            )
        descriptor = os.open(relative.parts[-1], file_flags, dir_fd=descriptors[-1])
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size <= 0
            or before.st_size > limit
        ):
            raise HarnessCensusError("eligible private artifact is unsafe")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        contents = b"".join(chunks)
        after = os.fstat(descriptor)
    except HarnessCensusError:
        raise
    except FileNotFoundError as exc:
        raise _PrivateArtifactMissing("eligible private artifact is unavailable") from exc
    except OSError as exc:
        raise HarnessCensusError("eligible private artifact is unavailable") from exc
    finally:
        for descriptor in reversed(descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
    if (
        len(contents) != before.st_size
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise HarnessCensusError("eligible private artifact changed while reading")
    return contents


def _decode_json(root: Path, relative: Path, *, limit: int) -> object:
    try:
        return json.loads(_read_regular_beneath(root, relative, limit=limit))
    except HarnessCensusError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise HarnessCensusError("eligible private JSON is invalid") from exc


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _parse_api_metadata(root: Path, relative: Path) -> ApiStats:
    value = _decode_json(root, relative, limit=_MAX_JSON_BYTES)
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("requests"), list)
        or not value["requests"]
        or len(value["requests"]) > _MAX_REQUESTS_PER_RUN
    ):
        raise HarnessCensusError("eligible API metadata schema is invalid")
    result = ApiStats()
    usage_keys = {
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
    }
    for request in value["requests"]:
        if not isinstance(request, dict):
            raise HarnessCensusError("eligible API request metadata is invalid")
        role = request.get("role")
        if role not in {"main", "guardian"}:
            raise HarnessCensusError("eligible API request role is invalid")
        result.requests += 1
        if role == "main":
            result.main_requests += 1
        else:
            result.guardian_requests += 1
        if (
            request.get("stream_end_kind") == "terminal"
            and request.get("terminal_event_type") == "response.completed"
            and request.get("terminal_response_status") == "completed"
            and request.get("upstream_status") == 200
        ):
            result.terminal_completed += 1
        usage = request.get("usage")
        if (
            request.get("usage_valid") is not True
            or not isinstance(usage, dict)
            or set(usage) != usage_keys
            or not all(_nonnegative_int(usage[key]) for key in usage_keys)
        ):
            result.missing_or_invalid_usage += 1
            continue
        result.valid_usage += 1
        result.input_tokens += usage["input_tokens"]
        result.cached_input_tokens += usage["cached_input_tokens"]
        result.cache_write_input_tokens += usage["cache_write_input_tokens"]
        result.output_tokens += usage["output_tokens"]
    return result


def _parse_exec_jsonl(root: Path, relative: Path) -> ExecStats:
    contents = _read_regular_beneath(root, relative, limit=_MAX_EXEC_BYTES)
    lines = contents.splitlines()
    if not lines or len(lines) > _MAX_EXEC_LINES:
        raise HarnessCensusError("eligible exec JSONL bounds are invalid")
    result = ExecStats()
    commands: dict[str, bool] = {}
    thread_started = False
    turn_started = False
    turn_terminal = False
    for raw_line in lines:
        try:
            event = json.loads(raw_line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise HarnessCensusError("eligible exec JSONL is invalid") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise HarnessCensusError("eligible exec event schema is invalid")
        result.events += 1
        event_type = event["type"]
        if turn_terminal:
            raise HarnessCensusError("eligible exec lifecycle continues after terminal")
        if event_type == "thread.started":
            if thread_started or turn_started:
                raise HarnessCensusError("eligible exec thread lifecycle is invalid")
            thread_started = True
        elif event_type == "turn.started":
            if not thread_started or turn_started:
                raise HarnessCensusError("eligible exec turn lifecycle is invalid")
            turn_started = True
        elif event_type == "turn.completed":
            if not turn_started:
                raise HarnessCensusError("eligible exec terminal lifecycle is invalid")
            result.turns_completed += 1
            turn_terminal = True
        elif event_type == "turn.failed":
            if not turn_started:
                raise HarnessCensusError("eligible exec terminal lifecycle is invalid")
            result.turns_failed += 1
            turn_terminal = True
        elif event_type == "error":
            if not turn_started:
                raise HarnessCensusError("eligible exec error lifecycle is invalid")
            result.top_level_errors += 1
        elif event_type == "item.completed":
            if not turn_started:
                raise HarnessCensusError("eligible exec item lifecycle is invalid")
            item = event.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                raise HarnessCensusError("eligible completed item schema is invalid")
            item_type = item["type"]
            if item_type == "command_execution":
                command = item.get("command")
                output = item.get("aggregated_output")
                status_value = item.get("status")
                if not isinstance(command, str) or not isinstance(output, str):
                    raise HarnessCensusError("eligible command event schema is invalid")
                result.commands += 1
                if status_value == "completed":
                    result.commands_completed += 1
                    failed = False
                elif status_value == "failed":
                    result.commands_failed += 1
                    failed = True
                else:
                    result.commands_other_terminal += 1
                    failed = False
                if command in commands:
                    result.repeated_exact_commands += 1
                    if commands[command]:
                        result.repeated_after_failure += 1
                    commands[command] = commands[command] or failed
                else:
                    commands[command] = failed
                size = len(output.encode("utf-8"))
                result.command_output_sizes.append(size)
                result.max_command_output_bytes = max(result.max_command_output_bytes, size)
            elif item_type == "file_change":
                result.file_changes += 1
            elif item_type == "agent_message":
                result.agent_messages += 1
        elif event_type in {"item.started", "item.updated"}:
            if not turn_started:
                raise HarnessCensusError("eligible exec item lifecycle is invalid")
        else:
            result.unknown_events += 1
    if not thread_started or not turn_started or not turn_terminal:
        raise HarnessCensusError("eligible exec lifecycle is incomplete")
    return result


def _validate_redaction(root: Path, relative: Path) -> None:
    value = _decode_json(root, relative, limit=16 * 1024)
    if (
        not isinstance(value, dict)
        or set(value)
        != {"schema_version", "reason", "source_size_bytes", "source_sha256"}
        or value.get("schema_version") != 1
        or value.get("reason") != "sensitive_private_artifact_omitted"
        or not _nonnegative_int(value.get("source_size_bytes"))
        or not isinstance(value.get("source_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"]) is None
    ):
        raise HarnessCensusError("eligible redaction marker is invalid")


def _validate_private_summary(
    root: Path, artifact_relative: Path, record: dict[str, Any]
) -> None:
    value = _decode_json(
        root,
        artifact_relative / "run-summary.json",
        limit=_MAX_PRIVATE_SUMMARY_BYTES,
    )
    expected_keys = {
        "schema_version",
        "run_id",
        "side",
        "git_commit",
        "outcome",
        "config",
        "summary",
        "tasks",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected_keys
        or value.get("schema_version") != 1
        or any(
            not strict_json_equal(value.get(key), record.get(key))
            for key in expected_keys - {"schema_version"}
        )
    ):
        raise HarnessCensusError("eligible private summary is inconsistent")


def _eligible_records(paths: RepoPaths) -> tuple[list[dict[str, Any]], int, object]:
    validated = read_validated_tracked_run_records(
        paths.worktree_root / "eval/results/runs.jsonl",
        common_root=paths.common_root,
    )
    identity = load_historical_campaign_identity(paths, _CAMPAIGN_VERSION)
    if (
        identity.schema_version != 7
        or identity.campaign_id != _CAMPAIGN_ID
        or not isinstance(identity.lock_sha256, str)
    ):
        raise HarnessCensusError("frozen campaign identity is invalid")
    expected = {
        slot.slot_id: slot
        for slot in identity.slots
        if slot.side is Side.RONDO and slot.kind == "base" and slot.attempt == 1
    }
    selected: list[dict[str, Any]] = []
    observed_slots: set[str] = set()
    for record, _raw in validated:
        config = record.get("config")
        if not isinstance(config, dict) or config.get("campaign_id") != _CAMPAIGN_ID:
            continue
        if record.get("side") != "rondo":
            continue
        if not (
            record.get("track") == "tb"
            and record.get("product") == _PRODUCT
            and record.get("outcome") == "completed"
            and config.get("campaign_schema_version") == 7
            and config.get("campaign_product") == _PRODUCT
            and config.get("product") == _PRODUCT
            and config.get("binary_product") == _PRODUCT
            and config.get("campaign_lock_sha256") == identity.lock_sha256
        ):
            raise HarnessCensusError("campaign Local record identity is inconsistent")
        slot_id = config.get("campaign_slot_id")
        slot = expected.get(slot_id) if isinstance(slot_id, str) else None
        tasks = record.get("tasks")
        if (
            slot is None
            or record.get("run_id") != slot.run_id
            or config.get("campaign_round_id") != slot.round_id
            or config.get("campaign_attempt") != slot.attempt
            or not isinstance(tasks, list)
            or len(tasks) != 1
            or not isinstance(tasks[0], dict)
            or tasks[0].get("task_id") != slot.task_id
            or slot_id in observed_slots
        ):
            raise HarnessCensusError("campaign Local slot identity is inconsistent")
        observed_slots.add(slot_id)
        selected.append(record)
    if observed_slots != set(expected) or len(selected) != len(expected):
        raise HarnessCensusError("campaign Local cohort is incomplete")
    for record in selected:
        _validate_private_summary(
            paths.common_root,
            Path(record["artifacts"]),
            record,
        )
    return selected, len(validated), identity


def _availability(eligible: int, measured: int) -> str:
    if measured == 0:
        return "unavailable"
    return "measured" if measured == eligible else "partial"


def _rate_ppm(numerator: int, denominator: int) -> int | None:
    return None if denominator == 0 else round(numerator * 1_000_000 / denominator)


def _signal_status(
    affected_runs: int, measured_runs: int, *, material_impact: bool = False
) -> str:
    if measured_runs == 0:
        return "unmeasurable"
    if affected_runs == 0:
        return "not_observed"
    return "observed_material" if material_impact else "observed_weak"


def _candidate(
    *,
    status: str,
    basis: str,
    eligible_runs: int,
    measured_runs: int,
    eligible_tasks: int,
    measured_tasks: int,
    occurrences: int | None,
    affected_runs: int | None,
) -> dict[str, object]:
    if status not in _CANDIDATE_STATUSES:
        raise HarnessCensusError("candidate status is invalid")
    return {
        "status": status,
        "basis": basis,
        "eligible_runs": eligible_runs,
        "measured_runs": measured_runs,
        "eligible_tasks": eligible_tasks,
        "measured_tasks": measured_tasks,
        "occurrences": occurrences,
        "affected_runs": affected_runs,
        "affected_run_rate_ppm": (
            None
            if affected_runs is None
            else _rate_ppm(affected_runs, measured_runs)
        ),
    }


def build_census(paths: RepoPaths) -> dict[str, object]:
    """Build one deterministic aggregate; private bodies never leave this call."""

    records, tracked_records, identity = _eligible_records(paths)
    eligible_tasks = len(identity.catalog.tasks)
    api_total = ApiStats()
    exec_total = ExecStats()
    api_measured = 0
    exec_measured = 0
    api_tasks: set[str] = set()
    exec_tasks: set[str] = set()
    api_missing = {"not_archived": 0, "invalid": 0}
    exec_missing = {"redacted": 0, "not_archived": 0, "invalid": 0}
    repeated_runs = 0
    repeated_after_failure_runs = 0
    over_policy_runs = 0
    api_terminal_gap_runs = 0
    durations_ms: list[int] = []

    for record in records:
        task_id = record["tasks"][0]["task_id"]
        artifact_relative = Path(record["artifacts"])
        try:
            api = _parse_api_metadata(
                paths.common_root,
                artifact_relative / "api-metadata.json",
            )
        except _PrivateArtifactMissing:
            api_missing["not_archived"] += 1
        except HarnessCensusError:
            api_missing["invalid"] += 1
        else:
            api_total.add(api)
            api_measured += 1
            api_tasks.add(task_id)
            if api.terminal_completed != api.requests:
                api_terminal_gap_runs += 1
        metrics = record.get("metrics")
        wall_seconds = metrics.get("wall_seconds") if isinstance(metrics, dict) else None
        if isinstance(wall_seconds, (int, float)) and not isinstance(wall_seconds, bool) and wall_seconds >= 0:
            durations_ms.append(round(wall_seconds * 1000))

        exec_relative = artifact_relative / "harbor/agent/codex.txt"
        redacted_relative = artifact_relative / "harbor/agent/codex.txt.redacted.json"
        try:
            observed = _parse_exec_jsonl(paths.common_root, exec_relative)
        except _PrivateArtifactMissing:
            try:
                _validate_redaction(paths.common_root, redacted_relative)
            except _PrivateArtifactMissing:
                exec_missing["not_archived"] += 1
                continue
            except HarnessCensusError:
                exec_missing["invalid"] += 1
                continue
            else:
                exec_missing["redacted"] += 1
                continue
        except HarnessCensusError:
            exec_missing["invalid"] += 1
            continue
        exec_total.add(observed)
        exec_measured += 1
        exec_tasks.add(task_id)
        if observed.repeated_exact_commands:
            repeated_runs += 1
        if observed.repeated_after_failure:
            repeated_after_failure_runs += 1
        if any(size > _RAW_OUTPUT_POLICY_BYTES for size in observed.command_output_sizes):
            over_policy_runs += 1

    eligible_runs = len(records)
    output_over_policy = sum(
        size > _RAW_OUTPUT_POLICY_BYTES for size in exec_total.command_output_sizes
    )
    output_median = (
        statistics.median_low(exec_total.command_output_sizes)
        if exec_total.command_output_sizes
        else None
    )
    api_terminal_gaps = api_total.requests - api_total.terminal_completed
    c1_status = _signal_status(over_policy_runs, exec_measured)
    c2_status = _signal_status(repeated_runs, exec_measured)
    c11_status = (
        "unmeasurable"
        if api_measured != eligible_runs
        else _signal_status(api_terminal_gap_runs, api_measured)
    )
    report: dict[str, object] = {
        "schema_version": 1,
        "kind": "rondo_local_harness_bottleneck_census",
        "snapshot_date": _SNAPSHOT_DATE,
        "scope": {
            "product": _PRODUCT,
            "campaign_id": _CAMPAIGN_ID,
            "campaign_schema_version": identity.schema_version,
            "campaign_lock_sha256": identity.lock_sha256,
            "tracked_index_records_validated": tracked_records,
            "local_private_summaries_validated": eligible_runs,
            "eligible_runs": eligible_runs,
            "eligible_tasks": eligible_tasks,
            "observations_per_task": eligible_runs // eligible_tasks,
        },
        "coverage": {
            "api_metadata": {
                "availability": _availability(eligible_runs, api_measured),
                "eligible_runs": eligible_runs,
                "measured_runs": api_measured,
                "eligible_tasks": eligible_tasks,
                "measured_tasks": len(api_tasks),
                "missing": api_missing,
            },
            "exec_jsonl": {
                "availability": _availability(eligible_runs, exec_measured),
                "eligible_runs": eligible_runs,
                "measured_runs": exec_measured,
                "eligible_tasks": eligible_tasks,
                "measured_tasks": len(exec_tasks),
                "missing": exec_missing,
            },
        },
        "aggregates": {
            "api": {
                "requests": api_total.requests,
                "main_requests": api_total.main_requests,
                "guardian_requests": api_total.guardian_requests,
                "terminal_completed": api_total.terminal_completed,
                "terminal_gaps": api_terminal_gaps,
                "valid_usage": api_total.valid_usage,
                "missing_or_invalid_usage": api_total.missing_or_invalid_usage,
                "usage": {
                    "input_tokens": api_total.input_tokens,
                    "cached_input_tokens": api_total.cached_input_tokens,
                    "cache_write_input_tokens": api_total.cache_write_input_tokens,
                    "output_tokens": api_total.output_tokens,
                    "cached_input_rate_ppm": _rate_ppm(
                        api_total.cached_input_tokens, api_total.input_tokens
                    ),
                },
            },
            "exec": {
                "events": exec_total.events,
                "turns_completed": exec_total.turns_completed,
                "turns_failed": exec_total.turns_failed,
                "top_level_errors": exec_total.top_level_errors,
                "commands": exec_total.commands,
                "commands_completed": exec_total.commands_completed,
                "commands_failed": exec_total.commands_failed,
                "commands_other_terminal": exec_total.commands_other_terminal,
                "file_changes": exec_total.file_changes,
                "agent_messages": exec_total.agent_messages,
                "unknown_events": exec_total.unknown_events,
                "command_output_median_bytes": output_median,
                "command_output_max_bytes": exec_total.max_command_output_bytes,
                "command_outputs_over_policy": output_over_policy,
                "raw_output_policy_bytes": _RAW_OUTPUT_POLICY_BYTES,
                "runs_over_output_policy": over_policy_runs,
                "repeated_exact_commands": exec_total.repeated_exact_commands,
                "runs_with_repeated_exact_commands": repeated_runs,
                "repeated_after_failure": exec_total.repeated_after_failure,
                "runs_with_repeated_after_failure": repeated_after_failure_runs,
            },
            "runtime": {
                "duration_measured_runs": len(durations_ms),
                "duration_total_ms": sum(durations_ms),
                "duration_median_ms": statistics.median_low(durations_ms) if durations_ms else None,
            },
        },
        "candidates": {
            "C1": _candidate(
                status=c1_status,
                basis="raw_output_over_model_policy_proxy",
                eligible_runs=eligible_runs,
                measured_runs=exec_measured,
                eligible_tasks=eligible_tasks,
                measured_tasks=len(exec_tasks),
                occurrences=(output_over_policy if exec_measured else None),
                affected_runs=(over_policy_runs if exec_measured else None),
            ),
            "C11": _candidate(
                status=c11_status,
                basis="typed_terminal_completion_without_request_size_reason",
                eligible_runs=eligible_runs,
                measured_runs=api_measured,
                eligible_tasks=eligible_tasks,
                measured_tasks=len(api_tasks),
                occurrences=(api_terminal_gaps if api_measured == eligible_runs else None),
                affected_runs=(
                    api_terminal_gap_runs if api_measured == eligible_runs else None
                ),
            ),
            "C7": _candidate(
                status="unmeasurable",
                basis="no_typed_claim_verification_relation",
                eligible_runs=eligible_runs,
                measured_runs=0,
                eligible_tasks=eligible_tasks,
                measured_tasks=0,
                occurrences=None,
                affected_runs=None,
            ),
            "C2": _candidate(
                status=c2_status,
                basis="exact_command_repeat_in_memory",
                eligible_runs=eligible_runs,
                measured_runs=exec_measured,
                eligible_tasks=eligible_tasks,
                measured_tasks=len(exec_tasks),
                occurrences=(exec_total.repeated_exact_commands if exec_measured else None),
                affected_runs=(repeated_runs if exec_measured else None),
            ),
        },
        "auxiliaries": {
            "C4": {
                "availability": _availability(eligible_runs, api_measured),
                "basis": "request_usage_cache_projection",
                "cached_input_rate_ppm": _rate_ppm(
                    api_total.cached_input_tokens, api_total.input_tokens
                ),
                "attribution": "cause_unmeasurable",
            },
            "C5": {
                "availability": "unavailable",
                "basis": "no_historical_tool_approval_timeline",
                "overlap_rate_ppm": None,
                "record_lag_ms": None,
            },
        },
        "decision": {
            "outcome": "bounded_measurement_required",
            "selected_candidate": None,
            "reason": "only_weak_or_unmeasurable_primary_signals",
            "minimal_ea": "not_required",
        },
    }
    validate_census_report(report)
    return report


def _exact_object(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise HarnessCensusError(f"{name} schema is invalid")
    return value


def _count(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HarnessCensusError(f"{name} count is invalid")
    return value


def _optional_count(value: object, name: str) -> int | None:
    return None if value is None else _count(value, name)


def validate_census_report(value: object) -> dict[str, Any]:
    """Validate the exact Plan 052 public aggregate and its coverage invariants."""

    root = _exact_object(
        value,
        {
            "schema_version", "kind", "snapshot_date", "scope", "coverage",
            "aggregates", "candidates", "auxiliaries", "decision",
        },
        "census",
    )
    if (
        root["schema_version"] != 1
        or root["kind"] != "rondo_local_harness_bottleneck_census"
        or root["snapshot_date"] != _SNAPSHOT_DATE
    ):
        raise HarnessCensusError("census identity is invalid")
    scope = _exact_object(
        root["scope"],
        {
            "product", "campaign_id", "campaign_schema_version",
            "campaign_lock_sha256", "tracked_index_records_validated",
            "local_private_summaries_validated", "eligible_runs",
            "eligible_tasks", "observations_per_task",
        },
        "census scope",
    )
    eligible_runs = _count(scope["eligible_runs"], "eligible runs")
    eligible_tasks = _count(scope["eligible_tasks"], "eligible tasks")
    if (
        scope["product"] != _PRODUCT
        or scope["campaign_id"] != _CAMPAIGN_ID
        or scope["campaign_schema_version"] != 7
        or not isinstance(scope["campaign_lock_sha256"], str)
        or re.fullmatch(r"[0-9a-f]{64}", scope["campaign_lock_sha256"]) is None
        or eligible_runs == 0
        or eligible_tasks == 0
        or eligible_runs % eligible_tasks
        or scope["observations_per_task"] != eligible_runs // eligible_tasks
        or _count(
            scope["tracked_index_records_validated"], "tracked index records"
        ) < eligible_runs
        or scope["local_private_summaries_validated"] != eligible_runs
    ):
        raise HarnessCensusError("census scope is inconsistent")

    coverage = _exact_object(
        root["coverage"], {"api_metadata", "exec_jsonl"}, "census coverage"
    )
    coverage_values: dict[str, dict[str, Any]] = {}
    for name, missing_keys in (
        ("api_metadata", {"not_archived", "invalid"}),
        ("exec_jsonl", {"redacted", "not_archived", "invalid"}),
    ):
        item = _exact_object(
            coverage[name],
            {
                "availability", "eligible_runs", "measured_runs",
                "eligible_tasks", "measured_tasks", "missing",
            },
            f"{name} coverage",
        )
        measured_runs = _count(item["measured_runs"], f"{name} measured runs")
        measured_tasks = _count(item["measured_tasks"], f"{name} measured tasks")
        missing = _exact_object(item["missing"], missing_keys, f"{name} missing")
        missing_total = sum(_count(missing[key], f"{name} missing") for key in missing)
        if (
            item["eligible_runs"] != eligible_runs
            or item["eligible_tasks"] != eligible_tasks
            or measured_runs > eligible_runs
            or measured_tasks > eligible_tasks
            or missing_total != eligible_runs - measured_runs
            or item["availability"] != _availability(eligible_runs, measured_runs)
        ):
            raise HarnessCensusError(f"{name} coverage is inconsistent")
        coverage_values[name] = item

    aggregates = _exact_object(
        root["aggregates"], {"api", "exec", "runtime"}, "census aggregates"
    )
    api = _exact_object(
        aggregates["api"],
        {
            "requests", "main_requests", "guardian_requests", "terminal_completed",
            "terminal_gaps", "valid_usage", "missing_or_invalid_usage", "usage",
        },
        "API aggregate",
    )
    for key in set(api) - {"usage"}:
        _count(api[key], f"API {key}")
    usage = _exact_object(
        api["usage"],
        {
            "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
            "output_tokens", "cached_input_rate_ppm",
        },
        "API usage",
    )
    for key in set(usage) - {"cached_input_rate_ppm"}:
        _count(usage[key], f"API usage {key}")
    _optional_count(usage["cached_input_rate_ppm"], "cached input rate")
    if (
        api["requests"] != api["main_requests"] + api["guardian_requests"]
        or api["requests"] != api["terminal_completed"] + api["terminal_gaps"]
        or api["requests"] != api["valid_usage"] + api["missing_or_invalid_usage"]
        or usage["cached_input_rate_ppm"]
        != _rate_ppm(usage["cached_input_tokens"], usage["input_tokens"])
        or (
            coverage_values["api_metadata"]["measured_runs"] == 0
            and any(
                api[key] != 0
                for key in set(api) - {"usage"}
            )
            or coverage_values["api_metadata"]["measured_runs"] == 0
            and any(item not in {0, None} for item in usage.values())
        )
    ):
        raise HarnessCensusError("API aggregate is inconsistent")

    exec_aggregate = _exact_object(
        aggregates["exec"],
        {
            "events", "turns_completed", "turns_failed", "top_level_errors",
            "commands", "commands_completed", "commands_failed",
            "commands_other_terminal", "file_changes", "agent_messages",
            "unknown_events", "command_output_median_bytes",
            "command_output_max_bytes", "command_outputs_over_policy",
            "raw_output_policy_bytes", "runs_over_output_policy",
            "repeated_exact_commands", "runs_with_repeated_exact_commands",
            "repeated_after_failure", "runs_with_repeated_after_failure",
        },
        "exec aggregate",
    )
    for key, item in exec_aggregate.items():
        _optional_count(item, f"exec {key}") if key == "command_output_median_bytes" else _count(
            item, f"exec {key}"
        )
    if (
        exec_aggregate["commands"]
        != exec_aggregate["commands_completed"]
        + exec_aggregate["commands_failed"]
        + exec_aggregate["commands_other_terminal"]
        or exec_aggregate["repeated_after_failure"]
        > exec_aggregate["repeated_exact_commands"]
        or exec_aggregate["runs_with_repeated_after_failure"]
        > exec_aggregate["runs_with_repeated_exact_commands"]
        or exec_aggregate["raw_output_policy_bytes"] != _RAW_OUTPUT_POLICY_BYTES
        or (
            coverage_values["exec_jsonl"]["measured_runs"] == 0
            and any(
                item not in {0, None}
                for key, item in exec_aggregate.items()
                if key != "raw_output_policy_bytes"
            )
        )
    ):
        raise HarnessCensusError("exec aggregate is inconsistent")

    runtime = _exact_object(
        aggregates["runtime"],
        {"duration_measured_runs", "duration_total_ms", "duration_median_ms"},
        "runtime aggregate",
    )
    for key in runtime:
        _optional_count(runtime[key], f"runtime {key}")
    if runtime["duration_measured_runs"] > eligible_runs:
        raise HarnessCensusError("runtime aggregate is inconsistent")

    candidates = _exact_object(
        root["candidates"], {"C1", "C11", "C7", "C2"}, "candidates"
    )
    basis = {
        "C1": "raw_output_over_model_policy_proxy",
        "C11": "typed_terminal_completion_without_request_size_reason",
        "C7": "no_typed_claim_verification_relation",
        "C2": "exact_command_repeat_in_memory",
    }
    expected_coverage = {
        "C1": coverage_values["exec_jsonl"],
        "C11": coverage_values["api_metadata"],
        "C7": {"measured_runs": 0, "measured_tasks": 0},
        "C2": coverage_values["exec_jsonl"],
    }
    for name in ("C1", "C11", "C7", "C2"):
        item = _exact_object(
            candidates[name],
            {
                "status", "basis", "eligible_runs", "measured_runs",
                "eligible_tasks", "measured_tasks", "occurrences",
                "affected_runs", "affected_run_rate_ppm",
            },
            f"candidate {name}",
        )
        occurrences = _optional_count(item["occurrences"], f"{name} occurrences")
        affected = _optional_count(item["affected_runs"], f"{name} affected runs")
        rate = _optional_count(item["affected_run_rate_ppm"], f"{name} affected rate")
        if (
            item["status"] not in _CANDIDATE_STATUSES
            or item["basis"] != basis[name]
            or item["eligible_runs"] != eligible_runs
            or item["eligible_tasks"] != eligible_tasks
            or item["measured_runs"] != expected_coverage[name]["measured_runs"]
            or item["measured_tasks"] != expected_coverage[name]["measured_tasks"]
            or (affected is not None and affected > item["measured_runs"])
            or (affected is None) != (rate is None)
            or (
                affected is not None
                and rate != _rate_ppm(affected, item["measured_runs"])
            )
            or (name == "C7" and (occurrences is not None or affected is not None))
            or (item["status"] == "unmeasurable" and affected is not None)
            or (item["status"] == "not_observed" and affected != 0)
            or (
                item["status"] in {"observed_material", "observed_weak"}
                and (affected is None or affected == 0)
            )
        ):
            raise HarnessCensusError(f"candidate {name} is inconsistent")

    auxiliaries = _exact_object(
        root["auxiliaries"], {"C4", "C5"}, "auxiliaries"
    )
    c4 = _exact_object(
        auxiliaries["C4"],
        {"availability", "basis", "cached_input_rate_ppm", "attribution"},
        "C4 auxiliary",
    )
    c5 = _exact_object(
        auxiliaries["C5"],
        {"availability", "basis", "overlap_rate_ppm", "record_lag_ms"},
        "C5 auxiliary",
    )
    if (
        c4["availability"] != coverage_values["api_metadata"]["availability"]
        or c4["basis"] != "request_usage_cache_projection"
        or c4["cached_input_rate_ppm"] != usage["cached_input_rate_ppm"]
        or c4["attribution"] != "cause_unmeasurable"
        or c5 != {
            "availability": "unavailable",
            "basis": "no_historical_tool_approval_timeline",
            "overlap_rate_ppm": None,
            "record_lag_ms": None,
        }
    ):
        raise HarnessCensusError("auxiliary aggregate is inconsistent")

    decision = _exact_object(
        root["decision"],
        {"outcome", "selected_candidate", "reason", "minimal_ea"},
        "census decision",
    )
    if decision != {
        "outcome": "bounded_measurement_required",
        "selected_candidate": None,
        "reason": "only_weak_or_unmeasurable_primary_signals",
        "minimal_ea": "not_required",
    }:
        raise HarnessCensusError("census decision is inconsistent")
    assert_public_report(root)
    return root


_PUBLIC_KEYS = {
    "schema_version", "kind", "snapshot_date", "scope", "product", "campaign_id",
    "campaign_schema_version", "campaign_lock_sha256", "tracked_index_records_validated",
    "local_private_summaries_validated",
    "eligible_runs", "eligible_tasks", "observations_per_task", "coverage", "api_metadata",
    "exec_jsonl", "availability", "measured_runs", "measured_tasks", "missing", "redacted",
    "not_archived", "invalid", "aggregates", "api", "exec", "runtime", "requests",
    "main_requests", "guardian_requests", "terminal_completed", "terminal_gaps", "valid_usage",
    "missing_or_invalid_usage", "usage", "input_tokens", "cached_input_tokens",
    "cache_write_input_tokens", "output_tokens", "cached_input_rate_ppm", "events",
    "turns_completed", "turns_failed", "top_level_errors", "commands", "commands_completed",
    "commands_failed", "commands_other_terminal", "file_changes", "agent_messages",
    "unknown_events", "command_output_median_bytes", "command_output_max_bytes",
    "command_outputs_over_policy", "raw_output_policy_bytes", "runs_over_output_policy",
    "repeated_exact_commands", "runs_with_repeated_exact_commands", "repeated_after_failure",
    "runs_with_repeated_after_failure", "duration_measured_runs", "duration_total_ms",
    "duration_median_ms", "candidates", "C1", "C11", "C7", "C2", "status", "basis",
    "occurrences", "affected_runs", "affected_run_rate_ppm", "auxiliaries", "C4", "C5",
    "attribution", "overlap_rate_ppm", "record_lag_ms", "decision", "outcome",
    "selected_candidate", "reason", "minimal_ea", "comparable", "deltas",
    "aggregates.api.requests", "aggregates.api.usage.input_tokens",
    "aggregates.api.usage.cached_input_tokens", "aggregates.exec.commands",
    "aggregates.exec.repeated_exact_commands", "aggregates.runtime.duration_total_ms",
}


def assert_public_report(value: object) -> None:
    """Reject fields or strings outside the tracked body-free allowlist."""

    if isinstance(value, dict):
        for key, child in value.items():
            if key not in _PUBLIC_KEYS:
                raise HarnessCensusError("public census key is not allowlisted")
            assert_public_report(child)
    elif isinstance(value, list):
        for child in value:
            assert_public_report(child)
    elif isinstance(value, str):
        if _SAFE_PUBLIC_STRING.fullmatch(value) is None:
            raise HarnessCensusError("public census string is not allowlisted")
    elif value is not None and not isinstance(value, (bool, int)):
        raise HarnessCensusError("public census scalar type is not allowlisted")


def compare_census_reports(left: object, right: object) -> dict[str, object]:
    """Compare same-schema aggregates without exposing per-run identities."""

    before_report = validate_census_report(left)
    after_report = validate_census_report(right)
    left_scope = before_report["scope"]
    right_scope = after_report["scope"]
    comparable = all(
        left_scope[key] == right_scope[key]
        for key in {
            "product",
            "campaign_id",
            "campaign_lock_sha256",
            "eligible_runs",
            "eligible_tasks",
            "observations_per_task",
        }
    ) and all(
        before_report["coverage"][source][key]
        == after_report["coverage"][source][key]
        for source in {"api_metadata", "exec_jsonl"}
        for key in {"availability", "measured_runs", "measured_tasks", "missing"}
    ) and (
        before_report["aggregates"]["api"]["missing_or_invalid_usage"] == 0
        and after_report["aggregates"]["api"]["missing_or_invalid_usage"] == 0
        and before_report["aggregates"]["exec"]["unknown_events"] == 0
        and after_report["aggregates"]["exec"]["unknown_events"] == 0
    )
    paths = (
        ("aggregates", "api", "requests"),
        ("aggregates", "api", "usage", "input_tokens"),
        ("aggregates", "api", "usage", "cached_input_tokens"),
        ("aggregates", "exec", "commands"),
        ("aggregates", "exec", "repeated_exact_commands"),
        ("aggregates", "runtime", "duration_total_ms"),
    )
    deltas: dict[str, int | None] = {}
    for path in paths:
        before: object = before_report
        after: object = after_report
        for part in path:
            before = before[part]  # type: ignore[index]
            after = after[part]  # type: ignore[index]
        deltas[".".join(path)] = (
            after - before
            if comparable
            and isinstance(before, int)
            and not isinstance(before, bool)
            and isinstance(after, int)
            and not isinstance(after, bool)
            else None
        )
    result: dict[str, object] = {
        "schema_version": 1,
        "kind": "rondo_local_harness_census_delta",
        "comparable": comparable,
        "deltas": deltas,
    }
    validate_census_delta(result)
    return result


_CENSUS_DELTA_KEYS = {
    "aggregates.api.requests",
    "aggregates.api.usage.input_tokens",
    "aggregates.api.usage.cached_input_tokens",
    "aggregates.exec.commands",
    "aggregates.exec.repeated_exact_commands",
    "aggregates.runtime.duration_total_ms",
}


def validate_census_delta(value: object) -> dict[str, Any]:
    root = _exact_object(
        value,
        {"schema_version", "kind", "comparable", "deltas"},
        "census delta",
    )
    if (
        root["schema_version"] != 1
        or root["kind"] != "rondo_local_harness_census_delta"
        or not isinstance(root["comparable"], bool)
    ):
        raise HarnessCensusError("census delta identity is invalid")
    deltas = _exact_object(root["deltas"], _CENSUS_DELTA_KEYS, "census deltas")
    for key, item in deltas.items():
        if item is not None and (
            isinstance(item, bool) or not isinstance(item, int)
        ):
            raise HarnessCensusError(f"census delta {key} is invalid")
        if not root["comparable"] and item is not None:
            raise HarnessCensusError("incomparable census exposes a delta")
    assert_public_report(root)
    return root


def _write_report(path: Path, report: dict[str, object], *, worktree_root: Path) -> None:
    target = path if path.is_absolute() else worktree_root / path
    resolved_parent = target.parent.resolve(strict=True)
    resolved = resolved_parent / target.name
    try:
        resolved.relative_to(worktree_root)
    except ValueError as exc:
        raise HarnessCensusError("census output is outside the worktree") from exc
    if resolved.exists() and resolved.is_symlink():
        raise HarnessCensusError("census output is unsafe")
    encoded = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = resolved.with_name(f".{resolved.name}.plan052-{os.getpid()}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(resolved)
    except OSError as exc:
        raise HarnessCensusError("census output cannot be written safely") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the body-free Plan 052 census")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    paths = RepoPaths.discover(Path.cwd())
    report = build_census(paths)
    if args.output is None:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        _write_report(args.output, report, worktree_root=paths.worktree_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
