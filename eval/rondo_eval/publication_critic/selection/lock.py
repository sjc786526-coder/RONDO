"""The Plan 073 selection lock: the one artifact that opens unseen-test.

The lock is intentionally a single small document.  It names an indivisible
``model + threshold + runtime configuration`` combination, binds it to the
formal validation evidence that produced it, and is the only thing that
authorises an unseen-test release.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from .contract import (
    CANDIDATES,
    RUN_ID,
    SelectionError,
    require_exact_keys,
    require_finite,
    require_object,
    require_sha256,
    validate_runtime,
)


SCHEMA = "rondo-publication-critic-plan073-selection-lock-v1"
TERMINAL = "SELECTED"


def lock_sha256(lock: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(lock)))


def validate_lock(value: Any) -> dict[str, Any]:
    lock = require_object(value, "Plan 073 selection lock")
    require_exact_keys(
        lock,
        {
            "schema",
            "terminal",
            "run_id",
            "selection_freeze_sha256",
            "validation_result_sha256",
            "selected",
            "runner_up",
            "reasons",
            "unseen_release_authorized",
        },
        "Plan 073 selection lock",
    )
    run_match = (
        RUN_ID.fullmatch(lock["run_id"]) if isinstance(lock["run_id"], str) else None
    )
    if (
        lock["schema"] != SCHEMA
        or lock["terminal"] != TERMINAL
        or run_match is None
        or run_match.group(1) != "formal"
        or lock["unseen_release_authorized"] is not True
    ):
        raise SelectionError("Plan 073 selection lock identity is invalid")
    require_sha256(lock["selection_freeze_sha256"], "Plan 073 lock freeze binding")
    require_sha256(lock["validation_result_sha256"], "Plan 073 lock evidence binding")

    selected = require_object(lock["selected"], "Plan 073 locked combination")
    require_exact_keys(
        selected,
        {"candidate", "deployment_artifact_sha256", "threshold", "runtime"},
        "Plan 073 locked combination",
    )
    if selected["candidate"] not in CANDIDATES:
        raise SelectionError("Plan 073 locked candidate is invalid")
    require_sha256(
        selected["deployment_artifact_sha256"], "Plan 073 locked artifact"
    )
    threshold = require_object(selected["threshold"], "Plan 073 locked threshold")
    require_exact_keys(
        threshold, {"projected_score", "method"}, "Plan 073 locked threshold"
    )
    if type(threshold["projected_score"]) is not float:
        raise SelectionError("Plan 073 locked threshold must be an exact float")
    require_finite(
        threshold["projected_score"],
        "Plan 073 locked threshold",
        minimum=0.0,
        maximum=1.0,
    )
    if not isinstance(threshold["method"], str) or not threshold["method"].strip():
        raise SelectionError("Plan 073 locked threshold method is invalid")
    validate_runtime(selected["runtime"], "Plan 073 locked runtime")

    if lock["runner_up"] is not None and lock["runner_up"] not in CANDIDATES:
        raise SelectionError("Plan 073 lock runner-up is invalid")
    reasons = lock["reasons"]
    if (
        not isinstance(reasons, list)
        or not reasons
        or any(not isinstance(item, str) or not item.strip() for item in reasons)
    ):
        raise SelectionError("Plan 073 lock reasons are invalid")
    return dict(lock)
