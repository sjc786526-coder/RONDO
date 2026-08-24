#!/usr/bin/env python3
"""Compile one structured Plan 064 authoring batch without external calls."""

from pathlib import Path
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data.plan064_batch import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
