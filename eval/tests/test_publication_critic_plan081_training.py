import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training import checkpoint  # noqa: E402
from rondo_eval.publication_critic.full_model_training.contract import (  # noqa: E402
    FullModelTrainingError,
    read_json,
)
from rondo_eval.publication_critic.full_model_training.data import (  # noqa: E402
    PortableTrainingDataset,
)
from rondo_eval.publication_critic.full_model_training.plan066_contract import (  # noqa: E402
    validate_plan066_recipe,
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
    load_cloud_handoff,
    load_route_contract,
    validate_route_contract,
)
from rondo_eval.publication_critic.full_model_training.plan081_controller import (  # noqa: E402
    ContinuousTrainingController,
)
from rondo_eval.publication_critic.full_model_training.plan081_observation import (  # noqa: E402
    build_validation_observation,
    training_identity_sha256,
    validation_identity_sha256,
)


PLAN081_ROOT = REPO_ROOT / "training/publication-critic-plan081"


def _scope(name: str, parameters: tuple[str, ...], elements: int) -> TrainableScope:
    return TrainableScope.from_value(
        {
            "scope_id": name,
            "update_method": "direct_original_parameter_update",
            "parameter_names": list(parameters),
            "trainable_parameter_elements": elements,
            "reason": f"fixture-{name}",
        }
    )


def _control_plan(*, maximum: int = 4) -> ControlPlan:
    observations = list(range(1, maximum + 1))
    checkpoints = [2, maximum] if maximum > 2 else [maximum]
    return ControlPlan.from_value(
        {
            "maximum_updates": maximum,
            "observation_steps": observations,
            "checkpoint_steps": checkpoints,
            "turning_point_limit": 2,
        }
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


def _validation_dataset() -> ValidationDataset:
    supervision = {
        "pass-a": _supervision("pass-a", "PASS"),
        "rewrite-a": _supervision("rewrite-a", "REWRITE"),
        "pass-b": _supervision("pass-b", "PASS"),
        "rewrite-b": _supervision("rewrite-b", "REWRITE"),
    }
    return ValidationDataset(
        input_identity={"fixture": True},
        rubric="fixture rubric",
        packets={
            candidate_id: {"candidate_id": candidate_id, "packet": {}}
            for candidate_id in supervision
        },
        supervision=supervision,
        pairs={
            "boundary-1": {
                "pair_id": "boundary-1",
                "kind": "boundary",
                "target_dimension": "minimum_publication_quality",
                "preferred_candidate_id": "pass-a",
                "dispreferred_candidate_id": "rewrite-a",
            },
            "within-1": {
                "pair_id": "within-1",
                "kind": "within_pass",
                "target_dimension": "clarity",
                "preferred_candidate_id": "pass-b",
                "dispreferred_candidate_id": "rewrite-b",
            },
        },
    )


def _training_dataset() -> PortableTrainingDataset:
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
        input_identity={"fixture": "plan081-train-only"},
        rubric="fixture rubric",
        packets={
            candidate_id: {"candidate_id": candidate_id, "packet": {}}
            for candidate_id in supervision
        },
        supervision=supervision,
        pairs={
            "train-boundary": {
                "pair_id": "train-boundary",
                "kind": "boundary",
                "preferred_candidate_id": "train-pass",
                "dispreferred_candidate_id": "train-rewrite",
            }
        },
        membership={
            "schema_version": 1,
            "dataset_revision": "v8",
            "stages": {
                "fixture": {
                    "candidate_ids": sorted(supervision),
                    "pair_ids": ["train-boundary"],
                }
            },
        },
    )


def _overlapping_training_dataset() -> PortableTrainingDataset:
    validation = _validation_dataset()
    supervision = {
        candidate_id: {
            **dict(row),
            "proposed_split": "train",
        }
        for candidate_id, row in validation.supervision.items()
    }
    return PortableTrainingDataset(
        dataset_revision="v8",
        input_identity={"fixture": "overlapping-train"},
        rubric=validation.rubric,
        packets=validation.packets,
        supervision=supervision,
        pairs=validation.pairs,
        membership={
            "schema_version": 1,
            "dataset_revision": "v8",
            "stages": {
                "fixture": {
                    "candidate_ids": sorted(supervision),
                    "pair_ids": sorted(validation.pairs),
                }
            },
        },
    )


def _logits(boundary_margin: float, *, within_margin: float = 1.0) -> dict[str, float]:
    return {
        "pass-a": boundary_margin / 2.0,
        "rewrite-a": -boundary_margin / 2.0,
        "pass-b": within_margin / 2.0,
        "rewrite-b": -within_margin / 2.0,
    }


