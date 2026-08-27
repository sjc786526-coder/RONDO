from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import MethodType
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
from rondo_eval.publication_critic.full_model_training.plan081_contract import (  # noqa: E402
    ComparisonPolicy,
    ControlPlan,
    TrainableScope,
)
from rondo_eval.publication_critic.full_model_training.plan081_observation import (  # noqa: E402
    training_identity_sha256,
)
from rondo_eval.publication_critic.full_model_training.plan094_artifacts import (  # noqa: E402
    Plan094ArtifactStore,
)
from rondo_eval.publication_critic.full_model_training.plan094_contract import (  # noqa: E402
    assess_material,
    decide_stop,
    frozen_contract,
    materialize_run_spec,
    validate_budget_snapshot,
    validate_freeze,
)
from rondo_eval.publication_critic.full_model_training.plan094_controller import (  # noqa: E402
    Plan094ContinuousTrainingController,
)
from rondo_eval.publication_critic.full_model_training.plan094_finalize import (  # noqa: E402
    finalize_terminal,
)
from rondo_eval.publication_critic.full_model_training.plan090_artifacts import (  # noqa: E402
    Plan090ArtifactStore,
)
from rondo_eval.publication_critic.full_model_training.plan090_contract import (  # noqa: E402
    BF16_SECONDARY_RUN,
    frozen_contract as plan090_freeze,
    validate_budget_snapshot as validate_plan090_budget,
)
from rondo_eval.publication_critic.full_model_training.plan090_controller import (  # noqa: E402
    Plan090ConfirmationController,
)

from eval.tests.test_publication_critic_plan090_training import (  # noqa: E402
    _Plan090FakeAdapter,
    _cohort,
    _inventory,
    _precision,
    _runtime,
    _budget as _plan090_budget,
    _run_spec as _plan090_run_spec,
)


FREEZE_PATH = (
    REPO_ROOT / "training/publication-critic-plan094/continuous-freeze-v1.json"
)
ROUTE_PATH = REPO_ROOT / "training/publication-critic-plan081/route-contract-v1.json"


def _run_spec(
    *,
    run_kind: str = "commissioning",
    continuation_mode: str = "exact_base_rebuild_of_route_o_step_1",
) -> dict:
    return materialize_run_spec(
        frozen_contract(),
        run_kind=run_kind,
        namespace=f"{run_kind}/fixture",
        source_commit="a" * 40,
        source_archive_sha256="b" * 64,
        parameter_inventory=_inventory(),
        continuation_mode=continuation_mode,
    )


def _plan094_runtime(spec: dict) -> dict:
    value = _runtime(spec)
    value["runtime_kind"] = (
        "torch_real_route_o_continuous_direct_original_parameters"
    )
    value["provider_pod_name"] = "rondo-plan094-fixture"
    value["continuation_semantics"] = {
        "data_ordering": "sorted_candidates_and_frozen_pair_order",
        "data_shuffle": False,
        "attention_dropout": 0.0,
        "active_dropout_modules": [],
        "seed_sensitive_consumers": [],
        "seed_sensitive_stability_tested": False,
    }
    del value["repeat_semantics"]
    return value


def _budget(*, cost: float = 0.0, projected: float = 0.5) -> dict:
    return validate_budget_snapshot(
        {
            "schema": "rondo-publication-critic-plan094-budget-snapshot-v1",
            "captured_at": "2026-08-26T12:00:00Z",
            "live_balance_usd": 5.4 - cost,
            "known_unsettled_usd": 0.1,
            "stage_b_baseline_balance_usd": 5.4,
            "stage_b_baseline_known_unsettled_usd": 0.1,
            "conservative_task_cost_usd": cost,
            "closure_reserve_usd": 0.5,
            "projected_segment_and_closure_usd": projected,
        }
    )


