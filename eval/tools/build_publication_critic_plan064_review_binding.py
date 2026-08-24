#!/usr/bin/env python3
"""Bind one Plan 064 review directory to the exact compiled rows it reviewed."""

import argparse
import json
from pathlib import Path
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data.plan064_batch import (  # noqa: E402
    REVIEW_BINDING_FILE,
    create_plan064_review_binding,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bind current Plan 064 batch and review rows without overwriting."
    )
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--review-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    binding = create_plan064_review_binding(args.batch_dir, args.review_dir)
    print(
        json.dumps(
            {
                "binding": str((args.review_dir / REVIEW_BINDING_FILE).resolve()),
                "counts": binding["counts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
