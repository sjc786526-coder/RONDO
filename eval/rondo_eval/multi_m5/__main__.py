"""CLI: run the no-API Multi team_publish loopback drill."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..config import RepoPaths
from .loopback import LoopbackError, run_frozen_multi_team_publish_loopback
from .load import M5ContractError


def main(argv: list[str] | None = None) -> int:
    del argv
    try:
        paths = RepoPaths.discover(Path.cwd())
        result = run_frozen_multi_team_publish_loopback(common_root=paths.common_root)
    except (LoopbackError, M5ContractError) as exc:
        print(f"rondo-multi-m5: {exc}", file=sys.stderr)
        return 78
    print(json.dumps(result["record"], sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
