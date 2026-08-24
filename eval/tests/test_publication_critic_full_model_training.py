import io
import inspect
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training import bundle  # noqa: E402
from rondo_eval.publication_critic.full_model_training import checkpoint  # noqa: E402
from rondo_eval.publication_critic.full_model_training import contract  # noqa: E402
from rondo_eval.publication_critic.full_model_training import finalize  # noqa: E402
from rondo_eval.publication_critic.full_model_training import runner  # noqa: E402
from rondo_eval.publication_critic.full_model_training import __main__ as cli  # noqa: E402
from rondo_eval.publication_critic.full_model_training.objective import (  # noqa: E402
    binary_loss,
    binary_reference,
    extract_raw_scalar,
    pair_loss,
    pair_reference,
)


MODEL_CONTRACT_PATH = (
    REPO_ROOT / "training/publication-critic-plan060/model-contract-v1.json"
)
RECIPE_PATH = REPO_ROOT / "training/publication-critic-plan060/recipe-candidate-v1.json"


class _Device:
    type = "cuda"
    index = 0


class _Parameter:
    def __init__(self, count: int, *, requires_grad: bool = True) -> None:
        self._count = count
        self.requires_grad = requires_grad
        self.dtype = "torch.bfloat16"
        self.device = _Device()

    def numel(self) -> int:
        return self._count

    @staticmethod
    def is_floating_point() -> bool:
        return True


class _Model:
    def __init__(self, rows):
        self.rows = rows

    def named_parameters(self):
        return iter(self.rows)


def _runtime_prepare() -> dict:
    return {
        "runtime_prepare_seconds": 1.0,
        "heavy_import_seconds": 0.1,
        "tokenizer_load_seconds": 0.2,
        "model_load_seconds": 0.3,
        "data_tokenization_seconds": 0.1,
        "optimizer_init_seconds": 0.1,
        "optimizer_numerics_preflight_seconds": 0.1,
        "optimizer_numerics_preflight": {
            "schema": "rondo-flashadamw-global-numerics-preflight-v1",
            "check_numerics": True,
            "recompute_param_stats_called": True,
            "parameter_tensors_checked": 313,
            "configured_learning_rate": 4e-4,
            "failed_parameter_tensors": 0,
            "required_power_of_two_learning_rate": 4e-4,
            "all_parameters_passed": True,
            "elapsed_seconds": 0.1,
        },
    }


def _start_timing() -> dict:
    return {
        "process_startup_seconds": 1.0,
        "runtime_prepare": _runtime_prepare(),
        "first_step_jit_cold_seconds": 2.0,
        "steady_stage_step_seconds": {"C2": 1.0, "C3": 1.1},
        "optimizer_pre_checkpoint_seconds": 0.2,
        "checkpoint_save_seconds": 3.0,
        "process_elapsed_through_checkpoint_seconds": 8.0,
    }


def _resume_timing() -> dict:
    return {
        "process_startup_seconds": 1.0,
        "runtime_prepare": _runtime_prepare(),
        "checkpoint_verify_seconds": 0.2,
        "checkpoint_model_load_seconds": 0.3,
        "checkpoint_state_load_seconds": 0.4,
        "optimizer_scheduler_rng_restore_seconds": 0.1,
        "resume_verify_load_restore_seconds": 2.0,
        "continued_step_seconds": 1.1,
        "process_elapsed_through_continue_seconds": 4.0,
    }


def _compressed_state_evidence(entries: int = 313) -> dict:
    keys = [
        "error_bits",
        "exp_avg::quantized",
        "exp_avg::scales",
        "exp_avg_sq::quantized",
        "exp_avg_sq::scales",
        "step",
    ]
    return {
        "state_entries": entries,
        "expected_state_entries": entries,
        "required_state_keys": keys,
        "required_key_counts": {key: entries for key in keys},
        "optimizer_parameter_references": entries,
        "optimizer_step": 3,
        "state_dtype_counts": {key: {} for key in keys},
        "parameter_shapes_checked": True,
        "compressed_moment_state_complete": True,
    }


def _runtime_state_evidence(entries: int = 313) -> dict:
    return {
        "state_entries": entries,
        "expected_state_entries": entries,
        "optimizer_step": 3,
        "error_bits_dtype": "torch.int16",
        "moment_and_error_shapes_match_parameters": True,
    }


def _process(pid: int, instance_id: str) -> dict:
    return {
        "instance_id": instance_id,
        "pid": pid,
        "parent_pid": 1,
        "started_at": "2026-08-24T00:00:00Z",
    }


def _coverage() -> dict:
    count = 1_720_577_024
    return {
        "named_parameter_tensors": 313,
        "parameter_count": count,
        "floating_parameter_count": count,
        "trainable_parameter_count": count,
        "optimizer_parameter_tensors": 313,
        "optimizer_parameter_count": count,
        "dtype_counts": {"torch.bfloat16": count},
        "device_counts": {"cuda:0": count},
        "parameter_order_sha256": "c" * 64,
        "all_requires_grad": True,
        "optimizer_exact_coverage": True,
    }


def _winner_lock(selected_gpu: str = "NVIDIA H100 PCIe") -> dict:
    return {
        "schema": runner.WINNER_LOCK_SCHEMA,
        "locked_at": "2026-08-24T06:00:00Z",
        "selected_gpu": selected_gpu,
        "pod": {
            "id": "winner-pod",
            "name": "rondo-plan060-winner-training",
        },
        "evidence": {
            "selected_gpu_facts": {"gpu_id": selected_gpu},
            "network_volume_id": "volume-winner",
        },
    }


def _winner_identity(selected_gpu: str = "NVIDIA H100 PCIe") -> dict:
    return {
        "winner_lock_sha256": "e" * 64,
        "selected_gpu": selected_gpu,
        "winner_lock": _winner_lock(selected_gpu),
        "hardware": {
            "device_count": 1,
            "device_name": selected_gpu,
            "selected_gpu": selected_gpu,
        },
    }


def _provider_terminal_facts(identity: dict | None = None) -> dict:
    identity = identity or _winner_identity("NVIDIA H100 80GB HBM3")
    selected_gpu = identity["selected_gpu"]
    winner_pod = identity["winner_lock"]["pod"]
    retained_volume = {
        "volume_id": "volume-winner",
        "volume_name": "rondo-plan060-winner-assets",
        "gpu_id": selected_gpu,
        "data_center_id": "US-NE-1",
        "storage_class": "STANDARD",
        "size_gb": 60,
        "terminal_state": "retained_canonical",
        "canonical_assets_verified": True,
    }
    return {
        "schema": finalize.PROVIDER_FACTS_SCHEMA,
        "captured_at": "2026-08-24T09:00:00Z",
        "provider_task": {
            "provider": "RunPod",
            "winner_lock_sha256": identity["winner_lock_sha256"],
            "selected_gpu": selected_gpu,
            "max_concurrent_task_gpu_count_observed": 1,
            "pod_chain": [
                {
                    "pod_id": "legacy-pcie",
                    "pod_name": "rondo-plan060-legacy-asset-source",
                    "gpu_id": "NVIDIA H100 PCIe",
                    "role": "asset_source",
                    "billing_window": {
                        "start_utc": "2026-08-24T04:07:42Z",
                        "end_utc": "2026-08-24T06:00:00Z",
                    },
                },
                {
                    "pod_id": winner_pod["id"],
                    "pod_name": winner_pod["name"],
                    "gpu_id": selected_gpu,
                    "role": "training",
                    "billing_window": {
                        "start_utc": "2026-08-24T06:00:00Z",
                        "end_utc": "2026-08-24T07:00:00Z",
                    },
                },
            ],
        },
        "billing": {
            "provider_bill_settled": True,
            "all_task_pods_and_volumes_included": True,
            "actual_plan060_cost_usd": 1.25,
            "task_pod_cost_usd": 1.20,
            "task_standard_network_volume_cost_usd": 0.05,
            "actual_gpu_hourly_rate_usd": 3.89,
            "account_current_spend_per_hr_usd": 0.07,
        },
        "resources": {
            "all_compute_pods_terminated": True,
            "task_gpu_active_cost_usd_per_hr": 0,
            "task_cpu_active_cost_usd_per_hr": 0,
            "task_standard_network_volumes": [
                {
                    "volume_id": "volume-pcie",
                    "volume_name": "rondo-plan060-pcie-assets",
                    "gpu_id": "NVIDIA H100 PCIe",
                    "data_center_id": "US-KS-2",
                    "storage_class": "STANDARD",
                    "size_gb": 60,
                    "terminal_state": "deleted",
                    "canonical_assets_verified": True,
                },
                retained_volume,
            ],
            "retained_canonical_winner_volume_id": retained_volume["volume_id"],
            "continuing_storage_cost_usd_per_hr": 0.07,
            "formal_remote_disk_peak_bytes": 10,
            "full_smoke_checkpoint_deleted": True,
            "retained_full_checkpoint_count": 0,
        },
        "m3_b1c_cost_projection_assumptions": {
            "m3_b1c_total_update_range": [10, 20],
            "retry_multiplier": 1.25,
            "non_step_overhead_seconds": 60.0,
            "storage_and_cleanup_upper_usd": 0.25,
            "basis": "bounded qualification-scale planning range",
        },
        "qualification_conclusion": {
            "recommendation": "GO_RECOMMENDED",
            "formal_training_complete": True,
            "reason_codes": ["formal_chain_complete"],
        },
    }


def _checkpoint_receipt(
    status: str,
    process: dict | None = None,
    *,
    identity: dict | None = None,
) -> dict:
    return {
        "schema": contract.CHECKPOINT_SCHEMA,
        "status": status,
        "checkpoint_manifest_sha256": "a" * 64,
        "identity_sha256": (
            contract.sha256_bytes(contract.canonical_json_bytes(identity))
            if identity is not None
            else "b" * 64
        ),
        "global_step": 3,
        "stage": "C3",
        "process": process or _process(1, "start"),
        "bytes": 1,
        "file_count": 4,
    }


class _StateTensor:
    def __init__(self, dtype: str, *, value: int | None = None) -> None:
        self.dtype = dtype
        self._value = value

    def item(self) -> int:
        if self._value is None:
            raise AssertionError("not a scalar")
        return self._value


def _stage(name: str, step: int) -> dict:
    component_items = {
        "C1": {"binary": 6},
        "C2": {"binary": 6, "boundary": 1},
        "C3": {"binary": 6, "boundary": 1, "within_pass": 1},
    }[name]
    representative_names = ("model.norm.weight", "score.weight")
    representative_gradients = {
        representative: {
            "finite": True,
            "nonzero": True,
            "nonzero_elements": 1,
            "numel": 2,
            "backward_calls": 1,
        }
        for representative in representative_names
    }
    return {
        "stage": name,
        "global_step": step,
        "optimizer_updates": 1,
        "component_items": component_items,
        "component_mean_loss": {component: 1.0 for component in component_items},
        "all_losses_finite": True,
        "component_gradient_contributions": {
            component: json.loads(json.dumps(representative_gradients))
            for component in component_items
        },
        "gradient": {"global_finite": True, "global_nonzero": True},
        "representative_updates": {
            representative: {
                "effective_master_changed": True,
                "bf16_visible_changed": False,
                "numel": 2,
            }
            for representative in representative_names
        },
        "post_update_finiteness": {
            "all_finite": True,
            "model_parameter_tensors": 313,
            "effective_master_tensors": 313,
            "optimizer_floating_state_tensors": 626,
            "optimizer_param_groups": 1,
            "optimizer_learning_rates": [4e-4],
            "scheduler_learning_rates": [4e-4],
        },
        "optimizer_step": step,
        "tokens": 10,
        "tokens_per_second": 10.0,
        "elapsed_seconds": 1.0,
    }


