"""Small capacity preflight for atomic task-owned checkpoint publication."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from .contract import FullModelTrainingError

CAPACITY_PREFLIGHT_SCHEMA = "rondo-publication-critic-plan087-capacity-preflight-v1"
PROVIDER_GB_BYTES = 1_000_000_000


def assess_checkpoint_capacity(value: Any) -> dict[str, Any]:
    base_fields = {
        "schema",
        "captured_at",
        "volume_id",
        "current_size_gb",
        "capacity_bytes",
        "available_bytes",
        "checkpoint_estimate_bytes",
        "atomic_staging_copies",
        "reserve_bytes",
        "maximum_size_gb",
    }
    derived_fields = {
        "used_bytes",
        "checkpoint_closure_bytes",
        "required_bytes",
        "required_size_gb",
        "additional_size_gb",
        "recommended_size_gb",
        "checkpoint_write_ready",
        "extension_within_authorization",
    }
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("plan087_capacity_preflight_invalid")
    fields = set(value)
    if fields != base_fields and fields != base_fields | derived_fields:
        raise FullModelTrainingError("plan087_capacity_preflight_invalid")
    integers = {}
    for key in (
        "current_size_gb",
        "capacity_bytes",
        "available_bytes",
        "checkpoint_estimate_bytes",
        "atomic_staging_copies",
        "reserve_bytes",
        "maximum_size_gb",
    ):
        item = value.get(key)
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise FullModelTrainingError("plan087_capacity_preflight_invalid")
        integers[key] = item
    if (
        value.get("schema") != CAPACITY_PREFLIGHT_SCHEMA
        or not isinstance(value.get("captured_at"), str)
        or not value["captured_at"].strip()
        or not isinstance(value.get("volume_id"), str)
        or not value["volume_id"].strip()
        or not 0 < integers["current_size_gb"] <= 60
        or integers["capacity_bytes"] <= 0
        or integers["capacity_bytes"]
        > integers["current_size_gb"] * PROVIDER_GB_BYTES
        or integers["available_bytes"] > integers["capacity_bytes"]
        or integers["checkpoint_estimate_bytes"] <= 0
        or not 1 <= integers["atomic_staging_copies"] <= 2
        or integers["maximum_size_gb"] != 60
    ):
        raise FullModelTrainingError("plan087_capacity_preflight_invalid")
    used_bytes = integers["capacity_bytes"] - integers["available_bytes"]
    checkpoint_closure_bytes = (
        integers["checkpoint_estimate_bytes"]
        * integers["atomic_staging_copies"]
        + integers["reserve_bytes"]
    )
    required_bytes = used_bytes + checkpoint_closure_bytes
    required_size_gb = max(1, math.ceil(required_bytes / PROVIDER_GB_BYTES))
    recommended_size_gb = max(integers["current_size_gb"], required_size_gb)
    result = {
        **json.loads(json.dumps({key: value[key] for key in base_fields})),
        "used_bytes": used_bytes,
        "checkpoint_closure_bytes": checkpoint_closure_bytes,
        "required_bytes": required_bytes,
        "required_size_gb": required_size_gb,
        "additional_size_gb": max(0, required_size_gb - integers["current_size_gb"]),
        "recommended_size_gb": recommended_size_gb,
        "checkpoint_write_ready": checkpoint_closure_bytes
        <= integers["available_bytes"],
        "extension_within_authorization": recommended_size_gb <= 60,
    }
    if fields == base_fields | derived_fields and any(
        value[key] != result[key] for key in derived_fields
    ):
        raise FullModelTrainingError("plan087_capacity_preflight_derived_invalid")
    return result


__all__ = [
    "CAPACITY_PREFLIGHT_SCHEMA",
    "PROVIDER_GB_BYTES",
    "assess_checkpoint_capacity",
]
