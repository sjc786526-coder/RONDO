"""Plan 049 selection of the product Root from a multi-bundle trace root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..team_lens.reducer import BundleError, reduce_bundle_with_root_session


class ProactiveTraceError(ValueError):
    """The run's Root/Guardian trace identity cannot be determined safely."""


@dataclass(frozen=True)
class ProactiveTraceSelection:
    root_bundle: Path
    root_view: dict[str, Any]
    guardian_bundle_count: int


def select_proactive_root_bundle(
    trace_root: Path, *, product: str
) -> ProactiveTraceSelection:
    """Require one Exec Root and allow only validated Guardian side bundles."""

    root = Path(trace_root)
    if root.is_symlink() or not root.is_dir():
        raise ProactiveTraceError("Plan 049 trace root is not a regular directory")
    try:
        entries = sorted(root.iterdir())
    except OSError as exc:
        raise ProactiveTraceError("Plan 049 trace root is unreadable") from exc
    if not entries:
        raise ProactiveTraceError("Plan 049 trace root contains no bundles")

    exec_bundles: list[tuple[Path, dict[str, Any]]] = []
    guardian_count = 0
    for entry in entries:
        manifest = entry / "manifest.json"
        if (
            entry.is_symlink()
            or not entry.is_dir()
            or manifest.is_symlink()
            or not manifest.is_file()
        ):
            raise ProactiveTraceError(
                "Plan 049 trace root contains an incomplete or unknown entry"
            )
        try:
            reduction = reduce_bundle_with_root_session(entry, product)
        except BundleError as exc:
            raise ProactiveTraceError("Plan 049 trace bundle is malformed") from exc
        if reduction.root_session_kind == "exec":
            exec_bundles.append((entry, reduction.view))
        elif reduction.root_session_kind == "guardian":
            guardian_count += 1
        else:
            raise ProactiveTraceError(
                "Plan 049 trace root contains an unknown session source"
            )

    if len(exec_bundles) != 1:
        raise ProactiveTraceError(
            "Plan 049 trace root must contain exactly one Exec Root bundle"
        )
    bundle, view = exec_bundles[0]
    return ProactiveTraceSelection(
        root_bundle=bundle,
        root_view=view,
        guardian_bundle_count=guardian_count,
    )
