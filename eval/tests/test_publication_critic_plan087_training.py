from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training.contract import (  # noqa: E402
    FullModelTrainingError,
    canonical_json_bytes,
    read_json,
    sha256_bytes,
)
from rondo_eval.publication_critic.full_model_training.plan081_artifacts import (  # noqa: E402
    Plan081ArtifactStore,
)
from rondo_eval.publication_critic.full_model_training.plan081_contract import (  # noqa: E402
    ComparisonPolicy,
    ControlPlan,
    TrainableScope,
)
from rondo_eval.publication_critic.full_model_training.plan082_adapter import (  # noqa: E402
    validate_recipe as validate_plan082_recipe,
)
from rondo_eval.publication_critic.full_model_training.plan087_adapter import (  # noqa: E402
    RUNTIME_KIND,
    validate_adaptive_recipe,
)
from rondo_eval.publication_critic.full_model_training.plan087_capacity import (  # noqa: E402
    CAPACITY_PREFLIGHT_SCHEMA,
    PROVIDER_GB_BYTES,
    assess_checkpoint_capacity,
)
from rondo_eval.publication_critic.full_model_training.plan087_contract import (  # noqa: E402
    COST_SNAPSHOT_SCHEMA,
    PROCESS_RECEIPT_SCHEMA,
    RECOVERY_RECEIPT_SCHEMA,
    ROUTE_CONTEXT_SCHEMA,
    validate_cost_progression,
    validate_cost_snapshot,
    validate_route_context,
)
from rondo_eval.publication_critic.full_model_training.plan087_controller import (  # noqa: E402
    Plan087AdaptiveTrainingController,
)
from rondo_eval.publication_critic.full_model_training.plan087_finalize import (  # noqa: E402
    finalize_route,
    finalize_search,
    validate_route_result,
)
from rondo_eval.publication_critic.full_model_training.plan087_run import (  # noqa: E402
    RUN_SPEC_SCHEMA,
    run_scheduled,
    validate_run_spec,
)
from rondo_eval.publication_critic.full_model_training.plan087_search import (  # noqa: E402
    SCOPE_STRATEGY_SCHEMA,
    materialize_run_spec,
    resolve_scope,
    validate_route_candidate,
)

from eval.tests.test_publication_critic_plan081_training import (  # noqa: E402
    _logits,
)
from eval.tests.test_publication_critic_plan082_training import (  # noqa: E402
    _environment_receipt,
    _parameter_inventory,
    _Plan082FakeAdapter,
    _training,
    _validation,
)

ROUTE = REPO_ROOT / "training/publication-critic-plan081/route-contract-v1.json"
CANDIDATE_A = (
    REPO_ROOT
    / "training/publication-critic-plan087/route-a-terminal-pair-v1.json"
)
CANDIDATE_B = (
    REPO_ROOT / "training/publication-critic-plan087/route-b-wider-decay-v1.json"
)


def _cost(*, current: float = 9.14, projected: float = 1.0) -> dict:
    return {
        "schema": COST_SNAPSHOT_SCHEMA,
        "captured_at": "2026-08-26T12:00:00Z",
        "snapshot_index": 0,
        "previous_snapshot_content_sha256": None,
        "baseline_balance_usd": 9.14,
        "current_balance_usd": current,
        "provider_task_billing_usd": 0.0,
        "cost_entries": [],
        "initial_available_usd": 9.0,
        "projected_next_increment_usd": projected,
    }


def _next_cost(
    previous: dict,
    *,
    current: float | None = None,
    projected: float = 0.0,
    provider_task_billing_usd: float | None = None,
    appended_entries: list[dict] | None = None,
) -> dict:
    before = validate_cost_snapshot(previous)
    return {
        "schema": COST_SNAPSHOT_SCHEMA,
        "captured_at": "2026-08-26T12:05:00Z",
        "snapshot_index": before["snapshot_index"] + 1,
        "previous_snapshot_content_sha256": before["content_sha256"],
        "baseline_balance_usd": before["baseline_balance_usd"],
        "current_balance_usd": (
            before["current_balance_usd"] if current is None else current
        ),
        "provider_task_billing_usd": (
            before["provider_task_billing_usd"]
            if provider_task_billing_usd is None
            else provider_task_billing_usd
        ),
        "cost_entries": [
            *before["cost_entries"],
            *(appended_entries or []),
        ],
        "initial_available_usd": before["initial_available_usd"],
        "projected_next_increment_usd": projected,
    }


