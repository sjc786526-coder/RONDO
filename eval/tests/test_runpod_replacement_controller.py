import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/create-runpod-replacement-when-ready.py"
SPEC = importlib.util.spec_from_file_location("runpod_replacement_controller", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
controller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller)


def _write_marker(root: Path) -> tuple[Path, str]:
    marker = root / "asset-verification.json"
    value = {
        "schema": controller.ASSET_VERIFICATION_SCHEMA,
        "status": "verified",
        "verified_at": "2026-08-24T00:00:00Z",
        "network_volume": {
            "id": "volume-1",
            "name": "task-assets",
            "type": "STANDARD",
            "size_gb": 60,
            "data_center_id": "US-KS-2",
            "mount_path": "/workspace",
        },
        "asset_root": "/workspace/task-root",
        "checks": [
            {
                "name": "exact-model",
                "status": "verified",
                "evidence_sha256": "a" * 64,
            },
            {
                "name": "runtime-imports",
                "status": "verified",
                "evidence_sha256": "b" * 64,
            },
        ],
    }
    marker.write_text(json.dumps(value, sort_keys=True) + "\n")
    marker.chmod(0o600)
    return marker, hashlib.sha256(marker.read_bytes()).hexdigest()


def _args(root: Path) -> argparse.Namespace:
    policy = root / "budget-policy.json"
    policy.write_text('{"hard_cap_usd":12.0}\n')
    marker, marker_sha = _write_marker(root)
    return argparse.Namespace(
        runpodctl="runpodctl",
        pod_name="rondo-task-replacement-01",
        task_pod_name_prefix="rondo-task-",
        allowed_stopped_pod_id=[],
        stopped_desired_status="EXITED",
        stopped_runtime_status="stopped",
        running_desired_status="RUNNING",
        running_runtime_status="running",
        gpu_id="NVIDIA H100 PCIe",
        gpu_memory_gb=80,
        expected_gpu_count=1,
        cloud_type="SECURE",
        data_center_id="US-KS-2",
        image="runpod/pytorch:exact",
        container_disk_gb=40,
        network_volume_id="volume-1",
        network_volume_name="task-assets",
        network_volume_type="STANDARD",
        network_volume_size_gb=60,
        volume_mount_path="/workspace",
        asset_root="/workspace/task-root",
        asset_verification_file=marker,
        asset_verification_sha256=marker_sha,
        required_asset_check=["exact-model", "runtime-imports"],
        port="22/tcp",
        minimum_cuda_version="12.8",
        expected_cuda_version="13.0",
        maximum_gpu_price_per_hour=2.89,
        baseline_balance=10.0,
        maximum_additional_seconds=600.0,
        running_storage_per_hour=0.029,
        budget_policy=policy,
        poll_seconds=0.01,
        create_timeout_seconds=1.0,
        create_reconciliation_grace_seconds=0.03,
        running_transition_timeout_seconds=10.0,
        handoff_ack_file=root / "handoff.ack",
        handoff_timeout_seconds=0.02,
        timeout_seconds=0.0,
        state_log=root / "state.jsonl",
        controller_lock=root / "controller.lock",
    )


def _pod(args, *, pod_id="pod-new", running=True, gpu_id=None):
    return {
        "id": pod_id,
        "name": args.pod_name,
        "desiredStatus": "RUNNING" if running else "CREATED",
        "runtimeStatus": "running" if running else "pending",
        "gpuCount": 1,
        "costPerHr": 2.89,
        "cloudType": "SECURE",
        "imageName": args.image,
        "networkVolumeId": args.network_volume_id,
        "machine": {
            "gpuId": gpu_id or args.gpu_id,
            "dataCenterId": args.data_center_id,
            "cudaVersion": args.expected_cuda_version,
        },
    }


