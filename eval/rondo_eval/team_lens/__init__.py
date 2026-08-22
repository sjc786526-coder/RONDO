"""Body-free reduction and offline reporting for native rollout traces."""

from .model import TeamViewError, dump_team_view, load_team_view, validate_team_view
from .reducer import (
    BundleError,
    BundleReduction,
    NativeBundleReader,
    reduce_bundle,
    reduce_bundle_with_root_session,
    write_team_view,
)
from .report import render_report, write_report

__all__ = [
    "BundleError",
    "BundleReduction",
    "NativeBundleReader",
    "TeamViewError",
    "dump_team_view",
    "load_team_view",
    "reduce_bundle",
    "reduce_bundle_with_root_session",
    "render_report",
    "validate_team_view",
    "write_report",
    "write_team_view",
]
