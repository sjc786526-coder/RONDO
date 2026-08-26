from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "training/publication-critic-plan087"
BOOTSTRAP = SCRIPT_ROOT / "runpod-bootstrap.sh"
LAUNCHER = SCRIPT_ROOT / "runpod-launch.sh"
WORKER = SCRIPT_ROOT / "runpod-worker.sh"
TERMINAL = SCRIPT_ROOT / "runpod-terminal.py"
CREATE = SCRIPT_ROOT / "runpod-create.py"
SPEC = importlib.util.spec_from_file_location("plan087_runpod_terminal", TERMINAL)
assert SPEC is not None and SPEC.loader is not None
terminal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(terminal)
CREATE_SPEC = importlib.util.spec_from_file_location("plan087_runpod_create", CREATE)
assert CREATE_SPEC is not None and CREATE_SPEC.loader is not None
create = importlib.util.module_from_spec(CREATE_SPEC)
CREATE_SPEC.loader.exec_module(create)
CONFIRMATION_START = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def _create_args(**overrides) -> argparse.Namespace:
    values = {
        "pod_name": "rondo-plan087-search-a",
        "task_pod_name_prefix": "rondo-plan087-",
        "image": "image@sha256:" + "a" * 64,
        "gpu_id": "NVIDIA A40",
        "data_center_id": "US-TX-3",
        "network_volume_id": "mwemzrn33y",
        "container_disk_gb": 20,
        "stop_after": "2026-08-26T12:30:00Z",
        "terminate_after": "2026-08-26T12:45:00Z",
        "wait_timeout": "10m",
        "captured_at": "2026-08-26T12:00:00Z",
        "poll_seconds": 0.01,
        "timeout_seconds": 30.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _created_pod(args: argparse.Namespace, **overrides) -> dict:
    value = {
        "id": "pod-087",
        "name": args.pod_name,
        "imageName": args.image,
        "gpuCount": 1,
        "gpuTypeId": args.gpu_id,
        "containerDiskInGb": args.container_disk_gb,
        "volumeMountPath": "/workspace",
        "desiredStatus": "RUNNING",
        "runtimeStatus": "initializing",
        "cloudType": "SECURE",
        "stopAfter": args.stop_after,
        "terminateAfter": args.terminate_after,
        "machine": {
            "gpuId": args.gpu_id,
            "dataCenterId": args.data_center_id,
        },
    }
    value.update(overrides)
    return value


def _provider_observation(
    args: argparse.Namespace, pending: dict, **pod_overrides
) -> dict:
    pod = {
        "id": pending["pod"]["id"],
        "name": args.pod_name,
        "image": args.image,
        "containerDiskInGb": args.container_disk_gb,
        "gpu": {"id": args.gpu_id, "count": 1},
        "volumeMountPath": "/workspace",
        "desiredStatus": "RUNNING",
        "machine": {
            "gpuTypeId": args.gpu_id,
            "dataCenterId": args.data_center_id,
            "secureCloud": True,
        },
        "networkVolume": {
            "id": args.network_volume_id,
            "dataCenterId": args.data_center_id,
        },
    }
    pod.update(pod_overrides)
    return {
        "schema": create.PROVIDER_OBSERVATION_SCHEMA,
        "captured_at": "2026-08-26T12:00:05Z",
        "source": "runpod-mcp-get-pod-v2",
        "include_machine": True,
        "include_network_volume": True,
        "pod": pod,
    }


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
        args = argparse.Namespace(
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
                            "id": "pod-087",
                            "name": "rondo-plan087-search-a",
                            "gpuCount": 1,
                            **state,
                        }
                    ]
                )
            if command[:2] == ("pod", "get"):
                return {
                    "id": "pod-087",
                    "name": "rondo-plan087-search-a",
                    "gpuCount": 1,
                    **state,
                }
            if command[:2] == ("billing", "pods"):
                return [{"podId": "pod-087", "amount": 0.2}]
            if command == ("user",):
                return {"clientBalance": 8.5, "currentSpendPerHr": 0.001}
            raise AssertionError(command)

        def mutate(command, _timeout):
            calls.append(tuple(command))
            if command[:2] == ("pod", "stop"):
                state.update(desiredStatus="EXITED", runtimeStatus="stopped")
                raise terminal.MutationUncertain("fixture_stop_timeout")
            elif command[:2] == ("pod", "delete"):
                state["deleted"] = True
                raise terminal.MutationUncertain("fixture_delete_timeout")
            else:
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
        self.assertIn(("pod", "stop", "pod-087"), calls)
        self.assertIn(("pod", "delete", "pod-087"), calls)
        self.assertFalse(any("volume" in item for call in calls for item in call))

    def test_terminal_identity_mismatch_prevents_mutation(self) -> None:
        args = argparse.Namespace(
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
        mutations = []
        with self.assertRaisesRegex(terminal.TerminalError, "account_pods_remain"):
            terminal.terminate_exact_pod(
                args,
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
        args = argparse.Namespace(
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

        def query(command, _timeout):
            if command[:2] == ("pod", "list"):
                return []
            if command[:2] == ("billing", "pods"):
                return []
            if command == ("user",):
                return {"clientBalance": 8.5, "currentSpendPerHr": 0.001}
            raise AssertionError(command)

        result = terminal.terminate_exact_pod(
            args,
            query=query,
            mutate=lambda *_args: self.fail("already absent must not mutate"),
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
        )
        self.assertEqual(result["pod_list_snapshot"], [])
        self.assertEqual(result["compute_rate_usd_per_hour"], 0.0)

    def test_create_timeout_reconciles_one_exact_pod_without_retry(self) -> None:
        args = _create_args()
        state = {"pod": None}
        mutations = []

        def query(command, _timeout):
            if command[:2] == ("pod", "list"):
                return [] if state["pod"] is None else [state["pod"]]
            if command[:2] == ("pod", "get"):
                return state["pod"]
            raise AssertionError(command)

        def mutate(command, _timeout):
            mutations.append(command)
            state["pod"] = _created_pod(args)
            raise create.MutationUncertain("fixture_timeout")

        result = create.create_or_reconcile_exact_pod(
            args,
            query=query,
            mutate=mutate,
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
            wall_clock=lambda: CONFIRMATION_START,
        )
        self.assertEqual(result["schema"], create.CREATE_PENDING_SCHEMA)
        self.assertTrue(result["mutation_response_uncertain"])
        self.assertEqual(result["pod"]["id"], "pod-087")
        self.assertEqual(len(mutations), 1)
        self.assertEqual(
            result["creation_contract_binding"]["basis"],
            "single_exact_create_request_after_empty_account",
        )
        self.assertFalse(
            result["creation_contract_binding"]["cross_process_reuse_allowed"]
        )
        self.assertNotIn("provider_observed", result["creation_contract_binding"])
        final = create.confirm_exact_pod_attachment(
            result,
            _provider_observation(args, result),
            wall_clock=lambda: CONFIRMATION_START + timedelta(seconds=10),
        )
        self.assertEqual(final["schema"], create.CREATE_SCHEMA)
        self.assertEqual(
            final["creation_contract_binding"]["provider_observed"][
                "network_volume_id"
            ],
            args.network_volume_id,
        )
        with self.assertRaisesRegex(
            create.CreateError, "existing_pod_contract_unverifiable"
        ):
            create.create_or_reconcile_exact_pod(
                args,
                query=query,
                mutate=lambda *_args: self.fail("existing Pod must not be adopted"),
                monotonic=lambda: 0.0,
                sleeper=lambda _seconds: None,
            )

    def test_create_uses_pending_receipt_for_stripped_runpodctl_projection(
        self,
    ) -> None:
        args = _create_args()
        state = {"pod": None}
        mutations = []
        queries = []

        def query(command, _timeout):
            queries.append(tuple(command))
            if command[:2] == ("pod", "list"):
                return [] if state["pod"] is None else [state["pod"]]
            if command[:2] == ("pod", "get"):
                return _created_pod(args)
            raise AssertionError(command)

        def mutate(command, _timeout):
            mutations.append(command)
            state["pod"] = _created_pod(args)

        result = create.create_or_reconcile_exact_pod(
            args,
            query=query,
            mutate=mutate,
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
            wall_clock=lambda: CONFIRMATION_START,
        )
        self.assertEqual(len(mutations), 1)
        self.assertEqual(
            [query for query in queries if query[:2] == ("pod", "get")],
            [("pod", "get", "pod-087", "--include-machine")],
        )
        self.assertEqual(result["attachment_confirmation"]["status"], "pending")

    def test_mcp_confirmation_rejects_missing_null_or_wrong_volume(self) -> None:
        args = _create_args()
        state = {"pod": None}

        def query(command, _timeout):
            if command[:2] == ("pod", "list"):
                return [] if state["pod"] is None else [state["pod"]]
            return _created_pod(args)

        def mutate(_command, _timeout):
            state["pod"] = _created_pod(args)

        pending = create.create_or_reconcile_exact_pod(
            args,
            query=query,
            mutate=mutate,
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
            wall_clock=lambda: CONFIRMATION_START,
        )
        cases = {
            "missing": ...,
            "null": None,
            "wrong": {"id": "other-volume"},
        }
        for label, network_volume in cases.items():
            observation = _provider_observation(args, pending)
            if network_volume is ...:
                observation["pod"].pop("networkVolume")
            else:
                observation["pod"]["networkVolume"] = network_volume
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    create.CreateError, "provider_attachment_configuration_drifted"
                ),
            ):
                create.confirm_exact_pod_attachment(
                    pending,
                    observation,
                    wall_clock=lambda: CONFIRMATION_START + timedelta(seconds=10),
                )

        final = create.confirm_exact_pod_attachment(
            pending,
            _provider_observation(args, pending),
            wall_clock=lambda: CONFIRMATION_START + timedelta(seconds=10),
        )
        self.assertEqual(
            final["creation_contract_binding"]["provider_observed"][
                "network_volume_id"
            ],
            args.network_volume_id,
        )
        with self.assertRaisesRegex(
            create.CreateError, "attachment_confirmation_timeout"
        ):
            create.confirm_exact_pod_attachment(
                pending,
                _provider_observation(args, pending),
                wall_clock=lambda: CONFIRMATION_START + timedelta(seconds=31),
            )

    def test_mcp_confirmation_rejects_provider_configuration_drift(self) -> None:
        args = _create_args()
        state = {"pod": None}

        def query(command, _timeout):
            if command[:2] == ("pod", "list"):
                return [] if state["pod"] is None else [state["pod"]]
            return _created_pod(args)

        def mutate(_command, _timeout):
            state["pod"] = _created_pod(args)

        pending = create.create_or_reconcile_exact_pod(
            args,
            query=query,
            mutate=mutate,
            monotonic=lambda: 0.0,
            sleeper=lambda _seconds: None,
            wall_clock=lambda: CONFIRMATION_START,
        )

        def wrong_image(pod):
            pod["image"] = "wrong-image"

        def wrong_gpu(pod):
            pod["gpu"]["id"] = "NVIDIA L40S"

        def wrong_machine_gpu(pod):
            pod["machine"]["gpuTypeId"] = "NVIDIA L40S"

        def wrong_region(pod):
            pod["machine"]["dataCenterId"] = "US-KS-2"

        def wrong_cloud(pod):
            pod["machine"]["secureCloud"] = False

        def wrong_disk(pod):
            pod["containerDiskInGb"] += 1

        def wrong_mount(pod):
            pod["volumeMountPath"] = "/other"

        for label, drift in {
            "image": wrong_image,
            "gpu": wrong_gpu,
            "machine_gpu": wrong_machine_gpu,
            "region": wrong_region,
            "cloud": wrong_cloud,
            "disk": wrong_disk,
            "mount": wrong_mount,
        }.items():
            observation = _provider_observation(args, pending)
            drift(observation["pod"])
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    create.CreateError, "provider_attachment_configuration_drifted"
                ),
            ):
                create.confirm_exact_pod_attachment(
                    pending,
                    observation,
                    wall_clock=lambda: CONFIRMATION_START + timedelta(seconds=10),
                )

    def test_create_rejects_configuration_drift_after_single_mutation(self) -> None:
        drift_cases = {
            "image": {"imageName": "other@sha256:" + "b" * 64},
            "gpu": {"gpuTypeId": "NVIDIA L40S"},
            "data_center": {
                "machine": {"gpuId": "NVIDIA A40", "dataCenterId": "US-KS-2"}
            },
            "container_disk": {"containerDiskInGb": 21},
            "mount": {"volumeMountPath": "/other"},
            "stop_after": {"stopAfter": "2026-08-26T12:31:00Z"},
            "terminate_after": {"terminateAfter": "2026-08-26T12:46:00Z"},
        }
        for label, drift in drift_cases.items():
            with self.subTest(label=label):
                args = _create_args()
                state = {"pod": None}
                mutations = []

                def query(command, _timeout):
                    if command[:2] == ("pod", "list"):
                        return [] if state["pod"] is None else [state["pod"]]
                    if command[:2] == ("pod", "get"):
                        return state["pod"]
                    raise AssertionError(command)

                def mutate(command, _timeout):
                    mutations.append(command)
                    state["pod"] = _created_pod(args, **drift)

                with self.assertRaisesRegex(
                    create.CreateError, "created_pod_configuration"
                ):
                    create.create_or_reconcile_exact_pod(
                        args,
                        query=query,
                        mutate=mutate,
                        monotonic=lambda: 0.0,
                        sleeper=lambda _seconds: None,
                    )
                self.assertEqual(len(mutations), 1)

    def test_create_rejects_preexisting_same_name_before_mutation(self) -> None:
        args = _create_args()
        pod = _created_pod(args, imageName="wrong-image")
        with self.assertRaisesRegex(
            create.CreateError, "existing_pod_contract_unverifiable"
        ):
            create.create_or_reconcile_exact_pod(
                args,
                query=lambda _command, _timeout: [pod],
                mutate=lambda *_args: self.fail("preexisting Pod must not mutate"),
                monotonic=lambda: 0.0,
            )

    def test_create_requires_absolute_ordered_stop_times(self) -> None:
        for args, code in (
            (_create_args(stop_after="30m"), "creation_datetime_invalid"),
            (
                _create_args(stop_after="2026-08-26T12:45:00Z"),
                "creation_stop_terminate_order_invalid",
            ),
        ):
            with (
                self.subTest(code=code),
                self.assertRaisesRegex(create.CreateError, code),
            ):
                create.create_or_reconcile_exact_pod(
                    args,
                    query=lambda *_args: self.fail("invalid time must fail first"),
                    mutate=lambda *_args: self.fail("invalid time must not mutate"),
                    monotonic=lambda: 0.0,
                )

    def test_create_rejects_unrelated_or_multiple_pods_before_mutation(self) -> None:
        args = _create_args()
        with self.assertRaisesRegex(
            create.CreateError, "account_pods_not_exactly_one_task_pod"
        ):
            create.create_or_reconcile_exact_pod(
                args,
                query=lambda _command, _timeout: [
                    {
                        "id": "other",
                        "name": "unrelated",
                        "gpuCount": 1,
                    }
                ],
                mutate=lambda *_args: self.fail("must not mutate"),
                monotonic=lambda: 0.0,
            )


if __name__ == "__main__":
    unittest.main()
