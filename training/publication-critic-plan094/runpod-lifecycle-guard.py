#!/usr/bin/env python3
"""Wait for one frozen task Pod deadline, then confirm exact deletion."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rondo_eval.publication_critic.full_model_training.contract import (
    FullModelTrainingError,
)
from rondo_eval.publication_critic.full_model_training.plan094_contract import (
    validate_pod_lifecycle_authorization as validate_plan094_lifecycle,
)
from rondo_eval.publication_critic.full_model_training.plan099_contract import (
    validate_pod_lifecycle_authorization as validate_plan099_lifecycle,
)

ARMED_SCHEMA = "rondo-publication-critic-plan094-pod-lifecycle-guard-armed-v1"
RESULT_SCHEMA = "rondo-publication-critic-plan094-pod-lifecycle-guard-result-v1"
PLAN099_ARMED_SCHEMA = "rondo-publication-critic-plan099-pod-lifecycle-guard-armed-v1"
PLAN099_RESULT_SCHEMA = "rondo-publication-critic-plan099-pod-lifecycle-guard-result-v1"
ARM_MAX_DELAY_SECONDS = 60
POLL_SECONDS = 30.0
RETRY_SECONDS = 5.0


class LifecycleGuardError(RuntimeError):
    """Sanitized lifecycle failure."""


Terminator = Callable[[Mapping[str, Any], datetime, float], Mapping[str, Any]]
Validator = Callable[[Any], dict[str, Any]]

PROFILES = {
    "plan094": {
        "validator": validate_plan094_lifecycle,
        "approval_environment": "RONDO_PLAN094_STAGE_B_APPROVED",
        "task_prefix": "rondo-plan094-",
        "started_at_field": "task_started_at",
        "armed_schema": ARMED_SCHEMA,
        "result_schema": RESULT_SCHEMA,
    },
    "plan099": {
        "validator": validate_plan099_lifecycle,
        "approval_environment": "RONDO_PLAN099_STAGE_B_APPROVED",
        "task_prefix": "rondo-plan099-",
        "started_at_field": "pod_started_at",
        "armed_schema": PLAN099_ARMED_SCHEMA,
        "result_schema": PLAN099_RESULT_SCHEMA,
    },
}


def enforce_lifecycle(
    authorization: Any,
    *,
    terminator: Terminator,
    validator: Validator = validate_plan094_lifecycle,
    result_schema: str = RESULT_SCHEMA,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Use the provider-start absolute trigger, including idle launch gaps."""

    receipt = validator(authorization)
    trigger = _utc(receipt["termination_trigger_at"])
    while (remaining := (trigger - _now(now)).total_seconds()) > 0.0:
        sleeper(min(POLL_SECONDS, remaining))

    confirmation_deadline = trigger.timestamp() + float(
        receipt["terminal_confirmation_seconds"]
    )
    last_failure = "terminal_not_attempted"
    while True:
        observed = _now(now)
        remaining = confirmation_deadline - observed.timestamp()
        if remaining <= 0.0:
            raise LifecycleGuardError(
                f"terminal_confirmation_deadline_exceeded:{last_failure}"
            )
        try:
            terminal = terminator(
                receipt,
                observed,
                min(
                    float(
                        receipt.get(
                            "terminal_helper_timeout_seconds",
                            receipt["terminal_confirmation_seconds"],
                        )
                    ),
                    remaining,
                ),
            )
            _require_zero_pod(terminal, receipt)
        except LifecycleGuardError as exc:
            last_failure = str(exc)
            sleeper(min(RETRY_SECONDS, remaining))
            continue
        confirmed = _now(now)
        if confirmed < observed:
            raise LifecycleGuardError("guard_clock_moved_backwards")
        if confirmed.timestamp() > confirmation_deadline:
            raise LifecycleGuardError(
                "terminal_confirmation_deadline_exceeded:terminal_succeeded_late"
            )
        return {
            "schema": result_schema,
            "status": "pod_absent_confirmed",
            "termination_trigger_at": receipt["termination_trigger_at"],
            "confirmed_at": confirmed.isoformat().replace("+00:00", "Z"),
            "pod_id": receipt["pod_id"],
            "pod_name": receipt["pod_name"],
            "authorization_content_sha256": receipt["content_sha256"],
            "terminal_receipt": dict(terminal),
        }


