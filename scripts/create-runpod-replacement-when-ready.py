#!/usr/bin/env python3
"""Create one exact RunPod replacement when its locked GPU has capacity.

This provider-facing controller is deliberately narrower than a scheduler.  It
polls one Secure Cloud GPU model in one data center, creates one exact Pod name
on one already-verified Standard network volume, and never creates a second
candidate in parallel.  Every provider call reloads the external budget policy.
An uncertain create is reconciled by exact name before another create is
allowed.  Once the Pod is RUNNING, the existing handoff watchdog stops that
same Pod unless a local acknowledgement appears within the configured window.

Provider stdout and stderr are captured and reduced to stable error codes; raw
provider bodies are never written to stdout or the state log.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_EVAL_ROOT = _REPO_ROOT / "eval"
if str(_EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(_EVAL_ROOT))

from rondo_eval.budget_policy import (  # noqa: E402
    BudgetPolicyError,
    load_budget_policy,
)


_WAITER_PATH = Path(__file__).with_name("wait-runpod-readiness.py")
_WAITER_SPEC = importlib.util.spec_from_file_location(
    "rondo_replacement_readiness", _WAITER_PATH
)
if _WAITER_SPEC is None or _WAITER_SPEC.loader is None:
    raise RuntimeError("readiness_waiter_import_failed")
readiness = importlib.util.module_from_spec(_WAITER_SPEC)
_WAITER_SPEC.loader.exec_module(readiness)

_START_PATH = Path(__file__).with_name("start-runpod-when-ready.py")
_START_SPEC = importlib.util.spec_from_file_location(
    "rondo_replacement_start_wait", _START_PATH
)
if _START_SPEC is None or _START_SPEC.loader is None:
    raise RuntimeError("start_waiter_import_failed")
start_wait = importlib.util.module_from_spec(_START_SPEC)
_START_SPEC.loader.exec_module(start_wait)


REPLACEMENT_SCHEMA = "rondo-runpod-replacement-create-wait-v1"
ASSET_VERIFICATION_SCHEMA = (
    "rondo-runpod-network-volume-asset-verification-v1"
)
MAXIMUM_ASSET_VERIFICATION_BYTES = 64 * 1024
CAPACITY_STOCK = {"Low", "Medium", "High"}
_PROVIDER_STOCK_STATUS = {
    "none": "Out",
    "out": "Out",
    "low": "Low",
    "medium": "Medium",
    "high": "High",
}
CAPACITY_MARKERS = (
    "host capacity",
    "insufficient capacity",
    "no available host",
    "no instances available",
    "no longer any instances available",
    "not enough free gpu",
)
_HEX = frozenset("0123456789abcdef")


class ReplacementControllerError(RuntimeError):
    """One stable, provider-body-free replacement controller failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


JsonQuery = Callable[[str, Sequence[str], float | None], Any]
PodCreator = Callable[[str, Sequence[str], float | None], dict[str, Any]]
PodStopper = Callable[[str, str, float | None], None]
HandoffNotifier = Callable[[dict[str, Any]], None]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplacementControllerError(
                "asset_verification_json_duplicate_key"
            )
        result[key] = value
    return result


def _strict_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ReplacementControllerError(f"{field}_invalid")
    return value


def _finite_number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise ReplacementControllerError(f"{field}_invalid")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ReplacementControllerError(f"{field}_invalid") from exc
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        raise ReplacementControllerError(f"{field}_invalid")
    return number


def _normalize_stock_status(value: Any) -> str:
    """Map the CLI's case-insensitive stock enum to the controller contract."""

    if not isinstance(value, str) or not value or value.strip() != value:
        raise ReplacementControllerError("data_center_stock_invalid")
    normalized = _PROVIDER_STOCK_STATUS.get(value.casefold())
    if normalized is None:
        raise ReplacementControllerError("data_center_stock_invalid")
    return normalized


def _sha256(value: Any, field: str) -> str:
    text = _strict_string(value, field)
    if len(text) != 64 or any(character not in _HEX for character in text):
        raise ReplacementControllerError(f"{field}_invalid")
    return text


