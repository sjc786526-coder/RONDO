from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.config import RepoPaths  # noqa: E402
from rondo_eval.terminal_bench import tasksets  # noqa: E402


class TerminalBenchTasksetTests(unittest.TestCase):
    def test_frozen_partitions_are_complete_disjoint_and_stable(self) -> None:
        frozen = tasksets.load_frozen_tasksets(RepoPaths.discover(Path.cwd()))

        self.assertEqual(
            (len(frozen.canary), len(frozen.validation), len(frozen.holdout)),
            (10, 61, 18),
        )
        self.assertEqual(len(frozen.all_ids), 89)
        self.assertEqual(len(set(frozen.all_ids)), 89)
        self.assertEqual(
            frozen.taskset_sha256,
            "07aa634495ba612667817a68be7f58ad435f1c6e9ada31453d832bfae929ca27",
        )

    def test_holdout_is_recomputed_from_ids_without_task_content(self) -> None:
        frozen = tasksets.load_frozen_tasksets(RepoPaths.discover(Path.cwd()))
        ranked = sorted(
            frozen.all_ids,
            key=lambda task_id: (
                hashlib.sha256(task_id.encode("utf-8")).hexdigest(),
                task_id,
            ),
        )

        self.assertEqual(frozen.holdout, tuple(sorted(ranked[:18])))

    def test_partition_tampering_is_rejected(self) -> None:
        live = tasksets.load_frozen_tasksets(RepoPaths.discover(Path.cwd()))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            taskset_root = root / "eval/tasksets"
            taskset_root.mkdir(parents=True)
            (taskset_root / "canary.txt").write_text(
                "\n".join(live.canary[:-1]) + "\n", encoding="utf-8"
            )
            (taskset_root / "validation.txt").write_text(
                "\n".join(live.validation) + "\n", encoding="utf-8"
            )
            (taskset_root / "holdout.txt").write_text(
                "\n".join(live.holdout) + "\n", encoding="utf-8"
            )
            paths = RepoPaths(root, root)
            with mock.patch.object(
                tasksets, "_git_output", side_effect=(tasksets.TERMINAL_BENCH_COMMIT, "")
            ), mock.patch.object(
                tasksets, "_load_dataset_ids", return_value=live.all_ids
            ):
                with self.assertRaisesRegex(tasksets.TasksetError, "counts"):
                    tasksets.load_frozen_tasksets(paths)


if __name__ == "__main__":
    unittest.main()
