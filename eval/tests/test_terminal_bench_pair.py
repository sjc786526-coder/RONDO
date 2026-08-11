from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import (  # noqa: E402
    BinaryManifest,
    ModelPricing,
    ProviderProjection,
    RunSpec,
    Side,
)
from rondo_eval.terminal_bench import pair as pair_module  # noqa: E402
from rondo_eval.terminal_bench.metrics import RunnerMetricsTimer, metrics_from_dict  # noqa: E402
from rondo_eval.terminal_bench.pair import (  # noqa: E402
    PairSequenceLedger,
    PairIdentityError,
    assess_m1,
    has_complete_guardian_approval_sequence,
    load_consumed_v17_pair_identity,
    load_consumed_v16_pair_identity,
    load_consumed_v10_pair_identity,
    load_consumed_v11_pair_identity,
    load_consumed_v12_pair_identity,
    load_consumed_v13_pair_identity,
    load_consumed_v14_pair_identity,
    load_consumed_v15_pair_identity,
    load_consumed_v9_pair_identity,
    load_legacy_pair_identity,
    load_pair_identity,
    load_previous_pair_identity,
    terminal_record_sha256,
    validate_harbor_installation,
)
from rondo_eval.terminal_bench.runner import HARBOR_EXECUTABLE  # noqa: E402