def _context() -> dict:
    return validate_route_context(
        {
            "schema": ROUTE_CONTEXT_SCHEMA,
            "search_id": "plan087-fixture",
            "route_id": "route-a-terminal-pair",
            "route_generation": 1,
            "start_state": "exact_base",
            "decision": {
                "reason": "initial bounded route",
                "evidence_observation_id": None,
                "changes": ["terminal block and boundary emphasis"],
            },
            "prior_route_summaries": [],
            "cost_snapshot": _cost(),
        }
    )


def _scope(name: str, names: list[str], elements: int) -> dict:
    return {
        "scope_id": name,
        "update_method": "direct_original_parameter_update",
        "parameter_names": names,
        "trainable_parameter_elements": elements,
        "reason": f"fixture {name}",
    }


def _run_spec() -> dict:
    candidate = read_json(CANDIDATE_A)
    return validate_run_spec(
        {
            "schema": RUN_SPEC_SCHEMA,
            "route_context": _context(),
            "recipe": candidate["recipe"],
            "initial_scope": _scope("tail", ["tail.weight"], 2),
            "scope_schedule": [
                {
                    "after_observation_step": 1,
                    "scope": _scope(
                        "tail-expanded", ["tail.weight", "tail.bias"], 3
                    ),
                }
            ],
            "control_plan": {
                "maximum_updates": 2,
                "observation_steps": [1, 2],
                "checkpoint_steps": [1, 2],
                "turning_point_limit": 2,
            },
            "comparison_policy": candidate["comparison_policy"],
            "report_threshold": 0.5,
        }
    )


def _runtime_identity() -> dict:
    recipe = _run_spec()["recipe"]
    inventory = _parameter_inventory()
    return {
        "runtime_kind": RUNTIME_KIND,
        "gpu_name": "NVIDIA A40",
        "gpu_count": 1,
        "cuda_version": "12.8",
        "torch_version": "2.8.0+cu128",
        "transformers_version": "4.52.3",
        "model_repository": "Skywork/Skywork-Reward-V2-Qwen3-1.7B",
        "model_revision": "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc",
        "peft": False,
        "quantized_training": False,
        "snapshot_content_sha256": "1" * 64,
        "recipe_sha256": sha256_bytes(canonical_json_bytes(recipe)),
        "parameter_inventory_sha256": inventory["inventory_sha256"],
        "parameter_tensors": 2,
        "parameter_elements": 3,
        "environment": _environment_receipt(),
    }


def _recovery_receipts(
    state: dict, checkpoint_id: str, checkpoint_sha256: str
) -> tuple[dict, dict]:
    runtime_sha256 = sha256_bytes(
        canonical_json_bytes(state["plan087"]["runtime_identity"])
    )
    context_sha256 = sha256_bytes(
        canonical_json_bytes(state["plan087"]["route_context"])
    )
    recovery_process = state["plan087"]["process_identity"]
    source_process_id = "9" * 32
    process = {
        "schema": PROCESS_RECEIPT_SCHEMA,
        "process_identity": recovery_process,
        "source_process_id": source_process_id,
        "status": "started",
        "global_step": state["current_step"],
        "runtime_identity_sha256": runtime_sha256,
        "route_context_sha256": context_sha256,
        "source": {"commit": "a" * 40},
    }
    recovery = {
        "schema": RECOVERY_RECEIPT_SCHEMA,
        "checkpoint_id": checkpoint_id,
        "checkpoint_sha256": checkpoint_sha256,
        "runtime_identity_sha256": runtime_sha256,
        "route_context_sha256": context_sha256,
        "source_process_id": source_process_id,
        "recovery_process_id": recovery_process["instance_id"],
        "fresh_adapter": True,
        "model_loaded": True,
        "optimizer_scheduler_rng_data_equal": True,
        "probe_update_completed": False,
        "checkpoint_reuse_verified": True,
    }
    return process, recovery


class _Plan087FakeAdapter(_Plan082FakeAdapter):
    def plan082_runtime_identity(self) -> dict:
        return _runtime_identity()

    def plan087_runtime_identity(self) -> dict:
        return _runtime_identity()

    @contextmanager
    def checkpoint_recovery_probe(self):
        with super().checkpoint_recovery_probe() as probe:
            probe.plan087_runtime_identity = self.plan087_runtime_identity
            yield probe


