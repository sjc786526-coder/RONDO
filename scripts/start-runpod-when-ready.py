#!/usr/bin/env python3
"""Wait for readiness, then start one existing RunPod Pod without replacement.

The script reloads the external budget policy on every readiness sample. It
only invokes ``pod start`` for the exact configured Pod ID. Capacity-related
HTTP 400 failures are retried; every other start failure is terminal. Provider
stdout/stderr is always captured and never forwarded to logs or the terminal.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import copy
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import time
from typing import Any


_WAITER_PATH = Path(__file__).with_name("wait-runpod-readiness.py")
_WAITER_SPEC = importlib.util.spec_from_file_location(
    "rondo_wait_runpod_readiness", _WAITER_PATH
)
if _WAITER_SPEC is None or _WAITER_SPEC.loader is None:
    raise RuntimeError("readiness_waiter_import_failed")
readiness = importlib.util.module_from_spec(_WAITER_SPEC)
_WAITER_SPEC.loader.exec_module(readiness)


START_WAIT_SCHEMA = "rondo-runpod-existing-pod-start-wait-v1"
CAPACITY_MARKERS = (
    "host capacity",
    "insufficient capacity",
    "no available host",
    "no instances available",
    "no longer any instances available",
    "not enough free gpu",
    "requested specifications",
)


class StartWaitError(RuntimeError):
    """A sanitized existing-Pod start failure."""


JsonQuery = Callable[[str, Sequence[str], float | None], Any]
PodStarter = Callable[[str, str, float | None], str]
PodStopper = Callable[[str, str, float | None], None]
HandoffNotifier = Callable[[dict[str, Any]], None]


def _start_same_pod(client: str, pod_id: str, timeout: float | None) -> str:
    try:
        completed = subprocess.run(
            [client, "pod", "start", pod_id, "-o", "json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise StartWaitError("pod_start_timeout") from exc
    if completed.returncode == 0:
        return "accepted"
    body = f"{completed.stdout}\n{completed.stderr}".casefold()
    # The REST/MCP path includes HTTP 400, while runpodctl may normalize the
    # same provider response into a JSON CLI error without retaining the HTTP
    # status.  The allowlisted provider phrases are specific enough to classify
    # either representation without forwarding the private response body.
    if any(marker in body for marker in CAPACITY_MARKERS):
        return "capacity_unavailable"
    raise StartWaitError(f"pod_start_failed_{completed.returncode}")


def _stop_same_pod(client: str, pod_id: str, timeout: float | None) -> None:
    try:
        completed = subprocess.run(
            [client, "pod", "stop", pod_id, "-o", "json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise StartWaitError("pod_stop_timeout") from exc
    if completed.returncode != 0:
        raise StartWaitError(f"pod_stop_failed_{completed.returncode}")


def _stdout_handoff(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True), flush=True)


def _require_fresh_handoff_ack(path: Path) -> None:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise StartWaitError("handoff_ack_inspection_failed") from exc
    raise StartWaitError("handoff_ack_file_stale")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runpodctl", default="runpodctl")
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--stopped-desired-status", default="EXITED")
    parser.add_argument("--stopped-runtime-status", default="stopped")
    parser.add_argument("--running-desired-status", default="RUNNING")
    parser.add_argument("--running-runtime-status", default="running")
    parser.add_argument("--gpu-id", required=True)
    parser.add_argument("--gpu-memory-gb", type=int, required=True)
    parser.add_argument("--expected-gpu-count", type=int, default=1)
    parser.add_argument(
        "--price-field",
        choices=("securePricePerHr", "communityPricePerHr"),
        default="securePricePerHr",
    )
    parser.add_argument("--data-center-id")
    parser.add_argument("--expected-machine-location")
    parser.add_argument("--maximum-gpu-price-per-hour", type=float, required=True)
    parser.add_argument("--baseline-balance", type=float, required=True)
    parser.add_argument("--billing-start-time", required=True)
    parser.add_argument("--maximum-additional-seconds", type=int, required=True)
    parser.add_argument("--running-storage-per-hour", type=float, required=True)
    parser.add_argument("--budget-policy", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--start-retry-seconds", type=float, default=30.0)
    parser.add_argument("--start-transition-timeout-seconds", type=float, default=120.0)
    parser.add_argument("--handoff-ack-file", type=Path, required=True)
    parser.add_argument("--handoff-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    parser.add_argument("--maximum-consecutive-query-errors", type=int, default=10)
    parser.add_argument("--required-consecutive-ready", type=int, default=1)
    parser.add_argument("--state-log", type=Path, required=True)
    return parser


def _validate_args(args: argparse.Namespace) -> None:
    finite_values = (
        args.maximum_gpu_price_per_hour,
        args.baseline_balance,
        args.running_storage_per_hour,
        args.poll_seconds,
        args.start_retry_seconds,
        args.start_transition_timeout_seconds,
        args.handoff_timeout_seconds,
        args.timeout_seconds,
    )
    try:
        finite = all(math.isfinite(float(value)) for value in finite_values)
    except (TypeError, ValueError, OverflowError):
        finite = False
    if (
        not finite
        or not args.pod_id
        or not args.pod_name
        or not args.stopped_desired_status
        or not args.stopped_runtime_status
        or not args.running_desired_status
        or not args.running_runtime_status
        or not args.gpu_id
        or args.gpu_memory_gb <= 0
        or args.expected_gpu_count <= 0
        or args.maximum_gpu_price_per_hour < 0
        or args.baseline_balance < 0
        or args.maximum_additional_seconds <= 0
        or args.running_storage_per_hour < 0
        or args.poll_seconds <= 0
        or args.start_retry_seconds <= 0
        or args.start_transition_timeout_seconds <= 0
        or args.handoff_timeout_seconds <= 0
        or args.timeout_seconds < 0
        or args.maximum_consecutive_query_errors <= 0
        or args.required_consecutive_ready <= 0
    ):
        raise SystemExit("invalid existing Pod start wait bounds")
    try:
        _require_fresh_handoff_ack(args.handoff_ack_file)
    except StartWaitError as exc:
        if str(exc) == "handoff_ack_file_stale":
            raise SystemExit("handoff ack file must not already exist") from exc
        raise SystemExit("handoff ack path cannot be inspected") from exc


def _record(
    args: argparse.Namespace,
    *,
    status: str,
    attempt_count: int,
    readiness_result: dict[str, Any] | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": START_WAIT_SCHEMA,
        "captured_at": readiness._utc_now(),
        "status": status,
        "pod": {"id": args.pod_id, "name": args.pod_name},
        "start_attempt_count": attempt_count,
    }
    if readiness_result is not None:
        result["readiness"] = readiness_result
    if error_code is not None:
        result["error_code"] = error_code
    readiness._append_log(args.state_log, result)
    return result


def wait_for_existing_pod_start(
    args: argparse.Namespace,
    *,
    query: JsonQuery,
    starter: PodStarter,
    stopper: PodStopper = _stop_same_pod,
    handoff_notifier: HandoffNotifier = _stdout_handoff,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[int, dict[str, Any]]:
    """Run the bounded readiness/start loop with injectable provider seams."""

    _validate_args(args)
    started_at = monotonic()
    deadline = started_at + args.timeout_seconds if args.timeout_seconds else None
    attempts = 0
    consecutive_errors = 0
    consecutive_ready = 0
    start_accepted = False
    start_accepted_at: float | None = None

    def remaining() -> float | None:
        if deadline is None:
            return None
        value = deadline - monotonic()
        if value <= 0:
            raise StartWaitError("start_wait_deadline_exceeded")
        return value

    def pause(seconds: float) -> None:
        if deadline is None:
            sleeper(seconds)
            return
        available = deadline - monotonic()
        if available <= 0:
            raise StartWaitError("start_wait_deadline_exceeded")
        sleeper(min(seconds, available))

    while True:
        try:
            pod = query(
                "pod",
                ("pod", "get", args.pod_id, "--include-machine"),
                remaining(),
            )
            if not isinstance(pod, dict):
                raise readiness.ReadinessQueryError("pod_shape_invalid")
            desired = pod.get("desiredStatus")
            runtime = pod.get("runtimeStatus")
            sample_args = copy.copy(args)
            sample_args.required_desired_status = desired
            sample_args.required_runtime_status = runtime

            def sample_query(
                label: str, command: Sequence[str]
            ) -> Any:
                if label == "pod":
                    return pod
                return query(label, command, remaining())

            sample = readiness.evaluate(sample_args, sample_query)
            consecutive_errors = 0
        except (readiness.ReadinessQueryError, StartWaitError) as exc:
            consecutive_errors += 1
            code = str(exc)
            result = _record(
                args,
                status="query_error",
                attempt_count=attempts,
                error_code=code,
            )
            if code == "start_wait_deadline_exceeded":
                return 5, result
            if consecutive_errors >= args.maximum_consecutive_query_errors:
                return 4, result
            try:
                pause(args.poll_seconds)
            except StartWaitError:
                result = _record(
                    args,
                    status="timeout",
                    attempt_count=attempts,
                    error_code="start_wait_deadline_exceeded",
                )
                return 5, result
            continue

        if sample["failures"]:
            result = _record(
                args,
                status="blocked",
                attempt_count=attempts,
                readiness_result=sample,
            )
            return 2, result

        is_running = (
            desired == args.running_desired_status
            and runtime == args.running_runtime_status
        )
        is_stopped = (
            desired == args.stopped_desired_status
            and runtime == args.stopped_runtime_status
        )
        if is_running:
            handoff_notifier(
                {
                    "schema": START_WAIT_SCHEMA,
                    "status": "running_handoff_pending",
                    "pod": {"id": args.pod_id, "name": args.pod_name},
                    "handoff_ack_file": str(args.handoff_ack_file),
                }
            )
            pending = _record(
                args,
                status="running_handoff_pending",
                attempt_count=attempts,
                readiness_result=sample,
            )
            return _wait_for_handoff_ack(
                args,
                attempt_count=attempts,
                pending=pending,
                query=query,
                stopper=stopper,
                monotonic=monotonic,
                sleeper=sleeper,
            )
        if not is_stopped:
            if not start_accepted:
                result = _record(
                    args,
                    status="blocked",
                    attempt_count=attempts,
                    readiness_result=sample,
                    error_code="pod_state_unexpected_before_start",
                )
                return 2, result
            consecutive_ready = 0
            _record(
                args,
                status="waiting_start_transition",
                attempt_count=attempts,
                readiness_result=sample,
            )
            try:
                pause(args.poll_seconds)
            except StartWaitError:
                result = _record(
                    args,
                    status="timeout",
                    attempt_count=attempts,
                    error_code="start_wait_deadline_exceeded",
                )
                return 5, result
            continue

        if start_accepted:
            assert start_accepted_at is not None
            if monotonic() - start_accepted_at >= args.start_transition_timeout_seconds:
                start_accepted = False
                start_accepted_at = None
            else:
                consecutive_ready = 0
                _record(
                    args,
                    status="waiting_start_transition",
                    attempt_count=attempts,
                    readiness_result=sample,
                )
                try:
                    pause(args.poll_seconds)
                except StartWaitError:
                    result = _record(
                        args,
                        status="timeout",
                        attempt_count=attempts,
                        error_code="start_wait_deadline_exceeded",
                    )
                    return 5, result
                continue
        if sample["status"] != "ready":
            consecutive_ready = 0
            _record(
                args,
                status="waiting_readiness",
                attempt_count=attempts,
                readiness_result=sample,
            )
            try:
                pause(args.poll_seconds)
            except StartWaitError:
                result = _record(
                    args,
                    status="timeout",
                    attempt_count=attempts,
                    error_code="start_wait_deadline_exceeded",
                )
                return 5, result
            continue

        consecutive_ready += 1
        if consecutive_ready < args.required_consecutive_ready:
            _record(
                args,
                status="confirming_ready",
                attempt_count=attempts,
                readiness_result=sample,
            )
            try:
                pause(args.poll_seconds)
            except StartWaitError:
                result = _record(
                    args,
                    status="timeout",
                    attempt_count=attempts,
                    error_code="start_wait_deadline_exceeded",
                )
                return 5, result
            continue

        try:
            _require_fresh_handoff_ack(args.handoff_ack_file)
        except StartWaitError as exc:
            result = _record(
                args,
                status="blocked",
                attempt_count=attempts,
                readiness_result=sample,
                error_code=str(exc),
            )
            return 2, result
        attempts += 1
        try:
            outcome = starter(args.runpodctl, args.pod_id, remaining())
        except StartWaitError as exc:
            result = _record(
                args,
                status="blocked",
                attempt_count=attempts,
                readiness_result=sample,
                error_code=str(exc),
            )
            return 2, result
        if outcome == "capacity_unavailable":
            consecutive_ready = 0
            _record(
                args,
                status="waiting_host_capacity",
                attempt_count=attempts,
                readiness_result=sample,
                error_code="pod_start_capacity_unavailable",
            )
            try:
                pause(args.start_retry_seconds)
            except StartWaitError:
                result = _record(
                    args,
                    status="timeout",
                    attempt_count=attempts,
                    error_code="start_wait_deadline_exceeded",
                )
                return 5, result
            continue
        if outcome != "accepted":
            result = _record(
                args,
                status="blocked",
                attempt_count=attempts,
                readiness_result=sample,
                error_code="pod_start_outcome_invalid",
            )
            return 2, result
        start_accepted = True
        start_accepted_at = monotonic()
        consecutive_ready = 0
        _record(
            args,
            status="start_accepted_waiting_running",
            attempt_count=attempts,
            readiness_result=sample,
        )
        try:
            pause(args.poll_seconds)
        except StartWaitError:
            result = _record(
                args,
                status="timeout",
                attempt_count=attempts,
                error_code="start_wait_deadline_exceeded",
            )
            return 5, result


def _wait_for_handoff_ack(
    args: argparse.Namespace,
    *,
    attempt_count: int,
    pending: dict[str, Any],
    query: JsonQuery,
    stopper: PodStopper,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
) -> tuple[int, dict[str, Any]]:
    handoff_deadline = monotonic() + args.handoff_timeout_seconds
    while True:
        try:
            info = os.lstat(args.handoff_ack_file)
        except FileNotFoundError:
            info = None
        except OSError:
            return _stop_after_handoff_failure(
                args,
                attempt_count=attempt_count,
                reason="handoff_ack_inspection_failed",
                query=query,
                stopper=stopper,
                monotonic=monotonic,
                sleeper=sleeper,
            )
        if info is not None:
            if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                result = _record(
                    args,
                    status="running_handoff_acknowledged",
                    attempt_count=attempt_count,
                    readiness_result=pending.get("readiness"),
                )
                return 0, result
            return _stop_after_handoff_failure(
                args,
                attempt_count=attempt_count,
                reason="handoff_ack_unsafe",
                query=query,
                stopper=stopper,
                monotonic=monotonic,
                sleeper=sleeper,
            )
        remaining = handoff_deadline - monotonic()
        if remaining <= 0:
            return _stop_after_handoff_failure(
                args,
                attempt_count=attempt_count,
                reason="handoff_timeout",
                query=query,
                stopper=stopper,
                monotonic=monotonic,
                sleeper=sleeper,
            )
        sleeper(min(args.poll_seconds, remaining))


def _stop_after_handoff_failure(
    args: argparse.Namespace,
    *,
    attempt_count: int,
    reason: str,
    query: JsonQuery,
    stopper: PodStopper,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
) -> tuple[int, dict[str, Any]]:
    stop_deadline = monotonic() + args.handoff_timeout_seconds

    def cleanup_remaining() -> float:
        remaining = stop_deadline - monotonic()
        if remaining <= 0:
            raise StartWaitError("handoff_stop_confirmation_timeout")
        return remaining

    def read_exact_pod() -> dict[str, Any]:
        value = query(
            "pod",
            ("pod", "get", args.pod_id, "--include-machine"),
            cleanup_remaining(),
        )
        if (
            not isinstance(value, dict)
            or value.get("id") != args.pod_id
            or value.get("name") != args.pod_name
        ):
            raise StartWaitError("handoff_stop_pod_identity_mismatch")
        return value

    try:
        pod = read_exact_pod()
        stopped = (
            pod.get("desiredStatus") == args.stopped_desired_status
            and pod.get("runtimeStatus") == args.stopped_runtime_status
        )
        if not stopped:
            stopper(args.runpodctl, args.pod_id, cleanup_remaining())
        while not stopped:
            pod = read_exact_pod()
            stopped = (
                pod.get("desiredStatus") == args.stopped_desired_status
                and pod.get("runtimeStatus") == args.stopped_runtime_status
            )
            if not stopped:
                sleeper(min(args.poll_seconds, cleanup_remaining()))
    except (readiness.ReadinessQueryError, StartWaitError) as exc:
        result = _record(
            args,
            status="handoff_stop_failed",
            attempt_count=attempt_count,
            error_code=str(exc),
        )
        return 7, result
    status = (
        "handoff_timeout_stopped"
        if reason == "handoff_timeout"
        else "handoff_failure_stopped"
    )
    result = _record(
        args,
        status=status,
        attempt_count=attempt_count,
        error_code=reason,
    )
    return 6, result


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    def query(label: str, command: Sequence[str], timeout: float | None) -> Any:
        return readiness._run_json(
            args.runpodctl, label, command, timeout=timeout
        )

    code, result = wait_for_existing_pod_start(
        args,
        query=query,
        starter=_start_same_pod,
    )
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
