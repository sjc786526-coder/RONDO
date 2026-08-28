from __future__ import annotations

from decimal import Decimal
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock

from rondo_eval.publication_critic.engineering import campaign


class Plan097CampaignTests(unittest.TestCase):
    def test_codex_environment_uses_private_runtime_tmp(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            home = root / "home"
            trace = root / "trace"
            home.mkdir(mode=0o700)
            trace.mkdir(mode=0o700)

            environment = campaign._codex_environment(
                home=home,
                trace_root=trace,
                downstream_key="bounded-loopback-key",
            )

            private_tmp = home / "tmp"
            self.assertEqual(environment["TMPDIR"], str(private_tmp))
            self.assertTrue(private_tmp.is_dir())
            self.assertFalse(private_tmp.is_symlink())
            self.assertEqual(stat.S_IMODE(private_tmp.stat().st_mode), 0o700)
            self.assertEqual(environment["CODEX_HOME"], str(home))
            self.assertEqual(environment["CODEX_ROLLOUT_TRACE_ROOT"], str(trace))

    def test_codex_environment_rejects_multiline_key(self) -> None:
        with self.assertRaisesRegex(campaign.CampaignError, "downstream_key_invalid"):
            campaign._codex_environment(
                home=Path("home"),
                trace_root=Path("trace"),
                downstream_key="unsafe\nkey",
            )

    def test_cloud_budget_projection_retains_only_body_free_counts(self) -> None:
        projection = campaign._cloud_budget_projection(
            {
                "cap_rmb": "12",
                "conservative_charged_rmb": "1.5",
                "remaining_rmb": "10.5",
                "attempts": [
                    {
                        "state": "usage_priced",
                        "request_body": "must not survive",
                    },
                    {
                        "state": "unknown_usage_charged",
                        "response_body": "must not survive",
                    },
                ],
            }
        )
        self.assertEqual(
            projection,
            {
                "cap_rmb": "12",
                "conservative_charged_rmb": "1.5",
                "remaining_rmb": "10.5",
                "attempt_count": 2,
                "usage_priced_count": 1,
                "unknown_usage_count": 1,
            },
        )

    def test_cloud_budget_roll_forward_includes_prior_attempts_and_charges(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime_root = Path(raw)
            budget_root = runtime_root / "budget"
            budget_root.mkdir()
            (budget_root / campaign._PRIOR_CLOUD_LEDGER_NAME).write_text(
                json.dumps(
                    {
                        "schema": "rondo-publication-critic-plan097-cloud-budget-v1",
                        "cap_rmb": "12",
                        "attempts": [
                            {
                                "attempt": 1,
                                "state": "usage_priced",
                                "usage": {},
                                "actual_charge_rmb": "0.1",
                                "conservative_charge_rmb": "0.1",
                            },
                            {
                                "attempt": 2,
                                "state": "unknown_usage_charged",
                                "usage": None,
                                "actual_charge_rmb": None,
                                "conservative_charge_rmb": "1",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            prior = campaign._prior_cloud_budget_projection(
                mock.Mock(runtime_root=runtime_root)
            )
            contract = campaign.load_contract(Path(__file__).resolve().parents[2])

        projection = campaign._combined_cloud_budget_projection(
            contract,
            prior,
            {
                "cap_rmb": "9.9",
                "conservative_charged_rmb": "0.2",
                "remaining_rmb": "9.7",
                "attempts": [
                    {"state": "usage_priced"},
                ],
            },
        )

        self.assertEqual(projection["cap_rmb"], "11")
        self.assertEqual(projection["conservative_charged_rmb"], "1.3")
        self.assertEqual(projection["remaining_rmb"], "9.7")
        self.assertEqual(projection["attempt_count"], 3)
        self.assertEqual(projection["usage_priced_count"], 2)
        self.assertEqual(projection["unknown_usage_count"], 1)

    def test_local_backend_requires_build_watchdog_scope(self) -> None:
        names = (
            "RONDO_WATCHDOG_WRAPPER_PID",
            "RONDO_WATCHDOG_WRAPPER_START_TICKS",
            "RONDO_WATCHDOG_HEARTBEAT_PATH",
            "RONDO_WATCHDOG_SCRIPT_PATH",
        )
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                campaign.CampaignError, "local_backend_requires_watchdog_scope"
            ):
                campaign._require_watchdog_scope()
            os.environ.update({name: "bounded" for name in names})
            campaign._require_watchdog_scope()

    def test_run_and_producer_ids_share_bounded_plan_namespace(self) -> None:
        for value in ("plan097-formal-a", "plan097-producer-01"):
            campaign._require_run_id(value)
        for value in (
            "formal-a",
            "plan097-UPPER",
            "plan097-contains_underscore",
            "plan097-" + "a" * 81,
        ):
            with self.assertRaisesRegex(campaign.CampaignError, "run_id_invalid"):
                campaign._require_run_id(value)

    def test_decimal_projection_is_exact(self) -> None:
        self.assertEqual(campaign._decimal_text(Decimal("0.1200")), "0.1200")

    def test_legacy_zero_cost_attempts_remain_in_total_request_count(self) -> None:
        projection = campaign._producer_ledger_projection(
            {
                "batch_id": "plan097-producer-v1",
                "runs": {
                    "plan097-old-run": {
                        "spent_usd": "0.000000",
                        "requests": {
                            "request-1": {
                                "status": "settled",
                                "charged_usd": "0.000000",
                            }
                        },
                    }
                },
            },
            expected_batch_id="plan097-producer-v1",
        )
        self.assertEqual(projection["spent_usd"], Decimal("0.000000"))
        self.assertEqual(projection["request_count"], 1)

        with self.assertRaisesRegex(campaign.CampaignError, "producer_budget_invalid"):
            campaign._producer_ledger_projection(
                {
                    "batch_id": "plan097-producer-v1",
                    "runs": {
                        "plan097-bad-run": {
                            "spent_usd": "0",
                            "requests": {"request-1": {"status": "reserved"}},
                        }
                    },
                },
                expected_batch_id="plan097-producer-v1",
            )

    def test_current_budget_includes_every_superseded_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime_root = Path(raw)
            budget_root = runtime_root / "budget"
            budget_root.mkdir()
            for index, (batch_id, filename) in enumerate(
                campaign._PRIOR_PRODUCER_LEDGERS, start=1
            ):
                (budget_root / filename).write_text(
                    json.dumps(
                        {
                            "batch_id": batch_id,
                            "runs": {
                                f"plan097-prior-{index}": {
                                    "spent_usd": f"0.{index}00000",
                                    "requests": {
                                        f"request-{request}": {
                                            "status": "settled",
                                            "charged_usd": "0.000000",
                                        }
                                        for request in range(index)
                                    },
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            projection = campaign._prior_producer_budget_projection(
                mock.Mock(runtime_root=runtime_root)
            )

        self.assertEqual(projection["spent_usd"], Decimal("1.500000"))
        self.assertEqual(projection["request_count"], 15)

    def test_producer_only_recovery_is_for_commissioning_only(self) -> None:
        campaign._require_backend_mode("commissioning", True)
        campaign._require_backend_mode("formal", False)
        with self.assertRaisesRegex(
            campaign.CampaignError, "producer_only_requires_commissioning"
        ):
            campaign._require_backend_mode("formal", True)

        args = campaign.build_parser().parse_args(
            [
                "backend",
                "--phase",
                "commissioning",
                "--run-id",
                "plan097-commission-recovery",
                "--backend",
                "local",
                "--producer-run-id",
                "plan097-producer-recovery",
                "--producer-only",
            ]
        )
        self.assertTrue(args.producer_only)

    def test_owned_command_reaps_a_lingering_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            child_pid_path = root / "child.pid"
            script = (
                "import pathlib,subprocess,sys; "
                "child=subprocess.Popen([sys.executable,'-c',"
                "'import time; time.sleep(60)'],stdout=subprocess.DEVNULL,"
                "stderr=subprocess.DEVNULL); "
                f"pathlib.Path({str(child_pid_path)!r}).write_text(str(child.pid))"
            )
            completed = campaign._run_owned_command(
                [sys.executable, "-c", script],
                cwd=root,
                env={"PATH": os.environ.get("PATH", "")},
                timeout=10,
                timeout_code="test_timeout",
            )

            self.assertEqual(completed.returncode, 0)
            child_pid = int(child_pid_path.read_text(encoding="utf-8"))
            self.assertFalse(Path(f"/proc/{child_pid}").exists())


if __name__ == "__main__":
    unittest.main()