class _FakeAdapter:
    def __init__(
        self,
        observations: dict[int, dict[str, float]],
        *,
        codec_id: str = "fixture-python-literal-v1",
    ) -> None:
        self.observations = observations
        self.codec_id = codec_id
        self.step = 0
        self.scope = None
        self.events: list[str] = []
        self.validation_calls = 0
        self.update_calls = 0
        self.data_cursor: dict = {"fixture_update": 0}
        self.invalid_receipt_steps: set[int] = set()
        self.validation_failure_steps: set[int] = set()
        self.snapshot_failure_steps: set[int] = set()
        self.checkpoint_writer_failure_steps: set[int] = set()
        self.wrong_validation_identity = False
        self.reader_failure = False
        self.reader_calls = 0
        self.received_validation_datasets: list[ValidationDataset] = []
        self.restored_typed_state = False

    def configure_trainable_scope(self, scope: TrainableScope) -> None:
        self.events.append(f"configure:{scope.scope_id}")
        self.scope = scope

    def assert_trainable_scope(self, scope: TrainableScope) -> None:
        if self.scope != scope:
            raise FullModelTrainingError("fixture_scope_mismatch")
        self.events.append(f"assert:{scope.scope_id}")

    def apply_update(
        self,
        step: int,
        scope: TrainableScope,
        training_dataset: PortableTrainingDataset,
    ) -> dict:
        if any(
            row["proposed_split"] != "train"
            for row in training_dataset.supervision.values()
        ):
            raise AssertionError("fixture adapter received a non-training row")
        self.update_calls += 1
        self.step = step
        self.data_cursor = {"fixture_update": step}
        receipt = {
            "global_step": step,
            "training_split": "train",
            "validation_candidates_consumed": 0,
            "unseen_candidates_consumed": 0,
            "training_identity_sha256": training_identity_sha256(training_dataset),
            "training_candidate_count": len(training_dataset.supervision),
            "training_pair_count": len(training_dataset.pairs),
            "scope": scope.as_dict(),
            "data_cursor": dict(self.data_cursor),
        }
        if step in self.invalid_receipt_steps:
            receipt["training_candidate_count"] += 1
        return receipt

    def evaluate_validation(self, dataset: ValidationDataset) -> dict:
        before = (self.step, self.scope)
        self.validation_calls += 1
        self.received_validation_datasets.append(dataset)
        if self.step in self.validation_failure_steps:
            raise FullModelTrainingError("fixture_validation_failed")
        receipt = {
            "raw_logits": dict(self.observations[self.step]),
            "gradient_access": False,
            "training_state_unchanged": True,
            "validation_identity_sha256": (
                "0" * 64
                if self.wrong_validation_identity
                else validation_identity_sha256(dataset)
            ),
        }
        if before != (self.step, self.scope):
            raise AssertionError("fixture validation mutated training state")
        return receipt

    def save_model(self, root: Path) -> None:
        if (
            root.parent.parent.name == "model-snapshots"
            and self.step in self.snapshot_failure_steps
        ):
            raise FullModelTrainingError("fixture_snapshot_failed")
        (root / "fake-model.json").write_text(
            json.dumps(
                {
                    "step": self.step,
                    "scope": self.scope.as_dict(),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

    def load_model(self, root: Path) -> None:
        value = json.loads((root / "fake-model.json").read_text(encoding="utf-8"))
        self.step = int(value["step"])
        self.events.append(f"load:{self.step}")

    def capture_training_state(self) -> dict:
        return {
            "optimizer": {
                "step": self.step,
                "scope_id": self.scope.scope_id,
                "slots": {7: (b"\x00\xff", self.step)},
            },
            "scheduler": {"milestones": (self.step, self.step + 1)},
            "rng": {"fixture_token": (b"rng", self.step * 17)},
            "data": dict(self.data_cursor),
        }

    def training_state_codec_id(self) -> str:
        return self.codec_id

    def write_training_state(self, path: Path, value: dict) -> None:
        if self.step in self.checkpoint_writer_failure_steps:
            raise FullModelTrainingError("fixture_checkpoint_writer_failed")
        path.write_bytes(b"PLAN081-LITERAL-V1\n" + repr(value).encode("utf-8"))

    def read_training_state(self, path: Path) -> dict:
        self.reader_calls += 1
        if self.reader_failure:
            raise ValueError("fixture reader failed")
        raw = path.read_bytes()
        prefix = b"PLAN081-LITERAL-V1\n"
        if not raw.startswith(prefix):
            raise ValueError("fixture codec header invalid")
        value = ast.literal_eval(raw[len(prefix) :].decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("fixture state is not a mapping")
        return value

    def restore_training_state(self, value: dict) -> None:
        if self.scope is None:
            raise FullModelTrainingError("fixture_restore_before_scope")
        if value["optimizer"]["scope_id"] != self.scope.scope_id:
            raise FullModelTrainingError("fixture_optimizer_scope_mismatch")
        self.events.append(f"restore:{self.scope.scope_id}")
        self.restored_typed_state = (
            value["optimizer"]["slots"][7] == (b"\x00\xff", self.step)
            and isinstance(value["scheduler"]["milestones"], tuple)
            and isinstance(value["rng"]["fixture_token"], tuple)
        )
        self.step = int(value["optimizer"]["step"])
        self.data_cursor = dict(value["data"])

    def assert_data_cursor(self, value: dict) -> None:
        if self.data_cursor != value:
            raise FullModelTrainingError("fixture_data_cursor_mismatch")
        self.events.append(f"data:{self.data_cursor['fixture_update']}")


class Plan081ContractTests(unittest.TestCase):
    def test_route_binds_exact_non_peft_model_and_leaves_recipe_open(self) -> None:
        route = load_route_contract(PLAN081_ROOT / "route-contract-v1.json")
        self.assertEqual(
            route["model"],
            {
                "repository": "Skywork/Skywork-Reward-V2-Qwen3-1.7B",
                "revision": "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc",
                "scalar": "logits[:,0]",
                "projection": "stable_sigmoid_v1",
                "direction": "higher_is_better",
            },
        )
        self.assertEqual(route["update_route"]["initial_scope"], "partial_runtime_inventory")
        self.assertFalse(route["update_route"]["peft"])
        self.assertFalse(route["update_route"]["lora"])
        self.assertFalse(route["update_route"]["qlora"])
        self.assertEqual(route["update_route"]["recipe_fields_fixed_here"], [])
        self.assertIn("optimizer", route["update_route"]["recipe_fields_deferred"])

        changed = copy.deepcopy(route)
        changed["update_route"]["lora"] = True
        with self.assertRaisesRegex(FullModelTrainingError, "plan081_update_route_invalid"):
            validate_route_contract(changed)

    def test_cloud_handoff_is_an_unproven_unapproved_boundary(self) -> None:
        handoff = load_cloud_handoff(PLAN081_ROOT / "cloud-handoff-v1.json")
        self.assertEqual(
            [(row["gpu"], row["vram_gb"]) for row in handoff["hardware_priority"]],
            [("NVIDIA A40", 48), ("NVIDIA L40S", 48)],
        )
        self.assertEqual(handoff["limits"]["gpu_count"], 1)
        self.assertLessEqual(handoff["limits"]["maximum_window_hours"], 12)
        self.assertLessEqual(handoff["limits"]["maximum_external_cost_usd"], 15)
        self.assertFalse(handoff["retained_plan079_volume"]["required"])
        self.assertEqual(handoff["authorization"], "not_granted")
        self.assertFalse(any(handoff["claims"].values()))

    def test_historical_plan066_recipe_and_checkpoint_remain_exact(self) -> None:
        recipe = read_json(REPO_ROOT / "training/publication-critic-plan066/recipe-v1.json")
        validated = validate_plan066_recipe(recipe, require_frozen=True)
        self.assertEqual(validated["stage_order"], ["C1", "C2", "C3"])
        self.assertEqual(validated["updates_per_stage"], {"C1": 1, "C2": 1, "C3": 1})
        with self.assertRaisesRegex(FullModelTrainingError, "checkpoint_progress_invalid"):
            checkpoint._validate_progress(
                {
                    "stage": "continuous",
                    "global_step": 4,
                    "stage_update": 4,
                    "completed_stages": [],
                    "data_cursor": {},
                }
            )

    def test_public_dataclass_constructors_cannot_bypass_runtime_validation(self) -> None:
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan081_comparison_tolerance_invalid"
        ):
            ComparisonPolicy("boundary_pair_mean_margin", -0.1)
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan081_control_plan_invalid"
        ):
            ControlPlan(
                maximum_updates=2,
                observation_steps=(1, 2),
                checkpoint_steps=(1,),
                turning_point_limit=2,
            )


class Plan081ObservationTests(unittest.TestCase):
    def test_shared_metrics_keep_full_curve_and_raw_signed_pair_margins(self) -> None:
        observation = build_validation_observation(
            _validation_dataset(),
            _logits(2.0),
            global_step=1,
            scope=_scope("partial", ("score_head",), 10),
            policy=ComparisonPolicy("boundary_pair_mean_margin", 0.05),
        )
        self.assertEqual(observation["metrics"]["boundary_pairs"]["strict_wins"], 1)
        self.assertGreater(len(observation["operating_curve"]), 1)
        boundary = next(
            row for row in observation["pair_margins"] if row["kind"] == "boundary"
        )
        self.assertEqual(boundary["signed_raw_margin"], 2.0)
        self.assertEqual(boundary["direction"], "preferred")
        self.assertFalse(observation["validation"]["gradient_access"])
        self.assertFalse(observation["validation"]["feeds_parameter_updates"])
        self.assertEqual(observation["comparison_value"], 2.0)

    def test_observation_rejects_non_validation_rows_and_nonfinite_scores(self) -> None:
        dataset = _validation_dataset()
        changed = copy.deepcopy(dataset.supervision)
        changed["pass-a"]["proposed_split"] = "train"
        bad_dataset = ValidationDataset(
            input_identity=dataset.input_identity,
            rubric=dataset.rubric,
            packets=dataset.packets,
            supervision=changed,
            pairs=dataset.pairs,
        )
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan081_observation_requires_validation_split"
        ):
            build_validation_observation(
                bad_dataset,
                _logits(2.0),
                global_step=0,
                scope=_scope("partial", ("score_head",), 10),
                policy=ComparisonPolicy("roc_auc", 0.0),
            )
        scores = _logits(2.0)
        scores["pass-a"] = float("nan")
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan081_observation_raw_logit_invalid"
        ):
            build_validation_observation(
                dataset,
                scores,
                global_step=0,
                scope=_scope("partial", ("score_head",), 10),
                policy=ComparisonPolicy("roc_auc", 0.0),
            )

    def test_training_identity_rejects_extra_or_mislabeled_packet(self) -> None:
        dataset = _training_dataset()
        packets = copy.deepcopy(dataset.packets)
        packets["unseen-extra"] = {
            "candidate_id": "unseen-extra",
            "packet": {"body": "must not reach adapter"},
        }
        changed = PortableTrainingDataset(
            dataset_revision=dataset.dataset_revision,
            input_identity=dataset.input_identity,
            rubric=dataset.rubric,
            packets=packets,
            supervision=dataset.supervision,
            pairs=dataset.pairs,
            membership=dataset.membership,
        )
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan081_training_input_not_train_only_v8"
        ):
            training_identity_sha256(changed)


