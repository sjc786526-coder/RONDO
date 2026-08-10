"""Authorized short-lived counterfactual for the wrapper heartbeat contract."""

from __future__ import annotations

import argparse
import json
import os
import signal
import time
from typing import Callable

from .runtime_bridge import RuntimeBridgeError, lease_from_watchdog


def run_counterfactual(
    *,
    kill: Callable[[int, int], None] = os.kill,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    timeout_seconds: float = 22.0,
) -> bool:
    """Pause only the validated parent wrapper and require the live guard to fail."""

    if timeout_seconds <= 15:
        raise RuntimeBridgeError("watchdog counterfactual timeout is too short")
    proof = lease_from_watchdog()
    if proof.guard.is_held(proof.lease) is not True:
        raise RuntimeBridgeError("watchdog guard was not live before the counterfactual")
    raw_pid = os.environ.get("RONDO_WATCHDOG_WRAPPER_PID", "")
    if not raw_pid.isascii() or not raw_pid.isdigit() or int(raw_pid) <= 1:
        raise RuntimeBridgeError("watchdog counterfactual parent is invalid")
    watcher_pid = int(raw_pid)
    stopped = False
    try:
        kill(watcher_pid, signal.SIGSTOP)
        stopped = True
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            if proof.guard.is_held(proof.lease) is not True:
                return True
            sleeper(0.1)
        return False
    finally:
        if stopped:
            try:
                kill(watcher_pid, signal.SIGCONT)
            except ProcessLookupError:
                pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.watchdog_liveness_diagnostic"
    )
    parser.add_argument(
        "--mode",
        choices=("pause-wrapper", "expect-mint-rejected"),
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    mode = _parser().parse_args(argv).mode
    if mode == "expect-mint-rejected":
        try:
            lease_from_watchdog()
        except RuntimeBridgeError:
            print('{"mint_rejected":true,"status":"passed"}')
            return 0
        print('{"mint_rejected":false,"status":"failed"}')
        return 70
    try:
        rejected = run_counterfactual()
    except (OSError, RuntimeBridgeError, ValueError) as exc:
        print(
            json.dumps(
                {"status": "error", "reason": str(exc)},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 70
    print(
        json.dumps(
            {
                "guard_rejected_stale_watcher": rejected,
                "status": "passed" if rejected else "failed",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if rejected else 70


if __name__ == "__main__":
    raise SystemExit(main())
