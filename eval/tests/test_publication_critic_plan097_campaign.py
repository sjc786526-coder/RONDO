from __future__ import annotations

from decimal import Decimal
import os
from pathlib import Path
import stat
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


if __name__ == "__main__":
    unittest.main()
