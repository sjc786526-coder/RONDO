#!/usr/bin/env python3
"""Create or reconcile one uniquely named Plan 087 RunPod Pod."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
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
    requested = _requested_configuration(args)
    deadline = monotonic() + args.timeout_seconds

    def remaining() -> float:
        value = deadline - monotonic()
        if value <= 0:
            raise CreateError("creation_confirmation_timeout")
        return value

    before = _pod_rows(query(("pod", "list", "--all"), remaining()))
    existing = _exact_single_or_fail(before, args)
    if existing is not None:
        # runpodctl 2.9.0 omits networkVolumeId, stopAfter and terminateAfter
        # from pod get.  A prior process therefore cannot prove the full create
        # contract and must never silently adopt a same-name billed resource.
        raise CreateError("existing_pod_contract_unverifiable")
    outcome = "created"
    mutation_uncertain = False
    try:
        mutate(_create_command(args), remaining())
    except MutationUncertain:
        mutation_uncertain = True
        outcome = "reconciled_after_uncertain_create"
    while True:
        rows = _pod_rows(query(("pod", "list", "--all"), remaining()))
        existing = _exact_single_or_fail(rows, args)
        if existing is not None:
            break
        sleeper(min(args.poll_seconds, remaining()))
    assert existing is not None
    detail = query(
        (
            "pod",
            "get",
            existing["id"],
            "--include-machine",
            "--include-network-volume",
        ),
        remaining(),
    )
    observed = _validate_created_pod_observation(
        detail, list_row=existing, requested=requested
    )
    return {
        "schema": CREATE_SCHEMA,
        "captured_at": args.captured_at,
        "outcome": outcome,
        "mutation_response_uncertain": mutation_uncertain,
        "pod": {
            "id": observed["id"],
            "name": observed["name"],
            "gpu_count": observed["gpu_count"],
            "desired_status": observed["desired_status"],
            "runtime_status": observed["runtime_status"],
        },
        "creation_contract_binding": {
            "basis": "single_exact_create_request_after_empty_account",
            "requested": requested,
            "provider_observed": observed,
            "cross_process_reuse_allowed": False,
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
        or pod.get("runtimeStatus") not in {"initializing", "running", "unknown"}
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


def _requested_configuration(args: argparse.Namespace) -> dict[str, Any]:
    strings = {
        "image": getattr(args, "image", None),
        "gpu_id": getattr(args, "gpu_id", None),
        "data_center_id": getattr(args, "data_center_id", None),
        "network_volume_id": getattr(args, "network_volume_id", None),
    }
    if any(not isinstance(value, str) or not value for value in strings.values()):
        raise CreateError("creation_arguments_invalid")
    stop = _rfc3339_instant(args.stop_after)
    terminate = _rfc3339_instant(args.terminate_after)
    if stop >= terminate:
        raise CreateError("creation_stop_terminate_order_invalid")
    return {
        **strings,
        "gpu_count": 1,
        "cloud_type": "SECURE",
        "container_disk_gb": args.container_disk_gb,
        "volume_mount_path": "/workspace",
        "stop_after": stop.isoformat().replace("+00:00", "Z"),
        "terminate_after": terminate.isoformat().replace("+00:00", "Z"),
    }


def _validate_created_pod_observation(
    value: Any,
    *,
    list_row: Mapping[str, Any],
    requested: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CreateError("created_pod_detail_invalid")
    machine = value.get("machine")
    if not isinstance(machine, Mapping):
        raise CreateError("created_pod_detail_invalid")
    gpu_id = _one_observed(value, machine, "gpuTypeId", "gpuId")
    data_center_id = _one_observed(value, machine, "dataCenterId")
    required_equal = {
        "imageName": requested["image"],
        "containerDiskInGb": requested["container_disk_gb"],
        "volumeMountPath": requested["volume_mount_path"],
    }
    if (
        value.get("id") != list_row.get("id")
        or value.get("name") != list_row.get("name")
        or value.get("gpuCount") != 1
        or gpu_id != requested["gpu_id"]
        or data_center_id != requested["data_center_id"]
        or any(value.get(key) != expected for key, expected in required_equal.items())
        or value.get("desiredStatus") != "RUNNING"
        or value.get("runtimeStatus") not in {"initializing", "running", "unknown"}
    ):
        raise CreateError("created_pod_configuration_drifted")
    optional = {
        "cloudType": requested["cloud_type"],
        "networkVolumeId": requested["network_volume_id"],
        "stopAfter": requested["stop_after"],
        "terminateAfter": requested["terminate_after"],
    }
    for key, expected in optional.items():
        if key in value and value[key] is not None:
            observed = value[key]
            if key in {"stopAfter", "terminateAfter"}:
                observed = _rfc3339_instant(observed).isoformat().replace("+00:00", "Z")
            if observed != expected:
                raise CreateError("created_pod_configuration_drifted")
    network_volume = value.get("networkVolume")
    if network_volume is not None and (
        not isinstance(network_volume, Mapping)
        or network_volume.get("id") != requested["network_volume_id"]
    ):
        raise CreateError("created_pod_configuration_drifted")
    return {
        "id": value["id"],
        "name": value["name"],
        "image": value["imageName"],
        "gpu_id": gpu_id,
        "gpu_count": value["gpuCount"],
        "data_center_id": data_center_id,
        "container_disk_gb": value["containerDiskInGb"],
        "volume_mount_path": value["volumeMountPath"],
        "desired_status": value["desiredStatus"],
        "runtime_status": value["runtimeStatus"],
    }


def _one_observed(top: Mapping[str, Any], nested: Mapping[str, Any], *keys: str) -> Any:
    values = [
        mapping[key]
        for mapping in (top, nested)
        for key in keys
        if key in mapping and mapping[key] is not None
    ]
    if not values or any(value != values[0] for value in values[1:]):
        raise CreateError("created_pod_configuration_ambiguous")
    return values[0]


def _rfc3339_instant(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise CreateError("creation_datetime_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CreateError("creation_datetime_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CreateError("creation_datetime_invalid")
    return parsed.astimezone(timezone.utc)


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