class FullModelObjectiveTests(unittest.TestCase):
    def test_binary_and_pair_directions_share_higher_is_better_scalar(self) -> None:
        pass_loss, pass_derivative = binary_reference(0.0, "PASS")
        rewrite_loss, rewrite_derivative = binary_reference(0.0, "REWRITE")
        pair_loss, preferred_derivative, dispreferred_derivative = pair_reference(0.0, 0.0)
        self.assertGreater(pass_loss, 0)
        self.assertGreater(rewrite_loss, 0)
        self.assertGreater(pair_loss, 0)
        self.assertLess(pass_derivative, 0)
        self.assertGreater(rewrite_derivative, 0)
        self.assertLess(preferred_derivative, 0)
        self.assertGreater(dispreferred_derivative, 0)
        self.assertLess(binary_reference(2.0, "PASS")[0], pass_loss)
        self.assertLess(binary_reference(-2.0, "REWRITE")[0], rewrite_loss)
        self.assertLess(pair_reference(2.0, -2.0)[0], pair_loss)

    def test_mini_autograd_objective_contract_and_raw_scalar_execute(self) -> None:
        torch = _mini_torch()
        with mock.patch.dict(sys.modules, {"torch": torch}):
            binary_scores = torch.tensor([0.0, 0.0], requires_grad=True)
            observed_binary = binary_loss(binary_scores, ["PASS", "REWRITE"])
            observed_binary.backward()
            self.assertTrue(torch.isfinite(observed_binary).all().item())
            self.assertLess(binary_scores.grad.values[0], 0)
            self.assertGreater(binary_scores.grad.values[1], 0)

            preferred = torch.tensor([0.0], requires_grad=True)
            dispreferred = torch.tensor([0.0], requires_grad=True)
            observed_pair = pair_loss(
                preferred, dispreferred, margin=0.0, temperature=1.0
            )
            observed_pair.backward()
            self.assertLess(preferred.grad.item(), 0)
            self.assertGreater(dispreferred.grad.item(), 0)

            logits = torch.tensor([[1.0], [-2.0]])
            self.assertEqual(extract_raw_scalar(logits).values, [1.0, -2.0])
            with self.assertRaisesRegex(
                contract.FullModelTrainingError, "model_scalar_nonfinite"
            ):
                extract_raw_scalar(torch.tensor([[float("nan")]]))

    def test_package_import_does_not_load_torch(self) -> None:
        source = (
            "import sys; "
            f"sys.path.insert(0, {str(EVAL_ROOT)!r}); "
            "import rondo_eval.publication_critic.full_model_training; "
            "assert 'torch' not in sys.modules"
        )
        completed = subprocess.run(
            [sys.executable, "-B", "-P", "-c", source],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class FullModelContractTests(unittest.TestCase):
    def test_tracked_runpod_scripts_parse_and_use_package_entrypoint(self) -> None:
        scripts = (
            REPO_ROOT
            / "training/publication-critic-plan060/runpod-bootstrap.sh",
            REPO_ROOT
            / "training/publication-critic-plan060/runpod-training-entrypoint.sh",
            REPO_ROOT
            / "training/publication-critic-plan060/runpod-launch.sh",
        )
        for script in scripts:
            subprocess.run(
                ["bash", "-n", str(script)],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            source = script.read_text(encoding="utf-8")
            self.assertNotIn("full_model_training.cli", source)
            if script.name == "runpod-launch.sh":
                self.assertIn("runpod-training-entrypoint.sh", source)
                self.assertIn("runpod-bootstrap.sh", source)
                self.assertIn("runpod-launch-worker.sh", source)
                self.assertIn("active.lock", source)
                self.assertIn("flock -n 9", source)
                self.assertIn('setsid bash "$worker"', source)
                self.assertNotIn("setsid bash -c", source)
                self.assertIn("formal-resume requires checkpoint", source)
                self.assertIn("require_persistent_path", source)
            else:
                self.assertIn("rondo_eval.publication_critic.full_model_training", source)
                self.assertIn("-B -P -m", source)
                self.assertIn("require_persistent_path", source)
            if script.name == "runpod-training-entrypoint.sh":
                self.assertIn("trap write_training_status EXIT", source)
                self.assertIn("RONDO_PLAN060_WINNER_LOCK", source)
                self.assertIn("--winner-lock", source)
                self.assertIn('mv "$temporary" "$RONDO_PLAN060_STATUS"', source)
            if script.name == "runpod-bootstrap.sh":
                self.assertIn('"$venv/bin/hf" download', source)
                self.assertNotIn('if [ ! -f "$model/model.safetensors" ]', source)

    def test_runpod_launch_worker_preserves_argv_and_fallback_status(self) -> None:
        worker = (
            REPO_ROOT
            / "training/publication-critic-plan060/runpod-launch-worker.sh"
        )
        subprocess.run(
            ["bash", "-n", str(worker)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            failed_status = root / "failed.json"
            failed = subprocess.run(
                [
                    "bash",
                    str(worker),
                    str(failed_status),
                    "bootstrap",
                    "bash",
                    "-c",
                    "exit 7",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(failed.returncode, 7)
            self.assertEqual(
                json.loads(failed_status.read_text(encoding="utf-8")),
                {
                    "status": "failed",
                    "mode": "bootstrap",
                    "exit_code": 7,
                    "code": "target_status_missing",
                },
            )

            owned_status = root / "owned.json"
            owned = subprocess.run(
                [
                    "bash",
                    str(worker),
                    str(owned_status),
                    "formal-start",
                    "bash",
                    "-c",
                    "printf '%s\\n' '{\"status\":\"completed\"}' > \"$1\"",
                    "target-writer",
                    str(owned_status),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(owned.returncode, 0, owned.stderr)
            self.assertEqual(
                json.loads(owned_status.read_text(encoding="utf-8")),
                {"status": "completed"},
            )

    def test_tracked_recipe_and_model_contract_are_exact(self) -> None:
        recipe = contract.validate_recipe(
            json.loads(RECIPE_PATH.read_text(encoding="utf-8")), require_frozen=True
        )
        model_contract = runner._validate_model_contract(
            json.loads(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
        )
        self.assertEqual(recipe["stage_order"], ["C1", "C2", "C3"])
        self.assertEqual(recipe["learning_rate"], 4e-4)
        # FlashAdamW 0.1.4 checks Adam at a 0.1 * LR minimum effective step.
        # Keep the candidate strictly above the latest real H100 gate rather
        # than weakening check_numerics or changing the optimizer route.
        self.assertGreater(recipe["learning_rate"] * 0.1, 3.114e-5)
        self.assertTrue(model_contract["optimizer"]["quantize"])
        self.assertTrue(model_contract["optimizer"]["fused"])
        self.assertTrue(model_contract["optimizer"]["global_numerics_preflight"])
        self.assertFalse(model_contract["optimizer"]["decouple_lr"])
        self.assertFalse(model_contract["optimizer"]["gradient_release"])
        self.assertEqual(model_contract["model"]["bos_token_id"], 151643)
        self.assertEqual(
            model_contract["route"]["allowed_hardware"],
            ["NVIDIA H100 PCIe", "NVIDIA H100 80GB HBM3"],
        )
        self.assertTrue(model_contract["route"]["winner_lock_required"])

    def test_loaded_model_contract_uses_exact_config_token_ids(self) -> None:
        model_contract = json.loads(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
        parameter = SimpleNamespace(
            numel=lambda: 1_720_577_024,
            requires_grad_=mock.Mock(),
        )
        model_class = type("Qwen3ForSequenceClassification", (), {})
        model = model_class()
        model.config = SimpleNamespace(
            model_type="qwen3",
            num_labels=1,
            pad_token_id=151654,
            eos_token_id=151645,
            bos_token_id=int("151643"),
        )
        model.parameters = lambda: iter((parameter,))

        runner._validate_loaded_model(model, model_contract)
        parameter.requires_grad_.assert_called_once_with(True)

        model.config.bos_token_id = None
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "loaded_model_contract_invalid"
        ):
            runner._validate_loaded_model(model, model_contract)

    def test_model_contract_rejects_candidate_order_or_missing_winner_lock(self) -> None:
        original = json.loads(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
        for name, mutate in (
            (
                "candidate_order",
                lambda value: value["route"]["allowed_hardware"].reverse(),
            ),
            (
                "winner_lock_required",
                lambda value: value["route"].update(winner_lock_required=False),
            ),
        ):
            changed = json.loads(json.dumps(original))
            mutate(changed)
            with self.subTest(name=name):
                with self.assertRaisesRegex(
                    contract.FullModelTrainingError,
                    "model_contract_identity_invalid",
                ):
                    runner._validate_model_contract(changed)

    def test_flashadamw_constructor_matches_0_1_4_without_gradient_release(self) -> None:
        captured = {}

        def fake_flash(parameters, **kwargs):
            captured["parameters"] = list(parameters)
            captured["kwargs"] = kwargs
            return object()

        recipe = json.loads(RECIPE_PATH.read_text(encoding="utf-8"))
        optimizer_contract = json.loads(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))[
            "optimizer"
        ]
        parameters = [object(), object()]
        runner._construct_flashadamw(
            fake_flash,
            iter(parameters),
            recipe=recipe,
            optimizer_contract=optimizer_contract,
        )
        self.assertEqual(captured["parameters"], parameters)
        self.assertNotIn("gradient_release", captured["kwargs"])
        self.assertEqual(
            {
                name: captured["kwargs"][name]
                for name in (
                    "quantize",
                    "fused",
                    "decouple_lr",
                    "master_weight_bits",
                    "compress_state_dict",
                    "check_numerics",
                )
            },
            {
                "quantize": True,
                "fused": True,
                "decouple_lr": False,
                "master_weight_bits": 32,
                "compress_state_dict": True,
                "check_numerics": True,
            },
        )

    def test_flashadamw_reexport_identity_uses_defining_module(self) -> None:
        flash_class = type("FlashAdamW", (), {})
        flash_class.__module__ = "flashoptim.optimizers"
        fake_module = SimpleNamespace(FlashAdamW=flash_class)
        model_contract = json.loads(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
        with (
            mock.patch.object(runner.importlib, "import_module", return_value=fake_module),
            mock.patch.object(runner.importlib.metadata, "version", return_value="0.1.4"),
        ):
            self.assertIs(runner._flashadamw_class(model_contract), flash_class)

    def test_flashadamw_numerics_error_uses_exact_public_and_defining_export(
        self,
    ) -> None:
        numerics_error = type("NumericsError", (RuntimeError,), {})
        numerics_error.__module__ = "flashoptim.optimizers"
        public_module = SimpleNamespace(NumericsError=numerics_error)
        defining_module = SimpleNamespace(NumericsError=numerics_error)
        model_contract = json.loads(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
        with (
            mock.patch.object(
                runner.importlib,
                "import_module",
                side_effect=[public_module, defining_module],
            ),
            mock.patch.object(runner.importlib.metadata, "version", return_value="0.1.4"),
        ):
            self.assertIs(
                runner._flashadamw_numerics_error_class(model_contract),
                numerics_error,
            )

    def test_dependency_contract_requires_complete_training_stack(self) -> None:
        packages = {
            name: "1"
            for name in (
                "torch",
                "transformers",
                "flashoptim",
                "safetensors",
                "triton",
                "tokenizers",
                "huggingface-hub",
                "numpy",
            )
        }
        identity = {
            "schema": contract.DEPENDENCY_SCHEMA,
            "status": "formal_frozen",
            "packages": packages,
            "python_version": "3.12.0",
            "cuda_version": "12.8",
            "container_image": "image@sha256:" + "a" * 64,
            "flashoptim": {
                "distribution": "flashoptim",
                "version": "1",
                "import_path": "flashoptim.FlashAdamW",
                "defining_module": "flashoptim.optimizers",
                "class": "FlashAdamW",
                "source_revision": "commit",
            },
            "complete_freeze_sha256": "b" * 64,
        }
        contract.validate_dependency_identity(identity, require_frozen=True)
        del identity["packages"]["triton"]
        with self.assertRaisesRegex(contract.FullModelTrainingError, "dependency_identity_invalid"):
            contract.validate_dependency_identity(identity, require_frozen=True)


class _MiniHookHandle:
    def __init__(self, hooks, callback) -> None:
        self.hooks = hooks
        self.callback = callback

    def remove(self) -> None:
        if self.callback in self.hooks:
            self.hooks.remove(self.callback)


class _MiniTensor:
    def __init__(
        self,
        values,
        *,
        shape=None,
        dtype="torch.float32",
        requires_grad=False,
        parents=(),
        backward_fn=None,
    ) -> None:
        self.values = [float(value) for value in values]
        self.shape = tuple(shape if shape is not None else (len(self.values),))
        self.dtype = dtype
        self.device = "cpu"
        self.requires_grad = requires_grad or any(parent.requires_grad for parent in parents)
        self._parents = tuple(parents)
        self._backward_fn = backward_fn or (lambda _gradient: None)
        self._grad_values = [0.0] * len(self.values)
        self._grad_touched = False
        self._hooks = []

    @property
    def grad(self):
        if not self._grad_touched:
            return None
        return _MiniTensor(self._grad_values, shape=self.shape, dtype=self.dtype)

    @grad.setter
    def grad(self, value) -> None:
        if value is None:
            self._grad_values = [0.0] * len(self.values)
            self._grad_touched = False
        else:
            self._grad_values = list(value.values)
            self._grad_touched = True

    def _accumulate(self, gradient) -> None:
        for index, value in enumerate(gradient):
            self._grad_values[index] += value
        self._grad_touched = True

    def add_external_gradient(self, gradient) -> None:
        contribution = _MiniTensor(gradient, shape=self.shape, dtype=self.dtype)
        for hook in tuple(self._hooks):
            hook(contribution)
        for index, value in enumerate(gradient):
            current = self._grad_values[index]
            if self.dtype == "torch.bfloat16" and abs(current) >= 128 and abs(value) < 1:
                continue
            self._grad_values[index] = current + value
        self._grad_touched = True

    def register_hook(self, callback):
        self._hooks.append(callback)
        return _MiniHookHandle(self._hooks, callback)

    def backward(self) -> None:
        ordered = []
        visited = set()

        def visit(tensor):
            if id(tensor) in visited:
                return
            visited.add(id(tensor))
            for parent in tensor._parents:
                visit(parent)
            ordered.append(tensor)

        visit(self)
        self._accumulate([1.0] * len(self.values))
        for tensor in reversed(ordered):
            tensor._backward_fn(tensor._grad_values)

    def _binary(self, other, forward, left_gradient, right_gradient):
        other = other if isinstance(other, _MiniTensor) else _MiniTensor([other], shape=())
        count = max(len(self.values), len(other.values))
        left = self.values if len(self.values) == count else self.values * count
        right = other.values if len(other.values) == count else other.values * count
        values = [forward(a, b) for a, b in zip(left, right)]

        def backward(gradient):
            if self.requires_grad:
                left_values = [
                    gradient[index] * left_gradient(left[index], right[index])
                    for index in range(count)
                ]
                self._accumulate(
                    [sum(left_values)] if len(self.values) == 1 else left_values
                )
            if other.requires_grad:
                right_values = [
                    gradient[index] * right_gradient(left[index], right[index])
                    for index in range(count)
                ]
                other._accumulate(
                    [sum(right_values)] if len(other.values) == 1 else right_values
                )

        return _MiniTensor(
            values,
            shape=self.shape if len(self.values) == count else other.shape,
            parents=(self, other),
            backward_fn=backward,
        )

    def __add__(self, other):
        return self._binary(other, lambda a, b: a + b, lambda _a, _b: 1, lambda _a, _b: 1)

    def __sub__(self, other):
        return self._binary(other, lambda a, b: a - b, lambda _a, _b: 1, lambda _a, _b: -1)

    def __rsub__(self, other):
        return (-self).__add__(other)

    def __mul__(self, other):
        return self._binary(other, lambda a, b: a * b, lambda _a, b: b, lambda a, _b: a)

    __rmul__ = __mul__

    def __truediv__(self, other):
        return self._binary(
            other,
            lambda a, b: a / b,
            lambda _a, b: 1 / b,
            lambda a, b: -a / (b * b),
        )

    def __neg__(self):
        return self * -1.0

    def __getitem__(self, key):
        if isinstance(key, tuple):
            rows, column = key
            if rows != slice(None) or column != 0 or len(self.shape) != 2:
                raise IndexError(key)
            indices = [row * self.shape[1] for row in range(self.shape[0])]
            shape = (self.shape[0],)
        elif isinstance(key, slice):
            indices = list(range(len(self.values)))[key]
            shape = (len(indices),)
        else:
            indices = [key]
            shape = ()

        def backward(gradient):
            if self.requires_grad:
                result = [0.0] * len(self.values)
                for index, source in enumerate(indices):
                    result[source] += gradient[index]
                self._accumulate(result)

        return _MiniTensor(
            [self.values[index] for index in indices],
            shape=shape,
            parents=(self,),
            backward_fn=backward,
        )

    def mean(self):
        count = len(self.values)

        def backward(gradient):
            if self.requires_grad:
                self._accumulate([gradient[0] / count] * count)

        return _MiniTensor(
            [sum(self.values) / count],
            shape=(),
            parents=(self,),
            backward_fn=backward,
        )

    def detach(self):
        return _MiniTensor(self.values, shape=self.shape, dtype=self.dtype)

    def float(self):
        if self.dtype.startswith("torch.float") or self.dtype == "torch.bfloat16":
            return self
        return _MiniTensor(self.values, shape=self.shape)

    def cpu(self):
        return self

    def clone(self):
        return _MiniTensor(self.values, shape=self.shape, dtype=self.dtype)

    def to(self, _device):
        return self

    def numel(self):
        return len(self.values)

    def item(self):
        if len(self.values) != 1:
            raise ValueError("not a scalar")
        if self.dtype.startswith("torch.int") or self.dtype.startswith("torch.uint"):
            return int(self.values[0])
        return self.values[0]

    def all(self):
        return _MiniTensor([all(bool(value) for value in self.values)], shape=())

    def is_floating_point(self):
        return self.dtype in {"torch.float16", "torch.float32", "torch.bfloat16"}

    def is_contiguous(self):
        return True

    def stride(self):
        if not self.shape:
            return ()
        result = []
        running = 1
        for size in reversed(self.shape):
            result.append(running)
            running *= size
        return tuple(reversed(result))


def _mini_tensor(value, *, dtype="torch.float32", requires_grad=False):
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], (list, tuple)):
        rows = len(value)
        columns = len(value[0])
        return _MiniTensor(
            [item for row in value for item in row],
            shape=(rows, columns),
            dtype=dtype,
            requires_grad=requires_grad,
        )
    is_sequence = isinstance(value, (list, tuple))
    values = list(value) if is_sequence else [value]
    return _MiniTensor(
        values,
        shape=(len(values),) if is_sequence else (),
        dtype=dtype,
        requires_grad=requires_grad,
    )


def _mini_softplus(value):
    import math

    values = [math.log1p(math.exp(item)) for item in value.values]

    def backward(gradient):
        if value.requires_grad:
            value._accumulate(
                [
                    gradient[index] / (1.0 + math.exp(-item))
                    for index, item in enumerate(value.values)
                ]
            )

    return _MiniTensor(
        values,
        shape=value.shape,
        parents=(value,),
        backward_fn=backward,
    )


def _mini_torch():
    import math

    def tensor(value, *, dtype="torch.float32", device=None, requires_grad=False):
        del device
        return _mini_tensor(value, dtype=dtype, requires_grad=requires_grad)

    def isfinite(value):
        return _MiniTensor([math.isfinite(item) for item in value.values], shape=value.shape)

    def count_nonzero(value):
        return _MiniTensor([sum(item != 0 for item in value.values)], shape=())

    def clip_grad_norm(parameters, max_norm, *, error_if_nonfinite):
        del max_norm
        total = sum(
            item * item
            for parameter in parameters
            if parameter.grad is not None
            for item in parameter.grad.values
        ) ** 0.5
        if error_if_nonfinite and not math.isfinite(total):
            raise RuntimeError("nonfinite")
        return _MiniTensor([total], shape=())

    return SimpleNamespace(
        tensor=tensor,
        isfinite=isfinite,
        count_nonzero=count_nonzero,
        equal=lambda left, right: left.values == right.values,
        nn=SimpleNamespace(
            functional=SimpleNamespace(softplus=_mini_softplus),
            utils=SimpleNamespace(clip_grad_norm_=clip_grad_norm),
        ),
    )


class _MiniLoss:
    def __init__(self, parameters, *, value=1.0, contribution=0.1) -> None:
        self.parameters = list(parameters)
        self.value = value
        self.contribution = contribution

    def detach(self):
        return _MiniTensor([self.value], shape=())

    def __mul__(self, factor):
        return _MiniLoss(
            self.parameters,
            value=self.value * factor,
            contribution=self.contribution * factor,
        )

    __rmul__ = __mul__

    def __truediv__(self, divisor):
        return self * (1.0 / divisor)

    def backward(self):
        for index, parameter in enumerate(self.parameters, start=1):
            parameter.add_external_gradient([self.contribution * index])


class _MiniScalars:
    def float(self):
        return self

    def __getitem__(self, _key):
        return self


def _light_stage_context(*, injection: str | None = None):
    class Model:
        def __init__(self) -> None:
            self.base = _MiniTensor([0.5], requires_grad=True)
            self.score = _MiniTensor([0.25], requires_grad=True)

        def named_parameters(self):
            return iter((("model.norm.weight", self.base), ("score.weight", self.score)))

        def parameters(self):
            return iter((self.base, self.score))

    class Dataset:
        stage_value = SimpleNamespace(
            binary_candidate_ids=tuple(f"c{index}" for index in range(6)),
            pair_ids=("boundary", "within"),
        )

        def stage(self, name):
            if name != "C3":
                raise AssertionError(name)
            return self.stage_value

        @staticmethod
        def label(_candidate_id):
            return "PASS"

        @staticmethod
        def pair(pair_id):
            return {
                "kind": "boundary" if pair_id == "boundary" else "within_pass",
                "preferred_candidate_id": "c5",
                "dispreferred_candidate_id": "c0",
            }

    class QuantizedMoment:
        def __init__(self, parameter, dtype) -> None:
            self.quantized = _MiniTensor([0] * parameter.numel(), shape=parameter.shape, dtype=dtype)
            self.scales = _MiniTensor([1], dtype="torch.float16")

        @staticmethod
        def is_quantized():
            return True

        def numel(self):
            return self.quantized.numel()

    class Optimizer:
        def __init__(self, parameters) -> None:
            self.parameters = list(parameters)
            self.param_groups = [{"params": self.parameters, "lr": 0.01}]
            self.state = {
                parameter: {
                    "step": _MiniTensor([0], dtype="torch.int64"),
                    "exp_avg": QuantizedMoment(parameter, "torch.int8"),
                    "exp_avg_sq": QuantizedMoment(parameter, "torch.uint8"),
                    "error_bits": _MiniTensor(
                        [0] * parameter.numel(), shape=parameter.shape, dtype="torch.int16"
                    ),
                }
                for parameter in self.parameters
            }

        def zero_grad(self, *, set_to_none):
            for parameter in self.parameters:
                parameter.grad = None if set_to_none else _MiniTensor([0])

        def step(self):
            if injection == "optimizer_step_error":
                raise RuntimeError("optimizer detail")
            for parameter in self.parameters:
                for index, gradient in enumerate(parameter.grad.values):
                    parameter.values[index] -= 0.01 * gradient
                self.state[parameter]["step"].values[0] += 1
            if injection == "model_nan":
                self.parameters[0].values[0] = float("nan")
            if injection == "optimizer_inf":
                self.state[self.parameters[0]]["exp_avg"].scales.values[0] = float("inf")
            if injection == "optimizer_lr_nan":
                self.param_groups[0]["lr"] = float("nan")

    class Scheduler:
        def __init__(self, optimizer) -> None:
            self.optimizer = optimizer
            self._last_lr = [float(group["lr"]) for group in optimizer.param_groups]

        def step(self):
            if injection == "scheduler_step_error":
                raise RuntimeError("scheduler detail")
            self._last_lr = [float(group["lr"]) for group in self.optimizer.param_groups]
            if injection == "scheduler_lr_inf":
                self._last_lr[0] = float("inf")

        def get_last_lr(self):
            return list(self._last_lr)

    class Cuda:
        reset_peak_memory_stats = staticmethod(lambda _device: None)
        synchronize = staticmethod(lambda _device: None)
        max_memory_allocated = staticmethod(lambda _device: 0)
        max_memory_reserved = staticmethod(lambda _device: 0)

    model = Model()
    optimizer = Optimizer(model.parameters())
    scheduler = Scheduler(optimizer)
    torch = _mini_torch()
    torch.cuda = Cuda()
    return runner._RunContext(
        torch=torch,
        model=model,
        tokenizer=SimpleNamespace(),
        exact_tokenizer=SimpleNamespace(tokenizer=SimpleNamespace(padding_side="right")),
        optimizer=optimizer,
        scheduler=scheduler,
        dataset=Dataset(),
        tokenized={},
        recipe={
            "component_weights": {
                "C3": {"binary": 1.0, "boundary": 1.0, "within_pass": 1.0}
            },
            "binary_micro_batch_size": 2,
            "gradient_clip_norm": 1.0,
        },
        identity={},
        coverage={"optimizer_parameter_tensors": 2},
        device="cpu",
        hardware={},
        startup_timing={},
        optimizer_contract={},
    )


class FullModelRuntimeGateTests(unittest.TestCase):
    class _FlashNumericsError(RuntimeError):
        pass

    _FlashNumericsError.__name__ = "NumericsError"
    _FlashNumericsError.__qualname__ = "NumericsError"
    _FlashNumericsError.__module__ = "flashoptim.optimizers"

    class _NumericsParameter:
        def __init__(self, required_learning_rate: float) -> None:
            self.required_learning_rate = required_learning_rate

    class _NumericsOptimizer:
        def __init__(
            self,
            parameters: list[object],
            *,
            learning_rate: float = 4e-4,
            unexpected_error: bool = False,
            error_class: type[BaseException] | None = None,
        ) -> None:
            self.param_groups = [
                {
                    "params": parameters,
                    "lr": learning_rate,
                    "master_bytewidth": 4,
                }
            ]
            self.recompute_calls = 0
            self.checked: list[tuple[object, float, int]] = []
            self.unexpected_error = unexpected_error
            self.error_class = (
                error_class or FullModelRuntimeGateTests._FlashNumericsError
            )

        def recompute_param_stats(self) -> None:
            self.recompute_calls += 1

        def _check_param_numerics(
            self, parameter: object, *, lr: float, master_bytewidth: int
        ) -> None:
            self.checked.append((parameter, lr, master_bytewidth))
            if self.unexpected_error:
                raise RuntimeError("unexpected checker failure")
            if lr < parameter.required_learning_rate:
                raise self.error_class(
                    f"lr={lr} below required={parameter.required_learning_rate}"
                )

    def test_global_flashadamw_numerics_preflight_checks_every_parameter(self) -> None:
        parameters = [
            self._NumericsParameter(1e-4),
            self._NumericsParameter(4e-4),
        ]
        optimizer = self._NumericsOptimizer(parameters)
        evidence = runner._preflight_flashadamw_numerics(
            optimizer,
            numerics_error_class=self._FlashNumericsError,
            check_numerics=True,
            configured_learning_rate=4e-4,
            expected_parameter_tensors=2,
        )
        self.assertEqual(optimizer.recompute_calls, 1)
        self.assertEqual([item[0] for item in optimizer.checked], parameters)
        self.assertTrue(evidence["all_parameters_passed"])
        self.assertEqual(evidence["parameter_tensors_checked"], 2)
        self.assertEqual(evidence["failed_parameter_tensors"], 0)
        self.assertEqual(evidence["required_power_of_two_learning_rate"], 4e-4)

    def test_global_flashadamw_numerics_preflight_reports_later_256_class_gate(
        self,
    ) -> None:
        parameters = [
            self._NumericsParameter(1e-4),
            self._NumericsParameter(8e-4),
            self._NumericsParameter(2e-4),
        ]
        optimizer = self._NumericsOptimizer(parameters)
        with self.assertRaisesRegex(
            contract.FullModelTrainingError,
            "flashadamw_global_numerics_preflight_failed",
        ) as captured:
            runner._preflight_flashadamw_numerics(
                optimizer,
                numerics_error_class=self._FlashNumericsError,
                check_numerics=True,
                configured_learning_rate=4e-4,
                expected_parameter_tensors=3,
            )
        detail = json.loads(captured.exception.detail or "{}")
        self.assertEqual(optimizer.recompute_calls, 1)
        self.assertEqual(detail["parameter_tensors_checked"], 3)
        self.assertEqual(detail["failed_parameter_tensors"], 1)
        self.assertEqual(detail["required_power_of_two_learning_rate"], 8e-4)
        self.assertIn("required=0.0008", detail["first_failure"])

    def test_global_flashadamw_numerics_preflight_rejects_unexpected_checker_error(
        self,
    ) -> None:
        optimizer = self._NumericsOptimizer(
            [self._NumericsParameter(1e-4)], unexpected_error=True
        )
        with self.assertRaisesRegex(
            contract.FullModelTrainingError,
            "flashadamw_numerics_preflight_check_failed",
        ):
            runner._preflight_flashadamw_numerics(
                optimizer,
                numerics_error_class=self._FlashNumericsError,
                check_numerics=True,
                configured_learning_rate=4e-4,
                expected_parameter_tensors=1,
            )

    def test_global_flashadamw_numerics_preflight_rejects_same_name_spoof(
        self,
    ) -> None:
        spoof = type("NumericsError", (RuntimeError,), {})
        spoof.__module__ = "flashoptim.optimizers"
        optimizer = self._NumericsOptimizer(
            [self._NumericsParameter(8e-4)], error_class=spoof
        )
        with self.assertRaisesRegex(
            contract.FullModelTrainingError,
            "flashadamw_numerics_preflight_check_failed",
        ):
            runner._preflight_flashadamw_numerics(
                optimizer,
                numerics_error_class=self._FlashNumericsError,
                check_numerics=True,
                configured_learning_rate=4e-4,
                expected_parameter_tensors=1,
            )

    def test_winner_h100_gate_accepts_each_exact_candidate(self) -> None:
        for name, qualification in (
            ("NVIDIA H100 PCIe", "H100 PCIe 80GB"),
            ("NVIDIA H100 80GB HBM3", "H100 SXM 80GB"),
        ):
            cuda = SimpleNamespace(
                device_count=lambda: 1,
                get_device_name=lambda _index, value=name: value,
                get_device_properties=lambda _index: SimpleNamespace(
                    total_memory=80 * 1024**3
                ),
                get_device_capability=lambda _index: (9, 0),
            )
            with self.subTest(name=name):
                facts = runner._validate_h100_hardware(
                    SimpleNamespace(cuda=cuda), selected_gpu=name
                )
                self.assertEqual(facts["qualification"], qualification)
                self.assertEqual(facts["selected_gpu"], name)
                self.assertEqual(facts["compute_capability"], [9, 0])

    def test_hardware_gate_rejects_cross_variant_nvl_size_and_multi_gpu(self) -> None:
        cases = (
            ("NVIDIA H100 80GB HBM3", "NVIDIA H100 PCIe", 80 * 1024**3, 1),
            ("NVIDIA H100 NVL", "NVIDIA H100 80GB HBM3", 80 * 1024**3, 1),
            ("NVIDIA H100 PCIe", "NVIDIA H100 PCIe", 78 * 1024**3, 1),
            ("NVIDIA H100 PCIe", "NVIDIA H100 PCIe", 80 * 1024**3, 2),
        )
        for name, selected, memory, count in cases:
            cuda = SimpleNamespace(
                device_count=lambda value=count: value,
                get_device_name=lambda _index, value=name: value,
                get_device_properties=lambda _index, value=memory: SimpleNamespace(
                    total_memory=value
                ),
                get_device_capability=lambda _index: (9, 0),
            )
            with self.subTest(name=name, selected=selected, memory=memory, count=count):
                with self.assertRaisesRegex(
                    contract.FullModelTrainingError,
                    "winner_h100_80gb_hardware_mismatch",
                ):
                    runner._validate_h100_hardware(
                        SimpleNamespace(cuda=cuda), selected_gpu=selected
                    )

    def test_winner_lock_replica_binds_exact_bytes_across_remote_mode_normalization(self) -> None:
        model_contract = json.loads(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path = root / "winner-lock.json"
            value = _winner_lock("NVIDIA H100 80GB HBM3")
            lock_path.write_bytes(contract.pretty_json_bytes(value))
            lock_path.chmod(0o600)
            observed = runner._load_winner_lock(
                lock_path, model_contract=model_contract
            )
            self.assertEqual(observed["value"], value)
            self.assertEqual(observed["selected_gpu"], "NVIDIA H100 80GB HBM3")
            self.assertEqual(observed["sha256"], contract.sha256_file(lock_path))

            # RunPod Standard volumes have been observed to report 0666 after
            # chmod(0600).  The controller authority remains 0600; the remote
            # replica remains exact-hash/schema/regular-file bound.
            lock_path.chmod(0o666)
            normalized = runner._load_winner_lock(
                lock_path, model_contract=model_contract
            )
            self.assertEqual(normalized, observed)

    def test_winner_lock_rejects_symlink_and_candidate_outside_contract(self) -> None:
        model_contract = json.loads(MODEL_CONTRACT_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "outside.json"
            outside.write_bytes(contract.pretty_json_bytes(_winner_lock()))
            outside.chmod(0o600)
            link = root / "winner-lock.json"
            link.symlink_to(outside)
            with self.assertRaisesRegex(
                contract.FullModelTrainingError, "winner_lock_file_invalid"
            ):
                runner._load_winner_lock(link, model_contract=model_contract)

            invalid = root / "invalid.json"
            invalid.write_bytes(
                contract.pretty_json_bytes(_winner_lock("NVIDIA H100 NVL"))
            )
            invalid.chmod(0o600)
            with self.assertRaisesRegex(
                contract.FullModelTrainingError, "winner_lock_identity_invalid"
            ):
                runner._load_winner_lock(invalid, model_contract=model_contract)

            for name, mutate in (
                ("missing_pod", lambda value: value.pop("pod")),
                (
                    "missing_winner_volume",
                    lambda value: value["evidence"].pop("network_volume_id"),
                ),
            ):
                value = _winner_lock()
                mutate(value)
                path = root / f"{name}.json"
                path.write_bytes(contract.pretty_json_bytes(value))
                path.chmod(0o600)
                with self.subTest(name=name), self.assertRaisesRegex(
                    contract.FullModelTrainingError,
                    "winner_lock_identity_invalid",
                ):
                    runner._load_winner_lock(path, model_contract=model_contract)

    def test_receipt_binds_winner_lock_selected_gpu_hardware_and_checkpoint(self) -> None:
        identity = _winner_identity("NVIDIA H100 80GB HBM3")
        receipt = {
            "identity": identity,
            "checkpoint": _checkpoint_receipt("verified", identity=identity),
        }
        runner._validate_winner_bound_receipt(receipt)
        for field, replacement in (
            ("winner_lock_sha256", "x" * 64),
            ("selected_gpu", "NVIDIA H100 PCIe"),
        ):
            changed = json.loads(json.dumps(receipt))
            changed["identity"][field] = replacement
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    contract.FullModelTrainingError,
                    "winner_lock_receipt_binding_invalid",
                ):
                    runner._validate_winner_bound_receipt(changed)

    def test_optimizer_coverage_and_representative_avoid_embedding_copy(self) -> None:
        embedding = _Parameter(1_000_000)
        norm = _Parameter(2048)
        head = _Parameter(2048)
        model = _Model(
            [
                ("model.embed_tokens.weight", embedding),
                ("model.layers.0.input_layernorm.weight", norm),
                ("score.weight", head),
            ]
        )
        optimizer = SimpleNamespace(
            param_groups=[{"params": [embedding, norm, head]}]
        )
        coverage = runner.validate_optimizer_coverage(model, optimizer)
        representatives = runner._representative_parameters(model)
        self.assertTrue(coverage["optimizer_exact_coverage"])
        self.assertIn("model.layers.0.input_layernorm.weight", representatives)
        self.assertNotIn("model.embed_tokens.weight", representatives)

    def test_numerics_stats_are_recomputed_before_checkpoint(self) -> None:
        optimizer = SimpleNamespace(calls=0)

        def recompute():
            optimizer.calls += 1

        optimizer.recompute_param_stats = recompute
        state_keys = _compressed_state_evidence()["required_state_keys"]
        dtypes = {
            "step": "torch.int64",
            "exp_avg::quantized": "torch.int8",
            "exp_avg_sq::quantized": "torch.uint8",
            "exp_avg::scales": "torch.bfloat16",
            "exp_avg_sq::scales": "torch.bfloat16",
            "error_bits": "torch.bfloat16",
        }
        optimizer.state_dict = lambda: {
            "state": {
                0: {
                    key: _StateTensor(dtypes[key], value=3 if key == "step" else None)
                    for key in state_keys
                }
            },
            "param_groups": [{"params": [0]}],
        }
        result, exported = runner._prepare_optimizer_for_checkpoint(
            optimizer, check_numerics=True, expected_state_entries=1, expected_step=3
        )
        self.assertEqual(optimizer.calls, 1)
        self.assertTrue(result["recompute_param_stats_called"])
        self.assertTrue(result["compressed_state"]["compressed_moment_state_complete"])
        self.assertEqual(len(exported["state"]), 1)

    def test_resume_validates_loaded_compressed_state_without_reexport(self) -> None:
        state_keys = _compressed_state_evidence()["required_state_keys"]
        dtypes = {
            "step": "torch.int64",
            "exp_avg::quantized": "torch.int8",
            "exp_avg_sq::quantized": "torch.uint8",
            "exp_avg::scales": "torch.bfloat16",
            "exp_avg_sq::scales": "torch.bfloat16",
            "error_bits": "torch.bfloat16",
        }
        loaded = {
            "state": {
                0: {
                    key: _StateTensor(dtypes[key], value=3 if key == "step" else None)
                    for key in state_keys
                }
            },
            "param_groups": [{"params": [0]}],
        }
        evidence = runner._validate_flashadamw_compressed_state_dict(
            loaded, expected_state_entries=1, expected_step=3
        )
        self.assertTrue(evidence["compressed_moment_state_complete"])
        for resume in (runner.run_commissioning_resume, runner.run_formal_resume):
            source = inspect.getsource(resume)
            self.assertIn("_validate_flashadamw_compressed_state_dict", source)
            self.assertNotIn("_export_and_validate_flashadamw_compressed_state", source)

    def test_gradient_clipping_fails_before_mutating_nonfinite_gradients(self) -> None:
        source = inspect.getsource(runner._run_stage_update)
        self.assertIn("error_if_nonfinite=True", source)

    def test_fused_layout_gate_rejects_parameter_and_gradient_before_step(self) -> None:
        class Tensor:
            shape = (2, 3)

            def __init__(self, *, contiguous, grad=None) -> None:
                self._contiguous = contiguous
                self.grad = grad

            def is_contiguous(self):
                return self._contiguous

            @staticmethod
            def stride():
                return (1, 2)

        for parameter_contiguous, gradient_contiguous, code in (
            (False, True, "flashadamw_parameter_noncontiguous"),
            (True, False, "flashadamw_gradient_noncontiguous"),
        ):
            gradient = Tensor(contiguous=gradient_contiguous)
            parameter = Tensor(contiguous=parameter_contiguous, grad=gradient)
            model = SimpleNamespace(named_parameters=lambda: iter((("weight", parameter),)))
            with self.subTest(code=code), self.assertRaisesRegex(
                contract.FullModelTrainingError, code
            ) as raised:
                runner._validate_flashadamw_fused_inputs(model)
            self.assertEqual(
                raised.exception.detail,
                "name=weight;shape=(2, 3);stride=(1, 2)",
            )

    @staticmethod
    def _flashoptim_import(name):
        if name == "flashoptim":
            return SimpleNamespace(
                reconstruct_fp32_param=lambda parameter, error: parameter.float()
                + error.float()
            )
        return __import__(name)

    def test_stage_update_contract_executes_backward_and_optimizer_control_flow(self) -> None:
        context = _light_stage_context()
        with (
            mock.patch.object(
                runner.importlib, "import_module", side_effect=self._flashoptim_import
            ),
            mock.patch.object(
                runner,
                "_forward_candidates",
                return_value=(_MiniScalars(), 4),
            ),
            mock.patch.object(
                runner,
                "binary_loss",
                side_effect=lambda _scalars, _labels: _MiniLoss(
                    context.model.parameters(), contribution=0.2
                ),
            ),
            mock.patch.object(
                runner,
                "pair_loss",
                side_effect=lambda *_args, **_kwargs: _MiniLoss(
                    context.model.parameters(), contribution=0.1
                ),
            ),
        ):
            receipt = runner._run_stage_update(context, "C3", global_step=1)
        self.assertEqual(
            receipt["component_items"],
            {"binary": 6, "boundary": 1, "within_pass": 1},
        )
        self.assertEqual(receipt["optimizer_step"], 1)
        self.assertTrue(receipt["post_update_finiteness"]["all_finite"])
        self.assertTrue(
            all(
                item["backward_calls"] > 0
                for component in receipt["component_gradient_contributions"].values()
                for item in component.values()
            )
        )

    def test_stage_update_rejects_injected_nonfinite_model_and_optimizer_state(self) -> None:
        for injection, error in (
            ("model_nan", "post_update_model_nonfinite"),
            ("optimizer_inf", "post_update_optimizer_state_nonfinite"),
            ("optimizer_lr_nan", "post_update_learning_rate_nonfinite"),
            ("scheduler_lr_inf", "post_update_scheduler_learning_rate_nonfinite"),
        ):
            with self.subTest(injection=injection):
                context = _light_stage_context(injection=injection)
                with (
                    mock.patch.object(
                        runner.importlib,
                        "import_module",
                        side_effect=self._flashoptim_import,
                    ),
                    mock.patch.object(
                        runner,
                        "_forward_candidates",
                        return_value=(_MiniScalars(), 4),
                    ),
                    mock.patch.object(
                        runner,
                        "binary_loss",
                        side_effect=lambda _scalars, _labels: _MiniLoss(
                            context.model.parameters(), contribution=0.2
                        ),
                    ),
                    mock.patch.object(
                        runner,
                        "pair_loss",
                        side_effect=lambda *_args, **_kwargs: _MiniLoss(
                            context.model.parameters(), contribution=0.1
                        ),
                    ),
                    self.assertRaisesRegex(contract.FullModelTrainingError, error),
                ):
                    runner._run_stage_update(context, "C3", global_step=1)

    def test_stage_update_distinguishes_optimizer_and_scheduler_failures(self) -> None:
        for injection, code, detail in (
            (
                "optimizer_step_error",
                "flashadamw_update_failed",
                "builtins.RuntimeError: optimizer detail",
            ),
            (
                "scheduler_step_error",
                "scheduler_update_failed",
                "builtins.RuntimeError: scheduler detail",
            ),
        ):
            with self.subTest(injection=injection):
                context = _light_stage_context(injection=injection)
                with (
                    mock.patch.object(
                        runner.importlib,
                        "import_module",
                        side_effect=self._flashoptim_import,
                    ),
                    mock.patch.object(
                        runner,
                        "_forward_candidates",
                        return_value=(_MiniScalars(), 4),
                    ),
                    mock.patch.object(
                        runner,
                        "binary_loss",
                        side_effect=lambda _scalars, _labels: _MiniLoss(
                            context.model.parameters(), contribution=0.2
                        ),
                    ),
                    mock.patch.object(
                        runner,
                        "pair_loss",
                        side_effect=lambda *_args, **_kwargs: _MiniLoss(
                            context.model.parameters(), contribution=0.1
                        ),
                    ),
                    self.assertRaisesRegex(contract.FullModelTrainingError, code) as raised,
                ):
                    runner._run_stage_update(context, "C3", global_step=1)
                self.assertEqual(raised.exception.detail, detail)

    def test_effective_master_nonfinite_is_rejected(self) -> None:
        context = _light_stage_context()
        with (
            mock.patch.object(
                runner.importlib,
                "import_module",
                return_value=SimpleNamespace(
                    reconstruct_fp32_param=lambda parameter, error: _MiniTensor(
                        [float("nan")] * parameter.numel(), shape=parameter.shape
                    )
                ),
            ),
            self.assertRaisesRegex(
                contract.FullModelTrainingError,
                "post_update_effective_master_nonfinite",
            ),
        ):
            runner._validate_post_update_finiteness(context)

    def test_component_capture_survives_bf16_absorption_and_cancellation(self) -> None:
        torch = _mini_torch()
        parameter = _MiniTensor(
            [128.0], dtype="torch.bfloat16", requires_grad=True
        )
        representatives = {"model.norm.weight": parameter}
        parameter.grad = _MiniTensor([128.0], dtype="torch.bfloat16")
        with runner._capture_component_gradients(representatives) as captured:
            parameter.add_external_gradient([0.25])
            parameter.add_external_gradient([-0.25])
        self.assertEqual(parameter.grad.item(), 128.0)
        evidence = runner._component_gradient_evidence(
            SimpleNamespace(torch=torch), representatives, captured=captured
        )
        self.assertTrue(evidence["model.norm.weight"]["nonzero"])
        self.assertEqual(evidence["model.norm.weight"]["backward_calls"], 2)


class FullModelBundleTests(unittest.TestCase):
    def test_prepare_verify_archive_and_portable_stage_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = root / "bundle"
            receipt = bundle.prepare_bundle(REPO_ROOT, prepared)
            self.assertEqual(receipt["binary_count"], 6)
            self.assertEqual(receipt["pair_count"], 2)
            self.assertEqual(receipt["stage_pair_counts"], {"C1": 0, "C2": 1, "C3": 2})
            self.assertTrue(
                (prepared / "eval/rondo_eval/publication_critic/full_model_training/checkpoint.py").is_file()
            )
            manifest = json.loads(
                (prepared / bundle.MANIFEST_RELATIVE).read_text(encoding="utf-8")
            )
            train_bodies = [
                name
                for name, metadata in manifest["files"].items()
                if metadata["contains_train_body"]
            ]
            self.assertEqual(train_bodies, [bundle.DATA_RELATIVE])
            self.assertFalse(
                any(
                    term in name.casefold()
                    for name in manifest["files"]
                    for term in ("unseen-test", "unseen_test", "validation")
                )
            )
            first = root / "first.tar"
            second = root / "second.tar"
            first_receipt = bundle.create_deterministic_archive(prepared, first)
            second_receipt = bundle.create_deterministic_archive(prepared, second)
            self.assertEqual(
                first_receipt["archive_sha256"], second_receipt["archive_sha256"]
            )
            extracted = root / "extracted"
            bundle.extract_verified_archive(
                first,
                extracted,
                expected_sha256=first_receipt["archive_sha256"],
            )
            bundle.verify_bundle(extracted)

    def test_strict_verifier_subprocess_uses_no_bytecode_or_cwd_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = root / "bundle"
            bundle.prepare_bundle(REPO_ROOT, prepared)
            shadow = root / "shadow/rondo_eval"
            shadow.mkdir(parents=True)
            (shadow / "__init__.py").write_text(
                "raise RuntimeError('cwd shadow imported')\n", encoding="utf-8"
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(prepared / "eval")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-P",
                    "-m",
                    "rondo_eval.publication_critic.full_model_training",
                    "verify-bundle",
                    "--bundle",
                    str(prepared),
                ],
                cwd=shadow.parent,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertFalse(any(prepared.rglob("__pycache__")))
            (prepared / "unexpected.txt").write_text("unexpected", encoding="utf-8")
            rejected = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-P",
                    "-m",
                    "rondo_eval.publication_critic.full_model_training",
                    "verify-bundle",
                    "--bundle",
                    str(prepared),
                ],
                cwd=shadow.parent,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("bundle_file_set_mismatch", rejected.stderr)

    def test_strict_verifier_subprocess_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = root / "bundle"
            bundle.prepare_bundle(REPO_ROOT, prepared)
            target = prepared / "contracts/portable-input-v1.json"
            original = target.read_bytes()
            target.unlink()
            outside = root / "outside.json"
            outside.write_bytes(original)
            target.symlink_to(outside)
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(prepared / "eval")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-P",
                    "-m",
                    "rondo_eval.publication_critic.full_model_training",
                    "verify-bundle",
                    "--bundle",
                    str(prepared),
                ],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("bundle_non_regular_entry", completed.stderr)

    def test_archive_extractor_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "bad.tar"
            with tarfile.open(archive_path, "w") as archive:
                info = tarfile.TarInfo("../escape")
                raw = b"x"
                info.size = len(raw)
                archive.addfile(info, io.BytesIO(raw))
            with self.assertRaisesRegex(
                contract.FullModelTrainingError, "relative_path_unsafe"
            ):
                bundle.extract_verified_archive(
                    archive_path,
                    root / "out",
                    expected_sha256=contract.sha256_file(archive_path),
                )

    def test_bundle_path_policy_allows_checkpoint_source_but_rejects_state(self) -> None:
        self.assertFalse(
            bundle._forbidden_bundle_path(
                "eval/rondo_eval/publication_critic/full_model_training/checkpoint.py"
            )
        )
        self.assertTrue(bundle._forbidden_bundle_path("runs/checkpoint-c3/state.pt"))
        self.assertTrue(bundle._forbidden_bundle_path("weights/shard.safetensors"))

    def test_model_snapshot_verifier_binds_config_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "cache/snapshots/revision"
            root.mkdir(parents=True)
            for name, raw in (("model.safetensors", b"weights"), ("config.json", b"config")):
                (root / name).write_bytes(raw)
            portable = {
                "tokenizer_file_sha256": {},
                "model": {
                    "weight_file": "model.safetensors",
                    "weight_sha256": contract.sha256_file(root / "model.safetensors"),
                    "config_file": "config.json",
                    "config_sha256": contract.sha256_file(root / "config.json"),
                },
            }
            runner._verify_model_snapshot(root, portable)
            (root / "config.json").write_bytes(b"drift")
            with self.assertRaisesRegex(
                contract.FullModelTrainingError, "model_snapshot_asset_hash_mismatch"
            ):
                runner._verify_model_snapshot(root, portable)


class FullModelCheckpointAndReceiptTests(unittest.TestCase):
    def test_cli_emits_bounded_controlled_failure_detail(self) -> None:
        detail = "builtins.RuntimeError: fused update failed"
        with mock.patch.object(
            cli,
            "_dispatch",
            side_effect=contract.FullModelTrainingError("step_failed", detail),
        ), mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(cli.main(["verify-bundle", "--bundle", "/bundle"]), 2)
        self.assertEqual(
            json.loads(stderr.getvalue()),
            {
                "status": "failed",
                "failure_kind": "FullModelTrainingError",
                "code": "step_failed",
                "detail": detail,
            },
        )

    def test_optimizer_exception_detail_is_bounded_and_single_line(self) -> None:
        error = RuntimeError("line one\n" + "x" * 2000)
        detail = runner._bounded_exception_detail(error)
        self.assertLessEqual(len(detail), 1024)
        self.assertNotIn("\n", detail)
        self.assertTrue(detail.startswith("builtins.RuntimeError: line one "))

    def test_real_torch_objective_update_checkpoint_restore_and_continue(self) -> None:
        try:
            import numpy
            import torch
        except ImportError:
            self.skipTest("real CPU Torch and NumPy dependencies are not installed")

        class TinyModel(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.projection = torch.nn.Linear(2, 1)

            def forward(self, inputs):
                return self.projection(inputs)

            def save_pretrained(self, destination, *, safe_serialization):
                self.assert_safe_serialization = safe_serialization
                destination = Path(destination)
                destination.mkdir()
                torch.save(self.state_dict(), destination / "model.pt")

        class TinyTokenizer:
            @staticmethod
            def save_pretrained(destination):
                destination = Path(destination)
                destination.mkdir()
                (destination / "tokenizer.json").write_text(
                    '{"tiny":true}\n', encoding="utf-8"
                )

        def update(model, optimizer, scheduler):
            optimizer.zero_grad(set_to_none=True)
            inputs = torch.tensor(
                [[1.0, 0.0], [-1.0, 0.5], [0.75, -0.25], [-0.5, 1.0]],
                dtype=torch.float32,
            )
            scalars = extract_raw_scalar(model(inputs))
            loss = binary_loss(scalars[:2], ["PASS", "REWRITE"]) + pair_loss(
                scalars[2:3], scalars[3:4], margin=0.0, temperature=1.0
            )
            self.assertTrue(torch.isfinite(loss).item())
            before = [parameter.detach().clone() for parameter in model.parameters()]
            loss.backward()
            self.assertTrue(
                all(
                    parameter.grad is not None
                    and torch.isfinite(parameter.grad).all().item()
                    for parameter in model.parameters()
                )
            )
            optimizer.step()
            scheduler.step()
            self.assertTrue(
                any(
                    not torch.equal(previous, parameter.detach())
                    for previous, parameter in zip(before, model.parameters())
                )
            )
            return float(loss.detach().item())

        original_python_rng = random.getstate()
        original_numpy_rng = numpy.random.get_state()
        original_torch_rng = torch.get_rng_state()
        original_threads = torch.get_num_threads()
        try:
            torch.set_num_threads(1)
            random.seed(20260824)
            numpy.random.seed(20260824)
            torch.manual_seed(20260824)
            model = TinyModel()
            optimizer = torch.optim.AdamW(model.parameters(), lr=0.05)
            scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lambda _step: 1.0)
            first_loss = update(model, optimizer, scheduler)
            self.assertGreater(first_loss, 0.0)

            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary) / "checkpoint"
                progress = {
                    "stage": "C3",
                    "global_step": 3,
                    "stage_update": 1,
                    "completed_stages": ["C1", "C2", "C3"],
                    "data_cursor": {
                        "stage_fully_consumed": True,
                        "binary_candidate_ids": [f"c{index}" for index in range(6)],
                        "pair_ids": ["boundary", "within"],
                    },
                }
                checkpoint.save_full_checkpoint(
                    root,
                    model=model,
                    tokenizer=TinyTokenizer(),
                    optimizer=optimizer,
                    scheduler=scheduler,
                    progress=progress,
                    identity={"run": "real-cpu-torch-seam"},
                    process_identity=contract.ProcessIdentity(
                        "real-torch-start", os.getpid(), os.getppid(), "now"
                    ),
                )
                self.assertTrue(model.assert_safe_serialization)
                verified = checkpoint.verify_checkpoint(root)
                expected_python_random = random.random()
                expected_numpy_random = numpy.random.random(4)
                expected_torch_random = torch.rand(4)

                restored_model = TinyModel()
                restored_model.load_state_dict(
                    torch.load(
                        root / "full-model/model/model.pt",
                        map_location="cpu",
                        weights_only=True,
                    )
                )
                restored_optimizer = torch.optim.AdamW(
                    restored_model.parameters(), lr=0.05
                )
                restored_scheduler = torch.optim.lr_scheduler.LambdaLR(
                    restored_optimizer, lambda _step: 1.0
                )
                loaded = checkpoint.load_training_state(
                    root, verified_receipt=verified
                )
                restored_optimizer.load_state_dict(loaded["optimizer"])
                restored_scheduler.load_state_dict(loaded["scheduler"])
                checkpoint.restore_rng_state(loaded["rng"])
                self.assertEqual(random.random(), expected_python_random)
                numpy.testing.assert_allclose(
                    numpy.random.random(4), expected_numpy_random, rtol=0, atol=0
                )
                torch.testing.assert_close(torch.rand(4), expected_torch_random)
                self.assertEqual(restored_scheduler.last_epoch, 1)
                self.assertTrue(
                    all(
                        int(state["step"].item()) == 1
                        for state in restored_optimizer.state.values()
                    )
                )

                continued_loss = update(
                    restored_model, restored_optimizer, restored_scheduler
                )
                self.assertGreater(continued_loss, 0.0)
                self.assertEqual(restored_scheduler.last_epoch, 2)
                self.assertTrue(
                    all(
                        int(state["step"].item()) == 2
                        for state in restored_optimizer.state.values()
                    )
                )
        finally:
            random.setstate(original_python_rng)
            numpy.random.set_state(original_numpy_rng)
            torch.set_rng_state(original_torch_rng)
            torch.set_num_threads(original_threads)

    def test_fake_full_checkpoint_and_new_process_pid_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkpoint"

            def model_saver(model_root: Path) -> None:
                (model_root / "model").mkdir()
                (model_root / "tokenizer").mkdir()
                (model_root / "model/model.safetensors").write_bytes(b"tiny")
                (model_root / "tokenizer/tokenizer.json").write_bytes(b"tiny")

            def encode(path: Path, value) -> None:
                path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

            progress = {
                "stage": "C3",
                "global_step": 3,
                "stage_update": 1,
                "completed_stages": ["C1", "C2", "C3"],
                "data_cursor": {
                    "stage_fully_consumed": True,
                    "binary_candidate_ids": [f"c{index}" for index in range(6)],
                    "pair_ids": ["boundary", "within"],
                },
            }
            process = contract.ProcessIdentity("start", os.getpid(), os.getppid(), "now")
            checkpoint.write_checkpoint(
                root,
                model_saver=model_saver,
                optimizer_state={"state": {"0": {"step": 3}}, "param_groups": [{"params": [0]}]},
                scheduler_state={"last_epoch": 3},
                rng_state={"python": [1, 2, 3]},
                progress=progress,
                identity={"run": "fake"},
                process_identity=process,
                state_encoder=encode,
            )
            verified = checkpoint.verify_checkpoint(root)
            loaded = checkpoint.load_training_state(
                root,
                state_decoder=lambda path: json.loads(path.read_text(encoding="utf-8")),
            )
            self.assertEqual(verified["global_step"], 3)
            self.assertEqual(loaded["scheduler"]["last_epoch"], 3)
            with mock.patch.object(
                checkpoint,
                "verify_checkpoint",
                side_effect=AssertionError("checkpoint must not be hashed twice"),
            ):
                loaded_again = checkpoint.load_training_state(
                    root,
                    state_decoder=lambda path: json.loads(
                        path.read_text(encoding="utf-8")
                    ),
                    verified_receipt=verified,
                )
            self.assertEqual(loaded_again["scheduler"]["last_epoch"], 3)
            self.assertNotIn(
                "verify_checkpoint(staging)", inspect.getsource(checkpoint.write_checkpoint)
            )
            with self.assertRaisesRegex(
                contract.FullModelTrainingError, "checkpoint_resume_requires_new_process"
            ):
                checkpoint.require_new_process(checkpoint.read_checkpoint_metadata(root))
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(EVAL_ROOT)
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-P",
                    "-m",
                    "rondo_eval.publication_critic.full_model_training",
                    "verify-checkpoint",
                    "--checkpoint",
                    str(root),
                    "--require-new-process",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertTrue(json.loads(completed.stdout)["new_process"])

    def test_checkpoint_progress_and_resume_cursor_are_exact(self) -> None:
        stage = SimpleNamespace(
            binary_candidate_ids=tuple(f"c{index}" for index in range(6)),
            pair_ids=("boundary", "within"),
        )
        dataset = SimpleNamespace(stage=lambda name: stage if name == "C3" else None)
        expected = runner._progress("C3", 3, ["C1", "C2", "C3"], stage)
        checkpoint._validate_progress(expected)
        runner._require_expected_resume_progress({"progress": expected}, dataset)
        mutations = (
            ("completed_order", lambda value: value.update(completed_stages=["C2", "C1", "C3"])),
            ("completed_duplicate", lambda value: value.update(completed_stages=["C1", "C3", "C3"])),
            ("stage", lambda value: value.update(stage="C2")),
            ("stage_update", lambda value: value.update(stage_update=2)),
            (
                "cursor_flag",
                lambda value: value["data_cursor"].update(stage_fully_consumed=False),
            ),
            (
                "binary_ids",
                lambda value: value["data_cursor"]["binary_candidate_ids"].__setitem__(
                    0, "wrong"
                ),
            ),
            (
                "pair_ids",
                lambda value: value["data_cursor"]["pair_ids"].__setitem__(0, "wrong"),
            ),
        )
        for name, mutate in mutations:
            value = json.loads(json.dumps(expected))
            mutate(value)
            with self.subTest(name=name):
                if name in {"binary_ids", "pair_ids"}:
                    checkpoint._validate_progress(value)
                else:
                    with self.assertRaises(contract.FullModelTrainingError):
                        checkpoint._validate_progress(value)
                with self.assertRaisesRegex(
                    contract.FullModelTrainingError,
                    "checkpoint_resume_progress_mismatch",
                ):
                    runner._require_expected_resume_progress({"progress": value}, dataset)

    def test_formal_and_commissioning_receipts_require_split_resume_and_timings(self) -> None:
        start_process = _process(1, "start")
        winner_identity = _winner_identity()
        start = {
            "schema": "rondo-publication-critic-formal-start-receipt-v1",
            "status": "pending_new_process_resume",
            "created_at": "now",
            "process": start_process,
            "identity": winner_identity,
            "coverage": _coverage(),
            "stages": [_stage("C1", 1), _stage("C2", 2), _stage("C3", 3)],
            "checkpoint": _checkpoint_receipt(
                "saved_manifest_built", start_process, identity=winner_identity
            ),
            "optimizer_pre_checkpoint": {
                "check_numerics": True,
                "recompute_param_stats_called": True,
                "elapsed_seconds": 0.2,
                "compressed_state": _compressed_state_evidence(),
            },
            "global_step": 3,
            "resume_required": {"stage": "C3", "updates": 1, "new_os_process": True},
            "timing": _start_timing(),
        }
        contract.validate_formal_start_receipt(start)
        preflight_count_mismatch = json.loads(json.dumps(start))
        preflight_count_mismatch["timing"]["runtime_prepare"][
            "optimizer_numerics_preflight"
        ]["parameter_tensors_checked"] = 1
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "formal_start_receipt_invalid"
        ):
            contract.validate_formal_start_receipt(preflight_count_mismatch)
        preflight_lr_mismatch = json.loads(json.dumps(start))
        preflight_lr_mismatch["timing"]["runtime_prepare"][
            "optimizer_numerics_preflight"
        ]["configured_learning_rate"] = 8e-4
        preflight_lr_mismatch["timing"]["runtime_prepare"][
            "optimizer_numerics_preflight"
        ]["required_power_of_two_learning_rate"] = 8e-4
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "formal_start_receipt_invalid"
        ):
            contract.validate_formal_start_receipt(preflight_lr_mismatch)
        failed_preflight = json.loads(json.dumps(start))
        failed_preflight["timing"]["runtime_prepare"][
            "optimizer_numerics_preflight"
        ].update(failed_parameter_tensors=1, all_parameters_passed=False)
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "formal_start_receipt_invalid"
        ):
            contract.validate_formal_start_receipt(failed_preflight)
        empty_coverage = json.loads(json.dumps(start))
        empty_coverage["coverage"] = {}
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "formal_start_receipt_invalid"
        ):
            contract.validate_formal_start_receipt(empty_coverage)
        finite_count_mismatch = json.loads(json.dumps(start))
        finite_count_mismatch["stages"][0]["post_update_finiteness"].update(
            model_parameter_tensors=1,
            effective_master_tensors=1,
            optimizer_floating_state_tensors=2,
        )
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "formal_start_receipt_invalid"
        ):
            contract.validate_formal_start_receipt(finite_count_mismatch)
        state_count_mismatch = json.loads(json.dumps(start))
        state_count_mismatch["optimizer_pre_checkpoint"]["compressed_state"] = (
            _compressed_state_evidence(1)
        )
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "formal_start_receipt_invalid"
        ):
            contract.validate_formal_start_receipt(state_count_mismatch)
        commissioning_start = dict(start)
        commissioning_start.update(
            schema="rondo-publication-critic-commissioning-start-receipt-v1",
            status="commissioning_only_pending_new_process_resume",
        )
        runner._validate_commissioning_start_receipt(commissioning_start)
        pending = {
            "schema": "rondo-publication-critic-formal-training-pending-v1",
            "status": "pending_billing_and_resource_cleanup",
            "created_at": "now",
            "identity": winner_identity,
            "start_process": start_process,
            "resume_process": _process(2, "resume"),
            "new_os_process_confirmed": True,
            "restored_from_global_step": 3,
            "continued_global_step": 4,
            "continued_stage": _stage("C3", 4),
            "coverage": _coverage(),
            "restored_optimizer_state": _compressed_state_evidence(),
            "restored_optimizer_runtime": _runtime_state_evidence(),
            "checkpoint": _checkpoint_receipt(
                "verified", start_process, identity=winner_identity
            ),
            "formal_start_receipt_sha256": "0" * 64,
            "timing": _resume_timing(),
            "billing": None,
            "remote_resource_terminal_state": None,
            "qualification_conclusion": None,
        }
        contract.validate_formal_pending_receipt(pending)
        resume_preflight_count_mismatch = json.loads(json.dumps(pending))
        resume_preflight_count_mismatch["timing"]["runtime_prepare"][
            "optimizer_numerics_preflight"
        ]["parameter_tensors_checked"] = 1
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "formal_pending_receipt_invalid"
        ):
            contract.validate_formal_pending_receipt(resume_preflight_count_mismatch)
        restored_count_mismatch = json.loads(json.dumps(pending))
        restored_count_mismatch["restored_optimizer_state"] = _compressed_state_evidence(1)
        restored_count_mismatch["restored_optimizer_runtime"] = _runtime_state_evidence(1)
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "formal_pending_receipt_invalid"
        ):
            contract.validate_formal_pending_receipt(restored_count_mismatch)
        commissioning_resume = dict(pending)
        for key in (
            "billing",
            "remote_resource_terminal_state",
            "qualification_conclusion",
            "formal_start_receipt_sha256",
        ):
            commissioning_resume.pop(key)
        commissioning_resume.update(
            schema="rondo-publication-critic-commissioning-resume-receipt-v1",
            status="commissioning_only_complete_not_formal_evidence",
        )
        runner._validate_commissioning_resume_receipt(commissioning_resume)
        pending["resume_process"] = _process(1, "resume")
        with self.assertRaisesRegex(
            contract.FullModelTrainingError, "formal_pending_resume_evidence_invalid"
        ):
            contract.validate_formal_pending_receipt(pending)

    def test_cli_passes_dependency_freeze_to_formal_commands(self) -> None:
        args = cli._parser().parse_args(
            [
                "formal-start",
                "--bundle",
                "/bundle",
                "--model-snapshot",
                "/model",
                "--output",
                "/output",
                "--winner-lock",
                "/winner.json",
                "--container-image",
                "image",
                "--dependency-identity",
                "/dependency.json",
                "--dependency-freeze",
                "/freeze.txt",
            ]
        )
        with mock.patch.object(cli, "run_formal_start", return_value={"ok": True}) as call:
            self.assertEqual(cli._dispatch(args), {"ok": True})
        self.assertEqual(call.call_args.kwargs["dependency_freeze_path"], Path("/freeze.txt"))
        self.assertEqual(call.call_args.kwargs["winner_lock_path"], Path("/winner.json"))

    def test_cli_requires_and_passes_winner_lock_for_every_training_mode(self) -> None:
        targets = {
            "commission-start": "run_commissioning_start",
            "commission-resume": "run_commissioning_resume",
            "formal-start": "run_formal_start",
            "formal-resume": "run_formal_resume",
        }
        for command, target in targets.items():
            argv = [
                command,
                "--bundle",
                "/bundle",
                "--model-snapshot",
                "/model",
                "--output",
                "/output",
                "--winner-lock",
                "/winner.json",
                "--container-image",
                "image",
            ]
            if command.endswith("-resume"):
                argv.extend(("--checkpoint", "/checkpoint"))
            if command.startswith("formal-"):
                argv.extend(
                    (
                        "--dependency-identity",
                        "/dependency.json",
                        "--dependency-freeze",
                        "/freeze.txt",
                    )
                )
            args = cli._parser().parse_args(argv)
            with self.subTest(command=command):
                with mock.patch.object(cli, target, return_value={"ok": True}) as call:
                    self.assertEqual(cli._dispatch(args), {"ok": True})
                self.assertEqual(
                    call.call_args.kwargs["winner_lock_path"], Path("/winner.json")
                )

    def test_cli_passes_runtime_budget_policy_to_finalizer(self) -> None:
        args = cli._parser().parse_args(
            [
                "finalize-formal",
                "--formal-start",
                "/start.json",
                "--formal-pending",
                "/pending.json",
                "--provider-facts",
                "/facts.json",
                "--budget-policy",
                "/budget-policy.json",
                "--output",
                "/final.json",
            ]
        )
        with mock.patch.object(
            cli, "finalize_formal_receipt", return_value={"ok": True}
        ) as call:
            self.assertEqual(cli._dispatch(args), {"ok": True})
        self.assertEqual(
            call.call_args.kwargs["budget_policy_path"], Path("/budget-policy.json")
        )

    def test_finalizer_binds_training_to_settled_billing_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            start_path = root / "start.json"
            pending_path = root / "pending.json"
            facts_path = root / "facts.json"
            budget_policy_path = root / "budget-policy.json"
            output_path = root / "final.json"
            budget_policy_path.write_text('{"hard_cap_usd":8.0}\n')
            start_process = _process(1, "start")
            winner_identity = _winner_identity("NVIDIA H100 80GB HBM3")
            start = {
                "schema": "rondo-publication-critic-formal-start-receipt-v1",
                "status": "pending_new_process_resume",
                "created_at": "2026-08-24T07:30:00Z",
                "process": start_process,
                "identity": winner_identity,
                "coverage": _coverage(),
                "stages": [_stage("C1", 1), _stage("C2", 2), _stage("C3", 3)],
                "checkpoint": _checkpoint_receipt(
                    "saved_manifest_built", start_process, identity=winner_identity
                ),
                "optimizer_pre_checkpoint": {
                    "check_numerics": True,
                    "recompute_param_stats_called": True,
                    "elapsed_seconds": 0.2,
                    "compressed_state": _compressed_state_evidence(),
                },
                "global_step": 3,
                "resume_required": {"stage": "C3", "updates": 1, "new_os_process": True},
                "timing": _start_timing(),
            }
            start_path.write_bytes(contract.pretty_json_bytes(start))
            pending = {
                "schema": "rondo-publication-critic-formal-training-pending-v1",
                "status": "pending_billing_and_resource_cleanup",
                "created_at": "2026-08-24T08:00:00Z",
                "identity": start["identity"],
                "start_process": start["process"],
                "resume_process": _process(2, "resume"),
                "new_os_process_confirmed": True,
                "restored_from_global_step": 3,
                "continued_global_step": 4,
                "continued_stage": _stage("C3", 4),
                "coverage": _coverage(),
                "restored_optimizer_state": _compressed_state_evidence(),
                "restored_optimizer_runtime": _runtime_state_evidence(),
                "checkpoint": _checkpoint_receipt(
                    "verified", start_process, identity=winner_identity
                ),
                "formal_start_receipt_sha256": contract.sha256_file(start_path),
                "timing": _resume_timing(),
                "billing": None,
                "remote_resource_terminal_state": None,
                "qualification_conclusion": None,
            }
            pending_path.write_bytes(contract.pretty_json_bytes(pending))
            facts = _provider_terminal_facts(winner_identity)
            facts_path.write_bytes(contract.pretty_json_bytes(facts))
            receipt = finalize.finalize_formal_receipt(
                formal_start_path=start_path,
                formal_pending_path=pending_path,
                provider_facts_path=facts_path,
                budget_policy_path=budget_policy_path,
                output_path=output_path,
            )
            self.assertEqual(receipt["budget"]["m3_b1c_remaining_budget_usd"], 21.75)
            self.assertEqual(receipt["budget"]["runtime_policy"]["hard_cap_usd"], 8.0)
            self.assertEqual(
                receipt["budget"]["runtime_policy"]["source_sha256"],
                contract.sha256_file(budget_policy_path),
            )
            self.assertTrue(
                receipt["m3_b1c_cost_projection"][
                    "affordable_within_remaining_budget"
                ]
            )
            self.assertTrue(output_path.is_file())
            stale_facts = json.loads(json.dumps(facts))
            stale_facts["captured_at"] = "2026-08-24T07:59:59Z"
            stale_facts_path = root / "stale-facts.json"
            stale_facts_path.write_bytes(contract.pretty_json_bytes(stale_facts))
            with self.assertRaisesRegex(
                contract.FullModelTrainingError,
                "formal_finalization_time_binding_invalid",
            ):
                finalize.finalize_formal_receipt(
                    formal_start_path=start_path,
                    formal_pending_path=pending_path,
                    provider_facts_path=stale_facts_path,
                    budget_policy_path=budget_policy_path,
                    output_path=root / "stale-final.json",
                )
            cap_facts = json.loads(json.dumps(facts))
            cap_facts["billing"]["actual_plan060_cost_usd"] = 8.0
            cap_facts["billing"]["task_pod_cost_usd"] = 7.95
            self.assertEqual(
                finalize._validate_provider_terminal_facts(
                    cap_facts,
                    hard_cap_usd=8.0,
                    training_identity=winner_identity,
                )["billing"]["actual_plan060_cost_usd"],
                8.0,
            )
            cap_facts["billing"]["task_pod_cost_usd"] = 7.950001
            cap_facts["billing"]["actual_plan060_cost_usd"] = 8.000001
            with self.assertRaisesRegex(
                contract.FullModelTrainingError, "provider_terminal_facts_invalid"
            ):
                finalize._validate_provider_terminal_facts(
                    cap_facts,
                    hard_cap_usd=8.0,
                    training_identity=winner_identity,
                )
            budget_policy_path.write_text('{"hard_cap_usd":NaN}\n')
            with self.assertRaisesRegex(
                contract.FullModelTrainingError, "budget_policy_hard_cap_invalid"
            ):
                finalize.finalize_formal_receipt(
                    formal_start_path=start_path,
                    formal_pending_path=pending_path,
                    provider_facts_path=facts_path,
                    budget_policy_path=budget_policy_path,
                    output_path=root / "invalid-policy.json",
                )
            budget_policy_path.write_text('{"hard_cap_usd":8.0}\n')
            pending["coverage"]["parameter_order_sha256"] = "d" * 64
            pending_path.write_bytes(contract.pretty_json_bytes(pending))
            with self.assertRaisesRegex(
                contract.FullModelTrainingError,
                "formal_finalization_training_binding_mismatch",
            ):
                finalize.finalize_formal_receipt(
                    formal_start_path=start_path,
                    formal_pending_path=pending_path,
                    provider_facts_path=facts_path,
                    budget_policy_path=budget_policy_path,
                    output_path=root / "mismatch.json",
                )
            facts["provider_task"]["selected_gpu"] = "NVIDIA H100 PCIe"
            with self.assertRaisesRegex(
                contract.FullModelTrainingError, "provider_terminal_facts_invalid"
            ):
                finalize._validate_provider_terminal_facts(
                    facts,
                    hard_cap_usd=8.0,
                    training_identity=winner_identity,
                )

    def test_provider_terminal_facts_reject_gpu_chain_and_resource_drift(self) -> None:
        winner_identity = _winner_identity("NVIDIA H100 80GB HBM3")
        valid = _provider_terminal_facts(winner_identity)
        self.assertEqual(
            finalize._validate_provider_terminal_facts(
                valid,
                hard_cap_usd=8.0,
                training_identity=winner_identity,
            )["provider_task"]["selected_gpu"],
            "NVIDIA H100 80GB HBM3",
        )
        preselection_winner = json.loads(json.dumps(valid))
        locked_pod = preselection_winner["provider_task"]["pod_chain"][1]
        locked_pod["role"] = "winner_preselection"
        preselection_winner["provider_task"]["pod_chain"].append(
            {
                "pod_id": "winner-replacement",
                "pod_name": "rondo-plan060-winner-replacement-training",
                "gpu_id": "NVIDIA H100 80GB HBM3",
                "role": "training",
                "billing_window": {
                    "start_utc": "2026-08-24T07:00:00Z",
                    "end_utc": "2026-08-24T08:00:00Z",
                },
            }
        )
        finalize._validate_provider_terminal_facts(
            preselection_winner,
            hard_cap_usd=8.0,
            training_identity=winner_identity,
        )
        third_volume = json.loads(
            json.dumps(valid["resources"]["task_standard_network_volumes"][0])
        )
        third_volume["volume_id"] = "volume-third"
        third_volume["volume_name"] = "rondo-plan060-third-assets"
        mutations = {
            "winner_pod_missing": lambda value: value["provider_task"]["pod_chain"][
                1
            ].update(
                pod_id="unrelated-training-pod",
                pod_name="rondo-plan060-unrelated-training",
            ),
            "winner_pod_name_mismatch": lambda value: value["provider_task"][
                "pod_chain"
            ][1].update(pod_name="rondo-plan060-wrong-winner-name"),
            "winner_lock_sha_drift": lambda value: value["provider_task"].update(
                winner_lock_sha256="f" * 64
            ),
            "winner_model_drift": lambda value: value["provider_task"]["pod_chain"][
                1
            ].update(gpu_id="NVIDIA H100 PCIe"),
            "legacy_asset_source_marked_training": lambda value: value[
                "provider_task"
            ]["pod_chain"][0].update(role="training"),
            "concurrent_gpu_count": lambda value: value["provider_task"].update(
                max_concurrent_task_gpu_count_observed=2
            ),
            "overlapping_billing_windows": lambda value: value["provider_task"][
                "pod_chain"
            ][1]["billing_window"].update(start_utc="2026-08-24T05:59:59Z"),
            "billing_window_after_capture": lambda value: value["provider_task"][
                "pod_chain"
            ][1]["billing_window"].update(end_utc="2026-08-24T09:00:01Z"),
            "three_volumes": lambda value: value["resources"][
                "task_standard_network_volumes"
            ].append(third_volume),
            "loser_volume_not_deleted": lambda value: value["resources"][
                "task_standard_network_volumes"
            ][0].update(terminal_state="retained_canonical"),
            "retained_volume_unverified": lambda value: value["resources"][
                "task_standard_network_volumes"
            ][1].update(canonical_assets_verified=False),
            "retained_volume_model_drift": lambda value: value["resources"][
                "task_standard_network_volumes"
            ][1].update(gpu_id="NVIDIA H100 PCIe"),
            "retained_volume_not_winner_lock": lambda value: (
                value["resources"]["task_standard_network_volumes"][0].update(
                    terminal_state="retained_canonical",
                    gpu_id="NVIDIA H100 80GB HBM3",
                ),
                value["resources"]["task_standard_network_volumes"][1].update(
                    terminal_state="deleted"
                ),
                value["resources"].update(
                    retained_canonical_winner_volume_id="volume-pcie"
                ),
            ),
            "compute_pod_left_active": lambda value: value["resources"].update(
                all_compute_pods_terminated=False
            ),
            "billing_not_aggregated": lambda value: value["billing"].update(
                all_task_pods_and_volumes_included=False
            ),
            "retained_volume_zero_storage_rate": lambda value: value[
                "resources"
            ].update(continuing_storage_cost_usd_per_hr=0),
        }
        for name, mutate in mutations.items():
            candidate = json.loads(json.dumps(valid))
            mutate(candidate)
            with self.subTest(name=name), self.assertRaisesRegex(
                contract.FullModelTrainingError, "provider_terminal_facts_invalid"
            ):
                finalize._validate_provider_terminal_facts(
                    candidate,
                    hard_cap_usd=8.0,
                    training_identity=winner_identity,
                )

    def test_receipts_reject_empty_or_inconsistent_full_parameter_coverage(self) -> None:
        coverage = _coverage()
        self.assertTrue(contract.valid_full_parameter_coverage(coverage))
        for name, mutate in (
            ("empty", lambda value: value.clear()),
            ("parameter_count", lambda value: value.update(parameter_count=1)),
            ("optimizer_flag", lambda value: value.update(optimizer_exact_coverage=False)),
            ("dtype", lambda value: value.update(dtype_counts={"torch.float32": 1_720_577_024})),
            ("device", lambda value: value.update(device_counts={"cpu:0": 1_720_577_024})),
        ):
            candidate = json.loads(json.dumps(coverage))
            mutate(candidate)
            with self.subTest(name=name):
                self.assertFalse(contract.valid_full_parameter_coverage(candidate))

    def test_receipt_rejects_missing_component_gradient_or_master_evidence(self) -> None:
        stages = [_stage("C1", 1), _stage("C2", 2), _stage("C3", 3)]
        self.assertTrue(contract._valid_stage_receipts(stages))
        del stages[1]["component_gradient_contributions"]["boundary"]
        self.assertFalse(contract._valid_stage_receipts(stages))
        stages = [_stage("C1", 1), _stage("C2", 2), _stage("C3", 3)]
        stages[2]["representative_updates"]["score.weight"][
            "effective_master_changed"
        ] = False
        self.assertFalse(contract._valid_stage_receipts(stages))
        stages = [_stage("C1", 1), _stage("C2", 2), _stage("C3", 3)]
        stages[0]["post_update_finiteness"]["optimizer_learning_rates"] = [
            float("nan")
        ]
        self.assertFalse(contract._valid_stage_receipts(stages))

    def test_capture_dependency_cli_hashes_complete_freeze(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            freeze = root / "freeze.txt"
            freeze.write_text("torch==x\n", encoding="utf-8")
            output = root / "identity.json"
            args = cli._parser().parse_args(
                [
                    "capture-dependencies",
                    "--bundle",
                    "/bundle",
                    "--container-image",
                    "image",
                    "--status",
                    "formal_frozen",
                    "--complete-freeze",
                    str(freeze),
                    "--output",
                    str(output),
                ]
            )
            identity = {
                "schema": "fake",
                "complete_freeze_sha256": contract.sha256_file(freeze),
            }
            with (
                mock.patch.object(cli, "verify_bundle"),
                mock.patch.object(cli, "read_json", return_value={}),
                mock.patch.object(cli, "_validate_model_contract", return_value={}),
                mock.patch.object(
                    cli, "capture_dependency_identity", return_value=identity
                ) as capture,
            ):
                cli._dispatch(args)
            self.assertEqual(
                capture.call_args.kwargs["complete_freeze_sha256"],
                contract.sha256_file(freeze),
            )
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), identity)


if __name__ == "__main__":
    unittest.main()
