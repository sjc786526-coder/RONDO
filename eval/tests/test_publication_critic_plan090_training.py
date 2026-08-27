from __future__ import annotations

import copy
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training.contract import (  # noqa: E402
    FullModelTrainingError,
    canonical_json_bytes,
    read_json,
    sha256_bytes,
)
from rondo_eval.publication_critic.full_model_training.data import (  # noqa: E402
    PortableTrainingDataset,
)
from rondo_eval.publication_critic.full_model_training.plan066_data import (  # noqa: E402
    ValidationDataset,
)
from rondo_eval.publication_critic.full_model_training.plan081_contract import (  # noqa: E402
    ComparisonPolicy,
    ControlPlan,
    TrainableScope,
)
from rondo_eval.publication_critic.full_model_training.plan081_observation import (  # noqa: E402
    training_identity_sha256,
)
from rondo_eval.publication_critic.full_model_training.plan082_environment import (  # noqa: E402
    ENVIRONMENT_SCHEMA,
)
from rondo_eval.publication_critic.full_model_training.plan090_adapter import (  # noqa: E402
    PRECISION_RECEIPT_SCHEMA,
    RUNTIME_KIND,
)
from rondo_eval.publication_critic.full_model_training.plan090_artifacts import (  # noqa: E402
    Plan090ArtifactStore,
)
from rondo_eval.publication_critic.full_model_training.plan090_contract import (  # noqa: E402
    BF16_PRIMARY_RUN,
    BF16_SECONDARY_RUN,
    DATA_BUNDLE_CONTENT_SHA256,
    FP32_CONTROL_RUN,
    SCOPE_PARAMETER_ELEMENTS,
    SCOPE_PARAMETER_NAMES,
    freeze_sha256,
    frozen_contract,
    materialize_run_spec,
    validate_budget_snapshot,
    validate_freeze,
)
from rondo_eval.publication_critic.full_model_training.plan090_controller import (  # noqa: E402
    Plan090ConfirmationController,
    validate_runtime_identity,
)
from rondo_eval.publication_critic.full_model_training.plan090_cli import (  # noqa: E402
    _authorize_run_boundary,
    _build_no_update_diagnostics,
    _diagnose,
    _preflight_run_outputs,
    _run_with_adapter as _cli_run_with_adapter,
)
from rondo_eval.publication_critic.full_model_training.plan090_finalize import (  # noqa: E402
    RECOVERY_RECEIPT_SCHEMA,
    assess_reproduction,
    finalize_run,
    finalize_terminal,
    next_action,
)

from eval.tests.test_publication_critic_plan081_training import (  # noqa: E402
    _FakeAdapter,
)

FREEZE_PATH = (
    REPO_ROOT / "training/publication-critic-plan090/confirmation-freeze-v1.json"
)
ROUTE_PATH = REPO_ROOT / "training/publication-critic-plan081/route-contract-v1.json"


def _inventory(dtype: str = "torch.bfloat16") -> dict:
    counts = [1] * (len(SCOPE_PARAMETER_NAMES) - 1)
    counts.append(SCOPE_PARAMETER_ELEMENTS - sum(counts))
    rows = [
        {"name": name, "elements": elements, "dtype": dtype}
        for name, elements in zip(SCOPE_PARAMETER_NAMES, counts)
    ]
    filler_count = 311 - len(rows)
    remaining = 1_720_577_024 - SCOPE_PARAMETER_ELEMENTS
    filler_elements = [1] * (filler_count - 1)
    filler_elements.append(remaining - sum(filler_elements))
    rows.extend(
        {
            "name": f"fixture.unselected.{index:03d}",
            "elements": elements,
            "dtype": dtype,
        }
        for index, elements in enumerate(filler_elements)
    )
    return {
        "parameter_tensors": len(rows),
        "parameter_elements": 1_720_577_024,
        "parameters": rows,
        "inventory_sha256": sha256_bytes(canonical_json_bytes(rows)),
    }


def _run_spec(run_id: str = BF16_PRIMARY_RUN) -> dict:
    dtype = "torch.float32" if run_id == FP32_CONTROL_RUN else "torch.bfloat16"
    return materialize_run_spec(frozen_contract(), run_id, _inventory(dtype))


def _environment() -> dict:
    distributions = ["torch==2.8.0", "transformers==4.52.3"]
    core = {
        "schema": ENVIRONMENT_SCHEMA,
        "container_image": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
        "python_version": "3.12.3",
        "python_implementation": "CPython",
        "python_executable_name": "python",
        "driver_version": "570.00",
        "torch_cuda_runtime": "12.8",
        "nvidia_smi_cuda_version": "12.8",
        "gpu_count": 1,
        "gpu_names": ["NVIDIA L40S"],
        "gpu_compute_capabilities": ["8.9"],
        "installed_distributions": distributions,
        "installed_distributions_sha256": sha256_bytes(
            ("\n".join(distributions) + "\n").encode()
        ),
    }
    return {**core, "content_sha256": sha256_bytes(canonical_json_bytes(core))}


