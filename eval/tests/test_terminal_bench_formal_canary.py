from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.terminal_bench import formal_canary  # noqa: E402
from rondo_eval.config import RepoPaths  # noqa: E402


class FormalCanaryEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        pointer = self.root / "eval/locks/p2-b7-active.json"
        pointer.parent.mkdir(parents=True)
        pointer.write_text(
            '{"schema_version":1,"active_lock":null}\n', encoding="utf-8"
        )
        self.paths = RepoPaths(self.root, self.root)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_default_action_is_zero_api_status(self) -> None:
        with (
            mock.patch.object(
                formal_canary.RepoPaths, "discover", return_value=self.paths
            ),
            mock.patch.object(
                formal_canary,
                "load_runtime_config",
                side_effect=AssertionError("status loaded provider config"),
            ),
            mock.patch.object(
                formal_canary,
                "baseline_main",
                side_effect=AssertionError("status entered paid runner"),
            ),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = formal_canary.main([])
        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "idle")
        self.assertEqual(payload["paid_requests_sent"], 0)

    def test_run_requires_the_literal_paid_action_before_preparation(self) -> None:
        with (
            mock.patch.object(
                formal_canary.RepoPaths, "discover", return_value=self.paths
            ),
            mock.patch.object(
                formal_canary,
                "prepare",
                side_effect=AssertionError("unacknowledged run prepared"),
            ),
            mock.patch.object(
                formal_canary,
                "baseline_main",
                side_effect=AssertionError("unacknowledged run entered runner"),
            ),
            self.assertRaisesRegex(
                formal_canary.FormalCanaryError, "paid action is required"
            ),
        ):
            formal_canary.main(["run"])

    def test_acknowledged_run_delegates_only_after_preflight_is_ready(self) -> None:
        with (
            mock.patch.object(
                formal_canary.RepoPaths, "discover", return_value=self.paths
            ),
            mock.patch.object(
                formal_canary,
                "prepare",
                return_value={"preflight_receipts_ready": True},
            ),
            mock.patch.object(formal_canary, "baseline_main", return_value=7) as run,
        ):
            result = formal_canary.main(
                [
                    "run",
                    "--paid-action",
                    formal_canary.PAID_ACTION,
                    "--docker-host-volume",
                    "/tmp/docker-host",
                    "--results-worktree-root",
                    "/tmp/results",
                    "--rondo-measurement-worktree-root",
                    "/tmp/rondo",
                    "--codex-measurement-worktree-root",
                    "/tmp/codex",
                ]
            )
        self.assertEqual(result, 7)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
