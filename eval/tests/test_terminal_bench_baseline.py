from __future__ import annotations

import json
import hashlib
import argparse
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import RunOutcome, Side  # noqa: E402
from rondo_eval.config import RepoPaths, load_runtime_config  # noqa: E402
from rondo_eval.terminal_bench.baseline import (  # noqa: E402
    BASE_ROUNDS,
    CAMPAIGN_ACTIVE_POINTER_PATH,
    BaselineError,
    BaselineRun,
    BaselineStatus,
    CampaignSlotStatus,
    CampaignStateLedger,
    ConditionalRun,
    MechanicalFailureCategory,
    assess_baseline,
    campaign_lock_registry,
    cost_forecast,
    load_campaign_identity_path,
    load_historical_campaign_identity,
    load_campaign_identity,
)
from rondo_eval.terminal_bench.scoring import TaskOutcome  # noqa: E402
from rondo_eval.terminal_bench import baseline_cli  # noqa: E402
from rondo_eval.terminal_bench.baseline_identity import (  # noqa: E402
    CampaignIdentityGenerationError,
    required_successor_prior,
    validate_successor_run_range,
)


class TerminalBenchBaselineTests(unittest.TestCase):
    tasks = tuple(f"terminal-bench/task-{index}" for index in range(10))

    @staticmethod
    def _identity():
        return load_historical_campaign_identity(RepoPaths.discover(Path.cwd()), 9)

    def _base(
        self,
        outcomes: dict[tuple[str, str], TaskOutcome] | None = None,
        *,
        second: dict[tuple[str, str], TaskOutcome] | None = None,
    ) -> tuple[BaselineRun, ...]:
        outcomes = outcomes or {}
        second = second or {}
        values: list[BaselineRun] = []
        for round_id in BASE_ROUNDS:
            side = Side.CODEX if round_id == "ab-codex-1" else Side.RONDO
            for index, task_id in enumerate(self.tasks):
                values.append(
                    BaselineRun(
                        task_id,
                        round_id,
                        side,
                        1,
                        outcomes.get((round_id, task_id), TaskOutcome.PASS),
                        f"{round_id}-{index}-a1",
                    )
                )
                if (round_id, task_id) in second:
                    values.append(
                        BaselineRun(
                            task_id,
                            round_id,
                            side,
                            2,
                            second[(round_id, task_id)],
                            f"{round_id}-{index}-a2",
                        )
                    )
        return tuple(values)

    def _conditional(
        self,
        task_id: str,
        rondo: TaskOutcome,
        codex: TaskOutcome,
    ) -> tuple[ConditionalRun, ...]:
        return tuple(
            ConditionalRun(
                task_id,
                side,
                repeat,
                1,
                rondo if side is Side.RONDO else codex,
                f"conditional-{side.value}-{repeat}",
            )
            for side in (Side.RONDO, Side.CODEX)
            for repeat in (1, 2)
        )

    def test_cost_forecast_is_recomputable_and_below_cap_for_observed_shape(self) -> None:
        forecast = cost_forecast()
        self.assertEqual(forecast["base_point_estimate_usd"], "17.829510")
        self.assertEqual(forecast["full_condition_point_estimate_usd"], "35.529550")
        self.assertEqual(forecast["v19_shape_stress_with_canary_usd"], "173.653100")
        self.assertEqual(forecast["prior_estimated_usd"], "281.718702")
        self.assertEqual(
            forecast["remaining_before_v9_canary_usd"], "318.281298"
        )
        self.assertTrue(forecast["feasible_from_observed_shape"])
        self.assertFalse(forecast["mathematical_all_legal_usage_guarantee"])
        tracked = json.loads(
            (EVAL_ROOT / "tasksets/p2-b7-cost-forecast.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(tracked, forecast)

    def test_results_worktree_cannot_be_the_live_eval_harness(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        with self.assertRaisesRegex(
            baseline_cli.CampaignExecutionError,
            "results worktree must be distinct",
        ):
            baseline_cli._require_distinct_results_worktree(
                paths,
                paths.worktree_root,
            )

        distinct = paths.common_root / ".claude/worktrees/distinct-results"
        baseline_cli._require_distinct_results_worktree(paths, distinct)

    def test_campaign_lease_is_exclusive_and_reacquirable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executor.lock"
            with baseline_cli.CampaignExecutionLease(path) as lease:
                self.assertGreaterEqual(lease.descriptor, 0)
                baseline_cli._require_held_campaign_lease(path, lease.token)
                with self.assertRaisesRegex(
                    baseline_cli.CampaignExecutionError,
                    "already owns",
                ):
                    with baseline_cli.CampaignExecutionLease(path):
                        pass
            with self.assertRaisesRegex(
                baseline_cli.CampaignExecutionError,
                "not held",
            ):
                baseline_cli._require_held_campaign_lease(path, path.read_text().strip())
            with baseline_cli.CampaignExecutionLease(path):
                pass

    def test_locked_worker_environment_is_minimal_and_secret_free(self) -> None:
        environment = baseline_cli._locked_worker_environment(
            {
                "PATH": "/usr/bin",
                "HOME": "/tmp/home",
                "OPENAI_API_KEY": "secret",
                "OTHER_PROVIDER_TOKEN": "secret",
                "HTTP_PROXY": "http://ambient.invalid",
                "RONDO_BUILD_METRICS_DIR": "/tmp/metrics",
            },
            worktree_root=Path("/repo"),
        )
        self.assertEqual(environment["PATH"], "/usr/bin")
        self.assertEqual(environment["RONDO_BUILD_METRICS_DIR"], "/tmp/metrics")
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("OTHER_PROVIDER_TOKEN", environment)
        self.assertNotIn("HTTP_PROXY", environment)
        self.assertEqual(environment["NO_PROXY"], "127.0.0.1,localhost")
        self.assertEqual(environment["PYTHONPATH"], "/repo/eval")

    def test_coordinator_projects_one_locked_worker_step(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        args = argparse.Namespace(
            docker_host_volume=Path("/docker-data"),
            results_worktree_root=Path("/results"),
            rondo_measurement_worktree_root=Path("/rondo"),
            codex_measurement_worktree_root=Path("/codex"),
        )
        argv = baseline_cli._locked_worker_argv(paths, args, lease_token="a" * 64)
        self.assertEqual(
            argv[0],
            str(paths.worktree_root / "mydev/scripts/with-build-lock.sh"),
        )
        self.assertIn("--worker-step", argv)
        self.assertEqual(argv.count("--worker-step"), 1)
        self.assertIn("--campaign-lease-token", argv)

    def test_campaign_lock_freezes_unique_full_slot_space_and_profile(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        identity = load_historical_campaign_identity(paths, 9)

        self.assertEqual(len(identity.slots), 161)
        self.assertEqual(len({item.run_id for item in identity.slots}), 161)
        self.assertEqual(len({item.slot_id for item in identity.slots}), 161)
        self.assertEqual(identity.slots[0].slot_id, "wire-canary")
        self.assertEqual(identity.campaign_id, "p2-b7-canary-baseline-v9")
        self.assertEqual(identity.batch_id, "p2-b7-canary-sol-sol-v9")
        self.assertEqual(identity.budget["campaign_cap_usd"], "600.000000")
        self.assertEqual(identity.budget["prior_estimated_usd"], "281.718702")
        identity.validate_provider(load_runtime_config(paths).paid_provider_projection())

    def test_registry_keeps_history_read_only_and_only_latest_active(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        registry = campaign_lock_registry(paths)
        self.assertEqual(
            tuple(item.version for item in registry),
            tuple(range(1, len(registry) + 1)),
        )
        self.assertGreaterEqual(len(registry), 10)
        self.assertEqual(registry[-1].campaign_id, "p2-b7-canary-baseline-v10")
        active = load_campaign_identity(paths)
        self.assertEqual(active.campaign_id, registry[-1].campaign_id)
        self.assertEqual(active.lock_sha256, registry[-1].lock_sha256)
        pointer = json.loads(
            (paths.worktree_root / CAMPAIGN_ACTIVE_POINTER_PATH).read_text()
        )
        self.assertEqual(pointer["active_lock"], registry[-1].path.as_posix())
        self.assertEqual(
            load_historical_campaign_identity(paths, 9).campaign_id,
            "p2-b7-canary-baseline-v9",
        )

    def test_campaign_registry_sorts_multi_digit_versions_numerically(self) -> None:
        live = RepoPaths.discover(Path.cwd())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            locks = root / "eval/locks"
            locks.mkdir(parents=True)
            for version in range(1, 10):
                source = (
                    live.worktree_root
                    / f"eval/locks/p2-b7-canary-baseline-v{version}.json"
                )
                (locks / source.name).write_bytes(source.read_bytes())
            value = json.loads(
                (locks / "p2-b7-canary-baseline-v9.json").read_text()
            )
            value.update(
                campaign_id="p2-b7-canary-baseline-v10",
                batch_id="p2-b7-canary-sol-sol-v10",
                run_id_sequence_base=300000000,
            )
            (locks / "p2-b7-canary-baseline-v10.json").write_text(
                json.dumps(value), encoding="utf-8"
            )
            registry = campaign_lock_registry(RepoPaths(root, root))
            self.assertEqual(
                tuple(item.version for item in registry), tuple(range(1, 11))
            )

    def test_successor_prior_is_derived_from_terminal_v9_facts(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        self.assertEqual(
            required_successor_prior(paths, version=9),
            Decimal("282.287684"),
        )

    def test_successor_run_range_rejects_history_and_accepts_fresh_ids(self) -> None:
        registry = campaign_lock_registry(RepoPaths.discover(Path.cwd()))
        with self.assertRaisesRegex(
            CampaignIdentityGenerationError,
            "collides",
        ):
            validate_successor_run_range(
                registry,
                run_id_date=registry[-1].run_id_date,
                run_id_sequence_base=registry[-1].run_id_sequence_base,
            )
        validate_successor_run_range(
            registry,
            run_id_date="20260812",
            run_id_sequence_base=310000000,
        )

    def test_campaign_lock_catalog_drift_is_rejected(self) -> None:
        live_paths = RepoPaths.discover(Path.cwd())
        live = load_historical_campaign_identity(live_paths, 9)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval/locks").mkdir(parents=True)
            lock = json.loads(
                (
                    live_paths.worktree_root
                    / "eval/locks/p2-b7-canary-baseline-v9.json"
                ).read_text()
            )
            lock["canary_catalog_sha256"] = "0" * 64
            lock_path = root / "eval/locks/p2-b7-canary-baseline-v9.json"
            lock_path.write_text(
                json.dumps(lock), encoding="utf-8"
            )
            with mock.patch(
                "rondo_eval.terminal_bench.baseline.load_frozen_canary_catalog",
                return_value=live.catalog,
            ):
                with self.assertRaisesRegex(Exception, "contract"):
                    load_campaign_identity_path(
                        RepoPaths(root, root),
                        Path("eval/locks/p2-b7-canary-baseline-v9.json"),
                    )

    def test_campaign_state_ledger_is_single_claim_and_crash_closed(self) -> None:
        identity = self._identity()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            with CampaignStateLedger(path, identity=identity) as ledger:
                ledger.claim("wire-canary")
                with self.assertRaisesRegex(BaselineError, "not claimable"):
                    ledger.claim("wire-canary")
                ledger.finish(
                    "wire-canary",
                    status=CampaignSlotStatus.COMPLETED,
                    outcome="completed",
                    estimated_usd="0.123456",
                    artifact_path="eval-data/campaigns/canary/receipt.json",
                    result_record_sha256="1" * 64,
                    reason=None,
                )
            with CampaignStateLedger(path, identity=identity) as ledger:
                snapshot = ledger.snapshot()
                self.assertEqual(snapshot["slots"][0]["status"], "completed")

            state = json.loads(path.read_text())
            state["slots"][1]["status"] = "running"
            path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(BaselineError, "crash-interrupted"):
                with CampaignStateLedger(path, identity=identity):
                    pass
            with CampaignStateLedger(
                path,
                identity=identity,
                allow_interrupted_recovery=True,
            ) as ledger:
                recovered = ledger.fail_interrupted(
                    estimated_usd="18.885000",
                    reason="interrupted_request",
                )
                self.assertEqual(recovered, identity.slots[1].slot_id)
                snapshot = ledger.snapshot()
                self.assertEqual(snapshot["slots"][1]["status"], "failed")
                self.assertEqual(snapshot["slots"][1]["outcome"], "infra_failed")

    def test_interrupted_paid_slot_reconciles_publication_without_reexecution(self) -> None:
        identity = self._identity()
        slot = identity.slots[1]
        run = {
            "cap_usd": "40.000000",
            "spent_usd": "0.100000",
            "stopped": False,
            "stop_reason": None,
            "requests": {
                "request": {
                    "status": "settled",
                    "charged_usd": "0.100000",
                    "reserved_usd": "18.885000",
                    "usage_valid": True,
                    "attempt_count": 1,
                    "settlement_kind": "usage_priced",
                }
            },
        }
        record = {
            "run_id": slot.run_id,
            "outcome": "completed",
            "artifacts": f"eval-data/runs/{slot.run_id}",
            "config": {
                "campaign_id": identity.campaign_id,
                "campaign_lock_sha256": identity.lock_sha256,
                "campaign_slot_id": slot.slot_id,
            },
            "cost": {"estimated_usd": 0.1, "actual_usd": None},
            "summary": {"evidence": []},
            "tasks": [{"task_id": slot.task_id, "outcome": "fail"}],
        }

        class Budget:
            def snapshot(self):
                return {"runs": {slot.run_id: run}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            (results / "eval/results").mkdir(parents=True)
            line = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
            (results / "eval/results/runs.jsonl").write_bytes(line + b"\n")
            state_path = root / "state.json"
            with CampaignStateLedger(
                state_path,
                identity=identity,
                allow_interrupted_recovery=True,
            ) as state:
                state.claim(slot.slot_id)
                with mock.patch.object(baseline_cli, "_sample_storage"):
                    baseline_cli._reconcile_running_paid_slot(
                        paths=RepoPaths.discover(Path.cwd()),
                        identity=identity,
                        state=state,
                        budget=Budget(),
                        counter=mock.Mock(),
                        storage_baseline=baseline_cli.StorageBaseline(1, 1, 1),
                        results_root=results,
                    )
                row = next(
                    item for item in state.snapshot()["slots"]
                    if item["slot_id"] == slot.slot_id
                )
                self.assertEqual(row["status"], "completed")
                self.assertEqual(row["estimated_usd"], "0.100000")
                self.assertEqual(row["result_record_sha256"], hashlib.sha256(line).hexdigest())

    def test_interrupted_paid_slot_without_publication_is_blocked_not_retried(self) -> None:
        identity = self._identity()
        slot = identity.slots[1]

        class Budget:
            def snapshot(self):
                return {
                    "runs": {
                        slot.run_id: {
                            "spent_usd": "18.885000",
                            "requests": {},
                        }
                    }
                }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            (results / "eval/results").mkdir(parents=True)
            (results / "eval/results/runs.jsonl").write_text("", encoding="utf-8")
            with CampaignStateLedger(
                root / "state.json",
                identity=identity,
                allow_interrupted_recovery=True,
            ) as state:
                state.claim(slot.slot_id)
                with self.assertRaisesRegex(
                    baseline_cli.CampaignExecutionError,
                    "interrupted ambiguously",
                ):
                    baseline_cli._reconcile_running_paid_slot(
                        paths=RepoPaths.discover(Path.cwd()),
                        identity=identity,
                        state=state,
                        budget=Budget(),
                        counter=mock.Mock(),
                        storage_baseline=baseline_cli.StorageBaseline(1, 1, 1),
                        results_root=results,
                    )
                row = next(
                    item for item in state.snapshot()["slots"]
                    if item["slot_id"] == slot.slot_id
                )
                self.assertEqual(row["status"], "failed")
                self.assertEqual(row["reason"], "operator_interruption")

    def test_campaign_base_orchestrator_activates_only_mechanical_replacements(self) -> None:
        identity = self._identity()

        class State:
            skipped: list[str] = []

            def skip(self, slot_id: str, *, reason: str) -> None:
                del reason
                self.skipped.append(slot_id)

        state = State()
        calls: list[str] = []

        def execute(*, slot, task, **kwargs):
            del task, kwargs
            calls.append(slot.slot_id)
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.COMPLETED,
                TaskOutcome.PASS,
                Decimal("0.100000"),
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            values = baseline_cli._execute_base_rounds(
                identity=identity,
                state=state,
            )
        self.assertEqual((len(calls), len(values), len(state.skipped)), (40, 40, 40))
        self.assertTrue(all(":a1" in value for value in calls))

    def test_resumable_orchestrator_executes_at_most_one_paid_slot(self) -> None:
        identity = self._identity()

        class Budget:
            def snapshot(self):
                return {"runs": {}, "spent_usd": "0.000000"}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = root / "results"
            (results / "eval/results").mkdir(parents=True)
            (results / "eval/results/runs.jsonl").write_text("", encoding="utf-8")
            with CampaignStateLedger(root / "state.json", identity=identity) as state:
                state.claim("wire-canary")
                state.finish(
                    "wire-canary",
                    status=CampaignSlotStatus.COMPLETED,
                    outcome="completed",
                    estimated_usd="0.100000",
                    artifact_path="eval-data/canary/receipt.json",
                    result_record_sha256="1" * 64,
                    reason=None,
                )
                with mock.patch.object(
                    baseline_cli,
                    "_execute_task_slot",
                    side_effect=baseline_cli._CampaignStepAdvanced,
                ) as execute:
                    result = baseline_cli._advance_one_paid_step(
                        paths=RepoPaths.discover(Path.cwd()),
                        identity=identity,
                        state=state,
                        budget=Budget(),
                        counter=mock.Mock(),
                        storage_baseline=baseline_cli.StorageBaseline(1, 1, 1),
                        results_root=results,
                        campaign_root=root,
                        canary_cost=Decimal("0.100000"),
                    )
                self.assertEqual(result, 10)
                execute.assert_called_once()
                self.assertEqual(
                    execute.call_args.kwargs["slot"].slot_id,
                    f"base:aa-rondo-1:{identity.catalog.tasks[0].task_id}:a1",
                )

    def test_targeted_retries_recover_infra_without_rerunning_other_tasks(self) -> None:
        identity = self._identity()

        class State:
            skipped: list[str]

            def __init__(self) -> None:
                self.skipped = []

            def skip(self, slot_id: str, *, reason: str) -> None:
                del reason
                self.skipped.append(slot_id)

        calls: list[str] = []
        target = identity.catalog.tasks[0].task_id

        def execute(*, slot, task, **kwargs):
            del task, kwargs
            calls.append(slot.slot_id)
            infra = slot.task_id == target and slot.round_id == "aa-rondo-1" and slot.attempt == 1
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.INFRA_FAILED if infra else RunOutcome.COMPLETED,
                TaskOutcome.INFRA if infra else TaskOutcome.PASS,
                Decimal("0.100000"),
                (
                    MechanicalFailureCategory.DOCKER_RUNTIME
                    if infra
                    else None
                ),
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            values = baseline_cli._execute_base_rounds(identity=identity, state=State())
        self.assertEqual(len(calls), 41)
        self.assertEqual(sum(":a2" in item for item in calls), 1)
        self.assertEqual(len(values), 41)

    def test_pass_and_normal_reward_zero_do_not_activate_replacement(self) -> None:
        identity = self._identity()

        class State:
            def skip(self, slot_id: str, *, reason: str) -> None:
                del slot_id, reason

        calls: list[str] = []

        def execute(*, slot, task, **kwargs):
            del task, kwargs
            calls.append(slot.slot_id)
            outcome = (
                TaskOutcome.FAIL
                if slot.task_id == identity.catalog.tasks[0].task_id
                else TaskOutcome.PASS
            )
            return baseline_cli.ExecutedSlot(
                slot, RunOutcome.COMPLETED, outcome, Decimal("0.100000")
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            baseline_cli._execute_base_rounds(identity=identity, state=State())
        self.assertEqual(len(calls), 40)
        self.assertTrue(all(":a1" in item for item in calls))

    def test_two_remaining_infra_per_round_can_continue(self) -> None:
        identity = self._identity()

        class State:
            def skip(self, slot_id: str, *, reason: str) -> None:
                del slot_id, reason

        task_ids = tuple(item.task_id for item in identity.catalog.tasks)
        calls: list[str] = []

        def execute(*, slot, task, **kwargs):
            del task, kwargs
            calls.append(slot.slot_id)
            index = task_ids.index(slot.task_id)
            infra = index < 2
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.INFRA_FAILED if infra else RunOutcome.COMPLETED,
                TaskOutcome.INFRA if infra else TaskOutcome.PASS,
                Decimal("0.100000"),
                (
                    MechanicalFailureCategory.DOCKER_RUNTIME
                    if infra
                    else None
                ),
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            values = baseline_cli._execute_base_rounds(
                identity=identity,
                state=State(),
            )
        self.assertEqual(len(calls), 48)
        self.assertEqual(len(values), 48)

    def test_three_same_category_tasks_open_circuit_before_later_claims(self) -> None:
        identity = self._identity()

        class State:
            def skip(self, slot_id: str, *, reason: str) -> None:
                del slot_id, reason

        calls: list[str] = []
        task_ids = tuple(item.task_id for item in identity.catalog.tasks)

        def execute(*, slot, task, **kwargs):
            del task, kwargs
            calls.append(slot.slot_id)
            infra = task_ids.index(slot.task_id) < 3
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.INFRA_FAILED if infra else RunOutcome.COMPLETED,
                TaskOutcome.INFRA if infra else TaskOutcome.PASS,
                Decimal("0.100000"),
                MechanicalFailureCategory.PROVIDER_RESPONSE_INTEGRITY if infra else None,
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            with self.assertRaisesRegex(
                baseline_cli.CampaignExecutionError,
                "mechanical_circuit_breaker:provider_response_integrity",
            ):
                baseline_cli._execute_base_rounds(identity=identity, state=State())
        self.assertEqual(len(calls), 5)
        self.assertNotIn(identity.catalog.tasks[3].task_id, " ".join(calls))

    def test_round_infra_gate_precedes_next_round(self) -> None:
        identity = self._identity()

        class State:
            def skip(self, slot_id: str, *, reason: str) -> None:
                del slot_id, reason

        categories = (
            MechanicalFailureCategory.PROVIDER_RESPONSE_INTEGRITY,
            MechanicalFailureCategory.DOCKER_RUNTIME,
            MechanicalFailureCategory.HARNESS_RUNTIME,
        )
        calls: list[str] = []
        task_ids = tuple(item.task_id for item in identity.catalog.tasks)

        def execute(*, slot, task, **kwargs):
            del task, kwargs
            calls.append(slot.slot_id)
            index = task_ids.index(slot.task_id)
            infra = index < 3
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.INFRA_FAILED if infra else RunOutcome.COMPLETED,
                TaskOutcome.INFRA if infra else TaskOutcome.PASS,
                Decimal("0.100000"),
                categories[index] if infra else None,
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            with self.assertRaisesRegex(
                baseline_cli.CampaignExecutionError,
                "base_round_infra_threshold_exceeded:aa-rondo-1",
            ):
                baseline_cli._execute_base_rounds(identity=identity, state=State())
        self.assertEqual(len(calls), 13)
        self.assertTrue(all("aa-rondo-1" in item for item in calls))

    def test_structured_failure_category_inherits_budget_root_cause(self) -> None:
        provider = baseline_cli._mechanical_failure_category(
            task_outcome=TaskOutcome.INFRA,
            failure_stage="publication",
            guardian_technical_failure=False,
            budget_run={
                "stopped": True,
                "stop_reason": "upstream_response_unavailable",
            },
        )
        docker = baseline_cli._mechanical_failure_category(
            task_outcome=TaskOutcome.INFRA,
            failure_stage="docker",
            guardian_technical_failure=False,
            budget_run={"stopped": False, "stop_reason": None},
        )
        ordinary = baseline_cli._mechanical_failure_category(
            task_outcome=TaskOutcome.FAIL,
            failure_stage=None,
            guardian_technical_failure=False,
            budget_run={"stopped": False, "stop_reason": None},
        )
        self.assertEqual(
            provider, MechanicalFailureCategory.PROVIDER_RESPONSE_INTEGRITY
        )
        self.assertEqual(docker, MechanicalFailureCategory.DOCKER_RUNTIME)
        self.assertIsNone(ordinary)

    def test_storage_projection_keeps_initial_final_and_growth(self) -> None:
        initial = baseline_cli.StorageBaseline(100, 200, 300)
        final = baseline_cli.StorageBaseline(120, 250, 280)
        self.assertEqual(
            baseline_cli._storage_projection(initial, final),
            {
                "initial": {
                    "docker_total_bytes": 100,
                    "docker_desktop_vhdx_bytes": 200,
                    "windows_free_bytes": 300,
                },
                "final": {
                    "docker_total_bytes": 120,
                    "docker_desktop_vhdx_bytes": 250,
                    "windows_free_bytes": 280,
                },
                "growth_bytes": 50,
            },
        )
        self.assertIsNone(
            baseline_cli._storage_projection(initial, None)["final"]
        )

    def test_public_campaign_aggregate_scores_rounds_and_sums_usage(self) -> None:
        base = self._base()
        assessment = assess_baseline(self.tasks, base, ())
        records = {
            item.run_id: {
                "outcome": "completed",
                "tasks": [{"task_id": item.task_id, "outcome": "pass"}],
                "summary": {"evidence": []},
            }
            for item in base
        }
        public = baseline_cli._public_assessment(assessment, records)
        self.assertEqual(public["sigma"], 0)
        self.assertEqual(
            public["base_rounds"]["aa-rondo-1"]["summary"]["success_rate"],
            1.0,
        )

        with tempfile.TemporaryDirectory() as directory:
            common = Path(directory)
            artifact = common / "eval-data/runs/example"
            artifact.mkdir(parents=True)
            (artifact / "api-metadata.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "requests": [
                            {
                                "usage": {
                                    "input_tokens": 10,
                                    "cached_input_tokens": 2,
                                    "cache_write_input_tokens": 1,
                                    "output_tokens": 3,
                                }
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            usage = baseline_cli._campaign_usage(
                common,
                {
                    "run": {
                        "artifacts": "eval-data/runs/example",
                        "summary": {"metadata_ready": True},
                    }
                },
            )
        self.assertEqual(
            usage,
            {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "cache_write_input_tokens": 1,
                "output_tokens": 3,
            },
        )

    def test_happy_path_has_zero_sigma_and_delta(self) -> None:
        result = assess_baseline(self.tasks, self._base(), ())
        self.assertEqual((result.status, result.sigma, result.delta), (BaselineStatus.PASSED, 0, 0))

    def test_three_infra_targeted_replacements_block_round(self) -> None:
        round_id = "aa-rondo-1"
        outcomes = {
            (round_id, task_id): TaskOutcome.INFRA for task_id in self.tasks[:3]
        }
        targeted_second = {
            (round_id, task_id): TaskOutcome.PASS for task_id in self.tasks[:3]
        }
        result = assess_baseline(
            self.tasks,
            self._base(outcomes, second=targeted_second),
            (),
        )
        self.assertEqual(result.status, BaselineStatus.PASSED)

        still_infra = {
            (round_id, task_id): TaskOutcome.INFRA for task_id in self.tasks[:3]
        }
        result = assess_baseline(
            self.tasks,
            self._base(outcomes, second=still_infra),
            (),
        )
        self.assertEqual(result.status, BaselineStatus.BLOCKED)
        self.assertIn(f"{round_id}_infra_threshold_exceeded", result.reasons)

    def test_two_infra_use_only_targeted_replacements(self) -> None:
        round_id = "aa-rondo-1"
        outcomes = {
            (round_id, task_id): TaskOutcome.INFRA for task_id in self.tasks[:2]
        }
        second = {(round_id, task_id): TaskOutcome.PASS for task_id in self.tasks[:2]}
        result = assess_baseline(self.tasks, self._base(outcomes, second=second), ())
        self.assertEqual(result.status, BaselineStatus.PASSED)

    def test_sigma_and_delta_boundaries_are_enforced(self) -> None:
        outcomes = {
            ("aa-rondo-2", self.tasks[index]): TaskOutcome.FAIL for index in range(3)
        }
        result = assess_baseline(self.tasks, self._base(outcomes), ())
        self.assertEqual(result.status, BaselineStatus.FAILED)
        self.assertIn("aa_sigma_exceeds_frozen_stability_limit", result.reasons)

        outcomes = {
            ("ab-rondo-1", self.tasks[0]): TaskOutcome.FAIL,
        }
        result = assess_baseline(
            self.tasks,
            self._base(outcomes),
            self._conditional(self.tasks[0], TaskOutcome.PASS, TaskOutcome.PASS),
        )
        self.assertEqual((result.sigma, result.delta), (0, 1))
        self.assertIn("ab_delta_exceeds_aa_sigma", result.reasons)

    def test_stable_directional_regression_fails_after_required_reruns(self) -> None:
        outcomes = {("ab-rondo-1", self.tasks[0]): TaskOutcome.FAIL}
        result = assess_baseline(
            self.tasks,
            self._base(outcomes),
            self._conditional(self.tasks[0], TaskOutcome.FAIL, TaskOutcome.PASS),
        )
        self.assertEqual(result.status, BaselineStatus.FAILED)
        self.assertIn(
            f"stable_directional_regression:{self.tasks[0]}", result.reasons
        )

    def test_sigma_delta_share_the_same_common_valid_denominator(self) -> None:
        round_id = "aa-rondo-1"
        outcomes = {(round_id, self.tasks[0]): TaskOutcome.INFRA}
        second = {(round_id, self.tasks[0]): TaskOutcome.INFRA}
        result = assess_baseline(self.tasks, self._base(outcomes, second=second), ())
        self.assertEqual(result.status, BaselineStatus.PASSED)
        self.assertEqual(result.common_valid_tasks, self.tasks[1:])
        self.assertEqual((result.sigma, result.delta), (0, 0))

        outcomes = {
            (BASE_ROUNDS[index], self.tasks[index]): TaskOutcome.INFRA
            for index in range(3)
        }
        second = dict(outcomes)
        result = assess_baseline(self.tasks, self._base(outcomes, second=second), ())
        self.assertEqual(result.status, BaselineStatus.BLOCKED)
        self.assertEqual(len(result.common_valid_tasks), 7)
        self.assertIsNone(result.sigma)
        self.assertIsNone(result.delta)

    def test_common_denominator_block_does_not_start_conditionals(self) -> None:
        identity = self._identity()
        task_ids = tuple(item.task_id for item in identity.catalog.tasks)
        outcomes = {
            (BASE_ROUNDS[index], task_ids[index]): TaskOutcome.INFRA
            for index in range(3)
        }
        runs: list[BaselineRun] = []
        for round_id in BASE_ROUNDS:
            side = Side.CODEX if round_id == "ab-codex-1" else Side.RONDO
            for index, task_id in enumerate(task_ids):
                outcome = outcomes.get((round_id, task_id), TaskOutcome.PASS)
                runs.append(
                    BaselineRun(
                        task_id,
                        round_id,
                        side,
                        1,
                        outcome,
                        f"{round_id}-{index}-a1",
                    )
                )
                if outcome is TaskOutcome.INFRA:
                    runs.append(
                        BaselineRun(
                            task_id,
                            round_id,
                            side,
                            2,
                            TaskOutcome.INFRA,
                            f"{round_id}-{index}-a2",
                        )
                    )

        class State:
            skipped: list[str]

            def __init__(self) -> None:
                self.skipped = []

            def skip(self, slot_id: str, *, reason: str) -> None:
                self.skipped.append(f"{slot_id}:{reason}")

        state = State()
        with mock.patch.object(baseline_cli, "_execute_task_slot") as execute:
            conditionals = baseline_cli._execute_conditionals(
                identity=identity,
                state=state,
                base_runs=runs,
            )
        self.assertEqual(conditionals, [])
        execute.assert_not_called()
        self.assertEqual(len(state.skipped), 80)
        self.assertTrue(
            all("common_valid_task_count_below_minimum" in item for item in state.skipped)
        )


if __name__ == "__main__":
    unittest.main()
