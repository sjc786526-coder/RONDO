from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rondo_eval.config import RepoPaths
from rondo_eval.harness_census import HarnessCensusError
from rondo_eval.harness_census import assert_public_report
from rondo_eval.harness_census import build_census
from rondo_eval.harness_census import compare_census_reports
from rondo_eval.harness_census import validate_census_delta
from rondo_eval.harness_census import validate_census_report


def _api_metadata() -> dict[str, object]:
    return {
        "schema_version": 1,
        "requests": [
            {
                "role": "main",
                "stream_end_kind": "terminal",
                "terminal_event_type": "response.completed",
                "terminal_response_status": "completed",
                "upstream_status": 200,
                "usage_valid": True,
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 75,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 10,
                },
            }
        ],
    }


class HarnessCensusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.common = root / "common"
        self.worktree = root / "worktree"
        self.common.mkdir()
        self.worktree.mkdir()
        self.paths = RepoPaths(common_root=self.common, worktree_root=self.worktree)

    def _artifact(self, name: str) -> Path:
        root = self.common / "eval-data/runs" / name
        (root / "harbor/agent").mkdir(parents=True)
        (root / "api-metadata.json").write_text(
            json.dumps(_api_metadata()), encoding="utf-8"
        )
        return root

    def test_partial_redaction_stays_missing_and_report_is_body_free(self) -> None:
        first = self._artifact("first")
        second = self._artifact("second")
        private_command = "secret command body"
        private_output = "sensitive output"
        events = [
            {"type": "thread.started", "thread_id": "private-thread"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "id": "private-item-1",
                    "command": private_command,
                    "aggregated_output": "x" * 10_001,
                    "exit_code": 1,
                    "status": "failed",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "id": "private-item-2",
                    "command": private_command,
                    "aggregated_output": private_output,
                    "exit_code": 0,
                    "status": "completed",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "id": "private-item-3",
                    "command": private_command,
                    "aggregated_output": "done",
                    "exit_code": 0,
                    "status": "completed",
                },
            },
            {"type": "turn.completed", "usage": {}},
        ]
        (first / "harbor/agent/codex.txt").write_text(
            "".join(json.dumps(item) + "\n" for item in events), encoding="utf-8"
        )
        (second / "harbor/agent/codex.txt.redacted.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "reason": "sensitive_private_artifact_omitted",
                    "source_size_bytes": 123,
                    "source_sha256": "a" * 64,
                }
            ),
            encoding="utf-8",
        )
        records = [
            {
                "artifacts": "eval-data/runs/first",
                "tasks": [{"task_id": "private-task"}],
                "metrics": {"wall_seconds": 1.25},
            },
            {
                "artifacts": "eval-data/runs/second",
                "tasks": [{"task_id": "private-task"}],
                "metrics": {"wall_seconds": 2.25},
            },
        ]
        identity = SimpleNamespace(
            schema_version=7,
            campaign_id="p2-b7-canary-baseline-v28",
            lock_sha256="a" * 64,
            catalog=SimpleNamespace(tasks=(object(),)),
        )
        with mock.patch(
            "rondo_eval.harness_census._eligible_records",
            return_value=(records, 2, identity),
        ):
            report = build_census(self.paths)

        self.assertEqual(report["coverage"]["exec_jsonl"]["measured_runs"], 1)
        self.assertEqual(report["coverage"]["exec_jsonl"]["missing"]["redacted"], 1)
        self.assertEqual(report["candidates"]["C1"]["status"], "observed_weak")
        self.assertEqual(report["candidates"]["C2"]["status"], "observed_weak")
        self.assertEqual(report["aggregates"]["exec"]["repeated_after_failure"], 2)
        encoded = json.dumps(report, sort_keys=True)
        for forbidden in [
            private_command,
            private_output,
            "private-thread",
            "private-item",
            "private-task",
            "eval-data/runs",
        ]:
            self.assertNotIn(forbidden, encoded)

    def test_public_allowlist_rejects_body_and_float(self) -> None:
        with self.assertRaisesRegex(HarnessCensusError, "key is not allowlisted"):
            assert_public_report({"prompt": "secret"})
        with self.assertRaisesRegex(HarnessCensusError, "scalar type"):
            assert_public_report({"schema_version": 1.5})

    def test_same_report_comparison_is_zero_and_body_free(self) -> None:
        first = self._artifact("only")
        (first / "harbor/agent/codex.txt").write_text(
            json.dumps({"type": "turn.completed", "usage": {}}) + "\n",
            encoding="utf-8",
        )
        records = [
            {
                "artifacts": "eval-data/runs/only",
                "tasks": [{"task_id": "private-task"}],
                "metrics": {"wall_seconds": 1},
            }
        ]
        identity = SimpleNamespace(
            schema_version=7,
            campaign_id="p2-b7-canary-baseline-v28",
            lock_sha256="b" * 64,
            catalog=SimpleNamespace(tasks=(object(),)),
        )
        with mock.patch(
            "rondo_eval.harness_census._eligible_records",
            return_value=(records, 1, identity),
        ):
            report = build_census(self.paths)

        comparison = compare_census_reports(report, report)
        self.assertTrue(comparison["comparable"])
        self.assertEqual(set(comparison["deltas"].values()), {0})
        self.assertEqual(validate_census_delta(comparison), comparison)

        malformed = json.loads(json.dumps(report))
        malformed["scope"]["requests"] = 1
        with self.assertRaisesRegex(HarnessCensusError, "scope schema"):
            validate_census_report(malformed)

    def test_different_coverage_returns_only_null_deltas(self) -> None:
        measured = self._artifact("measured")
        redacted = self._artifact("redacted")
        (measured / "harbor/agent/codex.txt").write_text(
            json.dumps({"type": "turn.completed", "usage": {}}) + "\n",
            encoding="utf-8",
        )
        (redacted / "harbor/agent/codex.txt.redacted.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "reason": "sensitive_private_artifact_omitted",
                    "source_size_bytes": 1,
                    "source_sha256": "c" * 64,
                }
            ),
            encoding="utf-8",
        )
        identity = SimpleNamespace(
            schema_version=7,
            campaign_id="p2-b7-canary-baseline-v28",
            lock_sha256="c" * 64,
            catalog=SimpleNamespace(tasks=(object(),)),
        )

        def report_for(path: Path) -> dict[str, object]:
            record = {
                "artifacts": path.relative_to(self.common).as_posix(),
                "tasks": [{"task_id": "private-task"}],
                "metrics": {"wall_seconds": 1},
            }
            with mock.patch(
                "rondo_eval.harness_census._eligible_records",
                return_value=([record], 1, identity),
            ):
                return build_census(self.paths)

        measured_report = report_for(measured)
        comparison = compare_census_reports(measured_report, report_for(redacted))

        self.assertFalse(comparison["comparable"])
        self.assertEqual(set(comparison["deltas"].values()), {None})
        self.assertEqual(validate_census_delta(comparison), comparison)

        missing_usage = json.loads(json.dumps(measured_report))
        api = missing_usage["aggregates"]["api"]
        api["valid_usage"] = 0
        api["missing_or_invalid_usage"] = 1
        for key in {
            "input_tokens",
            "cached_input_tokens",
            "cache_write_input_tokens",
            "output_tokens",
        }:
            api["usage"][key] = 0
        api["usage"]["cached_input_rate_ppm"] = None
        missing_usage["auxiliaries"]["C4"]["cached_input_rate_ppm"] = None
        usage_comparison = compare_census_reports(measured_report, missing_usage)
        self.assertFalse(usage_comparison["comparable"])
        self.assertEqual(set(usage_comparison["deltas"].values()), {None})

    def test_intermediate_directory_symlink_is_not_followed(self) -> None:
        artifact = self._artifact("linked")
        outside = self.common / "outside"
        (outside / "agent").mkdir(parents=True)
        (outside / "agent/codex.txt").write_text(
            json.dumps({"type": "turn.completed", "usage": {}}) + "\n",
            encoding="utf-8",
        )
        (artifact / "harbor/agent").rmdir()
        (artifact / "harbor").rmdir()
        (artifact / "harbor").symlink_to(outside, target_is_directory=True)
        record = {
            "artifacts": artifact.relative_to(self.common).as_posix(),
            "tasks": [{"task_id": "private-task"}],
            "metrics": {"wall_seconds": 1},
        }
        identity = SimpleNamespace(
            schema_version=7,
            campaign_id="p2-b7-canary-baseline-v28",
            lock_sha256="d" * 64,
            catalog=SimpleNamespace(tasks=(object(),)),
        )
        with mock.patch(
            "rondo_eval.harness_census._eligible_records",
            return_value=([record], 1, identity),
        ):
            report = build_census(self.paths)

        self.assertEqual(report["coverage"]["exec_jsonl"]["measured_runs"], 0)
        self.assertEqual(report["coverage"]["exec_jsonl"]["missing"]["invalid"], 1)
        self.assertEqual(report["candidates"]["C1"]["status"], "unmeasurable")


if __name__ == "__main__":
    unittest.main()