class _Plan094FakeAdapter(_Plan090FakeAdapter):
    def __init__(self, spec: dict, validation_logits: dict, train_logits: dict):
        super().__init__(spec, validation_logits, train_logits)
        self.codec_id = "plan094-fixture-v1"
        self.provider_pod_id = "fixture-pod-id"
        self.provider_pod_name = "rondo-plan094-fixture"

    def plan094_runtime_identity(self) -> dict:
        value = _plan094_runtime(self.spec)
        value["provider_pod_id"] = self.provider_pod_id
        value["provider_pod_name"] = self.provider_pod_name
        return value

    def apply_update(self, step, scope, training_dataset):
        receipt = super().apply_update(step, scope, training_dataset)
        self.data_cursor = {"macro_update": step}
        receipt["data_cursor"] = dict(self.data_cursor)
        return receipt

    def assert_data_cursor(self, value: dict) -> None:
        if self.data_cursor != value:
            raise FullModelTrainingError("fixture_data_cursor_mismatch")
        self.events.append(f"data:{next(iter(value.values()))}")

    def restore_training_state(self, value: dict) -> None:
        normalized = copy.deepcopy(value)
        if normalized["optimizer"].get("scope_id", "").startswith("plan090-"):
            normalized["optimizer"]["scope_id"] = self.scope.scope_id
        super().restore_training_state(normalized)

    def training_states_equal(self, left: dict, right: dict) -> bool:
        normalized = copy.deepcopy(right)
        if normalized["optimizer"].get("scope_id", "").startswith("plan090-"):
            normalized["optimizer"]["scope_id"] = self.scope.scope_id
        return super().training_states_equal(left, normalized)

    def save_model(self, root: Path) -> None:
        self.events.append(f"save:{self.step}")
        super().save_model(root)

    def evaluate_validation(self, dataset):
        self.events.append(f"validation:{self.step}")
        return super().evaluate_validation(dataset)

    @contextmanager
    def checkpoint_recovery_probe(self):
        with super().checkpoint_recovery_probe() as probe:
            probe.plan094_runtime_identity = self.plan094_runtime_identity
            probe.assert_data_cursor = MethodType(
                lambda runtime, value: (
                    None
                    if runtime.data_cursor == value
                    else (_ for _ in ()).throw(
                        FullModelTrainingError("fixture_data_cursor_mismatch")
                    )
                ),
                probe,
            )
            yield probe


class _Plan090ContinuationFakeAdapter(_Plan090FakeAdapter):
    def __init__(self, spec: dict, validation_logits: dict, train_logits: dict):
        super().__init__(spec, validation_logits, train_logits)
        self.codec_id = "plan090-torch-state-v1"

    def apply_update(self, step, scope, training_dataset):
        receipt = super().apply_update(step, scope, training_dataset)
        self.data_cursor = {"macro_update": step}
        receipt["data_cursor"] = dict(self.data_cursor)
        return receipt

    @contextmanager
    def checkpoint_recovery_probe(self):
        with super().checkpoint_recovery_probe() as probe:
            probe.assert_data_cursor = MethodType(
                lambda runtime, value: (
                    None
                    if runtime.data_cursor == value
                    else (_ for _ in ()).throw(
                        FullModelTrainingError("fixture_data_cursor_mismatch")
                    )
                ),
                probe,
            )
            yield probe


def _fixtures():
    spec = _run_spec()
    validation, validation_logits = _cohort("validation")
    training, train_logits = _cohort("train")
    for step in range(2, 7):
        validation_logits[step] = copy.deepcopy(validation_logits[1])
        train_logits[step] = copy.deepcopy(train_logits[1])
    return spec, validation, validation_logits, training, train_logits


def _controller(root: Path, adapter: _Plan094FakeAdapter):
    spec = adapter.spec
    validation, _validation_logits = _cohort("validation")
    training, _train_logits = _cohort("train")
    controller = Plan094ContinuousTrainingController(
        freeze=frozen_contract(),
        run_spec=spec,
        launch_budget_snapshot=_budget(),
        route_contract=read_json(ROUTE_PATH),
        control_plan=ControlPlan.from_value(spec["control_plan"]),
        initial_scope=TrainableScope.from_value(spec["scope"]),
        comparison_policy=ComparisonPolicy.from_value(spec["comparison_policy"]),
        training_dataset=training,
        validation_dataset=validation,
        artifact_store=Plan094ArtifactStore(root),
        report_threshold=spec["report_threshold"],
    )
    controller.begin_process(
        {"instance_id": "1" * 32, "hostname": "fixture-a", "pid": 1}
    )
    controller.initialize(adapter)
    return controller, spec, validation, training