def _runtime(spec: dict) -> dict:
    return {
        "runtime_kind": RUNTIME_KIND,
        "gpu_name": "NVIDIA L40S",
        "gpu_count": 1,
        "cuda_version": "12.8",
        "torch_version": "2.8.0+cu128",
        "transformers_version": "4.52.3",
        "model_repository": "Skywork/Skywork-Reward-V2-Qwen3-1.7B",
        "model_revision": "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc",
        "peft": False,
        "quantized_training": False,
        "snapshot_content_sha256": (
            "18d9edf7132d9c5e13bb0e59e3c2c6a42f82007fa17de464e20783755a171360"
        ),
        "recipe_sha256": sha256_bytes(canonical_json_bytes(spec["recipe"])),
        "parameter_inventory_sha256": spec["parameter_inventory_sha256"],
        "parameter_tensors": 311,
        "parameter_elements": 1_720_577_024,
        "environment": _environment(),
        "provider_pod_id": "fixture-pod-id",
        "provider_pod_name": "rondo-plan090-fixture",
        "precision_controls": {
            "float32_matmul_precision": "highest",
            "cuda_matmul_allow_tf32": False,
            "cudnn_allow_tf32": False,
            "autocast_enabled": False,
        },
        "repeat_semantics": {
            "recipe_seed_metadata": spec["recipe"]["seed"],
            "data_ordering": "sorted_candidates_and_frozen_pair_order",
            "data_shuffle": False,
            "attention_dropout": 0.0,
            "active_dropout_modules": [],
            "seed_sensitive_consumers": [],
            "seed_sensitive_stability_tested": False,
        },
    }


def _precision(spec: dict) -> dict:
    dtype = {
        "bfloat16": "torch.bfloat16",
        "float32": "torch.float32",
    }[spec["recipe"]["parameter_dtype"]]
    optimizer = [dtype] if dtype == "torch.float32" else [dtype, "torch.float32"]
    return {
        "schema": PRECISION_RECEIPT_SCHEMA,
        "parameter_dtype": spec["recipe"]["parameter_dtype"],
        "model_parameter_dtypes": [dtype],
        "selected_parameter_dtypes": {name: dtype for name in SCOPE_PARAMETER_NAMES},
        "gradient_dtypes": {name: dtype for name in SCOPE_PARAMETER_NAMES},
        "forward_output_dtypes": [dtype],
        "optimizer_state_dtypes": optimizer,
        "save_parameter_dtype": dtype,
        "save_verification": (
            "fail_closed_safetensors_header_before_checkpoint_publish_and_load"
        ),
        "controls": {
            "float32_matmul_precision": "highest",
            "cuda_matmul_allow_tf32": False,
            "cudnn_allow_tf32": False,
            "autocast_enabled": False,
        },
        "precision_contract": spec["precision_contract"],
    }


def _supervision(candidate_id: str, label: str, split: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "binary_label": label,
        "proposed_split": split,
        "slices": ["fixture"],
        "publication_class": "status",
        "completion_state": "complete",
        "actor_role": "producer",
        "hard_focus": "none",
        "length_bucket": "short",
        "style": "plain",
        "unicode": False,
    }


def _cohort(split: str) -> tuple[Any, dict[int, dict[str, float]]]:
    pair_counts = {"validation": (19, 7), "train": (29, 29)}[split]
    expected_candidates = 55 if split == "validation" else 128
    supervision: dict[str, dict] = {}
    packets: dict[str, dict] = {}
    pairs: dict[str, dict] = {}
    base: dict[str, float] = {}
    candidate: dict[str, float] = {}
    pair_index = 0
    for kind, count in zip(("boundary", "within_pass"), pair_counts):
        for index in range(count):
            preferred = f"{split}-{kind}-{index}-preferred"
            dispreferred = f"{split}-{kind}-{index}-dispreferred"
            pair_id = f"{split}-{kind}-{index}"
            for candidate_id, label in (
                (preferred, "PASS"),
                (dispreferred, "REWRITE"),
            ):
                supervision[candidate_id] = _supervision(candidate_id, label, split)
                packets[candidate_id] = {"candidate_id": candidate_id, "packet": {}}
            pairs[pair_id] = {
                "pair_id": pair_id,
                "kind": kind,
                "target_dimension": "fixture",
                "preferred_candidate_id": preferred,
                "dispreferred_candidate_id": dispreferred,
            }
            margin = 1.0
            if split == "validation" and kind == "boundary":
                if index < 7:
                    margin += 0.015625
                elif index < 10:
                    margin -= 0.015625
            elif split == "validation" and kind == "within_pass":
                if index < 4:
                    margin += 0.001
                elif index == 4:
                    margin -= 0.001
            base[preferred], base[dispreferred] = 0.5, -0.5
            candidate[preferred], candidate[dispreferred] = margin / 2, -margin / 2
            pair_index += 1
    while len(supervision) < expected_candidates:
        index = len(supervision)
        candidate_id = f"{split}-extra-{index}"
        label = "PASS" if index % 2 == 0 else "REWRITE"
        supervision[candidate_id] = _supervision(candidate_id, label, split)
        packets[candidate_id] = {"candidate_id": candidate_id, "packet": {}}
        score = 2.0 if label == "PASS" else -2.0
        base[candidate_id] = candidate[candidate_id] = score
    if split == "validation":
        dataset = ValidationDataset(
            input_identity={"fixture": split},
            rubric="fixture rubric",
            packets=packets,
            supervision=supervision,
            pairs=pairs,
        )
    else:
        dataset = PortableTrainingDataset(
            dataset_revision="v8",
            input_identity={"fixture": split},
            rubric="fixture rubric",
            packets=packets,
            supervision=supervision,
            pairs=pairs,
            membership={
                "schema_version": 1,
                "dataset_revision": "v8",
                "stages": {
                    "fixture": {
                        "candidate_ids": sorted(supervision),
                        "pair_ids": sorted(pairs),
                    }
                },
            },
        )
    return dataset, {0: base, 1: candidate}


