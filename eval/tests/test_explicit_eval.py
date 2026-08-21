from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))
REPO_ROOT = EVAL_ROOT.parent


from rondo_eval.contracts import ModelPricing, ProviderProjection, Side  # noqa: E402
from rondo_eval.docker_supervisor import DockerResourceStop  # noqa: E402
from rondo_eval.explicit_eval.contract import (  # noqa: E402
    ContractError,
    POLICY_SHA256,
    POLICY_TEXT,
    load_contract,
)
from rondo_eval.explicit_eval.paid import (  # noqa: E402
    LOCAL_CONDITIONS,
    PHASE_B_ACTION,
    PHASE_B_AUTHORIZATION,
    PaidGuardError,
    PaidRuntimeDependencies,
    enter_paid_phase,
    run_authorized_paid_phase,
)
from rondo_eval.explicit_eval.rehearsal import plan050_store, run_fake  # noqa: E402
from rondo_eval.explicit_eval.report import (  # noqa: E402
    ReportError,
    build_case_outputs,
    validate_case,
    validate_overview,
)
from rondo_eval.explicit_eval.schedule import (  # noqa: E402
    dry_run_projection,
    slots,
)
from rondo_eval.proactive_eval.aggregate import (  # noqa: E402
    aggregate,
    synthetic_team_view,
    write_replay_artifacts,
)
from rondo_eval.proactive_eval.formal import (  # noqa: E402
    FormalDriftError,
    FormalError,
    FormalExecutionResult,
    FormalStore,
    formal_identity,
    formal_paths,
    open_paid_ledger,
    require_safe_formal_prefix,
    run_formal_campaign,
)
from rondo_eval.proactive_eval.store import StoreError, assert_body_free  # noqa: E402
from rondo_eval.proactive_eval.loopback import (  # noqa: E402
    LoopbackError,
    _command,
    _command_projection,
    loopback_output_root,
)
from rondo_eval.team_lens.reducer import reduce_bundle  # noqa: E402
from tests.test_team_lens import make_bundle  # noqa: E402


_CONTRACT_FILES = (
    "eval/locks/multi-explicit-collaboration-v1.json",
    "eval/tasksets/multi-explicit-collaboration-v1.json",
    "eval/tasksets/p2-b7-canary-catalog-v4.json",
    "eval/locks/multi-m5-runtime-v4.json",
    "eval/templates/multi-explicit-collaboration/explicit-collaboration-policy-v1.md",
    "eval/fixtures/multi-explicit-collaboration-v1/body-free-replay-v1.json",
)


