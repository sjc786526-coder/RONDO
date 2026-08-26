from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "training/publication-critic-plan087"
BOOTSTRAP = SCRIPT_ROOT / "runpod-bootstrap.sh"
LAUNCHER = SCRIPT_ROOT / "runpod-launch.sh"
WORKER = SCRIPT_ROOT / "runpod-worker.sh"
TERMINAL = SCRIPT_ROOT / "runpod-terminal.py"
SPEC = importlib.util.spec_from_file_location("plan087_runpod_terminal", TERMINAL)
assert SPEC is not None and SPEC.loader is not None
terminal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(terminal)


def _terminal_args() -> argparse.Namespace:
    return argparse.Namespace(
        pod_id="pod-087",
        pod_name="rondo-plan087-search-a",
        task_pod_name_prefix="rondo-plan087-",
        captured_at="2026-08-26T13:00:00Z",
        task_started_at="2026-08-26T12:00:00Z",
        stopped_desired_status="EXITED",
        stopped_runtime_status="stopped",
        poll_seconds=0.01,
        timeout_seconds=30.0,
    )


class Plan087ScriptTests(unittest.TestCase):
    def test_shell_entries_parse_and_reject_non_task_namespace(self) -> None:
        for script in (BOOTSTRAP, LAUNCHER, WORKER):
            subprocess.run(["bash", "-n", str(script)], check=True, timeout=10)
        self.assertEqual(
            subprocess.run(["bash", str(WORKER)], check=False, timeout=10).returncode,
            2,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            result = subprocess.run(
                ["bash", str(LAUNCHER), "--", "true"],
                check=False,
                timeout=10,
                env={
                    **os.environ,
                    "RONDO_PLAN087_TASK_ROOT": str(root),
                    "RONDO_PLAN087_SOURCE_ROOT": str(source),
                    "RONDO_PLAN087_IMAGE_IDENTITY": "fixture@sha256:" + "f" * 64,
                    "RONDO_PLAN087_LAUNCH_NAME": "fixture",
                    "RONDO_PLAN087_MAX_SECONDS": "60",
                },
            )
            self.assertEqual(result.returncode, 2)

    def test_terminal_deletes_only_exact_bound_pod_and_confirms_zero(self) -> None:
        args = _terminal_args()
        state = {"desiredStatus": "RUNNING", "runtimeStatus": "running"}
        calls: list[tuple[str, ...]] = []

        def query(command, _timeout):
            calls.append(tuple(command))
            if command[:2] == ("pod", "list"):
                return (
                    []
                    if state.get("deleted")
                    else [
                        {
                            "id": args.pod_id,
                            "name": args.pod_name,
                            "gpuCount": 1,
                            **state,
                        }
                    ]
                )
            if command[:2] == ("pod", "get"):
                return {
                    "id": args.pod_id,
                    "name": args.pod_name,
                    "gpuCount": 1,
                    **state,
                }
            if command[:2] == ("billing", "pods"):
                return [{"podId": args.pod_id, "amount": 0.2}]
            if command == ("user",):
                return {"clientBalance": 8.5, "currentSpendPerHr": 0.001}
            raise AssertionError(command)

        def mutate(command, _timeout):
            calls.append(tuple(command))
            if command[:2] == ("pod", "stop"):
                state.update(desiredStatus="EXITED", runtimeStatus="stopped")
                raise terminal.MutationUncertain("fixture_stop_timeout")
            if command[:2] == ("pod", "delete"):
                state["deleted"] = True
                raise terminal.MutationUncertain("fixture_delete_timeout")
            raise AssertionError(command)

        result = terminal.terminate_exact_pod(
            args,
            query=query,
            mutate=mutate,
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(result["pod_count"], 0)
        self.assertEqual(result["compute_rate_usd_per_hour"], 0.0)
        self.assertIn(("pod", "stop", args.pod_id), calls)
        self.assertIn(("pod", "delete", args.pod_id), calls)
        self.assertFalse(any("volume" in item for call in calls for item in call))

    def test_terminal_identity_mismatch_prevents_mutation(self) -> None:
        mutations = []
        with self.assertRaisesRegex(terminal.TerminalError, "account_pods_remain"):
            terminal.terminate_exact_pod(
                _terminal_args(),
                query=lambda _command, _timeout: [
                    {
                        "id": "other",
                        "name": "rondo-plan087-search-a",
                        "gpuCount": 1,
                    }
                ],
                mutate=lambda command, _timeout: mutations.append(command),
                monotonic=lambda: 0.0,
            )
        self.assertEqual(mutations, [])

    def test_terminal_is_idempotent_when_exact_pod_is_already_absent(self) -> None:
        def query(command, _timeout):
            if command[:2] == ("pod", "list"):
                return []
            if command[:2] == ("billing", "pods"):
                return []
            if command == ("user",):
                return {"clientBalance": 8.5, "currentSpendPerHr": 0.001}
            raise AssertionError(command)

        result = terminal.terminate_exact_pod(
            _terminal_args(),
            query=query,
            mutate=lambda *_args: self.fail("already absent must not mutate"),
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(result["pod_list_snapshot"], [])
        self.assertEqual(result["compute_rate_usd_per_hour"], 0.0)


if __name__ == "__main__":
    unittest.main()