class _Plan090FakeAdapter(_FakeAdapter):
    def __init__(self, spec: dict, validation_logits: dict, train_logits: dict):
        super().__init__(validation_logits, codec_id="plan090-fixture-v1")
        self.spec = spec
        self.train_logits = train_logits

    def plan090_runtime_identity(self) -> dict:
        return _runtime(self.spec)

    def close(self) -> None:
        return None

    def evaluate_training(self, dataset: PortableTrainingDataset) -> dict:
        return {
            "raw_logits": dict(self.train_logits[self.step]),
            "gradient_access": False,
            "training_state_unchanged": True,
            "training_identity_sha256": training_identity_sha256(dataset),
        }

    def apply_update(self, step, scope, training_dataset):
        receipt = super().apply_update(step, scope, training_dataset)
        receipt["parameter_change"] = {
            "method": "torch.equal_any_nonzero_gradient_parameter_cpu_snapshots",
            "parameter_name": scope.parameter_names[0],
            "parameter_elements": 1,
            "maximum_absolute_change": 0.01,
        }
        receipt["precision_receipt"] = _precision(self.spec)
        return receipt

    @contextmanager
    def checkpoint_recovery_probe(self):
        with super().checkpoint_recovery_probe() as probe:
            probe.plan090_runtime_identity = self.plan090_runtime_identity
            yield probe


def _budget(*, projected: float = 0.5, cost: float = 0.0) -> dict:
    return {
        "schema": "rondo-publication-critic-plan090-budget-snapshot-v1",
        "captured_at": "2026-08-26T12:00:00Z",
        "live_balance_usd": 7.88,
        "known_unsettled_usd": 0.25,
        "stage_b_baseline_balance_usd": 7.88,
        "stage_b_baseline_known_unsettled_usd": 0.25,
        "conservative_task_cost_usd": cost,
        "closure_reserve_usd": 0.5,
        "projected_complete_branch_usd": projected,
    }


def _recovery(run_id: str, checkpoint_id: str, checkpoint_sha: str) -> dict:
    return {
        "schema": RECOVERY_RECEIPT_SCHEMA,
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,
        "checkpoint_sha256": checkpoint_sha,
        "freeze_sha256": freeze_sha256(frozen_contract()),
        "source_process_id": "1" * 32,
        "recovery_process_id": "2" * 32,
        "fresh_adapter": True,
        "model_loaded": True,
        "optimizer_scheduler_rng_data_equal": True,
        "no_update": True,
        "checkpoint_reuse_verified": True,
    }


