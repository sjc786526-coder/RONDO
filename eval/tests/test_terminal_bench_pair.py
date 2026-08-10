from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import (  # noqa: E402
    BinaryManifest,
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
    load_pair_identity,
    terminal_record_sha256,
    validate_harbor_installation,
)
from rondo_eval.terminal_bench.runner import HARBOR_EXECUTABLE  # noqa: E402


class PairIdentityTests(unittest.TestCase):
    HARNESS_COMMIT = "f" * 40

    def setUp(self) -> None:
        self.identity = load_pair_identity()

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

    def _spec(self, side: Side) -> RunSpec:
        fair = self.identity.fairness
        return RunSpec(
            side=side,
            batch_id=pair_module.B2_NO_API_BATCH_ID,
            task_id=fair["task_id"],
            task_image_digest=fair["task_image_digest"],
            binary=self._manifest(side),
            terminal_bench_version=fair["terminal_bench_version"],
            provider=ProviderProjection(
                provider_id=fair["provider_id"],
                api=fair["provider_api"],
                base_url=fair["provider_base_url"],
                api_key_env=fair["provider_api_key_env"],
                main_model=fair["main_model"],
                guardian_model=fair["guardian_model"],
                guardian_effort=fair["guardian_effort"],
                config_sha256="a" * 64,
            ),
            timeout_seconds=fair["timeout_seconds"],
            max_retries=fair["max_retries"],
            budget_usd=fair["budget_usd"],
        )

    def _record(self, side: Side, created_at: str) -> dict[str, object]:
        slot = self.identity.slot_for(side)
        fair = self.identity.fairness
        config = {
            "pair_id": self.identity.pair_id,
            "pair_lock_sha256": self.identity.lock_sha256,
            "pair_slot": slot.slot,
            "pair_round": slot.round,
            "eval_harness_commit": self.HARNESS_COMMIT,
            "main_model": fair["main_model"],
            "guardian_model": fair["guardian_model"],
            "guardian_effort": fair["guardian_effort"],
            "provider": fair["provider_id"],
            "provider_api": fair["provider_api"],
            "provider_base_url": fair["provider_base_url"],
            "provider_api_key_env": fair["provider_api_key_env"],
            "provider_config_sha256": "c" * 64,
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
                "api_request_roles": {"main": 1, "guardian": 1 if side is Side.RONDO else 0},
                "evidence": [{"relative_path": "e"}] if side is Side.RONDO else [],
                "s2_request_evidence_binding": "unbound" if side is Side.RONDO else "not_triggered",
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

    def test_tracked_lock_keeps_no_api_lightweight_and_paid_disabled(self) -> None:
        self.assertNotIn("no_api", self.identity.modes)
        profile = self.identity.validate_no_api_seccomp(project_root=EVAL_ROOT.parent)
        self.assertEqual(
            hashlib.sha256(profile.read_bytes()).hexdigest(),
            self.identity.no_api_seccomp.source_sha256,
        )
        with self.assertRaisesRegex(PairIdentityError, "fresh_pair"):
            self.identity.mode("paid")
        validate_harbor_installation(
            self.identity,
            executable=HARBOR_EXECUTABLE,
        )

    def test_shared_fair_pair_gate_rejects_runtime_drift(self) -> None:
        self.identity.validate_spec(self._spec(Side.CODEX), mode="no_api")
        drifted = replace(self._spec(Side.RONDO), timeout_seconds=900)
        with self.assertRaisesRegex(PairIdentityError, "fairness"):
            self.identity.validate_spec(drifted, mode="no_api")

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
                    )
                    sequence.stage_paid_publication(
                        run_id=record["run_id"],
                        eval_harness_commit=self.HARNESS_COMMIT,
                        container_metrics=self._container_metrics(Side.RONDO),
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
                )
            state = json.loads(ledger_path.read_text(encoding="utf-8"))
            self.assertEqual(state["runs"][0]["status"], "completed")
            self.assertEqual(digest, terminal_record_sha256(record))

    def test_m1_pair_aggregation_keeps_s2_independent(self) -> None:
        records = [
            self._record(Side.RONDO, "2026-08-10T01:00:00Z"),
            self._record(Side.CODEX, "2026-08-10T02:00:00Z"),
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
                    )
                    sequence.finish(
                        run_id=record["run_id"],
                        completed=True,
                        eval_harness_commit=self.HARNESS_COMMIT,
                        publication_sha256=terminal_record_sha256(record),
                        container_metrics=self._container_metrics(side),
                    )
            result = assess_m1(
                records, paid_identity, pair_ledger_path=ledger_path
            )
            self.assertEqual(result["m1"], "passed")
            self.assertEqual(result["s2"], "unbound")
            self.assertEqual(result["reasons"], [])

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
