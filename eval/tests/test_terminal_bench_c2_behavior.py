from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from rondo_eval.config import RepoPaths
from rondo_eval.api_budget_proxy import (
    BudgetCapacityExhausted,
    PersistentBudgetLedger,
    Usage,
)
from rondo_eval.terminal_bench.c2_behavior import (
    C2BehaviorError,
    C2BehaviorState,
    classify_provider_hard_stop,
    classify_pure_transport_retry,
    freeze_slots,
    _ensure_initialization_state_and_budget,
    _require_open_initialization_recovery,
    _initial_state,
    _reconcile_initialization_pointer,
    campaign_root,
    initialize_identity,
    plan058_request_reservation,
    plan058_usage_envelope,
    public_result,
    state_path,
    validate_refined_assessment,
)
from rondo_eval.terminal_bench.c2_behavior_cli import (
    _attempt_budget_projection,
    _formal_attempt_interrupted_without_projection,
    _logical_budget_summary,
    _make_request,
    _transition_preflight_worker_failure,
    status,
)
from rondo_eval.terminal_bench.tasksets import FrozenTask

from .test_harness_observation import _observation
from .test_api_budget_proxy import MAIN_PRICING
from rondo_eval.terminal_bench.task_budget import (
    TaskBudgetIdentity,
    load_task_budget,
    start_task_budget,
    task_budget_path,
)


def _task(index: int = 1) -> FrozenTask:
    return FrozenTask(
        task_id=f"terminal-bench/task-{index:02d}",
        source_digest="sha256:" + f"{index:064x}"[-64:],
        image_tag=f"example/task-{index:02d}:latest",
        image_ref=f"example/task-{index:02d}@sha256:" + f"{index + 10:064x}"[-64:],
        workdir="/workspace",
        memory_mb=2048,
        timeout_seconds=1800,
        agent_timeout_seconds=900,
        verifier_timeout_seconds=900,
        build_timeout_seconds=600,
    )


def _transport_metadata(
    *,
    status: int = 0,
    end: str = "open_error",
    code: str | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "requests": [
            {
                "request_id": "request-1",
                "upstream_status": status,
                "stream_end_kind": end,
                "terminal_event_type": None,
                "terminal_error_code": code,
                "usage_valid": False,
                "attempt_count": 1,
            }
        ],
    }


def _budget_run() -> dict[str, object]:
    return {
        "cap_usd": "40.000000",
        "spent_usd": "1.000000",
        "stopped": True,
        "stop_reason": "missing_or_invalid_usage",
        "infra_taint": {"reason": "missing_or_invalid_usage"},
        "requests": {
            "request-1": {
                "status": "settled",
                "attempt_count": 1,
                "charged_usd": "1.000000",
                "usage_valid": False,
                "settlement_kind": "unpriced_fallback",
                "reserved_usd": "1.000000",
            }
        },
    }


def _retry_evidence(
    attempt: int,
    attempt_run_id: str,
    *,
    prior_budget_run_sha256: str | None = None,
) -> dict[str, object]:
    return {
        "attempt": attempt,
        "attempt_run_id": attempt_run_id,
        "classification": "typed_pure_transport",
        "reason_code": "upstream_open_error",
        "api_metadata_sha256": "a" * 64,
        "budget_run_sha256": chr(ord("a") + attempt) * 64,
        "prior_budget_run_sha256": prior_budget_run_sha256,
        "ledger_stop_reason": "missing_or_invalid_usage",
        "upstream_attempts": 1,
        "logical_request_count": attempt,
        "logical_upstream_attempts": attempt,
        "charged_usd": "1.000000",
    }


def _state_identity(*, campaign_mode: str = "formal") -> SimpleNamespace:
    task = _task()
    slot = freeze_slots(
        (task,),
        run_id_date="20260822",
        run_id_sequence_base=580000001,
        rounds=1,
    )[0]
    return SimpleNamespace(
        campaign_id=f"plan058-direction1-c2-{campaign_mode}-state-test",
        batch_id=f"plan058-direction1-c2-{campaign_mode}-state-test-batch",
        campaign_mode=campaign_mode,
        lock_sha256="c" * 64,
        tasks=(task,),
        slots=(slot,),
        prior_settled_usd=Decimal(0),
        slot=lambda slot_id: slot
        if slot_id == slot.slot_id
        else (_ for _ in ()).throw(KeyError(slot_id)),
    )


