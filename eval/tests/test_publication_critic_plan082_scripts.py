from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "training/publication-critic-plan082"
BOOTSTRAP = SCRIPT_ROOT / "runpod-bootstrap.sh"
LAUNCHER = SCRIPT_ROOT / "runpod-launch.sh"
WORKER = SCRIPT_ROOT / "runpod-worker.sh"


class Plan082ScriptTests(unittest.TestCase):
    def test_shell_entries_parse_and_require_bounded_arguments(self) -> None:
        for script in (BOOTSTRAP, LAUNCHER, WORKER):
            subprocess.run(["bash", "-n", str(script)], check=True, timeout=10)
        self.assertEqual(
            subprocess.run(["bash", str(WORKER)], check=False, timeout=10).returncode,
            2,
        )
        self.assertEqual(
            subprocess.run(
                ["bash", str(LAUNCHER)],
                check=False,
                timeout=10,
                env={
                    **os.environ,
                    "RONDO_PLAN082_TASK_ROOT": "/workspace/fixture",
                    "RONDO_PLAN082_SOURCE_ROOT": "/workspace/fixture/source",
                    "RONDO_PLAN082_LAUNCH_NAME": "fixture",
                    "RONDO_PLAN082_MAX_SECONDS": "60",
                },
            ).returncode,
            2,
        )

    def test_worker_publishes_success_and_failure_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            success = root / "success.json"
            completed = subprocess.run(
                ["bash", str(WORKER), str(success), "bash", "-c", "exit 0"],
                check=False,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0)
            self.assertEqual(json.loads(success.read_text()), {"status": "completed"})
            self.assertEqual(success.stat().st_mode & 0o777, 0o600)

            failure = root / "failure.json"
            failed = subprocess.run(
                ["bash", str(WORKER), str(failure), "bash", "-c", "exit 7"],
                check=False,
                timeout=10,
            )
            self.assertEqual(failed.returncode, 7)
            self.assertEqual(
                json.loads(failure.read_text()),
                {"status": "failed", "exit_code": 7},
            )


if __name__ == "__main__":
    unittest.main()
