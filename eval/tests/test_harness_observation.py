from __future__ import annotations

import copy
import unittest

from rondo_eval.harness_observation import HarnessObservationError
from rondo_eval.harness_observation import compare_task_observations
from rondo_eval.harness_observation import validate_task_observation


def _observation() -> dict[str, object]:
    return {
        "schema_version": 1,
        "scope": "rondo_local_task",
        "event_stream_complete": True,
        "turn": {"status": "completed", "duration_ms": 20, "items_view": "full"},
        "responses": {
            "completed": 1,
            "with_valid_usage": 1,
            "missing_usage": 0,
            "invalid_usage": 0,
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 4,
                "cache_write_input_tokens": 0,
                "output_tokens": 2,
                "reasoning_output_tokens": 1,
            },
        },
        "errors": {
            "total": 0,
            "retryable": 0,
            "context_window_exceeded": 0,
            "bad_request": 0,
            "response_stream_failure": 0,
            "response_retry_limit": 0,
            "budget_or_usage_limit": 0,
            "other": 0,
        },
        "tools": {
            "command": 1,
            "mcp": 0,
            "dynamic": 0,
            "with_valid_duration": 1,
            "missing_or_invalid_duration": 0,
            "total_duration_ms": 5,
            "command_output_bytes": 3,
            "max_command_output_bytes": 3,
            "repeated_exact_commands": 0,
            "repeated_after_failure": 0,
        },
        "compactions": {"completed": 0, "coverage": "measured"},
        "guardian": {
            "started": 0,
            "completed": 0,
            "with_valid_duration": 0,
            "invalid_duration": 0,
            "total_duration_ms": 0,
            "approved": 0,
            "denied": 0,
            "timed_out": 0,
            "aborted": 0,
            "non_terminal": 0,
        },
        "unavailable": {
            "turn_phase_profile": True,
            "model_visible_output_truncation": True,
            "compaction_reason_and_tokens": True,
            "direct_tool_dispatch_handler_split": True,
            "guardian_token_breakdown": True,
        },
    }


class HarnessObservationTests(unittest.TestCase):
    def test_exact_schema_accepts_zero_as_measured(self) -> None:
        value = _observation()

        validated = validate_task_observation(value)

        self.assertEqual(validated, value)
        self.assertIsNot(validated, value)
        self.assertEqual(validated["compactions"]["completed"], 0)
        self.assertEqual(validated["compactions"]["coverage"], "measured")

    def test_extra_body_field_is_rejected(self) -> None:
        value = _observation()
        value["prompt"] = "private body"

        with self.assertRaisesRegex(HarnessObservationError, "schema is invalid"):
            validate_task_observation(value)

    def test_missing_usage_is_not_silently_zero(self) -> None:
        value = _observation()
        responses = value["responses"]
        responses["with_valid_usage"] = 0
        responses["missing_usage"] = 1
        for key in responses["usage"]:
            responses["usage"][key] = 0

        validated = validate_task_observation(value)

        self.assertEqual(validated["responses"]["missing_usage"], 1)
        comparison = compare_task_observations(_observation(), validated)
        self.assertFalse(comparison["comparable"])
        self.assertEqual(set(comparison["deltas"].values()), {None})

    def test_comparison_requires_complete_full_item_views(self) -> None:
        before = _observation()
        after = copy.deepcopy(before)
        after["tools"]["repeated_exact_commands"] = 2
        after["turn"]["duration_ms"] = 25

        comparison = compare_task_observations(before, after)

        self.assertTrue(comparison["comparable"])
        self.assertEqual(comparison["deltas"]["tools.repeated_exact_commands"], 2)
        self.assertEqual(comparison["deltas"]["turn.duration_ms"], 5)

        after["event_stream_complete"] = False
        incomplete = compare_task_observations(before, after)
        self.assertFalse(incomplete["comparable"])
        self.assertEqual(set(incomplete["deltas"].values()), {None})

    def test_missing_duration_or_compaction_coverage_blocks_comparison(self) -> None:
        before = _observation()
        variants = []

        tool_missing = copy.deepcopy(before)
        tool_missing["tools"]["with_valid_duration"] = 0
        tool_missing["tools"]["missing_or_invalid_duration"] = 1
        tool_missing["tools"]["total_duration_ms"] = 0
        variants.append(tool_missing)

        guardian_missing = copy.deepcopy(before)
        guardian_missing["guardian"].update(
            {
                "started": 1,
                "completed": 1,
                "with_valid_duration": 0,
                "invalid_duration": 1,
                "approved": 1,
            }
        )
        variants.append(guardian_missing)

        guardian_non_terminal = copy.deepcopy(before)
        guardian_non_terminal["guardian"].update(
            {
                "started": 1,
                "completed": 1,
                "with_valid_duration": 1,
                "total_duration_ms": 3,
                "non_terminal": 1,
            }
        )
        variants.append(guardian_non_terminal)

        compaction_missing = copy.deepcopy(before)
        compaction_missing["compactions"]["coverage"] = "partial"
        variants.append(compaction_missing)

        non_terminal_turn = copy.deepcopy(before)
        non_terminal_turn["turn"]["status"] = "in_progress"
        variants.append(non_terminal_turn)

        for variant in variants:
            with self.subTest(variant=variant):
                comparison = compare_task_observations(before, variant)
                self.assertFalse(comparison["comparable"])
                self.assertEqual(set(comparison["deltas"].values()), {None})


if __name__ == "__main__":
    unittest.main()
