import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/wait-runpod-readiness.py"
SPEC = importlib.util.spec_from_file_location("wait_runpod_readiness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
waiter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(waiter)


def _args(budget_policy: Path) -> argparse.Namespace:
    return argparse.Namespace(
        pod_id="pod-1",
        pod_name="task-pod",
        required_desired_status="EXITED",
        required_runtime_status="stopped",
        gpu_id="NVIDIA H100 PCIe",
        gpu_memory_gb=80,
        expected_gpu_count=1,
        price_field="securePricePerHr",
        data_center_id=None,
        expected_machine_location=None,
        maximum_gpu_price_per_hour=2.89,
        baseline_balance=10.0,
        billing_start_time="2026-01-01T00:00:00Z",
        maximum_additional_seconds=3600,
        running_storage_per_hour=0.017,
        budget_policy=budget_policy,
    )


def _responses(*, available=True, price=2.89, balance=9.0, pod_name="task-pod"):
    return {
        "pod": {
            "id": "pod-1",
            "name": pod_name,
            "desiredStatus": "EXITED",
            "runtimeStatus": "stopped",
            "gpuCount": 1,
            "costPerHr": price,
            "machine": {
                "gpuId": "NVIDIA H100 PCIe",
                "dataCenterId": "US-KS-2",
                "location": "US",
            },
        },
        "user": {"clientBalance": balance, "currentSpendPerHr": 0.017},
        "gpu": [
            {
                "gpuId": "NVIDIA H100 PCIe",
                "memoryInGb": 80,
                "available": available,
                "securePricePerHr": price,
                "dataCenterAvailability": [],
            }
        ],
        "billing": [{"podId": "pod-1", "amount": 0.9}],
    }


class RunPodReadinessWaitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.policy_path = Path(self.temporary.name) / "budget-policy.json"
        self.policy_path.write_text('{"hard_cap_usd":6.0}\n')

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _evaluate(self, responses):
        return waiter.evaluate(
            _args(self.policy_path), lambda label, _command: responses[label]
        )

    def test_ready_requires_available_capacity_and_all_gates(self):
        result = self._evaluate(_responses())
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["failures"], [])
        self.assertAlmostEqual(result["budget"]["projected_cost_usd"], 3.907)

    def test_unavailable_capacity_waits_without_failing_other_gates(self):
        result = self._evaluate(_responses(available=False))
        self.assertEqual(result["status"], "waiting_capacity")
        self.assertEqual(result["failures"], [])

    def test_budget_projection_fails_closed(self):
        result = self._evaluate(_responses(balance=7.0))
        self.assertEqual(result["status"], "blocked")
        self.assertIn("projected_cost_gate_failed", result["failures"])

    def test_identity_and_price_drift_fail_closed(self):
        result = self._evaluate(_responses(price=3.0, pod_name="wrong"))
        self.assertEqual(result["status"], "blocked")
        self.assertIn("pod_identity_mismatch", result["failures"])
        self.assertIn("gpu_price_gate_failed", result["failures"])

    def test_pod_query_requests_machine_facts(self):
        commands = {}
        responses = _responses()

        def query(label, command):
            commands[label] = command
            return responses[label]

        result = waiter.evaluate(_args(self.policy_path), query)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(
            commands["pod"], ("pod", "get", "pod-1", "--include-machine")
        )

    def test_missing_or_wrong_pod_machine_fails_closed(self):
        missing = _responses()
        missing["pod"].pop("machine")
        result = self._evaluate(missing)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("pod_machine_missing", result["failures"])
        self.assertIn("pod_gpu_model_mismatch", result["failures"])

        wrong = _responses()
        wrong["pod"]["machine"] = {
            "gpuId": "NVIDIA A100 80GB PCIe",
            "dataCenterId": "EU-RO-1",
            "location": "EU",
        }
        args = _args(self.policy_path)
        args.data_center_id = "US-KS-2"
        args.expected_machine_location = "US"
        wrong["gpu"][0]["dataCenterAvailability"] = [
            {"dataCenterId": "US-KS-2", "stockStatus": "Low"}
        ]
        result = waiter.evaluate(args, lambda label, _command: wrong[label])
        self.assertEqual(result["status"], "blocked")
        self.assertIn("pod_gpu_model_mismatch", result["failures"])
        self.assertIn("pod_data_center_mismatch", result["failures"])
        self.assertIn("pod_machine_location_mismatch", result["failures"])

    def _main_argv(self, state_log: Path) -> list[str]:
        return [
            "--pod-id",
            "pod-1",
            "--pod-name",
            "task-pod",
            "--gpu-id",
            "NVIDIA H100 PCIe",
            "--gpu-memory-gb",
            "80",
            "--maximum-gpu-price-per-hour",
            "2.89",
            "--baseline-balance",
            "10",
            "--billing-start-time",
            "2026-01-01T00:00:00Z",
            "--maximum-additional-seconds",
            "3600",
            "--running-storage-per-hour",
            "0.017",
            "--budget-policy",
            str(self.policy_path),
            "--poll-seconds",
            "0.01",
            "--state-log",
            str(state_log),
            "--once",
        ]

    def test_non_finite_cli_bounds_fail_before_query(self):
        replacements = {
            "--maximum-gpu-price-per-hour": ("nan", "inf"),
            "--baseline-balance": ("nan", "inf"),
            "--running-storage-per-hour": ("nan", "inf"),
            "--poll-seconds": ("nan", "inf"),
            "--timeout-seconds": ("nan", "inf"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            state_log = Path(temporary) / "state.jsonl"
            for option, values in replacements.items():
                for value in values:
                    with self.subTest(option=option, value=value):
                        argv = self._main_argv(state_log)
                        if option == "--timeout-seconds":
                            argv.extend((option, value))
                        else:
                            argv[argv.index(option) + 1] = value
                        with mock.patch.object(waiter, "evaluate") as evaluate:
                            with self.assertRaisesRegex(
                                SystemExit, "invalid readiness wait bounds"
                            ):
                                waiter.main(argv)
                        evaluate.assert_not_called()

    def test_policy_is_reloaded_and_derived_cutoffs_are_recorded(self):
        self.policy_path.write_text('{"hard_cap_usd":10.0}\n')
        first = self._evaluate(_responses())
        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["budget"]["decision"], "normal_work")
        self.assertEqual(
            first["budget"]["policy"]["normal_work_cutoff_usd"], 8.75
        )

        self.policy_path.write_text('{"hard_cap_usd":4.0}\n')
        second = self._evaluate(_responses())
        self.assertEqual(second["status"], "blocked")
        self.assertEqual(second["budget"]["decision"], "no_new_work")
        self.assertNotEqual(
            first["budget"]["policy"]["source_sha256"],
            second["budget"]["policy"]["source_sha256"],
        )

    def test_policy_rejects_unknown_nonfinite_and_symlink_inputs(self):
        for raw in (
            '{"hard_cap_usd":6.0,"duplicate_cap":6.0}\n',
            '{"hard_cap_usd":6.0,"hard_cap_usd":7.0}\n',
            '{"hard_cap_usd":NaN}\n',
            '{"hard_cap_usd":false}\n',
        ):
            with self.subTest(raw=raw):
                self.policy_path.write_text(raw)
                with self.assertRaises(waiter.ReadinessQueryError):
                    self._evaluate(_responses())
        target = Path(self.temporary.name) / "policy-target.json"
        target.write_text('{"hard_cap_usd":6.0}\n')
        self.policy_path.unlink()
        self.policy_path.symlink_to(target)
        with self.assertRaisesRegex(
            waiter.ReadinessQueryError, "budget_policy_regular_file_required"
        ):
            self._evaluate(_responses())

    def test_late_ready_is_timeout_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            state_log = Path(temporary) / "state.jsonl"
            argv = self._main_argv(state_log)
            argv.remove("--once")
            argv.extend(("--timeout-seconds", "0.005"))

            def late_ready(_args, _query):
                time.sleep(0.02)
                return {
                    "schema": "rondo-runpod-readiness-wait-v1",
                    "captured_at": "ignored",
                    "status": "ready",
                    "failures": [],
                }

            with mock.patch.object(waiter, "evaluate", side_effect=late_ready):
                self.assertEqual(waiter.main(argv), 5)
            record = json.loads(state_log.read_text().splitlines()[-1])
            self.assertEqual(record["status"], "timeout")

    def test_hung_provider_query_is_bounded_and_sanitized(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = Path(temporary) / "hung-client"
            client.write_text("#!/bin/sh\nsleep 10\n")
            client.chmod(0o700)
            started = time.monotonic()
            with self.assertRaisesRegex(
                waiter.ReadinessQueryError, "pod_query_timeout"
            ):
                waiter._run_json(str(client), "pod", (), timeout=0.02)
            self.assertLess(time.monotonic() - started, 1.0)


if __name__ == "__main__":
    unittest.main()
