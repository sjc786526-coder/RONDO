import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/start-runpod-when-ready.py"
SPEC = importlib.util.spec_from_file_location("start_runpod_when_ready", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
start_wait = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(start_wait)


def _args(root: Path) -> argparse.Namespace:
    policy = root / "budget-policy.json"
    policy.write_text('{"hard_cap_usd":10.0}\n')
    return argparse.Namespace(
        runpodctl="runpodctl",
        pod_id="pod-1",
        pod_name="task-pod",
        stopped_desired_status="EXITED",
        stopped_runtime_status="stopped",
        running_desired_status="RUNNING",
        running_runtime_status="running",
        gpu_id="NVIDIA H100 PCIe",
        gpu_memory_gb=80,
        expected_gpu_count=1,
        price_field="securePricePerHr",
        data_center_id="US-KS-2",
        expected_machine_location="US",
        maximum_gpu_price_per_hour=2.89,
        baseline_balance=10.0,
        billing_start_time="2026-01-01T00:00:00Z",
        maximum_additional_seconds=3600,
        running_storage_per_hour=0.017,
        budget_policy=policy,
        poll_seconds=0.01,
        start_retry_seconds=0.01,
        start_transition_timeout_seconds=120.0,
        handoff_ack_file=root / "handoff.ack",
        handoff_timeout_seconds=180.0,
        timeout_seconds=0.0,
        maximum_consecutive_query_errors=2,
        required_consecutive_ready=1,
        state_log=root / "state.jsonl",
    )


def _responses(state: dict[str, str], *, pod_name: str = "task-pod"):
    return {
        "pod": {
            "id": "pod-1",
            "name": pod_name,
            "desiredStatus": state["desired"],
            "runtimeStatus": state["runtime"],
            "gpuCount": 1,
            "costPerHr": 2.89,
            "machine": {
                "gpuId": "NVIDIA H100 PCIe",
                "dataCenterId": "US-KS-2",
                "location": "US",
            },
        },
        "user": {"clientBalance": 9.0, "currentSpendPerHr": 0.017},
        "gpu": [
            {
                "gpuId": "NVIDIA H100 PCIe",
                "memoryInGb": 80,
                "available": True,
                "securePricePerHr": 2.89,
                "dataCenterAvailability": [
                    {"dataCenterId": "US-KS-2", "stockStatus": "Low"}
                ],
            }
        ],
        "billing": [{"podId": "pod-1", "amount": 0.9}],
    }


def _query_for(state: dict[str, str], *, pod_name: str = "task-pod"):
    def query(label, _command, _timeout):
        return _responses(state, pod_name=pod_name)[label]

    return query


def _acknowledge(args: argparse.Namespace):
    def notify(_value):
        args.handoff_ack_file.write_text("ack\n")

    return notify


class RunPodExistingPodStartWaitTests(unittest.TestCase):
    def test_start_subprocess_is_exact_and_capacity_body_is_not_forwarded(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="private-start-body",
            stderr="HTTP 400: not enough free GPUs",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(start_wait.subprocess, "run", return_value=completed) as run:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                outcome = start_wait._start_same_pod("client", "pod-1", 3.0)
        self.assertEqual(outcome, "capacity_unavailable")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            run.call_args.args[0],
            ["client", "pod", "start", "pod-1", "-o", "json"],
        )
        self.assertNotIn("create", run.call_args.args[0])

    def test_non_capacity_start_error_fails_with_sanitized_code(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=7,
            stdout="private-response",
            stderr="authentication detail",
        )
        with mock.patch.object(start_wait.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(start_wait.StartWaitError, "pod_start_failed_7"):
                start_wait._start_same_pod("client", "pod-1", None)

    def test_runpodctl_capacity_json_without_http_status_is_retryable(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=(
                '{"error":"There are not enough free GPUs on the host '
                'machine to start this pod.","code":"provider_error"}'
            ),
            stderr="",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(start_wait.subprocess, "run", return_value=completed):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                outcome = start_wait._start_same_pod("client", "pod-1", None)
        self.assertEqual(outcome, "capacity_unavailable")
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_capacity_retry_starts_only_same_pod_and_exits_when_running(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            state = {"desired": "EXITED", "runtime": "stopped"}
            calls = []

            def starter(client, pod_id, _timeout):
                calls.append((client, pod_id))
                if len(calls) == 1:
                    return "capacity_unavailable"
                state.update(desired="RUNNING", runtime="running")
                return "accepted"

            code, result = start_wait.wait_for_existing_pod_start(
                args,
                query=_query_for(state),
                starter=starter,
                handoff_notifier=_acknowledge(args),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "running_handoff_acknowledged")
            self.assertEqual(calls, [("runpodctl", "pod-1")] * 2)
            records = [
                json.loads(line) for line in args.state_log.read_text().splitlines()
            ]
            self.assertIn("waiting_host_capacity", [row["status"] for row in records])
            self.assertNotIn("private", args.state_log.read_text())

    def test_budget_is_reloaded_after_capacity_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            state = {"desired": "EXITED", "runtime": "stopped"}
            starts = 0

            def starter(_client, _pod_id, _timeout):
                nonlocal starts
                starts += 1
                return "capacity_unavailable"

            def lower_budget(_seconds):
                args.budget_policy.write_text('{"hard_cap_usd":2.0}\n')

            code, result = start_wait.wait_for_existing_pod_start(
                args,
                query=_query_for(state),
                starter=starter,
                sleeper=lower_budget,
            )
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(starts, 1)
            self.assertEqual(
                result["readiness"]["budget"]["policy"]["hard_cap_usd"], 2.0
            )

    def test_identity_mismatch_blocks_before_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            state = {"desired": "EXITED", "runtime": "stopped"}
            starter = mock.Mock(return_value="accepted")
            code, result = start_wait.wait_for_existing_pod_start(
                args,
                query=_query_for(state, pod_name="other-pod"),
                starter=starter,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "blocked")
            self.assertIn(
                "pod_identity_mismatch", result["readiness"]["failures"]
            )
            starter.assert_not_called()

    def test_accepted_start_is_not_reissued_while_state_is_still_stopped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            state = {"desired": "EXITED", "runtime": "stopped"}
            starts = 0
            sleeps = 0

            def starter(_client, _pod_id, _timeout):
                nonlocal starts
                starts += 1
                return "accepted"

            def transition(_seconds):
                nonlocal sleeps
                sleeps += 1
                if sleeps >= 2:
                    state.update(desired="RUNNING", runtime="running")

            code, _result = start_wait.wait_for_existing_pod_start(
                args,
                query=_query_for(state),
                starter=starter,
                handoff_notifier=_acknowledge(args),
                sleeper=transition,
            )
            self.assertEqual(code, 0)
            self.assertEqual(starts, 1)

    def test_stopped_state_is_retried_after_transition_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            args.start_transition_timeout_seconds = 0.02
            state = {"desired": "EXITED", "runtime": "stopped"}
            starts = 0
            clock = [0.0]

            def starter(_client, _pod_id, _timeout):
                nonlocal starts
                starts += 1
                if starts == 2:
                    state.update(desired="RUNNING", runtime="running")
                return "accepted"

            def advance(seconds):
                clock[0] += seconds

            code, result = start_wait.wait_for_existing_pod_start(
                args,
                query=_query_for(state),
                starter=starter,
                handoff_notifier=_acknowledge(args),
                monotonic=lambda: clock[0],
                sleeper=advance,
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "running_handoff_acknowledged")
            self.assertEqual(starts, 2)

    def test_running_acknowledgement_exits_without_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            state = {"desired": "RUNNING", "runtime": "running"}
            stopper = mock.Mock()
            stdout = io.StringIO()

            def notify(value):
                start_wait._stdout_handoff(value)
                args.handoff_ack_file.write_text("ack\n")

            with redirect_stdout(stdout):
                code, result = start_wait.wait_for_existing_pod_start(
                    args,
                    query=_query_for(state),
                    starter=mock.Mock(),
                    stopper=stopper,
                    handoff_notifier=notify,
                    sleeper=lambda _seconds: None,
                )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "running_handoff_acknowledged")
            stopper.assert_not_called()
            wake = json.loads(stdout.getvalue())
            self.assertEqual(wake["status"], "running_handoff_pending")
            self.assertEqual(wake["pod"], {"id": "pod-1", "name": "task-pod"})
            self.assertEqual(wake["handoff_ack_file"], str(args.handoff_ack_file))

    def test_handoff_timeout_stops_exact_pod_without_forwarding_provider_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            args.handoff_timeout_seconds = 0.02
            state = {"desired": "RUNNING", "runtime": "running"}
            clock = [0.0]
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="private-stop-body",
                stderr="private-stop-detail",
            )

            def advance(seconds):
                clock[0] += seconds

            with mock.patch.object(
                start_wait.subprocess, "run", return_value=completed
            ) as run:
                def query(label, _command, _timeout):
                    if run.call_count:
                        state.update(desired="EXITED", runtime="stopped")
                    return _responses(state)[label]

                stdout = io.StringIO()
                stderr = io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code, result = start_wait.wait_for_existing_pod_start(
                        args,
                        query=query,
                        starter=mock.Mock(),
                        monotonic=lambda: clock[0],
                        sleeper=advance,
                    )
            self.assertEqual(code, 6)
            self.assertEqual(result["status"], "handoff_timeout_stopped")
            self.assertEqual(
                run.call_args.args[0],
                ["runpodctl", "pod", "stop", "pod-1", "-o", "json"],
            )
            self.assertNotIn("private-stop", stdout.getvalue())
            self.assertNotIn("private-stop", stderr.getvalue())
            self.assertNotIn("private-stop", args.state_log.read_text())

    def test_stale_regular_or_symlink_ack_is_rejected_before_provider_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            args.handoff_ack_file.write_text("stale\n")
            with self.assertRaisesRegex(
                SystemExit, "handoff ack file must not already exist"
            ):
                start_wait._validate_args(args)

            args.handoff_ack_file.unlink()
            target = root / "ack-target"
            target.write_text("stale\n")
            args.handoff_ack_file.symlink_to(target)
            with self.assertRaisesRegex(
                SystemExit, "handoff ack file must not already exist"
            ):
                start_wait._validate_args(args)


if __name__ == "__main__":
    unittest.main()
