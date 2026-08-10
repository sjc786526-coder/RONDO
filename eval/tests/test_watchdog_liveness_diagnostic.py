from __future__ import annotations

import os
import signal
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval import watchdog_liveness_diagnostic as diagnostic  # noqa: E402


class _Guard:
    def __init__(self, states: list[bool]) -> None:
        self.states = states

    def is_held(self, lease: object) -> bool:
        del lease
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


class WatchdogLivenessDiagnosticTests(unittest.TestCase):
    def test_counterfactual_stops_and_resumes_only_validated_wrapper(self) -> None:
        proof = SimpleNamespace(lease=object(), guard=_Guard([True, True, False]))
        signals: list[tuple[int, int]] = []
        clock = iter((0.0, 0.0, 0.1, 0.2))
        with mock.patch.object(
            diagnostic, "lease_from_watchdog", return_value=proof
        ), mock.patch.dict(
            os.environ,
            {"RONDO_WATCHDOG_WRAPPER_PID": "4242"},
        ):
            rejected = diagnostic.run_counterfactual(
                kill=lambda pid, value: signals.append((pid, value)),
                monotonic=lambda: next(clock),
                sleeper=lambda _: None,
            )

        self.assertTrue(rejected)
        self.assertEqual(
            signals,
            [(4242, signal.SIGSTOP), (4242, signal.SIGCONT)],
        )

    def test_old_synthetic_scope_mode_requires_mint_rejection(self) -> None:
        with mock.patch.object(
            diagnostic,
            "lease_from_watchdog",
            side_effect=diagnostic.RuntimeBridgeError("missing watcher"),
        ), mock.patch("builtins.print"):
            self.assertEqual(
                diagnostic.main(["--mode", "expect-mint-rejected"]),
                0,
            )


if __name__ == "__main__":
    unittest.main()