class C2BehaviorStateTests(unittest.TestCase):
    def test_formal_preflight_fault_invalidates_while_commissioning_retries(
        self,
    ) -> None:
        for campaign_mode, expected_status, expected_preflight in (
            ("formal", "invalid", "running"),
            ("commissioning", "running", "pending"),
        ):
            with self.subTest(campaign_mode=campaign_mode), tempfile.TemporaryDirectory() as raw:
                identity = _state_identity(campaign_mode=campaign_mode)
                value = _initial_state(identity)
                value["preflight"][0].update(status="running", attempts=1)
                path = Path(raw) / "state.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                with C2BehaviorState(path, identity=identity) as state:
                    state.fail_preflight(identity.tasks[0].task_id, reason="InjectedFault")
                    snapshot = state.snapshot()
                self.assertEqual(snapshot["status"], expected_status)
                self.assertEqual(snapshot["preflight"][0]["status"], expected_preflight)
                if campaign_mode == "formal":
                    self.assertEqual(
                        snapshot["invalid_reason"],
                        "formal_preflight_failed:InjectedFault",
                    )

        with tempfile.TemporaryDirectory() as raw:
            identity = _state_identity(campaign_mode="formal")
            path = Path(raw) / "state-before-claim.json"
            path.write_text(json.dumps(_initial_state(identity)), encoding="utf-8")
            with C2BehaviorState(path, identity=identity) as state:
                _transition_preflight_worker_failure(
                    state,
                    identity=identity,
                    reason="WorkerInputFault",
                )
                snapshot = state.snapshot()
            self.assertEqual(snapshot["status"], "invalid")
            self.assertEqual(
                snapshot["invalid_reason"],
                "formal_preflight_failed:WorkerInputFault",
            )

    def test_unavailable_final_resource_sample_invalidates_ready_campaign(self) -> None:
        identity = _state_identity()
        value = _initial_state(identity)
        value["preflight"][0].update(
            status="complete", attempts=1, receipt_sha256="d" * 64
        )
        value["slots"][0].update(
            status="published",
            execution_attempts=1,
            published_attempt=1,
            published_attempt_run_id=identity.slots[0].attempt_run_id(1),
            record_sha256="e" * 64,
        )
        value["status"] = "ready_to_finalize"
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "state.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with C2BehaviorState(path, identity=identity) as state:
                state.store_final_storage(
                    {
                        "final_sample_status": "unavailable_after_fail_closed",
                        "final_sample_reason": "InjectedStorageFault",
                    }
                )
                snapshot = state.snapshot()

        self.assertEqual(snapshot["status"], "invalid")
        self.assertEqual(
            snapshot["invalid_reason"],
            "final_resource_sample_unavailable:InjectedStorageFault",
        )
        self.assertEqual(
            snapshot["final_storage"]["final_sample_reason"],
            "InjectedStorageFault",
        )

    def test_reliable_usage_reservation_stops_before_crossing_task_cap(self) -> None:
        provider = {
            "main_pricing": MAIN_PRICING.to_dict(),
            "guardian_pricing": MAIN_PRICING.to_dict(),
        }
        envelope = plan058_usage_envelope()
        reservation = plan058_request_reservation(provider)
        with tempfile.TemporaryDirectory() as raw:
            with PersistentBudgetLedger(
                Path(raw) / "budget.json",
                batch_id="plan058-reliable-cap",
                total_cap_usd=reservation + Decimal("0.500000"),
                max_runs=1,
                default_run_cap_usd=reservation + Decimal("0.500000"),
                usage_envelope=envelope,
                unpriced_fallback_usd="1",
                unpriced_fallback_per_attempt=True,
                reservation_upstream_attempts=1,
            ) as ledger:
                ledger.claim_run("logical-run")
                ledger.reserve("logical-run", "request-1", reservation)
                ledger.begin_attempt("logical-run", "request-1", max_attempts=1)
                settlement = ledger.settle(
                    "logical-run",
                    "request-1",
                    Usage(
                        envelope.max_input_tokens,
                        0,
                        envelope.max_input_tokens,
                        envelope.max_output_tokens,
                    ),
                    pricing=MAIN_PRICING,
                )
                self.assertEqual(settlement.charged_usd, reservation)
                with self.assertRaises(BudgetCapacityExhausted):
                    ledger.reserve("logical-run", "request-2", reservation)
                snapshot = ledger.snapshot()

        self.assertLessEqual(
            Decimal(snapshot["spent_usd"]) + Decimal(snapshot["reserved_usd"]),
            reservation + Decimal("0.500000"),
        )
        with tempfile.TemporaryDirectory() as raw:
            with PersistentBudgetLedger(
                Path(raw) / "unpriced.json",
                batch_id="plan058-unpriced-one-dollar",
                total_cap_usd=reservation,
                max_runs=1,
                default_run_cap_usd=reservation,
                usage_envelope=envelope,
                unpriced_fallback_usd="1",
                unpriced_fallback_per_attempt=True,
                reservation_upstream_attempts=1,
            ) as ledger:
                ledger.claim_run("logical-run")
                ledger.reserve("logical-run", "request-1", reservation)
                ledger.begin_attempt("logical-run", "request-1", max_attempts=1)
                settlement = ledger.settle(
                    "logical-run", "request-1", None, pricing=MAIN_PRICING
                )
        self.assertEqual(settlement.charged_usd, Decimal("1.000000"))

    def test_formal_restart_cannot_reuse_projectionless_attempt_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            metadata = Path(raw) / "attempt" / "api-metadata.json"
            metadata.parent.mkdir()
            self.assertTrue(
                _formal_attempt_interrupted_without_projection(
                    campaign_mode="formal",
                    attempt_was_running=False,
                    work_root_existed=True,
                    metadata_path=metadata,
                )
            )
            self.assertFalse(
                _formal_attempt_interrupted_without_projection(
                    campaign_mode="commissioning",
                    attempt_was_running=True,
                    work_root_existed=True,
                    metadata_path=metadata,
                )
            )
            self.assertTrue(
                _formal_attempt_interrupted_without_projection(
                    campaign_mode="formal",
                    attempt_was_running=True,
                    work_root_existed=False,
                    metadata_path=metadata,
                )
            )
            metadata.write_text("{}", encoding="utf-8")
            self.assertFalse(
                _formal_attempt_interrupted_without_projection(
                    campaign_mode="formal",
                    attempt_was_running=True,
                    work_root_existed=True,
                    metadata_path=metadata,
                )
            )

    def test_transport_retry_reuses_one_budget_run_without_losing_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "budget.json"
            with PersistentBudgetLedger(
                path,
                batch_id="plan058-one-logical-run",
                total_cap_usd="50",
                max_runs=1,
                default_run_cap_usd="40",
                unpriced_fallback_usd="1",
                unpriced_fallback_per_attempt=True,
                reservation_upstream_attempts=1,
            ) as ledger:
                ledger.claim_run("logical-run", cap_usd="40")
                ledger.reserve("logical-run", "request-1", "1")
                ledger.begin_attempt("logical-run", "request-1", max_attempts=1)
                ledger.settle("logical-run", "request-1", None, pricing=MAIN_PRICING)
                first = ledger.snapshot()["runs"]["logical-run"]
                self.assertTrue(first["stopped"])
                ledger.resume_settled_infra_run(
                    "logical-run",
                    expected_stop_reason=first["stop_reason"],
                    cap_usd="40",
                )
                ledger.reserve("logical-run", "request-2", "1")
                ledger.begin_attempt("logical-run", "request-2", max_attempts=1)
                ledger.settle("logical-run", "request-2", None, pricing=MAIN_PRICING)
                final = ledger.snapshot()

        self.assertEqual(final["run_slots_used"], 1)
        self.assertEqual(final["spent_usd"], "2.000000")
        self.assertEqual(
            set(final["runs"]["logical-run"]["requests"]),
            {"request-1", "request-2"},
        )

    def test_transport_retries_keep_one_logical_slot_and_unique_physical_runs(self) -> None:
        task = _task()
        slot = freeze_slots(
            (task,),
            run_id_date="20260822",
            run_id_sequence_base=580000001,
            rounds=1,
        )[0]
        identity = SimpleNamespace(
            campaign_id="plan058-direction1-c2-test",
            lock_sha256="c" * 64,
            tasks=(task,),
            slots=(slot,),
            slot=lambda slot_id: slot if slot_id == slot.slot_id else None,
        )
        state_value = {
            "schema_version": 1,
            "kind": "rondo_direction1_c2_behavior",
            "campaign_id": identity.campaign_id,
            "campaign_lock_sha256": identity.lock_sha256,
            "status": "running",
            "invalid_reason": None,
            "paid_boundary": False,
            "preflight": [
                {
                    "task_id": task.task_id,
                    "status": "complete",
                    "attempts": 1,
                    "receipt_sha256": "d" * 64,
                    "last_error": None,
                }
            ],
            "slots": [
                {
                    "slot_id": slot.slot_id,
                    "logical_run_id": slot.logical_run_id,
                    "status": "pending",
                    "execution_attempts": 0,
                    "current_attempt_run_id": None,
                    "transport_retries": [],
                    "published_attempt": None,
                    "published_attempt_run_id": None,
                    "record_sha256": None,
                }
            ],
            "final_storage": None,
            "outcome": None,
        }
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "state.json"
            path.write_text(json.dumps(state_value), encoding="utf-8")
            with C2BehaviorState(path, identity=identity) as state:
                retry_runs = []
                for expected_attempt in range(1, 5):
                    claimed = state.claim_or_resume_slot()
                    assert claimed is not None
                    _, retry_attempt, retry_run = claimed
                    self.assertEqual(retry_attempt, expected_attempt)
                    retry_runs.append(retry_run)
                    state.mark_transport_retry(
                        slot.slot_id,
                        attempt=retry_attempt,
                        attempt_run_id=retry_run,
                        evidence=_retry_evidence(
                            retry_attempt,
                            retry_run,
                            prior_budget_run_sha256=(
                                chr(ord("a") + retry_attempt - 1) * 64
                                if retry_attempt > 1
                                else None
                            ),
                        ),
                    )
                claimed = state.claim_or_resume_slot()
                assert claimed is not None
                _, published_attempt, published_run = claimed
                self.assertEqual(published_attempt, 5)
                self.assertEqual(len(set((*retry_runs, published_run))), 5)
                state.publish_slot(
                    slot.slot_id,
                    attempt=published_attempt,
                    attempt_run_id=published_run,
                    record_sha256="e" * 64,
                )
                snapshot = state.snapshot()

            self.assertEqual(snapshot["status"], "ready_to_finalize")
            self.assertEqual(snapshot["slots"][0]["execution_attempts"], 5)
            self.assertEqual(len(snapshot["slots"][0]["transport_retries"]), 4)
            self.assertEqual(snapshot["slots"][0]["published_attempt"], 5)

    def test_non_transport_attempt_cannot_enter_retry_state(self) -> None:
        self.assertIsNone(
            classify_pure_transport_retry(
                attempt=1,
                attempt_run_id="logical-a001",
                api_metadata=_transport_metadata(status=401, end="non_sse"),
                budget_run=_budget_run(),
            )
        )
        self.assertEqual(
            classify_provider_hard_stop(
                _transport_metadata(
                    status=429,
                    end="non_sse",
                    code="insufficient_quota",
                )
            ),
            "provider_quota_or_rate_limit",
        )
        self.assertIsNone(
            classify_pure_transport_retry(
                attempt=1,
                attempt_run_id="logical-a001",
                api_metadata=_transport_metadata(
                    status=429,
                    end="non_sse",
                    code="insufficient_quota",
                ),
                budget_run=_budget_run(),
            )
        )

    def test_typed_open_error_is_retryable_and_body_free(self) -> None:
        evidence = classify_pure_transport_retry(
            attempt=1,
            attempt_run_id="logical-a001",
            api_metadata=_transport_metadata(),
            budget_run=_budget_run(),
        )

        assert evidence is not None
        self.assertEqual(evidence["classification"], "typed_pure_transport")
        self.assertEqual(evidence["reason_code"], "upstream_open_error")
        self.assertEqual(evidence["charged_usd"], "1.000000")
        self.assertNotIn("request_id", evidence)

    def test_prior_success_does_not_hide_a_terminal_transport_failure(self) -> None:
        metadata = _transport_metadata()
        metadata["requests"].insert(
            0,
            {
                "request_id": "request-0",
                "upstream_status": 200,
                "stream": True,
                "stream_end_kind": "terminal",
                "terminal_event_type": "response.completed",
                "terminal_response_status": "completed",
                "terminal_error_code": None,
                "usage_valid": True,
                "attempt_count": 1,
            },
        )
        budget = _budget_run()
        budget["requests"]["request-0"] = {
            "status": "settled",
            "attempt_count": 1,
            "charged_usd": "0.010000",
            "usage_valid": True,
            "settlement_kind": "usage_priced",
            "reserved_usd": "1.000000",
        }
        budget["spent_usd"] = "1.010000"

        evidence = classify_pure_transport_retry(
            attempt=1,
            attempt_run_id="logical-a001",
            api_metadata=metadata,
            budget_run=budget,
        )

        assert evidence is not None
        self.assertEqual(evidence["upstream_attempts"], 2)
        self.assertEqual(evidence["charged_usd"], "1.010000")

    def test_later_transport_attempt_reconciles_new_subset_and_cumulative_chain(
        self,
    ) -> None:
        first_run = _budget_run()
        first = classify_pure_transport_retry(
            attempt=1,
            attempt_run_id="logical-a1",
            api_metadata=_transport_metadata(),
            budget_run=first_run,
            logical_budget_run=first_run,
        )
        assert first is not None

        logical_run = json.loads(json.dumps(first_run))
        logical_run["requests"]["request-2"] = {
            "status": "settled",
            "attempt_count": 1,
            "charged_usd": "1.000000",
            "usage_valid": False,
            "settlement_kind": "unpriced_fallback",
            "reserved_usd": "1.000000",
        }
        logical_run["spent_usd"] = "2.000000"
        second_metadata = _transport_metadata()
        second_metadata["requests"][0]["request_id"] = "request-2"
        second_budget = _attempt_budget_projection(
            logical_run, request_ids={"request-2"}
        )
        second = classify_pure_transport_retry(
            attempt=2,
            attempt_run_id="logical-a2",
            api_metadata=second_metadata,
            budget_run=second_budget,
            logical_budget_run=logical_run,
            prior_retry_evidence=first,
        )

        assert second is not None
        self.assertEqual(set(second_budget["requests"]), {"request-2"})
        self.assertEqual(second["prior_budget_run_sha256"], first["budget_run_sha256"])
        self.assertEqual(second["logical_request_count"], 2)
        self.assertEqual(second["logical_upstream_attempts"], 2)
        self.assertEqual(
            _logical_budget_summary(logical_run, logical_run_id="logical-run")[
                "request_count"
            ],
            2,
        )

        logical_run["requests"]["unobserved-request"] = json.loads(
            json.dumps(logical_run["requests"]["request-2"])
        )
        logical_run["spent_usd"] = "3.000000"
        self.assertIsNone(
            classify_pure_transport_retry(
                attempt=2,
                attempt_run_id="logical-a2",
                api_metadata=second_metadata,
                budget_run=second_budget,
                logical_budget_run=logical_run,
                prior_retry_evidence=first,
            )
        )


