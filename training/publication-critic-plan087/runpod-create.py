#!/usr/bin/env python3
"""Create or reconcile one uniquely named Plan 087 RunPod Pod."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

CREATE_SCHEMA = "rondo-publication-critic-plan087-runpod-create-v1"


class CreateError(RuntimeError):
    """Sanitized creation/reconciliation error."""


class MutationUncertain(CreateError):
    """A provider mutation may have succeeded despite the client error."""


Query = Callable[[Sequence[str], float], Any]
Mutation = Callable[[Sequence[str], float], None]


def create_or_reconcile_exact_pod(
    args: argparse.Namespace,
    *,
    query: Query,
    mutate: Mutation,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not args.pod_name.startswith(args.task_pod_name_prefix):
        raise CreateError("pod_name_outside_task_prefix")
    if (
        not isinstance(args.container_disk_gb, int)
        or isinstance(args.container_disk_gb, bool)
        or args.container_disk_gb <= 0
        or not args.stop_after
        or not args.terminate_after
        or args.poll_seconds <= 0
        or args.timeout_seconds <= 0
    ):
        raise CreateError("creation_arguments_invalid")
    deadline = monotonic() + args.timeout_seconds

    def remaining() -> float:
        value = deadline - monotonic()
        if value <= 0:
            raise CreateError("creation_confirmation_timeout")
        return value

    before = _pod_rows(query(("pod", "list", "--all"), remaining()))
    existing = _exact_single_or_fail(before, args)
    outcome = "reconciled_existing"
    mutation_uncertain = False
    if existing is None:
        outcome = "created"
        try:
            mutate(_create_command(args), remaining())
        except MutationUncertain:
            mutation_uncertain = True
        while True:
            rows = _pod_rows(query(("pod", "list", "--all"), remaining()))
            existing = _exact_single_or_fail(rows, args)
            if existing is not None:
                break
            sleeper(min(args.poll_seconds, remaining()))
    assert existing is not None
    return {
        "schema": CREATE_SCHEMA,
        "captured_at": args.captured_at,
        "outcome": outcome,
        "mutation_response_uncertain": mutation_uncertain,
        "pod": {
            "id": existing["id"],
            "name": existing["name"],
            "gpu_count": existing["gpuCount"],
            "desired_status": existing.get("desiredStatus"),
            "runtime_status": existing.get("runtimeStatus"),
        },
        "account_pod_count": 1,
    }


def _exact_single_or_fail(
    rows: Sequence[Mapping[str, Any]], args: argparse.Namespace
) -> Mapping[str, Any] | None:
    matches = [row for row in rows if row.get("name") == args.pod_name]
    if not rows:
        return None
    if len(rows) != 1 or len(matches) != 1:
        raise CreateError("account_pods_not_exactly_one_task_pod")
    pod = matches[0]
    if (
        not isinstance(pod.get("id"), str)
        or not pod["id"]
        or pod.get("gpuCount") != 1
        or pod.get("desiredStatus") != "RUNNING"
        or pod.get("runtimeStatus")
        not in {"initializing", "running", "unknown"}
    ):
        raise CreateError("created_pod_identity_or_state_invalid")
    return pod


def _create_command(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "pod",
        "create",
        "--name",
        args.pod_name,
        "--image",
        args.image,
        "--gpu-id",
        args.gpu_id,
        "--gpu-count",
        "1",
        "--cloud-type",
        "SECURE",
        "--data-center-ids",
        args.data_center_id,
        "--network-volume-id",
        args.network_volume_id,
        "--volume-mount-path",
        "/workspace",
        "--container-disk-in-gb",
        str(args.container_disk_gb),
        "--ports",
        "22/tcp",
        "--stop-after",
        args.stop_after,
        "--terminate-after",
        args.terminate_after,
        "--wait",
        "--wait-timeout",
        args.wait_timeout,
    )


def _pod_rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise CreateError("pod_list_invalid")
    if any(not isinstance(row, Mapping) for row in value):
        raise CreateError("pod_list_invalid")
    return list(value)


def _run_json(client: str, command: Sequence[str], timeout: float) -> Any:
    completed = _run(client, (*command, "-o", "json"), timeout)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise CreateError("provider_json_invalid") from exc


def _run_mutation(client: str, command: Sequence[str], timeout: float) -> None:
    try:
        _run(client, (*command, "-o", "json"), timeout)
    except CreateError as exc:
        raise MutationUncertain("create_response_uncertain") from exc


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
        raise CreateError("runpodctl_execution_failed") from exc
    if completed.returncode != 0:
        raise CreateError(f"runpodctl_failed_{completed.returncode}")
    return completed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runpodctl", default="runpodctl")
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--task-pod-name-prefix", default="rondo-plan087-")
    parser.add_argument("--image", required=True)
    parser.add_argument("--gpu-id", required=True)
    parser.add_argument("--data-center-id", required=True)
    parser.add_argument("--network-volume-id", required=True)
    parser.add_argument("--container-disk-gb", type=int, required=True)
    parser.add_argument("--stop-after", required=True)
    parser.add_argument("--terminate-after", required=True)
    parser.add_argument("--wait-timeout", default="10m")
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=660.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = create_or_reconcile_exact_pod(
            args,
            query=lambda command, timeout: _run_json(args.runpodctl, command, timeout),
            mutate=lambda command, timeout: _run_mutation(
                args.runpodctl, command, timeout
            ),
        )
    except CreateError as exc:
        print(json.dumps({"status": "failed", "code": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