class ExplicitEvalTest(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_contract(REPO_ROOT)

    def test_strict_contract_hashes_policy_lf_and_selected_tasks(self) -> None:
        expected_digests = {
            "eval/locks/multi-explicit-collaboration-v1.json": (
                "3ebdc723f87e5cc7f11e7cdedcc450dd32b993f7687b30f73e1059175e3f3de9"
            ),
            "eval/tasksets/multi-explicit-collaboration-v1.json": (
                "ea50a232328b84a32e1aa843ddb665b940b4eb7c0a568d57789d0464bbf0308a"
            ),
            "eval/tasksets/p2-b7-canary-catalog-v4.json": (
                "00b83e4435218de730c25fcbc8fd69cebc0cee36db433a4b305076cb1e157ddf"
            ),
            "eval/locks/multi-m5-runtime-v4.json": (
                "7763dc4e29077576465187aed81c8231afac73a9cf22c6b67d5cc9266bd8f02c"
            ),
            "eval/templates/multi-explicit-collaboration/"
            "explicit-collaboration-policy-v1.md": POLICY_SHA256,
            "eval/fixtures/multi-explicit-collaboration-v1/"
            "body-free-replay-v1.json": (
                "28ef4c848dc253ed18734a70b34a4342e00f4fa9e64871a8e42eacd76c481190"
            ),
        }
        for relative, expected in expected_digests.items():
            with self.subTest(relative=relative):
                raw = (REPO_ROOT / relative).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)

        policy_raw = (
            REPO_ROOT
            / "eval/templates/multi-explicit-collaboration/"
            "explicit-collaboration-policy-v1.md"
        ).read_bytes()
        self.assertEqual(policy_raw, (POLICY_TEXT + "\n").encode("utf-8"))
        self.assertEqual(policy_raw.count(b"\n"), 1)
        self.assertNotIn(b"\r", policy_raw)
        self.assertEqual(self.contract.policy, POLICY_TEXT + "\n")
        self.assertEqual(self.contract.lock["price_snapshot"]["date"], "2026-08-21")

        expected_tasks = {
            "terminal-bench/sqlite-db-truncate",
            "terminal-bench/headless-terminal",
            "terminal-bench/extract-elf",
        }
        self.assertEqual(
            {pair["task_id"] for pair in self.contract.taskset["case_pairs"]},
            expected_tasks,
        )
        for task_id in expected_tasks:
            task = self.contract.task_contract(task_id)
            self.assertTrue(task["source_digest"].startswith("sha256:"))
            self.assertIn("@sha256:", task["image_ref"])

    def test_strict_contract_rejects_unknown_lock_field_and_policy_byte_drift(
        self,
    ) -> None:
        for mutation in ("lock-shape", "policy-lf"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                self._copy_contract_files(root)
                if mutation == "lock-shape":
                    path = root / _CONTRACT_FILES[0]
                    value = json.loads(path.read_text("utf-8"))
                    value["unexpected"] = True
                    path.write_text(json.dumps(value), encoding="utf-8")
                else:
                    path = root / _CONTRACT_FILES[4]
                    path.write_bytes(path.read_bytes().removesuffix(b"\n"))
                with self.assertRaises(ContractError):
                    load_contract(root)

    def test_six_slot_identity_and_dry_run_use_an_independent_namespace(self) -> None:
        expected = [
            ("S01", "C01", "codex", "terminal-bench/sqlite-db-truncate"),
            ("S02", "C01", "rondo", "terminal-bench/sqlite-db-truncate"),
            ("S03", "C02", "rondo", "terminal-bench/headless-terminal"),
            ("S04", "C02", "codex", "terminal-bench/headless-terminal"),
            ("S05", "C03", "codex", "terminal-bench/extract-elf"),
            ("S06", "C03", "rondo", "terminal-bench/extract-elf"),
        ]
        schedule = slots(self.contract)
        self.assertEqual(
            [
                (slot.sequence_id, slot.pair_id, slot.side, slot.task_id)
                for slot in schedule
            ],
            expected,
        )
        self.assertEqual(len({slot.slot_id for slot in schedule}), 6)
        self.assertEqual(len({slot.rehearsal_run_id() for slot in schedule}), 6)
        self.assertEqual(len({slot.paid_run_id() for slot in schedule}), 6)
        for slot in schedule:
            self.assertEqual(slot.phase, "case")
            self.assertTrue(slot.rehearsal_run_id().startswith("plan050-rehearsal-"))
            self.assertTrue(slot.paid_run_id().startswith("plan050-paid-"))
            self.assertNotEqual(slot.rehearsal_run_id(), slot.paid_run_id())
            self.assertEqual(
                slot.attempt_id(request_ordinal=2),
                f"{slot.rehearsal_run_id()}-request-002",
            )

        with tempfile.TemporaryDirectory() as raw:
            common_root = Path(raw) / "common"
            projection = dry_run_projection(
                self.contract,
                common_root=common_root,
                namespace="unit-contract",
            )
            intended = (
                common_root.resolve()
                / "eval-data/plan-050/rehearsal/unit-contract"
            )
            self.assertEqual(projection["identity_class"], "rehearsal")
            self.assertEqual(projection["identity_contract"]["phase"], "case")
            self.assertEqual(
                projection["identity_contract"]["formal_namespace"],
                "plan-050-paid-v1",
            )
            self.assertEqual(projection["budget_contract"]["actual_cap_usd"], None)
            self.assertEqual(
                projection["budget_contract"]["maximum_authorizable_cap_usd"],
                "100.00",
            )
            for row in projection["slots"]:
                self.assertEqual(row["identity_class"], "rehearsal")
                self.assertTrue(row["run_id"].startswith("plan050-rehearsal-case-"))
                for artifact in row["expected"].values():
                    self.assertTrue(Path(artifact).is_relative_to(intended))
            self.assertFalse(common_root.exists(), "dry-run must not create state")

    def test_actual_cap_is_bound_only_from_a_concrete_receipt_value(self) -> None:
        self.assertIsNone(self.contract.actual_cap_usd)
        self.assertIsNone(self.contract.lock["budget"]["actual_cap_usd"])
        self.assertEqual(self.contract.maximum_authorizable_cap_usd, Decimal("100.00"))
        with self.assertRaises(ContractError):
            _ = self.contract.campaign_cap_usd
        for invalid in (None, "", "0", "100.01", "1.001", "NaN", "Infinity"):
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                self.contract.bind_actual_cap(invalid)  # type: ignore[arg-type]

        self.assertEqual(
            self.contract.bind_actual_cap("0.50").campaign_cap_usd,
            Decimal("0.50"),
        )
        bound = self.contract.bind_actual_cap("37.25")
        self.assertEqual(bound.campaign_cap_usd, Decimal("37.25"))
        self.assertIsNone(self.contract.actual_cap_usd)
        self.assertIsNone(bound.lock["budget"]["actual_cap_usd"])

    def test_fake_is_deterministic_and_preserves_valid_failures(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            common_root = Path(raw) / "common"
            first = run_fake(
                self.contract,
                common_root=common_root,
                namespace="deterministic",
            )
            store = plan050_store(
                self.contract,
                common_root=common_root,
                namespace="deterministic",
            )
            before = {
                path.relative_to(store.root): path.read_bytes()
                for path in store.root.rglob("*")
                if path.is_file()
            }
            second = run_fake(
                self.contract,
                common_root=common_root,
                namespace="deterministic",
            )
            after = {
                path.relative_to(store.root): path.read_bytes()
                for path in store.root.rglob("*")
                if path.is_file()
            }

            self.assertEqual(first, second)
            self.assertEqual(before, after)
            self.assertEqual(first["run_count"], 6)
            self.assertEqual(first["valid_success_count"], 4)
            self.assertEqual(first["valid_failure_count"], 2)
            self.assertEqual(first["infra_invalid_count"], 0)
            self.assertEqual(first["missing_slot_ids"], [])
            self.assertEqual(first["partial_pair_ids"], [])
            self.assertFalse(first["activation_observed"])
            outcomes = {row["slot_id"]: row["outcome"] for row in first["runs"]}
            self.assertEqual(outcomes["case-c02-rondo"], "task_failed")
            self.assertEqual(outcomes["case-c03-codex"], "product_failed")
            self.assertTrue(all(row["counts_as_effective"] for row in first["runs"]))
            self.assertTrue(all(row["cost_usd"] == "0.00" for row in first["runs"]))
            assert_body_free(first)

    def test_case_outputs_are_body_free_and_label_policy_noncompliance(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            aggregate = run_fake(
                self.contract,
                common_root=Path(raw) / "common",
                namespace="body-free",
            )
            cases, overview = build_case_outputs(aggregate)
            self.assertEqual(set(cases), {"C01", "C02", "C03"})
            for case in cases.values():
                validate_case(case)
                self.assertTrue(case["complete"])
                self.assertEqual([row["side"] for row in case["sides"]], ["codex", "rondo"])
                self.assertTrue(
                    all(
                        row["collaboration_status"] == "policy_noncompliance"
                        for row in case["sides"]
                    )
                )
                codex, rondo = case["sides"]
                self.assertEqual(codex["team_state_status"], "not_applicable")
                self.assertIn(rondo["team_state_status"], {"available", "partial"})
                assert_body_free(case)
            validate_overview(overview)
            assert_body_free(overview)
            self.assertEqual(
                overview["external_outcomes"],
                {"completed": 4, "product_failed": 1, "task_failed": 1},
            )
            self.assertEqual(
                overview["collaboration_statuses"],
                {"collaboration_observed": 0, "policy_noncompliance": 6},
            )

            body_bearing = copy.deepcopy(cases["C01"])
            body_bearing["sides"][0]["usage"]["response"] = "forbidden"
            with self.assertRaises(StoreError):
                assert_body_free(body_bearing)
            with self.assertRaises(ReportError):
                validate_case(body_bearing)

    def test_replay_fixture_is_bound_body_free_and_covers_orthogonal_statuses(
        self,
    ) -> None:
        fixture_path = (
            REPO_ROOT
            / "eval/fixtures/multi-explicit-collaboration-v1/"
            "body-free-replay-v1.json"
        )
        raw = fixture_path.read_bytes()
        fixture = json.loads(raw)
        self.assertEqual(fixture, self.contract.replay_fixture)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            self.contract.lock["artifacts"]["replay_fixture_sha256"],
        )
        self.assertEqual(len(fixture["records"]), 6)
        self.assertEqual(
            {row["slot_id"] for row in fixture["records"]},
            {slot.slot_id for slot in slots(self.contract)},
        )
        self.assertEqual(
            {row["outcome"] for row in fixture["records"]},
            {"completed", "task_failed", "product_failed"},
        )
        self.assertEqual(
            {row["collaboration_status"] for row in fixture["records"]},
            {"collaboration_observed", "policy_noncompliance"},
        )
        self.assertEqual(
            {row["observation_status"] for row in fixture["records"]},
            {"available", "partial"},
        )
        assert_body_free(fixture)

    def test_loopback_command_projects_high_roles_without_unsupported_config(
        self,
    ) -> None:
        catalog_path = Path("/tmp/plan050-shared-model-catalog.json")
        command = _command(
            self.contract,
            Path("/opt/frozen-codex"),
            Side.CODEX,
            "http://127.0.0.1:43210/v1",
            model_catalog_path=catalog_path,
        )
        overrides = [
            command[index + 1]
            for index, item in enumerate(command[:-1])
            if item == "-c"
        ]
        self.assertIn('model_reasoning_effort="high"', overrides)
        self.assertIn(f'model_catalog_json="{catalog_path}"', overrides)
        self.assertIn('agents.default_subagent_model="gpt-5.6-terra"', overrides)
        self.assertIn('agents.default_subagent_reasoning_effort="high"', overrides)
        self.assertIn(
            "developer_instructions=" + json.dumps(self.contract.policy), overrides
        )
        self.assertFalse(any(item.startswith("auto_review.") for item in overrides))
        projection = _command_projection(
            self.contract,
            model_catalog_identity={
                "sha256": "e" * 64,
                "main_model": "gpt-5.6-terra",
                "guardian_model": "gpt-5.6-terra",
                "override_target_slug": "gpt-5.6-terra",
            },
        )
        self.assertEqual(projection["root_effort"], "high")
        self.assertEqual(projection["member_effort"], "high")
        self.assertEqual(projection["guardian_effort"], "high")
        self.assertTrue(projection["root_request_observed"])
        self.assertFalse(projection["member_request_observed"])
        self.assertFalse(projection["guardian_request_observed"])

    def test_loopback_namespace_cannot_escape_the_campaign_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            common_root = Path(raw) / "common"
            expected = (
                common_root.resolve()
                / "eval-data/plan-050/loopback/phase-a-review"
            )
            self.assertEqual(
                loopback_output_root(
                    self.contract,
                    common_root=common_root,
                    namespace="phase-a-review",
                ),
                expected,
            )
            for namespace in ("/tmp/forged", "../../plan-049", "UPPER", ""):
                with self.subTest(namespace=namespace), self.assertRaises(
                    LoopbackError
                ):
                    loopback_output_root(
                        self.contract,
                        common_root=common_root,
                        namespace=namespace,
                    )

    def test_trace_backed_spawn_activity_and_result_are_all_required(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            bundle = make_bundle(Path(raw) / "bundle", product="codex")
            view = reduce_bundle(bundle, "codex")
            slot = slots(self.contract)[0]
            run_id = slot.rehearsal_run_id()
            record = {
                "phase": "case",
                "pair_id": slot.pair_id,
                "slot_id": slot.slot_id,
                "run_id": run_id,
                "attempt": 1,
                "task_id": slot.task_id,
                "side": slot.side,
                "product": None,
                "outcome": "completed",
                "terminal": True,
                "counts_as_effective": True,
                "cost_usd": "0.00",
                "request_count": 1,
                "trace_status": "available",
                "reason_code": None,
            }
            result = aggregate(
                [record],
                {run_id: view},
                lock_id=self.contract.lock_id,
                lock_sha256=self.contract.lock_sha256,
                policy_sha256=self.contract.policy_sha256,
                expected_slots={slot.slot_id: slot.pair_id},
            )
            row = result["runs"][0]
            self.assertGreater(row["root_spawn_accept_count"], 0)
            self.assertFalse(row["member_activity_observed"])
            self.assertTrue(row["member_result_returned"])
            cases, _overview = build_case_outputs(result)
            self.assertEqual(
                cases["C01"]["sides"][0]["collaboration_status"],
                "policy_noncompliance",
            )

            active_bundle = make_bundle(
                Path(raw) / "active-bundle",
                product="codex",
                include_member_inference=True,
            )
            active = aggregate(
                [record],
                {run_id: reduce_bundle(active_bundle, "codex")},
                lock_id=self.contract.lock_id,
                lock_sha256=self.contract.lock_sha256,
                policy_sha256=self.contract.policy_sha256,
                expected_slots={slot.slot_id: slot.pair_id},
            )
            self.assertTrue(active["runs"][0]["member_activity_observed"])
            cases, _overview = build_case_outputs(active)
            self.assertEqual(
                cases["C01"]["sides"][0]["collaboration_status"],
                "collaboration_observed",
            )

            missing_result = copy.deepcopy(active)
            missing_result["runs"][0]["member_result_returned"] = False
            cases, _overview = build_case_outputs(missing_result)
            self.assertEqual(
                cases["C01"]["sides"][0]["collaboration_status"],
                "policy_noncompliance",
            )

    def test_paid_pure_gate_and_negative_entry_have_no_external_side_effects(
        self,
    ) -> None:
        base = {
            "repo_root": REPO_ROOT,
            "authorization": PHASE_B_AUTHORIZATION,
            "phase_b_action": PHASE_B_ACTION,
            "actual_cap_usd": "37.25",
            "confirmed_balance_usd": "37.25",
            "harness_clean": True,
            "resume_prefix_safe": True,
            "phase_a_evidence_ready": True,
            "independent_review_passed": True,
            "local_conditions_ready": True,
            "docker_resource_gate_ready": True,
        }
        accepted = enter_paid_phase(**base)
        self.assertEqual(accepted.campaign_cap_usd, Decimal("37.25"))
        negative = {
            "authorization": None,
            "phase_b_action": None,
            "actual_cap_usd": "100.01",
            "confirmed_balance_usd": "37.24",
            "harness_clean": False,
            "resume_prefix_safe": False,
            "phase_a_evidence_ready": False,
            "independent_review_passed": False,
            "local_conditions_ready": False,
            "docker_resource_gate_ready": False,
        }
        for field, value in negative.items():
            with self.subTest(field=field), self.assertRaises(PaidGuardError):
                enter_paid_phase(**{**base, field: value})

        dependency = mock.Mock()
        runtime_dependencies = PaidRuntimeDependencies(
            acquire_docker_gate=dependency.acquire_docker_gate
        )
        call_base = {
            "repo_root": REPO_ROOT,
            "authorization": PHASE_B_AUTHORIZATION,
            "phase_b_action": PHASE_B_ACTION,
            "actual_cap_usd": "37.25",
            "confirmed_balance_usd": "37.25",
            "local_confirmation": LOCAL_CONDITIONS,
            "independent_review_commit": "a" * 40,
            "rehearsal_namespace": "phase-a-final",
            "loopback_namespace": "phase-a-final",
            "dependencies": runtime_dependencies,
        }
        with (
            mock.patch(
                "rondo_eval.explicit_eval.paid.harness_identity",
                return_value={"harness_commit": "a" * 40, "harness_dirty": False},
            ),
            mock.patch(
                "rondo_eval.explicit_eval.paid.require_phase_a_evidence"
            ) as phase_a,
            mock.patch(
                "rondo_eval.explicit_eval.paid.load_runtime_config"
            ) as runtime_config,
            mock.patch(
                "rondo_eval.explicit_eval.paid.load_provider_secret"
            ) as secret,
            mock.patch("rondo_eval.explicit_eval.paid.FormalStore") as formal_store,
        ):
            for override in (
                {"authorization": None},
                {"independent_review_commit": "b" * 40},
            ):
                with self.subTest(override=override), self.assertRaises(PaidGuardError):
                    run_authorized_paid_phase(**{**call_base, **override})
            dependency.acquire_docker_gate.assert_not_called()
            phase_a.assert_not_called()
            runtime_config.assert_not_called()
            secret.assert_not_called()
            formal_store.assert_not_called()

    def test_shared_formal_state_machine_runs_offline_and_resumes_idempotently(
        self,
    ) -> None:
        contract = self.contract.bind_actual_cap("25.00")
        provider = self._offline_provider()
        identity = formal_identity(
            contract,
            provider=provider,
            harness_commit="a" * 40,
        )
        self.assertEqual(identity["campaign_cap_usd"], "25.00")
        assert_body_free(identity)

        with tempfile.TemporaryDirectory() as raw:
            common_root = Path(raw) / "common"
            paths = formal_paths(common_root, contract)
            self.assertTrue(
                paths.root.is_relative_to(
                    common_root.resolve() / "eval-data/plan-050/paid"
                )
            )
            store = FormalStore(paths, identity)
            store.ensure_receipt()
            calls: list[str] = []

            class OfflineExecutor:
                def execute(inner, slot, *, attempt, run_id, run_root):
                    del inner, attempt
                    calls.append(run_id)
                    view = synthetic_team_view(
                        side=slot.side,
                        run_id=run_id,
                        ordinal=slot.ordinal,
                    )
                    digests = write_replay_artifacts(run_root, view)
                    return FormalExecutionResult(
                        outcome="completed",
                        trace_status="available",
                        request_preflight_sha256="b" * 64,
                        **digests,
                    )

            with open_paid_ledger(paths.ledger, contract) as ledger:
                first = run_formal_campaign(
                    contract,
                    store=store,
                    ledger=ledger,
                    executor=OfflineExecutor(),
                    phase="case",
                )
                second = run_formal_campaign(
                    contract,
                    store=store,
                    ledger=ledger,
                    executor=OfflineExecutor(),
                    phase="case",
                )

            self.assertEqual(first, second)
            self.assertEqual(first["evidence_kind"], "real_api")
            self.assertEqual(first["identity_class"], "paid")
            self.assertEqual(first["run_count"], 6)
            self.assertEqual(len(calls), 6)
            self.assertEqual(len(store.records()), 6)
            self.assertTrue(all(run_id.startswith("plan050-paid-case-") for run_id in calls))
            self.assertTrue(
                all(Decimal(row["cost_usd"]) == Decimal("0") for row in first["runs"])
            )
            assert_body_free(first)

    def test_docker_resource_stop_is_latched_across_formal_resume(self) -> None:
        contract = self.contract.bind_actual_cap("25.00")
        provider = self._offline_provider()
        identity = formal_identity(
            contract, provider=provider, harness_commit="f" * 40
        )
        with tempfile.TemporaryDirectory() as raw:
            common_root = Path(raw) / "common"
            paths = formal_paths(common_root, contract)
            store = FormalStore(paths, identity)
            store.ensure_receipt()
            calls: list[str] = []

            class HardStopExecutor:
                def execute(inner, slot, *, attempt, run_id, run_root):
                    del inner, slot, attempt, run_root
                    calls.append(run_id)
                    raise DockerResourceStop("injected host capacity stop")

            with open_paid_ledger(paths.ledger, contract) as ledger:
                first = run_formal_campaign(
                    contract,
                    store=store,
                    ledger=ledger,
                    executor=HardStopExecutor(),
                    phase="case",
                )
            self.assertEqual(calls, ["plan050-paid-case-c01-codex-a01"])
            self.assertEqual(first["runs"][0]["outcome"], "principled_stopped")
            self.assertEqual(first["runs"][0]["reason_code"], "docker_resource_stop")
            with self.assertRaisesRegex(FormalError, "latched stop"):
                require_safe_formal_prefix(paths, identity, contract)

            reopened = FormalStore(paths, identity, create=False)
            with open_paid_ledger(paths.ledger, contract) as ledger:
                with self.assertRaisesRegex(
                    FormalDriftError, "latched principled stop"
                ):
                    run_formal_campaign(
                        contract,
                        store=reopened,
                        ledger=ledger,
                        executor=HardStopExecutor(),
                        phase="case",
                    )
            self.assertEqual(calls, ["plan050-paid-case-c01-codex-a01"])

    def _copy_contract_files(self, root: Path) -> None:
        for relative in _CONTRACT_FILES:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / relative, destination)

    def _offline_provider(self) -> ProviderProjection:
        price = self.contract.lock["price_snapshot"]
        pricing = ModelPricing(
            model_id=price["model_id"],
            input_usd_per_million=Decimal(price["input_usd_per_million"]),
            cached_input_usd_per_million=Decimal(
                price["cached_input_usd_per_million"]
            ),
            output_usd_per_million=Decimal(price["output_usd_per_million"]),
            long_context_threshold_tokens=price["long_context_threshold_tokens"],
            long_context_input_multiplier=Decimal(
                price["long_context_input_multiplier"]
            ),
            long_context_output_multiplier=Decimal(
                price["long_context_output_multiplier"]
            ),
            cache_write_input_multiplier=Decimal(
                price["cache_write_input_multiplier"]
            ),
            price_snapshot_date=price["date"],
            price_source_url=price["source_url"],
        )
        provider = ProviderProjection(
            provider_id="relay",
            display_name="Offline injected relay",
            api="responses",
            base_url="https://www.cctq.ai/v1",
            api_key_env="PLAN050_TEST_API_KEY",
            main_model="gpt-5.6-terra",
            main_effort="high",
            guardian_model="gpt-5.6-terra",
            guardian_effort="high",
            main_pricing=pricing,
            guardian_pricing=pricing,
            max_attempts=5,
            retry_backoff_seconds=2.0,
            unbilled_retry_statuses=(429, 500, 502, 503, 504),
            profile_sha256="c" * 64,
            config_sha256="d" * 64,
        )
        provider.validate()
        return provider


if __name__ == "__main__":
    unittest.main()
