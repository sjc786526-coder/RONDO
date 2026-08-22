from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from decimal import Decimal
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

    def test_completed_repository_state_is_idle(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        payload = formal_canary.status(paths)

        self.assertEqual(payload["status"], "idle")
        self.assertIsNone(payload["active_lock"])
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
            mock.patch.object(
                formal_canary,
                "load_campaign_identity",
                return_value=mock.Mock(
                    budget={
                        "task_budget_id": "plan-051-direction0-schema-v7-canary"
                    }
                ),
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

    def test_new_task_paid_action_is_bound_to_its_budget_identity(self) -> None:
        identity = mock.Mock(
            budget={"task_budget_id": "direction0-local-optimization-052"}
        )
        with (
            mock.patch.object(
                formal_canary.RepoPaths, "discover", return_value=self.paths
            ),
            mock.patch.object(
                formal_canary, "load_campaign_identity", return_value=identity
            ),
            mock.patch.object(
                formal_canary,
                "prepare",
                side_effect=AssertionError("wrong acknowledgment prepared"),
            ),
            self.assertRaisesRegex(
                formal_canary.FormalCanaryError,
                "differs from the task budget identity",
            ),
        ):
            formal_canary.main(
                ["run", "--paid-action", formal_canary.PAID_ACTION]
            )

    def test_preflight_routes_through_the_shared_watchdog(self) -> None:
        metrics = self.root / "metrics/preflight-v29"
        with mock.patch.object(
            formal_canary.subprocess,
            "run",
            return_value=mock.Mock(returncode=0),
        ) as run:
            result = formal_canary.run_preflight(
                self.paths,
                mock.Mock(
                    docker_host_volume=Path("/tmp/docker-host"),
                    metrics_dir=metrics,
                ),
            )

        self.assertEqual(result, 0)
        argv = run.call_args.args[0]
        self.assertEqual(argv[0], str(self.root / "scripts/with-build-lock.sh"))
        self.assertIn("rondo_eval.terminal_bench.preflight_producer", argv)
        self.assertEqual(run.call_args.kwargs["cwd"], self.root / "eval")
        self.assertEqual(
            run.call_args.kwargs["env"]["RONDO_BUILD_METRICS_DIR"], str(metrics)
        )
        self.assertNotIn("HTTP_PROXY", run.call_args.kwargs["env"])

    def test_initialize_accepts_explicit_new_local_identity_and_budget(self) -> None:
        contract = self.root / "comparison.json"
        contract.write_text('{"product":"rondo-local"}\n', encoding="utf-8")
        prepared = {
            "preflight_receipts_ready": False,
            "paid_requests_sent": 0,
        }
        with (
            mock.patch.object(
                formal_canary.RepoPaths, "discover", return_value=self.paths
            ),
            mock.patch.object(
                formal_canary,
                "generate_successor_lock",
                return_value=(
                    self.root / "eval/locks/p2-b7-canary-baseline-v29.json",
                    Decimal("0.000000"),
                ),
            ) as generate,
            mock.patch.object(formal_canary, "prepare", return_value=prepared),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            result = formal_canary.main(
                [
                    "initialize",
                    "--campaign-id",
                    "p2-b7-canary-baseline-v29",
                    "--batch-id",
                    "p2-b7-canary-v29",
                    "--run-id-date",
                    "20260822",
                    "--run-id-sequence-base",
                    "500001928",
                    "--comparison-contract",
                    str(contract),
                    "--rondo-runtime-manifest",
                    "/tmp/rondo-manifest.json",
                    "--rondo-source-commit",
                    "1" * 40,
                    "--codex-runtime-manifest",
                    "/tmp/codex-manifest.json",
                    "--price-snapshot-date",
                    "2026-08-22",
                    "--task-budget-id",
                    "direction0-local-optimization-052",
                    "--task-budget-cap-usd",
                    "125.000000",
                    "--task-budget-prior-estimated-usd",
                    "0.000000",
                ]
            )

        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "initialized")
        self.assertEqual(payload["next_action"], "preflight")
        self.assertEqual(generate.call_args.kwargs["rondo_source_commit"], "1" * 40)
        self.assertEqual(
            generate.call_args.kwargs["task_budget_id"],
            "direction0-local-optimization-052",
        )
        self.assertEqual(
            generate.call_args.kwargs["task_budget_cap_usd"],
            Decimal("125.000000"),
        )

    def test_finalize_retires_only_a_closed_terminal_identity(self) -> None:
        identity = mock.Mock(
            campaign_id="p2-b7-canary-baseline-v28",
            batch_id="p2-b7-canary-v28",
            enforces_fair_comparison=True,
            budget={
                "task_budget_id": "plan-051-direction0-schema-v7-canary",
                "task_budget_cap_usd": "400.000000",
                "task_budget_prior_estimated_usd": "0.270445",
            },
        )
        state_path = (
            self.root
            / "eval-data/campaigns/p2-b7-canary-baseline-v28/state.json"
        )
        state_path.parent.mkdir(parents=True)
        state_path.write_text('{"status":"passed"}\n', encoding="utf-8")
        closed = {
            "active_identity": None,
            "closed_identities": [
                {
                    "campaign_id": identity.campaign_id,
                    "batch_id": identity.batch_id,
                    "terminal_status": "passed",
                }
            ],
        }
        runner_args = [
            "finalize",
            "--docker-host-volume",
            "/tmp/docker-host",
            "--results-worktree-root",
            "/tmp/results",
            "--rondo-measurement-worktree-root",
            "/tmp/rondo",
            "--codex-measurement-worktree-root",
            "/tmp/codex",
        ]
        with (
            mock.patch.object(
                formal_canary.RepoPaths, "discover", return_value=self.paths
            ),
            mock.patch.object(
                formal_canary, "load_campaign_identity", return_value=identity
            ),
            mock.patch.object(formal_canary, "baseline_main", return_value=0),
            mock.patch.object(formal_canary, "load_task_budget", return_value=closed),
            mock.patch.object(
                formal_canary, "retire_active_campaign_pointer"
            ) as retire,
        ):
            result = formal_canary.main(runner_args)

        self.assertEqual(result, 0)
        retire.assert_called_once_with(self.paths, identity=identity)

    def test_failed_baseline_closes_and_retires_before_returning_two(self) -> None:
        identity = mock.Mock(
            campaign_id="p2-b7-canary-baseline-v29",
            batch_id="p2-b7-canary-v29",
            enforces_fair_comparison=True,
            budget={
                "task_budget_id": "direction0-local-optimization-052",
                "task_budget_cap_usd": "125.000000",
                "task_budget_prior_estimated_usd": "0.000000",
            },
        )
        state_path = (
            self.root
            / "eval-data/campaigns/p2-b7-canary-baseline-v29/state.json"
        )
        state_path.parent.mkdir(parents=True)
        state_path.write_text('{"status":"failed"}\n', encoding="utf-8")
        active = {
            "active_identity": {
                "campaign_id": identity.campaign_id,
                "batch_id": identity.batch_id,
            },
            "closed_identities": [],
        }
        closed = {
            "active_identity": None,
            "closed_identities": [
                {
                    "campaign_id": identity.campaign_id,
                    "batch_id": identity.batch_id,
                    "terminal_status": "failed",
                }
            ],
        }
        runner_args = [
            "finalize",
            "--docker-host-volume",
            "/tmp/docker-host",
            "--results-worktree-root",
            "/tmp/results",
            "--rondo-measurement-worktree-root",
            "/tmp/rondo",
            "--codex-measurement-worktree-root",
            "/tmp/codex",
        ]
        with (
            mock.patch.object(
                formal_canary.RepoPaths, "discover", return_value=self.paths
            ),
            mock.patch.object(
                formal_canary, "load_campaign_identity", return_value=identity
            ),
            mock.patch.object(formal_canary, "baseline_main", return_value=2),
            mock.patch.object(
                formal_canary,
                "load_task_budget",
                side_effect=[active],
            ),
            mock.patch.object(
                formal_canary,
                "required_successor_prior",
                return_value=Decimal("9.500000"),
            ),
            mock.patch.object(
                formal_canary, "close_task_budget", return_value=closed
            ) as close,
            mock.patch.object(
                formal_canary, "retire_active_campaign_pointer"
            ) as retire,
        ):
            result = formal_canary.main(runner_args)

        self.assertEqual(result, 2)
        self.assertEqual(close.call_args.kwargs["terminal_status"], "failed")
        self.assertEqual(
            close.call_args.kwargs["task_budget_id"],
            "direction0-local-optimization-052",
        )
        retire.assert_called_once_with(self.paths, identity=identity)


if __name__ == "__main__":
    unittest.main()