def _responses(args, state):
    pods = []
    if state.get("duplicate"):
        pods = [
            _pod(args, pod_id="pod-a", running=False),
            _pod(args, pod_id="pod-b", running=False),
        ]
    elif state.get("other_active"):
        other = _pod(args, pod_id="pod-other", running=True)
        other["name"] = "rondo-task-other"
        pods = [other]
    elif state.get("other_stopped"):
        other = _pod(args, pod_id="pod-other", running=False)
        other["name"] = "rondo-task-other"
        other["desiredStatus"] = args.stopped_desired_status
        other["runtimeStatus"] = args.stopped_runtime_status
        pods = [other]
    elif state.get("created"):
        pods = [
            _pod(
                args,
                pod_id=state.get("actual_pod_id", "pod-new"),
                running=state.get("running", True),
            )
        ]
        if state.get("actual_pod_name"):
            pods[0]["name"] = state["actual_pod_name"]
    stock = state.get("stock", "Low")
    volume = {
        "id": args.network_volume_id,
        "name": args.network_volume_name,
        "type": (
            state["volume_type"]
            if "volume_type" in state
            else args.network_volume_type
        ),
        "size": args.network_volume_size_gb,
        "dataCenterId": state.get("volume_dc", args.data_center_id),
    }
    running = _pod(
        args,
        pod_id=state.get("actual_pod_id", "pod-new"),
        running=state.get("running", True),
        gpu_id=state.get("running_gpu"),
    )
    if state.get("stopped_after_stop"):
        running["desiredStatus"] = args.stopped_desired_status
        running["runtimeStatus"] = args.stopped_runtime_status
    if state.get("actual_pod_name"):
        running["name"] = state["actual_pod_name"]
    return {
        "user": {"clientBalance": 9.0, "currentSpendPerHr": 0.029},
        "gpu": [
            {
                "gpuId": args.gpu_id,
                "memoryInGb": 80,
                "securePricePerHr": 2.89,
                "dataCenterAvailability": [
                    {"dataCenterId": args.data_center_id, "stockStatus": stock}
                ],
            }
        ],
        "pods": pods,
        "pods_exact": [row for row in pods if row["name"] == args.pod_name],
        "network_volumes": [volume],
        "pod": running,
    }


def _query(args, state):
    def query(label, _command, _timeout):
        if label == "pods_preflight":
            return _responses(args, state)["pods"]
        return _responses(args, state)[label]

    return query


def _ack(args):
    def notify(_value):
        args.handoff_ack_file.write_text("ack\n")

    return notify


