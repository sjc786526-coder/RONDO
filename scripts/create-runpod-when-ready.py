#!/usr/bin/env python3
"""Poll one RunPod GPU target and create a Pod as soon as stock appears.

The caller supplies all Pod parameters and remains responsible for independently
validating the created resource, network volume, price, budget, and task
eligibility.  The script only automates frequent stock polling and the
latency-sensitive create.
If create completion is uncertain, it waits the full reconciliation window and
checks the exact Pod name before allowing another attempt.  It never starts,
stops, or deletes any resource.  Run only one monitor for an exact Pod name;
after terminating it during an uncertain create, wait at least one configured
reconciliation window before starting another monitor for that name.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

SCHEMA = "rondo-runpod-create-when-available-v1"
READY_STOCK = {"low", "medium", "high"}
CAPACITY_MARKERS = (
    "host capacity",
    "insufficient capacity",
    "no available host",
    "no instances available",
    "no longer any instances available",
    "not enough free gpu",
    "requested specifications",
)


class MonitorError(RuntimeError):
    """A stable error code which never contains provider response bodies."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


JsonQuery = Callable[[str, Sequence[str], float | None], Any]
PodCreator = Callable[[str, Sequence[str], float | None], dict[str, Any]]
StatusSink = Callable[[dict[str, Any]], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sequence(value: Any, label: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        for key in ("data", "items"):
            if isinstance(value.get(key), list):
                return value[key]
    raise MonitorError(f"{label}_shape_invalid")


def _run_json(
    client: str,
    label: str,
    command: Sequence[str],
    timeout: float | None,
) -> Any:
    try:
        completed = subprocess.run(
            [client, *command, "-o", "json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise MonitorError(f"{label}_query_timeout") from exc
    if completed.returncode != 0:
        raise MonitorError(f"{label}_query_failed_{completed.returncode}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise MonitorError(f"{label}_json_invalid") from exc


def _run_create(
    client: str, command: Sequence[str], timeout: float | None
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            [client, *command, "-o", "json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"status": "uncertain"}
    if completed.returncode != 0:
        body = f"{completed.stdout}\n{completed.stderr}".casefold()
        if any(marker in body for marker in CAPACITY_MARKERS):
            return {"status": "capacity_unavailable"}
        raise MonitorError(f"pod_create_failed_{completed.returncode}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "uncertain"}
    if not isinstance(value, Mapping):
        return {"status": "uncertain"}
    pod_id = value.get("id")
    pod_name = value.get("name")
    if not isinstance(pod_id, str) or not pod_id:
        return {"status": "uncertain"}
    if not isinstance(pod_name, str) or not pod_name:
        return {"status": "uncertain", "pod_id": pod_id}
    return {
        "status": "accepted",
        "pod_id": pod_id,
        "pod_name": pod_name,
    }


def _create_command(args: argparse.Namespace) -> tuple[str, ...]:
    command = [
        "pod",
        "create",
        "--name",
        args.pod_name,
        "--gpu-id",
        args.gpu_id,
        "--gpu-count",
        str(args.gpu_count),
        "--compute-type",
        args.compute_type,
        "--cloud-type",
        args.cloud_type,
        "--image",
        args.image,
        "--container-disk-in-gb",
        str(args.container_disk_gb),
        "--data-center-ids",
        args.data_center_id,
        "--network-volume-id",
        args.network_volume_id,
        "--volume-mount-path",
        args.volume_mount_path,
    ]
    command.extend(("--ports", ",".join(args.port)))
    command.append(f"--ssh={str(args.ssh).lower()}")
    if args.minimum_cuda_version:
        command.extend(("--min-cuda-version", args.minimum_cuda_version))
    return tuple(command)


def _stock_status(args: argparse.Namespace, query: JsonQuery) -> str:
    rows = _sequence(
        query(
            "gpu",
            ("gpu", "list", "--include-unavailable"),
            args.query_timeout_seconds,
        ),
        "gpu",
    )
    gpu = next(
        (
            row
            for row in rows
            if isinstance(row, Mapping) and row.get("gpuId") == args.gpu_id
        ),
        None,
    )
    if not isinstance(gpu, Mapping):
        raise MonitorError("gpu_catalog_entry_missing")
    availability = gpu.get("dataCenterAvailability")
    if not isinstance(availability, list):
        raise MonitorError("data_center_availability_invalid")
    center = next(
        (
            row
            for row in availability
            if isinstance(row, Mapping)
            and row.get("dataCenterId") == args.data_center_id
        ),
        None,
    )
    if not isinstance(center, Mapping):
        raise MonitorError("data_center_catalog_entry_missing")
    stock = center.get("stockStatus")
    if not isinstance(stock, str):
        raise MonitorError("data_center_stock_invalid")
    return stock.casefold()


def _exact_pods(args: argparse.Namespace, query: JsonQuery) -> list[dict[str, Any]]:
    rows = _sequence(
        query(
            "pods_exact",
            ("pod", "list", "--all", "--name", args.pod_name),
            args.query_timeout_seconds,
        ),
        "pods_exact",
    )
    if any(
        not isinstance(row, Mapping) or row.get("name") != args.pod_name for row in rows
    ):
        raise MonitorError("exact_name_query_shape_invalid")
    if len(rows) > 1:
        raise MonitorError("exact_name_duplicate")
    return [dict(row) for row in rows]


def _emit(sink: StatusSink, status: str, **fields: Any) -> dict[str, Any]:
    value = {
        "schema": SCHEMA,
        "captured_at": _utc_now(),
        "status": status,
        **fields,
    }
    sink(value)
    return value


def _stdout_sink(value: dict[str, Any]) -> None:
    print(json.dumps(value, sort_keys=True), flush=True)


def _reconcile(
    args: argparse.Namespace,
    *,
    query: JsonQuery,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
) -> tuple[dict[str, Any] | None, str | None]:
    deadline = monotonic() + args.reconciliation_grace_seconds
    successful_absences = 0
    last_error: str | None = None
    while True:
        try:
            rows = _exact_pods(args, query)
            if rows:
                return rows[0], None
            successful_absences += 1
            last_error = None
        except MonitorError as exc:
            successful_absences = 0
            last_error = exc.code
        remaining = deadline - monotonic()
        if remaining <= 0:
            if successful_absences >= 2:
                return None, None
            return None, last_error or "reconciliation_absence_unconfirmed"
        sleeper(min(args.poll_seconds, remaining))


def _validate_args(args: argparse.Namespace) -> None:
    numeric = (
        args.poll_seconds,
        args.query_timeout_seconds,
        args.create_timeout_seconds,
        args.reconciliation_grace_seconds,
        args.timeout_seconds,
    )
    try:
        finite = all(math.isfinite(float(value)) for value in numeric)
    except (TypeError, ValueError, OverflowError):
        finite = False
    if (
        not finite
        or not args.pod_name
        or not args.gpu_id
        or args.gpu_count <= 0
        or not args.compute_type
        or not args.cloud_type
        or not args.data_center_id
        or not args.image
        or args.container_disk_gb <= 0
        or not args.network_volume_id
        or not args.volume_mount_path.startswith("/")
        or not args.port
        or args.poll_seconds <= 0
        or args.query_timeout_seconds <= 0
        or args.create_timeout_seconds <= 0
        or args.reconciliation_grace_seconds <= 0
        or args.timeout_seconds < 0
    ):
        raise MonitorError("invalid_monitor_arguments")


def run_monitor(
    args: argparse.Namespace,
    *,
    query: JsonQuery,
    creator: PodCreator,
    sink: StatusSink = _stdout_sink,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[int, dict[str, Any]]:
    _validate_args(args)
    deadline = monotonic() + args.timeout_seconds if args.timeout_seconds else None
    attempts = 0

    def time_left() -> bool:
        return deadline is None or monotonic() < deadline

    while time_left():
        try:
            existing = _exact_pods(args, query)
            if existing:
                return 0, _emit(
                    sink,
                    "exact_pod_found",
                    pod=existing[0],
                    create_attempt_count=attempts,
                )
            stock = _stock_status(args, query)
        except MonitorError as exc:
            _emit(sink, "poll_error", error_code=exc.code)
            sleeper(args.poll_seconds)
            continue
        if stock not in READY_STOCK:
            _emit(sink, "waiting_capacity", stock_status=stock)
            sleeper(args.poll_seconds)
            continue

        attempts += 1
        try:
            outcome = creator(
                args.runpodctl,
                _create_command(args),
                args.create_timeout_seconds,
            )
        except MonitorError as exc:
            return 2, _emit(
                sink,
                "create_failed",
                create_attempt_count=attempts,
                error_code=exc.code,
            )
        if outcome.get("status") == "capacity_unavailable":
            _emit(
                sink,
                "waiting_create_capacity",
                create_attempt_count=attempts,
            )
            sleeper(args.poll_seconds)
            continue
        if outcome.get("status") == "accepted":
            if outcome.get("pod_name") != args.pod_name:
                return 2, _emit(
                    sink,
                    "create_identity_mismatch",
                    create_attempt_count=attempts,
                )
            return 0, _emit(
                sink,
                "pod_create_accepted",
                pod={
                    "id": outcome.get("pod_id"),
                    "name": outcome.get("pod_name"),
                },
                create_attempt_count=attempts,
            )

        pod, error = _reconcile(
            args,
            query=query,
            monotonic=monotonic,
            sleeper=sleeper,
        )
        if pod is not None:
            return 0, _emit(
                sink,
                "pod_create_reconciled",
                pod=pod,
                create_attempt_count=attempts,
            )
        if error is not None:
            return 2, _emit(
                sink,
                "create_reconciliation_failed",
                create_attempt_count=attempts,
                error_code=error,
            )
        _emit(
            sink,
            "create_unconfirmed_absent_after_grace",
            create_attempt_count=attempts,
        )
        sleeper(args.poll_seconds)

    return 5, _emit(
        sink,
        "monitor_timeout",
        create_attempt_count=attempts,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runpodctl", default="runpodctl")
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--gpu-id", required=True)
    parser.add_argument("--gpu-count", type=int, default=1)
    parser.add_argument("--compute-type", default="GPU")
    parser.add_argument("--cloud-type", default="SECURE")
    parser.add_argument("--data-center-id", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--container-disk-gb", type=int, required=True)
    parser.add_argument("--network-volume-id", required=True)
    parser.add_argument("--volume-mount-path", default="/workspace")
    parser.add_argument("--port", action="append", required=True)
    parser.add_argument("--ssh", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--minimum-cuda-version")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--query-timeout-seconds", type=float, default=15.0)
    parser.add_argument("--create-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--reconciliation-grace-seconds", type=float, default=30.0)
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    def query(label: str, command: Sequence[str], timeout: float | None) -> Any:
        return _run_json(args.runpodctl, label, command, timeout)

    try:
        code, _result = run_monitor(args, query=query, creator=_run_create)
        return code
    except MonitorError as exc:
        _stdout_sink(
            {
                "schema": SCHEMA,
                "captured_at": _utc_now(),
                "status": "monitor_failed",
                "error_code": exc.code,
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
