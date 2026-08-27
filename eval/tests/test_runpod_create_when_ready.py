import argparse
import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/create-runpod-when-ready.py"
SPEC = importlib.util.spec_from_file_location("runpod_create_when_ready", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        runpodctl="runpodctl",
        pod_name="rondo-create-when-ready-fixture",
        gpu_id="provider-current-gpu-id",
        gpu_count=1,
        compute_type="GPU",
        cloud_type="SECURE",
        data_center_id="provider-current-dc",
        image="provider/image:current",
        container_disk_gb=40,
        network_volume_id="provider-volume-id",
        volume_mount_path="/workspace",
        port=["22/tcp", "8888/http"],
        ssh=True,
        minimum_cuda_version="13.0",
        poll_seconds=0.01,
        query_timeout_seconds=1.0,
        create_timeout_seconds=1.0,
        reconciliation_grace_seconds=0.03,
        timeout_seconds=1.0,
    )


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class _Provider:
    def __init__(self, args: argparse.Namespace, clock: _Clock) -> None:
        self.args = args
        self.clock = clock
        self.stock = "Low"
        self.visible_at: float | None = None
        self.query_errors = 0
        self.events: list[str] = []

    def query(self, label, _command, _timeout):
        self.events.append(f"query:{label}")
        if self.query_errors:
            self.query_errors -= 1
            raise monitor.MonitorError("temporary_query_failure")
        if label == "gpu":
            return [
                {
                    "gpuId": self.args.gpu_id,
                    "dataCenterAvailability": [
                        {
                            "dataCenterId": self.args.data_center_id,
                            "stockStatus": self.stock,
                        }
                    ],
                }
            ]
        if label == "pods_exact":
            if self.visible_at is not None and self.clock.value >= self.visible_at:
                return [{"id": "pod-created", "name": self.args.pod_name}]
            return []
        raise AssertionError(label)


class RunPodCreateWhenReadyTests(unittest.TestCase):
    def test_create_command_uses_runtime_parameters(self):
        args = _args()
        args.gpu_id = "new-provider-gpu"
        args.gpu_count = 2
        args.cloud_type = "CURRENT-CLOUD"
        args.data_center_id = "new-provider-dc"
        args.minimum_cuda_version = None
        args.ssh = False

        command = monitor._create_command(args)

        self.assertIn("new-provider-gpu", command)
        self.assertIn("new-provider-dc", command)
        self.assertIn("CURRENT-CLOUD", command)
        self.assertIn("provider-volume-id", command)
        self.assertEqual(command.count("--ports"), 1)
        self.assertIn("22/tcp,8888/http", command)
        self.assertIn("--ssh=false", command)
        self.assertNotIn("--min-cuda-version", command)

    def test_waits_for_stock_then_creates(self):
        args = _args()
        clock = _Clock()
        provider = _Provider(args, clock)
        provider.stock = "Out"
        statuses = []

        def sleep(seconds):
            clock.sleep(seconds)
            provider.stock = "Low"

        def creator(_client, _command, _timeout):
            return {
                "status": "accepted",
                "pod_id": "pod-created",
                "pod_name": args.pod_name,
            }

        code, result = monitor.run_monitor(
            args,
            query=provider.query,
            creator=creator,
            sink=statuses.append,
            monotonic=clock.monotonic,
            sleeper=sleep,
        )

        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "pod_create_accepted")
        self.assertEqual(statuses[0]["status"], "waiting_capacity")
        self.assertEqual(result["create_attempt_count"], 1)

    def test_capacity_failure_is_retried(self):
        args = _args()
        clock = _Clock()
        provider = _Provider(args, clock)
        calls = 0

        def creator(_client, _command, _timeout):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"status": "capacity_unavailable"}
            return {
                "status": "accepted",
                "pod_id": "pod-created",
                "pod_name": args.pod_name,
            }

        code, result = monitor.run_monitor(
            args,
            query=provider.query,
            creator=creator,
            sink=lambda _value: None,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        self.assertEqual(code, 0)
        self.assertEqual(result["create_attempt_count"], 2)
        self.assertEqual(calls, 2)

    def test_delayed_visibility_during_full_grace_does_not_duplicate(self):
        args = _args()
        clock = _Clock()
        provider = _Provider(args, clock)
        calls = 0

        def creator(_client, _command, _timeout):
            nonlocal calls
            calls += 1
            provider.visible_at = clock.value + 0.025
            return {"status": "uncertain"}

        code, result = monitor.run_monitor(
            args,
            query=provider.query,
            creator=creator,
            sink=lambda _value: None,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "pod_create_reconciled")
        self.assertEqual(calls, 1)
        self.assertGreaterEqual(clock.value, 0.025)

    def test_uncertain_absence_waits_full_grace_before_retry(self):
        args = _args()
        clock = _Clock()
        provider = _Provider(args, clock)
        create_times = []

        def creator(_client, _command, _timeout):
            create_times.append(clock.value)
            if len(create_times) == 1:
                return {"status": "uncertain"}
            return {
                "status": "accepted",
                "pod_id": "pod-created",
                "pod_name": args.pod_name,
            }

        code, _result = monitor.run_monitor(
            args,
            query=provider.query,
            creator=creator,
            sink=lambda _value: None,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(create_times), 2)
        self.assertGreaterEqual(
            create_times[1] - create_times[0],
            args.reconciliation_grace_seconds,
        )

    def test_provider_error_body_is_not_exposed(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=9,
            stdout="private-provider-body",
            stderr="secret-provider-detail",
        )
        with (
            mock.patch.object(monitor.subprocess, "run", return_value=completed),
            self.assertRaisesRegex(
                monitor.MonitorError, "pod_create_failed_9"
            ) as caught,
        ):
            monitor._run_create("runpodctl", ("pod", "create"), 1.0)
        self.assertNotIn("private-provider-body", str(caught.exception))
        self.assertNotIn("secret-provider-detail", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