class RunPodReplacementControllerTests(unittest.TestCase):
    def test_provider_none_stock_normalizes_to_waiting_capacity(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {"stock": "none"}

            result = controller._evaluate_cycle(
                args,
                query=_query(args, state),
                timeout=1.0,
                adopted_pod_id=None,
            )

            self.assertEqual(result["status"], "waiting_capacity")
            self.assertEqual(result["gpu"]["stock_status"], "Out")
            self.assertEqual(result["failures"], [])

    def test_provider_stock_enum_is_case_insensitive_but_closed(self):
        self.assertEqual(controller._normalize_stock_status("low"), "Low")
        self.assertEqual(controller._normalize_stock_status("Medium"), "Medium")
        self.assertEqual(controller._normalize_stock_status("HIGH"), "High")
        with self.assertRaisesRegex(
            controller.ReplacementControllerError,
            "data_center_stock_invalid",
        ):
            controller._normalize_stock_status("available")

    def test_created_identity_only_binds_provider_id_and_name(self):
        value = {
            "id": "pod-new",
            "name": "rondo-plan060-pcie-replacement-01",
            "machine": {"cudaVersion": {"version": "still-pending"}},
        }
        self.assertEqual(
            controller._validate_created_pod_identity(value, "pod-new"),
            "rondo-plan060-pcie-replacement-01",
        )
        with self.assertRaisesRegex(
            controller.ReplacementControllerError,
            "created_pod_id_mismatch",
        ):
            controller._validate_created_pod_identity(value, "other-id")

    def test_missing_provider_volume_type_uses_verified_asset_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            result = controller._evaluate_cycle(
                args,
                query=_query(args, {"stock": "none", "volume_type": None}),
                timeout=1.0,
                adopted_pod_id=None,
            )

            self.assertEqual(result["status"], "waiting_capacity")
            self.assertEqual(result["network_volume"]["type"], "STANDARD")
            self.assertEqual(
                result["network_volume"]["type_source"],
                "asset_verification",
            )
            self.assertEqual(result["failures"], [])

    def test_explicit_provider_volume_type_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            result = controller._evaluate_cycle(
                args,
                query=_query(
                    args,
                    {"stock": "none", "volume_type": "HIGH_PERFORMANCE"},
                ),
                timeout=1.0,
                adopted_pod_id=None,
            )

            self.assertEqual(result["status"], "blocked")
            self.assertIn(
                "network_volume_contract_mismatch",
                result["failures"],
            )

    def test_exact_secure_single_gpu_create_argv(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            self.assertEqual(
                controller._create_command(args),
                (
                    "pod",
                    "create",
                    "--name",
                    args.pod_name,
                    "--gpu-id",
                    "NVIDIA H100 PCIe",
                    "--gpu-count",
                    "1",
                    "--compute-type",
                    "GPU",
                    "--cloud-type",
                    "SECURE",
                    "--image",
                    args.image,
                    "--container-disk-in-gb",
                    "40",
                    "--data-center-ids",
                    "US-KS-2",
                    "--network-volume-id",
                    "volume-1",
                    "--volume-mount-path",
                    "/workspace",
                    "--ports",
                    "22/tcp",
                    "--ssh",
                    "--min-cuda-version",
                    "12.8",
                ),
            )

    def test_capacity_wait_then_create_running_and_ack(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            calls = []

            def creator(_client, command, _timeout):
                calls.append(tuple(command))
                if len(calls) == 1:
                    return {"status": "capacity_unavailable"}
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                handoff_notifier=_ack(args),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "running_handoff_acknowledged")
            self.assertEqual(len(calls), 2)
            statuses = [
                json.loads(line)["status"]
                for line in args.state_log.read_text().splitlines()
            ]
            self.assertIn("waiting_create_capacity", statuses)
            self.assertIn("running_handoff_pending", statuses)

    def test_returned_running_id_handoffs_when_exact_name_list_lags(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            notified = []

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            def query(label, command, timeout):
                if label == "pods_exact":
                    return []
                return _query(args, state)(label, command, timeout)

            def notify(value):
                notified.append(value)
                args.handoff_ack_file.write_text("ack\n")

            code, result = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                handoff_notifier=notify,
                sleeper=lambda _seconds: None,
            )

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "running_handoff_acknowledged")
            self.assertEqual(len(notified), 1)
            self.assertTrue(
                notified[0]["running_provider_facts"][
                    "provider_review_required"
                ]
            )

    def test_adopted_running_pod_bypasses_catalog_and_volume_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            post_create_gate_queries = []

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            def query(label, command, timeout):
                if state.get("created") and label in {
                    "gpu",
                    "network_volumes",
                    "user",
                    "pods",
                }:
                    post_create_gate_queries.append(label)
                    raise controller.ReplacementControllerError(
                        "post_create_catalog_projection_unavailable"
                    )
                return _query(args, state)(label, command, timeout)

            code, result = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                handoff_notifier=_ack(args),
                sleeper=lambda _seconds: None,
            )

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "running_handoff_acknowledged")
            self.assertEqual(post_create_gate_queries, [])

    def test_restart_adopts_existing_running_exact_before_readiness_queries(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {"created": True, "running": True}
            forbidden = []
            notified = []

            def query(label, command, timeout):
                if label in {"user", "gpu", "pods", "network_volumes"}:
                    forbidden.append(label)
                    raise controller.ReplacementControllerError(
                        "readiness_projection_unavailable"
                    )
                return _query(args, state)(label, command, timeout)

            def notify(value):
                notified.append(value)
                args.handoff_ack_file.write_text("ack\n")

            creator = mock.Mock()
            code, result = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                handoff_notifier=notify,
                sleeper=lambda _seconds: None,
            )

            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "running_handoff_acknowledged")
            self.assertEqual(forbidden, [])
            self.assertEqual(len(notified), 1)
            creator.assert_not_called()

    def test_restart_exact_plus_other_task_pod_stops_only_exact(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            exact = _pod(args, pod_id="pod-exact", running=True)
            other = _pod(args, pod_id="pod-other", running=True)
            other["name"] = "rondo-task-other-active"
            exact_stopped = [False]
            stopped = []
            notified = []

            def query(label, _command, _timeout):
                if label == "pods_preflight":
                    return [exact, other]
                if label == "pod":
                    value = dict(exact)
                    if exact_stopped[0]:
                        value["desiredStatus"] = args.stopped_desired_status
                        value["runtimeStatus"] = args.stopped_runtime_status
                    return value
                raise AssertionError(f"unexpected query after conflict: {label}")

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                exact_stopped[0] = True

            code, result = controller.run_replacement_controller(
                args,
                query=query,
                creator=mock.Mock(),
                stopper=stopper,
                handoff_notifier=lambda value: notified.append(value),
                sleeper=lambda _seconds: None,
            )

            self.assertEqual(code, 6)
            self.assertEqual(result["status"], "handoff_failure_stopped")
            self.assertIn("other_task_pod_exists", result["error_code"])
            self.assertEqual(stopped, ["pod-exact"])
            self.assertEqual(notified, [])

    def test_create_timeout_exact_name_is_adopted_without_duplicate_create(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            calls = 0

            def creator(_client, _command, _timeout):
                nonlocal calls
                calls += 1
                state.update(created=True, running=True)
                return {"status": "uncertain_timeout"}

            code, _ = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                handoff_notifier=_ack(args),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            self.assertEqual(calls, 1)
            self.assertIn("create_uncertain_exact_name_adopted", args.state_log.read_text())

    def test_timeout_absent_retries_only_after_exact_name_query(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            calls = 0
            labels = []

            def query(label, command, timeout):
                labels.append(label)
                return _query(args, state)(label, command, timeout)

            def creator(_client, _command, _timeout):
                nonlocal calls
                calls += 1
                if calls == 1:
                    return {"status": "uncertain_timeout"}
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            code, _ = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                handoff_notifier=_ack(args),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            self.assertEqual(calls, 2)
            self.assertIn("pods_exact", labels)

    def test_noncapacity_create_failure_is_terminal_and_body_free(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=7, stdout="private-response", stderr="private-secret"
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(controller.subprocess, "run", return_value=completed):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                with self.assertRaisesRegex(
                    controller.ReplacementControllerError, "pod_create_failed_7"
                ):
                    controller._run_create("client", ("pod", "create"), 1.0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_invalid_requested_specifications_is_not_capacity(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="invalid requested specifications: bad cloud type private-detail",
        )
        with mock.patch.object(controller.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(
                controller.ReplacementControllerError, "pod_create_failed_1"
            ):
                controller._run_create("client", ("pod", "create"), 1.0)

    def test_success_with_invalid_json_is_uncertain_not_terminal_parse_error(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="private-invalid-json", stderr=""
        )
        with mock.patch.object(controller.subprocess, "run", return_value=completed):
            result = controller._run_create("client", ("pod", "create"), 1.0)
        self.assertEqual(
            result,
            {"status": "uncertain_success", "error_code": "pod_create_json_invalid"},
        )

    def test_success_with_valid_id_missing_name_preserves_id_for_cleanup(self):
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"id":"pod-new"}', stderr=""
        )
        with mock.patch.object(controller.subprocess, "run", return_value=completed):
            result = controller._run_create("client", ("pod", "create"), 1.0)
        self.assertEqual(
            result,
            {
                "status": "uncertain_success",
                "error_code": "pod_create_name_invalid",
                "pod_id": "pod-new",
            },
        )

    def test_uncertain_success_valid_id_missing_name_stops_mismatched_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {"actual_pod_name": "provider-missing-name-object"}
            stopped = []

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "uncertain_success",
                    "error_code": "pod_create_name_invalid",
                    "pod_id": "pod-new",
                }

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                state["stopped_after_stop"] = True

            code, _ = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                stopper=stopper,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 6)
            self.assertEqual(stopped, ["pod-new"])

    def test_uncertain_create_waits_through_eventual_consistency_and_adopts(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            creates = 0
            exact_queries = 0

            def creator(_client, _command, _timeout):
                nonlocal creates
                creates += 1
                return {"status": "uncertain_timeout"}

            def query(label, command, timeout):
                nonlocal exact_queries
                if label == "pods_exact":
                    exact_queries += 1
                    if exact_queries < 3:
                        return []
                    state.update(created=True, running=True)
                return _query(args, state)(label, command, timeout)

            code, _ = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                handoff_notifier=_ack(args),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            self.assertEqual(creates, 1)
            self.assertEqual(exact_queries, 3)

    def test_wrong_accepted_response_reconciles_exact_name_before_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": "wrong-response-name",
                }

            code, _ = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                handoff_notifier=_ack(args),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            self.assertIn("create_uncertain_exact_name_adopted", args.state_log.read_text())

    def test_wrong_returned_id_get_failure_blocks_exact_handoff_until_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {"actual_pod_id": "pod-real"}
            notified = []
            stopped = []
            clock = [0.0]

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-wrong",
                    "pod_name": args.pod_name,
                }

            def query(label, command, timeout):
                if label == "pod" and "pod-wrong" in command:
                    raise controller.ReplacementControllerError("pod_not_found")
                return _query(args, state)(label, command, timeout)

            def notify(value):
                notified.append(value["pod"]["id"])
                args.handoff_ack_file.write_text("ack\n")

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)

            def sleep(seconds):
                clock[0] += seconds

            code, result = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                stopper=stopper,
                handoff_notifier=notify,
                monotonic=lambda: clock[0],
                sleeper=sleep,
            )
            self.assertEqual(code, 7)
            self.assertEqual(notified, [])
            self.assertGreaterEqual(len(stopped), 1)
            self.assertEqual(set(stopped), {"pod-wrong"})
            self.assertEqual(result["status"], "cleanup_failed")

    def test_accepted_id_get_failure_and_exact_absence_still_attempts_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            stopped = []
            clock = [0.0]

            def creator(_client, _command, _timeout):
                return {
                    "status": "accepted",
                    "pod_id": "pod-returned",
                    "pod_name": args.pod_name,
                }

            def query(label, command, timeout):
                if label == "pod":
                    raise controller.ReplacementControllerError("pod_query_failed_9")
                return _query(args, state)(label, command, timeout)

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)

            def sleep(seconds):
                clock[0] += seconds

            code, result = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                stopper=stopper,
                monotonic=lambda: clock[0],
                sleeper=sleep,
            )
            self.assertEqual(code, 7)
            self.assertGreaterEqual(len(stopped), 1)
            self.assertEqual(set(stopped), {"pod-returned"})
            self.assertEqual(result["status"], "cleanup_failed")

    def test_expected_response_name_but_returned_id_actual_name_mismatch_stops(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {"actual_pod_name": "provider-wrong-task-name"}
            stopped = []

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                state["stopped_after_stop"] = True

            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                stopper=stopper,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 6)
            self.assertEqual(stopped, ["pod-new"])
            self.assertNotEqual(result["status"], "cleanup_failed")

    def test_bound_returned_id_conflict_is_stopped_before_exact_object_adoption(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {"created": False}
            wrong_stopped = [False]
            stopped = []
            notified = []

            exact_pod = _pod(args, pod_id="pod-real", running=True)
            wrong_pod = _pod(args, pod_id="pod-wrong", running=True)
            wrong_pod["name"] = "provider-returned-wrong-name"

            def creator(_client, _command, _timeout):
                state["created"] = True
                return {
                    "status": "accepted",
                    "pod_id": "pod-wrong",
                    "pod_name": args.pod_name,
                }

            def query(label, command, _timeout):
                base = _responses(args, {})
                if label == "pods":
                    return [exact_pod] if state["created"] else []
                if label == "pods_exact":
                    return [exact_pod] if state["created"] else []
                if label == "pods_preflight":
                    return [exact_pod] if state["created"] else []
                if label == "pod":
                    if "pod-wrong" in command:
                        value = dict(wrong_pod)
                        if wrong_stopped[0]:
                            value["desiredStatus"] = args.stopped_desired_status
                            value["runtimeStatus"] = args.stopped_runtime_status
                        return value
                    return exact_pod
                return base[label]

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                wrong_stopped[0] = True

            def notify(value):
                notified.append(value["pod"]["id"])
                args.handoff_ack_file.write_text("ack\n")

            code, _ = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                stopper=stopper,
                handoff_notifier=notify,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            self.assertEqual(stopped, ["pod-wrong"])
            self.assertEqual(notified, ["pod-real"])

    def test_wrong_name_returned_id_is_verified_then_stopped(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {"actual_pod_name": "provider-wrong-task-name"}
            stopped = []

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": "provider-wrong-task-name",
                }

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                state["stopped_after_stop"] = True

            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                stopper=stopper,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 6)
            self.assertEqual(stopped, ["pod-new"])
            self.assertIn("create_returned_id_name_mismatch", result["error_code"])

    def test_absent_then_query_failures_does_not_authorize_second_create(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            creates = 0
            exact_queries = 0
            clock = [0.0]

            def creator(_client, _command, _timeout):
                nonlocal creates
                creates += 1
                return {"status": "uncertain_timeout"}

            def query(label, command, timeout):
                nonlocal exact_queries
                if label == "pods_exact":
                    exact_queries += 1
                    if exact_queries == 1:
                        return []
                    raise controller.ReplacementControllerError("query_failed_9")
                return _query(args, state)(label, command, timeout)

            def sleep(seconds):
                clock[0] += seconds

            code, result = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                monotonic=lambda: clock[0],
                sleeper=sleep,
            )
            self.assertEqual(code, 4)
            self.assertEqual(creates, 1)
            self.assertEqual(result["error_code"], "create_reconciliation_query_failed")

    def test_duplicate_exact_name_and_other_active_task_pod_block(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for key, failure in (
                ("duplicate", "replacement_exact_name_duplicate"),
                ("other_active", "other_task_pod_exists"),
                ("other_stopped", "other_task_pod_exists"),
            ):
                with self.subTest(key=key):
                    args = _args(root)
                    state = {key: True}
                    creator = mock.Mock()
                    code, result = controller.run_replacement_controller(
                        args, query=_query(args, state), creator=creator
                    )
                    self.assertEqual(code, 2)
                    self.assertEqual(result["error_code"], failure)
                    creator.assert_not_called()
                    args.state_log.unlink()
                    args.controller_lock.unlink()

    def test_volume_and_asset_marker_mismatch_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, {"volume_dc": "US-OTHER-1"}),
                creator=mock.Mock(),
            )
            self.assertEqual(code, 2)
            self.assertIn("network_volume_contract_mismatch", result["cycle"]["failures"])

            args = _args(root)
            args.asset_verification_sha256 = "0" * 64
            with self.assertRaisesRegex(
                controller.ReplacementControllerError,
                "asset_verification_sha256_mismatch",
            ):
                controller.run_replacement_controller(
                    args, query=_query(args, {}), creator=mock.Mock()
                )

            args = _args(root)
            args.required_asset_check.append("missing-required-check")
            with self.assertRaisesRegex(
                controller.ReplacementControllerError,
                "asset_required_check_missing",
            ):
                controller.run_replacement_controller(
                    args, query=_query(args, {}), creator=mock.Mock()
                )

    def test_budget_is_reloaded_after_capacity_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            starts = 0

            def creator(_client, _command, _timeout):
                nonlocal starts
                starts += 1
                return {"status": "capacity_unavailable"}

            def lower_budget(_seconds):
                args.budget_policy.write_text('{"hard_cap_usd":2.0}\n')

            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, {}),
                creator=creator,
                sleeper=lower_budget,
            )
            self.assertEqual(code, 2)
            self.assertEqual(starts, 1)
            self.assertEqual(result["cycle"]["budget"]["policy"]["hard_cap_usd"], 2.0)

    def test_create_budget_is_rechecked_immediately_before_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            cycle = {
                "budget": {
                    "conservative_cost_usd": 1.0,
                    "projected_cost_usd": 1.5,
                }
            }
            controller._require_create_budget(args, cycle)
            args.budget_policy.write_text('{"hard_cap_usd":2.0}\n')
            with self.assertRaisesRegex(
                controller.ReplacementControllerError,
                "create_budget_gate_failed",
            ):
                controller._require_create_budget(args, cycle)

    def test_running_handoff_wakes_before_provider_contract_review(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True, running_gpu="wrong-gpu")
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            notified = []
            stopped = []

            def notify(value):
                notified.append(value)
                args.handoff_ack_file.write_text("ack\n")

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                state["stopped_after_stop"] = True

            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                stopper=stopper,
                handoff_notifier=notify,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "running_handoff_acknowledged")
            self.assertEqual(stopped, [])
            self.assertEqual(len(notified), 1)
            self.assertTrue(
                notified[0]["running_provider_facts"][
                    "provider_review_required"
                ]
            )

    def test_post_create_provider_contract_review_is_deferred_to_handoff(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            stopped = []

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True, volume_dc="US-OTHER-1")
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                state["stopped_after_stop"] = True

            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                stopper=stopper,
                handoff_notifier=_ack(args),
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "running_handoff_acknowledged")
            self.assertEqual(stopped, [])

    def test_adopted_query_failure_still_calls_stopper_with_broken_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            stopped = []

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                args.budget_policy.write_text("not-json\n")
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                state["stopped_after_stop"] = True

            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                stopper=stopper,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 6)
            self.assertEqual(stopped, ["pod-new"])
            self.assertIn("budget_policy_reload_failed_ignored", result["error_code"])

    def test_adopted_provider_query_error_still_calls_exact_stopper(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            stopped = []
            fail_pod_queries = [True]

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            def query(label, command, timeout):
                if label == "pod" and fail_pod_queries[0]:
                    raise controller.ReplacementControllerError("pod_query_failed_9")
                return _query(args, state)(label, command, timeout)

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                state["stopped_after_stop"] = True
                fail_pod_queries[0] = False

            code, result = controller.run_replacement_controller(
                args,
                query=query,
                creator=creator,
                stopper=stopper,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 6)
            self.assertEqual(result["status"], "handoff_failure_stopped")
            self.assertEqual(stopped, ["pod-new"])

    def test_handoff_notifier_failure_stops_adopted_pod(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            stopped = []

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                state["stopped_after_stop"] = True

            def broken_notifier(_value):
                raise BrokenPipeError("private-terminal-detail")

            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                stopper=stopper,
                handoff_notifier=broken_notifier,
                sleeper=lambda _seconds: None,
            )
            self.assertEqual(code, 6)
            self.assertEqual(stopped, ["pod-new"])
            self.assertNotIn("private-terminal-detail", json.dumps(result))

    def test_state_log_failure_after_adoption_still_stops_pod(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            stopped = []
            original_append = controller.readiness._append_log

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            def stopper(_client, pod_id, _timeout):
                stopped.append(pod_id)
                state["stopped_after_stop"] = True

            def failing_append(path, value):
                if value.get("status") == "running_handoff_pending":
                    raise OSError("private-disk-detail")
                return original_append(path, value)

            with mock.patch.object(
                controller.readiness, "_append_log", side_effect=failing_append
            ):
                code, result = controller.run_replacement_controller(
                    args,
                    query=_query(args, state),
                    creator=creator,
                    stopper=stopper,
                    handoff_notifier=lambda _value: None,
                    sleeper=lambda _seconds: None,
                )
            self.assertEqual(code, 6)
            self.assertEqual(stopped, ["pod-new"])
            self.assertNotIn("private-disk-detail", json.dumps(result))

    def test_cleanup_retries_transient_stop_failure_until_stopped(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {"created": True, "running": True}
            stops = 0
            clock = [0.0]

            def stopper(_client, _pod_id, _timeout):
                nonlocal stops
                stops += 1
                if stops == 1:
                    raise controller.start_wait.StartWaitError("pod_stop_failed_9")
                state["stopped_after_stop"] = True

            def sleep(seconds):
                clock[0] += seconds

            code, result = controller._emergency_stop_and_confirm(
                args,
                pod_id="pod-new",
                reason="test_cleanup",
                create_attempt_count=1,
                query=_query(args, state),
                stopper=stopper,
                monotonic=lambda: clock[0],
                sleeper=sleep,
            )
            self.assertEqual(code, 6)
            self.assertEqual(stops, 2)
            self.assertEqual(result["status"], "handoff_failure_stopped")

    def test_no_handoff_ack_stops_only_created_pod(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            state = {}
            stopped = []
            clock = [0.0]

            def creator(_client, _command, _timeout):
                state.update(created=True, running=True)
                return {
                    "status": "accepted",
                    "pod_id": "pod-new",
                    "pod_name": args.pod_name,
                }

            def stopper(client, pod_id, _timeout):
                stopped.append((client, pod_id))
                state["stopped_after_stop"] = True

            def sleep(seconds):
                clock[0] += seconds

            code, result = controller.run_replacement_controller(
                args,
                query=_query(args, state),
                creator=creator,
                stopper=stopper,
                handoff_notifier=lambda _value: None,
                monotonic=lambda: clock[0],
                sleeper=sleep,
            )
            self.assertEqual(code, 6)
            self.assertEqual(result["status"], "handoff_timeout_stopped")
            self.assertEqual(stopped, [("runpodctl", "pod-new")])

    def test_controller_lock_rejects_concurrent_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = _args(Path(temporary))
            with controller._controller_lock(args.controller_lock):
                with self.assertRaisesRegex(
                    controller.ReplacementControllerError,
                    "replacement_controller_already_running",
                ):
                    controller.run_replacement_controller(
                        args, query=_query(args, {}), creator=mock.Mock()
                    )

    def test_controller_lock_rejects_symlink_without_following(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = _args(root)
            target = root / "target.lock"
            target.write_text("do-not-touch")
            args.controller_lock.symlink_to(target)
            with self.assertRaisesRegex(
                controller.ReplacementControllerError,
                "controller_lock_symlink_rejected",
            ):
                controller.run_replacement_controller(
                    args, query=_query(args, {}), creator=mock.Mock()
                )
            self.assertEqual(target.read_text(), "do-not-touch")


if __name__ == "__main__":
    unittest.main()
