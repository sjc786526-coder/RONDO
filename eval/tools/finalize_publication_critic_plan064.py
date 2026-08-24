#!/usr/bin/env python3
"""Run the Plan 064 prefreeze or approved freeze mechanical chain."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.identity import sha256_file  # noqa: E402
from rondo_eval.publication_critic.runner import load_exact_tokenizer  # noqa: E402
from rondo_eval.publication_critic.training_data.input_identity import (  # noqa: E402
    verify_plan054_tokenizer_snapshot,
)
from rondo_eval.publication_critic.training_data.contract import (  # noqa: E402
    TrainingDataError,
)
from rondo_eval.publication_critic.training_data.plan064_release import (  # noqa: E402
    materialize_plan064_release,
)


IGNORED_NAMESPACE = Path(
    "/home/sjc/desktop/RONDO/eval-data/publication-critic/plan064"
)
BASE_DIR = REPO_ROOT / "training/publication-critic-v7"
FORMAL_RELEASE_DIR = REPO_ROOT / "training/publication-critic-v8"
DESIGN_LOCK_PATH = (
    REPO_ROOT / "eval/templates/publication-critic/training-data-design-lock-v8.json"
)
REFERENCE_PACKETS_PATH = (
    REPO_ROOT / "eval/fixtures/publication-critic-v1/packets.jsonl"
)


def _contract_hashes() -> dict[str, str]:
    training_data_root = (
        REPO_ROOT / "eval/rondo_eval/publication_critic/training_data"
    )
    paths = [
        DESIGN_LOCK_PATH,
        REPO_ROOT
        / "eval/templates/publication-critic/training-data-release-schema-v2.json",
        REPO_ROOT
        / "eval/templates/publication-critic/training-data-generator-prompt-v8.md",
        REPO_ROOT
        / "eval/templates/publication-critic/training-data-reviewer-prompt-v2.md",
        REPO_ROOT / "eval/templates/publication-critic/input-contract-v2.md",
        REPO_ROOT / "eval/templates/publication-critic/qualification-rubric-v1.md",
        REPO_ROOT / "eval/templates/publication-critic/render-contract-v3.json",
        REPO_ROOT / "eval/templates/publication-critic/product-packet-limits-v1.json",
        Path(__file__),
    ]
    paths.extend(sorted(training_data_root.glob("*.py")))
    return {
        path.relative_to(REPO_ROOT).as_posix(): sha256_file(path)
        for path in sorted(paths)
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("prefreeze", "freeze"), required=True)
    parser.add_argument("--delta-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-snapshot", type=Path, required=True)
    parser.add_argument("--generation-commit", required=True)
    parser.add_argument("--approved-prefreeze-identity")
    return parser


def _verify_clean_head(repo_root: Path, claimed_commit: str) -> None:
    if (
        len(claimed_commit) != 40
        or any(character not in "0123456789abcdef" for character in claimed_commit)
    ):
        raise TrainingDataError(
            "Plan 064 generation commit must be a full lowercase Git SHA"
        )
    try:
        head = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise TrainingDataError(
            "cannot verify the Plan 064 clean Git checkpoint"
        ) from exc
    if head != claimed_commit:
        raise TrainingDataError(
            "Plan 064 generation commit must equal the current worktree HEAD"
        )
    if status:
        raise TrainingDataError(
            "Plan 064 prefreeze/freeze requires a clean tracked worktree"
        )


def main() -> int:
    args = build_parser().parse_args()
    _verify_clean_head(REPO_ROOT, args.generation_commit)
    verify_plan054_tokenizer_snapshot(
        args.tokenizer_snapshot,
        repo_root=REPO_ROOT,
    )
    tokenizer = load_exact_tokenizer(args.tokenizer_snapshot.resolve(strict=True))
    result = materialize_plan064_release(
        phase=args.phase,
        base_dir=BASE_DIR,
        delta_dir=args.delta_dir,
        output_dir=args.output_dir,
        design_lock_path=DESIGN_LOCK_PATH,
        reference_packets_path=REFERENCE_PACKETS_PATH,
        tokenizer=tokenizer,
        generation_commit=args.generation_commit,
        contracts=_contract_hashes(),
        repo_root=REPO_ROOT,
        ignored_namespace=IGNORED_NAMESPACE,
        formal_release_dir=FORMAL_RELEASE_DIR,
        approved_prefreeze_identity=args.approved_prefreeze_identity,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