class C2BehaviorInitializationTests(unittest.TestCase):
    def test_result_namespace_and_filename_are_campaign_bound(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = RepoPaths(common_root=root, worktree_root=root)
            campaign_id = "plan058-direction1-c2-result-binding"
            common = dict(
                campaign_id=campaign_id,
                batch_id=campaign_id + "-batch",
                campaign_mode="commissioning",
                runtime_manifest=root / "missing-manifest.json",
                run_id_date="20260822",
                run_id_sequence_base=580000001,
                commissioning_task_id="terminal-bench/task-01",
            )
            with self.assertRaisesRegex(C2BehaviorError, "initialization identity"):
                initialize_identity(
                    paths,
                    result_namespace="other-result",
                    public_result_path=Path(
                        f"eval/results/observations/{campaign_id}.json"
                    ),
                    **common,
                )
            with self.assertRaisesRegex(C2BehaviorError, "result namespace"):
                initialize_identity(
                    paths,
                    result_namespace=campaign_id,
                    public_result_path=Path(
                        "eval/results/observations/colliding-name.json"
                    ),
                    **common,
                )

    def test_lock_pointer_restart_is_exact_and_rejects_active_collision(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = RepoPaths(common_root=root, worktree_root=root)
            lock_relpath = Path("eval/locks/plan058-direction1-c2-restart.json")
            (root / lock_relpath).parent.mkdir(parents=True)
            (root / lock_relpath).write_text("{}", encoding="utf-8")
            digest = "a" * 64
            _reconcile_initialization_pointer(
                paths, lock_relpath=lock_relpath, digest=digest
            )
            pointer_path = root / "eval/locks/plan058-direction1-c2-active.json"
            expected = json.loads(pointer_path.read_text(encoding="utf-8"))
            self.assertEqual(expected["active_lock"], lock_relpath.as_posix())

            retired = dict(expected)
            retired["active_lock"] = None
            retired["active_lock_sha256"] = None
            pointer_path.write_text(json.dumps(retired), encoding="utf-8")
            _reconcile_initialization_pointer(
                paths, lock_relpath=lock_relpath, digest=digest
            )
            self.assertEqual(
                json.loads(pointer_path.read_text(encoding="utf-8")), expected
            )

            collision = dict(expected)
            collision["active_lock"] = "eval/locks/other.json"
            pointer_path.write_text(json.dumps(collision), encoding="utf-8")
            with self.assertRaisesRegex(C2BehaviorError, "pointer differs"):
                _reconcile_initialization_pointer(
                    paths, lock_relpath=lock_relpath, digest=digest
                )

    def test_state_and_task_envelope_restart_boundaries_are_idempotent(self) -> None:
        for boundary in ("none", "state", "envelope", "both"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                paths = RepoPaths(common_root=root, worktree_root=root)
                identity = _state_identity(campaign_mode="commissioning")
                campaign = campaign_root(paths, identity)
                campaign.mkdir(parents=True)
                (campaign / "executor.lock").write_text("lease", encoding="utf-8")
                if boundary in {"state", "both"}:
                    state_path(paths, identity).write_text(
                        json.dumps(_initial_state(identity)), encoding="utf-8"
                    )
                envelope_path = task_budget_path(root, "plan-058-direction1-c2-behavior")
                if boundary in {"envelope", "both"}:
                    start_task_budget(
                        envelope_path,
                        active=TaskBudgetIdentity(
                            identity.campaign_id, identity.batch_id
                        ),
                        task_budget_id="plan-058-direction1-c2-behavior",
                        cap_usd=Decimal("50"),
                    )

                _ensure_initialization_state_and_budget(paths, identity)
                frozen_state = state_path(paths, identity).read_bytes()
                frozen_envelope = envelope_path.read_bytes()
                _ensure_initialization_state_and_budget(paths, identity)

                self.assertEqual(state_path(paths, identity).read_bytes(), frozen_state)
                self.assertEqual(envelope_path.read_bytes(), frozen_envelope)
                envelope = load_task_budget(
                    envelope_path,
                    task_budget_id="plan-058-direction1-c2-behavior",
                    cap_usd=Decimal("50"),
                )
                self.assertEqual(
                    envelope["active_identity"]["campaign_id"], identity.campaign_id
                )

    def test_initialization_recovery_does_not_reactivate_retired_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = RepoPaths(common_root=root, worktree_root=root)
            identity = _state_identity(campaign_mode="commissioning")
            lock_relpath = Path("eval/locks/plan058-direction1-c2-retired.json")
            pointer_path = root / "eval/locks/plan058-direction1-c2-active.json"
            pointer_path.parent.mkdir(parents=True)
            pointer_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "plan058_direction1_c2_behavior",
                        "active_lock": None,
                        "active_lock_sha256": None,
                        "last_lock": lock_relpath.as_posix(),
                        "last_lock_sha256": identity.lock_sha256,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(C2BehaviorError, "retired identity"):
                _require_open_initialization_recovery(
                    paths,
                    identity=identity,
                    lock_relpath=lock_relpath,
                    digest=identity.lock_sha256,
                )

    def test_initialized_state_requires_matching_active_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            paths = RepoPaths(common_root=root, worktree_root=root)
            identity = _state_identity(campaign_mode="commissioning")
            campaign = campaign_root(paths, identity)
            campaign.mkdir(parents=True)
            state_path(paths, identity).write_text(
                json.dumps(_initial_state(identity)), encoding="utf-8"
            )

            with self.assertRaisesRegex(C2BehaviorError, "active pointer"):
                _require_open_initialization_recovery(
                    paths,
                    identity=identity,
                    lock_relpath=Path(
                        "eval/locks/plan058-direction1-c2-recovery.json"
                    ),
                    digest=identity.lock_sha256,
                )


class C2BehaviorPublicationTests(unittest.TestCase):
    def test_plan058_request_enables_only_the_frozen_product_variable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            identity = SimpleNamespace(
                batch_id="plan058-direction1-c2-test-batch",
                value={
                    "seccomp": {
                        "source_sha256": "a" * 64,
                        "effective_sha256": "b" * 64,
                    },
                    "provider": {
                        "public_profile": {
                            "main_model": "gpt-5.6-terra",
                            "main_effort": "medium",
                            "guardian_effort": "low",
                        }
                    },
                },
            )
            request = _make_request(
                paths=RepoPaths(common_root=root, worktree_root=root),
                identity=identity,
                task=_task(),
                manifest=SimpleNamespace(product="rondo-local"),
                work_root=root / "work",
                docker_task_id="plan058-test-a001",
                seccomp_profile=root / "seccomp.json",
                stub=False,
            )

        self.assertTrue(request.exec_command_repeat_guidance_enabled)
        self.assertEqual(request.max_retries, 0)
        self.assertEqual(request.pinned_model_id, "gpt-5.6-terra")
        self.assertEqual(request.pinned_main_effort, "medium")
        self.assertEqual(request.pinned_guardian_effort, "low")

    def test_refined_assessment_must_reconcile_every_raw_occurrence(self) -> None:
        observation = _observation()
        observation["tools"]["command"] = 1
        observation["tools"]["total"] = 1
        observation["tools"]["total_lifecycle_duration_ms"] = 7
        observation["tools"]["repeated_exact_commands"] = 1
        observation["tools"]["repeated_exact_command_lifecycle_duration_ms"] = 7
        records = [{"slot": {"slot_id": "slot-1"}, "observation": observation}]
        assessment = {
            "schema_version": 1,
            "kind": "plan058_c2_refined_classification",
            "no_harm": {
                "reasonable_repeats_preserved": True,
                "recovery_and_user_control_preserved": True,
                "tools_remain_executable": True,
                "no_material_task_harm": True,
            },
            "slots": [
                {
                    "slot_id": "slot-1",
                    "harmful": 0,
                    "reasonable": 1,
                    "insufficient": 0,
                    "harmful_duration_ms": 0,
                    "reasonable_duration_ms": 7,
                    "insufficient_duration_ms": 0,
                }
            ],
        }

        result = validate_refined_assessment(records, assessment)
        self.assertEqual(result["harmful_occurrences"], 0)
        self.assertEqual(result["reasonable_occurrences"], 1)

        assessment["slots"][0]["reasonable"] = 0
        with self.assertRaisesRegex(C2BehaviorError, "reconcile"):
            validate_refined_assessment(records, assessment)

    def test_complete_task_failures_remain_formal_results(self) -> None:
        slots = tuple(SimpleNamespace(slot_id=f"slot-{index:02d}") for index in range(20))
        identity = SimpleNamespace(
            campaign_id="plan058-direction1-c2-formal-test",
            campaign_mode="formal",
            lock_sha256="a" * 64,
            tasks=tuple(range(10)),
            slots=slots,
            value={"rounds": 2},
            prior_settled_usd=Decimal(0),
            campaign_cap_usd=Decimal("50"),
        )
        records = [
            {
                "slot": {"slot_id": slot.slot_id},
                "terminal_bench": {
                    "outcome": "completed",
                    "task_outcome": "fail",
                },
                "observation": _observation(),
            }
            for slot in slots
        ]
        refined = {
            "schema_version": 1,
            "kind": "plan058_c2_refined_classification",
            "no_harm": {
                "reasonable_repeats_preserved": True,
                "recovery_and_user_control_preserved": True,
                "tools_remain_executable": True,
                "no_material_task_harm": False,
            },
            "slots": [
                {
                    "slot_id": slot.slot_id,
                    "harmful": 0,
                    "reasonable": 0,
                    "insufficient": 0,
                    "harmful_duration_ms": 0,
                    "reasonable_duration_ms": 0,
                    "insufficient_duration_ms": 0,
                }
                for slot in slots
            ],
        }
        state = {
            "status": "ready_to_finalize",
            "slots": [
                {"status": "published", "transport_retries": []} for _slot in slots
            ],
            "final_storage": {},
            "invalid_reason": None,
        }
        budget = {
            "spent_usd": "0.000000",
            "reserved_usd": "0.000000",
            "run_slots_used": 20,
            "runs": {},
        }

        result = public_result(
            identity=identity,
            state=state,
            budget=budget,
            records=records,
            refined_assessment=refined,
            snapshot_date="2026-08-22",
        )

        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["outcome"], "withdraw")
        self.assertEqual(result["terminal_bench"]["task_failures"], 20)

    def test_status_is_zero_api_when_uninitialized(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self.assertEqual(
                status(RepoPaths(common_root=root, worktree_root=root)),
                {"status": "uninitialized", "paid_requests_sent": 0},
            )


if __name__ == "__main__":
    unittest.main()
