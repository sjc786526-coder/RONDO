from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.proactive_eval.aggregate import (  # noqa: E402
    aggregate,
    synthetic_team_view,
    write_replay_artifacts,
)
from rondo_eval.proactive_eval.campaign import (  # noqa: E402
    ExecutionResult,
    default_fake_executor,
    run_rehearsal,
)
from rondo_eval.proactive_eval.contract import (  # noqa: E402
    COMMON_V2_TOOL_NAMES,
    RONDO_TEAM_STATE_TOOL_NAMES,
    ContractError,
    load_contract,
)
from rondo_eval.proactive_eval.formal import (  # noqa: E402
    FormalDriftError,
    FormalError,
    FormalExecutionResult,
    FormalInfraError,
    FormalPaths,
    FormalStore,
    Plan049RequestPreflight,
    Plan049TerminalBenchExecutor,
    formal_identity,
    formal_paths,
    open_paid_ledger,
    plan049_provider_projection,
    require_safe_formal_prefix,
    run_formal_campaign,
)
from rondo_eval.proactive_eval.paid import (  # noqa: E402
    ACTIVATION_ACTION,
    LOCAL_ACTIVATION_CONFIRMATION,
    PHASE_B_AUTHORIZATION,
    PaidGuardError,
    PaidRuntimeDependencies,
    enter_paid_phase,
    production_paid_dependencies,
    run_authorized_paid_phase,
)
from rondo_eval.proactive_eval.__main__ import main as proactive_main  # noqa: E402
from rondo_eval.proactive_eval.readiness import (  # noqa: E402
    ReadinessError,
    require_phase_a_evidence,
    secret_readiness,
)
from rondo_eval.proactive_eval.recovery import (  # noqa: E402
    RECOVERY_ACTION,
    RECOVERY_ID,
    prepare_recovery_prefix,
    recovery_paths,
    require_safe_recovery_prefix,
)
from rondo_eval.proactive_eval.schedule import dry_run_projection, slots  # noqa: E402
from rondo_eval.proactive_eval.store import (  # noqa: E402
    RehearsalStore,
    StoreError,
    assert_body_free,
)
from rondo_eval.proactive_eval.trace import (  # noqa: E402
    ProactiveTraceError,
    select_proactive_root_bundle,
)
from rondo_eval.team_lens.model import dump_team_view  # noqa: E402
from rondo_eval.team_lens.report import render_report  # noqa: E402
from rondo_eval.config import RepoPaths, load_runtime_config  # noqa: E402
from rondo_eval.contracts import RunOutcome, Side  # noqa: E402
from rondo_eval.api_budget_proxy import BudgetStopped, Usage  # noqa: E402
from tests.test_team_lens import make_bundle  # noqa: E402


def _spawn_view(*, source_is_root: bool, tool_status: str) -> dict:
    view = synthetic_team_view(side="rondo", run_id="spawn-check", ordinal=1)
    root = view["source"]["root_thread_id"]
    child = "spawn-check-child"
    view["agents"].append(
        {
            "agent_id": child,
            "agent_path": "/root/child",
            "parent_agent_id": root,
            "role": "spawned",
            "started_seq": 2,
            "started_at_unix_ms": 1001,
            "ended_seq": 4,
            "ended_at_unix_ms": 1003,
            "status": "completed",
        }
    )
    source = root
    target = child
    if not source_is_root:
        source = child
        target = "spawn-check-grandchild"
        view["agents"].append(
            {
                "agent_id": target,
                "agent_path": "/root/child/grandchild",
                "parent_agent_id": child,
                "role": "spawned",
                "started_seq": 3,
                "started_at_unix_ms": 1002,
                "ended_seq": 4,
                "ended_at_unix_ms": 1003,
                "status": "completed",
            }
        )
    view["tools"] = [
        {
            "tool_id": "spawn-tool",
            "agent_id": source,
            "turn_id": None,
            "name": "spawn_agent",
            "namespace": "collaboration",
            "requester": "model",
            "kind": "spawn_agent",
            "started_seq": 2,
            "started_at_unix_ms": 1001,
            "ended_seq": 3,
            "ended_at_unix_ms": 1002,
            "status": tool_status,
        }
    ]
    view["interactions"] = [
        {
            "interaction_id": "spawn-edge",
            "kind": "spawn_agent",
            "source_agent_id": source,
            "target_agent_id": target,
            "tool_id": "spawn-tool",
            "started_seq": 2,
            "started_at_unix_ms": 1001,
            "ended_seq": 3,
            "ended_at_unix_ms": 1002,
            "status": "completed",
        }
    ]
    view["summary"]["agent_count"] = len(view["agents"])
    view["summary"]["tool_count"] = 1
    view["summary"]["interaction_count"] = 1
    return view


def _aggregate_record(run_id: str) -> dict:
    return {
        "phase": "pilot",
        "pair_id": "P01",
        "slot_id": "pilot-p01-rondo",
        "run_id": run_id,
        "attempt": 1,
        "task_id": "terminal-bench/filter-js-from-html",
        "side": "rondo",
        "product": "rondo-multi",
        "outcome": "completed",
        "terminal": True,
        "counts_as_effective": True,
        "trace_status": "available",
        "reason_code": None,
    }


def _followup_view() -> dict:
    view = synthetic_team_view(side="rondo", run_id="followup-check", ordinal=1)
    root = view["source"]["root_thread_id"]
    child = "followup-check-child"
    view["agents"].append(
        {
            "agent_id": child,
            "agent_path": "/root/child",
            "parent_agent_id": root,
            "role": "spawned",
            "started_seq": 2,
            "started_at_unix_ms": 1001,
            "ended_seq": 4,
            "ended_at_unix_ms": 1003,
            "status": "completed",
        }
    )
    view["tools"] = [
        {
            "tool_id": "followup-tool",
            "agent_id": root,
            "turn_id": None,
            "name": "followup_task",
            "namespace": "collaboration",
            "requester": "model",
            "kind": "assign_agent_task",
            "started_seq": 2,
            "started_at_unix_ms": 1001,
            "ended_seq": 3,
            "ended_at_unix_ms": 1002,
            "status": "completed",
        }
    ]
    view["interactions"] = [
        {
            "interaction_id": "followup-edge",
            "kind": "assign_agent_task",
            "source_agent_id": root,
            "target_agent_id": child,
            "tool_id": "followup-tool",
            "started_seq": 2,
            "started_at_unix_ms": 1001,
            "ended_seq": 3,
            "ended_at_unix_ms": 1002,
            "status": "completed",
        }
    ]
    view["summary"]["agent_count"] = 2
    view["summary"]["tool_count"] = 1
    view["summary"]["interaction_count"] = 1
    return view


def _write_native_bundle(
    trace_root: Path,
    name: str,
    *,
    product: str,
    session_source: object,
) -> Path:
    bundle = make_bundle(trace_root / name, product=product)
    events = [
        json.loads(line)
        for line in (bundle / "trace.jsonl").read_text("utf-8").splitlines()
    ]
    root_start = next(
        row
        for row in events
        if row["payload"]["type"] == "thread_started"
        and row["payload"]["thread_id"] == "thread-root"
    )
    metadata_path = bundle / root_start["payload"]["metadata_payload"]["path"]
    metadata = json.loads(metadata_path.read_text("utf-8"))
    metadata["session_source"] = session_source
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    return bundle


def _write_loopback_receipt(
    common_root: Path, contract, *, namespace: str
) -> None:
    root = common_root / "eval-data/plan-049/loopback" / namespace
    side_rows = {}
    for ordinal, side in enumerate(("codex", "rondo"), start=1):
        side_root = root / side
        view = synthetic_team_view(side=side, run_id=f"loopback-{side}", ordinal=ordinal)
        digests = write_replay_artifacts(side_root, view)
        side_rows[side] = {
            "binary_sha256": contract.lock["runtime"][f"{side}_binary_sha256"],
            "request_count": 1,
            "policy_sha256": contract.policy_sha256,
            "policy_matched": True,
            "registered_tool_projection": sorted(
                COMMON_V2_TOOL_NAMES
                | (RONDO_TEAM_STATE_TOOL_NAMES if side == "rondo" else set())
            ),
            "team_state": None if side == "codex" else True,
            **digests,
            "trace_bundle_count": 1,
        }
    summary = {
        "schema_version": 2,
        "evidence_kind": "loopback",
        "identity_class": "rehearsal",
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "policy_sha256": contract.policy_sha256,
        "namespace": namespace,
        "sides": side_rows,
    }
    (root / "loopback.json").write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n",
        "utf-8",
    )


class ProactiveEvalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract(REPO_ROOT)
        self.temporary = tempfile.TemporaryDirectory()
        self.common_root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_frozen_contract_and_dry_run_are_exact_and_rehearsal_only(self) -> None:
        schedule = slots(self.contract)
        self.assertEqual(len(schedule), 26)
        self.assertEqual(
            [(row.pair_id, row.side) for row in schedule[:6]],
            [
                ("P01", "codex"),
                ("P01", "rondo"),
                ("P02", "rondo"),
                ("P02", "codex"),
                ("P03", "codex"),
                ("P03", "rondo"),
            ],
        )
        first = dry_run_projection(
            self.contract, common_root=self.common_root, namespace="deterministic"
        )
        second = dry_run_projection(
            self.contract, common_root=self.common_root, namespace="deterministic"
        )
        self.assertEqual(first, second)
        self.assertEqual(first["identity_class"], "rehearsal")
        self.assertTrue(all(row["identity_class"] == "rehearsal" for row in first["slots"]))
        self.assertTrue(all("paid" not in row["run_id"] for row in first["slots"]))
        codex = first["side_command_contract"]["codex"]
        rondo = first["side_command_contract"]["rondo"]
        self.assertIn("max_concurrent_threads_per_session=4", codex["config_overrides"][0])
        self.assertIn("max_concurrent_threads_per_session=4", rondo["config_overrides"][0])
        self.assertNotIn("team_state_enabled", codex["config_overrides"][0])
        self.assertIn("team_state_enabled=true", rondo["config_overrides"][0])
        self.assertIsNone(codex["team_state"])

    def test_trace_selector_accepts_one_root_and_guardians_for_both_products(self) -> None:
        for product in ("codex", "rondo-multi"):
            for guardian_count in (0, 1, 3):
                with self.subTest(product=product, guardians=guardian_count):
                    trace_root = self.common_root / f"trace-{product}-{guardian_count}"
                    root = _write_native_bundle(
                        trace_root,
                        "root",
                        product=product,
                        session_source="exec",
                    )
                    for ordinal in range(guardian_count):
                        _write_native_bundle(
                            trace_root,
                            f"guardian-{ordinal}",
                            product=product,
                            session_source={"subagent": {"other": "guardian"}},
                        )

                    selected = select_proactive_root_bundle(
                        trace_root, product=product
                    )

                    self.assertEqual(selected.root_bundle, root)
                    self.assertEqual(selected.guardian_bundle_count, guardian_count)
                    self.assertEqual(
                        selected.root_view["source"]["product"], product
                    )
                    self.assertEqual(selected.root_view["summary"]["agent_count"], 2)

    def test_trace_selector_rejects_ambiguous_unknown_and_damaged_bundles(self) -> None:
        for product in ("codex", "rondo-multi"):
            with self.subTest(product=product, case="two-roots"):
                trace_root = self.common_root / f"two-roots-{product}"
                for name in ("root-one", "root-two"):
                    _write_native_bundle(
                        trace_root,
                        name,
                        product=product,
                        session_source="exec",
                    )
                with self.assertRaisesRegex(
                    ProactiveTraceError, "exactly one Exec Root"
                ):
                    select_proactive_root_bundle(trace_root, product=product)

            with self.subTest(product=product, case="unknown-extra"):
                trace_root = self.common_root / f"unknown-{product}"
                _write_native_bundle(
                    trace_root,
                    "root",
                    product=product,
                    session_source="exec",
                )
                _write_native_bundle(
                    trace_root,
                    "unknown",
                    product=product,
                    session_source={"subagent": {"other": "worker"}},
                )
                with self.assertRaisesRegex(
                    ProactiveTraceError, "unknown session source"
                ):
                    select_proactive_root_bundle(trace_root, product=product)

            with self.subTest(product=product, case="damaged"):
                trace_root = self.common_root / f"damaged-{product}"
                _write_native_bundle(
                    trace_root,
                    "root",
                    product=product,
                    session_source="exec",
                )
                guardian = _write_native_bundle(
                    trace_root,
                    "guardian",
                    product=product,
                    session_source={"subagent": {"other": "guardian"}},
                )
                (guardian / "trace.jsonl").write_text("not-json\n", "utf-8")
                with self.assertRaisesRegex(
                    ProactiveTraceError, "bundle is malformed"
                ):
                    select_proactive_root_bundle(trace_root, product=product)

    def test_actual_paid_trace_reduces_offline_when_requested(self) -> None:
        trace_root_value = os.environ.get("PLAN049_PAID_TRACE_ROOT")
        if trace_root_value is None:
            self.skipTest("PLAN049_PAID_TRACE_ROOT is not set")

        selected = select_proactive_root_bundle(
            Path(trace_root_value), product="codex"
        )

        self.assertEqual(selected.guardian_bundle_count, 1)
        self.assertEqual(selected.root_view["source"]["product"], "codex")
        self.assertEqual(selected.root_view["summary"]["inference_count"], 15)
        self.assertEqual(selected.root_view["summary"]["tool_count"], 14)
        self.assertIsNone(selected.root_view["team"])

    def test_actual_paid_sample_recovers_offline_when_requested(self) -> None:
        source_root_value = os.environ.get("PLAN049_RECOVERY_SOURCE_ROOT")
        if source_root_value is None:
            self.skipTest("PLAN049_RECOVERY_SOURCE_ROOT is not set")
        source_root = Path(source_root_value)
        copied_source = formal_paths(self.common_root, self.contract).root
        shutil.copytree(source_root, copied_source)
        before = {
            path.relative_to(copied_source).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(copied_source.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        recovery_commit = "f" * 40

        first = prepare_recovery_prefix(
            self.contract,
            common_root=self.common_root,
            provider=provider,
            recovery_harness_commit=recovery_commit,
            recovery_action=RECOVERY_ACTION,
        )
        second = prepare_recovery_prefix(
            self.contract,
            common_root=self.common_root,
            provider=provider,
            recovery_harness_commit=recovery_commit,
            recovery_action=RECOVERY_ACTION,
        )
        context = require_safe_recovery_prefix(
            self.contract,
            common_root=self.common_root,
            provider=provider,
            recovery_harness_commit=recovery_commit,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["source_run_id"], "plan049-paid-pilot-p01-codex-a01")
        self.assertEqual(first["recovered_outcome"], "task_failed")
        self.assertEqual(first["request_count"], 15)
        self.assertEqual(first["prior_spend_usd"], "0.262759")
        self.assertEqual(first["remaining_authorized_usd"], "99.737241")
        self.assertEqual(first["next_slot_id"], "pilot-p01-rondo")
        self.assertEqual(first["provider_requests"], 0)
        self.assertEqual(first["docker_runs"], 0)
        self.assertEqual(str(context.remaining_usd), "99.737241")
        self.assertFalse(
            (
                context.paths.formal.runs
                / "plan049-paid-pilot-p01-codex-a02"
            ).exists()
        )
        recovered_run = (
            context.paths.formal.runs / "plan049-paid-pilot-p01-codex-a01"
        )
        self.assertFalse((recovered_run / "staging").exists())
        self.assertFalse((recovered_run / "settled.json").exists())

        store = FormalStore(context.paths.formal, context.identity)

        class OfflineExecutor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, attempt
                view = synthetic_team_view(
                    side=slot.side, run_id=run_id, ordinal=slot.ordinal
                )
                digests = write_replay_artifacts(run_root, view)
                return FormalExecutionResult(
                    outcome="task_failed",
                    trace_status="available",
                    request_preflight_sha256="e" * 64,
                    reason_code="task_native_verifier_failed",
                    **digests,
                )

        with open_paid_ledger(context.paths.formal.ledger, self.contract) as ledger:
            progressed = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=OfflineExecutor(),
                phase="pilot",
            )
        self.assertEqual(progressed["run_count"], 6)
        self.assertEqual(store.records()[0]["run_id"], first["source_run_id"])
        require_safe_recovery_prefix(
            self.contract,
            common_root=self.common_root,
            provider=provider,
            recovery_harness_commit=recovery_commit,
        )
        after = {
            path.relative_to(copied_source).as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(copied_source.rglob("*"))
            if path.is_file() and not path.is_symlink()
        }
        self.assertEqual(before, after)

        binding = json.loads(context.paths.binding.read_text("utf-8"))
        binding["source_run"]["request_count"] = 14
        context.paths.binding.write_text(
            json.dumps(binding, sort_keys=True, separators=(",", ":")) + "\n",
            "utf-8",
        )
        context.paths.binding.chmod(0o600)
        acquire_docker = mock.Mock()
        load_secret = mock.Mock()
        dependencies = PaidRuntimeDependencies(acquire_docker_gate=acquire_docker)
        repo_paths = RepoPaths(self.common_root, REPO_ROOT)
        with mock.patch(
            "rondo_eval.proactive_eval.paid.RepoPaths.discover",
            return_value=repo_paths,
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.harness_identity",
            return_value={
                "harness_commit": recovery_commit,
                "harness_dirty": False,
            },
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.enter_paid_phase",
            return_value=self.contract,
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.require_phase_a_evidence",
            return_value={},
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.load_runtime_config",
            return_value=config,
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.plan049_provider_projection",
            return_value=provider,
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.load_provider_secret",
            load_secret,
        ):
            with self.assertRaisesRegex(PaidGuardError, "recovery prefix is unsafe"):
                run_authorized_paid_phase(
                    repo_root=REPO_ROOT,
                    authorization=PHASE_B_AUTHORIZATION,
                    activation_action=ACTIVATION_ACTION,
                    confirmed_balance_usd="99.737241",
                    local_activation_confirmation=LOCAL_ACTIVATION_CONFIRMATION,
                    independent_review_commit=recovery_commit,
                    rehearsal_namespace="unused",
                    loopback_namespace="unused",
                    phase="pilot",
                    dependencies=dependencies,
                    recovery_id=RECOVERY_ID,
                )
        acquire_docker.assert_not_called()
        load_secret.assert_not_called()

    def test_contract_digest_drift_fails_closed(self) -> None:
        copied = self.common_root / "copy"
        for relpath in (
            "eval/locks/multi-proactive-delegation-v1.json",
            "eval/locks/multi-m5-runtime-v4.json",
            "eval/tasksets/multi-proactive-delegation-v1.json",
            "eval/tasksets/p2-b7-canary-catalog-v4.json",
            "eval/templates/multi-proactive-delegation/proactive-policy-v1.md",
        ):
            target = copied / relpath
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / relpath, target)
        taskset = copied / "eval/tasksets/multi-proactive-delegation-v1.json"
        value = json.loads(taskset.read_text("utf-8"))
        value["formal_pairs"][0]["side_order"].reverse()
        taskset.write_text(json.dumps(value), "utf-8")
        with self.assertRaisesRegex(ContractError, "digest differs"):
            load_contract(copied)

    def test_team_lens_replay_is_deterministic_and_codex_team_is_null(self) -> None:
        codex = synthetic_team_view(side="codex", run_id="r1", ordinal=1)
        rondo = synthetic_team_view(side="rondo", run_id="r2", ordinal=2)
        self.assertIsNone(codex["team"])
        self.assertEqual(
            codex["availability"]["team_events_versions"]["status"],
            "not_applicable",
        )
        self.assertIsInstance(rondo["team"], dict)
        self.assertEqual(dump_team_view(codex), dump_team_view(codex))
        self.assertEqual(render_report(codex), render_report(codex))
        first = write_replay_artifacts(self.common_root / "run", codex)
        second = write_replay_artifacts(self.common_root / "run", codex)
        self.assertEqual(first, second)

    def test_activation_requires_a_successful_root_owned_spawn_tool(self) -> None:
        cases = (
            (False, "completed", False),
            (True, "failed", False),
            (True, "completed", True),
        )
        for source_is_root, tool_status, expected in cases:
            with self.subTest(source_is_root=source_is_root, tool_status=tool_status):
                view = _spawn_view(
                    source_is_root=source_is_root, tool_status=tool_status
                )
                record = _aggregate_record("spawn-check")
                result = aggregate(
                    [record],
                    {"spawn-check": view},
                    lock_id=self.contract.lock_id,
                    lock_sha256=self.contract.lock_sha256,
                    policy_sha256=self.contract.policy_sha256,
                )
                self.assertIs(result["activation_observed"], expected)
                self.assertEqual(
                    result["runs"][0]["root_spawn_accept_count"], int(expected)
                )

    def test_followup_metric_uses_the_normalized_team_lens_kind(self) -> None:
        result = aggregate(
            [_aggregate_record("followup-check")],
            {"followup-check": _followup_view()},
            lock_id=self.contract.lock_id,
            lock_sha256=self.contract.lock_sha256,
            policy_sha256=self.contract.policy_sha256,
        )
        self.assertEqual(result["runs"][0]["followup_count"], 1)

    def test_success_valid_failure_duplicate_execution_and_body_free_archive(self) -> None:
        first = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="success-resume",
            executor=default_fake_executor,
        )
        store = RehearsalStore(self.common_root, "success-resume")
        archive_before = store.archive_path.read_bytes()
        aggregate_before = store.aggregate_path.read_bytes()
        second = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="success-resume",
            executor=lambda _slot, _attempt: self.fail("terminal slot reran"),
        )
        self.assertEqual(first, second)
        self.assertEqual(archive_before, store.archive_path.read_bytes())
        self.assertEqual(aggregate_before, store.aggregate_path.read_bytes())
        self.assertEqual(first["run_count"], 26)
        self.assertEqual(first["valid_failure_count"], 2)
        self.assertTrue(all(row["peak_agent_concurrency"] == 1 for row in first["runs"]))
        self.assertTrue(all(row["first_spawn_offset_ms"] is None for row in first["runs"]))
        self.assertEqual(len(store.records()), 26)
        self.assertTrue(all(row["cost_usd"] == "0.00" for row in store.records()))
        drifted = dict(store.records()[0])
        drifted["outcome"] = "task_failed"
        with self.assertRaisesRegex(StoreError, "identity drifted"):
            store.append(drifted)
        with self.assertRaisesRegex(ValueError, "contract drifted"):
            run_rehearsal(
                replace(self.contract, lock_sha256="0" * 64),
                common_root=self.common_root,
                namespace="success-resume",
                executor=default_fake_executor,
            )

    def test_provider_failure_partial_pair_and_interruption_resume(self) -> None:
        failed_once = False

        def executor(slot, attempt):
            nonlocal failed_once
            if slot.slot_id == "pilot-p01-codex" and not failed_once:
                failed_once = True
                raise ConnectionError("simulated")
            return ExecutionResult("completed")

        first = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="infra-resume",
            executor=executor,
        )
        self.assertEqual(first["run_count"], 25)
        records = RehearsalStore(self.common_root, "infra-resume").records()
        self.assertEqual(sum(row["outcome"] == "infra_failed" for row in records), 1)
        second = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="infra-resume",
            executor=executor,
        )
        self.assertEqual(second["run_count"], 26)
        target = [row for row in RehearsalStore(self.common_root, "infra-resume").records() if row["slot_id"] == "pilot-p01-codex"]
        self.assertEqual([row["attempt"] for row in target], [1, 2])

    def test_partial_trace_is_valid_but_missing_trace_is_infra(self) -> None:
        def partial(slot, attempt):
            del attempt
            if slot.slot_id == "pilot-p01-codex":
                return ExecutionResult("task_failed", trace_status="partial")
            if slot.slot_id == "pilot-p01-rondo":
                return ExecutionResult(
                    "provider_failed", trace_status="missing", reason_code="simulated_network_failure"
                )
            return ExecutionResult("completed")

        result = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="trace-matrix",
            executor=partial,
        )
        self.assertEqual(result["run_count"], 25)
        records = RehearsalStore(self.common_root, "trace-matrix").records()
        self.assertTrue(any(row["terminal"] and row["trace_status"] == "partial" for row in records))
        self.assertTrue(any(not row["terminal"] and row["trace_status"] == "missing" for row in records))

    def test_report_failure_recovers_and_archive_failure_resumes_same_claim(self) -> None:
        calls = 0
        report_executions = 0

        def report_executor(_slot, _attempt):
            nonlocal report_executions
            report_executions += 1
            return ExecutionResult("completed")

        def flaky_writer(path, view):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated report failure")
            return write_replay_artifacts(path, view)

        first = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="report-recovery",
            executor=report_executor,
            artifact_writer=flaky_writer,
        )
        self.assertEqual(first["run_count"], 25)
        second = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="report-recovery",
            executor=report_executor,
        )
        self.assertEqual(second["run_count"], 26)
        self.assertEqual(report_executions, 26)

        original = RehearsalStore.append
        failed = False
        archive_executions = 0

        def archive_executor(_slot, _attempt):
            nonlocal archive_executions
            archive_executions += 1
            return ExecutionResult("completed")

        def fail_once(store, record):
            nonlocal failed
            if not failed:
                failed = True
                raise OSError("simulated archive failure")
            return original(store, record)

        with mock.patch.object(RehearsalStore, "append", fail_once):
            with self.assertRaisesRegex(OSError, "archive failure"):
                run_rehearsal(
                    self.contract,
                    common_root=self.common_root,
                    namespace="archive-recovery",
                    executor=archive_executor,
                )
        recovered = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="archive-recovery",
            executor=archive_executor,
        )
        self.assertEqual(recovered["run_count"], 26)
        self.assertEqual(archive_executions, 26)
        first_slot = RehearsalStore(self.common_root, "archive-recovery").records()[0]
        self.assertEqual(first_slot["attempt"], 1)

        original_settle = RehearsalStore.settle
        settlement_failed = False

        def fail_settlement_once(store, slot_id, *, outcome):
            nonlocal settlement_failed
            if not settlement_failed:
                settlement_failed = True
                raise OSError("simulated settlement failure")
            return original_settle(store, slot_id, outcome=outcome)

        with mock.patch.object(RehearsalStore, "settle", fail_settlement_once):
            with self.assertRaisesRegex(OSError, "settlement failure"):
                run_rehearsal(
                    self.contract,
                    common_root=self.common_root,
                    namespace="settlement-recovery",
                    executor=lambda _slot, _attempt: ExecutionResult("completed"),
                )
        settled = run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="settlement-recovery",
            executor=lambda _slot, _attempt: ExecutionResult("completed"),
        )
        self.assertEqual(settled["run_count"], 26)
        repaired = json.loads(
            RehearsalStore(self.common_root, "settlement-recovery").ledger_path.read_text("utf-8")
        )
        self.assertEqual(repaired["claims"]["pilot-p01-codex"]["status"], "settled")

    def test_body_bearing_fields_are_rejected(self) -> None:
        for key in ("prompt", "response", "reasoning", "agent_message", "stdout", "raw_trace"):
            with self.subTest(key=key), self.assertRaises(StoreError):
                assert_body_free({key: "not persisted"})
        fixture = json.loads(
            (REPO_ROOT / "eval/fixtures/multi-proactive-delegation-v1/body-free-replay-v1.json").read_text("utf-8")
        )
        assert_body_free(fixture)

    def test_ready_requires_complete_rehearsal_and_loopback_receipts(self) -> None:
        with self.assertRaisesRegex(ReadinessError, "rehearsal evidence is absent"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )
        run_rehearsal(
            self.contract,
            common_root=self.common_root,
            namespace="acceptance",
            executor=default_fake_executor,
        )
        with self.assertRaisesRegex(ReadinessError, "loopback summary"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )
        _write_loopback_receipt(self.common_root, self.contract, namespace="loopback")
        receipt = require_phase_a_evidence(
            self.contract,
            common_root=self.common_root,
            rehearsal_namespace="acceptance",
            loopback_namespace="loopback",
        )
        self.assertEqual(receipt["run_count"], 26)
        loopback_path = (
            self.common_root
            / "eval-data/plan-049/loopback/loopback/loopback.json"
        )
        loopback_bytes = loopback_path.read_bytes()
        for side, missing in (
            ("codex", "followup_task"),
            ("rondo", "interrupt_agent"),
        ):
            with self.subTest(side=side, missing=missing):
                loopback = json.loads(loopback_bytes)
                loopback["sides"][side]["registered_tool_projection"].remove(missing)
                loopback_path.write_text(
                    json.dumps(loopback, sort_keys=True, separators=(",", ":")) + "\n",
                    "utf-8",
                )
                with self.assertRaisesRegex(ReadinessError, "tool projection"):
                    require_phase_a_evidence(
                        self.contract,
                        common_root=self.common_root,
                        rehearsal_namespace="acceptance",
                        loopback_namespace="loopback",
                    )
        loopback = json.loads(loopback_bytes)
        loopback["sides"]["rondo"]["registered_tool_projection"].append(
            "one_sided_unknown_tool"
        )
        loopback["sides"]["rondo"]["registered_tool_projection"].sort()
        loopback_path.write_text(
            json.dumps(loopback, sort_keys=True, separators=(",", ":")) + "\n",
            "utf-8",
        )
        with self.assertRaisesRegex(ReadinessError, "tool projection"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )
        loopback_path.write_bytes(loopback_bytes)
        store = RehearsalStore(self.common_root, "acceptance")
        ledger_bytes = store.ledger_path.read_bytes()
        store.ledger_path.unlink()
        with self.assertRaisesRegex(ReadinessError, "rehearsal ledger"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )
        store.ledger_path.write_bytes(ledger_bytes)
        first = store.records()[0]
        marker = store.runs_root / first["run_id"] / "run.json"
        marker_bytes = marker.read_bytes()
        marker.unlink()
        with self.assertRaisesRegex(ReadinessError, "run publication"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )
        marker.write_bytes(marker_bytes)
        store.aggregate_path.write_text("{}\n", "utf-8")
        with self.assertRaisesRegex(ReadinessError, "aggregate"):
            require_phase_a_evidence(
                self.contract,
                common_root=self.common_root,
                rehearsal_namespace="acceptance",
                loopback_namespace="loopback",
            )

    def test_paid_guard_stops_before_every_side_effect(self) -> None:
        cases = (
            {},
            {"authorization": PHASE_B_AUTHORIZATION},
            {
                "authorization": PHASE_B_AUTHORIZATION,
                "activation_action": ACTIVATION_ACTION,
                "confirmed_balance_usd": "99.99",
            },
            {
                "authorization": PHASE_B_AUTHORIZATION,
                "activation_action": ACTIVATION_ACTION,
                "confirmed_balance_usd": "100.00",
                "harness_clean": False,
            },
            {
                "authorization": PHASE_B_AUTHORIZATION,
                "activation_action": ACTIVATION_ACTION,
                "confirmed_balance_usd": "100.00",
                "activation_conditions_ready": False,
            },
            {
                "authorization": PHASE_B_AUTHORIZATION,
                "activation_action": ACTIVATION_ACTION,
                "confirmed_balance_usd": "100.00",
                "docker_resource_gate_ready": False,
            },
        )
        for overrides in cases:
            arguments = {
                "repo_root": REPO_ROOT,
                "authorization": None,
                "activation_action": None,
                "confirmed_balance_usd": None,
                "harness_clean": True,
                "resume_prefix_safe": True,
                "activation_conditions_ready": True,
                "docker_resource_gate_ready": True,
                "phase_a_evidence_ready": True,
                "independent_review_passed": True,
                **overrides,
            }
            with self.assertRaises(PaidGuardError):
                enter_paid_phase(**arguments)

        accepted = enter_paid_phase(
            repo_root=REPO_ROOT,
            authorization=PHASE_B_AUTHORIZATION,
            activation_action=ACTIVATION_ACTION,
            confirmed_balance_usd="100.00",
            harness_clean=True,
            resume_prefix_safe=True,
            activation_conditions_ready=True,
            docker_resource_gate_ready=True,
            phase_a_evidence_ready=True,
            independent_review_passed=True,
        )
        self.assertEqual(accepted.lock_id, self.contract.lock_id)

    def test_paid_guard_requires_phase_a_evidence_and_independent_review(self) -> None:
        base = {
            "repo_root": REPO_ROOT,
            "authorization": PHASE_B_AUTHORIZATION,
            "activation_action": ACTIVATION_ACTION,
            "confirmed_balance_usd": "100.00",
            "harness_clean": True,
            "resume_prefix_safe": True,
            "activation_conditions_ready": True,
            "docker_resource_gate_ready": True,
            "phase_a_evidence_ready": True,
            "independent_review_passed": True,
        }
        for key in ("phase_a_evidence_ready", "independent_review_passed"):
            with self.subTest(key=key), self.assertRaises(PaidGuardError):
                enter_paid_phase(**{**base, key: False})

    def test_formal_budget_preflight_and_publication_resume_are_idempotent(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="a" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/test-fixture"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        executions = 0

        class Executor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, attempt
                nonlocal executions
                executions += 1
                view = synthetic_team_view(
                    side=slot.side, run_id=run_id, ordinal=slot.ordinal
                )
                digests = write_replay_artifacts(run_root, view)
                return FormalExecutionResult(
                    outcome="completed",
                    trace_status="available",
                    request_preflight_sha256="b" * 64,
                    **digests,
                )

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            original = store.publish
            failed = False

            def fail_once(record):
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError("simulated formal publication failure")
                return original(record)

            with mock.patch.object(store, "publish", fail_once):
                with self.assertRaisesRegex(OSError, "publication failure"):
                    run_formal_campaign(
                        self.contract,
                        store=store,
                        ledger=ledger,
                        executor=Executor(),
                        phase="pilot",
                    )
            result = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=Executor(),
                phase="pilot",
            )
            again = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=Executor(),
                phase="pilot",
            )
        self.assertEqual(executions, 6)
        self.assertEqual(result, again)
        self.assertEqual(result["run_count"], 6)
        self.assertEqual(len(store.records()), 6)
        require_safe_formal_prefix(paths, identity, self.contract)

        preflight = Plan049RequestPreflight(
            contract=self.contract,
            side=Side.CODEX,
            task_id="terminal-bench/filter-js-from-html",
        )
        request = {
            "model": "gpt-5.6-terra",
            "reasoning": {"effort": "medium"},
            "instructions": self.contract.policy,
            "tools": [
                {"type": "function", "name": name, "parameters": {}}
                for name in sorted(COMMON_V2_TOOL_NAMES)
            ],
        }
        preflight.register(
            task_id="terminal-bench/filter-js-from-html",
            role="main",
            side=Side.CODEX,
            request=request,
        )
        self.assertEqual(len(preflight.digest()), 64)
        for missing in ("followup_task", "interrupt_agent"):
            with self.subTest(missing=missing):
                incomplete = Plan049RequestPreflight(
                    contract=self.contract,
                    side=Side.CODEX,
                    task_id="terminal-bench/filter-js-from-html",
                )
                with self.assertRaisesRegex(FormalDriftError, "common V2 tools"):
                    incomplete.register(
                        task_id="terminal-bench/filter-js-from-html",
                        role="main",
                        side=Side.CODEX,
                        request={
                            **request,
                            "tools": [
                                tool
                                for tool in request["tools"]
                                if tool["name"] != missing
                            ],
                        },
                    )
        rondo_preflight = Plan049RequestPreflight(
            contract=self.contract,
            side=Side.RONDO,
            task_id="terminal-bench/filter-js-from-html",
        )
        rondo_preflight.register(
            task_id="terminal-bench/filter-js-from-html",
            role="main",
            side=Side.RONDO,
            request={
                **request,
                "tools": [
                    {"type": "function", "name": name, "parameters": {}}
                    for name in sorted(
                        COMMON_V2_TOOL_NAMES | RONDO_TEAM_STATE_TOOL_NAMES
                    )
                ],
            },
        )
        self.assertEqual(len(rondo_preflight.digest()), 64)
        with self.assertRaisesRegex(Exception, "frozen policy"):
            failed_preflight = Plan049RequestPreflight(
                contract=self.contract,
                side=Side.CODEX,
                task_id="terminal-bench/filter-js-from-html",
            )
            failed_preflight.register(
                task_id="terminal-bench/filter-js-from-html",
                role="main",
                side=Side.CODEX,
                request={**request, "instructions": "drifted"},
            )

        latched = Plan049RequestPreflight(
            contract=self.contract,
            side=Side.CODEX,
            task_id="terminal-bench/filter-js-from-html",
        )
        latched.register(
            task_id="terminal-bench/filter-js-from-html",
            role="main",
            side=Side.CODEX,
            request=request,
        )
        with self.assertRaises(FormalDriftError):
            latched.register(
                task_id="terminal-bench/filter-js-from-html",
                role="main",
                side=Side.CODEX,
                request={**request, "instructions": "drifted"},
            )
        with self.assertRaisesRegex(FormalDriftError, "preflight failed"):
            latched.digest()

    def test_formal_infra_exhaustion_stops_at_the_first_incomplete_slot(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="d" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/infra-exhausted"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        calls = 0

        class InfraExecutor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, slot, attempt, run_id, run_root
                nonlocal calls
                calls += 1
                raise FormalInfraError("simulated provider failure")

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            result = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=InfraExecutor(),
                phase="pilot",
            )
            resumed = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=InfraExecutor(),
                phase="pilot",
            )
        rows = store.records()
        self.assertEqual(calls, 5)
        self.assertEqual(len(rows), 5)
        self.assertEqual({row["slot_id"] for row in rows}, {"pilot-p01-codex"})
        self.assertEqual(result, resumed)

    def test_formal_settled_checkpoint_recovers_reports_without_provider_repeat(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="1" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/settled-recovery"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        provider_calls = 0
        recover_calls = 0
        failed = False

        class Executor:
            @staticmethod
            def result(slot, run_id, run_root):
                view = synthetic_team_view(
                    side=slot.side, run_id=run_id, ordinal=slot.ordinal
                )
                return FormalExecutionResult(
                    outcome="completed",
                    trace_status="available",
                    request_preflight_sha256="7" * 64,
                    **write_replay_artifacts(run_root, view),
                )

            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, attempt
                nonlocal provider_calls, failed
                provider_calls += 1
                if not failed:
                    failed = True
                    run_root.mkdir(parents=True, exist_ok=True)
                    (run_root / "settled.json").write_text("{}\n", "utf-8")
                    raise OSError("simulated report failure after settlement")
                return Executor.result(slot, run_id, run_root)

            def recover(inner, slot, *, attempt, run_id, run_root):
                del inner, attempt
                nonlocal recover_calls
                recover_calls += 1
                return Executor.result(slot, run_id, run_root)

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            with self.assertRaisesRegex(FormalError, "local artifact recovery"):
                run_formal_campaign(
                    self.contract,
                    store=store,
                    ledger=ledger,
                    executor=Executor(),
                    phase="pilot",
                )
            result = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=Executor(),
                phase="pilot",
            )
        self.assertEqual(result["run_count"], 6)
        self.assertEqual(provider_calls, 6)
        self.assertEqual(recover_calls, 1)

    def test_formal_identity_error_is_a_principled_stop(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="e" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/identity-stop"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()

        class DriftExecutor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, slot, attempt, run_id, run_root
                raise FormalError("paid request lacks frozen policy")

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            with self.assertRaisesRegex(FormalError, "frozen policy"):
                run_formal_campaign(
                    self.contract,
                    store=store,
                    ledger=ledger,
                    executor=DriftExecutor(),
                    phase="pilot",
                )
        rows = store.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "principled_stopped")
        self.assertFalse(rows[0]["counts_as_effective"])
        resumed_calls = 0

        class WouldSucceed:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, slot, attempt, run_id, run_root
                nonlocal resumed_calls
                resumed_calls += 1
                raise AssertionError("latched principled stop executed again")

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            with self.assertRaisesRegex(FormalDriftError, "latched principled stop"):
                run_formal_campaign(
                    self.contract,
                    store=store,
                    ledger=ledger,
                    executor=WouldSucceed(),
                    phase="pilot",
                )
        self.assertEqual(resumed_calls, 0)
        self.assertEqual(len(json.loads(paths.ledger.read_text("utf-8"))["runs"]), 1)
        with self.assertRaisesRegex(FormalError, "latched stop"):
            require_safe_formal_prefix(paths, identity, self.contract)

    def test_safe_formal_prefix_rejects_a_corrupt_settled_checkpoint(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="2" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/corrupt-settled"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        first = slots(self.contract)[0]
        run_id = first.run_id().replace("rehearsal", "paid")
        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            ledger.claim_run(run_id, cap_usd="15.10")
        run_root = store.run_root(run_id)
        run_root.mkdir(parents=True)
        (run_root / "settled.json").write_text("{}\n", "utf-8")
        with self.assertRaisesRegex(FormalError, "settled provider checkpoint"):
            require_safe_formal_prefix(paths, identity, self.contract)

    def test_principled_stop_after_a_settled_request_never_buys_a_replacement(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="6" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/requested-drift"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        calls = 0

        class RequestedDrift:
            def __init__(inner, ledger):
                inner.ledger = ledger

            def execute(inner, slot, *, attempt, run_id, run_root):
                del slot, attempt, run_root
                nonlocal calls
                calls += 1
                request_id = f"{run_id}-request-001"
                inner.ledger.reserve(run_id, request_id, "2.22")
                inner.ledger.begin_attempt(run_id, request_id, max_attempts=5)
                inner.ledger.settle(
                    run_id,
                    request_id,
                    Usage(100, 0, 0, 10),
                    pricing=provider.main_pricing,
                )
                raise FormalDriftError("simulated post-request policy drift")

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            with self.assertRaisesRegex(FormalDriftError, "policy drift"):
                run_formal_campaign(
                    self.contract,
                    store=store,
                    ledger=ledger,
                    executor=RequestedDrift(ledger),
                    phase="pilot",
                )
        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            with self.assertRaisesRegex(FormalDriftError, "latched principled stop"):
                run_formal_campaign(
                    self.contract,
                    store=store,
                    ledger=ledger,
                    executor=RequestedDrift(ledger),
                    phase="pilot",
                )
        rows = store.records()
        self.assertEqual(calls, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "principled_stopped")
        self.assertEqual(rows[0]["request_count"], 1)
        self.assertGreater(float(rows[0]["cost_usd"]), 0)

    def test_unarchived_principled_marker_stops_before_paid_resources(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="8" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/stop-append-window"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()

        class DriftExecutor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, slot, attempt, run_id, run_root
                raise FormalDriftError("simulated fairness drift")

        with open_paid_ledger(paths.ledger, self.contract) as ledger, mock.patch.object(
            store, "append", side_effect=OSError("simulated stop append failure")
        ):
            with self.assertRaisesRegex(OSError, "stop append failure"):
                run_formal_campaign(
                    self.contract,
                    store=store,
                    ledger=ledger,
                    executor=DriftExecutor(),
                    phase="pilot",
                )
        self.assertEqual(store.records(), ())
        with self.assertRaisesRegex(FormalError, "latched stop"):
            require_safe_formal_prefix(paths, identity, self.contract)

        resumed_calls = 0

        class WouldSucceed:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner, slot, attempt, run_id, run_root
                nonlocal resumed_calls
                resumed_calls += 1
                raise AssertionError("unarchived stop marker was retried")

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            with self.assertRaisesRegex(FormalDriftError, "latched principled stop"):
                run_formal_campaign(
                    self.contract,
                    store=store,
                    ledger=ledger,
                    executor=WouldSucceed(),
                    phase="pilot",
                )
        self.assertEqual(resumed_calls, 0)
        self.assertEqual(len(store.records()), 1)

    def test_formal_budget_stop_is_a_persistent_campaign_barrier(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="3" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/budget-stop"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        calls = 0

        class BudgetExecutor:
            def __init__(inner, ledger):
                inner.ledger = ledger

            def execute(inner, slot, *, attempt, run_id, run_root):
                del slot, attempt, run_root
                nonlocal calls
                calls += 1
                inner.ledger.stop_run(
                    run_id, stop_reason="budget_capacity_exhausted"
                )
                raise BudgetStopped("budget_capacity_exhausted")

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            first = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=BudgetExecutor(ledger),
                phase="pilot",
            )
        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            second = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=BudgetExecutor(ledger),
                phase="pilot",
            )
        self.assertEqual(first, second)
        self.assertEqual(calls, 1)
        rows = store.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "budget_stopped")
        self.assertEqual(rows[0]["reason_code"], "budget_capacity_exhausted")
        self.assertEqual(rows[0]["attempt"], 1)
        with self.assertRaisesRegex(FormalError, "latched stop"):
            require_safe_formal_prefix(paths, identity, self.contract)

    def test_malformed_ledger_stops_before_docker_and_secret_access(self) -> None:
        repo_paths = RepoPaths(
            common_root=self.common_root,
            worktree_root=REPO_ROOT,
        )
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        harness_commit = "4" * 40
        identity = formal_identity(
            self.contract, provider=provider, harness_commit=harness_commit
        )
        paths = formal_paths(self.common_root, self.contract)
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        with open_paid_ledger(paths.ledger, self.contract):
            pass
        malformed = json.loads(paths.ledger.read_text("utf-8"))
        malformed["unexpected"] = True
        paths.ledger.write_text(
            json.dumps(malformed, sort_keys=True, separators=(",", ":")) + "\n",
            "utf-8",
        )
        paths.ledger.chmod(0o600)
        with self.assertRaisesRegex(FormalError, "ledger is invalid"):
            require_safe_formal_prefix(paths, identity, self.contract)

        acquire_docker = mock.Mock()
        load_secret = mock.Mock()
        dependencies = PaidRuntimeDependencies(acquire_docker_gate=acquire_docker)
        with mock.patch(
            "rondo_eval.proactive_eval.paid.RepoPaths.discover",
            return_value=repo_paths,
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.harness_identity",
            return_value={
                "harness_commit": harness_commit,
                "harness_dirty": False,
            },
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.enter_paid_phase",
            return_value=self.contract,
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.require_phase_a_evidence",
            return_value={},
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.load_runtime_config",
            return_value=config,
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.plan049_provider_projection",
            return_value=provider,
        ), mock.patch(
            "rondo_eval.proactive_eval.paid.load_provider_secret",
            load_secret,
        ):
            with self.assertRaisesRegex(PaidGuardError, "resume prefix is unsafe"):
                run_authorized_paid_phase(
                    repo_root=REPO_ROOT,
                    authorization=PHASE_B_AUTHORIZATION,
                    activation_action=ACTIVATION_ACTION,
                    confirmed_balance_usd="100.00",
                    local_activation_confirmation=LOCAL_ACTIVATION_CONFIRMATION,
                    independent_review_commit=harness_commit,
                    rehearsal_namespace="unused",
                    loopback_namespace="unused",
                    phase="pilot",
                    dependencies=dependencies,
                )
        acquire_docker.assert_not_called()
        load_secret.assert_not_called()

    def test_phase_b_cli_reaches_the_concrete_paid_runner(self) -> None:
        pilot_rows = [
            {"phase": "pilot", "counts_as_effective": True}
            for _index in range(6)
        ]
        with mock.patch(
            "rondo_eval.proactive_eval.__main__.run_authorized_paid_phase",
            return_value={
                "runs": pilot_rows,
                "activation_observed": True,
                "missing_slot_ids": [],
            },
        ) as runner, mock.patch("builtins.print"):
            status = proactive_main(
                [
                    "phase-b-paid",
                    "--authorize-phase-b",
                    PHASE_B_AUTHORIZATION,
                    "--activation-action",
                    ACTIVATION_ACTION,
                    "--confirmed-balance-usd",
                    "100.00",
                    "--confirm-local-activation",
                    LOCAL_ACTIVATION_CONFIRMATION,
                    "--independent-review-commit",
                    "f" * 40,
                    "--phase",
                    "pilot",
                    "--namespace",
                    "acceptance",
                    "--loopback-namespace",
                    "loopback",
                ]
            )
        self.assertEqual(status, 0)
        runner.assert_called_once()

    def test_production_paid_dependencies_bind_watchdog_and_docker_counter(self) -> None:
        paths = RepoPaths.discover(REPO_ROOT)
        proof = mock.Mock()
        proof.lease.token = "a" * 48
        proof.lease.held = True
        proof.guard.is_held.return_value = True
        counter = mock.Mock()
        with mock.patch(
            "rondo_eval.runtime_bridge.lease_from_watchdog", return_value=proof
        ) as lease, mock.patch(
            "rondo_eval.runtime_bridge.PowerShellDockerDesktopHostProbe"
        ) as host_probe, mock.patch(
            "rondo_eval.runtime_bridge.DockerCliCounter", return_value=counter
        ) as counter_type:
            resources = production_paid_dependencies(paths).acquire_docker_gate()
        lease.assert_called_once_with()
        host_probe.assert_called_once_with()
        counter_type.assert_called_once_with(
            host_data_root=paths.common_root / "eval-data" / "docker-host",
            desktop_host_probe=host_probe.return_value,
        )
        self.assertIs(resources.counter, counter)
        proof.guard.is_held.assert_called_once_with(resources.lease)

    def test_formal_terminal_bench_requests_share_v2_policy_models_and_trace(self) -> None:
        paths = RepoPaths.discover(REPO_ROOT)
        ledger_path = self.common_root / "eval-data/plan-049/paid/request-ledger.json"
        injected_paid_paths = recovery_paths(
            self.common_root, self.contract
        ).formal
        with open_paid_ledger(ledger_path, self.contract) as ledger:
            executor = Plan049TerminalBenchExecutor(
                contract=self.contract,
                common_root=paths.common_root,
                repo_root=paths.worktree_root,
                ledger=ledger,
                api_key="test-only-not-forwarded",
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=mock.Mock(),
                config=load_runtime_config(paths),
                paid_paths=injected_paid_paths,
            )
            selected = slots(self.contract)[:2]
            requests = [
                executor.build_request(
                    slot,
                    run_id=slot.run_id().replace("rehearsal", "paid"),
                )
                for slot in selected
            ]
        self.assertEqual([request.side.value for request in requests], ["codex", "rondo"])
        for request in requests:
            self.assertTrue(request.common_multi_agent_v2)
            self.assertEqual(request.pinned_model_id, "gpt-5.6-terra")
            self.assertEqual(request.pinned_subagent_model, "gpt-5.6-terra")
            self.assertEqual(request.pinned_subagent_effort, "medium")
            self.assertEqual(request.multi_agent_max_concurrency, 4)
            self.assertTrue(
                Path(request.staging_root).is_relative_to(
                    injected_paid_paths.runs
                )
            )
            self.assertEqual(
                request.developer_instructions_sha256,
                self.contract.policy_sha256,
            )
            self.assertEqual(request.rollout_trace_root, "/logs/agent/rollout-trace")
            self.assertEqual(request.budget_usd, 15.10)
        with self.assertRaisesRegex(FormalError, "lacks receipt identity"):
            executor.execute(
                selected[0],
                attempt=1,
                run_id="plan049-paid-pilot-p01-codex-a01",
                run_root=self.common_root / "eval-data/plan-049/no-receipt",
            )
        self.assertFalse(
            (self.common_root / "eval-data/plan-049/no-receipt").exists()
        )

    def test_run_local_request_limits_are_product_failures_without_retry(self) -> None:
        paths = RepoPaths.discover(REPO_ROOT)
        ledger_path = self.common_root / "eval-data/plan-049/paid/limit-ledger.json"
        with open_paid_ledger(ledger_path, self.contract) as ledger:
            executor = Plan049TerminalBenchExecutor(
                contract=self.contract,
                common_root=paths.common_root,
                repo_root=paths.worktree_root,
                ledger=ledger,
                api_key="test-only-not-forwarded",
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=mock.Mock(),
                config=load_runtime_config(paths),
                formal_identity_sha256="5" * 64,
            )
            for slot, stop_reason in zip(
                slots(self.contract)[:2],
                (
                    "logical_request_limit_exceeded",
                    "guardian_logical_request_limit_exceeded",
                ),
                strict=True,
            ):
                with self.subTest(stop_reason=stop_reason):
                    run_id = slot.run_id().replace("rehearsal", "paid")
                    run_root = self.common_root / "limit-runs" / run_id
                    ledger.claim_run(run_id, cap_usd="15.10")

                    async def fake_core(_config, request, **kwargs):
                        kwargs["request_preflight"].register(
                            task_id=slot.task_id,
                            role="main",
                            side=request.side,
                            request={
                                "model": "gpt-5.6-terra",
                                "instructions": self.contract.policy,
                                "tools": [
                                    {
                                        "type": "function",
                                        "name": name,
                                        "parameters": {},
                                    }
                                    for name in sorted(COMMON_V2_TOOL_NAMES)
                                ],
                            },
                        )
                        ledger.stop_run(run_id, stop_reason=stop_reason)
                        trial = run_root / "trial"
                        bundle = trial / "agent/rollout-trace/bundle"
                        bundle.mkdir(parents=True)
                        harbor = mock.Mock(trial_dir=trial, returncode=0)
                        return mock.Mock(harbor=harbor)

                    parsed = mock.Mock(
                        outcome=RunOutcome.AGENT_FAILED,
                        reward=0,
                    )
                    with mock.patch(
                        "rondo_eval.proactive_eval.formal.run_budgeted_terminal_bench_core",
                        side_effect=fake_core,
                    ), mock.patch(
                        "rondo_eval.proactive_eval.formal.parse_single_task_result",
                        return_value=parsed,
                    ), mock.patch(
                        "rondo_eval.proactive_eval.formal.select_proactive_root_bundle",
                        side_effect=lambda trace_root, **_kwargs: mock.Mock(
                            root_bundle=trace_root / "bundle"
                        ),
                    ), mock.patch(
                        "rondo_eval.proactive_eval.formal.reduce_bundle",
                        side_effect=lambda _bundle, product: synthetic_team_view(
                            side="codex" if product == "codex" else "rondo",
                            run_id=run_id,
                            ordinal=slot.ordinal,
                        ),
                    ):
                        result = executor.execute(
                            slot,
                            attempt=1,
                            run_id=run_id,
                            run_root=run_root,
                        )
                    self.assertEqual(result.outcome, "product_failed")
                    self.assertEqual(result.reason_code, stop_reason)
                    self.assertTrue((run_root / "settled.json").is_file())

    def test_request_limit_without_trace_latches_instead_of_retrying(self) -> None:
        repo_paths = RepoPaths.discover(REPO_ROOT)
        config = load_runtime_config(repo_paths)
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="7" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/limit-no-trace"
        formal = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(formal, identity)
        store.ensure_receipt()
        core_calls = 0

        with open_paid_ledger(formal.ledger, self.contract) as ledger:
            executor = Plan049TerminalBenchExecutor(
                contract=self.contract,
                common_root=repo_paths.common_root,
                repo_root=repo_paths.worktree_root,
                ledger=ledger,
                api_key="test-only-not-forwarded",
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=mock.Mock(),
                config=config,
                formal_identity_sha256=store.identity_sha256,
            )

            async def fake_core(_config, request, **kwargs):
                nonlocal core_calls
                core_calls += 1
                first = slots(self.contract)[0]
                run_id = first.run_id().replace("rehearsal", "paid")
                kwargs["request_preflight"].register(
                    task_id=first.task_id,
                    role="main",
                    side=request.side,
                    request={
                        "model": "gpt-5.6-terra",
                        "instructions": self.contract.policy,
                        "tools": [
                            {
                                "type": "function",
                                "name": name,
                                "parameters": {},
                            }
                            for name in sorted(COMMON_V2_TOOL_NAMES)
                        ],
                    },
                )
                ledger.stop_run(
                    run_id, stop_reason="logical_request_limit_exceeded"
                )
                trial = store.run_root(run_id) / "trial"
                (trial / "agent/rollout-trace").mkdir(parents=True)
                return mock.Mock(harbor=mock.Mock(trial_dir=trial, returncode=0))

            with mock.patch(
                "rondo_eval.proactive_eval.formal.run_budgeted_terminal_bench_core",
                side_effect=fake_core,
            ), mock.patch(
                "rondo_eval.proactive_eval.formal.parse_single_task_result",
                return_value=mock.Mock(
                    outcome=RunOutcome.AGENT_FAILED,
                    reward=0,
                ),
            ):
                with self.assertRaisesRegex(
                    FormalError, "lacks complete terminal evidence"
                ):
                    run_formal_campaign(
                        self.contract,
                        store=store,
                        ledger=ledger,
                        executor=executor,
                        phase="pilot",
                    )
                with self.assertRaisesRegex(
                    FormalDriftError, "latched principled stop"
                ):
                    run_formal_campaign(
                        self.contract,
                        store=store,
                        ledger=ledger,
                        executor=executor,
                        phase="pilot",
                    )
        self.assertEqual(core_calls, 1)
        rows = store.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "principled_stopped")
        self.assertEqual(rows[0]["attempt"], 1)

    def test_product_terminal_without_trace_latches_across_restart(self) -> None:
        repo_paths = RepoPaths.discover(REPO_ROOT)
        config = load_runtime_config(repo_paths)
        provider = plan049_provider_projection(config, self.contract)

        for parsed_outcome, reward in (
            (RunOutcome.AGENT_FAILED, 0),
            (RunOutcome.CANCELLED, 0),
            (RunOutcome.COMPLETED, 0),
            (RunOutcome.COMPLETED, 1),
        ):
            with self.subTest(
                parsed_outcome=parsed_outcome.value,
                reward=reward,
            ):
                identity = formal_identity(
                    self.contract, provider=provider, harness_commit="9" * 40
                )
                root = (
                    self.common_root
                    / "eval-data/plan-049/paid"
                    / f"missing-trace-{parsed_outcome.value}-reward-{reward}"
                )
                formal = FormalPaths(
                    root=root,
                    receipt=root / "activation-receipt.json",
                    ledger=root / "budget-ledger.json",
                    archive=root / "records.jsonl",
                    aggregate=root / "aggregate.json",
                    runs=root / "runs",
                )
                store = FormalStore(formal, identity)
                store.ensure_receipt()
                core_calls = 0

                async def fake_core(_config, request, **kwargs):
                    nonlocal core_calls
                    core_calls += 1
                    first = slots(self.contract)[0]
                    kwargs["request_preflight"].register(
                        task_id=first.task_id,
                        role="main",
                        side=request.side,
                        request={
                            "model": "gpt-5.6-terra",
                            "instructions": self.contract.policy,
                            "tools": [
                                {
                                    "type": "function",
                                    "name": name,
                                    "parameters": {},
                                }
                                for name in sorted(COMMON_V2_TOOL_NAMES)
                            ],
                        },
                    )
                    run_id = first.run_id().replace("rehearsal", "paid")
                    trial = store.run_root(run_id) / "trial"
                    (trial / "agent/rollout-trace").mkdir(parents=True)
                    return mock.Mock(
                        harbor=mock.Mock(trial_dir=trial, returncode=0)
                    )

                def executor(ledger):
                    return Plan049TerminalBenchExecutor(
                        contract=self.contract,
                        common_root=repo_paths.common_root,
                        repo_root=repo_paths.worktree_root,
                        ledger=ledger,
                        api_key="test-only-not-forwarded",
                        counter=mock.Mock(),
                        lock_guard=mock.Mock(),
                        lease=mock.Mock(),
                        config=config,
                        formal_identity_sha256=store.identity_sha256,
                    )

                with mock.patch(
                    "rondo_eval.proactive_eval.formal.run_budgeted_terminal_bench_core",
                    side_effect=fake_core,
                ), mock.patch(
                    "rondo_eval.proactive_eval.formal.parse_single_task_result",
                    return_value=mock.Mock(
                        outcome=parsed_outcome,
                        reward=reward,
                    ),
                ):
                    with open_paid_ledger(formal.ledger, self.contract) as ledger:
                        with self.assertRaisesRegex(
                            FormalError,
                            "non-infra task result lacks complete trace evidence",
                        ):
                            run_formal_campaign(
                                self.contract,
                                store=store,
                                ledger=ledger,
                                executor=executor(ledger),
                                phase="pilot",
                            )
                    with open_paid_ledger(formal.ledger, self.contract) as ledger:
                        with self.assertRaisesRegex(
                            FormalDriftError, "latched principled stop"
                        ):
                            run_formal_campaign(
                                self.contract,
                                store=store,
                                ledger=ledger,
                                executor=executor(ledger),
                                phase="pilot",
                            )
                self.assertEqual(core_calls, 1)
                rows = store.records()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["outcome"], "principled_stopped")
                self.assertEqual(rows[0]["attempt"], 1)
                self.assertEqual(
                    rows[0]["reason_code"],
                    "non_infra_terminal_missing_trace",
                )
                marker = store.marker(rows[0]["run_id"])
                self.assertEqual(marker, rows[0])

    def test_infra_result_stays_retryable_without_trace_lookup(self) -> None:
        repo_paths = RepoPaths.discover(REPO_ROOT)
        ledger_path = self.common_root / "eval-data/plan-049/paid/infra-result.json"
        first = slots(self.contract)[0]
        run_id = first.run_id().replace("rehearsal", "paid")
        run_root = self.common_root / "infra-result" / run_id

        with open_paid_ledger(ledger_path, self.contract) as ledger:
            ledger.claim_run(run_id, cap_usd="15.10")
            executor = Plan049TerminalBenchExecutor(
                contract=self.contract,
                common_root=repo_paths.common_root,
                repo_root=repo_paths.worktree_root,
                ledger=ledger,
                api_key="test-only-not-forwarded",
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=mock.Mock(),
                config=load_runtime_config(repo_paths),
                formal_identity_sha256="a" * 64,
            )

            async def fake_core(_config, request, **kwargs):
                kwargs["request_preflight"].register(
                    task_id=first.task_id,
                    role="main",
                    side=request.side,
                    request={
                        "model": "gpt-5.6-terra",
                        "instructions": self.contract.policy,
                        "tools": [
                            {
                                "type": "function",
                                "name": name,
                                "parameters": {},
                            }
                            for name in sorted(COMMON_V2_TOOL_NAMES)
                        ],
                    },
                )
                trial = run_root / "trial"
                trial.mkdir(parents=True)
                return mock.Mock(
                    harbor=mock.Mock(trial_dir=trial, returncode=0)
                )

            with mock.patch(
                "rondo_eval.proactive_eval.formal.run_budgeted_terminal_bench_core",
                side_effect=fake_core,
            ), mock.patch(
                "rondo_eval.proactive_eval.formal.parse_single_task_result",
                return_value=mock.Mock(
                    outcome=RunOutcome.INFRA_FAILED,
                    reward=0,
                ),
            ), mock.patch(
                "rondo_eval.proactive_eval.formal.select_proactive_root_bundle"
            ) as select_trace:
                with self.assertRaises(FormalInfraError) as caught:
                    executor.execute(
                        first,
                        attempt=1,
                        run_id=run_id,
                        run_root=run_root,
                    )
            self.assertIs(type(caught.exception), FormalInfraError)
            select_trace.assert_not_called()

    def test_request_limit_settled_write_failure_latches_without_retry(self) -> None:
        repo_paths = RepoPaths.discover(REPO_ROOT)
        config = load_runtime_config(repo_paths)
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="8" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/limit-settled-write"
        formal = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(formal, identity)
        store.ensure_receipt()
        core_calls = 0

        with open_paid_ledger(formal.ledger, self.contract) as ledger:
            executor = Plan049TerminalBenchExecutor(
                contract=self.contract,
                common_root=repo_paths.common_root,
                repo_root=repo_paths.worktree_root,
                ledger=ledger,
                api_key="test-only-not-forwarded",
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=mock.Mock(),
                config=config,
                formal_identity_sha256=store.identity_sha256,
            )

            async def fake_core(_config, request, **kwargs):
                nonlocal core_calls
                core_calls += 1
                first = slots(self.contract)[0]
                run_id = first.run_id().replace("rehearsal", "paid")
                kwargs["request_preflight"].register(
                    task_id=first.task_id,
                    role="main",
                    side=request.side,
                    request={
                        "model": "gpt-5.6-terra",
                        "instructions": self.contract.policy,
                        "tools": [
                            {
                                "type": "function",
                                "name": name,
                                "parameters": {},
                            }
                            for name in sorted(COMMON_V2_TOOL_NAMES)
                        ],
                    },
                )
                ledger.stop_run(
                    run_id, stop_reason="logical_request_limit_exceeded"
                )
                trial = store.run_root(run_id) / "trial"
                bundle = trial / "agent/rollout-trace/bundle"
                bundle.mkdir(parents=True)
                return mock.Mock(harbor=mock.Mock(trial_dir=trial, returncode=0))

            with mock.patch(
                "rondo_eval.proactive_eval.formal.run_budgeted_terminal_bench_core",
                side_effect=fake_core,
            ), mock.patch(
                "rondo_eval.proactive_eval.formal.parse_single_task_result",
                return_value=mock.Mock(
                    outcome=RunOutcome.AGENT_FAILED,
                    reward=0,
                ),
            ), mock.patch(
                "rondo_eval.proactive_eval.formal.select_proactive_root_bundle",
                side_effect=lambda trace_root, **_kwargs: mock.Mock(
                    root_bundle=trace_root / "bundle"
                ),
            ), mock.patch(
                "rondo_eval.proactive_eval.formal._write_settled_file",
                side_effect=OSError("injected settled checkpoint failure"),
            ):
                with self.assertRaisesRegex(
                    FormalError, "lacks a durable terminal checkpoint"
                ):
                    run_formal_campaign(
                        self.contract,
                        store=store,
                        ledger=ledger,
                        executor=executor,
                        phase="pilot",
                    )
                with self.assertRaisesRegex(
                    FormalDriftError, "latched principled stop"
                ):
                    run_formal_campaign(
                        self.contract,
                        store=store,
                        ledger=ledger,
                        executor=executor,
                        phase="pilot",
                    )
        self.assertEqual(core_calls, 1)
        rows = store.records()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["outcome"], "principled_stopped")
        self.assertEqual(rows[0]["attempt"], 1)

    def test_formal_resume_abandons_a_requested_unpublished_attempt(self) -> None:
        config = load_runtime_config(RepoPaths.discover(REPO_ROOT))
        provider = plan049_provider_projection(config, self.contract)
        identity = formal_identity(
            self.contract, provider=provider, harness_commit="c" * 40
        )
        root = self.common_root / "eval-data/plan-049/paid/requested-fixture"
        paths = FormalPaths(
            root=root,
            receipt=root / "activation-receipt.json",
            ledger=root / "budget-ledger.json",
            archive=root / "records.jsonl",
            aggregate=root / "aggregate.json",
            runs=root / "runs",
        )
        store = FormalStore(paths, identity)
        store.ensure_receipt()
        first_slot = slots(self.contract)[0]
        first_run = first_slot.run_id().replace("rehearsal", "paid")
        executed_attempts: list[tuple[str, int]] = []

        class Executor:
            def execute(inner, slot, *, attempt, run_id, run_root):
                del inner
                executed_attempts.append((slot.slot_id, attempt))
                view = synthetic_team_view(
                    side=slot.side, run_id=run_id, ordinal=slot.ordinal
                )
                digests = write_replay_artifacts(run_root, view)
                return FormalExecutionResult(
                    outcome="completed",
                    trace_status="available",
                    request_preflight_sha256="d" * 64,
                    **digests,
                )

        with open_paid_ledger(paths.ledger, self.contract) as ledger:
            ledger.claim_run(first_run, cap_usd="15.10")
            ledger.reserve(first_run, f"{first_run}-request-001", "2.22")
            ledger.begin_attempt(
                first_run, f"{first_run}-request-001", max_attempts=5
            )
            ledger.settle(
                first_run,
                f"{first_run}-request-001",
                Usage(100, 0, 0, 10),
                pricing=provider.main_pricing,
            )
            result = run_formal_campaign(
                self.contract,
                store=store,
                ledger=ledger,
                executor=Executor(),
                phase="pilot",
            )
        first_rows = [row for row in store.records() if row["slot_id"] == first_slot.slot_id]
        self.assertEqual(
            [(row["attempt"], row["outcome"]) for row in first_rows],
            [(1, "infra_failed"), (2, "completed")],
        )
        self.assertNotIn((first_slot.slot_id, 1), executed_attempts)
        self.assertIn((first_slot.slot_id, 2), executed_attempts)
        self.assertEqual(result["run_count"], 6)

    def test_secret_readiness_never_opens_an_unsafe_path(self) -> None:
        paths = RepoPaths(self.common_root, REPO_ROOT)
        absent = secret_readiness(paths, provider_name="relay")
        self.assertFalse(any(absent.values()))
        target = self.common_root / "not-a-secret"
        target.write_text("unreadable by contract", "utf-8")
        (self.common_root / ".env.local").symlink_to(target)
        linked = secret_readiness(paths, provider_name="relay")
        self.assertTrue(linked["exists"])
        self.assertFalse(linked["regular_file"])
        self.assertFalse(linked["non_symlink"])
        self.assertFalse(linked["phase_b_required_values_nonempty"])


if __name__ == "__main__":
    unittest.main()
