#!/usr/bin/env python3
"""Validate or freeze the Plan 098 directional-remediation data."""

import argparse
import json
from pathlib import Path
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.directional_data import (  # noqa: E402
    finalize_directional_releases,
    load_directional_contracts,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-contracts")
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--workspace", type=Path, required=True)
    finalize_parser.add_argument("--development-output", type=Path, required=True)
    finalize_parser.add_argument("--qualification-output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "validate-contracts":
        contracts = load_directional_contracts(REPO_ROOT)
        print(
            json.dumps(
                {
                    "config_sha256": contracts.config_sha256,
                    "design_sha256": contracts.design_sha256,
                },
                sort_keys=True,
            )
        )
        return 0

    summary = finalize_directional_releases(
        ignored_root=args.workspace,
        development_output=args.development_output,
        qualification_output=args.qualification_output,
        repo_root=REPO_ROOT,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
