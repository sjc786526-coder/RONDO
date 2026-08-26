#!/usr/bin/env python3
"""Stop, delete and confirm absence of one exact Plan 087 RunPod Pod."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from typing import Any

TERMINAL_SCHEMA = "rondo-publication-critic-plan087-runpod-terminal-v1"


class TerminalError(RuntimeError):
    """Sanitized lifecycle error."""


class MutationUncertain(TerminalError):
    """A stop/delete response failed after the provider may have applied it."""


Query = Callable[[Sequence[str], float], Any]
Mutation = Callable[[Sequence[str], float], None]


def terminate_exact_pod(
    args: argparse.Namespace,
    *,
    query: Query,
    mutate: Mutation,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not args.pod_name.startswith(args.task_pod_name_prefix):
        raise TerminalError("pod_name_outside_task_prefix")
    if args.poll_seconds <= 0 or args.timeout_seconds <= 0:
        raise TerminalError("terminal_arguments_invalid")
    deadline = monotonic() + args.timeout_seconds

    def remaining() -> float:
        value = deadline - monotonic()
        if value <= 0:
            raise TerminalError("terminal_confirmation_timeout")
        return value

    pods = _pod_rows(query(("pod", "list", "--all"), remaining()))
    listed = _exact_listed_pod_or_absent(pods, args)
    if listed is not None:
        pod = query(("pod", "get", args.pod_id, "--include-machine"), remaining())
        _require_exact_pod(pod, args)
        if not _stopped(pod, args):
            with suppress(MutationUncertain):
                mutate(("pod", "stop", args.pod_id), remaining())
        while True:
            pods = _pod_rows(query(("pod", "list", "--all"), remaining()))
            listed = _exact_listed_pod_or_absent(pods, args)
            if listed is None:
                break
            pod = query(
                ("pod", "get", args.pod_id, "--include-machine"), remaining()
            )
            _require_exact_pod(pod, args)
            if _stopped(pod, args):
                with suppress(MutationUncertain):
                    mutate(("pod", "delete", args.pod_id), remaining())
                break
            sleeper(min(args.poll_seconds, remaining()))
    while True:
        pods = _pod_rows(query(("pod", "list", "--all"), remaining()))
        if _exact_listed_pod_or_absent(pods, args) is None:
            break
        sleeper(min(args.poll_seconds, remaining()))
    billing = query(
        (
            "billing",
            "pods",
            "--start-time",
            args.task_started_at,
            "--end-time",
            args.captured_at,
        ),
        remaining(),
    )
    if not isinstance(billing, (Mapping, Sequence)) or isinstance(
        billing, (str, bytes, bytearray)
    ):
        raise TerminalError("pod_billing_snapshot_invalid")
    user = query(("user",), remaining())
    if not isinstance(user, Mapping):
        raise TerminalError("user_snapshot_invalid")
    balance = _finite_nonnegative(user.get("clientBalance"), "balance_invalid")
    return {
        "schema": TERMINAL_SCHEMA,
        "captured_at": args.captured_at,
        "deleted_pod": {"id": args.pod_id, "name": args.pod_name},
        "pod_count": 0,
        "compute_rate_usd_per_hour": 0.0,
        "pod_list_snapshot": pods,
        "pod_billing_snapshot": billing,
        "user_snapshot": {
            "clientBalance": balance,
            "currentSpendPerHr": _finite_nonnegative(
                user.get("currentSpendPerHr"), "account_spend_invalid"
            ),
        },
        "account_balance_usd": balance,
        "account_current_spend_per_hour_usd": _finite_nonnegative(
            user.get("currentSpendPerHr"), "account_spend_invalid"
        ),
    }


def _require_exact_pod(value: Any, args: argparse.Namespace) -> None:
    if (
        not isinstance(value, Mapping)
        or value.get("id") != args.pod_id
        or value.get("name") != args.pod_name
        or value.get("gpuCount") != 1
    ):
        raise TerminalError("exact_pod_identity_mismatch")


def _stopped(value: Mapping[str, Any], args: argparse.Namespace) -> bool:
    return (
        value.get("desiredStatus") == args.stopped_desired_status
        and value.get("runtimeStatus") == args.stopped_runtime_status
    )


def _exact_listed_pod_or_absent(
    rows: Sequence[Mapping[str, Any]], args: argparse.Namespace
) -> Mapping[str, Any] | None:
    if not rows:
        return None
    matches = [row for row in rows if row.get("id") == args.pod_id]
    if len(rows) != 1 or len(matches) != 1:
        raise TerminalError("account_pods_remain")
    _require_exact_pod(matches[0], args)
    return matches[0]


def _pod_rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TerminalError("pod_list_invalid")
    if any(not isinstance(row, Mapping) for row in value):
        raise TerminalError("pod_list_invalid")
    return list(value)


def _finite_nonnegative(value: Any, code: str) -> float:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise TerminalError(code)
    return float(value)


def _run_json(client: str, command: Sequence[str], timeout: float) -> Any:
    completed = _run(client, (*command, "-o", "json"), timeout)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise TerminalError("provider_json_invalid") from exc


def _run_mutation(client: str, command: Sequence[str], timeout: float) -> None:
    try:
        _run(client, (*command, "-o", "json"), timeout)
    except TerminalError as exc:
        raise MutationUncertain("runpod_mutation_response_uncertain") from exc


def _run(
    client: str, command: Sequence[str], timeout: float
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            [client, *command],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TerminalError("runpodctl_execution_failed") from exc
    if completed.returncode != 0:
        raise TerminalError(f"runpodctl_failed_{completed.returncode}")
    return completed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runpodctl", default="runpodctl")
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--task-pod-name-prefix", default="rondo-plan087-")
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--task-started-at", required=True)
    parser.add_argument("--stopped-desired-status", default="EXITED")
    parser.add_argument("--stopped-runtime-status", default="stopped")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = terminate_exact_pod(
            args,
            query=lambda command, timeout: _run_json(args.runpodctl, command, timeout),
            mutate=lambda command, timeout: _run_mutation(
                args.runpodctl, command, timeout
            ),
        )
    except TerminalError as exc:
        print(
            json.dumps({"status": "failed", "code": str(exc)}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
