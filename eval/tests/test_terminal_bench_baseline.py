from __future__ import annotations

import json
import hashlib
import argparse
import sys
import tempfile
import unittest
from dataclasses import replace
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
    ContinuationReference,
    DiagnosisDisposition,
    DiagnosisEvidenceCode,
    DiagnosisStatus,
    MechanicalFailureCategory,
    assess_baseline,
    campaign_baseline_contract,
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
    _successor_continuation,
    required_successor_prior,
    validate_successor_run_range,
)


class TerminalBenchBaselineTests(unittest.TestCase):
    tasks = tuple(f"terminal-bench/task-{index}" for index in range(10))

    @staticmethod
    def _identity():
        return load_historical_campaign_identity(RepoPaths.discover(Path.cwd()), 9)

    @classmethod
    def _identity_v2(cls):
        legacy = cls._identity()
        return replace(
            legacy,
            schema_version=2,
            budget={
                **legacy.budget,
                "campaign_cap_usd": "700.000000",
                "prior_estimated_usd": "343.896195",
                "max_run_slots": 321,
            },
            baseline=campaign_baseline_contract(2),
        )

    @classmethod
    def _identity_v3(cls):
        legacy = cls._identity_v2()
        return replace(
            legacy,
            schema_version=3,
            budget={
                **legacy.budget,
                "campaign_cap_usd": "1000.000000",
                "prior_estimated_usd": "826.674430",
            },
            baseline=campaign_baseline_contract(3),
        )

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
        self.assertEqual(forecast["prior_estimated_usd"], "826.674430")
        self.assertEqual(
            forecast["remaining_before_successor_canary_usd"], "173.325570"
        )
        self.assertFalse(forecast["feasible_from_observed_shape"])
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

        successor = self._identity_v2()
        self.assertEqual(successor.schema_version, 2)
        self.assertEqual(successor.max_attempts, 4)
        self.assertEqual(len(successor.slots), 321)
        self.assertEqual(len({item.run_id for item in successor.slots}), 321)
        self.assertEqual(len({item.slot_id for item in successor.slots}), 321)

    def test_registry_keeps_history_read_only_and_only_latest_active(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        registry = campaign_lock_registry(paths)
        self.assertEqual(
            tuple(item.version for item in registry),
            tuple(range(1, len(registry) + 1)),
        )
        self.assertGreaterEqual(len(registry), 16)
        self.assertEqual(
            registry[-1].campaign_id,
            f"p2-b7-canary-baseline-v{registry[-1].version}",
        )
        active = load_campaign_identity(paths)
        self.assertEqual(active.campaign_id, registry[-1].campaign_id)
        self.assertEqual(active.lock_sha256, registry[-1].lock_sha256)
        self.assertEqual(active.schema_version, 2)
        self.assertEqual(active.max_attempts, 4)
        self.assertEqual(len(active.slots), 321)
        self.assertIn(
            active.budget["campaign_cap_usd"],
            {"700.000000", "1000.000000"},
        )
        self.assertEqual(
            Decimal(active.budget["prior_estimated_usd"]),
            required_successor_prior(paths, version=registry[-2].version),
        )
        active_pids = {item.task_id: item.pids_limit for item in active.catalog.tasks}
        self.assertEqual(active_pids["terminal-bench/filter-js-from-html"], 4096)
        self.assertEqual(set(active_pids.values()), {256, 4096})
        pointer = json.loads(
            (paths.worktree_root / CAMPAIGN_ACTIVE_POINTER_PATH).read_text()
        )
        self.assertEqual(pointer["active_lock"], registry[-1].path.as_posix())
        retired = load_historical_campaign_identity(paths, 10)
        self.assertEqual(retired.campaign_id, "p2-b7-canary-baseline-v10")
        self.assertEqual(retired.schema_version, 1)
        self.assertEqual(retired.max_attempts, 2)
        self.assertEqual(len(retired.slots), 161)
        self.assertEqual(retired.budget["campaign_cap_usd"], "600.000000")
        v11 = load_historical_campaign_identity(paths, 11)
        self.assertEqual(v11.campaign_id, "p2-b7-canary-baseline-v11")
        self.assertEqual(v11.budget["prior_estimated_usd"], "343.896195")
        self.assertEqual(
            {item.pids_limit for item in v11.catalog.tasks},
            {256},
        )
        v12 = load_historical_campaign_identity(paths, 12)
        self.assertEqual(v12.campaign_id, "p2-b7-canary-baseline-v12")
        self.assertEqual(v12.budget["prior_estimated_usd"], "345.963147")
        self.assertEqual(
            v12.catalog.task("terminal-bench/filter-js-from-html").pids_limit,
            512,
        )
        v13 = load_historical_campaign_identity(paths, 13)
        self.assertEqual(v13.campaign_id, "p2-b7-canary-baseline-v13")
        self.assertEqual(v13.budget["prior_estimated_usd"], "385.923585")
        v14 = load_historical_campaign_identity(paths, 14)
        self.assertEqual(v14.campaign_id, "p2-b7-canary-baseline-v14")
        self.assertEqual(v14.budget["prior_estimated_usd"], "386.121920")
        self.assertEqual(
            v14.catalog.task("terminal-bench/filter-js-from-html").pids_limit,
            512,
        )
        v15 = load_historical_campaign_identity(paths, 15)
        self.assertEqual(v15.campaign_id, "p2-b7-canary-baseline-v15")
        self.assertEqual(v15.budget["prior_estimated_usd"], "406.691123")
        self.assertEqual(
            v15.catalog.task("terminal-bench/filter-js-from-html").pids_limit,
            1024,
        )
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

    def test_successor_prior_includes_the_immutable_v10_terminal_debit(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        self.assertEqual(
            required_successor_prior(paths, version=10),
            Decimal("343.896195"),
        )

    def test_successor_prior_includes_the_immutable_v11_terminal_debit(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        self.assertEqual(
            required_successor_prior(paths, version=11),
            Decimal("345.963147"),
        )

    def test_successor_prior_includes_the_immutable_v12_terminal_debit(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        self.assertEqual(
            required_successor_prior(paths, version=12),
            Decimal("385.923585"),
        )

    def test_successor_prior_includes_the_immutable_v13_terminal_debit(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        self.assertEqual(
            required_successor_prior(paths, version=13),
            Decimal("386.121920"),
        )

    def test_successor_prior_includes_the_immutable_v14_terminal_debit(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        self.assertEqual(
            required_successor_prior(paths, version=14),
            Decimal("406.691123"),
        )

    def test_successor_prior_includes_the_immutable_v15_terminal_debit(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        self.assertEqual(
            required_successor_prior(paths, version=15),
            Decimal("408.561823"),
        )

    def test_v18_continuation_reuses_first_noninfra_including_reward_zero(self) -> None:
        paths = RepoPaths.discover(Path.cwd())
        source = load_historical_campaign_identity(paths, 18)
        self.assertEqual(required_successor_prior(paths, version=18), Decimal("826.674430"))
        rows = _successor_continuation(paths, source)
        by_chain = {row["chain_id"]: row for row in rows}
        self.assertEqual(len(by_chain), 20)
        self.assertEqual(
            by_chain["base:aa-rondo-1:terminal-bench/sanitize-git-repo"]["source_run_id"],
            "20260812-380000048-tb-rondo-r2",
        )
        self.assertEqual(
            by_chain["base:ab-rondo-1:terminal-bench/db-wal-recovery"]["source_run_id"],
            "20260812-380000021-tb-rondo-r1",
        )
        self.assertNotIn(
            "base:aa-rondo-1:terminal-bench/vulnerable-secret",
            by_chain,
        )
        self.assertEqual(
            {row["source_upstream_timeout_seconds"] for row in rows},
            {"90.000"},
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
        latest_date = registry[-1].run_id_date
        fresh_base = max(
            item.run_id_sequence_base + item.max_run_slots
            for item in registry
            if item.run_id_date == latest_date
        )
        validate_successor_run_range(
            registry,
            run_id_date=latest_date,
            run_id_sequence_base=fresh_base,
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

    def test_idle_campaign_retirement_is_atomic_and_preserves_wire_fact(self) -> None:
        identity = self._identity_v2()
        reason = (
            "diagnosed_campaign_defect:"
            "local_implementation_defect:harness_runtime"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with CampaignStateLedger(path, identity=identity) as ledger:
                with self.assertRaisesRegex(BaselineError, "no durable execution fact"):
                    ledger.retire_blocked(reason=reason)
                ledger.claim("wire-canary")
                ledger.finish(
                    "wire-canary",
                    status=CampaignSlotStatus.COMPLETED,
                    outcome="completed",
                    estimated_usd="0.200000",
                    artifact_path="eval-data/campaigns/wire/receipt.json",
                    result_record_sha256="1" * 64,
                    reason=None,
                )
                ledger.retire_blocked(reason=reason)

            with CampaignStateLedger(path, identity=identity) as ledger:
                snapshot = ledger.snapshot()
                self.assertEqual(snapshot["status"], BaselineStatus.BLOCKED.value)
                self.assertEqual(snapshot["terminal_reason"], reason)
                statuses = [row["status"] for row in snapshot["slots"]]
                self.assertEqual(statuses.count(CampaignSlotStatus.COMPLETED.value), 1)
                self.assertEqual(
                    statuses.count(CampaignSlotStatus.SKIPPED.value),
                    len(identity.slots) - 1,
                )
                self.assertEqual(snapshot["slots"][0]["estimated_usd"], "0.200000")

    def test_post_oracle_worker_returns_after_wire_then_advances_paid_step(self) -> None:
        identity = self._identity_v2()
        unused = mock.Mock()
        kwargs = {
            "paths": RepoPaths.discover(Path.cwd()),
            "identity": identity,
            "campaign_root": Path("/campaign"),
            "budget_path": Path("/budget.json"),
            "config": unused,
            "counter": unused,
            "proof": unused,
            "storage_baseline": baseline_cli.StorageBaseline(1, 1, 1),
            "results_root": Path("/results"),
            "manifests": {},
            "measurement_roots": {},
            "measurement_commits": {},
            "eval_harness_commit": "a" * 40,
            "seccomp_profile": Path("/seccomp.json"),
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            with CampaignStateLedger(path, identity=identity) as ledger:
                with mock.patch.object(
                    baseline_cli, "_reconcile_running_wire_canary"
                ), mock.patch.object(
                    baseline_cli, "_execute_wire_canary"
                ) as execute_wire:
                    self.assertEqual(
                        baseline_cli._advance_post_oracle_step(
                            **kwargs,
                            state=ledger,
                        ),
                        10,
                    )
                execute_wire.assert_called_once()

                ledger.claim("wire-canary")
                ledger.finish(
                    "wire-canary",
                    status=CampaignSlotStatus.COMPLETED,
                    outcome="completed",
                    estimated_usd="0.200000",
                    artifact_path="eval-data/campaigns/wire/receipt.json",
                    result_record_sha256="1" * 64,
                    reason=None,
                )
                budget = mock.Mock()
                budget_context = mock.MagicMock()
                budget_context.__enter__.return_value = budget
                with mock.patch.object(
                    baseline_cli, "_reconcile_running_wire_canary"
                ), mock.patch.object(
                    baseline_cli, "load_provider_secret", return_value=("KEY", "secret")
                ), mock.patch.object(
                    baseline_cli,
                    "PersistentBudgetLedger",
                    return_value=budget_context,
                ), mock.patch.object(
                    baseline_cli, "_reconcile_running_paid_slot"
                ), mock.patch.object(
                    baseline_cli, "_advance_one_paid_step", return_value=10
                ) as advance_paid:
                    self.assertEqual(
                        baseline_cli._advance_post_oracle_step(
                            **kwargs,
                            state=ledger,
                        ),
                        10,
                    )
                advance_paid.assert_called_once()

    def test_schema_v2_diagnosis_hold_is_durable_and_gates_claims(self) -> None:
        identity = self._identity_v2()
        task_id = identity.catalog.tasks[0].task_id
        chain_id = f"base:aa-rondo-1:{task_id}"
        slots = tuple(identity.slot(f"{chain_id}:a{attempt}") for attempt in range(1, 5))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.json"
            with CampaignStateLedger(path, identity=identity) as ledger:
                for slot in slots[:2]:
                    ledger.claim(slot.slot_id)
                    ledger.finish(
                        slot.slot_id,
                        status=CampaignSlotStatus.COMPLETED,
                        outcome="infra_failed",
                        estimated_usd="0.100000",
                        artifact_path=f"eval-data/runs/{slot.run_id}",
                        result_record_sha256="1" * 64,
                        reason=MechanicalFailureCategory.DOCKER_RUNTIME.value,
                    )
                diagnosis = ledger.require_diagnosis(
                    chain_id=chain_id,
                    category=MechanicalFailureCategory.DOCKER_RUNTIME,
                    trigger_slot_ids=tuple(slot.slot_id for slot in slots[:2]),
                )
                self.assertEqual(diagnosis["status"], DiagnosisStatus.REQUIRED.value)
                with self.assertRaisesRegex(BaselineError, "unresolved diagnosis"):
                    ledger.claim(slots[2].slot_id)

            with CampaignStateLedger(path, identity=identity) as ledger:
                self.assertEqual(
                    ledger.snapshot()["diagnoses"][0]["status"],
                    DiagnosisStatus.REQUIRED.value,
                )
                ledger.resolve_diagnosis(
                    chain_id=chain_id,
                    category=MechanicalFailureCategory.DOCKER_RUNTIME,
                    disposition=DiagnosisDisposition.EXTERNAL_TRANSIENT,
                    evidence_code=DiagnosisEvidenceCode.DOCKER_COUNTER_COMMAND_FAILURE,
                )
                ledger.claim(slots[2].slot_id)
                ledger.finish(
                    slots[2].slot_id,
                    status=CampaignSlotStatus.COMPLETED,
                    outcome="infra_failed",
                    estimated_usd="0.100000",
                    artifact_path=f"eval-data/runs/{slots[2].run_id}",
                    result_record_sha256="2" * 64,
                    reason=MechanicalFailureCategory.DOCKER_RUNTIME.value,
                )
                ledger.mark_task_local_reproducible(
                    chain_id=chain_id,
                    category=MechanicalFailureCategory.DOCKER_RUNTIME,
                    trigger_slot_ids=tuple(slot.slot_id for slot in slots[:3]),
                )
                diagnosis = ledger.snapshot()["diagnoses"][0]
                self.assertEqual(
                    diagnosis["status"],
                    DiagnosisStatus.TASK_LOCAL_REPRODUCIBLE_INFRA.value,
                )
                self.assertEqual(len(diagnosis["trigger_slot_ids"]), 3)
                with mock.patch.object(
                    baseline_cli,
                    "_execute_task_slot",
                    side_effect=lambda *, slot, **kwargs: baseline_cli.ExecutedSlot(
                        slot,
                        RunOutcome.INFRA_FAILED,
                        TaskOutcome.INFRA,
                        Decimal("0.100000"),
                        MechanicalFailureCategory.DOCKER_RUNTIME,
                    ),
                ):
                    replayed = baseline_cli._execute_attempt_chain(
                        identity=identity,
                        state=ledger,
                        tracker=baseline_cli.MechanicalFailureTracker(),
                        task=identity.catalog.tasks[0],
                        chain_id=chain_id,
                    )
                self.assertEqual(len(replayed), 3)
                self.assertEqual(
                    next(
                        row
                        for row in ledger.snapshot()["slots"]
                        if row["slot_id"] == slots[3].slot_id
                    )["status"],
                    CampaignSlotStatus.SKIPPED.value,
                )

    def test_schema_v2_local_defect_resolution_blocks_any_new_claim(self) -> None:
        identity = self._identity_v2()
        task_id = identity.catalog.tasks[0].task_id
        chain_id = f"base:aa-rondo-1:{task_id}"
        slots = tuple(identity.slot(f"{chain_id}:a{attempt}") for attempt in range(1, 3))
        with tempfile.TemporaryDirectory() as directory:
            with CampaignStateLedger(Path(directory) / "state.json", identity=identity) as ledger:
                for slot in slots:
                    ledger.claim(slot.slot_id)
                    ledger.finish(
                        slot.slot_id,
                        status=CampaignSlotStatus.COMPLETED,
                        outcome="infra_failed",
                        estimated_usd="0.000000",
                        artifact_path=None,
                        result_record_sha256=None,
                        reason=MechanicalFailureCategory.HARNESS_RUNTIME.value,
                    )
                ledger.require_diagnosis(
                    chain_id=chain_id,
                    category=MechanicalFailureCategory.HARNESS_RUNTIME,
                    trigger_slot_ids=tuple(slot.slot_id for slot in slots),
                )
                with self.assertRaisesRegex(BaselineError, "evidence code disagrees"):
                    ledger.resolve_diagnosis(
                        chain_id=chain_id,
                        category=MechanicalFailureCategory.HARNESS_RUNTIME,
                        disposition=DiagnosisDisposition.EXTERNAL_TRANSIENT,
                        evidence_code=(
                            DiagnosisEvidenceCode.DOCKER_COUNTER_COMMAND_FAILURE
                        ),
                    )
                ledger.resolve_diagnosis(
                    chain_id=chain_id,
                    category=MechanicalFailureCategory.HARNESS_RUNTIME,
                    disposition=DiagnosisDisposition.LOCAL_IMPLEMENTATION_DEFECT,
                    evidence_code=DiagnosisEvidenceCode.LOCAL_CONTRACT_DEFECT_CONFIRMED,
                )
                with self.assertRaisesRegex(BaselineError, "terminal stop"):
                    ledger.claim(identity.slots[-1].slot_id)

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
                    reconciled = baseline_cli._reconcile_running_paid_slot(
                        paths=RepoPaths.discover(Path.cwd()),
                        identity=identity,
                        state=state,
                        budget=Budget(),
                        counter=mock.Mock(),
                        storage_baseline=baseline_cli.StorageBaseline(1, 1, 1),
                        results_root=results,
                    )
                self.assertTrue(reconciled)
                row = next(
                    item for item in state.snapshot()["slots"]
                    if item["slot_id"] == slot.slot_id
                )
                self.assertEqual(row["status"], "completed")
                self.assertEqual(row["estimated_usd"], "0.100000")
                self.assertEqual(row["result_record_sha256"], hashlib.sha256(line).hexdigest())

    def test_recovery_replay_stops_before_any_unclaimed_attempt(self) -> None:
        identity = self._identity_v2()
        task = identity.catalog.tasks[0]
        first = identity.slot(f"base:aa-rondo-1:{task.task_id}:a1")
        second = identity.slot(f"base:aa-rondo-1:{task.task_id}:a2")
        records: dict[str, dict[str, object]] = {}
        digests: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with CampaignStateLedger(root / "state.json", identity=identity) as state:
                for index, slot in enumerate((first, second), start=1):
                    digest = f"{index:064x}"
                    state.claim(slot.slot_id)
                    state.finish(
                        slot.slot_id,
                        status=CampaignSlotStatus.COMPLETED,
                        outcome=RunOutcome.INFRA_FAILED.value,
                        estimated_usd="0.100000",
                        artifact_path=f"eval-data/runs/{slot.run_id}",
                        result_record_sha256=digest,
                        reason=MechanicalFailureCategory.DOCKER_RUNTIME.value,
                    )
                    records[slot.run_id] = {
                        "run_id": slot.run_id,
                        "outcome": RunOutcome.INFRA_FAILED.value,
                        "artifacts": f"eval-data/runs/{slot.run_id}",
                    }
                    digests[slot.run_id] = digest
                with mock.patch.object(
                    baseline_cli,
                    "_campaign_records",
                    return_value=(records, digests),
                ), self.assertRaises(baseline_cli._CampaignDiagnosisRequired):
                    baseline_cli._replay_recovered_attempt_chain(
                        paths=RepoPaths.discover(Path.cwd()),
                        identity=identity,
                        state=state,
                        budget=mock.Mock(),
                        config=mock.Mock(),
                        counter=mock.Mock(),
                        proof=mock.Mock(),
                        storage_baseline=baseline_cli.StorageBaseline(1, 1, 1),
                        results_root=root,
                        manifests={},
                        measurement_roots={},
                        measurement_commits={},
                        eval_harness_commit="a" * 40,
                        seccomp_profile=root / "seccomp.json",
                        recovered_slot=second,
                    )
                third = identity.slot(f"base:aa-rondo-1:{task.task_id}:a3")
                self.assertEqual(
                    next(
                        row for row in state.snapshot()["slots"]
                        if row["slot_id"] == third.slot_id
                    )["status"],
                    CampaignSlotStatus.PLANNED.value,
                )

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

    def test_schema_v2_second_same_category_requires_diagnosis_before_a3(self) -> None:
        identity = self._identity_v2()
        task = identity.catalog.tasks[0]
        chain_id = f"base:aa-rondo-1:{task.task_id}"

        class State:
            def __init__(self) -> None:
                self.skipped: list[str] = []

            def skip(self, slot_id: str, *, reason: str) -> None:
                self.skipped.append(f"{slot_id}:{reason}")

            def require_diagnosis(self, **kwargs):
                del kwargs
                return {"status": DiagnosisStatus.REQUIRED.value}

            def mark_task_local_reproducible(self, **kwargs) -> None:
                raise AssertionError(kwargs)

        calls: list[str] = []

        def execute(*, slot, **kwargs):
            del kwargs
            calls.append(slot.slot_id)
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.INFRA_FAILED,
                TaskOutcome.INFRA,
                Decimal("0.100000"),
                MechanicalFailureCategory.DOCKER_RUNTIME,
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            with self.assertRaisesRegex(
                baseline_cli._CampaignDiagnosisRequired,
                "diagnosis_required",
            ):
                baseline_cli._execute_attempt_chain(
                    identity=identity,
                    state=State(),
                    tracker=baseline_cli.MechanicalFailureTracker(),
                    task=task,
                    chain_id=chain_id,
                )
        self.assertEqual(calls, [f"{chain_id}:a1", f"{chain_id}:a2"])

    def test_schema_v2_external_diagnosis_allows_a3_then_task_local_stop(self) -> None:
        identity = self._identity_v2()
        task = identity.catalog.tasks[0]
        chain_id = f"base:aa-rondo-1:{task.task_id}"

        class State:
            def __init__(self) -> None:
                self.skipped: list[str] = []
                self.marked: tuple[str, ...] | None = None

            def skip(self, slot_id: str, *, reason: str) -> None:
                self.skipped.append(f"{slot_id}:{reason}")

            def require_diagnosis(self, **kwargs):
                del kwargs
                return {
                    "status": DiagnosisStatus.RESOLVED.value,
                    "disposition": DiagnosisDisposition.EXTERNAL_TRANSIENT.value,
                }

            def mark_task_local_reproducible(self, **kwargs) -> None:
                self.marked = kwargs["trigger_slot_ids"]

        state = State()
        calls: list[str] = []

        def execute(*, slot, **kwargs):
            del kwargs
            calls.append(slot.slot_id)
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.INFRA_FAILED,
                TaskOutcome.INFRA,
                Decimal("0.100000"),
                MechanicalFailureCategory.DOCKER_RUNTIME,
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            values = baseline_cli._execute_attempt_chain(
                identity=identity,
                state=state,
                tracker=baseline_cli.MechanicalFailureTracker(),
                task=task,
                chain_id=chain_id,
            )
        self.assertEqual(len(values), 3)
        self.assertEqual(calls, [f"{chain_id}:a1", f"{chain_id}:a2", f"{chain_id}:a3"])
        self.assertEqual(state.marked, tuple(calls))
        self.assertEqual(len(state.skipped), 1)
        self.assertIn("task_local_reproducible_infra:docker_runtime", state.skipped[0])

    def test_schema_v2_mixed_categories_can_reach_a4_and_noninfra_stops(self) -> None:
        identity = self._identity_v2()
        task = identity.catalog.tasks[0]
        chain_id = f"base:aa-rondo-1:{task.task_id}"

        class State:
            def __init__(self) -> None:
                self.skipped: list[str] = []

            def skip(self, slot_id: str, *, reason: str) -> None:
                self.skipped.append(f"{slot_id}:{reason}")

            def require_diagnosis(self, **kwargs):
                raise AssertionError(kwargs)

            def mark_task_local_reproducible(self, **kwargs) -> None:
                raise AssertionError(kwargs)

        categories = (
            MechanicalFailureCategory.DOCKER_RUNTIME,
            MechanicalFailureCategory.GUARDIAN_RUNTIME,
            MechanicalFailureCategory.PUBLICATION_INTEGRITY,
        )
        calls: list[str] = []

        def execute(*, slot, **kwargs):
            del kwargs
            calls.append(slot.slot_id)
            if slot.attempt == 4:
                return baseline_cli.ExecutedSlot(
                    slot,
                    RunOutcome.COMPLETED,
                    TaskOutcome.FAIL,
                    Decimal("0.100000"),
                )
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.INFRA_FAILED,
                TaskOutcome.INFRA,
                Decimal("0.100000"),
                categories[slot.attempt - 1],
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            values = baseline_cli._execute_attempt_chain(
                identity=identity,
                state=State(),
                tracker=baseline_cli.MechanicalFailureTracker(),
                task=task,
                chain_id=chain_id,
            )
        self.assertEqual(len(values), 4)
        self.assertEqual(values[-1].task_outcome, TaskOutcome.FAIL)
        self.assertEqual(calls[-1], f"{chain_id}:a4")

        state = State()
        calls.clear()
        with mock.patch.object(
            baseline_cli,
            "_execute_task_slot",
            return_value=baseline_cli.ExecutedSlot(
                identity.slot(f"{chain_id}:a1"),
                RunOutcome.COMPLETED,
                TaskOutcome.PASS,
                Decimal("0.100000"),
            ),
        ) as execute_mock:
            values = baseline_cli._execute_attempt_chain(
                identity=identity,
                state=state,
                tracker=baseline_cli.MechanicalFailureTracker(),
                task=task,
                chain_id=chain_id,
            )
        self.assertEqual(len(values), 1)
        execute_mock.assert_called_once()
        self.assertEqual(len(state.skipped), 3)

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

    def test_schema_v3_provider_integrity_does_not_open_local_circuit(self) -> None:
        identity = self._identity_v3()
        tracker = baseline_cli.MechanicalFailureTracker(
            ignore_provider_integrity=True
        )
        for task in identity.catalog.tasks[:4]:
            slot = identity.slot(
                f"base:aa-rondo-1:{task.task_id}:a1"
            )
            tracker.observe(
                baseline_cli.ExecutedSlot(
                    slot,
                    RunOutcome.INFRA_FAILED,
                    TaskOutcome.INFRA,
                    Decimal("18.885000"),
                    MechanicalFailureCategory.PROVIDER_RESPONSE_INTEGRITY,
                )
            )
        docker = MechanicalFailureCategory.DOCKER_RUNTIME
        with self.assertRaisesRegex(
            baseline_cli.CampaignExecutionError,
            "mechanical_circuit_breaker:docker_runtime",
        ):
            for task in identity.catalog.tasks[:3]:
                tracker.observe(
                    baseline_cli.ExecutedSlot(
                        identity.slot(
                            f"base:aa-rondo-2:{task.task_id}:a1"
                        ),
                        RunOutcome.INFRA_FAILED,
                        TaskOutcome.INFRA,
                        Decimal("0.000000"),
                        docker,
                    )
                )

    def test_schema_v3_provider_integrity_does_not_trigger_round_infra_gate(self) -> None:
        identity = self._identity_v3()

        class State:
            def skip(self, slot_id: str, *, reason: str) -> None:
                del slot_id, reason

        task_ids = tuple(item.task_id for item in identity.catalog.tasks)

        def execute(*, slot, **kwargs):
            del kwargs
            infra = task_ids.index(slot.task_id) < 3
            return baseline_cli.ExecutedSlot(
                slot,
                RunOutcome.INFRA_FAILED if infra else RunOutcome.COMPLETED,
                TaskOutcome.INFRA if infra else TaskOutcome.PASS,
                Decimal("18.885000") if infra else Decimal("0.100000"),
                (
                    MechanicalFailureCategory.PROVIDER_RESPONSE_INTEGRITY
                    if infra
                    else None
                ),
            )

        with mock.patch.object(baseline_cli, "_execute_task_slot", side_effect=execute):
            values = baseline_cli._execute_base_rounds(
                identity=identity,
                state=State(),
            )
        self.assertEqual(len(values), 76)
        self.assertEqual(
            sum(item.outcome is TaskOutcome.INFRA for item in values),
            48,
        )

    def test_schema_v3_continuation_skips_new_attempts_and_keeps_reward_zero(self) -> None:
        identity = self._identity_v3()
        task = identity.catalog.tasks[0]
        chain_id = f"base:ab-rondo-1:{task.task_id}"
        source_slot = replace(
            identity.slot(f"{chain_id}:a1"),
            run_id="20260812-380000021-tb-rondo-r1",
        )
        reference = ContinuationReference(
            chain_id=chain_id,
            source_campaign_id="p2-b7-canary-baseline-v18",
            source_campaign_lock_sha256="a" * 64,
            source_slot_id=f"{chain_id}:a1",
            source_run_id=source_slot.run_id,
            source_result_record_sha256="b" * 64,
            source_upstream_timeout_seconds=Decimal("90.000"),
        )
        identity = replace(identity, continuation=(reference,))

        class State:
            def __init__(self) -> None:
                self.skipped: list[tuple[str, str]] = []

            def skip(self, slot_id: str, *, reason: str) -> None:
                self.skipped.append((slot_id, reason))

        continued = baseline_cli.ExecutedSlot(
            source_slot,
            RunOutcome.COMPLETED,
            TaskOutcome.FAIL,
            Decimal("0.476415"),
        )
        state = State()
        with mock.patch.object(
            baseline_cli,
            "_execute_task_slot",
            side_effect=AssertionError("continued result was rerun"),
        ):
            values = baseline_cli._execute_attempt_chain(
                identity=identity,
                state=state,
                tracker=baseline_cli.MechanicalFailureTracker(
                    ignore_provider_integrity=True
                ),
                task=task,
                chain_id=chain_id,
                continued={chain_id: continued},
            )
        self.assertEqual(values, [continued])
        self.assertEqual(len(state.skipped), 4)
        self.assertEqual({reason for _slot, reason in state.skipped}, {"continued_valid_result"})

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
