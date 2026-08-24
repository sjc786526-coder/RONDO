import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/runpod-candidate-controller.py"
SPEC = importlib.util.spec_from_file_location("runpod_candidate_controller", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
controller = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller)


def _candidate(candidate_id, gpu_id, preference, data_centers):
    return {
        "candidate_id": candidate_id,
        "gpu_id": gpu_id,
        "gpu_count": 1,
        "gpu_memory_gb": 80,
        "secure_cloud": True,
        "preference": preference,
        "allowed_data_center_ids": data_centers,
        "allowed_cuda_versions": ["13.0"],
    }


def _observation(candidate, *, stock, price, data_center=None):
    return {
        "candidate_id": candidate["candidate_id"],
        "gpu_id": candidate["gpu_id"],
        "gpu_count": candidate["gpu_count"],
        "gpu_memory_gb": candidate["gpu_memory_gb"],
        "secure_cloud": candidate["secure_cloud"],
        "data_center_id": data_center or candidate["allowed_data_center_ids"][0],
        "cuda_version": "13.0",
        "stock_status": stock,
        "price_per_hour_usd": price,
    }


def _policy(root, cap=10.0):
    path = root / "budget-policy.json"
    path.write_text(json.dumps({"hard_cap_usd": cap}) + "\n")
    return path


def _cycle(root, candidates, observations, **kwargs):
    policy_path = kwargs.pop("budget_policy_path", None)
    if policy_path is None:
        policy_path = _policy(root)
    return controller.select_candidate_cycle(
        candidates,
        observations,
        budget_policy_path=policy_path,
        conservative_cost_usd=kwargs.pop("conservative_cost_usd", 1.0),
        projected_runtime_seconds=kwargs.pop("projected_runtime_seconds", 600.0),
        hourly_non_gpu_cost_usd=kwargs.pop("hourly_non_gpu_cost_usd", 0.02),
        **kwargs,
    )


def _running_pod(observation, *, pod_id="pod-1", pod_name="task-pod"):
    return {
        "id": pod_id,
        "name": pod_name,
        "desired_status": "RUNNING",
        "runtime_status": "running",
        "candidate_id": observation["candidate_id"],
        "gpu_id": observation["gpu_id"],
        "gpu_count": observation["gpu_count"],
        "gpu_memory_gb": observation["gpu_memory_gb"],
        "secure_cloud": observation["secure_cloud"],
        "data_center_id": observation["data_center_id"],
        "cuda_version": observation["cuda_version"],
        "cost_per_hour_usd": observation["price_per_hour_usd"],
    }


def _reconciliation_pod(
    *, name="task-pod", gpu_id="NVIDIA H100 PCIe", gpu_count=1, running=False
):
    zero = gpu_count == 0
    return {
        "id": "pod-1",
        "name": name,
        "desired_status": "RUNNING" if running else "CREATED",
        "runtime_status": "running" if running else "pending",
        "gpu_id": None if zero else gpu_id,
        "gpu_count": gpu_count,
        "gpu_memory_gb": None if zero else 80,
        "secure_cloud": True,
        "data_center_id": None if zero else "US-KS-2",
        "cuda_version": None if zero else "13.0",
    }


