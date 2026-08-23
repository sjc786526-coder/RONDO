"""Compact, body-free projections of Plan 054 watchdog evidence."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .identity import sha256_file


_ENV_KEY = re.compile(r"[A-Z_a-z][A-Z_a-z0-9]*\Z")
_UNIT = re.compile(r"rondo-build-[0-9]+-[0-9]+-[0-9]+[.]scope\Z")
_MAX_SUMMARY_BYTES = 16 * 1024
_NUMERIC_FIELDS = (
    "project_before_bytes",
    "project_after_bytes",
    "project_peak_sampled_bytes",
    "target_after_bytes",
    "target_peak_sampled_bytes",
    "windows_c_used_before_bytes",
    "windows_c_used_after_bytes",
    "windows_c_available_before_bytes",
    "windows_c_available_after_bytes",
    "memory_peak_sampled_bytes",
    "memory_nonreclaimable_peak_sampled_bytes",
    "swap_peak_sampled_bytes",
    "cgroup_psi_full_avg10_peak_bp",
    "host_psi_full_avg10_peak_bp",
    "project_stop_bytes",
    "project_max_bytes",
)


class EvidenceError(ValueError):
    """A watchdog summary cannot support a successful formal result."""


def load_watchdog_summary(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("watchdog summary is missing or unsafe")
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise EvidenceError("watchdog summary cannot be read") from exc
    if not body or len(body) > _MAX_SUMMARY_BYTES or not body.isascii():
        raise EvidenceError("watchdog summary encoding is invalid")

    values: dict[str, str] = {}
    for line in body.decode("ascii").splitlines():
        if "=" not in line:
            raise EvidenceError("watchdog summary line is invalid")
        key, value = line.split("=", 1)
        if not _ENV_KEY.fullmatch(key) or key in values:
            raise EvidenceError("watchdog summary key is invalid")
        values[key] = value

    fixed = {
        "command_name": "python",
        "wrapper_status": "complete",
        "run_rc": "0",
        "final_rc": "0",
        "stop_reason": "none",
        "cleanup_reason": "none",
        "memory_high": "19G",
        "memory_max": "21G",
        "swap_max": "5G",
    }
    if any(values.get(key) != expected for key, expected in fixed.items()):
        raise EvidenceError("watchdog summary does not describe a successful bounded run")
    unit = values.get("unit", "")
    if not _UNIT.fullmatch(unit):
        raise EvidenceError("watchdog summary unit is invalid")

    numeric: dict[str, int] = {}
    for key in _NUMERIC_FIELDS:
        raw = values.get(key, "")
        if not raw.isascii() or not raw.isdigit():
            raise EvidenceError("watchdog summary counter is invalid")
        numeric[key] = int(raw)

    return {
        "schema": "rondo-watchdog-summary-projection-v1",
        "summary_sha256": sha256_file(path),
        "unit": unit,
        "wrapper_status": "complete",
        "run_rc": 0,
        "final_rc": 0,
        "stop_reason": "none",
        "cleanup_reason": "none",
        "project": {
            key: numeric[key]
            for key in (
                "project_before_bytes",
                "project_after_bytes",
                "project_peak_sampled_bytes",
                "target_after_bytes",
                "target_peak_sampled_bytes",
            )
        },
        "windows_c": {
            key: numeric[key]
            for key in (
                "windows_c_used_before_bytes",
                "windows_c_used_after_bytes",
                "windows_c_available_before_bytes",
                "windows_c_available_after_bytes",
            )
        },
        "watchdog_samples": {
            key: numeric[key]
            for key in (
                "memory_peak_sampled_bytes",
                "memory_nonreclaimable_peak_sampled_bytes",
                "swap_peak_sampled_bytes",
                "cgroup_psi_full_avg10_peak_bp",
                "host_psi_full_avg10_peak_bp",
            )
        },
        "limits": {
            "memory_high": "19G",
            "memory_max": "21G",
            "swap_max": "5G",
            "project_stop_bytes": numeric["project_stop_bytes"],
            "project_max_bytes": numeric["project_max_bytes"],
        },
    }
