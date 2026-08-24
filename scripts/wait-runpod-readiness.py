#!/usr/bin/env python3
"""Poll a RunPod Pod until machine, capacity, price, and budget gates agree.

All task and hardware identities are CLI parameters, so the same read-only
waiter can be reused for another Pod, GPU model, data center, or runtime budget
policy. It never starts, stops, creates, or deletes a resource. Exit 0 means
ready, 2 a stable gate failure, 3 a non-ready ``--once`` sample, 4 repeated
query errors, and 5 expiry of the shared query/poll deadline.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from rondo_eval.budget_policy import (  # noqa: E402
    BudgetPolicyError,
    load_budget_policy,
)


class ReadinessQueryError(RuntimeError):
    """A sanitized RunPod read failed."""


JsonQuery = Callable[[str, Sequence[str]], Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ReadinessQueryError(f"{field}_invalid")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReadinessQueryError(f"{field}_invalid") from exc
    if not math.isfinite(result):
        raise ReadinessQueryError(f"{field}_invalid")
    return result


def _run_json(
    client: str,
    label: str,
    arguments: Sequence[str],
    *,
    timeout: float | None = None,
) -> Any:
    try:
        completed = subprocess.run(
            [client, *arguments, "-o", "json"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ReadinessQueryError(f"{label}_query_timeout") from exc
    if completed.returncode != 0:
        raise ReadinessQueryError(f"{label}_query_failed_{completed.returncode}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReadinessQueryError(f"{label}_json_invalid") from exc


def _sequence(value: Any, label: str) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("data", "items"):
            if isinstance(value.get(key), list):
                return value[key]
    raise ReadinessQueryError(f"{label}_shape_invalid")


def evaluate(args: argparse.Namespace, query: JsonQuery) -> dict[str, Any]:
    try:
        budget_policy = load_budget_policy(args.budget_policy)
    except BudgetPolicyError as exc:
        raise ReadinessQueryError(exc.code) from exc
    pod = query("pod", ("pod", "get", args.pod_id, "--include-machine"))
    user = query("user", ("user",))
    gpu_rows = _sequence(
        query("gpu", ("gpu", "list", "--include-unavailable")), "gpu"
    )
    billing_rows = _sequence(
        query(
            "billing",
            (
                "billing",
                "pods",
                "--bucket-size",
                "hour",
                "--start-time",
                args.billing_start_time,
                "--grouping",
                "podId",
                "--pod-id",
                args.pod_id,
            ),
        ),
        "billing",
    )
    if not isinstance(pod, dict) or not isinstance(user, dict):
        raise ReadinessQueryError("provider_shape_invalid")
    gpu = next(
        (
            row
            for row in gpu_rows
            if isinstance(row, dict) and row.get("gpuId") == args.gpu_id
        ),
        None,
    )
    if gpu is None:
        raise ReadinessQueryError("gpu_catalog_entry_missing")

    failures: list[str] = []
    if pod.get("id") != args.pod_id or pod.get("name") != args.pod_name:
        failures.append("pod_identity_mismatch")
    if (
        pod.get("desiredStatus") != args.required_desired_status
        or pod.get("runtimeStatus") != args.required_runtime_status
    ):
        failures.append("pod_status_mismatch")
    if pod.get("gpuCount") != args.expected_gpu_count:
        failures.append("pod_gpu_count_mismatch")
    machine = pod.get("machine")
    if not isinstance(machine, dict):
        failures.append("pod_machine_missing")
        machine = {}
    if machine.get("gpuId") != args.gpu_id:
        failures.append("pod_gpu_model_mismatch")
    if args.data_center_id and machine.get("dataCenterId") != args.data_center_id:
        failures.append("pod_data_center_mismatch")
    if (
        args.expected_machine_location
        and machine.get("location") != args.expected_machine_location
    ):
        failures.append("pod_machine_location_mismatch")

    pod_price = _finite_number(pod.get("costPerHr"), "pod_price")
    catalog_price = _finite_number(gpu.get(args.price_field), "catalog_price")
    if pod_price < 0 or catalog_price < 0:
        raise ReadinessQueryError("gpu_price_invalid")
    if (
        pod_price > args.maximum_gpu_price_per_hour
        or catalog_price > args.maximum_gpu_price_per_hour
    ):
        failures.append("gpu_price_gate_failed")
    if gpu.get("memoryInGb") != args.gpu_memory_gb:
        failures.append("gpu_memory_mismatch")

    balance = _finite_number(user.get("clientBalance"), "client_balance")
    current_spend = _finite_number(
        user.get("currentSpendPerHr"), "account_current_spend"
    )
    if balance < 0 or current_spend < 0:
        raise ReadinessQueryError("account_financials_invalid")
    billing_total = 0.0
    for row in billing_rows:
        if not isinstance(row, dict) or row.get("podId") != args.pod_id:
            raise ReadinessQueryError("billing_row_identity_invalid")
        amount = _finite_number(row.get("amount"), "billing_amount")
        if amount < 0:
            raise ReadinessQueryError("billing_amount_invalid")
        billing_total += amount
    if not math.isfinite(billing_total):
        raise ReadinessQueryError("billing_total_invalid")
    balance_delta = max(0.0, args.baseline_balance - balance)
    conservative_cost = max(balance_delta, billing_total)
    requested_seconds = _finite_number(
        args.maximum_additional_seconds, "maximum_additional_seconds"
    )
    requested_hours = requested_seconds / 3600.0
    effective_gpu_price = max(pod_price, catalog_price)
    projection = conservative_cost + requested_hours * (
        effective_gpu_price + args.running_storage_per_hour
    )
    if not math.isfinite(projection):
        raise ReadinessQueryError("projected_cost_invalid")
    if conservative_cost >= budget_policy.hard_cap_usd:
        budget_decision = "hard_cap_reached"
        failures.append("hard_cap_gate_failed")
    elif conservative_cost >= budget_policy.delete_now_cutoff_usd:
        budget_decision = "delete_now"
        failures.append("delete_now_cutoff_reached")
    elif conservative_cost >= budget_policy.stop_and_recover_cutoff_usd:
        budget_decision = "stop_and_recover"
        failures.append("stop_and_recover_cutoff_reached")
    elif projection > budget_policy.normal_work_cutoff_usd:
        budget_decision = "no_new_work"
        failures.append("projected_cost_gate_failed")
    else:
        budget_decision = "normal_work"

    availability_rows = gpu.get("dataCenterAvailability")
    if args.data_center_id:
        if not isinstance(availability_rows, list):
            raise ReadinessQueryError("data_center_availability_invalid")
        data_center = next(
            (
                row
                for row in availability_rows
                if isinstance(row, dict)
                and row.get("dataCenterId") == args.data_center_id
            ),
            None,
        )
        if data_center is None:
            raise ReadinessQueryError("data_center_catalog_entry_missing")
        available = data_center.get("stockStatus") in {"Low", "Medium", "High"}
    else:
        available = gpu.get("available") is True
    if failures:
        status = "blocked"
    elif available:
        status = "ready"
    else:
        status = "waiting_capacity"
    return {
        "schema": "rondo-runpod-readiness-wait-v1",
        "captured_at": _utc_now(),
        "status": status,
        "pod": {
            "id": pod.get("id"),
            "name": pod.get("name"),
            "desired_status": pod.get("desiredStatus"),
            "runtime_status": pod.get("runtimeStatus"),
            "gpu_count": pod.get("gpuCount"),
            "machine_gpu_id": machine.get("gpuId"),
            "machine_data_center_id": machine.get("dataCenterId"),
            "machine_location": machine.get("location"),
        },
        "gpu": {
            "id": gpu.get("gpuId"),
            "memory_gb": gpu.get("memoryInGb"),
            "available": available,
            "price_field": args.price_field,
            "pod_price_per_hour_usd": pod_price,
            "price_per_hour_usd": catalog_price,
            "data_center_id": args.data_center_id,
            "stock": availability_rows,
        },
        "budget": {
            "client_balance_usd": balance,
            "account_current_spend_per_hour_usd": current_spend,
            "balance_delta_usd": balance_delta,
            "task_billing_usd": billing_total,
            "conservative_cost_usd": conservative_cost,
            "maximum_additional_seconds": args.maximum_additional_seconds,
            "projected_cost_usd": projection,
            "decision": budget_decision,
            "policy": budget_policy.as_receipt(),
        },
        "failures": failures,
    }


def _append_log(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink():
        raise ReadinessQueryError("state_log_symlink_rejected")
    if path.exists() and not stat.S_ISREG(os.lstat(path).st_mode):
        raise ReadinessQueryError("state_log_not_regular")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        os.write(descriptor, payload.encode("utf-8"))
    finally:
        os.close(descriptor)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runpodctl", default="runpodctl")
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--required-desired-status", default="EXITED")
    parser.add_argument("--required-runtime-status", default="stopped")
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
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    parser.add_argument("--maximum-consecutive-query-errors", type=int, default=10)
    parser.add_argument("--required-consecutive-ready", type=int, default=1)
    parser.add_argument("--state-log", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    finite_values = (
        args.maximum_gpu_price_per_hour,
        args.baseline_balance,
        args.running_storage_per_hour,
        args.poll_seconds,
        args.timeout_seconds,
    )
    try:
        finite_bounds = all(math.isfinite(float(value)) for value in finite_values)
    except (TypeError, ValueError, OverflowError):
        finite_bounds = False
    if (
        not finite_bounds
        or not args.pod_id
        or not args.pod_name
        or not args.gpu_id
        or args.gpu_memory_gb <= 0
        or args.expected_gpu_count <= 0
        or not args.required_desired_status
        or not args.required_runtime_status
        or args.maximum_gpu_price_per_hour < 0
        or args.baseline_balance < 0
        or args.maximum_additional_seconds <= 0
        or args.running_storage_per_hour < 0
        or args.poll_seconds <= 0
        or args.timeout_seconds < 0
        or args.maximum_consecutive_query_errors <= 0
        or args.required_consecutive_ready <= 0
    ):
        raise SystemExit("invalid readiness wait bounds")
    started = time.monotonic()
    deadline = started + args.timeout_seconds if args.timeout_seconds else None
    consecutive_errors = 0
    consecutive_ready = 0
    last_result: dict[str, Any] | None = None

    def timeout_result(result: dict[str, Any] | None) -> dict[str, Any]:
        return {
            **(result or {"schema": "rondo-runpod-readiness-wait-v1"}),
            "captured_at": _utc_now(),
            "status": "timeout",
        }

    def remaining_query_seconds() -> float | None:
        if deadline is None:
            return None
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ReadinessQueryError("readiness_deadline_exceeded")
        return remaining

    while True:
        if deadline is not None and time.monotonic() >= deadline:
            result = timeout_result(last_result)
            _append_log(args.state_log, result)
            print(json.dumps(result, sort_keys=True))
            return 5
        try:
            result = evaluate(
                args,
                lambda label, command: _run_json(
                    args.runpodctl,
                    label,
                    command,
                    timeout=remaining_query_seconds(),
                ),
            )
            consecutive_errors = 0
        except ReadinessQueryError as exc:
            consecutive_errors += 1
            result = {
                "schema": "rondo-runpod-readiness-wait-v1",
                "captured_at": _utc_now(),
                "status": "query_error",
                "error_code": str(exc),
                "consecutive_errors": consecutive_errors,
            }
        if deadline is not None and time.monotonic() >= deadline:
            result = timeout_result(result)
            _append_log(args.state_log, result)
            print(json.dumps(result, sort_keys=True))
            return 5
        last_result = result
        if result["status"] == "ready":
            consecutive_ready += 1
            result["consecutive_ready"] = consecutive_ready
            result["required_consecutive_ready"] = args.required_consecutive_ready
            if consecutive_ready < args.required_consecutive_ready:
                result["status"] = "confirming_ready"
        else:
            consecutive_ready = 0
        _append_log(args.state_log, result)
        if result["status"] == "ready":
            print(json.dumps(result, sort_keys=True))
            return 0
        if result["status"] == "blocked":
            print(json.dumps(result, sort_keys=True))
            return 2
        if args.once:
            print(json.dumps(result, sort_keys=True))
            return 3
        if consecutive_errors >= args.maximum_consecutive_query_errors:
            print(json.dumps(result, sort_keys=True))
            return 4
        sleep_seconds = args.poll_seconds
        if deadline is not None:
            sleep_seconds = min(sleep_seconds, max(0.0, deadline - time.monotonic()))
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