class RunPodCandidateControllerTests(unittest.TestCase):
    def setUp(self):
        self.pcie = _candidate("pcie", "NVIDIA H100 PCIe", 0, ["US-KS-2"])
        self.sxm = _candidate("sxm", "NVIDIA H100 80GB HBM3", 1, ["US-NE-1"])

    def test_stock_precedes_explicit_preference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = _cycle(
                root,
                [self.pcie, self.sxm],
                [
                    _observation(self.pcie, stock="Low", price=2.89),
                    _observation(self.sxm, stock="High", price=3.49),
                ],
            )
        self.assertEqual(result["selected_candidate"]["candidate"]["candidate_id"], "sxm")

    def test_same_stock_uses_preference_before_price(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = _cycle(
                root,
                [self.sxm, self.pcie],
                [
                    _observation(self.sxm, stock="Medium", price=2.0),
                    _observation(self.pcie, stock="Medium", price=2.89),
                ],
            )
        self.assertEqual(result["selected_candidate"]["candidate"]["candidate_id"], "pcie")

    def test_price_then_data_center_are_stable_tiebreakers(self):
        first = _candidate("first", self.pcie["gpu_id"], 0, ["US-ZZ-1"])
        second = _candidate("second", self.pcie["gpu_id"], 0, ["US-AA-1"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cheaper = _cycle(
                root,
                [first, second],
                [
                    _observation(first, stock="Low", price=2.0),
                    _observation(second, stock="Low", price=1.5),
                ],
            )
            tied = _cycle(
                root,
                [first, second],
                [
                    _observation(first, stock="Low", price=2.0),
                    _observation(second, stock="Low", price=2.0),
                ],
            )
        self.assertEqual(cheaper["selected_candidate"]["candidate"]["candidate_id"], "second")
        self.assertEqual(tied["selected_candidate"]["candidate"]["candidate_id"], "second")

    def test_selection_rejects_every_plan060_hardware_boundary_violation(self):
        cases = (
            ("other_gpu", "gpu_id", "GPU A", "candidate_gpu_id_not_allowed"),
            ("two_gpus", "gpu_count", 2, "candidate_gpu_count_not_one"),
            (
                "wrong_memory",
                "gpu_memory_gb",
                40,
                "candidate_gpu_memory_not_80gb",
            ),
            (
                "community",
                "secure_cloud",
                False,
                "candidate_secure_cloud_required",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, key, value, error in cases:
                with self.subTest(label=label):
                    candidate = dict(self.pcie)
                    candidate[key] = value
                    observation = _observation(
                        candidate, stock="Low", price=2.89
                    )
                    with self.assertRaisesRegex(
                        controller.CandidateControllerError, error
                    ):
                        _cycle(root, [candidate], [observation])
            zero_price = _observation(self.pcie, stock="Low", price=0.0)
            with self.assertRaisesRegex(
                controller.CandidateControllerError,
                "observation_price_per_hour_usd_invalid",
            ):
                _cycle(root, [self.pcie], [zero_price])

    def test_budget_policy_is_reloaded_each_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = _policy(root, 10.0)
            observation = _observation(self.pcie, stock="High", price=2.89)
            ready = _cycle(
                root, [self.pcie], [observation], budget_policy_path=policy
            )
            policy.write_text('{"hard_cap_usd":2.0}\n')
            blocked = _cycle(
                root, [self.pcie], [observation], budget_policy_path=policy
            )
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(blocked["status"], "no_new_work")
        self.assertEqual(blocked["budget_policy"]["hard_cap_usd"], 2.0)

    def test_out_stock_waits_and_nonfinite_or_unknown_values_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observation = _observation(self.pcie, stock="Out", price=2.89)
            result = _cycle(root, [self.pcie], [observation])
            self.assertEqual(result["status"], "waiting_capacity")
            observation["stock_status"] = "Mystery"
            with self.assertRaisesRegex(
                controller.CandidateControllerError,
                "observation_stock_status_unknown",
            ):
                _cycle(root, [self.pcie], [observation])
            observation["stock_status"] = "Low"
            observation["price_per_hour_usd"] = math.inf
            with self.assertRaisesRegex(
                controller.CandidateControllerError,
                "observation_price_per_hour_usd_invalid",
            ):
                _cycle(root, [self.pcie], [observation])

    def test_missing_or_unknown_fields_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observation = _observation(self.pcie, stock="Low", price=2.89)
            del observation["cuda_version"]
            with self.assertRaisesRegex(
                controller.CandidateControllerError,
                "candidate_observation_shape_invalid",
            ):
                _cycle(root, [self.pcie], [observation])
            observation = _observation(self.pcie, stock="Low", price=2.89)
            observation["unknown"] = "x"
            with self.assertRaisesRegex(
                controller.CandidateControllerError,
                "candidate_observation_shape_invalid",
            ):
                _cycle(root, [self.pcie], [observation])

    def test_winner_lock_requires_exact_running_identity_and_is_mode_0600(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = root / "winner.json"
            observation = _observation(self.pcie, stock="Low", price=2.89)
            pod = _running_pod(observation)
            pod["runtime_status"] = "pending"
            with self.assertRaisesRegex(
                controller.CandidateControllerError,
                "running_pod_status_unverified",
            ):
                controller.write_winner_lock(
                    lock,
                    observation,
                    pod,
                    expected_pod_id="pod-1",
                    expected_pod_name="task-pod",
                )
            self.assertFalse(lock.exists())
            pod["runtime_status"] = "running"
            record, created = controller.write_winner_lock(
                lock,
                observation,
                pod,
                expected_pod_id="pod-1",
                expected_pod_name="task-pod",
                evidence={"selection_cycle": "cycle-1"},
            )
            self.assertTrue(created)
            self.assertEqual(record["schema"], controller.WINNER_LOCK_SCHEMA)
            self.assertEqual(record["selected_gpu"], self.pcie["gpu_id"])
            self.assertEqual(record["evidence"]["selection_cycle"], "cycle-1")
            self.assertEqual(
                record["evidence"]["selected_gpu_facts"]["gpu_id"],
                self.pcie["gpu_id"],
            )
            self.assertEqual(stat.S_IMODE(os.lstat(lock).st_mode), 0o600)

    def test_winner_write_rejects_every_plan060_hardware_boundary_violation(self):
        cases = (
            ("other_gpu", "gpu_id", "GPU A", "winner_observation_gpu_id_not_allowed"),
            (
                "two_gpus",
                "gpu_count",
                2,
                "winner_observation_gpu_count_not_one",
            ),
            (
                "wrong_memory",
                "gpu_memory_gb",
                40,
                "winner_observation_gpu_memory_not_80gb",
            ),
            (
                "community",
                "secure_cloud",
                False,
                "winner_observation_secure_cloud_required",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for label, key, value, error in cases:
                with self.subTest(label=label):
                    observation = _observation(
                        self.pcie, stock="Low", price=2.89
                    )
                    observation[key] = value
                    pod = _running_pod(observation)
                    with self.assertRaisesRegex(
                        controller.CandidateControllerError, error
                    ):
                        controller.write_winner_lock(
                            root / f"{label}.json",
                            observation,
                            pod,
                            expected_pod_id="pod-1",
                            expected_pod_name="task-pod",
                        )
            zero_price = _observation(self.pcie, stock="Low", price=0.0)
            with self.assertRaisesRegex(
                controller.CandidateControllerError,
                "observation_price_per_hour_usd_invalid",
            ):
                controller.write_winner_lock(
                    root / "zero-price.json",
                    zero_price,
                    _running_pod(zero_price),
                    expected_pod_id="pod-1",
                    expected_pod_name="task-pod",
                )
            observation = _observation(self.pcie, stock="Low", price=2.89)
            pod = _running_pod(observation)
            pod["cost_per_hour_usd"] = 0.0
            with self.assertRaisesRegex(
                controller.CandidateControllerError,
                "running_pod_cost_per_hour_usd_invalid",
            ):
                controller.write_winner_lock(
                    root / "zero-pod-cost.json",
                    observation,
                    pod,
                    expected_pod_id="pod-1",
                    expected_pod_name="task-pod",
                )

    def test_legacy_object_selected_gpu_shape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "winner.json"
            lock.write_text(
                json.dumps(
                    {
                        "schema": controller.WINNER_LOCK_SCHEMA,
                        "selected_gpu": {"gpu_id": self.pcie["gpu_id"]},
                        "evidence": {
                            "selected_gpu_facts": {"gpu_id": self.pcie["gpu_id"]}
                        },
                    }
                )
                + "\n"
            )
            lock.chmod(0o600)
            with self.assertRaisesRegex(
                controller.CandidateControllerError,
                "winner_lock_selected_gpu_invalid",
            ):
                controller.load_winner_lock(lock)

    def test_existing_lock_is_immutable_and_never_switches_gpu(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = root / "winner.json"
            pcie_observation = _observation(self.pcie, stock="Low", price=2.89)
            first, created = controller.write_winner_lock(
                lock,
                pcie_observation,
                _running_pod(pcie_observation),
                expected_pod_id="pod-1",
                expected_pod_name="task-pod",
            )
            same, created_again = controller.write_winner_lock(
                lock,
                pcie_observation,
                _running_pod(pcie_observation, pod_id="pod-2", pod_name="replacement"),
                expected_pod_id="pod-2",
                expected_pod_name="replacement",
            )
            self.assertFalse(created_again)
            self.assertEqual(same, first)
            sxm_observation = _observation(self.sxm, stock="High", price=3.49)
            with self.assertRaisesRegex(
                controller.CandidateControllerError, "winner_gpu_already_locked"
            ):
                controller.write_winner_lock(
                    lock,
                    sxm_observation,
                    _running_pod(sxm_observation),
                    expected_pod_id="pod-1",
                    expected_pod_name="task-pod",
                )

    def test_existing_lock_filters_future_cycles_to_winner_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock = root / "winner.json"
            pcie_observation = _observation(self.pcie, stock="Low", price=2.89)
            controller.write_winner_lock(
                lock,
                pcie_observation,
                _running_pod(pcie_observation),
                expected_pod_id="pod-1",
                expected_pod_name="task-pod",
            )
            result = _cycle(
                root,
                [self.pcie, self.sxm],
                [
                    _observation(self.pcie, stock="Out", price=2.89),
                    _observation(self.sxm, stock="High", price=3.49),
                ],
                winner_lock_path=lock,
            )
        self.assertEqual(result["status"], "waiting_capacity")
        self.assertEqual(result["winner_gpu_id"], self.pcie["gpu_id"])
        self.assertEqual(len(result["ordered_candidates"]), 1)

    def test_provider_error_classification_is_narrow(self):
        self.assertEqual(
            controller.classify_provider_failure(
                return_code=1, message="not enough free GPUs"
            ),
            "retry_capacity",
        )
        self.assertEqual(
            controller.classify_provider_failure(
                return_code=401, message="not enough free GPUs plus auth failure"
            ),
            "fail",
        )
        self.assertEqual(
            controller.classify_provider_failure(
                return_code=None, message="", timed_out=True
            ),
            "reconcile_create_name",
        )

    def test_capacity_failure_advances_in_frozen_order_and_other_errors_fail(self):
        first = controller.decide_after_create_failure(
            failure_class="retry_capacity",
            attempted_candidate_id="pcie",
            ordered_candidate_ids=["pcie", "sxm"],
        )
        self.assertEqual(first["action"], "try_candidate")
        self.assertEqual(first["candidate_id"], "sxm")
        exhausted = controller.decide_after_create_failure(
            failure_class="retry_capacity",
            attempted_candidate_id="sxm",
            ordered_candidate_ids=["pcie", "sxm"],
        )
        self.assertEqual(exhausted["action"], "wait_capacity")
        fatal = controller.decide_after_create_failure(
            failure_class="fail",
            attempted_candidate_id="pcie",
            ordered_candidate_ids=["pcie", "sxm"],
        )
        self.assertEqual(fatal, {"action": "fail", "reason": "provider_error"})

    def test_create_timeout_reconciliation_covers_absent_exact_and_invalid(self):
        self.assertEqual(
            controller.reconcile_create_timeout(
                expected_name="task-pod", attempted_candidate=self.pcie, task_pods=[]
            )["action"],
            "retry_create",
        )
        exact = controller.reconcile_create_timeout(
            expected_name="task-pod",
            attempted_candidate=self.pcie,
            task_pods=[_reconciliation_pod()],
        )
        self.assertEqual(exact["action"], "adopt_existing")
        invalid = controller.reconcile_create_timeout(
            expected_name="task-pod",
            attempted_candidate=self.pcie,
            task_pods=[_reconciliation_pod(gpu_count=0)],
        )
        self.assertEqual(invalid["action"], "delete_invalid_then_retry")

    def test_reconciliation_blocks_duplicates_and_multiple_running_gpu_pods(self):
        duplicate = _reconciliation_pod()
        second = dict(duplicate, id="pod-2")
        with self.assertRaisesRegex(
            controller.CandidateControllerError, "duplicate_create_name_matches"
        ):
            controller.reconcile_create_timeout(
                expected_name="task-pod",
                attempted_candidate=self.pcie,
                task_pods=[duplicate, second],
            )
        running_one = _reconciliation_pod(name="first", running=True)
        running_two = dict(_reconciliation_pod(name="second", running=True), id="pod-2")
        with self.assertRaisesRegex(
            controller.CandidateControllerError, "multiple_running_gpu_pods"
        ):
            controller.ensure_at_most_one_running_gpu_pod([running_one, running_two])


if __name__ == "__main__":
    unittest.main()
