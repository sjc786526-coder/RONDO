from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rondo_eval.harness_observation import (
    HarnessObservationError,
    compare_task_observations,
    project_task_observation,
    validate_task_observation,
)
from tests.test_team_lens import (
    BODY_SENTINELS,
    COMMAND_BODY,
    OUTPUT_BODY,
    PROMPT_BODY,
    RAW_PATH_BODY,
    NativeBundleBuilder,
)

GUARDIAN_LIMIT_ERROR = (
    "exec_command failed with status 409; error code "
    "guardian_logical_request_limit_exceeded"
)
GUARDIAN_REJECTION_ERROR = (
    "exec_command failed for `/usr/bin/bash -lc 'dangerous command'`: "
    'CreateProcess { message: "Rejected(\\"This action was rejected due to '
    'unacceptable risk.\\\\nReason: synthetic rejection.\\\\nThe agent must not '
    "attempt to achieve the same outcome via workaround, indirect execution, or "
    "policy circumvention. Proceed only with a materially safer alternative, or if "
    "the user explicitly approves the action after being informed of the risk. "
    'Otherwise, stop and request user input.\\")" }'
)
UNKNOWN_PROCESS_ERROR = "write_stdin failed: Unknown process id 9"
JUSTIFICATION_ERROR = (
    '`justification` requires an explicit `sandbox_permissions`; use '
    '`sandbox_permissions: "require_escalated"` for unsandboxed execution, '
    'or omit `justification`.'
)


def _observation() -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "rondo_local_harness_observation",
        "scope": "rondo_local_task",
        "source": {
            "product": "rondo-local",
            "rollout_trace_manifest_schema_version": 1,
            "rollout_trace_event_schema_versions": [1],
            "api_metadata_schema_version": 1,
            "guardian_trace_bundles": 0,
        },
        "availability": {
            "turn_lifecycle": "measured",
            "response_lifecycle": "measured",
            "response_usage": "measured",
            "tool_lifecycle": "measured",
            "command_output": "measured",
            "compactions": "unmeasurable",
            "guardian_details": "unmeasurable",
            "model_visible_output_truncation": "measured",
            "code_mode_runtime_output_truncation": "measured",
            "claim_verification_relation": "unmeasurable",
        },
        "turn": {"status": "completed", "duration_ms": 100},
        "responses": {
            "total": 1,
            "main": 1,
            "guardian": 0,
            "terminal_completed": 1,
            "terminal_failed": 0,
            "terminal_incomplete": 0,
            "terminal_error": 0,
            "with_valid_usage": 1,
            "missing_or_invalid_usage": 0,
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "cache_write_input_tokens": 1,
                "output_tokens": 4,
            },
        },
        "errors": {
            "total": 0,
            "retryable_status": 0,
            "context_window_exceeded": 0,
            "bad_request": 0,
            "response_stream_failure": 0,
            "budget_or_usage_limit": 0,
            "other": 0,
        },
        "tools": {
            "total": 1,
            "command": 1,
            "mcp": 0,
            "other": 0,
            "total_lifecycle_duration_ms": 30,
            "command_output_bytes": len(OUTPUT_BODY.encode("utf-8")),
            "max_command_output_bytes": len(OUTPUT_BODY.encode("utf-8")),
            "model_visible_output_deliveries": 1,
            "model_visible_output_renders": 1,
            "model_visible_output_render_missing": 0,
            "model_visible_source_text_bytes": len(OUTPUT_BODY.encode("utf-8")),
            "model_visible_returned_text_bytes": len(OUTPUT_BODY.encode("utf-8")),
            "model_visible_presentation_truncations": 0,
            "model_visible_collection_omission_events": 0,
            "model_visible_collection_omitted_bytes": 0,
            "code_mode_runtime_output_deliveries": 0,
            "code_mode_runtime_output_renders": 0,
            "code_mode_runtime_output_render_missing": 0,
            "code_mode_runtime_source_text_bytes": 0,
            "code_mode_runtime_returned_text_bytes": 0,
            "code_mode_runtime_presentation_truncations": 0,
            "code_mode_runtime_collection_omission_events": 0,
            "code_mode_runtime_collection_omitted_bytes": 0,
            "repeated_exact_commands": 0,
            "repeated_exact_command_lifecycle_duration_ms": 0,
            "repeated_after_failure": 0,
        },
        "compactions": {"completed": None},
    }


