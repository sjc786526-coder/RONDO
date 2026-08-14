"""Offline symmetry preflight: compare two captured requests, touch no network.

The transport this entry point installs raises on any ``open`` attempt, so the
check is structurally incapable of reaching a provider.  Feed it the request
bodies captured from a stub-driven run of each side; a non-zero exit and a
bounded reason code mean the pair is not comparable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import Side
from .fair_comparison import (
    FairComparisonError,
    NoUpstreamTransport,
    SymmetryPreflight,
)


_MAX_REQUEST_BYTES = 8 * 1024 * 1024


def _load_request(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise FairComparisonError(f"request file is unavailable: {path.name}")
    raw = path.read_bytes()
    if not raw or len(raw) > _MAX_REQUEST_BYTES:
        raise FairComparisonError(f"request file is out of bounds: {path.name}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise FairComparisonError(f"request file is not an object: {path.name}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rondo-eval-preflight",
        description="Compare the task-independent partitions of two requests.",
    )
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--role", default="main", choices=("main", "guardian"))
    parser.add_argument("--rondo-request", required=True, type=Path)
    parser.add_argument("--codex-request", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    preflight = SymmetryPreflight(allow_upstream=False)
    try:
        for side, path in (
            (Side.RONDO, args.rondo_request),
            (Side.CODEX, args.codex_request),
        ):
            preflight.register(
                task_id=args.task_id,
                role=args.role,
                side=side,
                request=_load_request(path),
            )
    except FairComparisonError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reasons": list(exc.reasons) or ["task_independent_contract_drift"],
                },
                sort_keys=True,
            )
        )
        return 3
    except (OSError, ValueError):
        print(json.dumps({"status": "blocked", "reasons": ["request_unreadable"]}))
        return 2
    print(
        json.dumps(
            {
                "status": "symmetric",
                "upstream_transport": type(NoUpstreamTransport()).__name__,
                **preflight.provenance(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
