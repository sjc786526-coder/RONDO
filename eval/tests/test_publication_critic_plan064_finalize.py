from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


EVAL_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = EVAL_ROOT / "tools"
sys.path.insert(0, str(EVAL_ROOT))
sys.path.insert(0, str(TOOLS_ROOT))

from finalize_publication_critic_plan064 import _verify_clean_head  # noqa: E402
from rondo_eval.publication_critic.training_data.contract import (  # noqa: E402
    TrainingDataError,
)


class Plan064FinalizeCheckpointTests(unittest.TestCase):
    @patch("finalize_publication_critic_plan064.subprocess.run")
    def test_accepts_exact_clean_head(self, run: object) -> None:
        run.side_effect = [  # type: ignore[attr-defined]
            SimpleNamespace(stdout="a" * 40 + "\n"),
            SimpleNamespace(stdout=""),
        ]

        _verify_clean_head(Path("/repo"), "a" * 40)

    @patch("finalize_publication_critic_plan064.subprocess.run")
    def test_rejects_wrong_or_dirty_head(self, run: object) -> None:
        run.side_effect = [  # type: ignore[attr-defined]
            SimpleNamespace(stdout="b" * 40 + "\n"),
            SimpleNamespace(stdout=""),
        ]
        with self.assertRaisesRegex(TrainingDataError, "current worktree HEAD"):
            _verify_clean_head(Path("/repo"), "a" * 40)

        run.side_effect = [  # type: ignore[attr-defined]
            SimpleNamespace(stdout="a" * 40 + "\n"),
            SimpleNamespace(stdout=" M tracked.py\n"),
        ]
        with self.assertRaisesRegex(TrainingDataError, "clean tracked worktree"):
            _verify_clean_head(Path("/repo"), "a" * 40)

    @patch("finalize_publication_critic_plan064.subprocess.run")
    def test_fails_closed_when_git_cannot_be_verified(self, run: object) -> None:
        run.side_effect = subprocess.CalledProcessError(1, ["git"])  # type: ignore[attr-defined]
        with self.assertRaisesRegex(TrainingDataError, "cannot verify"):
            _verify_clean_head(Path("/repo"), "a" * 40)


if __name__ == "__main__":
    unittest.main()