def _run_terminal(
    helper: Path,
    runpodctl: str,
    receipt: Mapping[str, Any],
    captured_at: datetime,
    timeout_seconds: float,
    *,
    task_prefix: str = "rondo-plan094-",
    started_at_field: str = "task_started_at",
) -> Mapping[str, Any]:
    helper_timeout = max(timeout_seconds - 5.0, 1.0)
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-B",
                "-P",
                str(helper),
                "--runpodctl",
                runpodctl,
                "--pod-id",
                receipt["pod_id"],
                "--pod-name",
                receipt["pod_name"],
                "--task-pod-name-prefix",
                task_prefix,
                "--captured-at",
                captured_at.isoformat().replace("+00:00", "Z"),
                "--task-started-at",
                receipt[started_at_field],
                "--timeout-seconds",
                str(helper_timeout),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LifecycleGuardError("terminal_helper_execution_failed") from exc
    if completed.returncode != 0:
        raise LifecycleGuardError(f"terminal_helper_failed_{completed.returncode}")
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LifecycleGuardError("terminal_helper_result_invalid") from exc
    if not isinstance(value, Mapping):
        raise LifecycleGuardError("terminal_helper_result_invalid")
    return value


def _require_zero_pod(value: Any, receipt: Mapping[str, Any]) -> None:
    try:
        deleted = value["deleted_pod"]
        valid = (
            isinstance(value, Mapping)
            and value["pod_count"] == 0
            and float(value["compute_rate_usd_per_hour"]) == 0.0
            and deleted["id"] == receipt["pod_id"]
            and deleted["name"] == receipt["pod_name"]
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise LifecycleGuardError("terminal_helper_did_not_confirm_zero_pod")


def _task_path(path: Path, root: Path, *, must_exist: bool) -> Path:
    candidate = path.resolve(strict=must_exist)
    if candidate == root or not candidate.is_relative_to(root) or path.is_symlink():
        raise LifecycleGuardError("task_owned_path_required")
    return candidate


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise LifecycleGuardError("guard_output_exists")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def _now(source: Callable[[], datetime]) -> datetime:
    value = source()
    if value.tzinfo is None:
        raise LifecycleGuardError("guard_clock_invalid")
    return value.astimezone(timezone.utc)


def _utc(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise LifecycleGuardError("lifecycle_timestamp_invalid") from exc
    if result.tzinfo is None:
        raise LifecycleGuardError("lifecycle_timestamp_invalid")
    return result.astimezone(timezone.utc)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=tuple(PROFILES), default="plan094")
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--terminal-helper", type=Path, required=True)
    parser.add_argument("--runpodctl", default="runpodctl")
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--armed-output", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    os.umask(0o077)
    args = _parser().parse_args(argv)
    try:
        profile = PROFILES[args.profile]
        if os.getenv(str(profile["approval_environment"])) != "1":
            raise LifecycleGuardError("stage_b_approval_required")
        root = args.task_root.resolve(strict=True)
        if not root.is_dir() or not root.name.startswith(str(profile["task_prefix"])):
            raise LifecycleGuardError("task_root_invalid")
        authorization_path = _task_path(args.authorization, root, must_exist=True)
        armed_path = _task_path(args.armed_output, root, must_exist=False)
        result_path = _task_path(args.result, root, must_exist=False)
        if armed_path == result_path:
            raise LifecycleGuardError("guard_output_paths_must_differ")
        helper = args.terminal_helper.resolve(strict=True)
        if not helper.is_file() or args.terminal_helper.is_symlink():
            raise LifecycleGuardError("terminal_helper_invalid")
        validator = profile["validator"]
        assert callable(validator)
        authorization = validator(
            json.loads(authorization_path.read_text(encoding="utf-8"))
        )
        observed = _now(lambda: datetime.now(timezone.utc))
        age = (observed - _utc(authorization["authorized_at"])).total_seconds()
        if (
            age < -30.0
            or age > ARM_MAX_DELAY_SECONDS
            or observed >= _utc(authorization["termination_trigger_at"])
        ):
            raise LifecycleGuardError("lifecycle_guard_not_armed_immediately")
        _write_exclusive(
            armed_path,
            {
                "schema": profile["armed_schema"],
                "status": "armed",
                "pid": os.getpid(),
                "pod_id": authorization["pod_id"],
                "pod_name": authorization["pod_name"],
                "termination_trigger_at": authorization["termination_trigger_at"],
                "authorization_content_sha256": authorization["content_sha256"],
            },
        )
        result = enforce_lifecycle(
            authorization,
            terminator=lambda receipt, captured, timeout: _run_terminal(
                helper,
                args.runpodctl,
                receipt,
                captured,
                timeout,
                task_prefix=str(profile["task_prefix"]),
                started_at_field=str(profile["started_at_field"]),
            ),
            validator=validator,
            result_schema=str(profile["result_schema"]),
        )
        _write_exclusive(result_path, result)
    except (
        FullModelTrainingError,
        LifecycleGuardError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "failed", "code": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