def _mapping(value: Any, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ReplacementControllerError(f"{field}_shape_invalid")
    return dict(value)


def _sequence(value: Any, field: str) -> list[Any]:
    try:
        return readiness._sequence(value, field)
    except readiness.ReadinessQueryError as exc:
        raise ReplacementControllerError(str(exc)) from exc


def load_asset_verification(args: argparse.Namespace) -> dict[str, Any]:
    """Load and exactly match the controller-side verified-volume marker."""

    source = Path(args.asset_verification_file)
    try:
        info = os.lstat(source)
    except OSError as exc:
        raise ReplacementControllerError("asset_verification_missing") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise ReplacementControllerError(
            "asset_verification_regular_mode_0600_required"
        )
    if info.st_size <= 0 or info.st_size > MAXIMUM_ASSET_VERIFICATION_BYTES:
        raise ReplacementControllerError("asset_verification_size_invalid")
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ReplacementControllerError("asset_verification_read_failed") from exc
    if len(raw) != info.st_size:
        raise ReplacementControllerError(
            "asset_verification_changed_during_read"
        )
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != args.asset_verification_sha256:
        raise ReplacementControllerError("asset_verification_sha256_mismatch")
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReplacementControllerError(
            "asset_verification_json_invalid"
        ) from exc
    top = _mapping(
        value,
        {
            "schema",
            "status",
            "verified_at",
            "network_volume",
            "asset_root",
            "checks",
        },
        "asset_verification",
    )
    if top["schema"] != ASSET_VERIFICATION_SCHEMA:
        raise ReplacementControllerError("asset_verification_schema_mismatch")
    if top["status"] != "verified":
        raise ReplacementControllerError("asset_verification_status_not_verified")
    _strict_string(top["verified_at"], "asset_verification_verified_at")
    if top["asset_root"] != args.asset_root:
        raise ReplacementControllerError("asset_verification_root_mismatch")
    volume = _mapping(
        top["network_volume"],
        {"id", "name", "type", "size_gb", "data_center_id", "mount_path"},
        "asset_verification_volume",
    )
    expected_volume = {
        "id": args.network_volume_id,
        "name": args.network_volume_name,
        "type": args.network_volume_type,
        "size_gb": args.network_volume_size_gb,
        "data_center_id": args.data_center_id,
        "mount_path": args.volume_mount_path,
    }
    if volume != expected_volume:
        raise ReplacementControllerError("asset_verification_volume_mismatch")
    checks = top["checks"]
    if not isinstance(checks, list) or not checks:
        raise ReplacementControllerError("asset_verification_checks_invalid")
    names: set[str] = set()
    normalized_checks: list[dict[str, str]] = []
    for item in checks:
        check = _mapping(
            item, {"name", "status", "evidence_sha256"}, "asset_check"
        )
        name = _strict_string(check["name"], "asset_check_name")
        if name in names:
            raise ReplacementControllerError("asset_check_name_duplicate")
        names.add(name)
        if check["status"] != "verified":
            raise ReplacementControllerError("asset_check_status_not_verified")
        normalized_checks.append(
            {
                "name": name,
                "status": "verified",
                "evidence_sha256": _sha256(
                    check["evidence_sha256"], "asset_check_evidence_sha256"
                ),
            }
        )
    required_checks = set(args.required_asset_check)
    if not required_checks.issubset(names):
        raise ReplacementControllerError("asset_required_check_missing")
    return {
        "schema": top["schema"],
        "status": top["status"],
        "verified_at": top["verified_at"],
        "network_volume": expected_volume,
        "asset_root": top["asset_root"],
        "checks": normalized_checks,
        "required_checks": sorted(required_checks),
        "source_sha256": actual_sha,
    }


def _load_policy(args: argparse.Namespace):
    try:
        return load_budget_policy(args.budget_policy)
    except BudgetPolicyError as exc:
        raise ReplacementControllerError(exc.code) from exc


def _run_json(
    client: str,
    label: str,
    command: Sequence[str],
    timeout: float | None,
) -> Any:
    try:
        return readiness._run_json(client, label, command, timeout=timeout)
    except readiness.ReadinessQueryError as exc:
        raise ReplacementControllerError(str(exc)) from exc


def _create_command(args: argparse.Namespace) -> tuple[str, ...]:
    return (
        "pod",
        "create",
        "--name",
        args.pod_name,
        "--gpu-id",
        args.gpu_id,
        "--gpu-count",
        "1",
        "--compute-type",
        "GPU",
        "--cloud-type",
        "SECURE",
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
        "--ports",
        args.port,
        "--ssh",
        "--min-cuda-version",
        args.minimum_cuda_version,
    )


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
        return {"status": "uncertain_timeout"}
    if completed.returncode != 0:
        body = f"{completed.stdout}\n{completed.stderr}".casefold()
        if any(marker in body for marker in CAPACITY_MARKERS):
            return {"status": "capacity_unavailable"}
        raise ReplacementControllerError(
            f"pod_create_failed_{completed.returncode}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "uncertain_success",
            "error_code": "pod_create_json_invalid",
        }
    if not isinstance(value, dict):
        return {
            "status": "uncertain_success",
            "error_code": "pod_create_shape_invalid",
        }
    pod_id = value.get("id")
    pod_name = value.get("name")
    if not isinstance(pod_id, str) or not pod_id:
        return {
            "status": "uncertain_success",
            "error_code": "pod_create_id_invalid",
        }
    if not isinstance(pod_name, str) or not pod_name:
        return {
            "status": "uncertain_success",
            "error_code": "pod_create_name_invalid",
            "pod_id": pod_id,
        }
    return {"status": "accepted", "pod_id": pod_id, "pod_name": pod_name}


def _normalize_volume(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplacementControllerError("network_volume_row_invalid")
    size = value.get("size")
    if size is None:
        size = value.get("sizeInGb")
    volume_type = value.get("type")
    if volume_type is None:
        volume_type = value.get("volumeType")
    return {
        "id": value.get("id"),
        "name": value.get("name"),
        "type": volume_type,
        "size_gb": size,
        "data_center_id": value.get("dataCenterId"),
    }


def _pod_is_stopped(value: Mapping[str, Any], args: argparse.Namespace) -> bool:
    return (
        value.get("desiredStatus") == args.stopped_desired_status
        and value.get("runtimeStatus") == args.stopped_runtime_status
    )


def _evaluate_cycle(
    args: argparse.Namespace,
    *,
    query: JsonQuery,
    timeout: float | None,
    adopted_pod_id: str | None,
) -> dict[str, Any]:
    marker = load_asset_verification(args)

    def checked_query(label: str, command: Sequence[str]) -> Any:
        _load_policy(args)
        return query(label, command, timeout)

    user = checked_query("user", ("user",))
    gpu_rows = _sequence(
        checked_query("gpu", ("gpu", "list", "--include-unavailable")),
        "gpu",
    )
    pod_rows = _sequence(
        checked_query("pods", ("pod", "list", "--all")), "pods"
    )
    volume_rows = _sequence(
        checked_query("network_volumes", ("network-volume", "list")),
        "network_volumes",
    )
    policy = _load_policy(args)
    if not isinstance(user, Mapping):
        raise ReplacementControllerError("user_shape_invalid")
    balance = _finite_number(user.get("clientBalance"), "client_balance")
    current_spend = _finite_number(
        user.get("currentSpendPerHr"), "account_current_spend"
    )

    catalog = next(
        (
            row
            for row in gpu_rows
            if isinstance(row, Mapping) and row.get("gpuId") == args.gpu_id
        ),
        None,
    )
    if not isinstance(catalog, Mapping):
        raise ReplacementControllerError("gpu_catalog_entry_missing")
    if catalog.get("memoryInGb") != args.gpu_memory_gb:
        raise ReplacementControllerError("gpu_memory_mismatch")
    price = _finite_number(
        catalog.get("securePricePerHr"), "secure_gpu_price", positive=True
    )
    failures: list[str] = []
    if price > args.maximum_gpu_price_per_hour:
        failures.append("gpu_price_gate_failed")
    availability = catalog.get("dataCenterAvailability")
    if not isinstance(availability, list):
        raise ReplacementControllerError("data_center_availability_invalid")
    data_center = next(
        (
            row
            for row in availability
            if isinstance(row, Mapping)
            and row.get("dataCenterId") == args.data_center_id
        ),
        None,
    )
    if not isinstance(data_center, Mapping):
        raise ReplacementControllerError("data_center_catalog_entry_missing")
    stock = _normalize_stock_status(data_center.get("stockStatus"))

    matching_volumes = [
        _normalize_volume(row)
        for row in volume_rows
        if isinstance(row, Mapping) and row.get("id") == args.network_volume_id
    ]
    if len(matching_volumes) != 1:
        failures.append("network_volume_identity_missing_or_duplicate")
        volume = None
    else:
        provider_volume = matching_volumes[0]
        expected = {
            "id": args.network_volume_id,
            "name": args.network_volume_name,
            "type": args.network_volume_type,
            "size_gb": args.network_volume_size_gb,
            "data_center_id": args.data_center_id,
        }
        provider_type = provider_volume.get("type")
        compared_fields = {"id", "name", "size_gb", "data_center_id"}
        if (
            any(provider_volume.get(key) != expected[key] for key in compared_fields)
            or provider_type not in (None, expected["type"])
        ):
            failures.append("network_volume_contract_mismatch")
        volume = {
            **provider_volume,
            "type": expected["type"] if provider_type is None else provider_type,
            "type_source": (
                "asset_verification" if provider_type is None else "provider"
            ),
        }

    task_pods: list[dict[str, Any]] = []
    exact_pods: list[dict[str, Any]] = []
    for row in pod_rows:
        if not isinstance(row, Mapping):
            raise ReplacementControllerError("pod_row_invalid")
        name = row.get("name")
        if not isinstance(name, str):
            continue
        if name.startswith(args.task_pod_name_prefix):
            normalized = dict(row)
            task_pods.append(normalized)
            if name == args.pod_name:
                exact_pods.append(normalized)
    if len(exact_pods) > 1:
        failures.append("replacement_exact_name_duplicate")
    exact_pod = exact_pods[0] if len(exact_pods) == 1 else None
    allowed_stopped = set(args.allowed_stopped_pod_id)
    for pod in task_pods:
        pod_id = pod.get("id")
        gpu_count = pod.get("gpuCount")
        if not isinstance(pod_id, str) or not pod_id:
            failures.append("task_pod_id_invalid")
            continue
        if isinstance(gpu_count, bool) or not isinstance(gpu_count, int):
            failures.append("task_pod_gpu_count_invalid")
            continue
        if pod_id in allowed_stopped:
            if not _pod_is_stopped(pod, args):
                failures.append("allowed_task_pod_not_stopped")
            continue
        if pod.get("name") == args.pod_name:
            continue
        failures.append("other_task_pod_exists")

    if adopted_pod_id is None and exact_pod is not None:
        if _pod_is_stopped(exact_pod, args):
            failures.append("replacement_exact_name_already_stopped")
        elif exact_pod.get("id") is None:
            failures.append("replacement_exact_name_id_invalid")
    if adopted_pod_id is not None:
        if exact_pod is None or exact_pod.get("id") != adopted_pod_id:
            failures.append("adopted_pod_identity_missing")

    conservative_cost = max(0.0, args.baseline_balance - balance)
    projected_cost = conservative_cost + args.maximum_additional_seconds / 3600.0 * (
        price + args.running_storage_per_hour
    )
    if conservative_cost >= policy.hard_cap_usd:
        budget_decision = "hard_cap_reached"
        failures.append("hard_cap_gate_failed")
    elif conservative_cost >= policy.delete_now_cutoff_usd:
        budget_decision = "delete_now"
        failures.append("delete_now_cutoff_reached")
    elif conservative_cost >= policy.stop_and_recover_cutoff_usd:
        budget_decision = "stop_and_recover"
        failures.append("stop_and_recover_cutoff_reached")
    elif projected_cost > policy.normal_work_cutoff_usd:
        budget_decision = "no_new_work"
        failures.append("projected_cost_gate_failed")
    else:
        budget_decision = "normal_work"

    return {
        "schema": REPLACEMENT_SCHEMA,
        "captured_at": readiness._utc_now(),
        "status": (
            "blocked"
            if failures
            else "ready"
            if stock in CAPACITY_STOCK
            else "waiting_capacity"
        ),
        "gpu": {
            "id": args.gpu_id,
            "memory_gb": args.gpu_memory_gb,
            "secure_cloud": True,
            "data_center_id": args.data_center_id,
            "stock_status": stock,
            "price_per_hour_usd": price,
        },
        "network_volume": volume,
        "asset_verification": {
            "source_sha256": marker["source_sha256"],
            "asset_root": marker["asset_root"],
            "check_count": len(marker["checks"]),
            "required_checks": marker["required_checks"],
        },
        "replacement": {
            "pod_name": args.pod_name,
            "adopted_pod_id": adopted_pod_id,
            "exact_name_count": len(exact_pods),
            "task_pod_count": len(task_pods),
        },
        "budget": {
            "client_balance_usd": balance,
            "account_current_spend_per_hour_usd": current_spend,
            "conservative_cost_usd": conservative_cost,
            "projected_cost_usd": projected_cost,
            "decision": budget_decision,
            "policy": policy.as_receipt(),
        },
        "failures": failures,
        "_exact_pod": exact_pod,
    }


def _running_handoff_snapshot(
    args: argparse.Namespace, value: Any, pod_id: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplacementControllerError("running_pod_shape_invalid")
    if value.get("id") != pod_id or value.get("name") != args.pod_name:
        raise ReplacementControllerError("running_pod_identity_mismatch")
    if (
        value.get("desiredStatus") != args.running_desired_status
        or value.get("runtimeStatus") != args.running_runtime_status
    ):
        raise ReplacementControllerError("running_pod_status_mismatch")
    return {
        "id": pod_id,
        "name": args.pod_name,
        "desired_status": args.running_desired_status,
        "runtime_status": args.running_runtime_status,
        "provider_review_required": True,
    }


def _validate_created_pod_identity(value: Any, pod_id: str) -> str:
    """Bind a provider-success ID to one exact returned Pod name."""

    if not isinstance(value, Mapping) or value.get("id") != pod_id:
        raise ReplacementControllerError("created_pod_id_mismatch")
    return _strict_string(value.get("name"), "created_pod_name")


def _public_cycle(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if not key.startswith("_")}


def _require_create_budget(
    args: argparse.Namespace, cycle: Mapping[str, Any]
) -> None:
    """Re-evaluate the last priced cycle against a freshly loaded policy."""

    policy = _load_policy(args)
    budget = cycle.get("budget")
    if not isinstance(budget, Mapping):
        raise ReplacementControllerError("create_budget_snapshot_missing")
    conservative = _finite_number(
        budget.get("conservative_cost_usd"), "create_conservative_cost"
    )
    projected = _finite_number(
        budget.get("projected_cost_usd"), "create_projected_cost"
    )
    if (
        conservative >= policy.stop_and_recover_cutoff_usd
        or projected > policy.normal_work_cutoff_usd
    ):
        raise ReplacementControllerError("create_budget_gate_failed")


def _record(
    args: argparse.Namespace,
    *,
    status: str,
    create_attempt_count: int,
    cycle: dict[str, Any] | None = None,
    pod_id: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": REPLACEMENT_SCHEMA,
        "captured_at": readiness._utc_now(),
        "status": status,
        "replacement": {
            "pod_id": pod_id,
            "pod_name": args.pod_name,
            "create_attempt_count": create_attempt_count,
        },
    }
    if cycle is not None:
        result["cycle"] = _public_cycle(cycle)
    if error_code is not None:
        result["error_code"] = error_code
    readiness._append_log(args.state_log, result)
    return result


def _emergency_stop_and_confirm(
    args: argparse.Namespace,
    *,
    pod_id: str,
    reason: str,
    create_attempt_count: int,
    query: JsonQuery,
    stopper: PodStopper,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
    confirmed_pod_name: str | None = None,
    stop_on_initial_identity_mismatch: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Best-effort exact cleanup which a broken budget file cannot prevent."""

    deadline = monotonic() + args.handoff_timeout_seconds
    policy_reload_failed = False
    cleanup_pod_name = confirmed_pod_name or args.pod_name

    def cleanup_result(status: str, error_code: str) -> dict[str, Any]:
        try:
            return _record(
                args,
                status=status,
                create_attempt_count=create_attempt_count,
                pod_id=pod_id,
                error_code=error_code,
            )
        except Exception:
            # Cleanup already happened (or failed) independently of observability.
            # Return a body-free in-memory terminal result when the local log is
            # unavailable; never let a disk failure prevent the exact stop call.
            return {
                "schema": REPLACEMENT_SCHEMA,
                "captured_at": readiness._utc_now(),
                "status": status,
                "replacement": {
                    "pod_id": pod_id,
                    "pod_name": cleanup_pod_name,
                    "create_attempt_count": create_attempt_count,
                },
                "error_code": f"{error_code}:state_log_write_failed",
            }

    def remaining() -> float:
        value = deadline - monotonic()
        if value <= 0:
            raise ReplacementControllerError("cleanup_confirmation_timeout")
        return value

    def reload_policy_best_effort() -> None:
        nonlocal policy_reload_failed
        try:
            _load_policy(args)
        except ReplacementControllerError:
            policy_reload_failed = True

    def read_exact() -> dict[str, Any]:
        reload_policy_best_effort()
        try:
            value = query(
                "pod",
                (
                    "pod",
                    "get",
                    pod_id,
                    "--include-machine",
                    "--include-network-volume",
                ),
                remaining(),
            )
        except (ReplacementControllerError, readiness.ReadinessQueryError) as exc:
            raise ReplacementControllerError("cleanup_pod_query_failed") from exc
        except Exception as exc:
            raise ReplacementControllerError("cleanup_pod_query_failed") from exc
        if (
            not isinstance(value, Mapping)
            or value.get("id") != pod_id
            or value.get("name") != cleanup_pod_name
        ):
            raise ReplacementControllerError("cleanup_pod_identity_mismatch")
        return dict(value)

    first_query_error: ReplacementControllerError | None = None
    try:
        pod = read_exact()
    except ReplacementControllerError as exc:
        first_query_error = exc
        pod = None
    if pod is not None and _pod_is_stopped(pod, args):
        code = reason
        if policy_reload_failed:
            code += ":budget_policy_reload_failed_ignored"
        result = cleanup_result("cleanup_already_stopped", code)
        return 6, result
    if first_query_error is not None and first_query_error.code == (
        "cleanup_pod_identity_mismatch"
    ) and not stop_on_initial_identity_mismatch:
        result = cleanup_result("cleanup_failed", first_query_error.code)
        return 7, result

    last_error = first_query_error
    while True:
        reload_policy_best_effort()
        try:
            stopper(args.runpodctl, pod_id, remaining())
        except (ReplacementControllerError, start_wait.StartWaitError):
            last_error = ReplacementControllerError("cleanup_stop_failed")
        except Exception:
            last_error = ReplacementControllerError("cleanup_stop_failed")
        try:
            pod = read_exact()
            last_error = None
        except ReplacementControllerError as exc:
            last_error = exc
            if exc.code == "cleanup_pod_identity_mismatch":
                break
        else:
            if _pod_is_stopped(pod, args):
                code = reason
                if policy_reload_failed:
                    code += ":budget_policy_reload_failed_ignored"
                status = (
                    "handoff_timeout_stopped"
                    if reason == "handoff_timeout"
                    else "handoff_failure_stopped"
                )
                result = cleanup_result(status, code)
                return 6, result
        try:
            sleeper(min(args.poll_seconds, remaining()))
        except ReplacementControllerError as exc:
            last_error = exc
            break
    error_code = last_error.code if last_error is not None else (
        "cleanup_confirmation_timeout"
    )
    if policy_reload_failed:
        error_code += ":budget_policy_reload_failed_ignored"
    result = cleanup_result("cleanup_failed", error_code)
    return 7, result


def _wait_for_replacement_handoff(
    args: argparse.Namespace,
    *,
    pod_id: str,
    create_attempt_count: int,
    query: JsonQuery,
    stopper: PodStopper,
    monotonic: Callable[[], float],
    sleeper: Callable[[float], None],
) -> tuple[int, dict[str, Any]]:
    deadline = monotonic() + args.handoff_timeout_seconds
    while True:
        try:
            info = os.lstat(args.handoff_ack_file)
        except FileNotFoundError:
            info = None
        except OSError:
            return _emergency_stop_and_confirm(
                args,
                pod_id=pod_id,
                reason="handoff_ack_inspection_failed",
                create_attempt_count=create_attempt_count,
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
                    create_attempt_count=create_attempt_count,
                    pod_id=pod_id,
                )
                return 0, result
            return _emergency_stop_and_confirm(
                args,
                pod_id=pod_id,
                reason="handoff_ack_unsafe",
                create_attempt_count=create_attempt_count,
                query=query,
                stopper=stopper,
                monotonic=monotonic,
                sleeper=sleeper,
            )
        remaining = deadline - monotonic()
        if remaining <= 0:
            return _emergency_stop_and_confirm(
                args,
                pod_id=pod_id,
                reason="handoff_timeout",
                create_attempt_count=create_attempt_count,
                query=query,
                stopper=stopper,
                monotonic=monotonic,
                sleeper=sleeper,
            )
        sleeper(min(args.poll_seconds, remaining))


@contextmanager
def _controller_lock(path: Path) -> Iterator[None]:
    source = Path(path)
    source.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if source.is_symlink():
        raise ReplacementControllerError("controller_lock_symlink_rejected")
    if source.exists() and not stat.S_ISREG(os.lstat(source).st_mode):
        raise ReplacementControllerError("controller_lock_not_regular")
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags, 0o600)
    except OSError as exc:
        raise ReplacementControllerError("controller_lock_open_failed") from exc
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ReplacementControllerError(
                "replacement_controller_already_running"
            ) from exc
        yield
    finally:
        os.close(descriptor)


def _validate_args(args: argparse.Namespace) -> None:
    finite_values = (
        args.maximum_gpu_price_per_hour,
        args.baseline_balance,
        args.maximum_additional_seconds,
        args.running_storage_per_hour,
        args.poll_seconds,
        args.create_timeout_seconds,
        args.create_reconciliation_grace_seconds,
        args.running_transition_timeout_seconds,
        args.handoff_timeout_seconds,
        args.timeout_seconds,
    )
    try:
        finite = all(math.isfinite(float(value)) for value in finite_values)
    except (TypeError, ValueError, OverflowError):
        finite = False
    if (
        not finite
        or not args.pod_name
        or not args.task_pod_name_prefix
        or not args.pod_name.startswith(args.task_pod_name_prefix)
        or not args.gpu_id
        or args.gpu_memory_gb <= 0
        or args.expected_gpu_count != 1
        or args.cloud_type != "SECURE"
        or not args.data_center_id
        or not args.image
        or args.container_disk_gb <= 0
        or not args.network_volume_id
        or not args.network_volume_name
        or args.network_volume_type != "STANDARD"
        or args.network_volume_size_gb <= 0
        or not args.volume_mount_path.startswith("/")
        or not args.asset_root.startswith(args.volume_mount_path.rstrip("/") + "/")
        or not args.minimum_cuda_version
        or not args.expected_cuda_version
        or not args.required_asset_check
        or len(set(args.required_asset_check)) != len(args.required_asset_check)
        or any(
            not isinstance(name, str) or not name or name.strip() != name
            for name in args.required_asset_check
        )
        or len(set(args.allowed_stopped_pod_id))
        != len(args.allowed_stopped_pod_id)
        or any(
            not isinstance(pod_id, str) or not pod_id or pod_id.strip() != pod_id
            for pod_id in args.allowed_stopped_pod_id
        )
        or args.maximum_gpu_price_per_hour <= 0
        or args.baseline_balance < 0
        or args.maximum_additional_seconds <= 0
        or args.running_storage_per_hour < 0
        or args.poll_seconds <= 0
        or args.create_timeout_seconds <= 0
        or args.create_reconciliation_grace_seconds <= 0
        or args.running_transition_timeout_seconds <= 0
        or args.handoff_timeout_seconds <= 0
        or args.timeout_seconds < 0
    ):
        raise SystemExit("invalid replacement controller bounds")
    _sha256(args.asset_verification_sha256, "asset_verification_sha256")
    try:
        start_wait._require_fresh_handoff_ack(args.handoff_ack_file)
    except start_wait.StartWaitError as exc:
        raise SystemExit("handoff ack file must not already exist") from exc
    load_asset_verification(args)
    _load_policy(args)


def run_replacement_controller(
    args: argparse.Namespace,
    *,
    query: JsonQuery,
    creator: PodCreator,
    stopper: PodStopper = start_wait._stop_same_pod,
    handoff_notifier: HandoffNotifier = start_wait._stdout_handoff,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[int, dict[str, Any]]:
    """Run the exact-name replacement loop with injectable provider seams."""

    _validate_args(args)
    with _controller_lock(args.controller_lock):
        started_at = monotonic()
        deadline = started_at + args.timeout_seconds if args.timeout_seconds else None
        adopted_pod_id: str | None = None
        adopted_at: float | None = None
        attempts = 0

        def remaining() -> float | None:
            if deadline is None:
                return None
            value = deadline - monotonic()
            if value <= 0:
                raise ReplacementControllerError(
                    "replacement_controller_deadline_exceeded"
                )
            return value

        def checked_query(
            label: str, command: Sequence[str], timeout: float | None
        ) -> Any:
            _load_policy(args)
            return query(label, command, timeout)

        def pause() -> None:
            if deadline is None:
                sleeper(args.poll_seconds)
                return
            sleeper(min(args.poll_seconds, remaining() or args.poll_seconds))

        def stop_adopted(reason: str) -> tuple[int, dict[str, Any]]:
            assert adopted_pod_id is not None
            return _emergency_stop_and_confirm(
                args,
                pod_id=adopted_pod_id,
                reason=reason,
                create_attempt_count=attempts,
                query=query,
                stopper=stopper,
                monotonic=monotonic,
                sleeper=sleeper,
            )

        def reconcile_uncertain_create() -> tuple[dict[str, Any] | None, str | None]:
            reconciliation_deadline = (
                monotonic() + args.create_reconciliation_grace_seconds
            )
            last_error: str | None = None
            absence_streak = 0
            while True:
                # Reconciliation is a safety read: a temporarily malformed budget
                # authority is recorded by the caller but must not hide a Pod that
                # may already have been created.
                query_succeeded = False
                try:
                    _load_policy(args)
                except ReplacementControllerError:
                    last_error = "budget_policy_reload_failed_ignored"
                try:
                    rows = _sequence(
                        query(
                            "pods_exact",
                            ("pod", "list", "--all", "--name", args.pod_name),
                            min(
                                args.create_timeout_seconds,
                                max(0.001, reconciliation_deadline - monotonic()),
                            ),
                        ),
                        "pods_exact",
                    )
                    if any(
                        not isinstance(row, Mapping)
                        or row.get("name") != args.pod_name
                        for row in rows
                    ):
                        raise ReplacementControllerError(
                            "create_reconciliation_shape_invalid"
                        )
                    query_succeeded = True
                except (ReplacementControllerError, readiness.ReadinessQueryError):
                    rows = []
                    absence_streak = 0
                    last_error = "create_reconciliation_query_failed"
                except Exception:
                    rows = []
                    absence_streak = 0
                    last_error = "create_reconciliation_query_failed"
                exact = [
                    row
                    for row in rows
                    if isinstance(row, Mapping) and row.get("name") == args.pod_name
                ]
                if len(exact) > 1:
                    raise ReplacementControllerError(
                        "replacement_exact_name_duplicate"
                    )
                if len(exact) == 1:
                    return dict(exact[0]), last_error
                if query_succeeded:
                    absence_streak += 1
                    last_error = None
                remaining_grace = reconciliation_deadline - monotonic()
                if remaining_grace <= 0:
                    if absence_streak >= 2:
                        return None, None
                    return None, last_error or (
                        "create_reconciliation_absence_unconfirmed"
                    )
                sleeper(min(args.poll_seconds, remaining_grace))

        def inspect_returned_create_id(candidate_id: str) -> str | None:
            try:
                _load_policy(args)
            except ReplacementControllerError:
                pass
            try:
                returned_pod = query(
                    "pod",
                    (
                        "pod",
                        "get",
                        candidate_id,
                        "--include-machine",
                        "--include-network-volume",
                    ),
                    args.create_timeout_seconds,
                )
                return _validate_created_pod_identity(returned_pod, candidate_id)
            except (
                ReplacementControllerError,
                readiness.ReadinessQueryError,
            ):
                return None
            except Exception:
                return None

        while True:
            if adopted_pod_id is not None:
                assert adopted_at is not None
                try:
                    pod = checked_query(
                        "pod",
                        (
                            "pod",
                            "get",
                            adopted_pod_id,
                            "--include-machine",
                            "--include-network-volume",
                        ),
                        remaining(),
                    )
                except ReplacementControllerError as exc:
                    if (
                        monotonic() - adopted_at
                        < args.running_transition_timeout_seconds
                    ):
                        try:
                            _record(
                                args,
                                status="waiting_running_transition",
                                create_attempt_count=attempts,
                                pod_id=adopted_pod_id,
                                error_code=exc.code,
                            )
                            pause()
                        except Exception:
                            return stop_adopted(
                                "replacement_transition_wait_failure"
                            )
                        continue
                    return stop_adopted(
                        f"replacement_running_query_timeout:{exc.code}"
                    )
                if (
                    not isinstance(pod, Mapping)
                    or pod.get("id") != adopted_pod_id
                    or pod.get("name") != args.pod_name
                ):
                    return stop_adopted(
                        "replacement_adopted_identity_mismatch"
                    )
                desired = pod.get("desiredStatus")
                runtime = pod.get("runtimeStatus")
                if (
                    desired == args.running_desired_status
                    and runtime == args.running_runtime_status
                ):
                    try:
                        running = _running_handoff_snapshot(
                            args, pod, adopted_pod_id
                        )
                        handoff_notifier(
                            {
                                "schema": REPLACEMENT_SCHEMA,
                                "status": "running_handoff_pending",
                                "pod": {
                                    "id": adopted_pod_id,
                                    "name": args.pod_name,
                                },
                                "running_provider_facts": running,
                                "asset_root": args.asset_root,
                                "asset_verification_sha256": (
                                    args.asset_verification_sha256
                                ),
                                "handoff_ack_file": str(args.handoff_ack_file),
                            }
                        )
                        _record(
                            args,
                            status="running_handoff_pending",
                            create_attempt_count=attempts,
                            pod_id=adopted_pod_id,
                        )
                        return _wait_for_replacement_handoff(
                            args,
                            pod_id=adopted_pod_id,
                            create_attempt_count=attempts,
                            query=query,
                            stopper=stopper,
                            monotonic=monotonic,
                            sleeper=sleeper,
                        )
                    except Exception:
                        return stop_adopted("replacement_pre_handoff_failure")
                if _pod_is_stopped(pod, args):
                    result = _record(
                        args,
                        status="blocked",
                        create_attempt_count=attempts,
                        pod_id=adopted_pod_id,
                        error_code="adopted_pod_stopped_before_handoff",
                    )
                    return 2, result
                if (
                    monotonic() - adopted_at
                    >= args.running_transition_timeout_seconds
                ):
                    return stop_adopted(
                        "replacement_running_transition_timeout"
                    )
                try:
                    _record(
                        args,
                        status="waiting_running_transition",
                        create_attempt_count=attempts,
                        pod_id=adopted_pod_id,
                    )
                    pause()
                except Exception:
                    return stop_adopted("replacement_transition_wait_failure")
                continue

            try:
                preflight_rows = _sequence(
                    checked_query(
                        "pods_preflight",
                        ("pod", "list", "--all"),
                        remaining(),
                    ),
                    "pods_preflight",
                )
            except ReplacementControllerError as exc:
                result = _record(
                    args,
                    status="provider_or_contract_failure",
                    create_attempt_count=attempts,
                    error_code=exc.code,
                )
                return 4, result
            if any(
                not isinstance(row, Mapping)
                or not isinstance(row.get("name"), str)
                for row in preflight_rows
            ):
                result = _record(
                    args,
                    status="provider_or_contract_failure",
                    create_attempt_count=attempts,
                    error_code="replacement_preflight_shape_invalid",
                )
                return 4, result
            task_rows = [
                row
                for row in preflight_rows
                if row.get("name", "").startswith(args.task_pod_name_prefix)
            ]
            exact_rows = [
                row for row in task_rows if row.get("name") == args.pod_name
            ]
            if len(exact_rows) > 1:
                result = _record(
                    args,
                    status="blocked",
                    create_attempt_count=attempts,
                    error_code="replacement_exact_name_duplicate",
                )
                return 2, result
            preflight_failures: list[str] = []
            allowed_stopped = set(args.allowed_stopped_pod_id)
            for row in task_rows:
                pod_id = row.get("id")
                if not isinstance(pod_id, str) or not pod_id:
                    preflight_failures.append("task_pod_id_invalid")
                elif pod_id in allowed_stopped:
                    if not _pod_is_stopped(row, args):
                        preflight_failures.append(
                            "allowed_task_pod_not_stopped"
                        )
                elif row.get("name") != args.pod_name:
                    preflight_failures.append("other_task_pod_exists")
            if len(exact_rows) == 1:
                candidate_id = exact_rows[0].get("id")
                if not isinstance(candidate_id, str) or not candidate_id:
                    result = _record(
                        args,
                        status="provider_or_contract_failure",
                        create_attempt_count=attempts,
                        error_code="replacement_exact_name_id_invalid",
                    )
                    return 4, result
                adopted_pod_id = candidate_id
                adopted_at = monotonic()
                if preflight_failures:
                    return stop_adopted(
                        "replacement_preflight_"
                        + preflight_failures[0]
                    )
                try:
                    _record(
                        args,
                        status="existing_exact_name_adopted",
                        create_attempt_count=attempts,
                        pod_id=adopted_pod_id,
                    )
                except Exception:
                    return stop_adopted("replacement_adoption_log_failure")
                continue
            if preflight_failures:
                result = _record(
                    args,
                    status="blocked",
                    create_attempt_count=attempts,
                    error_code=preflight_failures[0],
                )
                return 2, result

            try:
                cycle = _evaluate_cycle(
                    args,
                    query=checked_query,
                    timeout=remaining(),
                    adopted_pod_id=None,
                )
            except ReplacementControllerError as exc:
                result = _record(
                    args,
                    status="provider_or_contract_failure",
                    create_attempt_count=attempts,
                    pod_id=adopted_pod_id,
                    error_code=exc.code,
                )
                return 4, result

            exact_pod = cycle.get("_exact_pod")
            if adopted_pod_id is None and isinstance(exact_pod, Mapping):
                candidate_id = exact_pod.get("id")
                if isinstance(candidate_id, str) and candidate_id:
                    adopted_pod_id = candidate_id
                    adopted_at = monotonic()
                    try:
                        _record(
                            args,
                            status="existing_exact_name_adopted",
                            create_attempt_count=attempts,
                            cycle=cycle,
                            pod_id=adopted_pod_id,
                        )
                    except Exception:
                        return stop_adopted("replacement_adoption_log_failure")
                    continue

            if cycle["failures"]:
                result = _record(
                    args,
                    status="blocked",
                    create_attempt_count=attempts,
                    cycle=cycle,
                    pod_id=adopted_pod_id,
                )
                return 2, result

            if cycle["status"] == "waiting_capacity":
                _record(
                    args,
                    status="waiting_capacity",
                    create_attempt_count=attempts,
                    cycle=cycle,
                )
                pause()
                continue
            if cycle["status"] != "ready":
                result = _record(
                    args,
                    status="blocked",
                    create_attempt_count=attempts,
                    cycle=cycle,
                    error_code="replacement_cycle_status_invalid",
                )
                return 2, result

            # Reload both local authorities immediately before the paid mutation.
            try:
                _require_create_budget(args, cycle)
            except ReplacementControllerError as exc:
                result = _record(
                    args,
                    status="blocked",
                    create_attempt_count=attempts,
                    cycle=cycle,
                    error_code=exc.code,
                )
                return 2, result
            load_asset_verification(args)
            attempts += 1
            try:
                outcome = creator(
                    args.runpodctl,
                    _create_command(args),
                    min(args.create_timeout_seconds, remaining())
                    if remaining() is not None
                    else args.create_timeout_seconds,
                )
            except ReplacementControllerError as exc:
                result = _record(
                    args,
                    status="create_failed",
                    create_attempt_count=attempts,
                    cycle=cycle,
                    error_code=exc.code,
                )
                return 2, result
            status = outcome.get("status") if isinstance(outcome, Mapping) else None
            if status == "capacity_unavailable":
                _record(
                    args,
                    status="waiting_create_capacity",
                    create_attempt_count=attempts,
                    cycle=cycle,
                    error_code="pod_create_capacity_unavailable",
                )
                pause()
                continue
            if status == "accepted":
                status = "accepted_unverified"
            elif status not in {
                "uncertain_timeout",
                "uncertain_success",
                "uncertain_response",
            }:
                status = "uncertain_response"
            returned_id = (
                outcome.get("pod_id") if isinstance(outcome, Mapping) else None
            )
            if not isinstance(returned_id, str) or not returned_id:
                returned_id = None
            returned_actual_name = (
                inspect_returned_create_id(returned_id)
                if returned_id is not None
                else None
            )
            try:
                exact, reconciliation_error = reconcile_uncertain_create()
            except ReplacementControllerError as exc:
                result = _record(
                    args,
                    status="create_reconciliation_failed",
                    create_attempt_count=attempts,
                    cycle=cycle,
                    error_code=exc.code,
                )
                return 2, result
            if exact is not None:
                exact_id = exact.get("id")
                if not isinstance(exact_id, str) or not exact_id:
                    result = _record(
                        args,
                        status="create_reconciliation_failed",
                        create_attempt_count=attempts,
                        cycle=cycle,
                        error_code="replacement_exact_name_id_invalid",
                    )
                    return 2, result
                if (
                    returned_id is not None
                    and returned_id != exact_id
                ):
                    cleanup_code, cleanup_result = _emergency_stop_and_confirm(
                        args,
                        pod_id=returned_id,
                        reason="create_returned_id_conflicts_with_exact_name",
                        create_attempt_count=attempts,
                        query=query,
                        stopper=stopper,
                        monotonic=monotonic,
                        sleeper=sleeper,
                        confirmed_pod_name=returned_actual_name,
                        stop_on_initial_identity_mismatch=True,
                    )
                    if cleanup_code != 6:
                        return cleanup_code, cleanup_result
                if (
                    returned_id == exact_id
                    and returned_actual_name is not None
                    and returned_actual_name != args.pod_name
                ):
                    return _emergency_stop_and_confirm(
                        args,
                        pod_id=returned_id,
                        reason="create_exact_id_name_conflict",
                        create_attempt_count=attempts,
                        query=query,
                        stopper=stopper,
                        monotonic=monotonic,
                        sleeper=sleeper,
                        confirmed_pod_name=returned_actual_name,
                        stop_on_initial_identity_mismatch=True,
                    )
                adopted_pod_id = exact_id
                adopted_at = monotonic()
                try:
                    _record(
                        args,
                        status="create_uncertain_exact_name_adopted",
                        create_attempt_count=attempts,
                        cycle=cycle,
                        pod_id=adopted_pod_id,
                        error_code=status,
                    )
                except Exception:
                    return stop_adopted("replacement_adoption_log_failure")
                continue
            if returned_actual_name == args.pod_name and returned_id is not None:
                adopted_pod_id = returned_id
                adopted_at = monotonic()
                try:
                    _record(
                        args,
                        status="create_returned_id_adopted_after_name_absence",
                        create_attempt_count=attempts,
                        cycle=cycle,
                        pod_id=adopted_pod_id,
                        error_code=status,
                    )
                except Exception:
                    return stop_adopted("replacement_adoption_log_failure")
                continue
            if returned_actual_name is not None and returned_id is not None:
                return _emergency_stop_and_confirm(
                    args,
                    pod_id=returned_id,
                    reason="create_returned_id_name_mismatch",
                    create_attempt_count=attempts,
                    query=query,
                    stopper=stopper,
                    monotonic=monotonic,
                    sleeper=sleeper,
                    confirmed_pod_name=returned_actual_name,
                    stop_on_initial_identity_mismatch=True,
                )
            if returned_id is not None:
                # A provider-success ID remains a cleanup anchor even when both
                # ownership inspection and exact-name listing are temporarily
                # unable to bind the object.  The cleanup helper deliberately
                # attempts stop-by-ID after a failed initial read and then makes
                # bounded confirmation attempts.
                return _emergency_stop_and_confirm(
                    args,
                    pod_id=returned_id,
                    reason="create_returned_id_unbound_after_reconciliation",
                    create_attempt_count=attempts,
                    query=query,
                    stopper=stopper,
                    monotonic=monotonic,
                    sleeper=sleeper,
                    stop_on_initial_identity_mismatch=True,
                )
            if reconciliation_error is not None:
                result = _record(
                    args,
                    status="create_reconciliation_failed",
                    create_attempt_count=attempts,
                    cycle=cycle,
                    error_code=reconciliation_error,
                )
                return 4, result
            if status == "uncertain_timeout":
                _record(
                    args,
                    status="create_timeout_no_object",
                    create_attempt_count=attempts,
                    cycle=cycle,
                    error_code="pod_create_timeout_reconciled_absent",
                )
                pause()
                continue
            result = _record(
                args,
                status="create_uncertain_no_exact_object",
                create_attempt_count=attempts,
                cycle=cycle,
                error_code=status,
            )
            return 2, result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runpodctl", default="runpodctl")
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--task-pod-name-prefix", required=True)
    parser.add_argument("--allowed-stopped-pod-id", action="append", default=[])
    parser.add_argument("--stopped-desired-status", default="EXITED")
    parser.add_argument("--stopped-runtime-status", default="stopped")
    parser.add_argument("--running-desired-status", default="RUNNING")
    parser.add_argument("--running-runtime-status", default="running")
    parser.add_argument("--gpu-id", required=True)
    parser.add_argument("--gpu-memory-gb", type=int, required=True)
    parser.add_argument("--expected-gpu-count", type=int, default=1)
    parser.add_argument("--cloud-type", choices=("SECURE",), default="SECURE")
    parser.add_argument("--data-center-id", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--container-disk-gb", type=int, required=True)
    parser.add_argument("--network-volume-id", required=True)
    parser.add_argument("--network-volume-name", required=True)
    parser.add_argument(
        "--network-volume-type", choices=("STANDARD",), default="STANDARD"
    )
    parser.add_argument("--network-volume-size-gb", type=int, required=True)
    parser.add_argument("--volume-mount-path", required=True)
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--asset-verification-file", type=Path, required=True)
    parser.add_argument("--asset-verification-sha256", required=True)
    parser.add_argument("--required-asset-check", action="append", required=True)
    parser.add_argument("--port", default="22/tcp")
    parser.add_argument("--minimum-cuda-version", required=True)
    parser.add_argument("--expected-cuda-version", required=True)
    parser.add_argument("--maximum-gpu-price-per-hour", type=float, required=True)
    parser.add_argument("--baseline-balance", type=float, required=True)
    parser.add_argument("--maximum-additional-seconds", type=float, required=True)
    parser.add_argument("--running-storage-per-hour", type=float, required=True)
    parser.add_argument("--budget-policy", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--create-timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--create-reconciliation-grace-seconds", type=float, default=30.0
    )
    parser.add_argument(
        "--running-transition-timeout-seconds", type=float, default=180.0
    )
    parser.add_argument("--handoff-ack-file", type=Path, required=True)
    parser.add_argument("--handoff-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--timeout-seconds", type=float, default=0.0)
    parser.add_argument("--state-log", type=Path, required=True)
    parser.add_argument("--controller-lock", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    def query(label: str, command: Sequence[str], timeout: float | None) -> Any:
        return _run_json(args.runpodctl, label, command, timeout)

    try:
        code, result = run_replacement_controller(
            args, query=query, creator=_run_create
        )
    except ReplacementControllerError as exc:
        result = _record(
            args,
            status="controller_failed",
            create_attempt_count=0,
            error_code=exc.code,
        )
        code = 2
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
