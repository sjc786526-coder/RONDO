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


def _logits(boundary_margin: float, *, within_margin: float = 1.0) -> dict[str, float]:
    return {
        "pass-a": boundary_margin / 2.0,
        "rewrite-a": -boundary_margin / 2.0,
        "pass-b": within_margin / 2.0,
        "rewrite-b": -within_margin / 2.0,
    }


class _FakeAdapter:
    def __init__(self, observations: dict[int, dict[str, float]]) -> None:
        self.observations = observations
        self.step = 0
        self.scope = None
        self.events: list[str] = []
        self.validation_calls = 0
        self.update_calls = 0
        self.data_cursor: dict = {"fixture_update": 0}

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
        return {
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

    def evaluate_validation(self) -> dict:
        before = (self.step, self.scope)
        self.validation_calls += 1
        receipt = {
            "raw_logits": dict(self.observations[self.step]),
            "gradient_access": False,
            "training_state_unchanged": True,
        }
        if before != (self.step, self.scope):
            raise AssertionError("fixture validation mutated training state")
        return receipt

    def save_model(self, root: Path) -> None:
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
            "optimizer": {"step": self.step, "scope_id": self.scope.scope_id},
            "scheduler": {"step": self.step},
            "rng": {"fixture_token": self.step * 17},
            "data": dict(self.data_cursor),
        }

    def restore_training_state(self, value: dict) -> None:
        if self.scope is None:
            raise FullModelTrainingError("fixture_restore_before_scope")
        if value["optimizer"]["scope_id"] != self.scope.scope_id:
            raise FullModelTrainingError("fixture_optimizer_scope_mismatch")
        self.events.append(f"restore:{self.scope.scope_id}")
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
    def _controller(self, root: Path, adapter: _FakeAdapter, *, maximum: int = 4):
        store = Plan081ArtifactStore(root)
        controller = ContinuousTrainingController(
            route_contract=load_route_contract(PLAN081_ROOT / "route-contract-v1.json"),
            control_plan=_control_plan(maximum=maximum),
            initial_scope=_scope("partial", ("score_head",), 10),
            comparison_policy=ComparisonPolicy("boundary_pair_mean_margin", 0.05),
            training_dataset=_training_dataset(),
            validation_dataset=_validation_dataset(),
            artifact_store=store,
        )
        controller.initialize(adapter)
        return controller, store

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
                    keep_snapshot_ids={
                        "snapshot-attempt-000-step-000001",
                        "snapshot-attempt-000-step-000002",
                    },
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
