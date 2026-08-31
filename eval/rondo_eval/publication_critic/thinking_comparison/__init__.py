"""Plan 101 thinking-switch × output-expression comparison eval."""

from .archive import ComparisonArchive
from .freeze import build_freeze, freeze_sha256, validate_freeze
from .metrics import unit_metrics, wilson_interval
from .runner import recompute_commissioning, recompute_formal, run_batch

__all__ = [
    "ComparisonArchive",
    "build_freeze",
    "freeze_sha256",
    "recompute_commissioning",
    "recompute_formal",
    "run_batch",
    "unit_metrics",
    "validate_freeze",
    "wilson_interval",
]
