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
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import (  # noqa: E402
    BinaryManifest,
    ProviderProjection,
    RunSpec,
    Side,
)
from rondo_eval.terminal_bench import pair as pair_module  # noqa: E402
from rondo_eval.terminal_bench.metrics import (  # noqa: E402
    ExternalRunMetrics,
    RunnerMetricsTimer,
    metrics_from_dict,
)
from rondo_eval.terminal_bench.pair import (  # noqa: E402
    PairSequenceLedger,
    PairIdentityError,
    assess_m1,
    load_pair_identity,
    validate_harbor_installation,
)
from rondo_eval.terminal_bench.runner import HARBOR_EXECUTABLE  # noqa: E402


class PairIdentityTests(unittest.TestCase):
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
            batch_id="p1-no-api-smoke",
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

    def test_tracked_lock_enables_no_api_and_hard_disables_paid(self) -> None:
        self.assertEqual(self.identity.mode("no_api").batch_id, "p1-no-api-smoke")
        profile = self.identity.validate_no_api_seccomp(project_root=EVAL_ROOT.parent)
        self.assertEqual(
            hashlib.sha256(profile.read_bytes()).hexdigest(),
            self.identity.no_api_seccomp.source_sha256,
        )
        with self.assertRaisesRegex(PairIdentityError, "fresh_pair"):
            self.identity.mode("paid")

    def test_current_frozen_harbor_install_matches_pair_lock(self) -> None:
        validate_harbor_installation(
            self.identity,
            executable=HARBOR_EXECUTABLE,
        )

    def test_shared_fair_pair_gate_rejects_runtime_drift(self) -> None:
        self.identity.validate_spec(self._spec(Side.CODEX), mode="no_api")
        drifted = replace(self._spec(Side.RONDO), timeout_seconds=900)
        with self.assertRaisesRegex(PairIdentityError, "fairness"):
            self.identity.validate_spec(drifted, mode="no_api")

    def test_persistent_sequence_enforces_rondo_then_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pair.json"
            with PairSequenceLedger(
                path, identity=self.identity, mode="no_api"
            ) as sequence:
                with self.assertRaisesRegex(PairIdentityError, "slot order"):
                    sequence.claim(side=Side.CODEX, run_id="codex-first")
                sequence.claim(side=Side.RONDO, run_id="rondo-slot")
                sequence.finish(run_id="rondo-slot", completed=True)
            with PairSequenceLedger(
                path, identity=self.identity, mode="no_api"
            ) as sequence:
                sequence.claim(side=Side.CODEX, run_id="codex-slot")
                sequence.finish(run_id="codex-slot", completed=True)
            state = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(state["next_slot"], 3)
            self.assertEqual(
                [item["side"] for item in state["runs"]], ["rondo", "codex"]
            )

    def test_m1_pair_aggregation_keeps_s2_independent(self) -> None:
        records = [
            self._record(Side.RONDO, "2026-08-10T01:00:00Z"),
            self._record(Side.CODEX, "2026-08-10T02:00:00Z"),
        ]
        result = assess_m1(records, self.identity)
        self.assertEqual(result["m1"], "passed")
        self.assertEqual(result["s2"], "unbound")
        self.assertEqual(result["reasons"], [])

        duplicate = assess_m1([*records, records[1]], self.identity)
        self.assertEqual(duplicate["m1"], "incomplete")
        self.assertIn("exactly_two", duplicate["reasons"][0])

    def test_harbor_preflight_binds_closure_and_console_interpreter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "harbor"
            executable.write_text(
                f"#!{sys.executable}\nfrom harbor.cli.main import app\napp()\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            distribution = SimpleNamespace(version="0.20.0")
            with mock.patch.object(
                pair_module,
                "_installed_harbor_closure",
                return_value=(
                    self.identity.harbor.installed_closure_sha256,
                    self.identity.harbor.installed_closure_files,
                ),
            ):
                validate_harbor_installation(
                    self.identity,
                    executable=executable,
                    distribution=distribution,
                )
            executable.write_text(f"#!{sys.executable}\nprint('wrong')\n", encoding="utf-8")
            with mock.patch.object(
                pair_module,
                "_installed_harbor_closure",
                return_value=(
                    self.identity.harbor.installed_closure_sha256,
                    self.identity.harbor.installed_closure_files,
                ),
            ), self.assertRaisesRegex(PairIdentityError, "entry point"):
                validate_harbor_installation(
                    self.identity,
                    executable=executable,
                    distribution=distribution,
                )


class RunnerMetricsTests(unittest.TestCase):
    def test_runner_timer_records_fixed_process_tree_shape(self) -> None:
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
