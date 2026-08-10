"""Minimal process-external metrics required by the inherited B3 contract."""

from __future__ import annotations

import math
import resource
import sys
import time
from dataclasses import dataclass
from typing import Callable


class RunMetricsError(ValueError):
    """Raised when an external runner metric is missing or inconsistent."""


@dataclass(frozen=True)
class ExternalRunMetrics:
    wall_seconds: float
    cpu_user_seconds: float
    cpu_system_seconds: float
    peak_rss_bytes: int
    exit_code: int

    def validate(self) -> None:
        if (
            isinstance(self.wall_seconds, bool)
            or not isinstance(self.wall_seconds, (int, float))
            or not math.isfinite(self.wall_seconds)
            or self.wall_seconds < 0
        ):
            raise RunMetricsError("runner wall time is invalid")
        if (
            isinstance(self.cpu_user_seconds, bool)
            or not isinstance(self.cpu_user_seconds, (int, float))
            or not math.isfinite(self.cpu_user_seconds)
            or self.cpu_user_seconds < 0
        ):
            raise RunMetricsError("runner user CPU time is invalid")
        if (
            isinstance(self.cpu_system_seconds, bool)
            or not isinstance(self.cpu_system_seconds, (int, float))
            or not math.isfinite(self.cpu_system_seconds)
            or self.cpu_system_seconds < 0
        ):
            raise RunMetricsError("runner system CPU time is invalid")
        if (
            isinstance(self.peak_rss_bytes, bool)
            or not isinstance(self.peak_rss_bytes, int)
            or self.peak_rss_bytes <= 0
        ):
            raise RunMetricsError("runner peak RSS is invalid")
        if (
            isinstance(self.exit_code, bool)
            or not isinstance(self.exit_code, int)
            or not 0 <= self.exit_code <= 255
        ):
            raise RunMetricsError("runner exit code is invalid")

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "wall_seconds": round(float(self.wall_seconds), 6),
            "cpu_user_seconds": round(float(self.cpu_user_seconds), 6),
            "cpu_system_seconds": round(float(self.cpu_system_seconds), 6),
            "peak_rss_bytes": self.peak_rss_bytes,
            "exit_code": self.exit_code,
        }


class RunnerMetricsTimer:
    """Measure one fresh runner process plus all children spawned by that run.

    The production CLI executes exactly one run, so Linux ``ru_maxrss`` is a
    per-invocation process-tree peak rather than a cumulative multi-run value.
    """

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        getrusage: Callable[[int], resource.struct_rusage] = resource.getrusage,
    ) -> None:
        self._monotonic = monotonic
        self._getrusage = getrusage
        self._started_at = monotonic()
        self._self_start = getrusage(resource.RUSAGE_SELF)
        self._children_start = getrusage(resource.RUSAGE_CHILDREN)

    def snapshot(self, *, exit_code: int) -> ExternalRunMetrics:
        self_end = self._getrusage(resource.RUSAGE_SELF)
        children_end = self._getrusage(resource.RUSAGE_CHILDREN)
        user_start = float(self._self_start.ru_utime) + float(self._children_start.ru_utime)
        user_end = float(self_end.ru_utime) + float(children_end.ru_utime)
        system_start = float(self._self_start.ru_stime) + float(
            self._children_start.ru_stime
        )
        system_end = float(self_end.ru_stime) + float(children_end.ru_stime)
        peak_units = max(self_end.ru_maxrss, children_end.ru_maxrss)
        # Linux and the supported WSL2 environment report KiB; macOS reports bytes.
        peak_rss_bytes = int(peak_units if sys.platform == "darwin" else peak_units * 1024)
        metrics = ExternalRunMetrics(
            wall_seconds=max(0.0, self._monotonic() - self._started_at),
            cpu_user_seconds=max(0.0, user_end - user_start),
            cpu_system_seconds=max(0.0, system_end - system_start),
            peak_rss_bytes=peak_rss_bytes,
            exit_code=exit_code,
        )
        metrics.validate()
        return metrics


def metrics_from_dict(value: object) -> ExternalRunMetrics:
    if not isinstance(value, dict) or set(value) != {
        "wall_seconds",
        "cpu_user_seconds",
        "cpu_system_seconds",
        "peak_rss_bytes",
        "exit_code",
    }:
        raise RunMetricsError("runner metrics differ from schema v1")
    metrics = ExternalRunMetrics(
        wall_seconds=value["wall_seconds"],
        cpu_user_seconds=value["cpu_user_seconds"],
        cpu_system_seconds=value["cpu_system_seconds"],
        peak_rss_bytes=value["peak_rss_bytes"],
        exit_code=value["exit_code"],
    )
    metrics.validate()
    return metrics