class Plan090TrainingTests(unittest.TestCase):
    def test_tracked_freeze_is_exact_and_pre_result_complete(self) -> None:
        value = read_json(FREEZE_PATH)
        self.assertEqual(validate_freeze(value), frozen_contract())
        self.assertEqual(value["branch_order"][-1], FP32_CONTROL_RUN)
        self.assertEqual(value["repeat_semantics"]["seed_sensitive_consumers"], [])
        self.assertFalse(value["claims"]["seed_sensitive_stability_tested"])
        self.assertEqual(value["scope"]["parameter_names"], list(SCOPE_PARAMETER_NAMES))
        self.assertEqual(
            value["historical_reference"]["delta"]["raw_boundary_pair_mean_margin"],
            0.00390625,
        )
        drifted = copy.deepcopy(value)
        drifted["rubric"]["minimum_raw_boundary_delta"] = 0.0
        with self.assertRaisesRegex(FullModelTrainingError, "plan090_freeze_drifted"):
            validate_freeze(drifted)

    def test_run_specs_bind_exact_scope_dtype_and_independent_namespaces(self) -> None:
        primary = _run_spec()
        secondary = _run_spec(BF16_SECONDARY_RUN)
        fp32 = _run_spec(FP32_CONTROL_RUN)
        self.assertEqual(
            primary["scope"]["parameter_names"], list(SCOPE_PARAMETER_NAMES)
        )
        self.assertNotEqual(
            primary["artifact_namespace"], secondary["artifact_namespace"]
        )
        self.assertEqual(fp32["recipe"]["parameter_dtype"], "float32")
        self.assertEqual(
            secondary["repeat_semantics"]["bf16_run_kind"],
            "independent_clean_repeat_with_distinct_seed_metadata",
        )
        self.assertFalse(
            secondary["repeat_semantics"]["seed_sensitive_stability_tested"]
        )
        drifted_runtime = _runtime(secondary)
        drifted_runtime["repeat_semantics"]["seed_sensitive_stability_tested"] = True
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan090_runtime_identity_invalid"
        ):
            validate_runtime_identity(drifted_runtime, run_spec=secondary)
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan090_scope_dtype_mismatch"
        ):
            materialize_run_spec(
                frozen_contract(), BF16_PRIMARY_RUN, _inventory("torch.float32")
            )
        drifted = _inventory()
        drifted["parameters"].append(
            {"name": "fixture.extra", "elements": 7, "dtype": "torch.bfloat16"}
        )
        drifted["parameter_tensors"] += 1
        drifted["parameter_elements"] += 7
        identity = [
            {"name": row["name"], "elements": row["elements"], "dtype": row["dtype"]}
            for row in drifted["parameters"]
        ]
        drifted["inventory_sha256"] = sha256_bytes(canonical_json_bytes(identity))
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan090_parameter_inventory_invalid"
        ):
            materialize_run_spec(frozen_contract(), BF16_PRIMARY_RUN, drifted)

    def test_start_boundary_binds_branch_budget_and_actual_namespace(self) -> None:
        contract = frozen_contract()
        primary = _run_spec()
        budget = validate_budget_snapshot(_budget())
        _authorize_run_boundary(
            SimpleNamespace(prior_run_result=[]),
            recovery=False,
            contract=contract,
            spec=primary,
            budget=budget,
        )
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan090_run_branch_not_authorized"
        ):
            _authorize_run_boundary(
                SimpleNamespace(prior_run_result=[]),
                recovery=False,
                contract=contract,
                spec=_run_spec(BF16_SECONDARY_RUN),
                budget=budget,
            )
        with tempfile.TemporaryDirectory() as directory:
            task = Path(directory) / "rondo-plan090-fixture"
            task.mkdir()
            expected = task / primary["artifact_namespace"] / "artifacts"
            args = SimpleNamespace(
                artifact_root=expected,
                state_output=task / "state.json",
                process_receipt_output=task / "process.json",
            )
            with patch.dict(os.environ, {"RONDO_PLAN090_TASK_ROOT": str(task)}):
                _preflight_run_outputs(args, recovery=False, run_spec=primary)
                args.artifact_root = task / "formal/wrong/artifacts"
                with self.assertRaisesRegex(
                    FullModelTrainingError, "plan090_artifact_namespace_mismatch"
                ):
                    _preflight_run_outputs(args, recovery=False, run_spec=primary)

    def test_budget_is_conservative_idempotent_and_complete_branch_gated(self) -> None:
        result = validate_budget_snapshot(_budget(projected=5.9, cost=0.25))
        self.assertEqual(result["safe_available_usd"], 6.0)
        self.assertEqual(result["action_headroom_usd"], 5.75)
        self.assertFalse(result["complete_branch_authorized"])
        self.assertEqual(validate_budget_snapshot(result), result)
        delayed = _budget(cost=0.5)
        delayed["live_balance_usd"] = 6.88
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan090_budget_cost_floor_violated"
        ):
            validate_budget_snapshot(delayed)
        malformed = dict(_budget())
        malformed["extra"] = 1
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan090_budget_snapshot_invalid"
        ):
            validate_budget_snapshot(malformed)

    def test_base_and_legacy_no_update_diagnostics_share_objective_schema(self) -> None:
        contract = frozen_contract()
        spec = _run_spec()
        validation, validation_logits = _cohort("validation")
        training, train_logits = _cohort("train")
        datasets = SimpleNamespace(train=training, validation=validation)
        scope = TrainableScope.from_value(spec["scope"])
        adapters = [
            _Plan090FakeAdapter(spec, validation_logits, train_logits),
            _Plan090FakeAdapter(spec, validation_logits, train_logits),
        ]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / "rondo-plan090-fixture"
            task.mkdir()
            freeze_path = task / "freeze.json"
            spec_path = task / "spec.json"
            freeze_path.write_bytes(canonical_json_bytes(contract))
            spec_path.write_bytes(canonical_json_bytes(spec))
            checkpoint_id = Path(contract["legacy_checkpoint"]["relative_path"]).name
            checkpoint_path = (
                base
                / "rondo-plan087-history"
                / "route-o-artifacts"
                / "recovery-checkpoints"
                / checkpoint_id
            )
            payload = checkpoint_path / "payload"
            payload.mkdir(parents=True)
            (payload / "fake-model.json").write_text(
                '{"scope": null, "step": 0}', encoding="utf-8"
            )
            checkpoint = {
                "bytes": contract["legacy_checkpoint"]["bytes"],
                "content_sha256": contract["legacy_checkpoint"]["content_sha256"],
            }
            common = {
                "freeze": freeze_path,
                "run_spec": spec_path,
                "data_bundle": task / "data-bundle",
                "snapshot": task / "snapshot",
                "model_lock": task / "model-lock.json",
            }
            arguments = [
                SimpleNamespace(
                    **common,
                    role="exact_base",
                    legacy_checkpoint=None,
                    output=task / "exact-base.json",
                ),
                SimpleNamespace(
                    **common,
                    role="legacy_route_o",
                    legacy_checkpoint=checkpoint_path,
                    output=task / "legacy-route-o.json",
                ),
            ]
            module = "rondo_eval.publication_critic.full_model_training.plan090_cli"
            with (
                patch.dict(os.environ, {"RONDO_PLAN090_TASK_ROOT": str(task)}),
                patch(
                    f"{module}.verify_data_bundle",
                    return_value={"content_sha256": DATA_BUNDLE_CONTENT_SHA256},
                ),
                patch(f"{module}.load_plan066_datasets", return_value=datasets),
                patch(f"{module}._new_adapter", side_effect=adapters),
                patch.object(
                    Plan090ArtifactStore,
                    "verify_checkpoint",
                    return_value=checkpoint,
                ),
            ):
                observed = [_diagnose(args) for args in arguments]
            self.assertEqual(
                [row["role"] for row in observed],
                ["exact_base", "legacy_route_o"],
            )
            for result, adapter in zip(observed, adapters):
                self.assertTrue(result["no_update"])
                self.assertEqual(adapter.update_calls, 0)
                for observation in (
                    result["validation_observation"],
                    result["train_observation"],
                ):
                    objective = observation["objective_diagnostic"]
                    self.assertEqual(
                        objective["schema"],
                        "rondo-publication-critic-plan090-objective-diagnostic-v1",
                    )
                    self.assertFalse(objective["gradient_access"])
                    self.assertEqual(
                        set(objective["component_mean_loss"]),
                        {"binary", "boundary", "within_pass"},
                    )
            self.assertEqual(
                observed[0]["validation_observation"]["objective_diagnostic"],
                observed[1]["validation_observation"]["objective_diagnostic"],
            )
            self.assertEqual(
                observed[0]["train_observation"]["objective_diagnostic"],
                observed[1]["train_observation"]["objective_diagnostic"],
            )

        drifted_adapter = _Plan090FakeAdapter(spec, validation_logits, train_logits)
        drifted_adapter.wrong_validation_identity = True
        with self.assertRaisesRegex(
            FullModelTrainingError,
            "plan090_no_update_diagnostic_receipt_invalid",
        ):
            _build_no_update_diagnostics(
                adapter=drifted_adapter,
                datasets=datasets,
                spec=spec,
                scope=scope,
            )

    def test_same_scorer_train_diagnostic_and_frozen_rubric_pass_and_no_go(
        self,
    ) -> None:
        spec = _run_spec()
        validation, validation_logits = _cohort("validation")
        training, train_logits = _cohort("train")
        with tempfile.TemporaryDirectory() as directory:
            store = Plan090ArtifactStore(Path(directory))
            adapter = _Plan090FakeAdapter(spec, validation_logits, train_logits)
            controller = Plan090ConfirmationController(
                freeze=frozen_contract(),
                run_spec=spec,
                launch_budget_snapshot=validate_budget_snapshot(_budget()),
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                initial_scope=TrainableScope.from_value(spec["scope"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=store,
                report_threshold=spec["report_threshold"],
            )
            controller.begin_process(
                {"instance_id": "1" * 32, "hostname": "fixture-a", "pid": 1}
            )
            controller.initialize(adapter)
            controller.run(adapter)
            self.assertEqual(controller.state["status"], "completed")
            self.assertEqual(
                len(controller.state["plan090"]["training_observations"]), 2
            )
            checkpoint_id = controller.state["latest_checkpoint_id"]
            first = finalize_run(
                freeze=frozen_contract(),
                controller_state=controller.state,
                artifact_root=Path(directory),
                selected_checkpoint_id=checkpoint_id,
            )
            self.assertTrue(first["assessment"]["passed"])
            self.assertIn(
                "objective_weighted", first["assessment"]["validation"]["deltas"]
            )
            self.assertIn("objective_boundary", first["assessment"]["train"]["deltas"])
            self.assertFalse(first["selected_checkpoint"]["fresh_process_recovery"])

            candidate_validation = copy.deepcopy(
                first["candidate_validation_observation"]
            )
            candidate_validation["pair_margins"] = copy.deepcopy(
                first["base_validation_observation"]["pair_margins"]
            )
            candidate_validation["metrics"] = copy.deepcopy(
                first["base_validation_observation"]["metrics"]
            )
            candidate_validation["operating_curve"] = copy.deepcopy(
                first["base_validation_observation"]["operating_curve"]
            )
            negative = assess_reproduction(
                frozen_contract(),
                base_validation=first["base_validation_observation"],
                candidate_validation=candidate_validation,
                base_train=first["base_train_observation"],
                candidate_train=first["candidate_train_observation"],
            )
            self.assertFalse(negative["passed"])
            self.assertFalse(negative["checks"]["raw_boundary_direction"])

    def test_different_process_recovery_binds_final_checkpoint(self) -> None:
        spec = _run_spec()
        validation, validation_logits = _cohort("validation")
        training, train_logits = _cohort("train")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Plan090ArtifactStore(root)
            first_adapter = _Plan090FakeAdapter(spec, validation_logits, train_logits)
            controller = Plan090ConfirmationController(
                freeze=frozen_contract(),
                run_spec=spec,
                launch_budget_snapshot=validate_budget_snapshot(_budget()),
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                initial_scope=TrainableScope.from_value(spec["scope"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=store,
                report_threshold=spec["report_threshold"],
            )
            controller.begin_process(
                {"instance_id": "1" * 32, "hostname": "fixture-a", "pid": 1}
            )
            controller.initialize(first_adapter)
            controller.run(first_adapter)
            checkpoint_id = controller.state["latest_checkpoint_id"]
            checkpoint = store.verify_checkpoint(checkpoint_id)

            recovery_adapter = _Plan090FakeAdapter(
                spec, validation_logits, train_logits
            )
            recovered = Plan090ConfirmationController.resume(
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=store,
                adapter=recovery_adapter,
                checkpoint_id=checkpoint_id,
                report_threshold=spec["report_threshold"],
            )
            recovered.begin_process(
                {"instance_id": "2" * 32, "hostname": "fixture-a", "pid": 2}
            )
            recovered.record_new_process_recovery(
                checkpoint_id, checkpoint["content_sha256"]
            )
            recovered.run(recovery_adapter, stop_after=1)
            result = finalize_run(
                freeze=frozen_contract(),
                controller_state=recovered.state,
                artifact_root=root,
                selected_checkpoint_id=checkpoint_id,
                recovery_receipt=_recovery(
                    BF16_PRIMARY_RUN, checkpoint_id, checkpoint["content_sha256"]
                ),
            )
            self.assertTrue(result["selected_checkpoint"]["fresh_process_recovery"])
            self.assertEqual(recovery_adapter.update_calls, 0)

    def test_process_receipt_precedes_an_interrupted_training_update(self) -> None:
        spec = _run_spec()
        validation, validation_logits = _cohort("validation")
        training, train_logits = _cohort("train")
        adapter = _Plan090FakeAdapter(spec, validation_logits, train_logits)
        adapter.invalid_receipt_steps.add(1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(
                artifact_root=root / "formal-artifacts",
                state_output=root / "state.json",
                process_receipt_output=root / "process.json",
            )
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_update_receipt_invalid"
            ):
                _cli_run_with_adapter(
                    args,
                    recovery=False,
                    source={"commit": "a" * 40},
                    contract=frozen_contract(),
                    spec=spec,
                    data={"content_sha256": "b" * 64},
                    datasets=SimpleNamespace(train=training, validation=validation),
                    route=read_json(ROUTE_PATH),
                    adapter=adapter,
                    budget=validate_budget_snapshot(_budget()),
                )
            process = read_json(args.process_receipt_output)
            self.assertEqual(process["global_step"], 0)
            self.assertFalse(args.state_output.exists())

    def test_branch_order_negative_stop_fp32_budget_and_terminal_zero_pod(self) -> None:
        passed = _completed_result(BF16_PRIMARY_RUN, recovered=False)
        negative = _negative_result(passed)
        self.assertEqual(
            next_action(frozen_contract(), [negative])["outcome"],
            "ROUTE_O_CONFIRMATION_NO_GO",
        )
        self.assertEqual(
            next_action(frozen_contract(), [passed])["run_id"],
            BF16_SECONDARY_RUN,
        )
        second = _completed_result(BF16_SECONDARY_RUN, recovered=True)
        self.assertEqual(
            next_action(
                frozen_contract(),
                [passed, second],
                fp32_budget_snapshot=_budget(),
            )["run_id"],
            FP32_CONTROL_RUN,
        )
        low = _budget(projected=1.0, cost=5.5)
        decision = next_action(
            frozen_contract(), [passed, second], fp32_budget_snapshot=low
        )
        self.assertEqual(decision["outcome"], "ROUTE_O_CONFIRMATION_PASS")
        terminal = finalize_terminal(
            freeze=frozen_contract(),
            run_results=[passed, second],
            outcome="ROUTE_O_CONFIRMATION_PASS",
            reason="both BF16 clean repeats passed; FP32 closure did not fit",
            resource_state={
                "captured_at": "2026-08-26T13:00:00Z",
                "pod_count": 0,
                "compute_rate_usd_per_hour": 0,
                "volume": {
                    "id": "mwemzrn33y",
                    "region": "US-TX-3",
                    "size_gb": 57,
                    "deleted": False,
                },
            },
            terminal_budget_snapshot=_budget(projected=0.0, cost=5.5),
            fp32_budget_snapshot=low,
        )
        self.assertEqual(terminal["resource_state"]["pod_count"], 0)
        self.assertTrue(
            terminal["claims"]["route_o_repeated_on_same_validation_two_clean_runs"]
        )
        self.assertFalse(terminal["claims"]["seed_sensitive_stability_tested"])

        zero_projected = _budget(projected=0.0)
        self.assertEqual(
            next_action(
                frozen_contract(),
                [passed, second],
                fp32_budget_snapshot=zero_projected,
            )["outcome"],
            "ROUTE_O_CONFIRMATION_PASS",
        )
        with self.assertRaisesRegex(
            FullModelTrainingError,
            "plan090_infrastructure_cannot_override_model_result",
        ):
            finalize_terminal(
                freeze=frozen_contract(),
                run_results=[passed, second],
                outcome="INCONCLUSIVE_INFRASTRUCTURE",
                reason="zero projected cost never authorizes an FP32 start",
                resource_state=terminal["resource_state"],
                terminal_budget_snapshot=_budget(projected=0.0),
                fp32_budget_snapshot=zero_projected,
            )

        fp32_infrastructure = finalize_terminal(
            freeze=frozen_contract(),
            run_results=[passed, second],
            outcome="INCONCLUSIVE_INFRASTRUCTURE",
            reason="exact Pod was lost before the authorized FP32 branch",
            resource_state=terminal["resource_state"],
            terminal_budget_snapshot=_budget(projected=0.0),
            fp32_budget_snapshot=_budget(),
        )
        self.assertEqual(
            fp32_infrastructure["fp32"]["status"],
            "incomplete_infrastructure",
        )
        self.assertTrue(fp32_infrastructure["claims"]["fp32_branch_incomplete"])
        self.assertTrue(
            fp32_infrastructure["claims"]["confirmation_closure_incomplete"]
        )

        unrecovered_second = _completed_result(BF16_SECONDARY_RUN, recovered=False)
        inconclusive = finalize_terminal(
            freeze=frozen_contract(),
            run_results=[passed, unrecovered_second],
            outcome="INCONCLUSIVE_INFRASTRUCTURE",
            reason="fresh-process recovery closure unavailable",
            resource_state=terminal["resource_state"],
            terminal_budget_snapshot=_budget(projected=0.0),
        )
        self.assertTrue(inconclusive["claims"]["positive_bf16_clean_repeats_observed"])
        self.assertTrue(inconclusive["claims"]["confirmation_closure_incomplete"])
        self.assertFalse(inconclusive["claims"]["model_question_unanswered"])
        fp32 = _completed_result(FP32_CONTROL_RUN, recovered=False)
        fp32_inconclusive = finalize_terminal(
            freeze=frozen_contract(),
            run_results=[passed, unrecovered_second, fp32],
            outcome="INCONCLUSIVE_INFRASTRUCTURE",
            reason="recovery closure failed after the diagnostic FP32 run",
            resource_state=terminal["resource_state"],
            terminal_budget_snapshot=_budget(projected=0.0),
        )
        self.assertTrue(fp32_inconclusive["claims"]["confirmation_closure_incomplete"])
        self.assertTrue(
            fp32_inconclusive["claims"][
                "route_o_repeated_on_same_validation_two_clean_runs"
            ]
        )
        with self.assertRaisesRegex(
            FullModelTrainingError,
            "plan090_infrastructure_cannot_override_model_result",
        ):
            finalize_terminal(
                freeze=frozen_contract(),
                run_results=[passed, second],
                outcome="INCONCLUSIVE_INFRASTRUCTURE",
                reason="completed confirmation cannot become inconclusive",
                resource_state=terminal["resource_state"],
                terminal_budget_snapshot=_budget(projected=0.0),
            )
        with self.assertRaisesRegex(
            FullModelTrainingError,
            "plan090_infrastructure_cannot_override_model_result",
        ):
            finalize_terminal(
                freeze=frozen_contract(),
                run_results=[negative],
                outcome="INCONCLUSIVE_INFRASTRUCTURE",
                reason="must not conceal a valid negative result",
                resource_state=terminal["resource_state"],
                terminal_budget_snapshot=_budget(projected=0.0),
            )

        drifted_second = copy.deepcopy(second)
        drifted_second["runtime_identity"]["provider_pod_id"] = "other-pod-id"
        core = {
            key: item for key, item in drifted_second.items() if key != "content_sha256"
        }
        drifted_second["content_sha256"] = sha256_bytes(canonical_json_bytes(core))
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan090_formal_pod_identity_drifted"
        ):
            finalize_terminal(
                freeze=frozen_contract(),
                run_results=[passed, drifted_second],
                outcome="ROUTE_O_CONFIRMATION_PASS",
                reason="fixture provider Pod drift",
                resource_state=terminal["resource_state"],
                terminal_budget_snapshot=_budget(projected=0.0, cost=5.5),
                fp32_budget_snapshot=low,
            )

        decreasing = copy.deepcopy(second)
        decreasing["launch_budget_snapshot"] = validate_budget_snapshot(
            _budget(cost=1.0)
        )
        core = {
            key: item for key, item in decreasing.items() if key != "content_sha256"
        }
        decreasing["content_sha256"] = sha256_bytes(canonical_json_bytes(core))
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan090_budget_cost_decreased"
        ):
            finalize_terminal(
                freeze=frozen_contract(),
                run_results=[passed, decreasing],
                outcome="ROUTE_O_CONFIRMATION_PASS",
                reason="fixture cost reset",
                resource_state=terminal["resource_state"],
                terminal_budget_snapshot=_budget(projected=0.0, cost=0.5),
                fp32_budget_snapshot=low,
            )
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan090_terminal_run_binding_invalid"
        ):
            finalize_terminal(
                freeze=frozen_contract(),
                run_results=[second],
                outcome="INCONCLUSIVE_INFRASTRUCTURE",
                reason="fixture ordering drift",
                resource_state=terminal["resource_state"],
                terminal_budget_snapshot=_budget(projected=0.0),
            )


def _completed_result(run_id: str, *, recovered: bool) -> dict:
    spec = _run_spec(run_id)
    validation, validation_logits = _cohort("validation")
    training, train_logits = _cohort("train")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        store = Plan090ArtifactStore(root)
        adapter = _Plan090FakeAdapter(spec, validation_logits, train_logits)
        controller = Plan090ConfirmationController(
            freeze=frozen_contract(),
            run_spec=spec,
            launch_budget_snapshot=validate_budget_snapshot(_budget()),
            route_contract=read_json(ROUTE_PATH),
            control_plan=ControlPlan.from_value(spec["control_plan"]),
            initial_scope=TrainableScope.from_value(spec["scope"]),
            comparison_policy=ComparisonPolicy.from_value(spec["comparison_policy"]),
            training_dataset=training,
            validation_dataset=validation,
            artifact_store=store,
            report_threshold=spec["report_threshold"],
        )
        controller.begin_process(
            {"instance_id": "1" * 32, "hostname": "fixture-a", "pid": 1}
        )
        controller.initialize(adapter)
        controller.run(adapter)
        checkpoint_id = controller.state["latest_checkpoint_id"]
        receipt = None
        if recovered:
            checkpoint = store.verify_checkpoint(checkpoint_id)
            recovery_adapter = _Plan090FakeAdapter(
                spec, validation_logits, train_logits
            )
            controller = Plan090ConfirmationController.resume(
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=store,
                adapter=recovery_adapter,
                checkpoint_id=checkpoint_id,
                report_threshold=spec["report_threshold"],
            )
            controller.begin_process(
                {"instance_id": "2" * 32, "hostname": "fixture-a", "pid": 2}
            )
            controller.record_new_process_recovery(
                checkpoint_id, checkpoint["content_sha256"]
            )
            controller.run(recovery_adapter, stop_after=1)
            receipt = _recovery(run_id, checkpoint_id, checkpoint["content_sha256"])
        return finalize_run(
            freeze=frozen_contract(),
            controller_state=controller.state,
            artifact_root=root,
            selected_checkpoint_id=checkpoint_id,
            recovery_receipt=receipt,
        )


def _negative_result(value: dict) -> dict:
    result = copy.deepcopy(value)
    result["candidate_validation_observation"]["pair_margins"] = copy.deepcopy(
        result["base_validation_observation"]["pair_margins"]
    )
    result["candidate_validation_observation"]["metrics"] = copy.deepcopy(
        result["base_validation_observation"]["metrics"]
    )
    result["candidate_validation_observation"]["operating_curve"] = copy.deepcopy(
        result["base_validation_observation"]["operating_curve"]
    )
    result["assessment"] = assess_reproduction(
        frozen_contract(),
        base_validation=result["base_validation_observation"],
        candidate_validation=result["candidate_validation_observation"],
        base_train=result["base_train_observation"],
        candidate_train=result["candidate_train_observation"],
    )
    core = {key: item for key, item in result.items() if key != "content_sha256"}
    result["content_sha256"] = sha256_bytes(canonical_json_bytes(core))
    return result


if __name__ == "__main__":
    unittest.main()