class Plan081ControllerTests(unittest.TestCase):
    def _controller(
        self,
        root: Path,
        adapter: _FakeAdapter,
        *,
        maximum: int = 4,
        control_plan: ControlPlan | None = None,
        comparison_policy: ComparisonPolicy | None = None,
    ):
        store = Plan081ArtifactStore(root)
        controller = ContinuousTrainingController(
            route_contract=load_route_contract(PLAN081_ROOT / "route-contract-v1.json"),
            control_plan=control_plan or _control_plan(maximum=maximum),
            initial_scope=_scope("partial", ("score_head",), 10),
            comparison_policy=comparison_policy
            or ComparisonPolicy("boundary_pair_mean_margin", 0.05),
            training_dataset=_training_dataset(),
            validation_dataset=_validation_dataset(),
            artifact_store=store,
        )
        controller.initialize(adapter)
        return controller, store

    def test_actual_training_best_is_not_filtered_by_candidate_tolerance(self) -> None:
        observations = {0: _logits(2.0), 1: _logits(2.04), 2: _logits(2.08)}
        with tempfile.TemporaryDirectory() as directory:
            adapter = _FakeAdapter(observations)
            controller, _store = self._controller(Path(directory), adapter, maximum=2)
            result = controller.run(adapter)
            step_two = controller.state["observations"][-1]
        self.assertEqual(step_two["comparisons"]["base"], "improved")
        self.assertEqual(
            result["selection"]["training_best_snapshot_id"],
            "snapshot-attempt-000-step-000002",
        )
        self.assertEqual(
            result["selection"]["control_candidate_snapshot_id"],
            "snapshot-attempt-000-step-000002",
        )

    def test_sparse_observation_retains_first_expanded_scope_turning_point(self) -> None:
        plan = ControlPlan.from_value(
            {
                "maximum_updates": 5,
                "observation_steps": [1, 4, 5],
                "checkpoint_steps": [5],
                "turning_point_limit": 2,
            }
        )
        observations = {
            0: _logits(2.0),
            1: _logits(3.0),
            4: _logits(1.0),
            5: _logits(2.5),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(
                root, adapter, control_plan=plan
            )
            controller.run(adapter, stop_after=1)
            controller.schedule_scope_expansion(
                _scope("expanded", ("score_head", "upper_block"), 20)
            )
            result = controller.run(adapter)
            step_four = next(
                row
                for row in controller.state["observations"]
                if row["global_step"] == 4
            )
            self.assertIn(
                "trainable_scope_expanded", step_four["turning_point_reasons"]
            )
            self.assertEqual(
                {path.name for path in (root / "model-snapshots").iterdir()},
                {
                    "snapshot-attempt-000-step-000001",
                    "snapshot-attempt-000-step-000004",
                    "snapshot-attempt-000-step-000005",
                },
            )
            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=plan,
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id="checkpoint-attempt-000-step-000005",
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")
        self.assertTrue(resumed_adapter.restored_typed_state)

    def test_controller_rejects_train_validation_candidate_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_train_validation_overlap"
            ):
                ContinuousTrainingController(
                    route_contract=load_route_contract(
                        PLAN081_ROOT / "route-contract-v1.json"
                    ),
                    control_plan=_control_plan(maximum=2),
                    initial_scope=_scope("partial", ("score_head",), 10),
                    comparison_policy=ComparisonPolicy(
                        "boundary_pair_mean_margin", 0.05
                    ),
                    training_dataset=_overlapping_training_dataset(),
                    validation_dataset=_validation_dataset(),
                    artifact_store=Plan081ArtifactStore(Path(directory)),
                )

    def test_validation_receipt_binds_typed_declared_cohort(self) -> None:
        observations = {0: _logits(2.0), 1: _logits(2.5), 2: _logits(3.0)}
        with tempfile.TemporaryDirectory() as directory:
            adapter = _FakeAdapter(observations)
            adapter.wrong_validation_identity = True
            controller = ContinuousTrainingController(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(maximum=2),
                initial_scope=_scope("partial", ("score_head",), 10),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=Plan081ArtifactStore(Path(directory)),
            )
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_validation_receipt_invalid"
            ):
                controller.initialize(adapter)
            self.assertIs(
                adapter.received_validation_datasets[0], controller.validation_dataset
            )

    def test_pause_and_continue_same_instance_keeps_monotonic_progress(self) -> None:
        observations = {0: _logits(2.0), 1: _logits(2.5), 2: _logits(2.8)}
        with tempfile.TemporaryDirectory() as directory:
            adapter = _FakeAdapter(observations)
            controller, _store = self._controller(Path(directory), adapter, maximum=2)
            paused = controller.run(adapter, stop_after=1)
            finished = controller.run(adapter)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(paused["global_step"], 1)
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["global_step"], 2)
        self.assertEqual(adapter.update_calls, 2)
        self.assertEqual(adapter.validation_calls, 3)  # base plus two observations
        self.assertEqual(
            [record["global_step"] for record in controller.state["observations"]],
            [1, 2],
        )

    def test_no_improvement_keeps_base_incumbent_separate_from_internal_best(self) -> None:
        observations = {0: _logits(2.0), 1: _logits(1.0), 2: _logits(1.5)}
        with tempfile.TemporaryDirectory() as directory:
            adapter = _FakeAdapter(observations)
            controller, _store = self._controller(Path(directory), adapter, maximum=2)
            result = controller.run(adapter)
        selection = result["selection"]
        self.assertEqual(selection["base_incumbent_snapshot_id"], "exact-base-incumbent")
        self.assertEqual(
            selection["training_best_snapshot_id"],
            "snapshot-attempt-000-step-000002",
        )
        self.assertEqual(
            selection["latest_snapshot_id"],
            "snapshot-attempt-000-step-000002",
        )
        self.assertEqual(selection["target_candidate_state"], "no_improvement")
        self.assertIsNone(selection["control_candidate_snapshot_id"])
        self.assertIsNone(selection["research_candidate_snapshot_id"])
        self.assertFalse(selection["research_candidate_eligible"])

    def test_invalid_update_receipt_requires_fresh_checkpoint_resume(self) -> None:
        observations = {
            0: _logits(2.0),
            1: _logits(2.5),
            2: _logits(2.8),
            3: _logits(3.0),
            4: _logits(3.2),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter)
            controller.run(adapter, stop_after=2)
            controller.schedule_scope_expansion(
                _scope("expanded", ("score_head", "upper_block"), 20)
            )
            adapter.invalid_receipt_steps.add(3)
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_update_receipt_invalid"
            ):
                controller.run(adapter, stop_after=3)
            self.assertEqual(controller.state["status"], "recovery_required")
            self.assertEqual(controller.state["current_step"], 2)
            self.assertEqual(controller.state["current_scope"]["scope_id"], "partial")
            update_calls = adapter.update_calls
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_recovery_required"
            ):
                controller.run(adapter)
            self.assertEqual(adapter.update_calls, update_calls)

            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id="checkpoint-attempt-000-step-000002",
            )
            resumed.schedule_scope_expansion(
                _scope("expanded", ("score_head", "upper_block"), 20)
            )
            self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")

    def test_snapshot_failure_keeps_orphan_observation_but_rolls_back_state(self) -> None:
        observations = {
            0: _logits(2.0),
            1: _logits(2.5),
            2: _logits(2.8),
            3: _logits(3.0),
            4: _logits(3.2),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter)
            controller.run(adapter, stop_after=2)
            adapter.snapshot_failure_steps.add(3)
            with self.assertRaisesRegex(
                FullModelTrainingError, "fixture_snapshot_failed"
            ):
                controller.run(adapter, stop_after=3)
            self.assertEqual(controller.state["status"], "recovery_required")
            self.assertEqual(controller.state["current_step"], 2)
            self.assertEqual(
                store.read_observation(
                    "observation-attempt-000-step-000003"
                )["global_step"],
                3,
            )
            self.assertFalse(
                (root / "model-snapshots/snapshot-attempt-000-step-000003").exists()
            )
            calls = adapter.update_calls
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_recovery_required"
            ):
                controller.run(adapter)
            self.assertEqual(adapter.update_calls, calls)

            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id="checkpoint-attempt-000-step-000002",
            )
            self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")

    def test_checkpoint_writer_failure_keeps_last_verified_pointer(self) -> None:
        observations = {
            0: _logits(2.0),
            1: _logits(2.5),
            2: _logits(2.8),
            3: _logits(3.0),
            4: _logits(3.2),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter)
            controller.run(adapter, stop_after=2)
            adapter.checkpoint_writer_failure_steps.add(4)
            with self.assertRaisesRegex(
                FullModelTrainingError, "fixture_checkpoint_writer_failed"
            ):
                controller.run(adapter)
            self.assertEqual(controller.state["status"], "recovery_required")
            self.assertEqual(controller.state["current_step"], 3)
            self.assertEqual(
                controller.state["latest_checkpoint_id"],
                "checkpoint-attempt-000-step-000002",
            )
            self.assertFalse(
                (root / "recovery-checkpoints/checkpoint-attempt-000-step-000004").exists()
            )
            self.assertFalse(
                any(
                    path.name.startswith(".checkpoint-attempt-000-step-000004")
                    for path in (root / "recovery-checkpoints").iterdir()
                )
            )

            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id="checkpoint-attempt-000-step-000002",
            )
            self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")

    def test_postpublish_checkpoint_failure_keeps_new_verified_anchor(self) -> None:
        observations = {
            0: _logits(2.0),
            1: _logits(2.5),
            2: _logits(2.8),
            3: _logits(3.0),
            4: _logits(3.2),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter)
            controller.run(adapter, stop_after=2)
            original_save = store.save_checkpoint

            def save_then_raise(artifact_id: str, **kwargs) -> dict:
                result = original_save(artifact_id, **kwargs)
                if artifact_id.endswith("step-000004"):
                    raise FullModelTrainingError("fixture_postpublish_failure")
                return result

            store.save_checkpoint = save_then_raise  # type: ignore[method-assign]
            with self.assertRaisesRegex(
                FullModelTrainingError, "fixture_postpublish_failure"
            ):
                controller.run(adapter)
            self.assertEqual(controller.state["status"], "recovery_required")
            self.assertEqual(controller.state["current_step"], 4)
            self.assertEqual(
                controller.state["latest_checkpoint_id"],
                "checkpoint-attempt-000-step-000004",
            )
            store.verify_checkpoint("checkpoint-attempt-000-step-000004")
            calls = adapter.update_calls
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_recovery_required"
            ):
                controller.run(adapter)
            self.assertEqual(adapter.update_calls, calls)

            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id="checkpoint-attempt-000-step-000004",
            )
            self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")
            self.assertTrue(
                store.has_retention_completion(
                    "checkpoint-attempt-000-step-000004"
                )
            )

    def test_retention_failure_cannot_bypass_completion_on_resume(self) -> None:
        observations = {0: _logits(2.0), 1: _logits(2.5), 2: _logits(2.8)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter, maximum=2)
            original_prune = store.prune

            def fail_retention(**_kwargs) -> dict:
                raise FullModelTrainingError("fixture_retention_failed")

            store.prune = fail_retention  # type: ignore[method-assign]
            with self.assertRaisesRegex(
                FullModelTrainingError, "fixture_retention_failed"
            ):
                controller.run(adapter)
            checkpoint_id = "checkpoint-attempt-000-step-000002"
            self.assertEqual(controller.state["status"], "recovery_required")
            self.assertEqual(controller.state["latest_checkpoint_id"], checkpoint_id)
            self.assertFalse(store.has_retention_completion(checkpoint_id))

            blocked_adapter = _FakeAdapter(observations)
            with self.assertRaisesRegex(
                FullModelTrainingError, "fixture_retention_failed"
            ):
                ContinuousTrainingController.resume(
                    route_contract=load_route_contract(
                        PLAN081_ROOT / "route-contract-v1.json"
                    ),
                    control_plan=_control_plan(maximum=2),
                    comparison_policy=ComparisonPolicy(
                        "boundary_pair_mean_margin", 0.05
                    ),
                    training_dataset=_training_dataset(),
                    validation_dataset=_validation_dataset(),
                    artifact_store=store,
                    adapter=blocked_adapter,
                    checkpoint_id=checkpoint_id,
                )
            self.assertEqual(blocked_adapter.events, [])

            store.prune = original_prune  # type: ignore[method-assign]
            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(maximum=2),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id=checkpoint_id,
            )
            self.assertTrue(store.has_retention_completion(checkpoint_id))
            self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")

    def test_retention_marker_prepublish_failure_is_retryable_on_resume(self) -> None:
        observations = {0: _logits(2.0), 1: _logits(2.5), 2: _logits(2.8)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter, maximum=2)
            original_write = store._write_artifact

            def fail_marker_before_publish(
                kind: str, artifact_id: str, **kwargs
            ) -> dict:
                if kind != "retention-completions":
                    return original_write(kind, artifact_id, **kwargs)
                populate = kwargs["populate"]

                def populate_then_fail(staging: Path) -> None:
                    populate(staging)
                    raise FullModelTrainingError(
                        "fixture_retention_marker_prepublish_failed"
                    )

                return original_write(
                    kind,
                    artifact_id,
                    **{**kwargs, "populate": populate_then_fail},
                )

            store._write_artifact = (  # type: ignore[method-assign]
                fail_marker_before_publish
            )
            with self.assertRaisesRegex(
                FullModelTrainingError,
                "fixture_retention_marker_prepublish_failed",
            ):
                controller.run(adapter)
            checkpoint_id = "checkpoint-attempt-000-step-000002"
            self.assertEqual(controller.state["status"], "recovery_required")
            self.assertFalse(store.has_retention_completion(checkpoint_id))
            completion_root = root / "retention-completions"
            self.assertFalse(
                any(path.name.startswith(".") for path in completion_root.iterdir())
            )

            store._write_artifact = original_write  # type: ignore[method-assign]
            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(maximum=2),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id=checkpoint_id,
            )
            self.assertTrue(store.has_retention_completion(checkpoint_id))
            self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")

    def test_retention_marker_postpublish_failure_does_not_repeat_prune(self) -> None:
        observations = {0: _logits(2.0), 1: _logits(2.5), 2: _logits(2.8)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter, maximum=2)
            original_mark = store.mark_retention_complete

            def mark_then_raise(checkpoint_id: str) -> dict:
                result = original_mark(checkpoint_id)
                raise FullModelTrainingError(
                    "fixture_retention_marker_postpublish_failed"
                )

            store.mark_retention_complete = (  # type: ignore[method-assign]
                mark_then_raise
            )
            with self.assertRaisesRegex(
                FullModelTrainingError,
                "fixture_retention_marker_postpublish_failed",
            ):
                controller.run(adapter)
            checkpoint_id = "checkpoint-attempt-000-step-000002"
            self.assertTrue(store.has_retention_completion(checkpoint_id))

            store.mark_retention_complete = original_mark  # type: ignore[method-assign]

            def reject_repeated_prune(**_kwargs) -> dict:
                raise FullModelTrainingError("fixture_repeated_retention")

            store.prune = reject_repeated_prune  # type: ignore[method-assign]
            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(maximum=2),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id=checkpoint_id,
            )
            self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")

    def test_retention_marker_staging_is_recovered_before_resume(self) -> None:
        observations = {0: _logits(2.0), 1: _logits(2.5), 2: _logits(2.8)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter, maximum=2)
            original_mark = store.mark_retention_complete

            def fail_marker(_checkpoint_id: str) -> dict:
                raise FullModelTrainingError("fixture_retention_marker_failed")

            store.mark_retention_complete = fail_marker  # type: ignore[method-assign]
            with self.assertRaisesRegex(
                FullModelTrainingError, "fixture_retention_marker_failed"
            ):
                controller.run(adapter)
            checkpoint_id = "checkpoint-attempt-000-step-000002"
            staging = (
                root
                / "retention-completions"
                / (
                    f".{checkpoint_id}.tmp-"
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                )
            )
            staging.mkdir(parents=True)
            (staging / "partial").write_text("incomplete", encoding="utf-8")

            store.mark_retention_complete = original_mark  # type: ignore[method-assign]
            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(maximum=2),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id=checkpoint_id,
            )
            self.assertFalse(staging.exists())
            self.assertTrue(store.has_retention_completion(checkpoint_id))
            self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")

    def test_resuming_completed_old_checkpoint_does_not_prune_newer_one(self) -> None:
        observations = {
            0: _logits(2.0),
            1: _logits(3.0),
            2: _logits(4.0),
            3: _logits(1.0),
            4: _logits(1.5),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter)
            controller.run(adapter)
            checkpoint_two = "checkpoint-attempt-000-step-000002"
            checkpoint_four = "checkpoint-attempt-000-step-000004"
            self.assertTrue(store.has_retention_completion(checkpoint_two))
            self.assertTrue(store.has_retention_completion(checkpoint_four))
            self.assertTrue(
                (root / "recovery-checkpoints" / checkpoint_four).is_dir()
            )

            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id=checkpoint_two,
            )
            self.assertEqual(resumed.state["current_step"], 2)
            self.assertTrue(
                (root / "recovery-checkpoints" / checkpoint_four).is_dir()
            )

    def test_non_json_codec_round_trip_and_preload_failure_boundaries(self) -> None:
        observations = {0: _logits(2.0), 1: _logits(2.5), 2: _logits(2.8)}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, adapter, maximum=2)
            controller.run(adapter)
            checkpoint_id = "checkpoint-attempt-000-step-000002"
            state_path = root / "recovery-checkpoints" / checkpoint_id / "training-state"
            raw = state_path.read_bytes()
            self.assertTrue(raw.startswith(b"PLAN081-LITERAL-V1\n"))
            with self.assertRaises((UnicodeDecodeError, json.JSONDecodeError)):
                json.loads(raw.decode("utf-8"))

            mismatched = _FakeAdapter(observations, codec_id="different-codec-v1")
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_training_state_codec_mismatch"
            ):
                ContinuousTrainingController.resume(
                    route_contract=load_route_contract(
                        PLAN081_ROOT / "route-contract-v1.json"
                    ),
                    control_plan=_control_plan(maximum=2),
                    comparison_policy=ComparisonPolicy(
                        "boundary_pair_mean_margin", 0.05
                    ),
                    training_dataset=_training_dataset(),
                    validation_dataset=_validation_dataset(),
                    artifact_store=store,
                    adapter=mismatched,
                    checkpoint_id=checkpoint_id,
                )
            self.assertEqual(mismatched.reader_calls, 0)
            self.assertEqual(mismatched.events, [])

            broken_reader = _FakeAdapter(observations)
            broken_reader.reader_failure = True
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_training_state_decode_failed"
            ):
                ContinuousTrainingController.resume(
                    route_contract=load_route_contract(
                        PLAN081_ROOT / "route-contract-v1.json"
                    ),
                    control_plan=_control_plan(maximum=2),
                    comparison_policy=ComparisonPolicy(
                        "boundary_pair_mean_margin", 0.05
                    ),
                    training_dataset=_training_dataset(),
                    validation_dataset=_validation_dataset(),
                    artifact_store=store,
                    adapter=broken_reader,
                    checkpoint_id=checkpoint_id,
                )
            self.assertEqual(broken_reader.reader_calls, 1)
            self.assertEqual(broken_reader.events, [])

            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(maximum=2),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id=checkpoint_id,
            )
            self.assertTrue(resumed_adapter.restored_typed_state)
            self.assertEqual(resumed.run(resumed_adapter)["status"], "completed")

            state_path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
            tampered = _FakeAdapter(observations)
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_artifact_tree_mismatch"
            ):
                ContinuousTrainingController.resume(
                    route_contract=load_route_contract(
                        PLAN081_ROOT / "route-contract-v1.json"
                    ),
                    control_plan=_control_plan(maximum=2),
                    comparison_policy=ComparisonPolicy(
                        "boundary_pair_mean_margin", 0.05
                    ),
                    training_dataset=_training_dataset(),
                    validation_dataset=_validation_dataset(),
                    artifact_store=store,
                    adapter=tampered,
                    checkpoint_id=checkpoint_id,
                )
            self.assertEqual(tampered.reader_calls, 0)
            self.assertEqual(tampered.events, [])

    def test_pause_new_instance_resume_scope_history_selection_and_retention(self) -> None:
        observations = {
            0: _logits(2.0),
            1: _logits(3.0),
            2: _logits(3.02),
            3: _logits(1.0),
            4: _logits(4.0),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first_adapter = _FakeAdapter(observations)
            controller, store = self._controller(root, first_adapter)
            paused = controller.run(first_adapter, stop_after=2)
            self.assertEqual(paused["status"], "paused")
            self.assertEqual(paused["global_step"], 2)
            checkpoint_two = "checkpoint-attempt-000-step-000002"
            self.assertEqual(paused["retention"]["latest_checkpoint_id"], checkpoint_two)

            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_unique_recovery_point_required"
            ):
                store.prune(
                    keep_snapshot_ids={"snapshot-attempt-000-step-000002"},
                    keep_checkpoint_ids=set(),
                )

            controller.schedule_scope_expansion(
                _scope("expanded", ("score_head", "upper_block"), 20)
            )
            orphaned = controller.run(first_adapter, stop_after=3)
            self.assertEqual(orphaned["global_step"], 3)
            self.assertEqual(orphaned["status"], "paused")
            staging = (
                root
                / "recovery-checkpoints"
                / (
                    ".checkpoint-attempt-999-step-999999.tmp-"
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                )
            )
            staging.mkdir()
            (staging / "partial").write_text("incomplete", encoding="utf-8")

            changed = _validation_dataset()
            changed_supervision = copy.deepcopy(changed.supervision)
            changed_supervision["pass-a"]["binary_label"] = "REWRITE"
            changed_dataset = ValidationDataset(
                input_identity=changed.input_identity,
                rubric=changed.rubric,
                packets=changed.packets,
                supervision=changed_supervision,
                pairs=changed.pairs,
            )
            rejected_adapter = _FakeAdapter(observations)
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_checkpoint_controller_state_invalid"
            ):
                ContinuousTrainingController.resume(
                    route_contract=load_route_contract(
                        PLAN081_ROOT / "route-contract-v1.json"
                    ),
                    control_plan=_control_plan(),
                    comparison_policy=ComparisonPolicy(
                        "boundary_pair_mean_margin", 0.05
                    ),
                    training_dataset=_training_dataset(),
                    validation_dataset=changed_dataset,
                    artifact_store=store,
                    adapter=rejected_adapter,
                    checkpoint_id=checkpoint_two,
                )
            self.assertEqual(rejected_adapter.events, [])
            self.assertFalse(staging.exists())

            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(PLAN081_ROOT / "route-contract-v1.json"),
                control_plan=_control_plan(),
                comparison_policy=ComparisonPolicy("boundary_pair_mean_margin", 0.05),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id=checkpoint_two,
            )
            resumed.schedule_scope_expansion(
                _scope("expanded", ("score_head", "upper_block"), 20)
            )
            replay_orphaned = resumed.run(resumed_adapter, stop_after=3)
            self.assertEqual(replay_orphaned["global_step"], 3)
            self.assertEqual(replay_orphaned["status"], "paused")
            self.assertEqual(
                store.read_observation(
                    "observation-attempt-001-step-000003"
                )["global_step"],
                3,
            )

            resumed_adapter = _FakeAdapter(observations)
            resumed = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id=checkpoint_two,
            )
            configure_index = resumed_adapter.events.index("configure:partial")
            restore_index = resumed_adapter.events.index("restore:partial")
            self.assertLess(configure_index, restore_index)
            resumed.schedule_scope_expansion(
                _scope("expanded", ("score_head", "upper_block"), 20)
            )
            finished = resumed.run(resumed_adapter)

            self.assertEqual(finished["status"], "completed")
            self.assertEqual(finished["global_step"], 4)
            self.assertEqual(
                finished["actual_trainable_scope"]["parameter_names"],
                ["score_head", "upper_block"],
            )
            selection = finished["selection"]
            self.assertEqual(
                selection["target_candidate_state"],
                "better_than_base_candidate_control_path",
            )
            self.assertEqual(
                selection["control_candidate_snapshot_id"],
                "snapshot-attempt-002-step-000004",
            )
            self.assertIsNone(selection["research_candidate_snapshot_id"])
            self.assertFalse(selection["research_candidate_eligible"])
            self.assertFalse(finished["claims"]["research_candidate_produced"])

            step_three = store.read_observation(
                "observation-attempt-002-step-000003"
            )
            self.assertEqual(
                step_three["comparisons"],
                {"base": "regressed", "previous": "regressed", "best": "regressed"},
            )
            self.assertEqual(
                next(
                    row
                    for row in step_three["pair_margins"]
                    if row["kind"] == "boundary"
                )["signed_raw_margin"],
                1.0,
            )

            snapshot_root = root / "model-snapshots"
            checkpoint_root = root / "recovery-checkpoints"
            self.assertEqual(
                {path.name for path in snapshot_root.iterdir()},
                {
                    "snapshot-attempt-002-step-000003",
                    "snapshot-attempt-002-step-000004",
                },
            )
            self.assertEqual(
                {path.name for path in checkpoint_root.iterdir()},
                {"checkpoint-attempt-002-step-000004"},
            )
            self.assertEqual(
                len(list((root / "observations").iterdir())),
                7,
            )
            self.assertEqual(
                store.read_observation(
                    "observation-attempt-000-step-000003"
                )["global_step"],
                3,
            )
            final_adapter = _FakeAdapter(observations)
            final_resume = ContinuousTrainingController.resume(
                route_contract=load_route_contract(
                    PLAN081_ROOT / "route-contract-v1.json"
                ),
                control_plan=_control_plan(),
                comparison_policy=ComparisonPolicy(
                    "boundary_pair_mean_margin", 0.05
                ),
                training_dataset=_training_dataset(),
                validation_dataset=_validation_dataset(),
                artifact_store=store,
                adapter=final_adapter,
                checkpoint_id="checkpoint-attempt-002-step-000004",
            )
            self.assertEqual(final_resume.state["current_step"], 4)
            self.assertEqual(
                final_resume.state["current_scope"]["scope_id"], "expanded"
            )
            self.assertEqual(final_resume.run(final_adapter)["status"], "completed")
            again = store.prune(
                keep_snapshot_ids={
                    "snapshot-attempt-002-step-000003",
                    "snapshot-attempt-002-step-000004",
                },
                keep_checkpoint_ids={"checkpoint-attempt-002-step-000004"},
            )
            self.assertEqual(again, {"removed_snapshots": [], "removed_checkpoints": []})
            self.assertEqual(
                {path.name for path in (root / "attempt-reservations").iterdir()},
                {"attempt-000001", "attempt-000002", "attempt-000003"},
            )


if __name__ == "__main__":
    unittest.main()