class PairIdentityTests(unittest.TestCase):
    HARNESS_COMMIT = "f" * 40

    def setUp(self) -> None:
        self.tracked_identity = load_pair_identity()
        self.provider = self._provider()
        selected = self.tracked_identity.require_selected_profile()
        self.identity = replace(
            self.tracked_identity,
            selected_profile=replace(
                selected,
                provider_public=self.provider.to_public_dict(),
            ),
        )

    def _provider(
        self,
        *,
        base_url: str = "https://provider.example/v1",
        config_sha256: str = "a" * 64,
    ) -> ProviderProjection:
        pricing = ModelPricing(
            model_id="gpt-5.6-sol",
            input_usd_per_million=Decimal("5"),
            cached_input_usd_per_million=Decimal("0.5"),
            output_usd_per_million=Decimal("30"),
            long_context_threshold_tokens=272_000,
            long_context_input_multiplier=Decimal("2"),
            long_context_output_multiplier=Decimal("1.5"),
            cache_write_input_multiplier=Decimal("1.25"),
            price_snapshot_date="2026-08-11",
            price_source_url="https://developers.openai.com/api/docs/models/gpt-5.6-sol",
        )
        return ProviderProjection(
            provider_id="test",
            display_name="Test provider",
            api="responses",
            base_url=base_url,
            api_key_env="TEST_API_KEY",
            main_model=pricing.model_id,
            main_effort="medium",
            guardian_model=pricing.model_id,
            guardian_effort="low",
            main_pricing=pricing,
            guardian_pricing=pricing,
            max_attempts=5,
            retry_backoff_seconds=1.0,
            unbilled_retry_statuses=(429, 500, 502, 503, 504),
            profile_sha256="d" * 64,
            config_sha256=config_sha256,
        )

    def _manifest(self, side: Side) -> BinaryManifest:
        bundle = self.identity.bundles[side]
        return BinaryManifest(
            path="/tmp/codex",
            sha256=bundle.cli_sha256,
            code_mode_host_path="/tmp/codex-code-mode-host",
            code_mode_host_sha256=bundle.code_mode_host_sha256,
            bwrap_path="/tmp/codex-resources/bwrap",
            bwrap_sha256=bundle.bwrap_sha256,
            bwrap_asset_url=(
                "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
                "bwrap-x86_64-unknown-linux-musl.tar.gz"
            ),
            bwrap_archive_sha256="1" * 64,
            bwrap_source_tree_sha256="2" * 64,
            source_commit=bundle.source_commit,
            source_dirty=False,
            rust_toolchain="rustc 1.95.0",
            build_command=("guarded-build",),
            code_mode_host_build_command=("guarded-host-build",),
            workspace_lock_normalization=bundle.workspace_lock_normalization,
        )

    def _spec(
        self,
        side: Side,
        *,
        base_url: str = "https://provider.example/v1",
        config_sha256: str = "a" * 64,
    ) -> RunSpec:
        fair = self.identity.fairness
        return RunSpec(
            side=side,
            batch_id=pair_module.B2_NO_API_BATCH_ID,
            task_id=fair["task_id"],
            task_image_digest=fair["task_image_digest"],
            binary=self._manifest(side),
            terminal_bench_version=fair["terminal_bench_version"],
            provider=self._provider(base_url=base_url, config_sha256=config_sha256),
            timeout_seconds=fair["timeout_seconds"],
            max_retries=fair["max_retries"],
            budget_usd=fair["budget_usd"],
        )

    def _record(self, side: Side, created_at: str) -> dict[str, object]:
        slot = self.identity.slot_for(side)
        fair = self.identity.fairness
        config = {
            **self.identity.require_selected_profile().to_dict(),
            "pair_id": self.identity.pair_id,
            "pair_lock_sha256": self.identity.lock_sha256,
            "pair_slot": slot.slot,
            "pair_round": slot.round,
            "eval_harness_commit": self.HARNESS_COMMIT,
            "approvals_reviewer": fair["approvals_reviewer"],
            "approval_policy": fair["approval_policy"],
            "sandbox_mode": fair["sandbox_mode"],
            "sandbox_network_access": fair["sandbox_network_access"],
            "websocket": fair["websocket"],
            "code_mode_host": fair["code_mode_host"],
            "terminal_bench_version": fair["terminal_bench_version"],
            "task_image_digest": fair["task_image_digest"],
            "timeout_seconds": fair["timeout_seconds"],
            "max_retries": fair["max_retries"],
            "budget_usd": fair["budget_usd"],
        }
        return {
            "run_id": f"tb-{side.value}-run",
            "side": side.value,
            "created_at": created_at,
            "outcome": "completed",
            "git_dirty": False,
            "binary_sha256": self.identity.bundles[side].cli_sha256,
            "config": config,
            "summary": {
                "metadata_ready": True,
                "api_request_roles": {"main": 2, "guardian": 1},
                "api_request_sequence": ["main", "guardian", "main"],
                "evidence": [{"relative_path": "e"}] if side is Side.RONDO else [],
                "s2_request_evidence_binding": "verified" if side is Side.RONDO else "not_triggered",
            },
            "metrics": {
                "wall_seconds": 1.0,
                "cpu_user_seconds": 0.5,
                "cpu_system_seconds": 0.25,
                "peak_rss_bytes": 4096,
                "exit_code": 0,
            },
            "artifacts": f"eval-data/runs/{side.value}",
        }

    def _paid_identity(self):
        modes = dict(self.identity.modes)
        modes["paid"] = pair_module.PairMode(True, "paid-batch")
        topology = tuple(
            replace(slot, paid_run_id=f"tb-{slot.side.value}-run")
            for slot in self.identity.topology
        )
        return replace(self.identity, modes=modes, topology=topology)

    @staticmethod
    def _container_metrics(side: Side) -> dict[str, object]:
        return {
            "container_id": ("a" if side is Side.RONDO else "b") * 64,
            "cpu_usage_seconds": 1.25,
            "peak_memory_bytes": 4096,
        }

    def test_tracked_lock_freezes_one_paid_round_per_side(self) -> None:
        identity = self.tracked_identity
        self.assertNotIn("no_api", identity.modes)
        profile = identity.validate_no_api_seccomp(project_root=EVAL_ROOT.parent)
        self.assertEqual(
            hashlib.sha256(profile.read_bytes()).hexdigest(),
            identity.no_api_seccomp.source_sha256,
        )
        paid = identity.mode("paid")
        self.assertEqual(identity.pair_id, "p1-fix-git-pair-v19")
        self.assertEqual(paid.batch_id, "p1-fix-git-b4-m1-v11")
        self.assertEqual(
            [slot.paid_run_id for slot in identity.topology],
            [
                "20260811-190000000-tb-rondo-r1",
                "20260811-190000001-tb-codex-r1",
            ],
        )
        selected = identity.require_selected_profile().to_dict()
        self.assertNotIn("provider_base_url", selected)
        self.assertNotIn("provider_api_key_env", selected)
        self.assertEqual(selected["requested_guardian_model"], "gpt-5.6-sol")
        self.assertEqual(selected["max_guardian_logical_requests"], 3)
        self.assertEqual(identity.fairness["max_retries"], 0)
        self.assertEqual(identity.fairness["budget_usd"], 10.0)
        self.assertEqual(identity.paid_budget.per_side_usd, 10.0)
        self.assertEqual(identity.paid_budget.pair_usd, 20.0)
        identity.validate_frozen_model_catalog(
            source_commit=selected["frozen_codex_model_catalog_source_commit"],
            sha256=selected["frozen_codex_model_catalog_sha256"],
            main_model=selected["effective_main_model"],
            guardian_model=selected["effective_guardian_model"],
        )
        with self.assertRaisesRegex(PairIdentityError, "catalog drifted"):
            identity.validate_frozen_model_catalog(
                source_commit=selected["frozen_codex_model_catalog_source_commit"],
                sha256="0" * 64,
                main_model=selected["effective_main_model"],
                guardian_model=selected["effective_guardian_model"],
            )
        validate_harbor_installation(
            identity,
            executable=HARBOR_EXECUTABLE,
        )

    def test_legacy_v8_identity_is_explicit_and_read_only(self) -> None:
        legacy = load_legacy_pair_identity()
        self.assertEqual(legacy.pair_id, "p1-fix-git-pair-v8")
        self.assertNotEqual(legacy.pair_id, self.tracked_identity.pair_id)
        self.assertNotEqual(
            legacy.mode("paid").batch_id,
            self.tracked_identity.mode("paid").batch_id,
        )
        self.assertTrue(
            {slot.paid_run_id for slot in legacy.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "schema v2"):
            load_pair_identity(pair_module.LEGACY_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "legacy.json",
                identity=legacy,
                mode="paid",
            )

    def test_codex_install_failed_v18_identity_is_explicit_and_read_only(self) -> None:
        previous = load_previous_pair_identity()
        self.assertEqual(previous.pair_id, "p1-fix-git-pair-v18")
        self.assertNotEqual(previous.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in previous.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.PREVIOUS_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "previous.json",
                identity=previous,
                mode="paid",
            )

    def test_docker_failed_v17_identity_remains_read_only(self) -> None:
        consumed = load_consumed_v17_pair_identity()
        self.assertEqual(consumed.pair_id, "p1-fix-git-pair-v17")
        self.assertNotEqual(consumed.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in consumed.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.CONSUMED_V17_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "consumed-v17.json",
                identity=consumed,
                mode="paid",
            )

    def test_publication_failed_v16_identity_remains_read_only(self) -> None:
        consumed = load_consumed_v16_pair_identity()
        self.assertEqual(consumed.pair_id, "p1-fix-git-pair-v16")
        self.assertNotEqual(consumed.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in consumed.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.CONSUMED_V16_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "consumed-v16.json",
                identity=consumed,
                mode="paid",
            )

    def test_third_approval_failed_v15_identity_remains_read_only(self) -> None:
        consumed = load_consumed_v15_pair_identity()
        self.assertEqual(consumed.pair_id, "p1-fix-git-pair-v15")
        self.assertNotEqual(consumed.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in consumed.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.CONSUMED_V15_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "consumed-v15.json",
                identity=consumed,
                mode="paid",
            )

    def test_second_approval_failed_v14_identity_remains_read_only(self) -> None:
        consumed = load_consumed_v14_pair_identity()
        self.assertEqual(consumed.pair_id, "p1-fix-git-pair-v14")
        self.assertNotEqual(consumed.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in consumed.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.CONSUMED_V14_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "consumed-v14.json",
                identity=consumed,
                mode="paid",
            )

    def test_guardian_failed_v13_identity_remains_read_only(self) -> None:
        consumed = load_consumed_v13_pair_identity()
        self.assertEqual(consumed.pair_id, "p1-fix-git-pair-v13")
        self.assertNotEqual(consumed.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in consumed.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.CONSUMED_V13_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "consumed-v13.json",
                identity=consumed,
                mode="paid",
            )

    def test_canary_failed_v12_identity_remains_read_only(self) -> None:
        consumed = load_consumed_v12_pair_identity()
        self.assertEqual(consumed.pair_id, "p1-fix-git-pair-v12")
        self.assertNotEqual(consumed.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in consumed.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.CONSUMED_V12_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "consumed-v12.json",
                identity=consumed,
                mode="paid",
            )

    def test_preflight_failed_v11_identity_remains_read_only(self) -> None:
        consumed = load_consumed_v11_pair_identity()
        self.assertEqual(consumed.pair_id, "p1-fix-git-pair-v11")
        self.assertNotEqual(consumed.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in consumed.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.CONSUMED_V11_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "consumed-v11.json",
                identity=consumed,
                mode="paid",
            )

    def test_consumed_v10_identity_remains_explicit_and_read_only(self) -> None:
        consumed = load_consumed_v10_pair_identity()
        self.assertEqual(consumed.pair_id, "p1-fix-git-pair-v10")
        self.assertNotEqual(consumed.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in consumed.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.CONSUMED_V10_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "consumed-v10.json",
                identity=consumed,
                mode="paid",
            )

    def test_consumed_v9_identity_remains_explicit_and_read_only(self) -> None:
        consumed = load_consumed_v9_pair_identity()
        self.assertEqual(consumed.pair_id, "p1-fix-git-pair-v9")
        self.assertNotEqual(consumed.pair_id, self.tracked_identity.pair_id)
        self.assertTrue(
            {slot.paid_run_id for slot in consumed.topology}.isdisjoint(
                slot.paid_run_id for slot in self.tracked_identity.topology
            )
        )
        with self.assertRaisesRegex(PairIdentityError, "identity differs"):
            load_pair_identity(pair_module.CONSUMED_V9_PAIR_LOCK_PATH)
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(
            PairIdentityError, "read-only"
        ):
            PairSequenceLedger(
                Path(directory) / "consumed-v9.json",
                identity=consumed,
                mode="paid",
            )

    def test_shared_fair_pair_gate_rejects_runtime_drift(self) -> None:
        self.identity.validate_spec(self._spec(Side.CODEX), mode="no_api")
        self.identity.validate_spec(
            self._spec(Side.CODEX, base_url="https://another.example/v1"),
            mode="no_api",
        )
        drifted = replace(self._spec(Side.RONDO), timeout_seconds=900)
        with self.assertRaisesRegex(PairIdentityError, "fairness"):
            self.identity.validate_spec(drifted, mode="no_api")

    def test_sequence_binds_profile_at_slot_one_and_rejects_slot_two_drift(self) -> None:
        identity = self._paid_identity()
        rondo_record = self._record(Side.RONDO, "2026-08-11T01:00:00Z")
        drifted_provider = self._provider(base_url="https://drift.example/v1")
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "paid.json"
            with PairSequenceLedger(
                ledger_path, identity=identity, mode="paid"
            ) as sequence:
                sequence.claim(
                    side=Side.RONDO,
                    run_id="tb-rondo-run",
                    eval_harness_commit=self.HARNESS_COMMIT,
                    provider=self.provider,
                )
                sequence.finish(
                    run_id="tb-rondo-run",
                    completed=True,
                    eval_harness_commit=self.HARNESS_COMMIT,
                    publication_sha256=terminal_record_sha256(rondo_record),
                    container_metrics=self._container_metrics(Side.RONDO),
                    provider=self.provider,
                )
                with self.assertRaisesRegex(PairIdentityError, "drifted"):
                    sequence.claim(
                        side=Side.CODEX,
                        run_id="tb-codex-run",
                        eval_harness_commit=self.HARNESS_COMMIT,
                        provider=drifted_provider,
                    )
                snapshot = sequence.snapshot()
            self.assertEqual(snapshot["selected_profile_sha256"], "d" * 64)
            self.assertEqual(len(snapshot["runs"]), 1)

    @unittest.skipUnless(hasattr(os, "fork"), "requires POSIX process death injection")
    def test_paid_publication_reconciles_after_process_restart(self) -> None:
        paid_identity = self._paid_identity()
        record = self._record(Side.RONDO, "2026-08-10T01:00:00Z")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger_path = root / "paid.json"
            index_path = root / "runs.jsonl"
            child = os.fork()
            if child == 0:
                with PairSequenceLedger(
                    ledger_path, identity=paid_identity, mode="paid"
                ) as sequence:
                    sequence.claim(
                        side=Side.RONDO,
                        run_id=record["run_id"],
                        eval_harness_commit=self.HARNESS_COMMIT,
                        provider=self.provider,
                    )
                    sequence.stage_paid_publication(
                        run_id=record["run_id"],
                        eval_harness_commit=self.HARNESS_COMMIT,
                        container_metrics=self._container_metrics(Side.RONDO),
                        provider=self.provider,
                    )
                with index_path.open("w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(record, sort_keys=True, separators=(",", ":"))
                        + "\n"
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                os._exit(77)
            _pid, status = os.waitpid(child, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 77)
            with PairSequenceLedger(
                ledger_path, identity=paid_identity, mode="paid"
            ) as sequence:
                digest = sequence.reconcile_paid_publication(
                    run_id=record["run_id"],
                    eval_harness_commit=self.HARNESS_COMMIT,
                    index_path=index_path,
                    provider=self.provider,
                )
            state = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(state["runs"][0]["status"], "completed")
            self.assertEqual(digest, terminal_record_sha256(record))

    def test_m1_accepts_real_multi_turn_approval_chain(self) -> None:
        records = [
            self._record(Side.RONDO, "2026-08-10T01:00:00Z"),
            self._record(Side.CODEX, "2026-08-10T02:00:00Z"),
        ]
        for record in records:
            record["summary"]["api_request_roles"] = {"main": 4, "guardian": 1}
            record["summary"]["api_request_sequence"] = [
                "main",
                "main",
                "guardian",
                "main",
                "main",
            ]
        paid_identity = self._paid_identity()
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "paid.json"
            with PairSequenceLedger(
                ledger_path, identity=paid_identity, mode="paid"
            ) as sequence:
                for side, record in zip((Side.RONDO, Side.CODEX), records, strict=True):
                    sequence.claim(
                        side=side,
                        run_id=record["run_id"],
                        eval_harness_commit=self.HARNESS_COMMIT,
                        provider=self.provider,
                    )
                    sequence.finish(
                        run_id=record["run_id"],
                        completed=True,
                        eval_harness_commit=self.HARNESS_COMMIT,
                        publication_sha256=terminal_record_sha256(record),
                        container_metrics=self._container_metrics(side),
                        provider=self.provider,
                    )
            result = assess_m1(
                records, paid_identity, pair_ledger_path=ledger_path
            )
            self.assertEqual(result["m1"], "passed")
            self.assertEqual(result["s2"], "verified")
            self.assertEqual(result["reasons"], [])

            provider_drift = json.loads(json.dumps(records))
            provider_drift[1]["config"]["provider_endpoint_sha256"] = "f" * 64
            drifted = assess_m1(
                provider_drift, paid_identity, pair_ledger_path=ledger_path
            )
            self.assertEqual(drifted["m1"], "failed")
            self.assertIn("pair_selected_profile_mismatch", drifted["reasons"])
            self.assertIn("pair_selected_profile_lock_mismatch", drifted["reasons"])

            effort_drift = json.loads(json.dumps(records))
            effort_drift[1]["config"]["main_effort"] = "high"
            effort_result = assess_m1(
                effort_drift, paid_identity, pair_ledger_path=ledger_path
            )
            self.assertIn("pair_selected_profile_mismatch", effort_result["reasons"])

            incomplete_approval = json.loads(json.dumps(records))
            incomplete_approval[1]["summary"]["api_request_roles"] = {
                "main": 1,
                "guardian": 0,
            }
            incomplete_approval[1]["summary"]["api_request_sequence"] = ["main"]
            approval_result = assess_m1(
                incomplete_approval, paid_identity, pair_ledger_path=ledger_path
            )
            self.assertIn(
                "codex_guardian_approval_incomplete", approval_result["reasons"]
            )

            split = json.loads(ledger_path.read_text(encoding="utf-8"))
            split["runs"][1]["status"] = "publishing"
            split["runs"][1]["publication_sha256"] = None
            split["next_slot"] = 2
            ledger_path.write_text(
                json.dumps(split, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            not_converged = assess_m1(
                records, paid_identity, pair_ledger_path=ledger_path
            )
            self.assertEqual(not_converged["m1"], "failed")
            self.assertIn("paid_pair_ledger_not_completed", not_converged["reasons"])

            duplicate = assess_m1(
                [*records, records[1]],
                paid_identity,
                pair_ledger_path=ledger_path,
            )
            self.assertEqual(duplicate["m1"], "incomplete")
            self.assertIn("exactly_two", duplicate["reasons"][0])

    def test_approval_sequence_requires_one_bracketed_guardian(self) -> None:
        self.assertTrue(
            has_complete_guardian_approval_sequence(
                ["main", "main", "guardian", "main", "main"]
            )
        )
        self.assertTrue(
            has_complete_guardian_approval_sequence(
                ["main", "guardian", "main", "guardian", "main"]
            )
        )
        for sequence in (
            ["guardian", "main"],
            ["main", "guardian"],
            ["main", "guardian", "guardian", "main"],
            ["main", "main", "main"],
        ):
            self.assertFalse(has_complete_guardian_approval_sequence(sequence))

class RunnerMetricsTests(unittest.TestCase):
    def test_runner_timer_records_fixed_runner_host_shape(self) -> None:
        usages = iter(
            (
                SimpleNamespace(ru_utime=1.0, ru_stime=2.0, ru_maxrss=100),
                SimpleNamespace(ru_utime=3.0, ru_stime=4.0, ru_maxrss=200),
                SimpleNamespace(ru_utime=2.5, ru_stime=3.5, ru_maxrss=300),
                SimpleNamespace(ru_utime=5.5, ru_stime=6.5, ru_maxrss=400),
            )
        )
        times = iter((10.0, 12.5))
        timer = RunnerMetricsTimer(
            monotonic=lambda: next(times),
            getrusage=lambda _scope: next(usages),
        )
        value = timer.snapshot(exit_code=70).to_dict()
        self.assertEqual(value["wall_seconds"], 2.5)
        self.assertEqual(value["cpu_user_seconds"], 4.0)
        self.assertEqual(value["cpu_system_seconds"], 4.0)
        self.assertEqual(value["exit_code"], 70)
        self.assertGreater(value["peak_rss_bytes"], 0)
        self.assertEqual(metrics_from_dict(value).exit_code, 70)


if __name__ == "__main__":
    unittest.main()
