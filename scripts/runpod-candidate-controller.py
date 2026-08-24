#!/usr/bin/env python3
"""Pure selection and winner-lock seams for a small RunPod GPU candidate set.

This module deliberately does not call RunPod.  A provider-facing controller
supplies normalized catalog and Pod facts, then applies the returned decision.
The external budget policy is reloaded for every selection cycle.  The only
write performed here is an exclusive, mode-0600 winner lock after an exact
RUNNING Pod identity and hardware match.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[1]
_EVAL_ROOT = _REPO_ROOT / "eval"
if str(_EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(_EVAL_ROOT))

from rondo_eval.budget_policy import BudgetPolicyError, load_budget_policy  # noqa: E402


_START_PATH = Path(__file__).with_name("start-runpod-when-ready.py")
_START_SPEC = importlib.util.spec_from_file_location(
    "rondo_start_runpod_when_ready_for_candidates", _START_PATH
)
if _START_SPEC is None or _START_SPEC.loader is None:
    raise RuntimeError("existing_pod_start_import_failed")
_start_wait = importlib.util.module_from_spec(_START_SPEC)
_START_SPEC.loader.exec_module(_start_wait)


CANDIDATE_CYCLE_SCHEMA = "rondo-runpod-candidate-cycle-v1"
WINNER_LOCK_SCHEMA = "rondo-publication-critic-plan060-winner-lock-v1"
MAXIMUM_WINNER_LOCK_BYTES = 64 * 1024
STOCK_RANK = {"Out": 0, "Low": 1, "Medium": 2, "High": 3}
PLAN060_WINNER_GPU_IDS = {
    "NVIDIA H100 PCIe",
    "NVIDIA H100 80GB HBM3",
}

_CANDIDATE_KEYS = {
    "candidate_id",
    "gpu_id",
    "gpu_count",
    "gpu_memory_gb",
    "secure_cloud",
    "preference",
    "allowed_data_center_ids",
    "allowed_cuda_versions",
}
_OBSERVATION_KEYS = {
    "candidate_id",
    "gpu_id",
    "gpu_count",
    "gpu_memory_gb",
    "secure_cloud",
    "data_center_id",
    "cuda_version",
    "stock_status",
    "price_per_hour_usd",
}
_RUNNING_POD_KEYS = {
    "id",
    "name",
    "desired_status",
    "runtime_status",
    "candidate_id",
    "gpu_id",
    "gpu_count",
    "gpu_memory_gb",
    "secure_cloud",
    "data_center_id",
    "cuda_version",
    "cost_per_hour_usd",
}
_RECONCILIATION_POD_KEYS = {
    "id",
    "name",
    "desired_status",
    "runtime_status",
    "gpu_id",
    "gpu_count",
    "gpu_memory_gb",
    "secure_cloud",
    "data_center_id",
    "cuda_version",
}


class CandidateControllerError(RuntimeError):
    """A stable, provider-body-free candidate controller failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _object(value: Any, keys: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CandidateControllerError(f"{label}_shape_invalid")
    return dict(value)


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise CandidateControllerError(f"{field}_invalid")
    return value


def _integer(value: Any, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CandidateControllerError(f"{field}_invalid")
    if value < 0 or (value == 0 and not allow_zero):
        raise CandidateControllerError(f"{field}_invalid")
    return value


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise CandidateControllerError(f"{field}_invalid")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CandidateControllerError(f"{field}_invalid") from exc
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        raise CandidateControllerError(f"{field}_invalid")
    return result


def _string_tuple(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CandidateControllerError(f"{field}_invalid")
    items = tuple(_string(item, field) for item in value)
    if len(set(items)) != len(items):
        raise CandidateControllerError(f"{field}_duplicate")
    return items


def normalize_candidate(value: Any) -> dict[str, Any]:
    row = _object(value, _CANDIDATE_KEYS, "candidate")
    secure_cloud = row["secure_cloud"]
    if not isinstance(secure_cloud, bool):
        raise CandidateControllerError("candidate_secure_cloud_invalid")
    return {
        "candidate_id": _string(row["candidate_id"], "candidate_id"),
        "gpu_id": _string(row["gpu_id"], "candidate_gpu_id"),
        "gpu_count": _integer(row["gpu_count"], "candidate_gpu_count"),
        "gpu_memory_gb": _integer(
            row["gpu_memory_gb"], "candidate_gpu_memory_gb"
        ),
        "secure_cloud": secure_cloud,
        "preference": _integer(
            row["preference"], "candidate_preference", allow_zero=True
        ),
        "allowed_data_center_ids": list(
            _string_tuple(
                row["allowed_data_center_ids"], "candidate_data_center_id"
            )
        ),
        "allowed_cuda_versions": list(
            _string_tuple(row["allowed_cuda_versions"], "candidate_cuda_version")
        ),
    }


def normalize_observation(value: Any) -> dict[str, Any]:
    row = _object(value, _OBSERVATION_KEYS, "candidate_observation")
    secure_cloud = row["secure_cloud"]
    if not isinstance(secure_cloud, bool):
        raise CandidateControllerError("observation_secure_cloud_invalid")
    stock = _string(row["stock_status"], "observation_stock_status")
    if stock not in STOCK_RANK:
        raise CandidateControllerError("observation_stock_status_unknown")
    return {
        "candidate_id": _string(row["candidate_id"], "observation_candidate_id"),
        "gpu_id": _string(row["gpu_id"], "observation_gpu_id"),
        "gpu_count": _integer(row["gpu_count"], "observation_gpu_count"),
        "gpu_memory_gb": _integer(
            row["gpu_memory_gb"], "observation_gpu_memory_gb"
        ),
        "secure_cloud": secure_cloud,
        "data_center_id": _string(
            row["data_center_id"], "observation_data_center_id"
        ),
        "cuda_version": _string(row["cuda_version"], "observation_cuda_version"),
        "stock_status": stock,
        "price_per_hour_usd": _number(
            row["price_per_hour_usd"],
            "observation_price_per_hour_usd",
            positive=True,
        ),
    }


def _match_observation(
    candidate: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    for key in (
        "candidate_id",
        "gpu_id",
        "gpu_count",
        "gpu_memory_gb",
        "secure_cloud",
    ):
        if observation[key] != candidate[key]:
            raise CandidateControllerError(f"observation_{key}_mismatch")
    if observation["data_center_id"] not in candidate["allowed_data_center_ids"]:
        raise CandidateControllerError("observation_data_center_not_allowed")
    if observation["cuda_version"] not in candidate["allowed_cuda_versions"]:
        raise CandidateControllerError("observation_cuda_version_not_allowed")


def _enforce_plan060_gpu_contract(value: Mapping[str, Any], label: str) -> None:
    if value["gpu_id"] not in PLAN060_WINNER_GPU_IDS:
        raise CandidateControllerError(f"{label}_gpu_id_not_allowed")
    if value["gpu_count"] != 1:
        raise CandidateControllerError(f"{label}_gpu_count_not_one")
    if value["gpu_memory_gb"] != 80:
        raise CandidateControllerError(f"{label}_gpu_memory_not_80gb")
    if value["secure_cloud"] is not True:
        raise CandidateControllerError(f"{label}_secure_cloud_required")


def select_candidate_cycle(
    candidates: Sequence[Mapping[str, Any]],
    observations: Sequence[Mapping[str, Any]],
    *,
    budget_policy_path: Path,
    conservative_cost_usd: float,
    projected_runtime_seconds: float,
    hourly_non_gpu_cost_usd: float,
    additional_fixed_cost_usd: float = 0.0,
    winner_lock_path: Path | None = None,
    require_secure_cloud: bool = True,
) -> dict[str, Any]:
    """Reload policy, validate one complete sample, and rank eligible candidates."""

    try:
        policy = load_budget_policy(budget_policy_path)
    except BudgetPolicyError as exc:
        raise CandidateControllerError(exc.code) from exc
    current_cost = _number(conservative_cost_usd, "conservative_cost_usd")
    runtime_seconds = _number(
        projected_runtime_seconds, "projected_runtime_seconds", positive=True
    )
    non_gpu_hourly = _number(hourly_non_gpu_cost_usd, "hourly_non_gpu_cost_usd")
    fixed_cost = _number(additional_fixed_cost_usd, "additional_fixed_cost_usd")
    normalized_candidates = [normalize_candidate(value) for value in candidates]
    normalized_observations = [normalize_observation(value) for value in observations]
    if require_secure_cloud is not True:
        raise CandidateControllerError("plan060_secure_cloud_requirement_fixed")
    if not normalized_candidates:
        raise CandidateControllerError("candidate_set_empty")
    candidate_ids = [row["candidate_id"] for row in normalized_candidates]
    observation_ids = [row["candidate_id"] for row in normalized_observations]
    if len(set(candidate_ids)) != len(candidate_ids):
        raise CandidateControllerError("candidate_id_duplicate")
    if len(set(observation_ids)) != len(observation_ids):
        raise CandidateControllerError("observation_candidate_id_duplicate")
    if set(candidate_ids) != set(observation_ids):
        raise CandidateControllerError("candidate_observation_set_mismatch")

    by_observation = {row["candidate_id"]: row for row in normalized_observations}
    rows: list[dict[str, Any]] = []
    for candidate in normalized_candidates:
        observation = by_observation[candidate["candidate_id"]]
        _match_observation(candidate, observation)
        _enforce_plan060_gpu_contract(candidate, "candidate")
        _enforce_plan060_gpu_contract(observation, "observation")
        projected_cost = fixed_cost + current_cost + runtime_seconds / 3600.0 * (
            observation["price_per_hour_usd"] + non_gpu_hourly
        )
        if not math.isfinite(projected_cost):
            raise CandidateControllerError("projected_cost_invalid")
        rows.append(
            {
                "candidate": candidate,
                "observation": observation,
                "projected_total_cost_usd": projected_cost,
                "budget_eligible": projected_cost <= policy.normal_work_cutoff_usd,
            }
        )

    locked_gpu_id: str | None = None
    if winner_lock_path is not None and _path_exists(winner_lock_path):
        locked_gpu_id = load_winner_lock(winner_lock_path)["selected_gpu"]
        rows = [row for row in rows if row["observation"]["gpu_id"] == locked_gpu_id]
        if not rows:
            raise CandidateControllerError("locked_gpu_not_in_candidate_sample")

    rows.sort(
        key=lambda row: (
            -STOCK_RANK[row["observation"]["stock_status"]],
            row["candidate"]["preference"],
            row["observation"]["price_per_hour_usd"],
            row["observation"]["data_center_id"],
            row["candidate"]["candidate_id"],
        )
    )
    if current_cost >= policy.hard_cap_usd:
        decision = "hard_cap_reached"
        selected = None
    elif current_cost >= policy.delete_now_cutoff_usd:
        decision = "delete_now"
        selected = None
    elif current_cost >= policy.stop_and_recover_cutoff_usd:
        decision = "stop_and_recover"
        selected = None
    else:
        ready = [
            row
            for row in rows
            if row["budget_eligible"] and STOCK_RANK[row["observation"]["stock_status"]]
        ]
        selected = ready[0] if ready else None
        if selected is not None:
            decision = "ready"
        elif not any(row["budget_eligible"] for row in rows):
            decision = "no_new_work"
        else:
            decision = "waiting_capacity"
    return {
        "schema": CANDIDATE_CYCLE_SCHEMA,
        "captured_at": _utc_now(),
        "status": decision,
        "winner_gpu_id": locked_gpu_id,
        "budget_policy": policy.as_receipt(),
        "ordered_candidates": rows,
        "selected_candidate": selected,
    }


def _path_exists(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise CandidateControllerError("winner_lock_inspection_failed") from exc
    return True


def _load_regular_0600_json(path: Path) -> dict[str, Any]:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise CandidateControllerError("winner_lock_missing") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size <= 0
        or info.st_size > MAXIMUM_WINNER_LOCK_BYTES
    ):
        raise CandidateControllerError("winner_lock_file_invalid")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CandidateControllerError("winner_lock_read_failed") from exc
    if len(raw) != info.st_size:
        raise CandidateControllerError("winner_lock_changed_during_read")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateControllerError("winner_lock_json_invalid") from exc
    if not isinstance(value, dict):
        raise CandidateControllerError("winner_lock_shape_invalid")
    return value


def load_winner_lock(path: Path) -> dict[str, Any]:
    value = _load_regular_0600_json(path)
    if value.get("schema") != WINNER_LOCK_SCHEMA:
        raise CandidateControllerError("winner_lock_schema_invalid")
    selected = value.get("selected_gpu")
    if not isinstance(selected, str) or selected not in PLAN060_WINNER_GPU_IDS:
        raise CandidateControllerError("winner_lock_selected_gpu_invalid")
    evidence = value.get("evidence")
    if not isinstance(evidence, dict):
        raise CandidateControllerError("winner_lock_evidence_invalid")
    selected_facts = evidence.get("selected_gpu_facts")
    if not isinstance(selected_facts, dict) or selected_facts.get("gpu_id") != selected:
        raise CandidateControllerError("winner_lock_selected_gpu_facts_invalid")
    return value


def _normalize_running_pod(value: Any) -> dict[str, Any]:
    row = _object(value, _RUNNING_POD_KEYS, "running_pod")
    secure_cloud = row["secure_cloud"]
    if not isinstance(secure_cloud, bool):
        raise CandidateControllerError("running_pod_secure_cloud_invalid")
    return {
        "id": _string(row["id"], "running_pod_id"),
        "name": _string(row["name"], "running_pod_name"),
        "desired_status": _string(
            row["desired_status"], "running_pod_desired_status"
        ),
        "runtime_status": _string(
            row["runtime_status"], "running_pod_runtime_status"
        ),
        "candidate_id": _string(row["candidate_id"], "running_pod_candidate_id"),
        "gpu_id": _string(row["gpu_id"], "running_pod_gpu_id"),
        "gpu_count": _integer(row["gpu_count"], "running_pod_gpu_count"),
        "gpu_memory_gb": _integer(
            row["gpu_memory_gb"], "running_pod_gpu_memory_gb"
        ),
        "secure_cloud": secure_cloud,
        "data_center_id": _string(
            row["data_center_id"], "running_pod_data_center_id"
        ),
        "cuda_version": _string(row["cuda_version"], "running_pod_cuda_version"),
        "cost_per_hour_usd": _number(
            row["cost_per_hour_usd"],
            "running_pod_cost_per_hour_usd",
            positive=True,
        ),
    }


def write_winner_lock(
    path: Path,
    selected_observation: Mapping[str, Any],
    running_pod: Mapping[str, Any],
    *,
    expected_pod_id: str,
    expected_pod_name: str,
    evidence: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    """Exclusively lock a verified RUNNING winner; return (record, created)."""

    selected = normalize_observation(selected_observation)
    pod = _normalize_running_pod(running_pod)
    _enforce_plan060_gpu_contract(selected, "winner_observation")
    _enforce_plan060_gpu_contract(pod, "running_pod")
    if pod["id"] != expected_pod_id or pod["name"] != expected_pod_name:
        raise CandidateControllerError("running_pod_identity_mismatch")
    if pod["desired_status"] != "RUNNING" or pod["runtime_status"] != "running":
        raise CandidateControllerError("running_pod_status_unverified")
    for pod_key, selected_key in (
        ("candidate_id", "candidate_id"),
        ("gpu_id", "gpu_id"),
        ("gpu_count", "gpu_count"),
        ("gpu_memory_gb", "gpu_memory_gb"),
        ("secure_cloud", "secure_cloud"),
        ("data_center_id", "data_center_id"),
        ("cuda_version", "cuda_version"),
    ):
        if pod[pod_key] != selected[selected_key]:
            raise CandidateControllerError(f"running_pod_{pod_key}_mismatch")
    if not math.isclose(
        pod["cost_per_hour_usd"], selected["price_per_hour_usd"], rel_tol=1e-9
    ):
        raise CandidateControllerError("running_pod_price_mismatch")
    if evidence is not None and not isinstance(evidence, Mapping):
        raise CandidateControllerError("winner_lock_evidence_invalid")
    if evidence is not None and "selected_gpu_facts" in evidence:
        raise CandidateControllerError("winner_lock_evidence_reserved_field")
    selected_gpu = {
        "candidate_id": selected["candidate_id"],
        "gpu_id": selected["gpu_id"],
        "gpu_count": selected["gpu_count"],
        "gpu_memory_gb": selected["gpu_memory_gb"],
        "secure_cloud": selected["secure_cloud"],
        "data_center_id": selected["data_center_id"],
        "cuda_version": selected["cuda_version"],
        "price_per_hour_usd": selected["price_per_hour_usd"],
    }
    record: dict[str, Any] = {
        "schema": WINNER_LOCK_SCHEMA,
        "locked_at": _utc_now(),
        "selected_gpu": selected["gpu_id"],
        "pod": {"id": pod["id"], "name": pod["name"]},
        "evidence": {
            **({} if evidence is None else dict(evidence)),
            "selected_gpu_facts": selected_gpu,
        },
    }
    try:
        raw = (
            json.dumps(
                record, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            + "\n"
        ).encode()
    except (TypeError, ValueError) as exc:
        raise CandidateControllerError("winner_lock_json_invalid") from exc
    if len(raw) > MAXIMUM_WINNER_LOCK_BYTES:
        raise CandidateControllerError("winner_lock_size_invalid")

    target = Path(path)
    try:
        parent_info = os.lstat(target.parent)
    except OSError as exc:
        raise CandidateControllerError("winner_lock_parent_invalid") from exc
    if not stat.S_ISDIR(parent_info.st_mode) or stat.S_ISLNK(parent_info.st_mode):
        raise CandidateControllerError("winner_lock_parent_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(target, flags, 0o600)
    except FileExistsError:
        existing = load_winner_lock(target)
        if existing["selected_gpu"] != selected["gpu_id"]:
            raise CandidateControllerError("winner_gpu_already_locked")
        return existing, False
    except OSError as exc:
        raise CandidateControllerError("winner_lock_create_failed") from exc
    try:
        os.fchmod(fd, 0o600)
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if written <= 0:
                raise OSError("short write")
            offset += written
        os.fsync(fd)
    except OSError as exc:
        try:
            os.close(fd)
        finally:
            _unlink_if_regular(target)
        raise CandidateControllerError("winner_lock_write_failed") from exc
    os.close(fd)
    return record, True


def _unlink_if_regular(path: Path) -> None:
    try:
        info = os.lstat(path)
        if stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            os.unlink(path)
    except OSError:
        pass


def classify_provider_failure(
    *, return_code: int | None, message: str, timed_out: bool = False
) -> str:
    """Classify captured provider failure without returning its body."""

    if timed_out:
        return "reconcile_create_name"
    if not isinstance(message, str):
        raise CandidateControllerError("provider_failure_message_invalid")
    if isinstance(return_code, bool) or not isinstance(return_code, int):
        raise CandidateControllerError("provider_failure_return_code_invalid")
    body = message.casefold()
    # A CLI usually returns a small process exit code and may omit HTTP 400;
    # direct clients may instead provide the HTTP status.  Preserve explicit
    # non-capacity HTTP failures while sharing the existing allowlisted
    # capacity phrases for both representations.
    explicit_other_http_failure = 400 < return_code < 500
    if not explicit_other_http_failure and any(
        marker in body for marker in _start_wait.CAPACITY_MARKERS
    ):
        return "retry_capacity"
    return "fail"


def decide_after_create_failure(
    *,
    failure_class: str,
    attempted_candidate_id: str,
    ordered_candidate_ids: Sequence[str],
) -> dict[str, Any]:
    """Turn one sanitized create failure into a deterministic next action."""

    failure = _string(failure_class, "provider_failure_class")
    attempted = _string(attempted_candidate_id, "attempted_candidate_id")
    candidate_ids = [
        _string(value, "ordered_candidate_id") for value in ordered_candidate_ids
    ]
    if not candidate_ids or len(set(candidate_ids)) != len(candidate_ids):
        raise CandidateControllerError("ordered_candidate_ids_invalid")
    try:
        index = candidate_ids.index(attempted)
    except ValueError as exc:
        raise CandidateControllerError("attempted_candidate_not_ordered") from exc
    if failure == "fail":
        return {"action": "fail", "reason": "provider_error"}
    if failure == "reconcile_create_name":
        return {"action": "reconcile_create_name", "candidate_id": attempted}
    if failure != "retry_capacity":
        raise CandidateControllerError("provider_failure_class_unknown")
    if index + 1 < len(candidate_ids):
        return {
            "action": "try_candidate",
            "candidate_id": candidate_ids[index + 1],
            "reason": "prior_candidate_capacity_unavailable",
        }
    return {"action": "wait_capacity", "reason": "candidate_set_exhausted"}


def _normalize_reconciliation_pod(value: Any) -> dict[str, Any]:
    row = _object(value, _RECONCILIATION_POD_KEYS, "reconciliation_pod")
    count = _integer(row["gpu_count"], "reconciliation_pod_gpu_count", allow_zero=True)
    result = {
        "id": _string(row["id"], "reconciliation_pod_id"),
        "name": _string(row["name"], "reconciliation_pod_name"),
        "desired_status": _string(
            row["desired_status"], "reconciliation_pod_desired_status"
        ),
        "runtime_status": _string(
            row["runtime_status"], "reconciliation_pod_runtime_status"
        ),
        "gpu_count": count,
    }
    if not isinstance(row["secure_cloud"], bool):
        raise CandidateControllerError("reconciliation_pod_secure_cloud_invalid")
    result["secure_cloud"] = row["secure_cloud"]
    nullable_keys = ("gpu_id", "gpu_memory_gb", "data_center_id", "cuda_version")
    if count == 0:
        if any(row[key] is not None for key in nullable_keys):
            raise CandidateControllerError("zero_gpu_pod_hardware_invalid")
        result.update({key: None for key in nullable_keys})
        return result
    result.update(
        {
            "gpu_id": _string(row["gpu_id"], "reconciliation_pod_gpu_id"),
            "gpu_memory_gb": _integer(
                row["gpu_memory_gb"], "reconciliation_pod_gpu_memory_gb"
            ),
            "data_center_id": _string(
                row["data_center_id"], "reconciliation_pod_data_center_id"
            ),
            "cuda_version": _string(
                row["cuda_version"], "reconciliation_pod_cuda_version"
            ),
        }
    )
    return result


def _is_running(pod: Mapping[str, Any]) -> bool:
    return pod["desired_status"] == "RUNNING" or pod["runtime_status"] == "running"


def ensure_at_most_one_running_gpu_pod(
    task_pods: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = [_normalize_reconciliation_pod(value) for value in task_pods]
    if sum(1 for row in rows if row["gpu_count"] > 0 and _is_running(row)) > 1:
        raise CandidateControllerError("multiple_running_gpu_pods")
    return rows


def reconcile_create_timeout(
    *,
    expected_name: str,
    attempted_candidate: Mapping[str, Any],
    task_pods: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Reconcile an ambiguous create by exact task name before any retry."""

    name = _string(expected_name, "expected_pod_name")
    candidate = normalize_candidate(attempted_candidate)
    rows = ensure_at_most_one_running_gpu_pod(task_pods)
    matches = [row for row in rows if row["name"] == name]
    if len(matches) > 1:
        raise CandidateControllerError("duplicate_create_name_matches")
    if not matches:
        if any(row["gpu_count"] > 0 and _is_running(row) for row in rows):
            return {"action": "fail", "reason": "another_gpu_pod_running"}
        return {"action": "retry_create", "reason": "create_name_absent"}
    pod = matches[0]
    if pod["gpu_count"] == 0:
        return {
            "action": "delete_invalid_then_retry",
            "reason": "zero_gpu_pod",
            "pod_id": pod["id"],
        }
    matches_candidate = (
        pod["gpu_id"] == candidate["gpu_id"]
        and pod["gpu_count"] == candidate["gpu_count"]
        and pod["gpu_memory_gb"] == candidate["gpu_memory_gb"]
        and pod["secure_cloud"] == candidate["secure_cloud"]
        and pod["data_center_id"] in candidate["allowed_data_center_ids"]
        and pod["cuda_version"] in candidate["allowed_cuda_versions"]
    )
    if not matches_candidate:
        return {
            "action": "delete_invalid_then_retry",
            "reason": "candidate_identity_mismatch",
            "pod_id": pod["id"],
        }
    return {
        "action": "adopt_existing",
        "reason": "exact_name_match",
        "pod_id": pod["id"],
    }
