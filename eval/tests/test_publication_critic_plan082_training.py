from __future__ import annotations

from contextlib import nullcontext
import copy
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training.contract import (  # noqa: E402
    MODEL_REPOSITORY,
    MODEL_REVISION,
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
from rondo_eval.publication_critic.full_model_training.plan081_artifacts import (  # noqa: E402
    Plan081ArtifactStore,
)
from rondo_eval.publication_critic.full_model_training.plan081_contract import (  # noqa: E402
    ComparisonPolicy,
    ControlPlan,
    TrainableScope,
)
from rondo_eval.publication_critic.full_model_training.plan081_observation import (  # noqa: E402
    validation_identity_sha256,
)
from rondo_eval.publication_critic.full_model_training.plan082_adapter import (  # noqa: E402
    RUNTIME_KIND,
    TorchContinuousTrainingAdapter,
    validate_recipe,
)
from rondo_eval.publication_critic.full_model_training.plan082_bundle import (  # noqa: E402
    DATA_BUNDLE_SCHEMA,
    SOURCE_PATHS,
    SOURCE_BUNDLE_SCHEMA,
    create_source_archive,
    extract_source_archive,
)
from rondo_eval.publication_critic.full_model_training.plan082_cli import (  # noqa: E402
    _load_process_receipt,
    _require_new_process,
    _run_with_adapter,
    _verify_executing_source,
)
from rondo_eval.publication_critic.full_model_training.plan082_controller import (  # noqa: E402
    CONTROLLER_SCHEMA,
    Plan082ContinuousTrainingController,
)
from rondo_eval.publication_critic.full_model_training.plan082_formal import (  # noqa: E402
    RECOVERY_SCHEMA,
    create_formal_freeze,
    finalize_formal_run,
)
from rondo_eval.publication_critic.full_model_training.plan082_run import (  # noqa: E402
    RUN_SPEC_SCHEMA,
    frozen_scope_history,
    run_scheduled,
    validate_run_spec,
)
from eval.tests.test_publication_critic_plan081_training import (  # noqa: E402
    _FakeAdapter as _Plan081FakeAdapter,
    _logits as _plan081_logits,
)


PLAN081_ROUTE = REPO_ROOT / "training/publication-critic-plan081/route-contract-v1.json"
RECIPE_PATH = REPO_ROOT / "training/publication-critic-plan082/recipe-candidate-v1.json"


def _scope(name: str, names: list[str], elements: int) -> dict:
    return {
        "scope_id": name,
        "update_method": "direct_original_parameter_update",
        "parameter_names": names,
        "trainable_parameter_elements": elements,
        "reason": f"fixture-{name}",
    }


def _run_spec() -> dict:
    return validate_run_spec(
        {
            "schema": RUN_SPEC_SCHEMA,
            "recipe": read_json(RECIPE_PATH),
            "initial_scope": _scope("tail", ["tail.weight"], 2),
            "scope_schedule": [
                {
                    "after_observation_step": 1,
                    "scope": _scope(
                        "tail-expanded",
                        ["tail.weight", "tail.bias"],
                        3,
                    ),
                }
            ],
            "control_plan": {
                "maximum_updates": 3,
                "observation_steps": [1, 2, 3],
                "checkpoint_steps": [1, 3],
                "turning_point_limit": 2,
            },
            "comparison_policy": {
                "metric": "boundary_pair_mean_margin",
                "direction": "higher_is_better",
                "tolerance": 0.0,
            },
            "report_threshold": 0.5,
        }
    )


def _runtime_identity() -> dict:
    recipe = read_json(RECIPE_PATH)
    inventory = _parameter_inventory()
    return {
        "runtime_kind": RUNTIME_KIND,
        "gpu_name": "NVIDIA A40",
        "gpu_count": 1,
        "cuda_version": "12.8",
        "torch_version": "2.8.0+cu128",
        "transformers_version": "4.52.3",
        "model_repository": MODEL_REPOSITORY,
        "model_revision": MODEL_REVISION,
        "peft": False,
        "quantized_training": False,
        "snapshot_content_sha256": "1" * 64,
        "recipe_sha256": sha256_bytes(canonical_json_bytes(recipe)),
        "parameter_inventory_sha256": inventory["inventory_sha256"],
        "parameter_tensors": 2,
        "parameter_elements": 3,
    }


def _parameter_inventory() -> dict:
    rows = [
        {"name": "tail.weight", "elements": 2, "dtype": "torch.float32"},
        {"name": "tail.bias", "elements": 1, "dtype": "torch.float32"},
    ]
    return {
        "parameter_tensors": 2,
        "parameter_elements": 3,
        "trainable_parameter_tensors": 2,
        "trainable_parameter_elements": 3,
        "parameters": [{**row, "requires_grad": True} for row in rows],
        "inventory_sha256": sha256_bytes(canonical_json_bytes(rows)),
    }


def _training() -> PortableTrainingDataset:
    supervision = {
        "train-pass": {
            "candidate_id": "train-pass",
            "binary_label": "PASS",
            "proposed_split": "train",
        },
        "train-rewrite": {
            "candidate_id": "train-rewrite",
            "binary_label": "REWRITE",
            "proposed_split": "train",
        },
    }
    return PortableTrainingDataset(
        dataset_revision="v8",
        input_identity={"fixture": "train"},
        rubric="fixture",
        packets={key: {"candidate_id": key, "packet": {}} for key in supervision},
        supervision=supervision,
        pairs={
            "pair": {
                "pair_id": "pair",
                "kind": "boundary",
                "preferred_candidate_id": "train-pass",
                "dispreferred_candidate_id": "train-rewrite",
            }
        },
        membership={
            "schema_version": 1,
            "dataset_revision": "v8",
            "stages": {
                "fixture": {"candidate_ids": sorted(supervision), "pair_ids": ["pair"]}
            },
        },
    )


def _supervision(candidate_id: str, label: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "binary_label": label,
        "proposed_split": "validation",
        "slices": ["fixture"],
        "publication_class": "status",
        "completion_state": "complete",
        "actor_role": "producer",
        "hard_focus": "none",
        "length_bucket": "short",
        "style": "plain",
        "unicode": False,
    }


def _validation() -> ValidationDataset:
    supervision = {
        "pass-a": _supervision("pass-a", "PASS"),
        "rewrite-a": _supervision("rewrite-a", "REWRITE"),
        "pass-b": _supervision("pass-b", "PASS"),
        "rewrite-b": _supervision("rewrite-b", "REWRITE"),
    }
    return ValidationDataset(
        input_identity={"fixture": "validation"},
        rubric="fixture",
        packets={key: {"candidate_id": key, "packet": {}} for key in supervision},
        supervision=supervision,
        pairs={
            "boundary": {
                "pair_id": "boundary",
                "kind": "boundary",
                "target_dimension": "minimum_publication_quality",
                "preferred_candidate_id": "pass-a",
                "dispreferred_candidate_id": "rewrite-a",
            },
            "within": {
                "pair_id": "within",
                "kind": "within_pass",
                "target_dimension": "clarity",
                "preferred_candidate_id": "pass-b",
                "dispreferred_candidate_id": "rewrite-b",
            },
        },
    )


class _ControllerAdapter:
    def __init__(self) -> None:
        self.scope = None

    def plan082_runtime_identity(self) -> dict:
        return _runtime_identity()

    def assert_fresh_exact_base(self, repository: str, revision: str) -> None:
        if (repository, revision) != (MODEL_REPOSITORY, MODEL_REVISION):
            raise AssertionError

    def training_state_codec_id(self) -> str:
        return "plan082-fixture-v1"

    def write_training_state(self, path: Path, value: dict) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def read_training_state(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def training_states_equal(self, left: object, right: object) -> bool:
        return left == right

    def configure_trainable_scope(self, scope: TrainableScope) -> None:
        self.scope = scope

    def assert_trainable_scope(self, scope: TrainableScope) -> None:
        if self.scope != scope:
            raise AssertionError

    def evaluate_validation(self, dataset: ValidationDataset) -> dict:
        return {
            "raw_logits": {
                "pass-a": 1.0,
                "rewrite-a": -1.0,
                "pass-b": 0.5,
                "rewrite-b": -0.5,
            },
            "gradient_access": False,
            "training_state_unchanged": True,
            "validation_identity_sha256": validation_identity_sha256(dataset),
        }


class _Parameter:
    def __init__(self, elements: int) -> None:
        self.elements = elements
        self.dtype = "torch.bfloat16"
        self.requires_grad = True
        self.grad = None

    def numel(self) -> int:
        return self.elements

    def requires_grad_(self, value: bool) -> None:
        self.requires_grad = value


class _Model:
    def __init__(self) -> None:
        self.rows = {
            "tail.weight": _Parameter(2),
            "tail.bias": _Parameter(1),
        }
        self.training = True

    def named_parameters(self):
        return list(self.rows.items())

    def parameters(self):
        return list(self.rows.values())

    def train(self) -> None:
        self.training = True

    def eval(self) -> None:
        self.training = False


class _Optimizer:
    def __init__(self, parameters, **_kwargs) -> None:
        self.param_groups = [{"params": list(parameters)}]
        self.state = {}

    def add_param_group(self, group: dict) -> None:
        self.param_groups.append(group)

    def state_dict(self) -> dict:
        return {"groups": len(self.param_groups)}


class _Scheduler:
    def __init__(self, optimizer, _function) -> None:
        self.optimizer = optimizer
        self.base_lrs = [1e-5]
        self._last_lr = [1e-5]

    def state_dict(self) -> dict:
        return {"base_lrs": list(self.base_lrs)}


class _Torch:
    class optim:
        AdamW = _Optimizer

        class lr_scheduler:
            LambdaLR = _Scheduler

    @staticmethod
    def inference_mode():
        return nullcontext()

    @staticmethod
    def is_tensor(_value: object) -> bool:
        return False


class _Tokenizer:
    pad_token_id = 151654
    bos_token_id = None
    eos_token_id = 151645
    padding_side = "left"


class _Scalar:
    def __init__(self, value: float) -> None:
        self.value = value

    def float(self):
        return self

    def item(self) -> float:
        return self.value


class _Vector:
    def __getitem__(self, index: int) -> _Scalar:
        return _Scalar(float(index + 1))


class _EvalAdapter(TorchContinuousTrainingAdapter):
    def _forward(self, tokenized, candidate_ids):
        del tokenized, candidate_ids
        return _Vector()


def _component_adapter(adapter_type=TorchContinuousTrainingAdapter):
    return adapter_type.from_components(
        torch_module=_Torch,
        transformers_module=SimpleNamespace(),
        model=_Model(),
        tokenizer=_Tokenizer(),
        device="fixture",
        recipe=read_json(RECIPE_PATH),
        snapshot_root=Path("/fixture/model"),
        snapshot_receipt={"snapshot_content_sha256": "1" * 64},
        runtime_facts={
            key: value
            for key, value in _runtime_identity().items()
            if key
            not in {
                "snapshot_content_sha256",
                "recipe_sha256",
                "parameter_inventory_sha256",
                "parameter_tensors",
                "parameter_elements",
            }
        },
    )


def _data_receipt() -> dict:
    return {
        "schema": DATA_BUNDLE_SCHEMA,
        "status": "verified",
        "bundle_manifest_sha256": "3" * 64,
        "content_sha256": "4" * 64,
        "data_export_sha256": "5" * 64,
        "file_count": 4,
        "train_candidate_count": 128,
        "train_pair_count": 58,
        "validation_candidate_count": 55,
        "validation_pair_count": 26,
        "commissioning_candidate_count": 6,
        "commissioning_pair_count": 2,
        "unseen_test_rows": 0,
    }


class Plan082TrainingTests(unittest.TestCase):
    def test_recipe_and_scope_schedule_are_typed_but_not_hardcoded(self) -> None:
        recipe = validate_recipe(read_json(RECIPE_PATH))
        self.assertEqual(recipe["macro_update"], "one_full_v8_train_cohort")
        spec = _run_spec()
        self.assertEqual(
            frozen_scope_history(spec),
            [
                {"effective_before_update": 1, "scope": spec["initial_scope"]},
                {
                    "effective_before_update": 2,
                    "scope": spec["scope_schedule"][0]["scope"],
                },
            ],
        )
        bad = {
            **spec,
            "scope_schedule": [
                {
                    "after_observation_step": 3,
                    "scope": spec["scope_schedule"][0]["scope"],
                }
            ],
        }
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan082_scope_schedule_invalid"
        ):
            validate_run_spec(bad)
        reordered = copy.deepcopy(spec)
        reordered["scope_schedule"][0]["scope"]["parameter_names"] = [
            "tail.bias",
            "tail.weight",
        ]
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan082_scope_schedule_order_invalid"
        ):
            validate_run_spec(reordered)

    def test_git_archive_extracts_and_verifies_without_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            for relative in SOURCE_PATHS:
                path = repo / relative
                if relative == "eval/rondo_eval/publication_critic":
                    path = path / "full_model_training/plan082_bundle.py"
                elif relative == "training/publication-critic-plan082":
                    path = path / "README.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"fixture:{relative}\n", encoding="utf-8")
            for command in (
                ["git", "init", "-q"],
                ["git", "config", "user.email", "plan082@example.invalid"],
                ["git", "config", "user.name", "Plan 082"],
                ["git", "add", "."],
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "-qm",
                    "fixture",
                ],
            ):
                subprocess.run(command, cwd=repo, check=True, timeout=20)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            ).stdout.strip()
            archive = root / "source.tar"
            created = create_source_archive(
                repo,
                archive,
                source_commit=commit,
            )
            extracted = root / "extracted"
            observed = extract_source_archive(
                archive,
                extracted,
                expected_sha256=created["archive_sha256"],
                expected_commit=commit,
            )
            self.assertEqual(observed, created)
            self.assertFalse((extracted / ".git").exists())

    def test_executing_source_rejects_wrong_root_and_receipt(self) -> None:
        receipt = {
            "schema": SOURCE_BUNDLE_SCHEMA,
            "commit": "6" * 40,
            "archive_bytes": 100,
            "archive_sha256": "7" * 64,
            "source_content_sha256": "8" * 64,
            "file_count": 20,
            "directory_count": 4,
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt_path = root / "receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan082_executing_source_root_mismatch"
            ):
                _verify_executing_source(
                    source_archive=root / "source.tar",
                    source_root=root,
                    receipt_path=receipt_path,
                )
            executing_root = (
                Path(
                    __import__(
                        "rondo_eval.publication_critic.full_model_training.plan082_cli",
                        fromlist=["__file__"],
                    ).__file__
                )
                .resolve()
                .parents[4]
            )
            with (
                mock.patch(
                    "rondo_eval.publication_critic.full_model_training.plan082_cli."
                    "verify_source_archive",
                    return_value={**receipt, "archive_sha256": "9" * 64},
                ),
                self.assertRaisesRegex(
                    FullModelTrainingError, "plan082_source_receipt_mismatch"
                ),
            ):
                _verify_executing_source(
                    source_archive=root / "source.tar",
                    source_root=executing_root,
                    receipt_path=receipt_path,
                )

    def test_real_controller_layer_does_not_flip_fixture_candidate_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec = _run_spec()
            controller = Plan082ContinuousTrainingController(
                route_contract=read_json(PLAN081_ROUTE),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                initial_scope=TrainableScope.from_value(spec["initial_scope"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=_training(),
                validation_dataset=_validation(),
                artifact_store=Plan081ArtifactStore(Path(directory)),
            )
            controller.begin_process(
                {"instance_id": "a" * 32, "hostname": "fixture", "pid": 11}
            )
            result = controller.initialize(_ControllerAdapter())
        self.assertEqual(controller.state["schema"], CONTROLLER_SCHEMA)
        self.assertEqual(
            controller.state["evidence_kind"],
            "torch_real_direct_original_parameters",
        )
        self.assertFalse(result["selection"]["research_candidate_eligible"])
        self.assertFalse(result["claims"]["research_candidate_produced"])

    def test_controller_requires_real_runtime_and_fresh_base(self) -> None:
        class MissingRuntime(_ControllerAdapter):
            plan082_runtime_identity = None

        with tempfile.TemporaryDirectory() as directory:
            spec = _run_spec()
            controller = Plan082ContinuousTrainingController(
                route_contract=read_json(PLAN081_ROUTE),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                initial_scope=TrainableScope.from_value(spec["initial_scope"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=_training(),
                validation_dataset=_validation(),
                artifact_store=Plan081ArtifactStore(Path(directory)),
            )
            controller.begin_process(
                {"instance_id": "b" * 32, "hostname": "fixture", "pid": 12}
            )
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan082_real_adapter_required"
            ):
                controller.initialize(MissingRuntime())

    def test_checkpoint_resumes_in_new_process_and_continues(self) -> None:
        spec = _run_spec()
        observations = {
            0: _plan081_logits(0.0),
            1: _plan081_logits(0.5),
            2: _plan081_logits(0.75),
            3: _plan081_logits(1.0),
        }
        first_identity = {
            "instance_id": "1" * 32,
            "hostname": "fixture",
            "pid": 101,
        }
        second_identity = {
            "instance_id": "2" * 32,
            "hostname": "fixture",
            "pid": 102,
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                _Plan081FakeAdapter,
                "plan082_runtime_identity",
                lambda _self: _runtime_identity(),
                create=True,
            ),
        ):
            store = Plan081ArtifactStore(Path(directory))
            first_adapter = _Plan081FakeAdapter(observations)
            first = Plan082ContinuousTrainingController(
                route_contract=read_json(PLAN081_ROUTE),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                initial_scope=TrainableScope.from_value(spec["initial_scope"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=_training(),
                validation_dataset=_validation(),
                artifact_store=store,
            )
            first.begin_process(first_identity)
            first.bind_formal_freeze("f" * 64)
            first.initialize(first_adapter)
            run_scheduled(first, first_adapter, spec, stop_after=1)
            checkpoint_id = first.state["latest_checkpoint_id"]
            self.assertIsInstance(checkpoint_id, str)
            checkpoint = store.verify_checkpoint(checkpoint_id)

            second_adapter = _Plan081FakeAdapter(observations)
            resumed = Plan082ContinuousTrainingController.resume(
                route_contract=read_json(PLAN081_ROUTE),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=_training(),
                validation_dataset=_validation(),
                artifact_store=store,
                adapter=second_adapter,
                checkpoint_id=checkpoint_id,
            )
            self.assertEqual(
                resumed.state["plan082"]["process_identity"], first_identity
            )
            resumed.begin_process(second_identity)
            resumed.record_new_process_recovery(
                checkpoint_id,
                checkpoint["content_sha256"],
            )
            run_scheduled(resumed, second_adapter, spec)
            self.assertEqual(resumed.state["status"], "completed")
            self.assertEqual(resumed.state["current_step"], 3)
            self.assertEqual(resumed.state["plan082"]["formal_freeze_sha256"], "f" * 64)
            self.assertEqual(
                resumed.state["plan082"]["recovery_proven_checkpoints"],
                {checkpoint_id: checkpoint["content_sha256"]},
            )

    def test_process_receipt_exists_before_training_segment_can_interrupt(self) -> None:
        spec = _run_spec()
        adapter = _Plan081FakeAdapter({0: _plan081_logits(0.0)})
        source = {
            "schema": SOURCE_BUNDLE_SCHEMA,
            "commit": "6" * 40,
            "archive_bytes": 100,
            "archive_sha256": "7" * 64,
            "source_content_sha256": "8" * 64,
            "file_count": 20,
            "directory_count": 4,
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.object(
                _Plan081FakeAdapter,
                "plan082_runtime_identity",
                lambda _self: _runtime_identity(),
                create=True,
            ),
            mock.patch(
                "rondo_eval.publication_critic.full_model_training.plan082_cli."
                "run_scheduled",
                side_effect=FullModelTrainingError("simulated_interruption"),
            ),
        ):
            root = Path(directory)
            args = SimpleNamespace(
                formal_freeze=None,
                artifact_root=root / "artifacts",
                stop_after=1,
                process_receipt_output=root / "process.json",
                state_output=root / "state.json",
            )
            with self.assertRaisesRegex(
                FullModelTrainingError, "simulated_interruption"
            ):
                _run_with_adapter(
                    args,
                    resume=False,
                    source_receipt=source,
                    route=read_json(PLAN081_ROUTE),
                    data_receipt=_data_receipt(),
                    datasets=SimpleNamespace(
                        train=_training(),
                        validation=_validation(),
                    ),
                    run_spec=spec,
                    initial_scope=TrainableScope.from_value(spec["initial_scope"]),
                    control=ControlPlan.from_value(spec["control_plan"]),
                    comparison=ComparisonPolicy.from_value(spec["comparison_policy"]),
                    threshold=float(spec["report_threshold"]),
                    adapter=adapter,
                )
            receipt = _load_process_receipt(args.process_receipt_output)
            self.assertEqual(receipt["status"], "started")
            self.assertEqual(receipt["global_step"], 0)

    def test_adapter_records_actual_parameter_inventory_and_expansion(self) -> None:
        adapter = _component_adapter()
        inventory = adapter.parameter_inventory()
        self.assertEqual(inventory["parameter_tensors"], 2)
        self.assertEqual(inventory["parameter_elements"], 3)
        first = TrainableScope.from_value(_scope("tail", ["tail.weight"], 2))
        second = TrainableScope.from_value(
            _scope("expanded", ["tail.weight", "tail.bias"], 3)
        )
        adapter.configure_trainable_scope(first)
        adapter.assert_trainable_scope(first)
        self.assertFalse(adapter.model.rows["tail.bias"].requires_grad)
        adapter.configure_trainable_scope(second)
        adapter.assert_trainable_scope(second)
        self.assertEqual(len(adapter.optimizer.param_groups), 1)
        self.assertEqual(len(adapter.optimizer.param_groups[0]["params"]), 2)

    def test_validation_uses_no_gradient_and_preserves_training_state(self) -> None:
        adapter = _component_adapter(_EvalAdapter)
        scope = TrainableScope.from_value(_scope("tail", ["tail.weight"], 2))
        adapter.configure_trainable_scope(scope)
        dataset = _validation()
        identity = validation_identity_sha256(dataset)
        adapter._validation_cache[identity] = {
            candidate_id: SimpleNamespace(input_ids=(1,))
            for candidate_id in dataset.supervision
        }
        receipt = adapter.evaluate_validation(dataset)
        self.assertTrue(receipt["training_state_unchanged"])
        self.assertFalse(receipt["gradient_access"])
        adapter.model.rows["tail.weight"].grad = object()
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan082_validation_gradient_present"
        ):
            adapter.evaluate_validation(dataset)

    def test_numpy_rng_state_comparator_round_trips(self) -> None:
        class Array:
            __module__ = "numpy"

            def __init__(self, values: tuple[int, ...]) -> None:
                self.values = values
                self.shape = (len(values),)

        adapter = object.__new__(TorchContinuousTrainingAdapter)
        adapter.torch = SimpleNamespace(is_tensor=lambda _value: False)
        fake_numpy = SimpleNamespace(
            array_equal=lambda left, right: left.values == right.values
        )
        with mock.patch(
            "rondo_eval.publication_critic.full_model_training.plan082_adapter."
            "importlib.import_module",
            return_value=fake_numpy,
        ):
            self.assertTrue(adapter._values_equal(Array((1, 2)), Array((1, 2))))
            self.assertFalse(adapter._values_equal(Array((1, 2)), Array((1, 3))))

    def test_formal_freeze_precedes_namespace_and_is_only_candidate_gate(self) -> None:
        spec = _run_spec()
        route = read_json(PLAN081_ROUTE)
        runtime = _runtime_identity()
        source = {
            "schema": SOURCE_BUNDLE_SCHEMA,
            "commit": "6" * 40,
            "archive_bytes": 100,
            "archive_sha256": "7" * 64,
            "source_content_sha256": "8" * 64,
            "file_count": 20,
            "directory_count": 4,
        }
        retention = {
            "observations": "all_small_records",
            "snapshots": [
                "training_best",
                "latest",
                "turning_points",
                "best_checkpoint_observation",
            ],
            "checkpoints": [
                "latest",
                "best_checkpoint_observation",
                "turning_points",
                "recovery_proven",
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            freeze_path = root / "freeze.json"
            namespace = root / "formal-run"
            with mock.patch(
                "rondo_eval.publication_critic.full_model_training.plan082_formal.verify_data_bundle",
                return_value=_data_receipt(),
            ):
                freeze = create_formal_freeze(
                    freeze_path,
                    run_id="plan082-formal-fixture",
                    formal_namespace=namespace,
                    source_receipt=source,
                    data_bundle_root=root / "data",
                    route_contract=route,
                    runtime_identity=runtime,
                    parameter_inventory=_parameter_inventory(),
                    run_spec=spec,
                    retention=retention,
                )["freeze"]
            namespace.mkdir()
            with mock.patch(
                "rondo_eval.publication_critic.full_model_training.plan082_formal.verify_data_bundle",
                return_value=_data_receipt(),
            ):
                all_parameters = copy.deepcopy(spec)
                all_parameters["initial_scope"] = _scope(
                    "all",
                    ["tail.weight", "tail.bias"],
                    3,
                )
                all_parameters["scope_schedule"] = []
                with self.assertRaisesRegex(
                    FullModelTrainingError, "plan082_formal_scope_bounds_invalid"
                ):
                    create_formal_freeze(
                        root / "all-parameters-freeze.json",
                        run_id="plan082-formal-all-parameters",
                        formal_namespace=root / "all-parameters-run",
                        source_receipt=source,
                        data_bundle_root=root / "data",
                        route_contract=route,
                        runtime_identity=runtime,
                        parameter_inventory=_parameter_inventory(),
                        run_spec=all_parameters,
                        retention=retention,
                    )
                with self.assertRaisesRegex(
                    FullModelTrainingError, "plan082_formal_namespace_not_pristine"
                ):
                    create_formal_freeze(
                        root / "other-freeze.json",
                        run_id="plan082-formal-too-late",
                        formal_namespace=namespace,
                        source_receipt=source,
                        data_bundle_root=root / "data",
                        route_contract=route,
                        runtime_identity=runtime,
                        parameter_inventory=_parameter_inventory(),
                        run_spec=spec,
                        retention=retention,
                    )

        state = {
            "schema": CONTROLLER_SCHEMA,
            "status": "completed",
            "evidence_kind": "torch_real_direct_original_parameters",
            "plan082": {
                "runtime_identity": runtime,
                "process_identity": {
                    "instance_id": "c" * 32,
                    "hostname": "fixture",
                    "pid": 13,
                },
                "formal_freeze_sha256": freeze["freeze_content_sha256"],
                "recovery_proven_checkpoints": {
                    "checkpoint-attempt-0-step-1": "9" * 64
                },
            },
            "route_contract_sha256": freeze["route_contract_sha256"],
            "control_plan": spec["control_plan"],
            "comparison_policy": spec["comparison_policy"],
            "report_threshold": spec["report_threshold"],
            "scope_history": frozen_scope_history(spec),
            "scope_decisions": [
                {
                    "before_update": 2,
                    "scope": spec["scope_schedule"][0]["scope"],
                }
            ],
            "current_step": 3,
            "updates": [
                {"global_step": 1},
                {"global_step": 2},
                {"global_step": 3},
            ],
            "base": {"comparison_value": 0.0},
            "latest_checkpoint_id": "checkpoint-attempt-0-step-3",
            "observations": [
                {
                    "global_step": 1,
                    "comparison_value": 0.5,
                    "snapshot_id": "snapshot-attempt-0-step-1",
                    "checkpoint_id": "checkpoint-attempt-0-step-1",
                },
                {
                    "global_step": 2,
                    "comparison_value": 2.0,
                    "snapshot_id": "snapshot-attempt-0-step-2",
                    "checkpoint_id": None,
                },
                {
                    "global_step": 3,
                    "comparison_value": 1.0,
                    "snapshot_id": "snapshot-attempt-0-step-3",
                    "checkpoint_id": "checkpoint-attempt-0-step-3",
                },
            ],
            "selection": {
                "base_incumbent_snapshot_id": "exact-base-incumbent",
                "training_best_snapshot_id": "snapshot-attempt-0-step-2",
                "latest_snapshot_id": "snapshot-attempt-0-step-3",
                "control_candidate_snapshot_id": "snapshot-attempt-0-step-2",
            },
        }
        recovery = {
            "schema": RECOVERY_SCHEMA,
            "checkpoint_id": "checkpoint-attempt-0-step-1",
            "checkpoint_sha256": "9" * 64,
            "formal_freeze_sha256": freeze["freeze_content_sha256"],
            "run_id": freeze["run_id"],
            "formal_namespace": freeze["formal_namespace"],
            "runtime_identity_sha256": sha256_bytes(
                canonical_json_bytes(freeze["runtime_identity"])
            ),
            "source_process_id": "d" * 32,
            "recovery_process_id": "c" * 32,
            "fresh_adapter": True,
            "model_loaded": True,
            "optimizer_scheduler_rng_data_equal": True,
            "probe_update_completed": True,
        }
        result = finalize_formal_run(
            freeze=freeze,
            controller_state=state,
            recovery_receipt=recovery,
        )
        self.assertEqual(result["terminal"], "TRAINING_IMPROVEMENT_FOUND")
        self.assertEqual(
            result["research_candidate_checkpoint_id"],
            "checkpoint-attempt-0-step-3",
        )
        self.assertFalse(result["claims"]["product_go"])
        mismatched_process = copy.deepcopy(recovery)
        mismatched_process["recovery_process_id"] = "e" * 32
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan082_formal_state_not_frozen"
        ):
            finalize_formal_run(
                freeze=freeze,
                controller_state=state,
                recovery_receipt=mismatched_process,
            )
        malformed_process = copy.deepcopy(recovery)
        malformed_process["source_process_id"] = "source"
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan082_recovery_receipt_invalid"
        ):
            finalize_formal_run(
                freeze=freeze,
                controller_state=state,
                recovery_receipt=malformed_process,
            )
        no_improvement = copy.deepcopy(state)
        no_improvement["base"]["comparison_value"] = 2.0
        no_improvement["selection"].update(
            {
                "training_best_snapshot_id": "snapshot-attempt-0-step-2",
                "control_candidate_snapshot_id": None,
            }
        )
        self.assertEqual(
            finalize_formal_run(
                freeze=freeze,
                controller_state=no_improvement,
                recovery_receipt=recovery,
            )["terminal"],
            "VALID_NO_IMPROVEMENT",
        )

    def test_new_process_receipt_rejects_same_os_process(self) -> None:
        source = {"instance_id": "d" * 32, "hostname": "pod", "pid": 44}
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan082_recovery_process_not_new"
        ):
            _require_new_process(
                source,
                {"instance_id": "e" * 32, "hostname": "pod", "pid": 44},
            )
        _require_new_process(
            source,
            {"instance_id": "f" * 32, "hostname": "pod", "pid": 45},
        )


if __name__ == "__main__":
    unittest.main()
