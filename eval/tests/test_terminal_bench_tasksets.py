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
            "2a9f9e3400f38606bacd71a220d8abb595a108ef3622556e8684dadbeb03a61b",
        )
        self.assertIn("terminal-bench/openssl-selfsigned-cert", frozen.canary)
        self.assertIn("terminal-bench/build-cython-ext", frozen.validation)
        self.assertNotIn("terminal-bench/build-cython-ext", frozen.canary)

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

    def test_canary_execution_catalog_is_bound_to_the_id_partition(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        task_ids = tasksets.load_frozen_tasksets(paths).canary
        catalog = tasksets.load_frozen_canary_catalog(paths)

        self.assertEqual(tuple(item.task_id for item in catalog.tasks), task_ids)
        self.assertEqual(len(catalog.catalog_sha256), 64)
        self.assertEqual(catalog.task("terminal-bench/fix-git").workdir, "/app/personal-site")
        openssl = catalog.task("terminal-bench/openssl-selfsigned-cert")
        self.assertEqual(openssl.workdir, "/app")
        self.assertEqual(
            openssl.image_digest,
            "sha256:4c948a4e630af2435ae0a19108fc0814a946ac2fa29a512469e0fc77b38c8c12",
        )
        self.assertTrue(
            all(item.image_ref.endswith(item.image_digest) for item in catalog.tasks)
        )

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