class Plan087TrainingTests(unittest.TestCase):
    def test_adaptive_recipe_does_not_relax_plan082_history(self) -> None:
        recipe = read_json(CANDIDATE_A)["recipe"]
        self.assertEqual(validate_adaptive_recipe(recipe), recipe)
        with self.assertRaises(FullModelTrainingError):
            validate_plan082_recipe(recipe)
        changed = copy.deepcopy(recipe)
        changed["objective"]["pair_margin"] = 0.1
        with self.assertRaisesRegex(FullModelTrainingError, "plan087_recipe_invalid"):
            validate_adaptive_recipe(changed)

    def test_scope_resolution_is_dynamic_ordered_and_strictly_expanding(self) -> None:
        rows = [
            {"name": "model.embed_tokens.weight", "elements": 100},
            {"name": "model.layers.25.self_attn.q_proj.weight", "elements": 25},
            {"name": "model.layers.26.self_attn.q_proj.weight", "elements": 26},
            {"name": "model.layers.27.self_attn.q_proj.weight", "elements": 27},
            {"name": "model.norm.weight", "elements": 8},
            {"name": "score.weight", "elements": 9},
        ]
        inventory = {"parameters": rows}
        one = resolve_scope(
            inventory,
            {
                "schema": SCOPE_STRATEGY_SCHEMA,
                "backbone_blocks": 1,
                "include_score_head": True,
                "include_final_norm": True,
            },
        )
        two = resolve_scope(
            inventory,
            {
                "schema": SCOPE_STRATEGY_SCHEMA,
                "backbone_blocks": 2,
                "include_score_head": True,
                "include_final_norm": True,
            },
        )
        self.assertEqual(
            two["parameter_names"][: len(one["parameter_names"])],
            one["parameter_names"],
        )
        self.assertEqual(
            one["parameter_names"],
            [
                "score.weight",
                "model.norm.weight",
                "model.layers.27.self_attn.q_proj.weight",
            ],
        )
        self.assertEqual(
            two["parameter_names"][-1],
            "model.layers.26.self_attn.q_proj.weight",
        )
        self.assertEqual(two["trainable_parameter_elements"], 70)

        candidate = validate_route_candidate(read_json(CANDIDATE_A))
        spec = materialize_run_spec(
            candidate, route_context=_context(), parameter_inventory=inventory
        )
        self.assertEqual(spec["initial_scope"], one)
        self.assertEqual(spec["scope_schedule"][0]["scope"], two)

    def test_budget_is_cumulative_conservative_and_idempotent(self) -> None:
        value = _cost(current=8.7, projected=8.6)
        value["provider_task_billing_usd"] = 0.3
        value["cost_entries"] = [
            {
                "entry_id": "pod-a",
                "category": "compute_pod",
                "amount_usd": 0.5,
                "basis": "wall clock times live rate",
            }
        ]
        result = validate_cost_snapshot(value)
        self.assertEqual(result["conservative_task_cost_usd"], 0.5)
        self.assertFalse(result["next_action_authorized"])
        self.assertEqual(validate_cost_snapshot(result), result)

        next_value = _next_cost(
            result,
            current=8.6,
            projected=0.2,
            provider_task_billing_usd=0.4,
            appended_entries=[
                {
                    "entry_id": "disk-a",
                    "category": "container_disk",
                    "amount_usd": 0.2,
                    "basis": "bounded container disk interval",
                }
            ],
        )
        advanced = validate_cost_progression(result, next_value)
        self.assertEqual(advanced["cost_entry_total_usd"], 0.7)
        tampered = copy.deepcopy(next_value)
        tampered["cost_entries"][0]["amount_usd"] = 0.1
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan087_cost_progression_invalid"
        ):
            validate_cost_progression(result, tampered)

    def test_budget_dual_gate_low_balance_and_billing_lag(self) -> None:
        low = _cost(current=0.15, projected=0.02)
        low["baseline_balance_usd"] = 0.2
        low["initial_available_usd"] = 0.06
        result = validate_cost_snapshot(low)
        self.assertFalse(result["next_action_authorized"])
        self.assertAlmostEqual(result["action_headroom_usd"], 0.01)

        baseline = validate_cost_snapshot(_cost(projected=0.0))
        lagged = _next_cost(
            baseline,
            current=9.14,
            projected=8.8,
            provider_task_billing_usd=0.0,
            appended_entries=[
                {
                    "entry_id": "pod-segment-a",
                    "category": "compute_pod",
                    "amount_usd": 0.35,
                    "basis": "wall clock times current live rate",
                },
                {
                    "entry_id": "volume-extension-a",
                    "category": "network_volume_expansion",
                    "amount_usd": 0.05,
                    "basis": "provider quoted extension charge",
                },
            ],
        )
        lagged_result = validate_cost_progression(baseline, lagged)
        self.assertAlmostEqual(lagged_result["conservative_task_cost_usd"], 0.4)
        self.assertFalse(lagged_result["next_action_authorized"])

    def test_capacity_preflight_recommends_only_needed_extension(self) -> None:
        result = assess_checkpoint_capacity(
            {
                "schema": CAPACITY_PREFLIGHT_SCHEMA,
                "captured_at": "2026-08-26T12:00:00Z",
                "volume_id": "mwemzrn33y",
                "current_size_gb": 40,
                "capacity_bytes": 40 * PROVIDER_GB_BYTES,
                "available_bytes": 8_789_929_022,
                "checkpoint_estimate_bytes": 7 * PROVIDER_GB_BYTES,
                "atomic_staging_copies": 2,
                "reserve_bytes": PROVIDER_GB_BYTES,
                "maximum_size_gb": 60,
            }
        )
        self.assertFalse(result["checkpoint_write_ready"])
        self.assertEqual(result["used_bytes"], 31_210_070_978)
        self.assertEqual(result["recommended_size_gb"], 47)
        self.assertTrue(result["extension_within_authorization"])
        self.assertEqual(assess_checkpoint_capacity(result), result)

    def test_route_history_binds_search_evidence_and_cost_chain(self) -> None:
        previous_cost = validate_cost_snapshot(_cost(current=8.9, projected=0.0))
        summary = {
            "search_id": "plan087-fixture",
            "route_id": "route-a-terminal-pair",
            "route_generation": 1,
            "route_result_content_sha256": "1" * 64,
            "run_spec_content_sha256": "2" * 64,
            "terminal_observation_id": "observation-step-000003",
            "terminal_observation_sha256": "3" * 64,
            "selected_checkpoint_content_sha256": "4" * 64,
            "candidate_disposition": "not_promising",
            "reason": "first route did not improve enough",
            "cost_snapshot_index": previous_cost["snapshot_index"],
            "cost_snapshot_content_sha256": previous_cost["content_sha256"],
            "baseline_balance_usd": previous_cost["baseline_balance_usd"],
            "current_balance_usd": previous_cost["current_balance_usd"],
            "conservative_task_cost_usd": previous_cost[
                "conservative_task_cost_usd"
            ],
        }
        context = {
            "schema": ROUTE_CONTEXT_SCHEMA,
            "search_id": "plan087-fixture",
            "route_id": "route-b-wider-decay",
            "route_generation": 2,
            "start_state": "exact_base",
            "decision": {
                "reason": "widen after the first route",
                "evidence_observation_id": "observation-step-000003",
                "changes": ["wider terminal scope"],
            },
            "prior_route_summaries": [summary],
            "cost_snapshot": _next_cost(
                previous_cost, current=8.8, projected=0.5
            ),
        }
        self.assertEqual(validate_route_context(context)["route_generation"], 2)
        for mutation in ("search", "evidence", "baseline"):
            invalid = copy.deepcopy(context)
            if mutation == "search":
                invalid["search_id"] = "other-search"
            elif mutation == "evidence":
                invalid["decision"]["evidence_observation_id"] = "other-observation"
            else:
                invalid["cost_snapshot"]["baseline_balance_usd"] = 9.0
                invalid["cost_snapshot"]["initial_available_usd"] = 8.86
            with self.assertRaises(FullModelTrainingError):
                validate_route_context(invalid)

    def test_route_checkpoint_restores_in_new_process_and_finalizes(self) -> None:
        spec = _run_spec()
        logits = {
            0: _logits(0.0),
            1: _logits(0.8),
            2: _logits(0.7),
        }
        with tempfile.TemporaryDirectory() as directory:
            store = Plan081ArtifactStore(Path(directory))
            first_adapter = _Plan087FakeAdapter(logits)
            first = Plan087AdaptiveTrainingController(
                route_context=spec["route_context"],
                run_spec=spec,
                route_contract=read_json(ROUTE),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                initial_scope=TrainableScope.from_value(spec["initial_scope"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=_training(),
                validation_dataset=_validation(),
                artifact_store=store,
            )
            first.begin_process(
                {"instance_id": "1" * 32, "hostname": "fixture", "pid": 101}
            )
            first.initialize(first_adapter)
            run_scheduled(first, first_adapter, spec, stop_after=1)
            checkpoint_id = first.state["latest_checkpoint_id"]
            checkpoint = store.verify_checkpoint(checkpoint_id)

            resumed_adapter = _Plan087FakeAdapter(logits)
            resumed = Plan087AdaptiveTrainingController.resume(
                route_contract=read_json(ROUTE),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=_training(),
                validation_dataset=_validation(),
                artifact_store=store,
                adapter=resumed_adapter,
                checkpoint_id=checkpoint_id,
            )
            resumed.begin_process(
                {"instance_id": "2" * 32, "hostname": "fixture", "pid": 102}
            )
            resumed.record_new_process_recovery(
                checkpoint_id, checkpoint["content_sha256"]
            )
            self.assertEqual(resumed.state["status"], "paused")
            selected = next(
                row
                for row in resumed.state["observations"]
                if row["checkpoint_id"] == checkpoint_id
            )
            process_receipt, recovery_receipt = _recovery_receipts(
                resumed.state, checkpoint_id, checkpoint["content_sha256"]
            )
            route = finalize_route(
                controller_state=resumed.state,
                artifact_root=Path(directory),
                selected_observation_id=selected["observation_id"],
                selected_checkpoint_id=checkpoint_id,
                operator_disposition="promising",
                operator_reason=(
                    "pair margins improve and companion metrics remain usable"
                ),
                operator_assessment={
                    "clear_ranking_or_pair_improvement": True,
                    "key_metrics_not_materially_collapsed": True,
                    "not_noise_offset_or_threshold_only": True,
                    "reviewed_complete_metrics": True,
                },
                cost_snapshots=[
                    _next_cost(
                        spec["route_context"]["cost_snapshot"],
                        current=8.9,
                        projected=0.0,
                    )
                ],
                process_receipt=process_receipt,
                recovery_receipt=recovery_receipt,
            )
            self.assertEqual(validate_route_result(route), route)
            self.assertTrue(route["selected_checkpoint"]["fresh_process_recovery"])
            self.assertIn("pair_margins", route["selected_validation_observation"])
            terminal = finalize_search(
                route_results=[route],
                outcome="PROMISING_CANDIDATE_RETAINED",
                reason="bounded candidate retained",
                selected_route_id="route-a-terminal-pair",
                terminal_cost_snapshots=[
                    _next_cost(
                        route["cost_snapshot"], current=8.9, projected=0.0
                    )
                ],
                resource_state={
                    "captured_at": "2026-08-26T13:00:00Z",
                    "pod_count": 0,
                    "compute_rate_usd_per_hour": 0,
                    "volumes": [
                        {
                            "id": "mwemzrn33y",
                            "region": "US-TX-3",
                            "size_gb": 40,
                            "role": "plan087 checkpoint retention",
                            "continuing_rate_usd_per_hour": 0.0001,
                            "deleted": False,
                        }
                    ],
                },
            )
            self.assertFalse(terminal["claims"]["model_route_failed"])

    def test_promising_disposition_rejects_unrecovered_checkpoint(self) -> None:
        spec = _run_spec()
        logits = {0: _logits(0.0), 1: _logits(0.8), 2: _logits(0.7)}
        with tempfile.TemporaryDirectory() as directory:
            store = Plan081ArtifactStore(Path(directory))
            adapter = _Plan087FakeAdapter(logits)
            controller = Plan087AdaptiveTrainingController(
                route_context=spec["route_context"],
                run_spec=spec,
                route_contract=read_json(ROUTE),
                control_plan=ControlPlan.from_value(spec["control_plan"]),
                initial_scope=TrainableScope.from_value(spec["initial_scope"]),
                comparison_policy=ComparisonPolicy.from_value(
                    spec["comparison_policy"]
                ),
                training_dataset=_training(),
                validation_dataset=_validation(),
                artifact_store=store,
            )
            controller.begin_process(
                {"instance_id": "3" * 32, "hostname": "fixture", "pid": 103}
            )
            controller.initialize(adapter)
            run_scheduled(controller, adapter, spec)
            selected = controller.state["observations"][-1]
            checkpoint = store.verify_checkpoint(selected["checkpoint_id"])
            process_receipt, recovery_receipt = _recovery_receipts(
                controller.state,
                selected["checkpoint_id"],
                checkpoint["content_sha256"],
            )
            with self.assertRaisesRegex(
                FullModelTrainingError,
                "plan087_selected_checkpoint_recovery_required",
            ):
                finalize_route(
                    controller_state=controller.state,
                    artifact_root=Path(directory),
                    selected_observation_id=selected["observation_id"],
                    selected_checkpoint_id=selected["checkpoint_id"],
                    operator_disposition="promising",
                    operator_reason="fixture",
                    operator_assessment={
                        "clear_ranking_or_pair_improvement": True,
                        "key_metrics_not_materially_collapsed": True,
                        "not_noise_offset_or_threshold_only": True,
                        "reviewed_complete_metrics": True,
                    },
                    cost_snapshots=[
                        _next_cost(
                            spec["route_context"]["cost_snapshot"], projected=0.0
                        )
                    ],
                    process_receipt=process_receipt,
                    recovery_receipt=recovery_receipt,
                )


if __name__ == "__main__":
    unittest.main()
