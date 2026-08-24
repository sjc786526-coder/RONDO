#!/usr/bin/env python3
"""Attach explicitly bound Plan 064 reviews to an existing aggregate."""

import argparse
import json
from pathlib import Path
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data.plan064_batch import (  # noqa: E402
    AGGREGATE_REVIEW_BINDINGS_FILE,
    aggregate_plan064_reviews,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Attach strict Plan 064 reviews; the Nth review directory binds to "
            "the Nth compiled batch directory."
        )
    )
    parser.add_argument(
        "--batch-dir",
        action="append",
        type=Path,
        required=True,
        help="Compiled batch directory; repeat in binding order.",
    )
    parser.add_argument(
        "--review-dir",
        action="append",
        type=Path,
        required=True,
        help="Review directory for the corresponding --batch-dir occurrence.",
    )
    parser.add_argument("--aggregate-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    candidate_count, pair_count = aggregate_plan064_reviews(
        args.batch_dir,
        args.review_dir,
        args.aggregate_dir,
    )
    print(
        json.dumps(
            {
                "bindings": len(args.batch_dir),
                "candidate_reviews": candidate_count,
                "pair_reviews": pair_count,
                "review_bindings": str(
                    (args.aggregate_dir / AGGREGATE_REVIEW_BINDINGS_FILE).resolve()
                ),
                "aggregate_dir": str(Path(args.aggregate_dir).resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
