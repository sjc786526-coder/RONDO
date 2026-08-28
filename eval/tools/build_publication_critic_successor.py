#!/usr/bin/env python3
"""Validate Plan 098 modules/reviews or run the transactional formal freeze."""

import argparse
import json
from pathlib import Path
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.successor_build import (  # noqa: E402
    finalize_successor_release,
    load_build_contracts,
    validate_module_file,
    validate_review_file,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    module_parser = subparsers.add_parser("validate-module")
    module_parser.add_argument("source", type=Path)
    review_parser = subparsers.add_parser("validate-review")
    review_parser.add_argument("source", type=Path)
    review_parser.add_argument("review", type=Path)
    finalize_parser = subparsers.add_parser("finalize")
    finalize_parser.add_argument("--workspace", type=Path, required=True)
    finalize_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contracts = load_build_contracts(REPO_ROOT)
    if args.command == "validate-module":
        module = validate_module_file(
            args.source,
            contracts=contracts,
            repo_root=REPO_ROOT,
        )
        print(
            json.dumps(
                {
                    "module_id": module.module_id,
                    "source_sha256": module.source_sha256,
                    "groups": len(module.group_splits),
                    "candidates": len(module.candidates),
                    "pairs": len(module.pairs),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "validate-review":
        module = validate_module_file(
            args.source,
            contracts=contracts,
            repo_root=REPO_ROOT,
        )
        review = validate_review_file(
            args.review,
            module,
            contracts=contracts,
            repo_root=REPO_ROOT,
        )
        print(json.dumps({"module_id": module.module_id, "verdict": review["verdict"]}))
        return 0
    coverage = finalize_successor_release(
        args.workspace,
        args.output,
        repo_root=REPO_ROOT,
    )
    print(json.dumps(coverage, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
