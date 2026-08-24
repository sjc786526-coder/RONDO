#!/usr/bin/env python3
"""Aggregate explicit compiled Plan 064 batches without external calls."""

import argparse
import json
from pathlib import Path
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data.plan064_batch import (  # noqa: E402
    aggregate_compiled_plan064_batches,
    write_compiled_plan064_batch,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate explicit compiled Plan 064 batch directories."
    )
    parser.add_argument(
        "--batch-dir",
        action="append",
        type=Path,
        required=True,
        help="Compiled batch directory; repeat for every input batch.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    compiled = aggregate_compiled_plan064_batches(args.batch_dir)
    write_compiled_plan064_batch(args.output_dir, compiled)
    summary = {
        "batch_directories": len(args.batch_dir),
        "scenarios": len(compiled.scenarios),
        "candidates": len(compiled.packets),
        "pairs": len(compiled.pairs),
        "output_dir": str(Path(args.output_dir).resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