def _write_bundle(
    root: Path,
    *,
    session_source: object = "exec",
    commands: tuple[tuple[str, int, str], ...] = ((COMMAND_BODY, 0, RAW_PATH_BODY),),
    model_output: str = OUTPUT_BODY,
    command_output: str = OUTPUT_BODY,
    presentation_truncated: bool = False,
    collection_omitted_bytes: int = 0,
    turn_count: int = 1,
    inference_terminal: str = "completed",
    duplicate_code_cell_render: bool = False,
    include_mcp_without_render: bool = False,
    code_mode_exec_phase: str | None = None,
    duplicate_public_exec_delivery: bool = False,
    pre_runtime_denied_command_index: int | None = None,
    code_mode_command_indexes: tuple[int, ...] = (),
) -> Path:
    builder = NativeBundleBuilder(root)
    builder.event(
        {
            "type": "rollout_started",
            "trace_id": builder.trace_id,
            "root_thread_id": builder.root_thread,
        }
    )
    metadata = builder.payload(
        "session_metadata",
        {
            "thread_id": builder.root_thread,
            "agent_path": "/root",
            "task_name": None,
            "nickname": None,
            "agent_role": None,
            "session_source": session_source,
            "cwd": RAW_PATH_BODY,
            "rollout_path": RAW_PATH_BODY,
            "model": "gpt-test",
            "provider_name": "provider-private",
            "approval_policy": "never",
            "sandbox_policy": "workspace_write",
        },
    )
    builder.event(
        {
            "type": "thread_started",
            "thread_id": builder.root_thread,
            "agent_path": "/root",
            "metadata_payload": metadata,
        },
        thread_id=builder.root_thread,
    )
    if turn_count < 1 or (turn_count != 1 and commands):
        raise ValueError("synthetic multi-turn bundles cannot carry command fixtures")
    for turn_index in range(1, turn_count + 1):
        turn_id = f"turn-{turn_index}"
        builder.event(
            {
                "type": "codex_turn_started",
                "codex_turn_id": turn_id,
                "thread_id": builder.root_thread,
            },
            thread_id=builder.root_thread,
            turn_id=turn_id,
        )
        builder.inference(
            f"inference-{turn_index}",
            {
                "model": "gpt-test",
                "input": [{"role": "user", "content": PROMPT_BODY}],
            },
            turn_id=turn_id,
        )
        if inference_terminal != "completed":
            inference_end = builder.events[-1]["payload"]
            if inference_end["type"] != "inference_completed":
                raise AssertionError("synthetic inference terminal is misplaced")
            builder.events[-1]["payload"] = {
                "type": "inference_failed",
                "inference_call_id": f"inference-{turn_index}",
                "upstream_request_id": "upstream-private",
                "error": "synthetic typed failure",
                "partial_response_payload": None,
            }
        if code_mode_exec_phase is not None:
            if turn_count != 1 or code_mode_exec_phase not in {
                "before_cell_error",
                "after_cell_start_error",
                "success",
            }:
                raise ValueError("synthetic public exec phase is invalid")
            model_call_id = "public-exec-call"
            runtime_cell_id = "public-exec-cell"
            if code_mode_exec_phase != "before_cell_error":
                builder.event(
                    {
                        "type": "code_cell_started",
                        "runtime_cell_id": runtime_cell_id,
                        "model_visible_call_id": model_call_id,
                        "source_js": "synthetic private source",
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
            if code_mode_exec_phase == "success":
                output_render = {
                    "surface": "direct_model",
                    "source_text_bytes": len(OUTPUT_BODY.encode("utf-8")),
                    "collection_omitted_bytes": 0,
                    "requested_max_output_tokens": 64,
                    "effective_max_output_tokens": 64,
                    "returned_text_bytes": len(OUTPUT_BODY.encode("utf-8")),
                    "presentation_truncated": False,
                }
                builder.event(
                    {
                        "type": "code_cell_initial_response",
                        "runtime_cell_id": runtime_cell_id,
                        "status": "completed",
                        "response_payload": None,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
                builder.event(
                    {
                        "type": "code_cell_output_rendered",
                        "runtime_cell_id": runtime_cell_id,
                        "observation": output_render,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
                builder.event(
                    {
                        "type": "code_cell_ended",
                        "runtime_cell_id": runtime_cell_id,
                        "status": "completed",
                        "response_payload": None,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
            delivery_payload = {
                "type": "code_mode_exec_output_delivered",
                "model_visible_call_id": model_call_id,
                **(
                    {"output_render": output_render}
                    if code_mode_exec_phase == "success"
                    else {}
                ),
            }
            builder.event(
                delivery_payload,
                thread_id=builder.root_thread,
                turn_id=turn_id,
            )
            if duplicate_public_exec_delivery:
                builder.event(
                    copy.deepcopy(delivery_payload),
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
        for index, (command, exit_code, cwd) in enumerate(commands, start=1):
            code_mode_command = (
                pre_runtime_denied_command_index == index
                or index in code_mode_command_indexes
            )
            direct_output_render = {
                "surface": "direct_model",
                "source_text_bytes": len(command_output.encode("utf-8")),
                "collection_omitted_bytes": collection_omitted_bytes,
                "requested_max_output_tokens": 64,
                "effective_max_output_tokens": 64,
                "returned_text_bytes": len(model_output.encode("utf-8")),
                "presentation_truncated": presentation_truncated,
            }
            if duplicate_code_cell_render:
                builder.event(
                    {
                        "type": "code_cell_started",
                        "runtime_cell_id": f"cell-duplicate-{index}",
                        "model_visible_call_id": f"model-tool-{index}",
                        "source_js": "synthetic private source",
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
            builder.tool(
                f"tool-{index}",
                name="exec_command",
                kind="exec_command",
                arguments={"cmd": command, "workdir": cwd},
                result=(
                    {
                        "chunk_id": f"chunk-{index}",
                        "wall_time_seconds": 0.0,
                        "exit_code": exit_code,
                        "original_token_count": 1,
                        "output": model_output,
                    }
                    if code_mode_command
                    else model_output
                ),
                result_mode=("code" if code_mode_command else "direct"),
                runtime_end=(
                    None
                    if pre_runtime_denied_command_index == index
                    else {
                        "process_id": f"terminal-{index}",
                        "command": [command],
                        "cwd": cwd,
                        "aggregated_output": command_output,
                        "status": "completed" if exit_code == 0 else "failed",
                        "exit_code": exit_code,
                        "duration": {"secs": 0, "nanos": 5_000_000},
                    }
                ),
                output_render=(
                    {**direct_output_render, "surface": "code_mode_runtime"}
                    if code_mode_command
                    else direct_output_render
                ),
                turn_id=turn_id,
            )
            if code_mode_command:
                runtime_cell_id = f"cell-tool-{index}"
                builder.event(
                    {
                        "type": "code_cell_initial_response",
                        "runtime_cell_id": runtime_cell_id,
                        "status": "completed",
                        "response_payload": None,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
                builder.event(
                    {
                        "type": "code_cell_output_rendered",
                        "runtime_cell_id": runtime_cell_id,
                        "observation": direct_output_render,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
                builder.event(
                    {
                        "type": "code_cell_ended",
                        "runtime_cell_id": runtime_cell_id,
                        "status": "completed",
                        "response_payload": None,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
                builder.event(
                    {
                        "type": "code_mode_exec_output_delivered",
                        "model_visible_call_id": f"model-tool-{index}",
                        "output_render": direct_output_render,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
            if duplicate_code_cell_render:
                builder.event(
                    {
                        "type": "code_cell_initial_response",
                        "runtime_cell_id": f"cell-duplicate-{index}",
                        "status": "completed",
                        "response_payload": None,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
                builder.event(
                    {
                        "type": "code_cell_output_rendered",
                        "runtime_cell_id": f"cell-duplicate-{index}",
                        "observation": direct_output_render,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
                builder.event(
                    {
                        "type": "code_cell_ended",
                        "runtime_cell_id": f"cell-duplicate-{index}",
                        "status": "completed",
                        "response_payload": None,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
                builder.event(
                    {
                        "type": "code_mode_exec_output_delivered",
                        "model_visible_call_id": f"model-tool-{index}",
                        "output_render": direct_output_render,
                    },
                    thread_id=builder.root_thread,
                    turn_id=turn_id,
                )
        if include_mcp_without_render:
            builder.tool(
                "tool-mcp",
                name="mcp_tool",
                kind="mcp",
                arguments={},
                result={"private": "result"},
                result_mode="direct",
                turn_id=turn_id,
            )
        turn_status = "completed" if inference_terminal == "completed" else "failed"
        builder.event(
            {
                "type": "codex_turn_ended",
                "codex_turn_id": turn_id,
                "status": turn_status,
            },
            thread_id=builder.root_thread,
            turn_id=turn_id,
        )
    rollout_status = "completed" if inference_terminal == "completed" else "failed"
    builder.event(
        {
            "type": "thread_ended",
            "thread_id": builder.root_thread,
            "status": rollout_status,
        },
        thread_id=builder.root_thread,
    )
    builder.event({"type": "rollout_ended", "status": rollout_status})
    builder.event({"type": "trace_capture_ended", "dropped_operations": 0})
    return builder.write()


def _make_pre_runtime_guardian_limit(
    bundle: Path,
    *,
    tool_index: int = 1,
    error: str = GUARDIAN_LIMIT_ERROR,
) -> None:
    """Convert one synthetic sandbox denial to the exact Guardian-limit shape."""

    tool_id = f"tool-{tool_index}"
    runtime_cell_id = f"cell-{tool_id}"
    model_call_id = f"model-{tool_id}"
    events = [
        json.loads(line)
        for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    ended = next(
        event
        for event in events
        if event["payload"]["type"] == "tool_call_ended"
        and event["payload"]["tool_call_id"] == tool_id
    )
    ended["payload"]["status"] = "failed"
    result_path = bundle / ended["payload"]["result_payload"]["path"]
    result_path.write_text(
        json.dumps({"type": "error", "error": error}), encoding="utf-8"
    )
    events = [
        event
        for event in events
        if not (
            event["payload"]["type"] == "code_cell_output_rendered"
            and event["payload"].get("runtime_cell_id") == runtime_cell_id
        )
    ]
    for event in events:
        payload = event["payload"]
        if payload["type"] in {"code_cell_initial_response", "code_cell_ended"}:
            if payload.get("runtime_cell_id") == runtime_cell_id:
                payload["status"] = "failed"
        if (
            payload["type"] == "code_mode_exec_output_delivered"
            and payload.get("model_visible_call_id") == model_call_id
        ):
            payload["output_render"]["requested_max_output_tokens"] = None
    for seq, event in enumerate(events, start=1):
        event["seq"] = seq
    (bundle / "trace.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def _update_exec_invocation_arguments(
    bundle: Path,
    *,
    tool_index: int = 1,
    updates: dict[str, object] | None = None,
    removals: tuple[str, ...] = (),
) -> None:
    tool_id = f"tool-{tool_index}"
    events = [
        json.loads(line)
        for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    started = next(
        event
        for event in events
        if event["payload"]["type"] == "tool_call_started"
        and event["payload"]["tool_call_id"] == tool_id
    )
    invocation_path = bundle / started["payload"]["invocation_payload"]["path"]
    invocation = json.loads(invocation_path.read_text("utf-8"))
    arguments = json.loads(invocation["payload"]["arguments"])
    for name in removals:
        arguments.pop(name, None)
    arguments.update(updates or {})
    invocation["payload"]["arguments"] = json.dumps(
        arguments, separators=(",", ":")
    )
    invocation_path.write_text(json.dumps(invocation), encoding="utf-8")


def _make_pre_runtime_unknown_write_stdin(
    bundle: Path,
    *,
    tool_index: int = 1,
    process_id: int = 9,
    error: str = UNKNOWN_PROCESS_ERROR,
) -> None:
    """Convert one missing exec runtime to an exact failed session lookup."""

    _make_pre_runtime_guardian_limit(bundle, tool_index=tool_index)
    tool_id = f"tool-{tool_index}"
    events = [
        json.loads(line)
        for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    started = next(
        event
        for event in events
        if event["payload"]["type"] == "tool_call_started"
        and event["payload"]["tool_call_id"] == tool_id
    )
    started["payload"]["kind"] = {"type": "write_stdin"}
    invocation_path = bundle / started["payload"]["invocation_payload"]["path"]
    invocation = json.loads(invocation_path.read_text("utf-8"))
    invocation["tool_name"] = "write_stdin"
    invocation["payload"]["arguments"] = json.dumps(
        {
            "session_id": process_id,
            "chars": "",
            "yield_time_ms": 30_000,
            "max_output_tokens": 20_000,
        },
        separators=(",", ":"),
    )
    invocation_path.write_text(json.dumps(invocation), encoding="utf-8")
    ended = next(
        event
        for event in events
        if event["payload"]["type"] == "tool_call_ended"
        and event["payload"]["tool_call_id"] == tool_id
    )
    result_path = bundle / ended["payload"]["result_payload"]["path"]
    result_path.write_text(
        json.dumps({"type": "error", "error": error}), encoding="utf-8"
    )
    (bundle / "trace.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def _make_local_guardian_limit_inference(
    bundle: Path,
    *,
    inference_id: str = "inference-2",
    error: str = GUARDIAN_LIMIT_ERROR,
) -> None:
    events = [
        json.loads(line)
        for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    terminal = next(
        event
        for event in events
        if event["payload"].get("inference_call_id") == inference_id
        and event["payload"]["type"] == "inference_completed"
    )
    terminal["payload"] = {
        "type": "inference_failed",
        "inference_call_id": inference_id,
        "upstream_request_id": None,
        "error": error,
        "partial_response_payload": None,
    }
    (bundle / "trace.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def _append_linked_local_inference_failure(bundle: Path) -> None:
    events = [
        json.loads(line)
        for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    started = copy.deepcopy(
        next(
            event
            for event in events
            if event["payload"]["type"] == "inference_started"
        )
    )
    turn_end_index = next(
        index
        for index, event in enumerate(events)
        if event["payload"]["type"] == "codex_turn_ended"
    )
    turn_end = events[turn_end_index]
    inference_id = "local-post-tool-failure"
    started["wall_time_unix_ms"] = turn_end["wall_time_unix_ms"] - 2
    started["payload"]["inference_call_id"] = inference_id
    failed = {
        **{
            key: started[key]
            for key in (
                "schema_version",
                "rollout_id",
                "thread_id",
                "codex_turn_id",
            )
        },
        "seq": 0,
        "wall_time_unix_ms": turn_end["wall_time_unix_ms"] - 1,
        "payload": {
            "type": "inference_failed",
            "inference_call_id": inference_id,
            "upstream_request_id": None,
            "error": "local inference stopped after tool failure",
            "partial_response_payload": None,
        },
    }
    events[turn_end_index:turn_end_index] = [started, failed]
    for seq, event in enumerate(events, start=1):
        event["seq"] = seq
    (bundle / "trace.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )


def _write_metadata(path: Path, *roles: str, terminal: str = "completed") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "requests": [
                    {
                        "request_id": f"request-{index}",
                        "body_sha256": "a" * 64,
                        "canonical_body_sha256": "b" * 64,
                        "role": role,
                        "role_provenance": "declared",
                        "declared_role": role,
                        "inferred_role": role,
                        "model": "gpt-test",
                        "reasoning_effort": "medium",
                        "stream": True,
                        "shape": "responses",
                        "contract_match": True,
                        "upstream_status": 200,
                        "usage_valid": terminal == "completed",
                        "charged_usd": "0.010000",
                        "attempt_count": 1,
                        "settlement_kind": "usage_priced",
                        "usage": (
                            {
                                "input_tokens": 10,
                                "cached_input_tokens": 2,
                                "cache_write_input_tokens": 1,
                                "output_tokens": 4,
                            }
                            if terminal == "completed"
                            else None
                        ),
                        "stream_end_kind": "terminal",
                        "terminal_event_type": f"response.{terminal}",
                        "terminal_response_status": terminal,
                        "terminal_error_code": (
                            None
                            if terminal == "completed"
                            else "context_length_exceeded"
                        ),
                    }
                    for index, role in enumerate(roles, start=1)
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _mark_request_failed(request: dict[str, object]) -> None:
    request["usage_valid"] = False
    request["usage"] = None
    request["terminal_event_type"] = "response.failed"
    request["terminal_response_status"] = "failed"
    request["terminal_error_code"] = "context_length_exceeded"


class HarnessObservationTests(unittest.TestCase):
    def test_exact_schema_and_comparison_keep_unmeasurable_fields_null(self) -> None:
        before = _observation()
        after = copy.deepcopy(before)
        after["turn"]["duration_ms"] = 125
        after["tools"]["command_output_bytes"] += 5
        after["tools"]["max_command_output_bytes"] += 5
        after["tools"]["repeated_exact_commands"] = 1
        after["tools"]["repeated_exact_command_lifecycle_duration_ms"] = 20

        validated = validate_task_observation(before)
        comparison = compare_task_observations(before, after)

        self.assertEqual(validated, before)
        self.assertIsNone(validated["compactions"]["completed"])
        self.assertTrue(comparison["comparable"])
        self.assertEqual(comparison["schema_version"], 2)
        self.assertEqual(comparison["deltas"]["turn.duration_ms"], 25)
        self.assertEqual(comparison["deltas"]["tools.command_output_bytes"], 5)
        self.assertEqual(
            comparison["deltas"]["tools.repeated_exact_command_lifecycle_duration_ms"],
            20,
        )

    def test_missing_usage_is_not_silently_zero(self) -> None:
        value = _observation()
        value["availability"]["response_usage"] = "unmeasurable"
        value["responses"]["with_valid_usage"] = 0
        value["responses"]["missing_or_invalid_usage"] = 1
        for key in value["responses"]["usage"]:
            value["responses"]["usage"][key] = 0

        comparison = compare_task_observations(_observation(), value)

        self.assertTrue(comparison["comparable"])
        usage_deltas = {
            result
            for key, result in comparison["deltas"].items()
            if key.startswith("responses.usage.")
        }
        self.assertEqual(usage_deltas, {None})
        self.assertEqual(comparison["deltas"]["responses.total"], 0)

    def test_extra_body_field_and_false_measured_compaction_are_rejected(self) -> None:
        extra = _observation()
        extra["prompt"] = "private body"
        with self.assertRaisesRegex(HarnessObservationError, "schema is invalid"):
            validate_task_observation(extra)

        false_zero = _observation()
        false_zero["compactions"]["completed"] = 0
        with self.assertRaisesRegex(HarnessObservationError, "not measurable"):
            validate_task_observation(false_zero)

    def test_impossible_repeated_command_durations_are_rejected(self) -> None:
        without_repeat = _observation()
        without_repeat["tools"]["repeated_exact_command_lifecycle_duration_ms"] = 1
        with self.assertRaisesRegex(HarnessObservationError, "lacks repeated commands"):
            validate_task_observation(without_repeat)

        exceeds_total = _observation()
        exceeds_total["tools"]["repeated_exact_commands"] = 1
        exceeds_total["tools"]["repeated_exact_command_lifecycle_duration_ms"] = 31
        with self.assertRaisesRegex(HarnessObservationError, "exceeds tool duration"):
            validate_task_observation(exceeds_total)

    def test_offline_projection_is_body_free_and_counts_exact_repeats(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=(
                    (COMMAND_BODY, 1, RAW_PATH_BODY),
                    (COMMAND_BODY, 0, RAW_PATH_BODY),
                ),
                model_output=(
                    "Warning: truncated output (original token count: 42)\n"
                    "head\n…12 tokens truncated…\ntail"
                ),
                command_output="head\n... 4096 bytes omitted ...\ntail",
                presentation_truncated=True,
                collection_omitted_bytes=4096,
            )
            _write_bundle(
                trace_root / "guardian",
                session_source={"subagent": {"other": "guardian"}},
                commands=(),
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main", "guardian")

            observation = project_task_observation(trace_root, metadata)

        encoded = json.dumps(observation, sort_keys=True)
        self.assertEqual(observation["source"]["guardian_trace_bundles"], 1)
        self.assertEqual(observation["responses"]["total"], 2)
        self.assertEqual(observation["tools"]["command"], 2)
        self.assertEqual(observation["tools"]["model_visible_output_renders"], 2)
        self.assertGreater(observation["tools"]["model_visible_returned_text_bytes"], 0)
        self.assertEqual(observation["tools"]["model_visible_presentation_truncations"], 2)
        self.assertEqual(observation["tools"]["model_visible_collection_omission_events"], 2)
        self.assertEqual(observation["tools"]["model_visible_collection_omitted_bytes"], 8192)
        self.assertEqual(observation["tools"]["repeated_exact_commands"], 1)
        self.assertEqual(
            observation["tools"]["repeated_exact_command_lifecycle_duration_ms"],
            30,
        )
        self.assertEqual(observation["tools"]["repeated_after_failure"], 1)
        self.assertTrue(all(body not in encoded for body in BODY_SENTINELS))

    def test_code_mode_pre_runtime_sandbox_denial_is_measured_body_free(self) -> None:
        source_output = OUTPUT_BODY * 4
        returned_output = "short rendered output"
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                model_output=returned_output,
                command_output=source_output,
                presentation_truncated=True,
                pre_runtime_denied_command_index=1,
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        encoded = json.dumps(observation, sort_keys=True)
        self.assertEqual(observation["tools"]["command"], 1)
        self.assertEqual(
            observation["tools"]["command_output_bytes"],
            len(source_output.encode("utf-8")),
        )
        self.assertEqual(
            observation["tools"]["code_mode_runtime_output_deliveries"], 1
        )
        self.assertEqual(
            observation["tools"]["code_mode_runtime_source_text_bytes"],
            len(source_output.encode("utf-8")),
        )
        self.assertEqual(
            observation["tools"]["code_mode_runtime_returned_text_bytes"],
            len(returned_output.encode("utf-8")),
        )
        self.assertEqual(observation["tools"]["model_visible_output_deliveries"], 1)
        self.assertTrue(all(body not in encoded for body in BODY_SENTINELS))

    def test_pre_runtime_denial_and_native_retry_share_caller_identity(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=(
                    (COMMAND_BODY, 128, RAW_PATH_BODY),
                    (COMMAND_BODY, 1, RAW_PATH_BODY),
                ),
                pre_runtime_denied_command_index=1,
                code_mode_command_indexes=(2,),
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["tools"]["repeated_exact_commands"], 1)
        self.assertEqual(observation["tools"]["repeated_after_failure"], 1)
        self.assertEqual(
            observation["tools"]["repeated_exact_command_lifecycle_duration_ms"],
            30,
        )

    def test_pre_runtime_guardian_limit_is_a_zero_output_failed_command(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                pre_runtime_denied_command_index=1,
            )
            _make_pre_runtime_guardian_limit(bundle)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        encoded = json.dumps(observation, sort_keys=True)
        self.assertEqual(observation["tools"]["command"], 1)
        self.assertGreater(observation["tools"]["total_lifecycle_duration_ms"], 0)
        self.assertEqual(observation["tools"]["command_output_bytes"], 0)
        self.assertEqual(observation["tools"]["max_command_output_bytes"], 0)
        self.assertNotIn(GUARDIAN_LIMIT_ERROR, encoded)

    def test_pre_runtime_guardian_rejection_is_a_zero_output_failed_command(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                pre_runtime_denied_command_index=1,
            )
            _make_pre_runtime_guardian_limit(
                bundle, error=GUARDIAN_REJECTION_ERROR
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        encoded = json.dumps(observation, sort_keys=True)
        self.assertEqual(observation["tools"]["command"], 1)
        self.assertEqual(observation["tools"]["command_output_bytes"], 0)
        self.assertEqual(observation["tools"]["max_command_output_bytes"], 0)
        self.assertNotIn("synthetic rejection", encoded)

    def test_pre_runtime_guardian_rejection_is_not_a_guardian_limit(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                pre_runtime_denied_command_index=1,
            )
            _make_pre_runtime_guardian_limit(
                bundle, error=GUARDIAN_REJECTION_ERROR
            )
            _append_linked_local_inference_failure(bundle)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            with self.assertRaisesRegex(
                HarnessObservationError, "populations disagree"
            ):
                project_task_observation(trace_root, metadata)

    def test_pre_runtime_justification_error_is_a_failed_command(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                pre_runtime_denied_command_index=1,
            )
            _make_pre_runtime_guardian_limit(bundle, error=JUSTIFICATION_ERROR)
            _update_exec_invocation_arguments(
                bundle,
                updates={"justification": ""},
                removals=("sandbox_permissions",),
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        encoded = json.dumps(observation, sort_keys=True)
        self.assertEqual(observation["tools"]["command"], 1)
        self.assertEqual(observation["tools"]["command_output_bytes"], 0)
        self.assertEqual(observation["tools"]["max_command_output_bytes"], 0)
        self.assertNotIn("sandbox_permissions", encoded)

    def test_pre_runtime_justification_error_is_bound_to_its_arguments(self) -> None:
        cases = (
            ({}, ("justification", "sandbox_permissions")),
            ({"justification": None}, ("sandbox_permissions",)),
            (
                {
                    "justification": "review this action",
                    "sandbox_permissions": "require_escalated",
                },
                (),
            ),
        )
        for updates, removals in cases:
            with self.subTest(updates=updates, removals=removals):
                with TemporaryDirectory() as raw:
                    root = Path(raw)
                    trace_root = root / "trace-root"
                    trace_root.mkdir()
                    bundle = _write_bundle(
                        trace_root / "exec",
                        commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                        pre_runtime_denied_command_index=1,
                    )
                    _make_pre_runtime_guardian_limit(
                        bundle, error=JUSTIFICATION_ERROR
                    )
                    _update_exec_invocation_arguments(
                        bundle,
                        updates=updates,
                        removals=removals,
                    )
                    metadata = root / "api-metadata.json"
                    _write_metadata(metadata, "main")

                    with self.assertRaisesRegex(
                        HarnessObservationError, "typed pre-runtime rejection"
                    ):
                        project_task_observation(trace_root, metadata)

    def test_pre_runtime_justification_error_is_not_a_guardian_limit(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                pre_runtime_denied_command_index=1,
            )
            _make_pre_runtime_guardian_limit(bundle, error=JUSTIFICATION_ERROR)
            _update_exec_invocation_arguments(
                bundle,
                updates={"justification": "review this action"},
                removals=("sandbox_permissions",),
            )
            _append_linked_local_inference_failure(bundle)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            with self.assertRaisesRegex(
                HarnessObservationError, "populations disagree"
            ):
                project_task_observation(trace_root, metadata)

    def test_pre_runtime_unknown_write_stdin_is_a_zero_output_failed_poll(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                pre_runtime_denied_command_index=1,
            )
            _make_pre_runtime_unknown_write_stdin(bundle)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        encoded = json.dumps(observation, sort_keys=True)
        self.assertEqual(observation["tools"]["command"], 1)
        self.assertEqual(observation["tools"]["command_output_bytes"], 0)
        self.assertEqual(observation["tools"]["max_command_output_bytes"], 0)
        self.assertEqual(observation["tools"]["repeated_exact_commands"], 0)
        self.assertNotIn(UNKNOWN_PROCESS_ERROR, encoded)

    def test_pre_runtime_unknown_write_stdin_binds_the_requested_process(self) -> None:
        cases = (
            (10, UNKNOWN_PROCESS_ERROR),
            (9, "write_stdin failed: stdin is closed"),
        )
        for process_id, error in cases:
            with self.subTest(process_id=process_id, error=error), TemporaryDirectory() as raw:
                root = Path(raw)
                trace_root = root / "trace-root"
                trace_root.mkdir()
                bundle = _write_bundle(
                    trace_root / "exec",
                    commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                    pre_runtime_denied_command_index=1,
                )
                _make_pre_runtime_unknown_write_stdin(
                    bundle, process_id=process_id, error=error
                )
                metadata = root / "api-metadata.json"
                _write_metadata(metadata, "main")

                with self.assertRaisesRegex(
                    HarnessObservationError, "typed missing-process"
                ):
                    project_task_observation(trace_root, metadata)

    def test_pre_runtime_guardian_limit_participates_in_failure_repeat(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=(
                    (COMMAND_BODY, 128, RAW_PATH_BODY),
                    (COMMAND_BODY, 1, RAW_PATH_BODY),
                ),
                pre_runtime_denied_command_index=1,
                code_mode_command_indexes=(2,),
            )
            _make_pre_runtime_guardian_limit(bundle)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(
            observation["tools"]["command_output_bytes"],
            len(OUTPUT_BODY.encode("utf-8")),
        )
        self.assertEqual(observation["tools"]["repeated_exact_commands"], 1)
        self.assertEqual(observation["tools"]["repeated_after_failure"], 1)

    def test_local_guardian_limit_inference_is_not_an_api_response(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            exec_bundle = _write_bundle(
                trace_root / "exec",
                commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                pre_runtime_denied_command_index=1,
            )
            _make_pre_runtime_guardian_limit(exec_bundle)
            guardian_bundle = _write_bundle(
                trace_root / "guardian",
                session_source={"subagent": {"other": "guardian"}},
                commands=(),
                turn_count=2,
            )
            _make_local_guardian_limit_inference(guardian_bundle)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main", "guardian")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["responses"]["total"], 2)
        self.assertEqual(observation["responses"]["guardian"], 1)
        self.assertEqual(observation["tools"]["command"], 1)
        self.assertEqual(observation["tools"]["command_output_bytes"], 0)

    def test_linked_exec_inference_failure_is_not_an_api_response(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                pre_runtime_denied_command_index=1,
            )
            _make_pre_runtime_guardian_limit(bundle)
            _append_linked_local_inference_failure(bundle)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["responses"]["main"], 1)
        self.assertEqual(observation["tools"]["command"], 1)

    def test_unlinked_exec_inference_failure_is_not_exempted(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(trace_root / "exec")
            _append_linked_local_inference_failure(bundle)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            with self.assertRaisesRegex(
                HarnessObservationError, "populations disagree"
            ):
                project_task_observation(trace_root, metadata)

    def test_generic_local_guardian_failure_is_not_exempted(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(trace_root / "exec")
            guardian_bundle = _write_bundle(
                trace_root / "guardian",
                session_source={"subagent": {"other": "guardian"}},
                commands=(),
                turn_count=2,
            )
            _make_local_guardian_limit_inference(
                guardian_bundle,
                error="ordinary local Guardian failure",
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main", "guardian")

            with self.assertRaisesRegex(
                HarnessObservationError, "populations disagree"
            ):
                project_task_observation(trace_root, metadata)

    def test_pre_runtime_guardian_limit_requires_exact_failed_error_shape(self) -> None:
        modes = (
            "ordinary_error",
            "missing_409",
            "ended_completed",
            "extra_result_field",
            "model_requester",
        )
        for mode in modes:
            with self.subTest(mode=mode), TemporaryDirectory() as raw:
                root = Path(raw)
                trace_root = root / "trace-root"
                trace_root.mkdir()
                bundle = _write_bundle(
                    trace_root / "exec",
                    commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                    pre_runtime_denied_command_index=1,
                )
                error = {
                    "ordinary_error": "exec_command failed with status 409",
                    "missing_409": (
                        "exec_command failed; error code "
                        "guardian_logical_request_limit_exceeded"
                    ),
                }.get(mode, GUARDIAN_LIMIT_ERROR)
                _make_pre_runtime_guardian_limit(bundle, error=error)
                events = [
                    json.loads(line)
                    for line in (bundle / "trace.jsonl")
                    .read_text("utf-8")
                    .splitlines()
                ]
                if mode == "ended_completed":
                    ended = next(
                        event
                        for event in events
                        if event["payload"]["type"] == "tool_call_ended"
                    )
                    ended["payload"]["status"] = "completed"
                elif mode == "extra_result_field":
                    ended = next(
                        event
                        for event in events
                        if event["payload"]["type"] == "tool_call_ended"
                    )
                    result_path = bundle / ended["payload"]["result_payload"]["path"]
                    result = json.loads(result_path.read_text("utf-8"))
                    result["output"] = ""
                    result_path.write_text(json.dumps(result), encoding="utf-8")
                elif mode == "model_requester":
                    started = next(
                        event
                        for event in events
                        if event["payload"]["type"] == "tool_call_started"
                    )
                    started["payload"]["requester"] = {"type": "model"}
                (bundle / "trace.jsonl").write_text(
                    "".join(json.dumps(event) + "\n" for event in events),
                    encoding="utf-8",
                )
                metadata = root / "api-metadata.json"
                _write_metadata(metadata, "main")

                with self.assertRaises(HarnessObservationError):
                    project_task_observation(trace_root, metadata)

    def test_native_runtime_cannot_override_source_output_bytes(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(trace_root / "exec")
            runtime_path = next(
                path
                for path in (bundle / "payloads").glob("*.json")
                if "aggregated_output" in json.loads(path.read_text("utf-8"))
            )
            runtime = json.loads(runtime_path.read_text("utf-8"))
            runtime["_source_output_bytes"] = 999_999
            runtime_path.write_text(json.dumps(runtime), encoding="utf-8")
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(
            observation["tools"]["command_output_bytes"],
            len(OUTPUT_BODY.encode("utf-8")),
        )

    def test_missing_command_runtime_requires_exact_pre_runtime_denial(self) -> None:
        modes = (
            "malformed_result",
            "session_id",
            "exit_zero",
            "wrong_surface",
            "render_mismatch",
            "missing_render",
            "error_result",
            "model_requester",
            "failed_status",
            "write_stdin",
            "direct_result",
            "only_runtime_start",
            "only_runtime_end",
        )
        for mode in modes:
            with self.subTest(mode=mode), TemporaryDirectory() as raw:
                root = Path(raw)
                trace_root = root / "trace-root"
                trace_root.mkdir()
                if mode in {
                    "direct_result",
                    "only_runtime_start",
                    "only_runtime_end",
                }:
                    bundle = _write_bundle(trace_root / "exec")
                else:
                    bundle = _write_bundle(
                        trace_root / "exec",
                        commands=((COMMAND_BODY, 128, RAW_PATH_BODY),),
                        pre_runtime_denied_command_index=1,
                    )
                result_paths = [
                    path
                    for path in (bundle / "payloads").glob("*.json")
                    if json.loads(path.read_text("utf-8")).get("type")
                    == "code_mode_response"
                ]
                if result_paths:
                    result_path = result_paths[0]
                    result = json.loads(result_path.read_text("utf-8"))
                    if mode == "malformed_result":
                        result["value"].pop("chunk_id")
                    elif mode == "session_id":
                        result["value"]["session_id"] = 7
                    elif mode == "exit_zero":
                        result["value"]["exit_code"] = 0
                    elif mode == "wrong_surface":
                        result["output_render"]["surface"] = "direct_model"
                    elif mode == "render_mismatch":
                        result["output_render"]["returned_text_bytes"] += 1
                    elif mode == "missing_render":
                        result.pop("output_render")
                    elif mode == "error_result":
                        result["type"] = "error"
                    result_path.write_text(json.dumps(result), encoding="utf-8")

                events = [
                    json.loads(line)
                    for line in (bundle / "trace.jsonl")
                    .read_text("utf-8")
                    .splitlines()
                ]
                if mode == "model_requester":
                    started = next(
                        event
                        for event in events
                        if event["payload"]["type"] == "tool_call_started"
                    )
                    started["payload"]["requester"] = {"type": "model"}
                    started["payload"]["model_visible_call_id"] = "model-tool-1"
                    started["payload"]["code_mode_runtime_tool_id"] = None
                elif mode == "failed_status":
                    ended = next(
                        event
                        for event in events
                        if event["payload"]["type"] == "tool_call_ended"
                    )
                    ended["payload"]["status"] = "failed"
                elif mode == "write_stdin":
                    started = next(
                        event
                        for event in events
                        if event["payload"]["type"] == "tool_call_started"
                    )
                    started["payload"]["kind"] = {"type": "write_stdin"}
                elif mode in {
                    "direct_result",
                    "only_runtime_start",
                    "only_runtime_end",
                }:
                    remove_types = {
                        "direct_result": {
                            "tool_call_runtime_started",
                            "tool_call_runtime_ended",
                        },
                        "only_runtime_start": {"tool_call_runtime_ended"},
                        "only_runtime_end": {"tool_call_runtime_started"},
                    }[mode]
                    events = [
                        event
                        for event in events
                        if event["payload"]["type"] not in remove_types
                    ]
                for seq, event in enumerate(events, start=1):
                    event["seq"] = seq
                (bundle / "trace.jsonl").write_text(
                    "".join(json.dumps(event) + "\n" for event in events),
                    encoding="utf-8",
                )
                metadata = root / "api-metadata.json"
                _write_metadata(metadata, "main")

                with self.assertRaises(HarnessObservationError):
                    project_task_observation(trace_root, metadata)

    def test_turn_duration_uses_the_turn_window_not_rollout_summary(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(trace_root / "exec")
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["turn"]["duration_ms"], 70)
        self.assertNotEqual(observation["turn"]["duration_ms"], 120)

    def test_failed_inference_without_usage_preserves_typed_c11_signal(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=(),
                inference_terminal="failed",
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main", terminal="failed")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["turn"]["status"], "failed")
        self.assertEqual(observation["responses"]["terminal_failed"], 1)
        self.assertEqual(observation["responses"]["missing_or_invalid_usage"], 1)
        self.assertEqual(observation["availability"]["response_usage"], "unmeasurable")
        self.assertEqual(observation["errors"]["context_window_exceeded"], 1)

    def test_pre_response_transport_failure_is_a_projectable_terminal_error(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=(),
                inference_terminal="failed",
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main", terminal="failed")
            value = json.loads(metadata.read_text("utf-8"))
            request = value["requests"][0]
            request["upstream_status"] = 0
            request["settlement_kind"] = "unpriced_fallback"
            for key in (
                "terminal_event_type",
                "terminal_response_status",
                "terminal_error_code",
            ):
                request.pop(key, None)
            request["stream_end_kind"] = "open_error"
            metadata.write_text(json.dumps(value), encoding="utf-8")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["turn"]["status"], "failed")
        self.assertEqual(observation["responses"]["terminal_error"], 1)
        self.assertEqual(observation["responses"]["missing_or_invalid_usage"], 1)
        self.assertEqual(observation["availability"]["response_usage"], "unmeasurable")
        self.assertEqual(observation["errors"]["other"], 1)

    def test_non_sse_response_to_stream_request_is_projectable(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(trace_root / "exec")
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")
            value = json.loads(metadata.read_text("utf-8"))
            request = value["requests"][0]
            request["stream_end_kind"] = "non_sse"
            for key in (
                "terminal_event_type",
                "terminal_response_status",
                "terminal_error_code",
            ):
                request.pop(key, None)
            metadata.write_text(json.dumps(value), encoding="utf-8")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["turn"]["status"], "completed")
        self.assertEqual(observation["responses"]["terminal_completed"], 1)

    def test_pre_response_transport_failure_requires_exact_terminal_shape(self) -> None:
        cases = (
            ("missing kind", None, 0, None),
            ("response already opened", "open_error", 200, None),
            ("terminal event present", "open_error", 0, "error"),
            ("non-SSE without response", "non_sse", 0, None),
        )
        for label, stream_end_kind, status, terminal_event_type in cases:
            with self.subTest(label=label), TemporaryDirectory() as raw:
                root = Path(raw)
                trace_root = root / "trace-root"
                trace_root.mkdir()
                _write_bundle(
                    trace_root / "exec",
                    commands=(),
                    inference_terminal="failed",
                )
                metadata = root / "api-metadata.json"
                _write_metadata(metadata, "main", terminal="failed")
                value = json.loads(metadata.read_text("utf-8"))
                request = value["requests"][0]
                request["upstream_status"] = status
                request["settlement_kind"] = "unpriced_fallback"
                for key in (
                    "stream_end_kind",
                    "terminal_event_type",
                    "terminal_response_status",
                    "terminal_error_code",
                ):
                    request.pop(key, None)
                if stream_end_kind is not None:
                    request["stream_end_kind"] = stream_end_kind
                if terminal_event_type is not None:
                    request["terminal_event_type"] = terminal_event_type
                metadata.write_text(json.dumps(value), encoding="utf-8")

                with self.assertRaisesRegex(
                    HarnessObservationError,
                    "API stream terminal (metadata|enum) is invalid",
                ):
                    project_task_observation(trace_root, metadata)

    def test_completed_inference_without_usage_is_rejected(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(trace_root / "exec")
            response_payload = next(
                path
                for path in (bundle / "payloads").glob("*.json")
                if "token_usage" in json.loads(path.read_text("utf-8"))
            )
            response = json.loads(response_payload.read_text("utf-8"))
            response.pop("token_usage")
            response_payload.write_text(json.dumps(response), encoding="utf-8")
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            with self.assertRaisesRegex(
                HarnessObservationError, "completed inference usage is missing"
            ):
                project_task_observation(trace_root, metadata)

    def test_completed_api_request_without_usage_is_rejected(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(trace_root / "exec")
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")
            value = json.loads(metadata.read_text("utf-8"))
            value["requests"][0]["usage_valid"] = False
            value["requests"][0]["usage"] = None
            metadata.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(
                HarnessObservationError, "completed API response usage is missing"
            ):
                project_task_observation(trace_root, metadata)

    def test_partial_usage_must_match_api_role_distribution(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=(),
                inference_terminal="failed",
            )
            _write_bundle(
                trace_root / "guardian",
                session_source={"subagent": {"other": "guardian"}},
                commands=(),
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main", "guardian")
            value = json.loads(metadata.read_text("utf-8"))
            _mark_request_failed(value["requests"][1])
            metadata.write_text(json.dumps(value), encoding="utf-8")

            with self.assertRaisesRegex(
                HarnessObservationError, "usage coverage disagree"
            ):
                project_task_observation(trace_root, metadata)

    def test_correlated_code_cell_and_tool_render_is_counted_once(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(trace_root / "exec", duplicate_code_cell_render=True)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["tools"]["model_visible_output_deliveries"], 1)
        self.assertEqual(observation["tools"]["model_visible_output_renders"], 1)
        self.assertEqual(
            observation["tools"]["model_visible_source_text_bytes"],
            len(OUTPUT_BODY.encode("utf-8")),
        )

    def test_correlated_code_cell_and_tool_render_must_agree(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec", duplicate_code_cell_render=True
            )
            events = [
                json.loads(line)
                for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
            ]
            rendered = next(
                event
                for event in events
                if event["payload"]["type"] == "code_cell_output_rendered"
            )
            rendered["payload"]["observation"]["returned_text_bytes"] += 1
            (bundle / "trace.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            with self.assertRaisesRegex(
                HarnessObservationError, "correlated output render observations disagree"
            ):
                project_task_observation(trace_root, metadata)

    def test_non_render_tool_is_partial_coverage_not_false_measured(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(trace_root / "exec", include_mcp_without_render=True)
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["availability"]["model_visible_output_truncation"], "partial")
        self.assertEqual(observation["tools"]["model_visible_output_deliveries"], 2)
        self.assertEqual(observation["tools"]["model_visible_output_renders"], 1)
        self.assertEqual(observation["tools"]["model_visible_output_render_missing"], 1)
        comparison = compare_task_observations(observation, observation)
        self.assertEqual(comparison["deltas"]["tools.model_visible_output_deliveries"], 0)
        self.assertIsNone(
            comparison["deltas"]["tools.model_visible_source_text_bytes"]
        )

    def test_only_non_render_tool_is_unmeasurable_not_false_zero(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=(),
                include_mcp_without_render=True,
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(
            observation["availability"]["model_visible_output_truncation"],
            "unmeasurable",
        )
        self.assertEqual(observation["tools"]["model_visible_output_deliveries"], 1)
        self.assertEqual(observation["tools"]["model_visible_output_renders"], 0)
        self.assertEqual(observation["tools"]["model_visible_output_render_missing"], 1)

    def test_public_exec_early_errors_are_missing_render_not_measured_zero(self) -> None:
        for phase in ("before_cell_error", "after_cell_start_error"):
            with self.subTest(phase=phase), TemporaryDirectory() as raw:
                root = Path(raw)
                trace_root = root / "trace-root"
                trace_root.mkdir()
                _write_bundle(
                    trace_root / "exec",
                    commands=(),
                    code_mode_exec_phase=phase,
                )
                metadata = root / "api-metadata.json"
                _write_metadata(metadata, "main")

                observation = project_task_observation(trace_root, metadata)

            self.assertEqual(
                observation["availability"]["model_visible_output_truncation"],
                "unmeasurable",
            )
            self.assertEqual(
                observation["tools"]["model_visible_output_deliveries"], 1
            )
            self.assertEqual(observation["tools"]["model_visible_output_renders"], 0)
            self.assertEqual(
                observation["tools"]["model_visible_output_render_missing"], 1
            )

    def test_public_exec_render_requires_initial_cell_response(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=(),
                code_mode_exec_phase="before_cell_error",
            )
            events = [
                json.loads(line)
                for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
            ]
            delivery = next(
                event
                for event in events
                if event["payload"]["type"] == "code_mode_exec_output_delivered"
            )
            delivery["payload"]["output_render"] = {
                "surface": "direct_model",
                "source_text_bytes": len(OUTPUT_BODY.encode("utf-8")),
                "collection_omitted_bytes": 0,
                "requested_max_output_tokens": 64,
                "effective_max_output_tokens": 64,
                "returned_text_bytes": len(OUTPUT_BODY.encode("utf-8")),
                "presentation_truncated": False,
            }
            (bundle / "trace.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            with self.assertRaisesRegex(
                HarnessObservationError,
                "public exec output render lifecycle is invalid",
            ):
                project_task_observation(trace_root, metadata)

    def test_public_exec_success_delivery_and_render_are_counted_once(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=(),
                code_mode_exec_phase="success",
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(
            observation["availability"]["model_visible_output_truncation"],
            "measured",
        )
        self.assertEqual(observation["tools"]["model_visible_output_deliveries"], 1)
        self.assertEqual(observation["tools"]["model_visible_output_renders"], 1)
        self.assertEqual(observation["tools"]["model_visible_output_render_missing"], 0)
        self.assertEqual(
            observation["tools"]["model_visible_source_text_bytes"],
            len(OUTPUT_BODY.encode("utf-8")),
        )
        self.assertEqual(
            observation["tools"]["model_visible_returned_text_bytes"],
            len(OUTPUT_BODY.encode("utf-8")),
        )

    def test_final_public_exec_missing_render_overrides_stale_cell_render(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec", duplicate_code_cell_render=True
            )
            events = [
                json.loads(line)
                for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
            ]
            delivery = next(
                event
                for event in events
                if event["payload"]["type"] == "code_mode_exec_output_delivered"
            )
            delivery["payload"].pop("output_render")
            (bundle / "trace.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(
            observation["availability"]["model_visible_output_truncation"],
            "unmeasurable",
        )
        self.assertEqual(observation["tools"]["model_visible_output_deliveries"], 1)
        self.assertEqual(observation["tools"]["model_visible_output_renders"], 0)
        self.assertEqual(observation["tools"]["model_visible_output_render_missing"], 1)

    def test_dangling_code_cell_without_delivery_fails_closed(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(
                trace_root / "exec",
                commands=(),
                code_mode_exec_phase="after_cell_start_error",
            )
            events = [
                json.loads(line)
                for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
            ]
            events = [
                event
                for event in events
                if event["payload"]["type"] != "code_mode_exec_output_delivered"
            ]
            (bundle / "trace.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in events),
                encoding="utf-8",
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            with self.assertRaisesRegex(
                HarnessObservationError, "code cell output delivery is incomplete"
            ):
                project_task_observation(trace_root, metadata)

    def test_duplicate_public_exec_delivery_fails_closed(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=(),
                code_mode_exec_phase="before_cell_error",
                duplicate_public_exec_delivery=True,
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            with self.assertRaisesRegex(
                HarnessObservationError, "public exec output delivery is duplicated"
            ):
                project_task_observation(trace_root, metadata)

    def test_runtime_render_availability_is_independent_from_model_surface(self) -> None:
        value = _observation()
        value["availability"]["code_mode_runtime_output_truncation"] = "unmeasurable"
        value["tools"]["code_mode_runtime_output_deliveries"] = 1
        value["tools"]["code_mode_runtime_output_render_missing"] = 1

        validated = validate_task_observation(value)
        comparison = compare_task_observations(value, value)

        self.assertEqual(
            validated["availability"]["model_visible_output_truncation"], "measured"
        )
        self.assertIsNone(
            comparison["deltas"]["tools.code_mode_runtime_source_text_bytes"]
        )
        self.assertEqual(
            comparison["deltas"]["tools.model_visible_source_text_bytes"], 0
        )

    def test_reused_guardian_bundle_accepts_multiple_terminal_turns(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(trace_root / "exec")
            _write_bundle(
                trace_root / "guardian",
                session_source={"subagent": {"other": "guardian"}},
                commands=(),
                turn_count=2,
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main", "guardian", "guardian")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["source"]["guardian_trace_bundles"], 1)
        self.assertEqual(observation["responses"]["total"], 3)
        self.assertEqual(observation["responses"]["guardian"], 2)

    def test_exact_repeats_include_cwd_and_only_immediate_failure(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            _write_bundle(
                trace_root / "exec",
                commands=(
                    (COMMAND_BODY, 1, "/private/first"),
                    (COMMAND_BODY, 0, "/private/second"),
                    (COMMAND_BODY, 0, "/private/second"),
                ),
            )
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            observation = project_task_observation(trace_root, metadata)

        self.assertEqual(observation["tools"]["repeated_exact_commands"], 1)
        self.assertEqual(observation["tools"]["repeated_after_failure"], 0)

    def test_projection_rejects_command_result_without_native_render_facts(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            trace_root = root / "trace-root"
            trace_root.mkdir()
            bundle = _write_bundle(trace_root / "exec")
            result_payload = next(
                path
                for path in (bundle / "payloads").glob("*.json")
                if json.loads(path.read_text("utf-8")).get("type") == "direct_response"
            )
            result = json.loads(result_payload.read_text("utf-8"))
            result.pop("output_render")
            result_payload.write_text(json.dumps(result), encoding="utf-8")
            metadata = root / "api-metadata.json"
            _write_metadata(metadata, "main")

            with self.assertRaisesRegex(HarnessObservationError, "render observation is missing"):
                project_task_observation(trace_root, metadata)

    def test_projection_rejects_missing_duplicate_nonfinal_or_dropped_capture_end(self) -> None:
        for mode in ("missing", "duplicate", "nonfinal", "dropped"):
            with self.subTest(mode=mode), TemporaryDirectory() as raw:
                root = Path(raw)
                trace_root = root / "trace-root"
                trace_root.mkdir()
                bundle = _write_bundle(trace_root / "exec")
                events = [
                    json.loads(line)
                    for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
                ]
                if mode == "missing":
                    events.pop()
                elif mode == "duplicate":
                    events.append(copy.deepcopy(events[-1]))
                elif mode == "nonfinal":
                    events[-1], events[-2] = events[-2], events[-1]
                else:
                    events[-1]["payload"]["dropped_operations"] = 1
                for seq, event in enumerate(events, start=1):
                    event["seq"] = seq
                (bundle / "trace.jsonl").write_text(
                    "".join(json.dumps(event) + "\n" for event in events),
                    encoding="utf-8",
                )
                metadata = root / "api-metadata.json"
                _write_metadata(metadata, "main")

                with self.assertRaises(HarnessObservationError):
                    project_task_observation(trace_root, metadata)

    def test_projection_rejects_empty_or_mismatched_api_population(self) -> None:
        for roles in ((), ("main", "main")):
            with self.subTest(roles=roles), TemporaryDirectory() as raw:
                root = Path(raw)
                trace_root = root / "trace-root"
                trace_root.mkdir()
                _write_bundle(trace_root / "exec")
                metadata = root / "api-metadata.json"
                _write_metadata(metadata, *roles)

                with self.assertRaises(HarnessObservationError):
                    project_task_observation(trace_root, metadata)


if __name__ == "__main__":
    unittest.main()
