from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from rondo_eval.harness_observation import HarnessObservationError
from rondo_eval.harness_observation import compare_task_observations
from rondo_eval.harness_observation import project_task_observation
from rondo_eval.harness_observation import validate_task_observation
from tests.test_team_lens import BODY_SENTINELS
from tests.test_team_lens import COMMAND_BODY
from tests.test_team_lens import NativeBundleBuilder
from tests.test_team_lens import OUTPUT_BODY
from tests.test_team_lens import PROMPT_BODY
from tests.test_team_lens import RAW_PATH_BODY


def _observation() -> dict[str, object]:
    return {
        "schema_version": 1,
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
            "model_visible_output_renders": 1,
            "model_visible_source_text_bytes": len(OUTPUT_BODY.encode("utf-8")),
            "model_visible_returned_text_bytes": len(OUTPUT_BODY.encode("utf-8")),
            "model_visible_presentation_truncations": 0,
            "model_visible_collection_omission_events": 0,
            "model_visible_collection_omitted_bytes": 0,
            "code_mode_runtime_output_renders": 0,
            "code_mode_runtime_source_text_bytes": 0,
            "code_mode_runtime_returned_text_bytes": 0,
            "code_mode_runtime_presentation_truncations": 0,
            "code_mode_runtime_collection_omission_events": 0,
            "code_mode_runtime_collection_omitted_bytes": 0,
            "repeated_exact_commands": 0,
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
        for index, (command, exit_code, cwd) in enumerate(commands, start=1):
            builder.tool(
                f"tool-{index}",
                name="exec_command",
                kind="exec_command",
                arguments={"cmd": command, "cwd": cwd},
                result=model_output,
                result_mode="direct",
                runtime_end={
                    "process_id": f"terminal-{index}",
                    "command": [command],
                    "cwd": cwd,
                    "aggregated_output": command_output,
                    "status": "completed" if exit_code == 0 else "failed",
                    "exit_code": exit_code,
                    "duration": {"secs": 0, "nanos": 5_000_000},
                },
                output_render={
                    "surface": "direct_model",
                    "source_text_bytes": len(command_output.encode("utf-8")),
                    "collection_omitted_bytes": collection_omitted_bytes,
                    "requested_max_output_tokens": 64,
                    "effective_max_output_tokens": 64,
                    "returned_text_bytes": len(model_output.encode("utf-8")),
                    "presentation_truncated": presentation_truncated,
                },
                turn_id=turn_id,
            )
        builder.event(
            {
                "type": "codex_turn_ended",
                "codex_turn_id": turn_id,
                "status": "completed",
            },
            thread_id=builder.root_thread,
            turn_id=turn_id,
        )
    builder.event(
        {
            "type": "thread_ended",
            "thread_id": builder.root_thread,
            "status": "completed",
        },
        thread_id=builder.root_thread,
    )
    builder.event({"type": "rollout_ended", "status": "completed"})
    builder.event({"type": "trace_capture_ended", "dropped_operations": 0})
    return builder.write()


def _write_metadata(path: Path, *roles: str) -> None:
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
                        "usage_valid": True,
                        "charged_usd": "0.010000",
                        "attempt_count": 1,
                        "settlement_kind": "usage_priced",
                        "usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 2,
                            "cache_write_input_tokens": 1,
                            "output_tokens": 4,
                        },
                        "stream_end_kind": "terminal",
                        "terminal_event_type": "response.completed",
                        "terminal_response_status": "completed",
                        "terminal_error_code": None,
                    }
                    for index, role in enumerate(roles, start=1)
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


class HarnessObservationTests(unittest.TestCase):
    def test_exact_schema_and_comparison_keep_unmeasurable_fields_null(self) -> None:
        before = _observation()
        after = copy.deepcopy(before)
        after["turn"]["duration_ms"] = 125
        after["tools"]["command_output_bytes"] += 5
        after["tools"]["max_command_output_bytes"] += 5

        validated = validate_task_observation(before)
        comparison = compare_task_observations(before, after)

        self.assertEqual(validated, before)
        self.assertIsNone(validated["compactions"]["completed"])
        self.assertTrue(comparison["comparable"])
        self.assertEqual(comparison["deltas"]["turn.duration_ms"], 25)
        self.assertEqual(comparison["deltas"]["tools.command_output_bytes"], 5)

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
        self.assertEqual(observation["tools"]["repeated_after_failure"], 1)
        self.assertTrue(all(body not in encoded for body in BODY_SENTINELS))

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