class Plan094TrainingTests(unittest.TestCase):
    def test_tracked_freeze_and_budget_are_exact_and_fail_closed(self) -> None:
        value = read_json(FREEZE_PATH)
        self.assertEqual(validate_freeze(value), frozen_contract())
        self.assertEqual(value["control_plan"]["checkpoint_steps"], [1, 2, 3, 4, 5, 6])
        self.assertFalse(value["claims"]["unseen_evidence"])
        budget = validate_budget_snapshot(
            {
                "schema": "rondo-publication-critic-plan094-budget-snapshot-v1",
                "captured_at": "2026-08-26T12:00:00Z",
                "live_balance_usd": 5.4,
                "known_unsettled_usd": 0.1,
                "stage_b_baseline_balance_usd": 5.4,
                "stage_b_baseline_known_unsettled_usd": 0.1,
                "conservative_task_cost_usd": 0.0,
                "closure_reserve_usd": 0.5,
                "projected_segment_and_closure_usd": 4.7,
            }
        )
        self.assertTrue(budget["segment_authorized"])
        self.assertEqual(validate_budget_snapshot(budget), budget)
        drifted = copy.deepcopy(value)
        drifted["material_rubric"]["minimum_raw_boundary_delta"] = 0.0
        with self.assertRaisesRegex(FullModelTrainingError, "plan094_freeze_drifted"):
            validate_freeze(drifted)

    def test_update_checkpoint_qualification_precedes_evaluation(self) -> None:
        spec, validation, validation_logits, training, train_logits = _fixtures()
        adapter = _Plan094FakeAdapter(spec, validation_logits, train_logits)
        with tempfile.TemporaryDirectory() as directory:
            controller, _spec, _validation, _training = _controller(
                Path(directory), adapter
            )
            controller.run(adapter, stop_after=1)
            checkpoint_id = controller.state["latest_checkpoint_id"]
            store = controller.plan094_store
            self.assertTrue(store.verify_checkpoint(checkpoint_id))
            self.assertTrue(store.verify_evaluation_result(checkpoint_id))
            first_save = adapter.events.index("save:1")
            actual_validation = max(
                index
                for index, event in enumerate(adapter.events)
                if event == "validation:1"
            )
            self.assertLess(first_save, actual_validation)
            self.assertEqual(adapter.update_calls, 1)
            self.assertEqual(controller.state["status"], "paused")

    def test_retention_preserves_all_distinct_hard_roles_within_trajectory_bound(
        self,
    ) -> None:
        spec, _validation, validation_logits, _training, train_logits = _fixtures()
        adapter = _Plan094FakeAdapter(spec, validation_logits, train_logits)
        with tempfile.TemporaryDirectory() as directory:
            controller, *_ = _controller(Path(directory), adapter)
            checkpoint_ids = [
                f"checkpoint-attempt-000-step-{step:06d}"
                for step in range(1, 7)
            ]
            training_state = adapter.capture_training_state()
            for checkpoint_id in checkpoint_ids:
                controller.plan094_store.save_checkpoint(
                    checkpoint_id,
                    model_saver=adapter.save_model,
                    training_state=training_state,
                    controller_state=controller.state,
                    metadata={"training_state_codec": adapter.codec_id},
                    state_writer=adapter.write_training_state,
                )
            controller.state["plan094"]["checkpoint_roles"] = {
                "material_candidate": checkpoint_ids[0],
                "latest": checkpoint_ids[5],
                "fresh_process_recovery": checkpoint_ids[1],
                "turning_points": checkpoint_ids[2:4],
                "checkpoint_backed_best": checkpoint_ids[4],
                "training_best": checkpoint_ids[4],
            }
            controller._apply_plan094_retention()
            self.assertEqual(
                set(controller.plan094_store.verified_checkpoint_ids()),
                set(checkpoint_ids),
            )

    def test_evaluation_failure_preserves_checkpoint_and_replays_without_update(self) -> None:
        spec, _validation, validation_logits, _training, train_logits = _fixtures()
        adapter = _Plan094FakeAdapter(spec, validation_logits, train_logits)
        adapter.validation_failure_steps.add(1)
        with tempfile.TemporaryDirectory() as directory:
            controller, _spec, _validation, _training = _controller(
                Path(directory), adapter
            )
            with self.assertRaisesRegex(FullModelTrainingError, "fixture_validation_failed"):
                controller.run(adapter, stop_after=1)
            checkpoint_id = controller.state["latest_checkpoint_id"]
            self.assertEqual(controller.state["status"], "evaluation_pending")
            controller.plan094_store.verify_checkpoint(checkpoint_id)
            self.assertFalse(
                controller.plan094_store.has_evaluation_result(checkpoint_id)
            )
            adapter.validation_failure_steps.clear()
            controller.run(adapter, stop_after=1)
            self.assertEqual(adapter.update_calls, 1)
            self.assertEqual(controller.state["status"], "paused")
            self.assertEqual(
                controller.state["plan094"]["evaluation_overlays"], [checkpoint_id]
            )

    def test_guarded_plan090_full_checkpoint_import_rejects_identity_drift(self) -> None:
        source_spec = _plan090_run_spec(BF16_SECONDARY_RUN)
        validation, validation_logits = _cohort("validation")
        training, train_logits = _cohort("train")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_store = Plan090ArtifactStore(root / "plan090")
            source_adapter = _Plan090ContinuationFakeAdapter(
                source_spec, validation_logits, train_logits
            )
            source = Plan090ConfirmationController(
                freeze=plan090_freeze(),
                run_spec=source_spec,
                launch_budget_snapshot=validate_plan090_budget(_plan090_budget()),
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(source_spec["control_plan"]),
                initial_scope=TrainableScope.from_value(source_spec["scope"]),
                comparison_policy=ComparisonPolicy.from_value(
                    source_spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=source_store,
                report_threshold=source_spec["report_threshold"],
            )
            source.begin_process(
                {"instance_id": "9" * 32, "hostname": "fixture-a", "pid": 9}
            )
            source.initialize(source_adapter)
            source.run(source_adapter)
            checkpoint_id = source.state["latest_checkpoint_id"]
            checkpoint = source_store.verify_checkpoint(checkpoint_id)

            spec = _run_spec(
                continuation_mode="guarded_plan090_full_checkpoint_import"
            )
            _v, plan094_logits = _cohort("validation")
            _t, plan094_train_logits = _cohort("train")
            for step in range(2, 7):
                plan094_logits[step] = copy.deepcopy(plan094_logits[1])
                plan094_train_logits[step] = copy.deepcopy(plan094_train_logits[1])
            adapter = _Plan094FakeAdapter(
                spec, plan094_logits, plan094_train_logits
            )
            controller, _spec, _validation, _training = _controller(
                root / "plan094", adapter
            )
            with patch(
                "rondo_eval.publication_critic.full_model_training.plan094_controller.PLAN090_SOURCE_CHECKPOINT_SHA256",
                checkpoint["content_sha256"],
            ), patch(
                "rondo_eval.publication_critic.full_model_training.plan094_controller.PLAN090_SOURCE_CHECKPOINT_BYTES",
                checkpoint["bytes"],
            ):
                controller.import_plan090_checkpoint(
                    adapter,
                    source_store=source_store,
                    checkpoint_id=checkpoint_id,
                )
            self.assertEqual(controller.state["current_step"], 1)
            self.assertEqual(
                controller.state["plan094"]["continuation_origin"]["mode"],
                "guarded_plan090_full_checkpoint_import",
            )
            self.assertEqual(adapter.update_calls, 0)
            self.assertEqual(
                controller.state["plan094"]["evaluation_overlays"], [checkpoint_id]
            )
            self.assertFalse(controller.archive_summary()["claims"]["real_training_run"])
            self.assertEqual(
                controller.state["selection"]["previous_checkpoint_id"],
                checkpoint_id,
            )
            self.assertIsNone(
                controller.state["selection"]["latest_checkpoint_id"]
            )
            roles = controller.state["plan094"]["checkpoint_roles"]
            self.assertTrue(
                all(
                    roles[key] is None
                    for key in (
                        "material_candidate",
                        "latest",
                        "fresh_process_recovery",
                        "checkpoint_backed_best",
                        "training_best",
                    )
                )
            )
            self.assertEqual(roles["turning_points"], [])

            controller.run(adapter, stop_after=2)
            self.assertTrue(controller.archive_summary()["claims"]["real_training_run"])
            owned_checkpoint_id = controller.state["latest_checkpoint_id"]
            self.assertNotEqual(owned_checkpoint_id, checkpoint_id)
            self.assertEqual(
                controller.state["selection"]["previous_checkpoint_id"],
                checkpoint_id,
            )
            roles = controller.state["plan094"]["checkpoint_roles"]
            self.assertEqual(roles["latest"], owned_checkpoint_id)
            self.assertEqual(roles["checkpoint_backed_best"], owned_checkpoint_id)
            self.assertEqual(roles["training_best"], owned_checkpoint_id)
            self.assertNotIn(checkpoint_id, roles["turning_points"])

            wrong_adapter = _Plan094FakeAdapter(
                spec, plan094_logits, plan094_train_logits
            )
            wrong_controller, *_ = _controller(root / "wrong", wrong_adapter)
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan094_source_checkpoint_identity_mismatch"
            ):
                wrong_controller.import_plan090_checkpoint(
                    wrong_adapter,
                    source_store=source_store,
                    checkpoint_id=checkpoint_id,
                )

    def test_fresh_process_resume_continues_and_binds_recovery_role(self) -> None:
        spec, validation, validation_logits, training, train_logits = _fixtures()
        first = _Plan094FakeAdapter(spec, validation_logits, train_logits)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, _spec, _validation, _training = _controller(root, first)
            controller.run(first, stop_after=1)
            checkpoint_id = controller.state["latest_checkpoint_id"]
            second = _Plan094FakeAdapter(spec, validation_logits, train_logits)
            recovered = Plan094ContinuousTrainingController.resume(
                freeze=frozen_contract(),
                run_spec=spec,
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=Plan094ArtifactStore(root),
                adapter=second,
                checkpoint_id=checkpoint_id,
                process_identity={
                    "instance_id": "2" * 32,
                    "hostname": "fixture-a",
                    "pid": 2,
                },
                budget_snapshot=_budget(cost=0.1),
                report_threshold=spec["report_threshold"],
            )
            recovered.run(second, stop_after=2)
            self.assertEqual(second.update_calls, 1)
            self.assertEqual(recovered.state["current_step"], 2)
            self.assertEqual(
                recovered.state["plan094"]["recovery_proven_checkpoints"],
                {
                    checkpoint_id: recovered.state["plan094"][
                        "resume_verification"
                    ]["source_checkpoint_content_sha256"]
                },
            )
            self.assertEqual(
                recovered.state["plan094"]["checkpoint_roles"][
                    "fresh_process_recovery"
                ],
                checkpoint_id,
            )

    def test_resume_after_next_checkpoint_evaluation_failure_preserves_history(
        self,
    ) -> None:
        spec, validation, validation_logits, training, train_logits = _fixtures()
        first = _Plan094FakeAdapter(spec, validation_logits, train_logits)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, *_ = _controller(root, first)
            controller.run(first, stop_after=1)
            first_checkpoint_id = controller.state["latest_checkpoint_id"]

            second = _Plan094FakeAdapter(spec, validation_logits, train_logits)
            second.validation_failure_steps.add(2)
            recovered = Plan094ContinuousTrainingController.resume(
                freeze=frozen_contract(),
                run_spec=spec,
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=Plan094ArtifactStore(root),
                adapter=second,
                checkpoint_id=first_checkpoint_id,
                process_identity={
                    "instance_id": "2" * 32,
                    "hostname": "fixture-a",
                    "pid": 2,
                },
                budget_snapshot=_budget(cost=0.1),
                report_threshold=spec["report_threshold"],
            )
            with self.assertRaisesRegex(
                FullModelTrainingError, "fixture_validation_failed"
            ):
                recovered.run(second, stop_after=2)
            second_checkpoint_id = recovered.state["latest_checkpoint_id"]

            third = _Plan094FakeAdapter(spec, validation_logits, train_logits)
            resumed_again = Plan094ContinuousTrainingController.resume(
                freeze=frozen_contract(),
                run_spec=spec,
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=Plan094ArtifactStore(root),
                adapter=third,
                checkpoint_id=second_checkpoint_id,
                process_identity={
                    "instance_id": "3" * 32,
                    "hostname": "fixture-a",
                    "pid": 3,
                },
                budget_snapshot=_budget(cost=0.2),
                report_threshold=spec["report_threshold"],
            )
            self.assertEqual(resumed_again.state["status"], "paused")
            self.assertEqual(resumed_again.state["current_step"], 2)
            self.assertEqual(
                resumed_again.state["plan094"]["checkpoint_roles"][
                    "fresh_process_recovery"
                ],
                first_checkpoint_id,
            )

    def test_replacement_pod_with_exact_runtime_can_resume(self) -> None:
        spec, validation, validation_logits, training, train_logits = _fixtures()
        first = _Plan094FakeAdapter(spec, validation_logits, train_logits)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, *_ = _controller(root, first)
            controller.run(first, stop_after=1)
            checkpoint_id = controller.state["latest_checkpoint_id"]

            replacement = _Plan094FakeAdapter(
                spec, validation_logits, train_logits
            )
            replacement.provider_pod_id = "replacement-pod-id"
            replacement.provider_pod_name = "rondo-plan094-replacement"
            recovered = Plan094ContinuousTrainingController.resume(
                freeze=frozen_contract(),
                run_spec=spec,
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=Plan094ArtifactStore(root),
                adapter=replacement,
                checkpoint_id=checkpoint_id,
                process_identity={
                    "instance_id": "2" * 32,
                    "hostname": "fixture-b",
                    "pid": 1,
                },
                budget_snapshot=_budget(cost=0.1),
                report_threshold=spec["report_threshold"],
            )
            recovered.run(replacement, stop_after=2)
            self.assertEqual(
                recovered.state["plan094"]["runtime_identity"][
                    "provider_pod_id"
                ],
                "replacement-pod-id",
            )
            verification = recovered.state["plan094"]["resume_verification"]
            self.assertEqual(
                verification["source_runtime_identity"]["provider_pod_id"],
                "fixture-pod-id",
            )
            self.assertEqual(
                verification["resume_runtime_identity"]["provider_pod_id"],
                "replacement-pod-id",
            )

    def test_negative_stop_is_prefrozen_and_not_infrastructure_result(self) -> None:
        contract = frozen_contract()
        assessments = []
        for step in range(1, 5):
            core = {
                "schema": "rondo-publication-critic-plan094-material-assessment-v1",
                "global_step": step,
                "base": {},
                "candidate": {},
                "deltas": {"raw_boundary": 0.0},
                "pair_distribution": {},
                "raw_logit_span_ratio": 1.0,
                "best_operating": {},
                "meaningful_events": {"event": False},
                "checks": {"material": False},
                "candidate_eligible": True,
                "rubric_passed": False,
                "passed": False,
            }
            assessments.append(
                {
                    **core,
                    "content_sha256": sha256_bytes(canonical_json_bytes(core)),
                }
            )
        decision = decide_stop(contract, assessments)
        self.assertTrue(decision["terminal"])
        self.assertEqual(
            decision["outcome"], "ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT"
        )

    def test_material_assessment_rejects_plan090_scale_only_motion(self) -> None:
        spec, validation, validation_logits, training, train_logits = _fixtures()
        adapter = _Plan094FakeAdapter(spec, validation_logits, train_logits)
        with tempfile.TemporaryDirectory() as directory:
            controller, _spec, _validation, _training = _controller(
                Path(directory), adapter
            )
            scope = TrainableScope.from_value(spec["scope"])
            adapter.apply_update(1, scope, training)
            candidate = controller._evaluate(adapter, global_step=1, scope=scope)
            base = controller.plan094_store.read_observation("base-step-000000")
            assessment = assess_material(
                frozen_contract(),
                base_validation=base,
                candidate_validation=candidate,
            )
            self.assertFalse(assessment["passed"])
            self.assertFalse(assessment["checks"]["meaningful_discrete_event"])

    def test_material_stop_waits_for_formal_restore_and_continue(self) -> None:
        spec = _run_spec(run_kind="formal")
        validation, validation_logits = _cohort("validation")
        training, train_logits = _cohort("train")
        pass_extra = next(
            candidate_id
            for candidate_id, row in validation.supervision.items()
            if candidate_id.startswith("validation-extra-")
            and row["binary_label"] == "PASS"
        )
        validation_logits[0][pass_extra] = -1.5
        candidate = copy.deepcopy(validation_logits[0])
        candidate[pass_extra] = 2.0
        for index in range(4):
            candidate[f"validation-boundary-{index}-preferred"] = 0.515
            candidate[f"validation-boundary-{index}-dispreferred"] = -0.515
        validation_logits[1] = candidate
        validation_logits[2] = copy.deepcopy(candidate)
        train_logits[2] = copy.deepcopy(train_logits[1])
        first = _Plan094FakeAdapter(spec, validation_logits, train_logits)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, _spec, _validation, _training = _controller(root, first)
            controller.run(first, stop_after=4)
            checkpoint_id = controller.state["latest_checkpoint_id"]
            self.assertEqual(controller.state["current_step"], 1)
            self.assertEqual(first.update_calls, 1)
            self.assertTrue(controller.state["plan094"]["stop_decision"]["terminal"])
            self.assertEqual(controller.state["status"], "paused")
            self.assertTrue(
                controller.state["plan094"]["terminal_deferred_for_recovery"]
            )
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan094_terminal_resume_required"
            ):
                controller.run(first, stop_after=2)
            second = _Plan094FakeAdapter(spec, validation_logits, train_logits)
            controller = Plan094ContinuousTrainingController.resume(
                freeze=frozen_contract(),
                run_spec=spec,
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=Plan094ArtifactStore(root),
                adapter=second,
                checkpoint_id=checkpoint_id,
                process_identity={
                    "instance_id": "2" * 32,
                    "hostname": "fixture-a",
                    "pid": 2,
                },
                budget_snapshot=_budget(cost=0.1),
                report_threshold=spec["report_threshold"],
            )
            controller.run(second, stop_after=2)
            self.assertEqual(controller.state["status"], "terminal")
            self.assertFalse(
                controller.state["plan094"]["terminal_deferred_for_recovery"]
            )
            self.assertEqual(
                controller.state["plan094"]["checkpoint_roles"][
                    "material_candidate"
                ],
                checkpoint_id,
            )
            self.assertEqual(
                controller.state["plan094"]["stop_decision"]["global_step"], 1
            )
            third = _Plan094FakeAdapter(spec, validation_logits, train_logits)
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan094_resume_checkpoint_not_latest"
            ):
                Plan094ContinuousTrainingController.resume(
                    freeze=frozen_contract(),
                    run_spec=spec,
                    route_contract=read_json(ROUTE_PATH),
                    control_plan=ControlPlan.from_value(spec["control_plan"]),
                    comparison_policy=ComparisonPolicy.from_value(
                        spec["comparison_policy"]
                    ),
                    training_dataset=training,
                    validation_dataset=validation,
                    artifact_store=Plan094ArtifactStore(root),
                    adapter=third,
                    checkpoint_id=checkpoint_id,
                    process_identity={
                        "instance_id": "3" * 32,
                        "hostname": "fixture-c",
                        "pid": 3,
                    },
                    budget_snapshot=_budget(cost=0.2),
                    report_threshold=spec["report_threshold"],
                )

    def test_formal_negative_requires_restore_continue_and_zero_compute(self) -> None:
        spec = _run_spec(run_kind="formal")
        validation, validation_logits = _cohort("validation")
        training, train_logits = _cohort("train")
        validation_logits[2] = copy.deepcopy(validation_logits[0])
        train_logits[2] = copy.deepcopy(train_logits[0])
        validation_logits[2]["validation-boundary-0-preferred"] = -1.0
        validation_logits[2]["validation-boundary-0-dispreferred"] = 1.0
        for step in range(3, 7):
            validation_logits[step] = copy.deepcopy(validation_logits[1])
            train_logits[step] = copy.deepcopy(train_logits[1])
        first = _Plan094FakeAdapter(spec, validation_logits, train_logits)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            controller, _spec, _validation, _training = _controller(root, first)
            controller.run(first, stop_after=1)
            checkpoint_id = controller.state["latest_checkpoint_id"]
            second = _Plan094FakeAdapter(spec, validation_logits, train_logits)
            controller = Plan094ContinuousTrainingController.resume(
                freeze=frozen_contract(),
                run_spec=spec,
                route_contract=read_json(ROUTE_PATH),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=training,
                validation_dataset=validation,
                artifact_store=Plan094ArtifactStore(root),
                adapter=second,
                checkpoint_id=checkpoint_id,
                process_identity={
                    "instance_id": "2" * 32,
                    "hostname": "fixture-a",
                    "pid": 2,
                },
                budget_snapshot=_budget(cost=0.1),
                report_threshold=spec["report_threshold"],
            )
            controller.run(second, stop_after=4)
            self.assertEqual(controller.state["status"], "terminal")
            self.assertEqual(
                len(controller.plan094_store.evaluation_result_ids()), 4
            )
            self.assertLessEqual(
                len(controller.plan094_store.verified_checkpoint_ids()), 6
            )
            result = finalize_terminal(
                freeze=frozen_contract(),
                controller_state=controller.state,
                artifact_root=root,
                resource_state={
                    "captured_at": "2026-08-26T13:00:00Z",
                    "pod_count": 0,
                    "compute_rate_usd_per_hour": 0.0,
                    "volume": {
                        "id": "mwemzrn33y",
                        "region": "US-TX-3",
                        "size_gb": 57,
                        "deleted": False,
                        "rate_usd_per_hour": 0.006,
                    },
                },
                terminal_budget_snapshot=_budget(cost=0.2, projected=0.0),
            )
            self.assertEqual(
                result["outcome"], "ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT"
            )
            self.assertTrue(result["claims"]["fresh_process_restore_and_continue"])
            self.assertTrue(result["claims"]["all_task_pods_released"])
            drifted_resource = copy.deepcopy(result["resource_state"])
            drifted_resource["pod_count"] = 1
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan094_terminal_resource_state_invalid"
            ):
                finalize_terminal(
                    freeze=frozen_contract(),
                    controller_state=controller.state,
                    artifact_root=root,
                    resource_state=drifted_resource,
                    terminal_budget_snapshot=_budget(cost=0.2, projected=0.0),
                )
            turning_id = controller.state["plan094"]["checkpoint_roles"][
                "turning_points"
            ][0]
            owned = set(
                controller.plan094_store.verified_checkpoint_ids()
            )
            controller.plan094_store.prune(
                keep_snapshot_ids=set(),
                keep_checkpoint_ids=owned - {turning_id},
                prune_checkpoints=True,
            )
            with self.assertRaisesRegex(
                FullModelTrainingError,
                "plan094_terminal_retained_checkpoint_missing",
            ):
                finalize_terminal(
                    freeze=frozen_contract(),
                    controller_state=controller.state,
                    artifact_root=root,
                    resource_state=result["resource_state"],
                    terminal_budget_snapshot=_budget(cost=0.2, projected=0.0),
                )


if __name__ == "__main__":
    unittest.main()
