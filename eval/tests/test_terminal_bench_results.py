from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.config import RepoPaths  # noqa: E402
from rondo_eval.artifacts import ArtifactError, ArtifactWriter  # noqa: E402
from rondo_eval import artifacts as artifacts_module  # noqa: E402
from rondo_eval.contracts import (  # noqa: E402
    BinaryManifest,
    ModelPricing,
    ProviderProjection,
    RunOutcome,
    RunSpec,
    Side,
)
from rondo_eval.docker_supervisor import DockerSupervisionError  # noqa: E402
from rondo_eval.runtime_bridge import RuntimeBridgeError  # noqa: E402
from rondo_eval.terminal_bench.live import (  # noqa: E402
    BudgetedTerminalBenchResult,
    load_guardian_evidence_bundle,
)
from rondo_eval.terminal_bench import __main__ as terminal_bench_main  # noqa: E402
from rondo_eval.terminal_bench.pair import (  # noqa: E402
    CampaignPublicationContext,
    PairMode,
    PairSequenceLedger,
    RunPublicationContext,
    assess_m1,
    load_historical_pair_identity,
    terminal_record_sha256,
)
from rondo_eval.terminal_bench.results import (  # noqa: E402
    HarborResultError,
    UPSTREAM_CODEX,
    classify_terminal_bench_result,
    parse_single_task_result,
    publish_terminal_bench_failure,
    publish_terminal_bench_result,
)
from rondo_eval.terminal_bench.runner import (  # noqa: E402
    HostHarborResult,
    TerminalBenchRunError,
)


class TerminalBenchResultTests(unittest.TestCase):
    PAID_BATCH_ID = "test-active-paid-batch"

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.trial = self.root / "work" / "staging" / "trials" / "rondo-p1-codex-abc"
        # Kept as a compatibility variable for APIs whose old parameter name
        # was jobs_dir; it now denotes the exact single-trial root.
        self.jobs = self.trial
        self.job = self.root / "work" / "unpublished-job-fixture"
        self.trial.mkdir(parents=True)
        self.job.mkdir(parents=True)
        self.job_result = {
            "n_total_trials": 1,
            "stats": {
                "n_completed_trials": 1,
                "n_errored_trials": 0,
                "n_running_trials": 0,
                "n_pending_trials": 0,
                "n_cancelled_trials": 0,
                "n_retries": 0,
            },
        }
        self.trial_result = {
            "trial_name": self.trial.name,
            "task_name": "terminal-bench/fix-git",
            "agent_result": {
                "n_input_tokens": 100,
                "n_cache_tokens": 20,
                "n_output_tokens": 10,
            },
            "verifier_result": {"rewards": {"reward": 1.0}},
            "exception_info": None,
            "started_at": "2026-08-10T01:00:00Z",
            "finished_at": "2026-08-10T01:00:05Z",
        }
        self._write_results()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_results(self) -> None:
        (self.trial / "result.json").write_text(json.dumps(self.trial_result), encoding="utf-8")
        (self.job / "job.log").write_text("safe log\n", encoding="utf-8")
        (self.job / "config.json").write_text("{}\n", encoding="utf-8")

    def _publication(
        self, *, side: Side = Side.CODEX, exit_code: int = 0
    ) -> RunPublicationContext:
        provider = self._live_result("publication-fixture").prepared.spec.provider
        return RunPublicationContext(
            pair_id="p1-fix-git-pair-v19",
            pair_lock_sha256="9" * 64,
            pair_slot=1 if side is Side.RONDO else 2,
            pair_round=1,
            metrics={
                "wall_seconds": 1.25,
                "cpu_user_seconds": 0.5,
                "cpu_system_seconds": 0.25,
                "peak_rss_bytes": 1024,
                "exit_code": exit_code,
            },
            selected_profile={
                **provider.to_public_dict(),
                "frozen_codex_model_catalog_source_commit": "a" * 40,
                "frozen_codex_model_catalog_sha256": "b" * 64,
                "max_guardian_logical_requests": 2,
            },
        )

    @staticmethod
    def _write_metadata(
        path: Path,
        *roles: str,
        provenance: str = "declared",
        guardian_digests: tuple[str, ...] = (),
    ) -> None:
        guardian_index = 0
        requests = []
        for index, role in enumerate(roles):
            digest = f"{index + 1:064x}"
            if role == "guardian" and guardian_index < len(guardian_digests):
                digest = guardian_digests[guardian_index]
                guardian_index += 1
            requests.append(
                {
                    "request_id": f"request-{index}",
                    "role": role,
                    "role_provenance": provenance,
                    "declared_role": role if provenance == "declared" else None,
                    "inferred_role": role,
                    "contract_match": True,
                    "usage_valid": True,
                    "canonical_body_sha256": digest,
                }
            )
        if guardian_index != len(guardian_digests):
            raise AssertionError("unused Guardian request digest fixture")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "requests": requests,
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _live_result(self, run_id: str) -> BudgetedTerminalBenchResult:
        binary = BinaryManifest(
            path=str(self.root / "codex"),
            sha256="a" * 64,
            code_mode_host_path=str(self.root / "codex-code-mode-host"),
            code_mode_host_sha256="e" * 64,
            bwrap_path=str(self.root / "codex-resources" / "bwrap"),
            bwrap_sha256="f" * 64,
            bwrap_asset_url=(
                "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
                "bwrap-x86_64-unknown-linux-musl.tar.gz"
            ),
            bwrap_archive_sha256="1" * 64,
            bwrap_source_tree_sha256="2" * 64,
            source_commit=UPSTREAM_CODEX["commit"],
            source_dirty=False,
            rust_toolchain="rustc 1.95.0",
            build_command=("supervised", "build"),
            code_mode_host_build_command=("supervised", "build-code-mode-host"),
            workspace_lock_normalization=UPSTREAM_CODEX["workspace_lock_normalization"],
        )
        main_pricing = ModelPricing(
            model_id="gpt-5.6-sol",
            input_usd_per_million=Decimal("5"),
            cached_input_usd_per_million=Decimal("0.5"),
            output_usd_per_million=Decimal("30"),
            long_context_threshold_tokens=272_000,
            long_context_input_multiplier=Decimal("2"),
            long_context_output_multiplier=Decimal("1.5"),
            cache_write_input_multiplier=Decimal("1.25"),
            price_snapshot_date="2026-08-10",
            price_source_url="https://developers.openai.com/api/docs/models/compare",
        )
        guardian_pricing = ModelPricing(
            model_id="gpt-5.6-luna",
            input_usd_per_million=Decimal("0.2"),
            cached_input_usd_per_million=Decimal("0.02"),
            output_usd_per_million=Decimal("1.2"),
            long_context_threshold_tokens=272_000,
            long_context_input_multiplier=Decimal("2"),
            long_context_output_multiplier=Decimal("1.5"),
            cache_write_input_multiplier=Decimal("1.25"),
            price_snapshot_date="2026-08-10",
            price_source_url="https://developers.openai.com/api/docs/models/compare",
        )
        provider = ProviderProjection(
            provider_id="openai",
            display_name="Test provider",
            api="responses",
            base_url="https://provider.example/v1",
            api_key_env="OPENAI_API_KEY",
            main_model="gpt-5.6-sol",
            main_effort="medium",
            guardian_model="gpt-5.6-luna",
            guardian_effort="low",
            main_pricing=main_pricing,
            guardian_pricing=guardian_pricing,
            max_attempts=5,
            retry_backoff_seconds=1.0,
            unbilled_retry_statuses=(429, 500, 502, 503, 504),
            profile_sha256="d" * 64,
            config_sha256="b" * 64,
        )
        spec = RunSpec(
            side=Side.CODEX,
            batch_id="p1-b3",
            task_id="terminal-bench/fix-git",
            task_image_digest="sha256:" + "c" * 64,
            binary=binary,
            terminal_bench_version="terminal-bench-2-1@" + "d" * 40,
            provider=provider,
        )
        prepared = SimpleNamespace(spec=spec)
        return BudgetedTerminalBenchResult(
            prepared=prepared,
            harbor=HostHarborResult(0, self.jobs),
            budget_snapshot=self._completed_budget_snapshot(run_id, request_count=3),
            metadata_ready=True,
            evidence=(),
            redaction_secrets=("never-persist", "temporary-token"),
        )

    @staticmethod
    def _completed_budget_snapshot(run_id: str, *, request_count: int) -> dict:
        return {
            "runs": {
                run_id: {
                    "cap_usd": "10.000000",
                    "spent_usd": "0.012345",
                    "stopped": False,
                    "stop_reason": None,
                    "requests": {
                        f"request-{index}": {
                            "status": "settled",
                            "reserved_usd": "5.000000",
                            "charged_usd": "0.012345" if index == 0 else "0.000000",
                            "usage_valid": True,
                            "attempt_count": 1,
                            "settlement_kind": "usage_priced",
                        }
                        for index in range(request_count)
                    },
                }
            }
        }

    def _write_guardian_bundle(
        self,
        review_id: str = "review-1",
        *,
        decision: str = "approved",
        terminal_status: str = "approved",
        failure_reason: str | None = None,
    ) -> str:
        bundle = self.trial / "agent" / "guardian-evidence" / review_id
        bundle.mkdir(parents=True)
        (bundle / "E_final.json").write_text(
            json.dumps(
                {
                    "instructions": "frozen guardian policy",
                    "input": [
                        {
                            "role": "user",
                            "content": f"approval evidence {review_id}",
                        }
                    ],
                    "text": {
                        "format": {
                            "schema": {
                                "properties": {
                                    "user_authorization": {
                                        "type": "string",
                                        "enum": ["unknown", "low", "medium", "high"],
                                    }
                                }
                            }
                        }
                    },
                    "tools": [],
                }
            ),
            encoding="utf-8",
        )
        meta = {
            "review_id": review_id,
            "guardian_source_baseline": "rust-v0.147.0",
            "guardian_source_commit": UPSTREAM_CODEX["commit"],
            "evidence": "e_final",
            "decision": decision,
            "terminal_status": terminal_status,
            "failure_reason": failure_reason,
            "attempt_count": 1,
            "duration_ms": 12,
            "guardian_thread_id": "thread-1",
            "model": "gpt-5.6-luna",
            "reasoning_effort": "low",
            "token_usage": {
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "cache_write_input_tokens": 0,
                "output_tokens": 2,
                "reasoning_output_tokens": 1,
                "total_tokens": 12,
            },
            "time_to_first_token_ms": 3,
        }
        (bundle / "meta.json").write_text(
            json.dumps(meta),
            encoding="utf-8",
        )
        return (bundle / "E_final.json").relative_to(self.jobs).as_posix()

    def test_completed_requires_job_trial_and_reward_not_just_host_zero(self) -> None:
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        self.assertEqual(parsed.outcome, RunOutcome.COMPLETED)
        self.assertEqual(parsed.task_outcome, "pass")
        self.assertEqual(parsed.duration_seconds, 5.0)
        self.assertEqual((parsed.input_tokens, parsed.cached_tokens, parsed.output_tokens), (100, 20, 10))

    def test_errored_trial_is_agent_failed_and_missing_reward_is_zero(self) -> None:
        self.job_result["stats"]["n_completed_trials"] = 0
        self.job_result["stats"]["n_errored_trials"] = 1
        self.trial_result["exception_info"] = {
            "exception_type": "NonZeroAgentExitCodeError"
        }
        self.trial_result["verifier_result"] = None
        self._write_results()
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        self.assertEqual((parsed.outcome, parsed.reward), (RunOutcome.AGENT_FAILED, 0.0))

    def test_early_agent_error_accepts_optional_harbor_fields(self) -> None:
        self.job_result["stats"]["n_completed_trials"] = 0
        self.job_result["stats"]["n_errored_trials"] = 1
        self.trial_result.update(
            {
                "agent_result": None,
                "verifier_result": None,
                "exception_info": {"exception_type": "NonZeroAgentExitCodeError"},
                "started_at": None,
                "finished_at": None,
            }
        )
        self._write_results()

        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        self.assertEqual(parsed.outcome, RunOutcome.AGENT_FAILED)
        self.assertEqual(parsed.task_outcome, "fail")
        self.assertEqual(parsed.duration_seconds, 0.0)
        self.assertEqual(
            (parsed.input_tokens, parsed.cached_tokens, parsed.output_tokens),
            (0, 0, 0),
        )

    def test_completed_still_requires_agent_result_and_timestamps(self) -> None:
        self.trial_result["agent_result"] = None
        self._write_results()
        with self.assertRaises(HarborResultError):
            parse_single_task_result(self.jobs, host_returncode=0)

        self.trial_result["agent_result"] = {
            "n_input_tokens": 0,
            "n_cache_tokens": 0,
            "n_output_tokens": 0,
        }
        self.trial_result["started_at"] = None
        self.trial_result["finished_at"] = None
        self._write_results()
        with self.assertRaises(HarborResultError):
            parse_single_task_result(self.jobs, host_returncode=0)

    def test_unknown_or_environment_trial_error_is_infra_failed(self) -> None:
        self.job_result["stats"]["n_completed_trials"] = 0
        self.job_result["stats"]["n_errored_trials"] = 1
        self.trial_result.update(
            {
                "agent_result": None,
                "verifier_result": None,
                "exception_info": {"exception_type": "AdapterError"},
                "started_at": None,
                "finished_at": None,
            }
        )
        self._write_results()

        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        self.assertEqual(parsed.outcome, RunOutcome.INFRA_FAILED)
        self.assertEqual(parsed.task_outcome, "fail")
        run_id = "20260810-010000007-tb-codex-r1"
        live_result = self._live_result(run_id)
        object.__setattr__(live_result, "metadata_ready", False)
        target = publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=live_result,
            parsed=parsed,
            metadata_path=self.root / "missing-api-metadata.json",
            publication=self._publication(exit_code=70),
        )
        self.assertTrue((target / "harbor/trial-result.json").is_file())
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "infra_failed")

    def test_infra_failure_cannot_publish_reward_as_success(self) -> None:
        run_id = "20260810-010000013-tb-codex-r1"
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main")
        parsed = parse_single_task_result(self.jobs, host_returncode=17)
        self.assertEqual((parsed.outcome, parsed.task_outcome), (RunOutcome.INFRA_FAILED, "fail"))
        live_result = self._live_result(run_id)
        object.__setattr__(live_result, "harbor", HostHarborResult(17, self.jobs))

        publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=live_result,
            parsed=parsed,
            metadata_path=metadata,
            publication=self._publication(exit_code=70),
        )

        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["summary"]["success_rate"], 0.0)
        self.assertEqual(record["tasks"][0]["outcome"], "fail")
        self.assertEqual(record["tasks"][0]["reward"], 0.0)
        self.assertEqual(record["tasks"][0]["attribution"], "infra")
        self.assertEqual(record["summary"]["api_request_roles"]["main"], 1)

    def test_ordinary_agent_failure_counts_verified_request_roles(self) -> None:
        run_id = "20260810-010000014-tb-codex-r1"
        self.job_result["stats"]["n_completed_trials"] = 0
        self.job_result["stats"]["n_errored_trials"] = 1
        self.trial_result.update(
            {
                "verifier_result": None,
                "exception_info": {"exception_type": "NonZeroAgentExitCodeError"},
            }
        )
        self._write_results()
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main", "guardian")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=self._live_result(run_id),
            parsed=parsed,
            metadata_path=metadata,
            publication=self._publication(exit_code=65),
        )

        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "agent_failed")
        self.assertEqual(record["tasks"][0]["attribution"], "agent")
        self.assertEqual(
            record["summary"]["api_request_roles"], {"main": 1, "guardian": 1}
        )

    def test_cancelled_trial_has_a_distinct_outcome(self) -> None:
        self.job_result["stats"].update(
            {
                "n_completed_trials": 0,
                "n_cancelled_trials": 1,
            }
        )
        self.trial_result.update(
            {
                "agent_result": None,
                "verifier_result": None,
                "exception_info": {"exception_type": "CancelledError"},
                "started_at": None,
                "finished_at": None,
            }
        )
        self._write_results()

        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        self.assertEqual(parsed.outcome, RunOutcome.CANCELLED)

    def test_reward_zero_is_a_completed_measurement_not_an_agent_crash(self) -> None:
        self.trial_result["verifier_result"] = {"rewards": {"reward": 0.0}}
        self._write_results()

        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        self.assertEqual(parsed.outcome, RunOutcome.COMPLETED)
        self.assertEqual(parsed.task_outcome, "fail")
        self.assertEqual(terminal_bench_main._outcome_exit_code(parsed.outcome), 0)

    def test_pre_api_agent_exit_is_archived_as_infrastructure(self) -> None:
        run_id = "20260810-010000005-tb-codex-r1"
        self.job_result["stats"]["n_completed_trials"] = 0
        self.job_result["stats"]["n_errored_trials"] = 1
        self.trial_result.update(
            {
                "agent_result": None,
                "verifier_result": None,
                "exception_info": {"exception_type": "NonZeroAgentExitCodeError"},
                "started_at": None,
                "finished_at": None,
            }
        )
        self._write_results()
        live_result = self._live_result(run_id)
        object.__setattr__(live_result, "metadata_ready", False)
        object.__setattr__(
            live_result,
            "budget_snapshot",
            {
                "runs": {
                    run_id: {"cap_usd": "10.000000", "spent_usd": "0.000000"}
                }
            },
        )
        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        target = publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=live_result,
            parsed=parsed,
            metadata_path=self.root / "missing-api-metadata.json",
            publication=self._publication(exit_code=70),
        )

        self.assertFalse((target / "harbor/job-result.json").exists())
        self.assertTrue((target / "harbor/trial-result.json").is_file())
        self.assertFalse((target / "harbor/job.log").exists())
        self.assertTrue((target / "api-metadata-unavailable.json").is_file())
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "infra_failed")
        self.assertEqual(record["tasks"][0]["attribution"], "infra")
        self.assertEqual(record["cost"], {"estimated_usd": 0.0, "actual_usd": 0.0})

    def test_nonzero_host_without_job_tree_is_explicit_infra_failure(self) -> None:
        missing = self.root / "missing-jobs"
        parsed = parse_single_task_result(missing, host_returncode=17)
        self.assertEqual(parsed.outcome, RunOutcome.INFRA_FAILED)
        self.assertEqual(parsed.task_outcome, "fail")
        self.assertEqual((parsed.reward, parsed.duration_seconds), (0.0, 0.0))
        self.assertEqual((parsed.job_result, parsed.trial_result), ({}, {}))
        with self.assertRaises(HarborResultError):
            parse_single_task_result(missing, host_returncode=0)

    def test_ambiguous_or_malformed_results_fail_closed(self) -> None:
        (self.jobs / "second-job").mkdir()
        # The parser is anchored to the exact trial directory and does not scan
        # children as candidate jobs/trials.
        self.assertEqual(
            parse_single_task_result(self.jobs, host_returncode=0).outcome,
            RunOutcome.COMPLETED,
        )
        (self.jobs / "second-job").rmdir()
        self.trial_result["task_name"] = "some-other-task"
        self._write_results()
        with self.assertRaises(HarborResultError):
            parse_single_task_result(self.jobs, host_returncode=0)

    def test_publication_copies_private_tree_and_appends_strict_index(self) -> None:
        run_id = "20260810-010000001-tb-codex-r1"
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main", "main", "guardian", "main", "main")
        (self.trial / "agent").mkdir()
        (self.trial / "agent" / "codex.txt").write_text(
            '{"type":"turn.completed"}\n', encoding="utf-8"
        )
        (self.job / "job.log").write_text(
            "Authorization: Bearer must-not-be-archived\n", encoding="utf-8"
        )
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        live_result = self._live_result(run_id)
        object.__setattr__(
            live_result,
            "budget_snapshot",
            self._completed_budget_snapshot(run_id, request_count=5),
        )
        target = publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=live_result,
            parsed=parsed,
            metadata_path=metadata,
            publication=self._publication(),
        )
        self.assertFalse((target / "harbor/job-result.json").exists())
        self.assertTrue((target / "harbor/trial-result.json").is_file())
        self.assertTrue((target / "harbor/agent/codex.txt").is_file())
        self.assertFalse((target / "harbor/job.log").exists())
        self.assertTrue((target / "api-metadata.json").is_file())
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["upstream_codex"], UPSTREAM_CODEX)
        self.assertEqual(record["outcome"], "completed")
        self.assertEqual(
            set(record["metrics"]),
            {
                "wall_seconds",
                "cpu_user_seconds",
                "cpu_system_seconds",
                "peak_rss_bytes",
                "exit_code",
            },
        )
        self.assertEqual(
            record["cost"], {"estimated_usd": 0.012345, "actual_usd": None}
        )
        self.assertNotIn("provider_base_url", record["config"])
        self.assertNotIn("provider_display_name", record["config"])
        self.assertNotIn("provider_api_key_env", record["config"])
        self.assertNotIn("provider_config_sha256", record["config"])
        serialized_config = json.dumps(record["config"], sort_keys=True)
        self.assertNotIn("Test provider", serialized_config)
        self.assertNotIn("https://provider.example/v1", serialized_config)
        self.assertNotIn("OPENAI_API_KEY", serialized_config)
        self.assertEqual(record["config"]["provider_profile_sha256"], "d" * 64)
        self.assertEqual(len(record["config"]["provider_endpoint_sha256"]), 64)
        self.assertEqual(
            record["config"]["requested_main_model"],
            record["config"]["effective_main_model"],
        )
        self.assertEqual(
            record["config"]["requested_guardian_model"],
            record["config"]["effective_guardian_model"],
        )
        self.assertEqual(
            record["config"]["frozen_codex_model_catalog_sha256"],
            "b" * 64,
        )
        summary = json.loads((target / "run-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            summary["config"]["bwrap_runtime_path"],
            "/opt/rondo-eval/bin/codex-resources/bwrap",
        )
        self.assertEqual(summary["config"]["bwrap_sha256"], "f" * 64)
        self.assertEqual(
            summary["config"]["bwrap_asset_url"],
            "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
            "bwrap-x86_64-unknown-linux-musl.tar.gz",
        )
        self.assertEqual(summary["config"]["bwrap_archive_sha256"], "1" * 64)
        self.assertEqual(summary["config"]["bwrap_source_tree_sha256"], "2" * 64)

    def test_campaign_publication_uses_campaign_identity_not_pair_fields(self) -> None:
        run_id = "20260811-210000001-tb-codex-r1"
        metadata = self.root / "work" / "campaign-api-metadata.json"
        self._write_metadata(metadata, "main", "guardian", "main")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        live_result = self._live_result(run_id)
        object.__setattr__(
            live_result,
            "budget_snapshot",
            self._completed_budget_snapshot(run_id, request_count=3),
        )
        provider = live_result.prepared.spec.provider
        target = publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=live_result,
            parsed=parsed,
            metadata_path=metadata,
            publication=CampaignPublicationContext(
                campaign_id="p2-b7-canary-baseline-v1",
                campaign_lock_sha256="7" * 64,
                campaign_slot_id="base:ab-codex-1:terminal-bench/fix-git:a1",
                campaign_round_id="ab-codex-1",
                campaign_attempt=1,
                taskset_sha256="8" * 64,
                canary_catalog_sha256="9" * 64,
                side=Side.CODEX,
                metrics={
                    "wall_seconds": 1.0,
                    "cpu_user_seconds": 0.1,
                    "cpu_system_seconds": 0.1,
                    "peak_rss_bytes": 1024,
                    "exit_code": 0,
                },
                selected_profile={
                    **provider.to_public_dict(),
                    "frozen_codex_model_catalog_source_commit": "a" * 40,
                    "frozen_codex_model_catalog_sha256": "b" * 64,
                    "max_guardian_logical_requests": 3,
                },
            ),
        )
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["config"]["campaign_id"], "p2-b7-canary-baseline-v1")
        self.assertEqual(record["config"]["campaign_attempt"], 1)
        self.assertNotIn("pair_id", record["config"])
        self.assertTrue(target.is_dir())

    def test_semantic_guardian_deny_is_scored_not_reclassified_as_infra(self) -> None:
        run_id = "20260811-210000002-tb-rondo-r1"
        relative = self._write_guardian_bundle(
            "deny-review",
            decision="denied",
            terminal_status="denied",
        )
        evidence, _e_final, _meta = load_guardian_evidence_bundle(
            self.jobs,
            relative,
            expected_model="gpt-5.6-luna",
            expected_effort="low",
        )
        metadata = self.root / "work" / "deny-api-metadata.json"
        self._write_metadata(
            metadata,
            "main",
            "guardian",
            "main",
            guardian_digests=(evidence.canonical_request_sha256,),
        )
        self.trial_result["verifier_result"] = {"rewards": {"reward": 0.0}}
        self._write_results()
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        live_result = self._live_result(run_id)
        object.__setattr__(
            live_result,
            "prepared",
            SimpleNamespace(spec=replace(live_result.prepared.spec, side=Side.RONDO)),
        )
        object.__setattr__(live_result, "evidence", (evidence,))
        publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.RONDO,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=live_result,
            parsed=parsed,
            metadata_path=metadata,
            publication=self._publication(side=Side.RONDO),
        )
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "completed")
        self.assertEqual(record["tasks"][0]["outcome"], "fail")
        self.assertEqual(record["summary"]["s2_request_evidence_binding"], "verified")
        self.assertEqual(record["summary"]["evidence"][0]["decision"], "denied")

    def test_guardian_technical_failure_is_infrastructure(self) -> None:
        relative = self._write_guardian_bundle(
            "failed-review",
            decision="denied",
            terminal_status="failed_closed",
            failure_reason="session_error",
        )
        evidence, _e_final, _meta = load_guardian_evidence_bundle(
            self.jobs,
            relative,
            expected_model="gpt-5.6-luna",
            expected_effort="low",
        )
        live_result = self._live_result("technical-fixture")
        object.__setattr__(live_result, "evidence", (evidence,))
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        self.assertEqual(
            classify_terminal_bench_result(live_result, parsed).outcome,
            RunOutcome.INFRA_FAILED,
        )

    def test_public_results_feed_m1_without_private_provider_fields(self) -> None:
        identity = load_historical_pair_identity()
        fixture_provider = self._live_result("m1-fixture").prepared.spec.provider
        identity = replace(
            identity,
            pair_id="test-producer-m1-pair",
            selected_profile=replace(
                identity.require_selected_profile(),
                provider_public=fixture_provider.to_public_dict(),
            ),
        )
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        relative = self._write_guardian_bundle("producer-m1-review")
        evidence, _e_final, _meta = load_guardian_evidence_bundle(
            self.jobs,
            relative,
            expected_model="gpt-5.6-luna",
            expected_effort="low",
        )
        harness_commit = "f" * 40
        records: list[dict[str, object]] = []
        for slot in identity.topology:
            self.assertIsNotNone(slot.paid_run_id)
            run_id = slot.paid_run_id or ""
            live_result = self._live_result(run_id)
            bundle = identity.bundles[slot.side]
            binary = replace(
                live_result.prepared.spec.binary,
                sha256=bundle.cli_sha256,
                code_mode_host_sha256=bundle.code_mode_host_sha256,
                bwrap_sha256=bundle.bwrap_sha256,
                source_commit=bundle.source_commit,
                workspace_lock_normalization=bundle.workspace_lock_normalization,
            )
            spec = replace(
                live_result.prepared.spec,
                side=slot.side,
                batch_id=identity.mode("paid").batch_id or "",
                task_id=identity.fairness["task_id"],
                task_image_digest=identity.fairness["task_image_digest"],
                terminal_bench_version=identity.fairness["terminal_bench_version"],
                binary=binary,
                timeout_seconds=identity.fairness["timeout_seconds"],
                max_retries=identity.fairness["max_retries"],
                budget_usd=identity.fairness["budget_usd"],
            )
            object.__setattr__(live_result, "prepared", SimpleNamespace(spec=spec))
            object.__setattr__(
                live_result,
                "evidence",
                (evidence,) if slot.side is Side.RONDO else (),
            )
            metadata = self.root / f"{slot.side.value}-api-metadata.json"
            self._write_metadata(
                metadata,
                "main",
                "guardian",
                "main",
                guardian_digests=(evidence.canonical_request_sha256,)
                if slot.side is Side.RONDO
                else (),
            )
            publish_terminal_bench_result(
                RepoPaths(self.root, self.root),
                results_worktree_root=self.root,
                run_id=run_id,
                side=slot.side,
                git_commit="e" * 40,
                eval_harness_commit=harness_commit,
                live_result=live_result,
                parsed=parsed,
                metadata_path=metadata,
                publication=RunPublicationContext(
                    pair_id=identity.pair_id,
                    pair_lock_sha256=identity.lock_sha256,
                    pair_slot=slot.slot,
                    pair_round=slot.round,
                    metrics={
                        "wall_seconds": 1.25,
                        "cpu_user_seconds": 0.5,
                        "cpu_system_seconds": 0.25,
                        "peak_rss_bytes": 1024,
                        "exit_code": 0,
                    },
                    selected_profile=identity.require_selected_profile().to_dict(),
                ),
            )
        index_path = self.root / "eval/results/runs.jsonl"
        records = [json.loads(line) for line in index_path.read_text().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertTrue(
            all("provider_api_key_env" not in record["config"] for record in records)
        )
        ledger_path = self.root / "pair-sequence.json"
        with PairSequenceLedger(ledger_path, identity=identity, mode="paid") as ledger:
            for slot, record in zip(identity.topology, records, strict=True):
                ledger.claim(
                    side=slot.side,
                    run_id=record["run_id"],
                    eval_harness_commit=harness_commit,
                    provider=fixture_provider,
                )
                ledger.finish(
                    run_id=record["run_id"],
                    completed=True,
                    eval_harness_commit=harness_commit,
                    publication_sha256=terminal_record_sha256(record),
                    container_metrics={
                        "container_id": ("a" if slot.side is Side.RONDO else "b") * 64,
                        "cpu_usage_seconds": 1.25,
                        "peak_memory_bytes": 4096,
                    },
                    provider=fixture_provider,
                )
        budget_path = self.root / "m1-budget.json"
        budget_runs = {
            record["run_id"]: self._completed_budget_snapshot(
                record["run_id"], request_count=3
            )["runs"][record["run_id"]]
            for record in records
        }
        budget_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "batch_id": identity.mode("paid").batch_id,
                    "total_cap_usd": "20.000000",
                    "max_runs": 4,
                    "default_run_cap_usd": "10.000000",
                    "runs": budget_runs,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        budget_path.with_name(f".{budget_path.name}.lock").touch(mode=0o600)
        result = assess_m1(
            records,
            identity,
            pair_ledger_path=ledger_path,
            budget_ledger_path=budget_path,
        )
        self.assertEqual(result["m1"], "passed", result["reasons"])
        self.assertNotIn("pair_fairness_mismatch", result["reasons"])

    def test_infra_without_job_tree_or_metadata_is_archived_explicitly(self) -> None:
        run_id = "20260810-010000002-tb-codex-r1"
        missing_jobs = self.root / "missing-jobs"
        missing_metadata = self.root / "work" / "missing-api-metadata.json"
        live_result = self._live_result(run_id)
        object.__setattr__(
            live_result,
            "harbor",
            HostHarborResult(17, missing_jobs),
        )
        object.__setattr__(live_result, "metadata_ready", False)
        parsed = parse_single_task_result(missing_jobs, host_returncode=17)

        target = publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=live_result,
            parsed=parsed,
            metadata_path=missing_metadata,
            publication=self._publication(exit_code=70),
        )

        self.assertTrue((target / "harbor/jobs-unavailable.json").is_file())
        self.assertTrue((target / "api-metadata-unavailable.json").is_file())
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "infra_failed")
        self.assertEqual(record["tasks"][0]["attribution"], "infra")

    def test_claimed_paid_exception_is_archived_with_budget_snapshot(self) -> None:
        run_id = "20260810-010000009-tb-codex-r1"
        paths = RepoPaths(self.root, self.root)
        writer = ArtifactWriter(
            paths, run_id, results_worktree_root=self.root
        ).start()
        live_result = self._live_result(run_id)
        budget_snapshot = {
            "batch_id": "p1-b3",
            "runs": {
                run_id: {
                    "cap_usd": "10.000000",
                    "spent_usd": "0.000000",
                    "requests": {"request-1": {"status": "reserved"}},
                }
            },
        }

        target = publish_terminal_bench_failure(
            paths,
            writer=writer,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            manifest=live_result.prepared.spec.binary,
            provider=live_result.prepared.spec.provider,
            budget_snapshot=budget_snapshot,
            metadata_path=self.root / "missing-api-metadata.json",
            outcome=RunOutcome.INFRA_FAILED,
            failure_stage="docker",
            publication=self._publication(exit_code=70),
            secrets=("never-persist",),
            infra_diagnostic={
                "supervisor_reason": "Docker storage counters are unavailable",
                "failed_probe": "docker_system_df",
                "probe_timings_ms": {"docker_system_df": 30000},
                "command_failure": {
                    "exit_code": 1,
                    "timed_out": False,
                    "stderr_bytes": 0,
                    "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                    "stderr_excerpt": "",
                },
            },
        )

        self.assertTrue((target / "run-failure.json").is_file())
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "infra_failed")
        self.assertEqual(record["config"]["failure_stage"], "docker")
        self.assertEqual(
            record["summary"]["infra_diagnostic"],
            {
                "supervisor_reason": "Docker storage counters are unavailable",
                "failed_probe": "docker_system_df",
                "probe_timings_ms": {"docker_system_df": 30000},
                "command_failure": {
                    "exit_code": 1,
                    "timed_out": False,
                    "stderr_bytes": 0,
                    "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                    "stderr_excerpt": "",
                },
            },
        )
        self.assertEqual(
            json.loads((target / "run-failure.json").read_text())["infra_diagnostic"],
            record["summary"]["infra_diagnostic"],
        )
        self.assertEqual(
            record["config"]["provider_profile_sha256"],
            live_result.prepared.spec.provider.profile_sha256,
        )
        self.assertEqual(
            len(record["config"]["provider_endpoint_sha256"]),
            64,
        )
        serialized = json.dumps(record, sort_keys=True)
        self.assertNotIn(live_result.prepared.spec.provider.base_url, serialized)
        self.assertNotIn(live_result.prepared.spec.provider.display_name, serialized)
        self.assertNotIn(live_result.prepared.spec.provider.api_key_env, serialized)
        self.assertEqual(
            record["cost"], {"estimated_usd": 0.0, "actual_usd": None}
        )

    def test_infra_diagnostic_rejects_unknown_or_non_docker_probe(self) -> None:
        run_id = "20260810-010000019-tb-codex-r1"
        paths = RepoPaths(self.root, self.root)
        live_result = self._live_result(run_id)
        for failure_stage, failed_probe in (
            ("result", "docker_system_df"),
            ("docker", "free_text_probe"),
        ):
            with self.subTest(failure_stage=failure_stage, failed_probe=failed_probe):
                writer = ArtifactWriter(
                    paths, run_id, results_worktree_root=self.root
                ).start()
                with self.assertRaises(HarborResultError):
                    publish_terminal_bench_failure(
                        paths,
                        writer=writer,
                        run_id=run_id,
                        side=Side.CODEX,
                        git_commit="e" * 40,
                        eval_harness_commit="f" * 40,
                        manifest=live_result.prepared.spec.binary,
                        provider=live_result.prepared.spec.provider,
                        budget_snapshot=live_result.budget_snapshot,
                        metadata_path=self.root / "missing-api-metadata.json",
                        outcome=RunOutcome.INFRA_FAILED,
                        failure_stage=failure_stage,
                        publication=self._publication(exit_code=70),
                        secrets=("never-persist",),
                        infra_diagnostic={
                            "supervisor_reason": "bounded reason",
                            "failed_probe": failed_probe,
                            "probe_timings_ms": {},
                        },
                    )
                writer.abort()

    def test_docker_failure_diagnostic_keeps_bounded_command_cause(self) -> None:
        command_failure = {
            "exit_code": 1,
            "timed_out": False,
            "stderr_bytes": 0,
            "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            "stderr_excerpt": "",
        }
        inner = RuntimeBridgeError(
            "Docker storage fact command failed",
            failed_probe="docker_container_metrics",
            command_failure=command_failure,
        )
        try:
            raise DockerSupervisionError(
                "Docker storage fact command failed",
                failed_probe="docker_container_metrics",
                probe_timings_ms=(("docker_container_metrics", 1700),),
            ) from inner
        except DockerSupervisionError as caught:
            diagnostic = terminal_bench_main._docker_failure_diagnostic(caught)
        self.assertEqual(diagnostic["command_failure"], command_failure)
        self.assertEqual(diagnostic["failed_probe"], "docker_container_metrics")

    def test_claimed_failure_reports_verified_api_metadata_truthfully(self) -> None:
        run_id = "20260810-010000012-tb-codex-r1"
        paths = RepoPaths(self.root, self.root)
        writer = ArtifactWriter(paths, run_id, results_worktree_root=self.root).start()
        live_result = self._live_result(run_id)
        metadata = self.root / "api-metadata.json"
        self._write_metadata(metadata, "main", "guardian")

        target = publish_terminal_bench_failure(
            paths,
            writer=writer,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            manifest=live_result.prepared.spec.binary,
            provider=live_result.prepared.spec.provider,
            budget_snapshot=live_result.budget_snapshot,
            metadata_path=metadata,
            outcome=RunOutcome.INFRA_FAILED,
            failure_stage="result",
            publication=self._publication(exit_code=70),
            secrets=("never-persist",),
        )

        self.assertTrue((target / "api-metadata.json").is_file())
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertTrue(record["summary"]["metadata_ready"])
        self.assertEqual(
            record["summary"]["api_request_roles"], {"main": 1, "guardian": 1}
        )

    def test_claimed_failure_counts_declared_roles_when_one_usage_is_invalid(self) -> None:
        run_id = "20260810-010000017-tb-rondo-r1"
        paths = RepoPaths(self.root, self.root)
        writer = ArtifactWriter(paths, run_id, results_worktree_root=self.root).start()
        live_result = self._live_result(run_id)
        metadata = self.root / "api-metadata.json"
        self._write_metadata(metadata, *("main",) * 5, "guardian")
        value = json.loads(metadata.read_text(encoding="utf-8"))
        value["requests"][-1]["usage_valid"] = False
        metadata.write_text(json.dumps(value) + "\n", encoding="utf-8")

        publish_terminal_bench_failure(
            paths,
            writer=writer,
            run_id=run_id,
            side=Side.RONDO,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            manifest=live_result.prepared.spec.binary,
            provider=live_result.prepared.spec.provider,
            budget_snapshot=live_result.budget_snapshot,
            metadata_path=metadata,
            outcome=RunOutcome.INFRA_FAILED,
            failure_stage="result",
            publication=self._publication(exit_code=70, side=Side.RONDO),
            secrets=("never-persist",),
        )

        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertFalse(record["summary"]["metadata_ready"])
        self.assertEqual(
            record["summary"]["api_request_roles"], {"main": 5, "guardian": 1}
        )

    def test_claimed_failure_archives_inferred_role_only_as_diagnostic(self) -> None:
        run_id = "20260810-010000015-tb-codex-r1"
        paths = RepoPaths(self.root, self.root)
        writer = ArtifactWriter(paths, run_id, results_worktree_root=self.root).start()
        live_result = self._live_result(run_id)
        metadata = self.root / "api-metadata.json"
        self._write_metadata(metadata, "main", provenance="inferred")

        target = publish_terminal_bench_failure(
            paths,
            writer=writer,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            manifest=live_result.prepared.spec.binary,
            provider=live_result.prepared.spec.provider,
            budget_snapshot=live_result.budget_snapshot,
            metadata_path=metadata,
            outcome=RunOutcome.INFRA_FAILED,
            failure_stage="result",
            publication=self._publication(exit_code=70),
            secrets=("never-persist",),
        )

        archived = json.loads((target / "api-metadata.json").read_text())
        self.assertEqual(archived["requests"][0]["role_provenance"], "inferred")
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertFalse(record["summary"]["metadata_ready"])
        self.assertEqual(
            record["summary"]["api_request_roles"], {"main": 0, "guardian": 0}
        )
        self.assertEqual(record["summary"]["api_request_sequence"], [])

    def test_completed_publication_keeps_metadata_gate(self) -> None:
        run_id = "20260810-010000003-tb-codex-r1"
        live_result = self._live_result(run_id)
        object.__setattr__(live_result, "metadata_ready", False)
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        with self.assertRaises(HarborResultError):
            publish_terminal_bench_result(
                RepoPaths(self.root, self.root),
                results_worktree_root=self.root,
                run_id=run_id,
                side=Side.CODEX,
                git_commit="e" * 40,
                eval_harness_commit="f" * 40,
                live_result=live_result,
                parsed=parsed,
                metadata_path=self.root / "missing-api-metadata.json",
                publication=self._publication(),
            )

    def test_completed_publication_rejects_stopped_budget_run(self) -> None:
        run_id = "20260810-010000020-tb-codex-r1"
        live_result = self._live_result(run_id)
        run = live_result.budget_snapshot["runs"][run_id]
        run["stopped"] = True
        run["stop_reason"] = "missing_or_invalid_usage"
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main", "guardian", "main")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        with self.assertRaisesRegex(
            HarborResultError, "completed run budget accounting is invalid"
        ):
            publish_terminal_bench_result(
                RepoPaths(self.root, self.root),
                results_worktree_root=self.root,
                run_id=run_id,
                side=Side.CODEX,
                git_commit="e" * 40,
                eval_harness_commit="f" * 40,
                live_result=live_result,
                parsed=parsed,
                metadata_path=metadata,
                publication=self._publication(),
            )

    def test_completed_publication_requires_exact_budget_request_ids(self) -> None:
        run_id = "20260810-010000021-tb-codex-r1"
        live_result = self._live_result(run_id)
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main", "guardian", "main")
        value = json.loads(metadata.read_text(encoding="utf-8"))
        value["requests"][0]["request_id"] = "different-request"
        metadata.write_text(json.dumps(value), encoding="utf-8")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        with self.assertRaisesRegex(
            HarborResultError, "budget requests differ from API metadata"
        ):
            publish_terminal_bench_result(
                RepoPaths(self.root, self.root),
                results_worktree_root=self.root,
                run_id=run_id,
                side=Side.CODEX,
                git_commit="e" * 40,
                eval_harness_commit="f" * 40,
                live_result=live_result,
                parsed=parsed,
                metadata_path=metadata,
                publication=self._publication(),
            )
        self.assertFalse((self.root / "eval/results/runs.jsonl").exists())

    def test_completed_publication_rejects_inferred_only_role(self) -> None:
        run_id = "20260810-010000016-tb-codex-r1"
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main", provenance="inferred")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        with self.assertRaises(HarborResultError):
            publish_terminal_bench_result(
                RepoPaths(self.root, self.root),
                results_worktree_root=self.root,
                run_id=run_id,
                side=Side.CODEX,
                git_commit="e" * 40,
                eval_harness_commit="f" * 40,
                live_result=self._live_result(run_id),
                parsed=parsed,
                metadata_path=metadata,
                publication=self._publication(),
            )

    def test_completed_rondo_without_guardian_request_is_rejected(self) -> None:
        run_id = "20260810-010000004-tb-rondo-r1"
        live_result = self._live_result(run_id)
        object.__setattr__(live_result.prepared.spec, "side", Side.RONDO)
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        with self.assertRaisesRegex(HarborResultError, "main-Guardian-main"):
            publish_terminal_bench_result(
                RepoPaths(self.root, self.root),
                results_worktree_root=self.root,
                run_id=run_id,
                side=Side.RONDO,
                git_commit="e" * 40,
                eval_harness_commit="f" * 40,
                live_result=live_result,
                parsed=parsed,
                metadata_path=metadata,
                publication=self._publication(side=Side.RONDO),
            )

    def test_completed_campaign_rondo_without_guardian_is_published(self) -> None:
        run_id = "20260811-230000001-tb-rondo-r1"
        live_result = self._live_result(run_id)
        object.__setattr__(live_result.prepared.spec, "side", Side.RONDO)
        object.__setattr__(
            live_result,
            "budget_snapshot",
            self._completed_budget_snapshot(run_id, request_count=1),
        )
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main")
        private = self.trial / "agent/codex.txt"
        private.parent.mkdir(parents=True)
        private.write_text("secret = task-fixture-value\n", encoding="utf-8")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        provider = live_result.prepared.spec.provider

        target = publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.RONDO,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=live_result,
            parsed=parsed,
            metadata_path=metadata,
            publication=CampaignPublicationContext(
                campaign_id="p2-b7-canary-baseline-v3",
                campaign_lock_sha256="7" * 64,
                campaign_slot_id="base:aa-rondo-1:terminal-bench/fix-git:a1",
                campaign_round_id="aa-rondo-1",
                campaign_attempt=1,
                taskset_sha256="8" * 64,
                canary_catalog_sha256="9" * 64,
                side=Side.RONDO,
                metrics={
                    "wall_seconds": 1.0,
                    "cpu_user_seconds": 0.1,
                    "cpu_system_seconds": 0.1,
                    "peak_rss_bytes": 1024,
                    "exit_code": 0,
                },
                selected_profile={
                    **provider.to_public_dict(),
                    "frozen_codex_model_catalog_source_commit": "a" * 40,
                    "frozen_codex_model_catalog_sha256": "b" * 64,
                    "max_guardian_logical_requests": 3,
                },
            ),
        )

        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "completed")
        self.assertEqual(record["summary"]["api_request_sequence"], ["main"])
        self.assertEqual(record["summary"]["evidence"], [])
        self.assertEqual(
            record["summary"]["s2_request_evidence_binding"], "not_triggered"
        )
        self.assertFalse((target / "harbor/agent/codex.txt").exists())
        marker = json.loads(
            (target / "harbor/agent/codex.txt.redacted.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(marker["reason"], "sensitive_private_artifact_omitted")
        self.assertEqual(marker["source_size_bytes"], len(private.read_bytes()))
        self.assertTrue(target.is_dir())

    def test_completed_rondo_guardian_request_requires_e_final(self) -> None:
        run_id = "20260810-010000006-tb-rondo-r1"
        live_result = self._live_result(run_id)
        object.__setattr__(live_result.prepared.spec, "side", Side.RONDO)
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main", "guardian", "main")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        with self.assertRaises(HarborResultError):
            publish_terminal_bench_result(
                RepoPaths(self.root, self.root),
                results_worktree_root=self.root,
                run_id=run_id,
                side=Side.RONDO,
                git_commit="e" * 40,
                eval_harness_commit="f" * 40,
                live_result=live_result,
                parsed=parsed,
                metadata_path=metadata,
                publication=self._publication(side=Side.RONDO),
            )

    def test_completed_rondo_archives_revalidated_e_final_and_meta(self) -> None:
        run_id = "20260810-010000008-tb-rondo-r1"
        observations = tuple(
            load_guardian_evidence_bundle(
                self.jobs,
                self._write_guardian_bundle(review_id),
                expected_model="gpt-5.6-luna",
                expected_effort="low",
            )[0]
            for review_id in ("review-1", "review-2")
        )
        live_result = self._live_result(run_id)
        object.__setattr__(live_result.prepared.spec, "side", Side.RONDO)
        object.__setattr__(live_result, "evidence", observations)
        object.__setattr__(
            live_result,
            "budget_snapshot",
            self._completed_budget_snapshot(run_id, request_count=7),
        )
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(
            metadata,
            "main",
            "main",
            "guardian",
            "main",
            "guardian",
            "main",
            "main",
            guardian_digests=tuple(
                item.canonical_request_sha256 for item in observations
            ),
        )
        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        target = publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.RONDO,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            live_result=live_result,
            parsed=parsed,
            metadata_path=metadata,
            publication=self._publication(side=Side.RONDO),
        )

        self.assertTrue((target / "guardian-evidence/0001/E_final.json").is_file())
        public_record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(
            [item["relative_path"] for item in public_record["summary"]["evidence"]],
            [
                "guardian-evidence/0001/E_final.json",
                "guardian-evidence/0002/E_final.json",
            ],
        )
        for item in public_record["summary"]["evidence"]:
            self.assertTrue((target / item["relative_path"]).is_file())
        archived_meta = json.loads(
            (target / "guardian-evidence/0001/meta.json").read_text(encoding="utf-8")
        )
        self.assertEqual(archived_meta["review_id"], "review-1")
        summary = json.loads((target / "run-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            summary["summary"]["evidence"][0]["guardian_source_commit"],
            UPSTREAM_CODEX["commit"],
        )
        self.assertEqual(
            summary["summary"]["api_request_sequence"],
            ["main", "main", "guardian", "main", "guardian", "main", "main"],
        )
        self.assertEqual(len(summary["summary"]["evidence"]), 2)
        self.assertEqual(summary["summary"]["s2_request_evidence_binding"], "verified")
        self.assertEqual(
            {
                item["canonical_request_sha256"]
                for item in summary["summary"]["evidence"]
            },
            {item.canonical_request_sha256 for item in observations},
        )

    def test_completed_rondo_rejects_evidence_request_digest_mismatch(self) -> None:
        run_id = "20260810-010000021-tb-rondo-r1"
        observation = load_guardian_evidence_bundle(
            self.jobs,
            self._write_guardian_bundle(),
            expected_model="gpt-5.6-luna",
            expected_effort="low",
        )[0]
        live_result = self._live_result(run_id)
        object.__setattr__(live_result.prepared.spec, "side", Side.RONDO)
        object.__setattr__(live_result, "evidence", (observation,))
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main", "guardian", "main")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)

        with self.assertRaisesRegex(
            HarborResultError, "not bound to canonical requests"
        ):
            publish_terminal_bench_result(
                RepoPaths(self.root, self.root),
                results_worktree_root=self.root,
                run_id=run_id,
                side=Side.RONDO,
                git_commit="e" * 40,
                eval_harness_commit="f" * 40,
                live_result=live_result,
                parsed=parsed,
                metadata_path=metadata,
                publication=self._publication(side=Side.RONDO),
            )

    def test_guardian_meta_source_drift_is_rejected(self) -> None:
        relative = self._write_guardian_bundle()
        meta_path = self.trial / "agent/guardian-evidence/review-1/meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["guardian_source_commit"] = "0" * 40
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with self.assertRaises(TerminalBenchRunError):
            load_guardian_evidence_bundle(
                self.jobs,
                relative,
                expected_model="gpt-5.6-luna",
                expected_effort="low",
            )

    def test_guardian_meta_contradictory_terminal_fields_are_rejected(self) -> None:
        relative = self._write_guardian_bundle()
        meta_path = self.trial / "agent/guardian-evidence/review-1/meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.update(
            decision="denied",
            terminal_status="approved",
            failure_reason="session_error",
        )
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with self.assertRaisesRegex(TerminalBenchRunError, "contradictory"):
            load_guardian_evidence_bundle(
                self.jobs,
                relative,
                expected_model="gpt-5.6-luna",
                expected_effort="low",
            )

    def test_outcome_exit_codes_preserve_infra_classification(self) -> None:
        self.assertEqual(terminal_bench_main._outcome_exit_code(RunOutcome.COMPLETED), 0)
        self.assertEqual(
            terminal_bench_main._outcome_exit_code(RunOutcome.INFRA_FAILED),
            terminal_bench_main.INFRA_ERROR,
        )
        self.assertEqual(
            terminal_bench_main._outcome_exit_code(RunOutcome.AGENT_FAILED),
            terminal_bench_main.EVIDENCE_ERROR,
        )
        self.assertEqual(
            terminal_bench_main._exception_failure(KeyboardInterrupt()),
            (RunOutcome.CANCELLED, "interrupted", 130),
        )

    def test_cli_rejects_run_id_before_loading_config_or_secret(self) -> None:
        with patch.object(terminal_bench_main, "load_runtime_config") as load_config:
            result = terminal_bench_main.main(
                [
                    "--side",
                    "codex",
                    "--batch-id",
                    "p1-b3",
                    "--run-id",
                    "not-a-run-id",
                    "--binary-manifest",
                    "/missing/manifest.json",
                    "--docker-host-volume",
                    "/missing/docker-volume",
                    "--results-worktree-root",
                    "/missing/results",
                ]
            )

        self.assertEqual(result, terminal_bench_main.EVIDENCE_ERROR)
        load_config.assert_not_called()

    def test_cli_rejects_unapproved_batch_before_loading_config_or_secret(self) -> None:
        with patch.object(terminal_bench_main, "load_runtime_config") as load_config:
            result = terminal_bench_main.main(
                [
                    "--side",
                    "codex",
                    "--batch-id",
                    "another-ledger",
                    "--run-id",
                    "20260810-010000010-tb-codex-r1",
                    "--binary-manifest",
                    "/missing/manifest.json",
                    "--docker-host-volume",
                    "/missing/docker-volume",
                    "--results-worktree-root",
                    "/missing/results",
                ]
            )

        self.assertEqual(result, terminal_bench_main.CONFIG_ERROR)
        load_config.assert_not_called()

    def test_cli_has_no_active_paid_identity_before_any_external_preflight(self) -> None:
        argv = [
            "--side",
            "codex",
            "--batch-id",
            "retired-paid-batch",
            "--run-id",
            "20260810-010000022-tb-codex-r1",
            "--binary-manifest",
            "/missing/manifest.json",
            "--docker-host-volume",
            "/missing/docker-volume",
            "--results-worktree-root",
            "/missing/results",
        ]
        with (
            patch.object(terminal_bench_main.RepoPaths, "discover") as discover,
            patch.object(terminal_bench_main, "load_runtime_config") as load_config,
            patch.object(terminal_bench_main, "load_provider_secret") as load_secret,
            patch.object(terminal_bench_main, "PairSequenceLedger") as sequence,
            patch.object(terminal_bench_main, "lease_from_watchdog") as watchdog,
        ):
            result = terminal_bench_main.main(argv)

        self.assertEqual(result, terminal_bench_main.CONFIG_ERROR)
        discover.assert_not_called()
        load_config.assert_not_called()
        load_secret.assert_not_called()
        sequence.assert_not_called()
        watchdog.assert_not_called()

    @staticmethod
    def _paid_recovery_record(
        *, identity: object, run_id: str, harness_commit: str, drift_side: bool = False
    ) -> dict[str, object]:
        slot = identity.slot_for(Side.RONDO)
        return {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": "2026-08-10T01:00:00+08:00",
            "track": "tb",
            "side": Side.CODEX.value if drift_side else Side.RONDO.value,
            "git_commit": "a" * 40,
            "git_dirty": False,
            "binary_sha256": "b" * 64,
            "upstream_codex": dict(UPSTREAM_CODEX),
            "config": {
                **identity.require_selected_profile().to_dict(),
                "pair_id": identity.pair_id,
                "pair_lock_sha256": identity.lock_sha256,
                "pair_slot": slot.slot,
                "pair_round": slot.round,
                "eval_harness_commit": harness_commit,
            },
            "outcome": RunOutcome.COMPLETED.value,
            "summary": {"success_rate": 1.0},
            "tasks": [{"task_id": "terminal-bench/fix-git", "outcome": "pass"}],
            "metrics": {
                "wall_seconds": 1.0,
                "cpu_user_seconds": 0.5,
                "cpu_system_seconds": 0.25,
                "peak_rss_bytes": 4096,
                "exit_code": 0,
            },
            "cost": {"estimated_usd": 0.0, "actual_usd": 0.0},
            "artifacts": f"eval-data/runs/{run_id}",
            "notes": "",
        }

    def _paid_recovery_fixture(
        self,
        *,
        write_record: bool,
        drift_record: bool = False,
    ) -> tuple[object, str, str, Path]:
        run_id = "20260810-010000012-tb-rondo-r1"
        batch_id = "p1-paid-recovery"
        harness_commit = "f" * 40
        identity = load_historical_pair_identity()
        provider = self._live_result("recovery-provider").prepared.spec.provider
        identity = replace(
            identity,
            pair_id="test-paid-recovery-pair",
            selected_profile=replace(
                identity.require_selected_profile(),
                provider_public=provider.to_public_dict(),
            ),
        )
        modes = dict(identity.modes)
        modes["paid"] = PairMode(True, batch_id)
        topology = tuple(
            replace(
                slot,
                paid_run_id=(run_id if slot.side is Side.RONDO else "20260810-010000013-tb-codex-r1"),
            )
            for slot in identity.topology
        )
        identity = replace(identity, modes=modes, topology=topology)
        sequence_path = (
            self.root / "eval-data" / "pairs" / f"{identity.pair_id}-paid.json"
        )
        with PairSequenceLedger(
            sequence_path, identity=identity, mode="paid"
        ) as sequence:
            sequence.claim(
                side=Side.RONDO,
                run_id=run_id,
                eval_harness_commit=harness_commit,
                provider=provider,
            )
            sequence.stage_paid_publication(
                run_id=run_id,
                eval_harness_commit=harness_commit,
                container_metrics={
                    "container_id": "a" * 64,
                    "cpu_usage_seconds": 1.0,
                    "peak_memory_bytes": 4096,
                },
                provider=provider,
            )
        if write_record:
            target = self.root / "eval-data" / "runs" / run_id
            target.mkdir(parents=True)
            (target / "result.json").write_text("{}\n", encoding="utf-8")
            index = self.root / "eval" / "results" / "runs.jsonl"
            index.parent.mkdir(parents=True)
            record = self._paid_recovery_record(
                identity=identity,
                run_id=run_id,
                harness_commit=harness_commit,
                drift_side=drift_record,
            )
            index.write_text(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
        work_root = self.root / "eval-data" / "work" / run_id
        work_root.mkdir(parents=True)
        return identity, run_id, batch_id, sequence_path

    def _run_recovery_cli(
        self,
        *,
        identity: object,
        run_id: str,
        batch_id: str,
    ) -> tuple[int, tuple[mock.Mock, ...]]:
        paths = RepoPaths(self.root, self.root)
        provider = self._live_result("recovery-provider").prepared.spec.provider
        with patch.object(
            terminal_bench_main.RepoPaths, "discover", return_value=paths
        ), patch.object(
            terminal_bench_main, "load_active_pair_identity", return_value=identity
        ), patch.object(
            terminal_bench_main, "validate_results_worktree", return_value=self.root
        ), patch.object(
            terminal_bench_main,
            "load_runtime_config",
            return_value=SimpleNamespace(
                paid_provider_projection=lambda: provider
            ),
        ), patch.object(
            terminal_bench_main, "load_provider_secret"
        ) as load_secret, patch.object(
            terminal_bench_main, "lease_from_watchdog"
        ) as watchdog, patch.object(
            terminal_bench_main, "run_budgeted_terminal_bench"
        ) as backend, patch.object(
            terminal_bench_main, "_load_manifest"
        ) as load_manifest, patch.object(
            terminal_bench_main, "validate_eval_harness_checkout"
        ) as validate_harness, patch.object(
            terminal_bench_main, "validate_harbor_installation"
        ) as validate_harbor, patch("builtins.print"):
            result = terminal_bench_main.main(
                [
                    "--side",
                    "rondo",
                    "--batch-id",
                    batch_id,
                    "--run-id",
                    run_id,
                    "--binary-manifest",
                    "/must-not-be-read/manifest.json",
                    "--docker-host-volume",
                    "/must-not-be-read/docker-volume",
                    "--results-worktree-root",
                    os.fspath(self.root),
                ]
            )
        return result, (
            load_secret,
            watchdog,
            backend,
            load_manifest,
            validate_harness,
            validate_harbor,
        )

    def test_cli_reconciles_publishing_before_worktree_or_external_preflight(self) -> None:
        identity, run_id, batch_id, sequence_path = self._paid_recovery_fixture(
            write_record=True
        )
        result, forbidden = self._run_recovery_cli(
            identity=identity,
            run_id=run_id,
            batch_id=batch_id,
        )
        self.assertEqual(result, 0)
        for operation in forbidden:
            operation.assert_not_called()
        state = json.loads(sequence_path.read_text(encoding="utf-8"))
        self.assertEqual(len(state["runs"]), 1)
        self.assertEqual(state["runs"][0]["status"], "completed")
        self.assertEqual(state["next_slot"], 2)

    @unittest.skipUnless(hasattr(os, "fork"), "requires POSIX publication crash injection")
    def test_cli_recovers_artifact_publication_at_three_crash_cuts(self) -> None:
        original_root = self.root
        try:
            for point in ("after-journal", "after-target", "after-index"):
                with self.subTest(point=point):
                    self.root = original_root / point
                    self.root.mkdir()
                    identity, run_id, batch_id, sequence_path = (
                        self._paid_recovery_fixture(write_record=False)
                    )
                    record = self._paid_recovery_record(
                        identity=identity,
                        run_id=run_id,
                        harness_commit="f" * 40,
                    )
                    child = os.fork()
                    if child == 0:
                        writer = ArtifactWriter(
                            RepoPaths(self.root, self.root), run_id
                        ).start()
                        writer.write_json("result.json", {"ok": True})
                        if point == "after-journal":
                            original_write_journal = ArtifactWriter._write_journal

                            def crash_after_journal(self, *args, **kwargs):
                                original_write_journal(self, *args, **kwargs)
                                os._exit(77)

                            ArtifactWriter._write_journal = crash_after_journal
                        elif point == "after-target":

                            def crash_before_index(*_args, **_kwargs):
                                os._exit(77)

                            artifacts_module._atomic_replace_index = crash_before_index
                        else:
                            original_replace_index = artifacts_module._atomic_replace_index

                            def crash_after_index(*args, **kwargs):
                                original_replace_index(*args, **kwargs)
                                os._exit(77)

                            artifacts_module._atomic_replace_index = crash_after_index
                        writer.finalize(record, secrets=())
                        os._exit(78)
                    _pid, status = os.waitpid(child, 0)
                    self.assertEqual(os.waitstatus_to_exitcode(status), 77)

                    result, forbidden = self._run_recovery_cli(
                        identity=identity,
                        run_id=run_id,
                        batch_id=batch_id,
                    )
                    self.assertEqual(result, 0)
                    for operation in forbidden:
                        operation.assert_not_called()
                    state = json.loads(sequence_path.read_text(encoding="utf-8"))
                    self.assertEqual(len(state["runs"]), 1)
                    self.assertEqual(state["runs"][0]["status"], "completed")
                    runs_root = self.root / "eval-data" / "runs"
                    self.assertTrue((runs_root / run_id / "result.json").is_file())
                    self.assertFalse((runs_root / f".{run_id}.publish.json").exists())
                    self.assertFalse(
                        any(
                            entry.name.startswith(f".{run_id}.staging-")
                            for entry in runs_root.iterdir()
                        )
                    )
        finally:
            self.root = original_root

    def test_cli_blocks_publishing_when_durable_record_is_missing(self) -> None:
        identity, run_id, batch_id, sequence_path = self._paid_recovery_fixture(
            write_record=False
        )
        result, forbidden = self._run_recovery_cli(
            identity=identity,
            run_id=run_id,
            batch_id=batch_id,
        )
        self.assertEqual(result, terminal_bench_main.EVIDENCE_ERROR)
        for operation in forbidden:
            operation.assert_not_called()
        state = json.loads(sequence_path.read_text(encoding="utf-8"))
        self.assertEqual(state["runs"][0]["status"], "publishing")

    def test_cli_blocks_publishing_when_durable_record_drifted(self) -> None:
        identity, run_id, batch_id, sequence_path = self._paid_recovery_fixture(
            write_record=True,
            drift_record=True,
        )
        result, forbidden = self._run_recovery_cli(
            identity=identity,
            run_id=run_id,
            batch_id=batch_id,
        )
        self.assertEqual(result, terminal_bench_main.CONFIG_ERROR)
        for operation in forbidden:
            operation.assert_not_called()
        state = json.loads(sequence_path.read_text(encoding="utf-8"))
        self.assertEqual(state["runs"][0]["status"], "publishing")

    def test_cli_archives_a_claimed_docker_exception_before_returning(self) -> None:
        run_id = "20260810-010000011-tb-codex-r1"
        live = self._live_result(run_id)
        paths = RepoPaths(self.root, self.root)
        async_failure = mock.AsyncMock(
            side_effect=DockerSupervisionError("redacted test failure")
        )
        pair_identity = mock.Mock(
            pair_id="p1-fix-git-pair-v19",
            lock_sha256="9" * 64,
        )
        pair_identity.paid_budget = SimpleNamespace(
            per_side_usd=10.0,
            pair_usd=20.0,
        )
        pair_identity.require_selected_profile.return_value.to_dict.return_value = {
            **live.prepared.spec.provider.to_public_dict(),
            "frozen_codex_model_catalog_source_commit": "a" * 40,
            "frozen_codex_model_catalog_sha256": "b" * 64,
            "max_guardian_logical_requests": 1,
        }
        pair_identity.mode.return_value = SimpleNamespace(
            batch_id=self.PAID_BATCH_ID
        )
        pair_identity.slot_for.return_value = SimpleNamespace(
            paid_run_id=run_id,
            slot=2,
            round=1,
        )
        sequence = mock.MagicMock()
        sequence.__enter__.return_value = sequence
        with patch.object(terminal_bench_main.RepoPaths, "discover", return_value=paths), patch.object(
            terminal_bench_main, "load_active_pair_identity", return_value=pair_identity
        ), patch.object(
            terminal_bench_main, "validate_harbor_installation"
        ), patch.object(
            terminal_bench_main,
            "load_runtime_config",
            return_value=SimpleNamespace(
                paid_provider_projection=lambda: live.prepared.spec.provider
            ),
        ), patch.object(
            terminal_bench_main, "validate_eval_harness_checkout", return_value="f" * 40
        ), patch.object(
            terminal_bench_main, "_load_manifest", return_value=live.prepared.spec.binary
        ), patch.object(
            terminal_bench_main, "validate_results_worktree", return_value=self.root
        ), patch.object(
            terminal_bench_main, "validate_measurement_checkout", return_value="e" * 40
        ), patch.object(
            terminal_bench_main, "load_provider_secret", return_value=("OPENAI_API_KEY", "key")
        ), patch.object(
            terminal_bench_main, "lease_from_watchdog", return_value=SimpleNamespace(
                lease=object(), guard=object()
            )
        ), patch.object(
            terminal_bench_main, "run_budgeted_terminal_bench", async_failure
        ), patch.object(
            terminal_bench_main, "PairSequenceLedger", return_value=sequence
        ), patch("builtins.print") as safe_print:
            result = terminal_bench_main.main(
                [
                    "--side",
                    "codex",
                    "--batch-id",
                    self.PAID_BATCH_ID,
                    "--run-id",
                    run_id,
                    "--binary-manifest",
                    "/ignored/manifest.json",
                    "--docker-host-volume",
                    os.fspath(self.root),
                    "--results-worktree-root",
                    os.fspath(self.root),
                ]
            )

        self.assertEqual(result, terminal_bench_main.INFRA_ERROR)
        sequence.claim.assert_called_once_with(
            side=Side.CODEX,
            run_id=run_id,
            eval_harness_commit="f" * 40,
            provider=live.prepared.spec.provider,
        )
        sequence.finish.assert_called_once_with(
            run_id=run_id,
            completed=False,
            eval_harness_commit="f" * 40,
            provider=live.prepared.spec.provider,
        )
        safe_print.assert_called_once()
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "infra_failed")
        self.assertEqual(record["config"]["failure_stage"], "docker")
        budget = json.loads(
            (self.root / f"eval-data/budgets/{self.PAID_BATCH_ID}.json").read_text()
        )
        self.assertIn(run_id, budget["runs"])

    def test_cli_converges_pre_journal_publication_validation_failure(self) -> None:
        run_id = "20260810-010000014-tb-codex-r1"
        live = self._live_result(run_id)
        paths = RepoPaths(self.root, self.root)
        measurement_root = self.root / "measurement"
        measurement_root.mkdir()
        measurement_paths = RepoPaths(self.root, measurement_root)

        def discover(start):
            return measurement_paths if Path(start) == measurement_root else paths

        pair_identity = mock.Mock(
            pair_id="p1-fix-git-pair-v19",
            lock_sha256="9" * 64,
        )
        pair_identity.paid_budget = SimpleNamespace(
            per_side_usd=10.0,
            pair_usd=20.0,
        )
        pair_identity.mode.return_value = SimpleNamespace(
            batch_id=self.PAID_BATCH_ID
        )
        pair_identity.slot_for.return_value = SimpleNamespace(
            paid_run_id=run_id,
            slot=2,
            round=1,
        )
        sequence = mock.MagicMock()
        sequence.__enter__.return_value = sequence

        with patch.object(
            terminal_bench_main.RepoPaths, "discover", side_effect=discover
        ), patch.object(
            terminal_bench_main, "load_active_pair_identity", return_value=pair_identity
        ), patch.object(
            terminal_bench_main, "validate_harbor_installation"
        ), patch.object(
            terminal_bench_main,
            "load_runtime_config",
            return_value=SimpleNamespace(
                paid_provider_projection=lambda: live.prepared.spec.provider
            ),
        ), patch.object(
            terminal_bench_main,
            "validate_eval_harness_checkout",
            return_value="f" * 40,
        ), patch.object(
            terminal_bench_main,
            "_load_manifest",
            return_value=live.prepared.spec.binary,
        ), patch.object(
            terminal_bench_main, "validate_results_worktree", return_value=self.root
        ), patch.object(
            terminal_bench_main,
            "validate_measurement_checkout",
            return_value="e" * 40,
        ) as validate_measurement, patch.object(
            terminal_bench_main,
            "load_provider_secret",
            return_value=("OPENAI_API_KEY", "key"),
        ), patch.object(
            terminal_bench_main,
            "lease_from_watchdog",
            return_value=SimpleNamespace(lease=object(), guard=object()),
        ), patch.object(
            terminal_bench_main,
            "run_budgeted_terminal_bench",
            mock.AsyncMock(return_value=live),
        ), patch.object(
            terminal_bench_main,
            "_paid_container_metrics",
            return_value={
                "container_id": "a" * 64,
                "cpu_usage_seconds": 1.0,
                "peak_memory_bytes": 4096,
            },
        ), patch.object(
            terminal_bench_main,
            "publication_context",
            return_value=self._publication(
                side=Side.CODEX,
                exit_code=terminal_bench_main.EVIDENCE_ERROR,
            ),
        ), patch.object(
            terminal_bench_main,
            "publish_terminal_bench_result",
            side_effect=ArtifactError("deterministic record validation failed"),
        ) as result_publisher, patch.object(
            terminal_bench_main, "PairSequenceLedger", return_value=sequence
        ), patch("builtins.print") as safe_print:
            result = terminal_bench_main.main(
                [
                    "--side",
                    "codex",
                    "--batch-id",
                    self.PAID_BATCH_ID,
                    "--run-id",
                    run_id,
                    "--binary-manifest",
                    "/ignored/manifest.json",
                    "--docker-host-volume",
                    os.fspath(self.root),
                    "--results-worktree-root",
                    os.fspath(self.root),
                    "--measurement-worktree-root",
                    os.fspath(measurement_root),
                ]
            )

        self.assertEqual(result, terminal_bench_main.EVIDENCE_ERROR)
        result_publisher.assert_called_once()
        safe_print.assert_called_once()
        self.assertEqual(validate_measurement.call_count, 2)
        self.assertTrue(
            all(
                call.args[0] == measurement_paths
                for call in validate_measurement.call_args_list
            )
        )
        sequence.stage_paid_publication.assert_called_once_with(
            run_id=run_id,
            eval_harness_commit="f" * 40,
            container_metrics={
                "container_id": "a" * 64,
                "cpu_usage_seconds": 1.0,
                "peak_memory_bytes": 4096,
            },
            provider=live.prepared.spec.provider,
        )
        sequence.finish.assert_called_once_with(
            run_id=run_id,
            completed=False,
            eval_harness_commit="f" * 40,
            provider=live.prepared.spec.provider,
        )
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "infra_failed")
        self.assertEqual(record["config"]["failure_stage"], "publication")

    def test_success_cli_reports_durable_public_guardian_evidence(self) -> None:
        run_id = "20260810-010000015-tb-rondo-r1"
        live = self._live_result(run_id)
        spec = replace(live.prepared.spec, side=Side.RONDO)
        object.__setattr__(live, "prepared", SimpleNamespace(spec=spec))
        evidence_relative = self._write_guardian_bundle()
        evidence, _e_final, _meta = load_guardian_evidence_bundle(
            live.harbor.jobs_dir,
            evidence_relative,
            expected_model=spec.provider.guardian_model,
            expected_effort=spec.provider.guardian_effort,
        )
        object.__setattr__(live, "evidence", (evidence,))
        metadata_path = self.root / "eval-data/work" / run_id / "api-metadata.json"

        async def run_live(*_args, **_kwargs):
            self._write_metadata(
                metadata_path,
                "main",
                "guardian",
                "main",
                guardian_digests=(evidence.canonical_request_sha256,),
            )
            return live
        pair_identity = mock.Mock(
            pair_id="test-cli-public-evidence-pair",
            lock_sha256="9" * 64,
        )
        pair_identity.paid_budget = SimpleNamespace(
            per_side_usd=10.0,
            pair_usd=20.0,
        )
        pair_identity.require_selected_profile.return_value.to_dict.return_value = {
            **spec.provider.to_public_dict(),
            "frozen_codex_model_catalog_source_commit": "a" * 40,
            "frozen_codex_model_catalog_sha256": "b" * 64,
            "max_guardian_logical_requests": 2,
        }
        pair_identity.mode.return_value = SimpleNamespace(batch_id=self.PAID_BATCH_ID)
        pair_identity.slot_for.return_value = SimpleNamespace(
            paid_run_id=run_id,
            slot=1,
            round=1,
        )
        pair_identity.validate_runtime_seccomp.return_value = self.root / "seccomp.json"
        pair_identity.no_api_seccomp = SimpleNamespace(
            source_sha256="c" * 64,
            effective_sha256="d" * 64,
        )
        sequence = mock.MagicMock()
        sequence.__enter__.return_value = sequence
        paths = RepoPaths(self.root, self.root)
        with patch.object(
            terminal_bench_main.RepoPaths, "discover", return_value=paths
        ), patch.object(
            terminal_bench_main, "load_active_pair_identity", return_value=pair_identity
        ), patch.object(
            terminal_bench_main, "validate_harbor_installation"
        ), patch.object(
            terminal_bench_main,
            "load_runtime_config",
            return_value=SimpleNamespace(
                paid_provider_projection=lambda: spec.provider
            ),
        ), patch.object(
            terminal_bench_main,
            "validate_eval_harness_checkout",
            return_value="f" * 40,
        ), patch.object(
            terminal_bench_main, "_load_manifest", return_value=spec.binary
        ), patch.object(
            terminal_bench_main, "validate_results_worktree", return_value=self.root
        ), patch.object(
            terminal_bench_main,
            "validate_measurement_checkout",
            return_value="e" * 40,
        ), patch.object(
            terminal_bench_main,
            "load_provider_secret",
            return_value=("OPENAI_API_KEY", "key"),
        ), patch.object(
            terminal_bench_main,
            "lease_from_watchdog",
            return_value=SimpleNamespace(lease=object(), guard=object()),
        ), patch.object(
            terminal_bench_main,
            "run_budgeted_terminal_bench",
            mock.AsyncMock(side_effect=run_live),
        ), patch.object(
            terminal_bench_main,
            "_paid_container_metrics",
            return_value={
                "container_id": "a" * 64,
                "cpu_usage_seconds": 1.0,
                "peak_memory_bytes": 4096,
            },
        ), patch.object(
            terminal_bench_main,
            "publication_context",
            return_value=self._publication(side=Side.RONDO),
        ), patch.object(
            terminal_bench_main, "PairSequenceLedger", return_value=sequence
        ), patch("builtins.print") as safe_print:
            result = terminal_bench_main.main(
                [
                    "--side",
                    "rondo",
                    "--batch-id",
                    self.PAID_BATCH_ID,
                    "--run-id",
                    run_id,
                    "--binary-manifest",
                    "/ignored/manifest.json",
                    "--docker-host-volume",
                    os.fspath(self.root),
                    "--results-worktree-root",
                    os.fspath(self.root),
                ]
            )

        self.assertEqual(result, 0)
        receipt = json.loads(safe_print.call_args.args[0])
        record = json.loads(
            (self.root / "eval/results/runs.jsonl").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["evidence"], record["summary"]["evidence"])
        self.assertEqual(
            receipt["evidence"][0]["canonical_request_sha256"],
            evidence.canonical_request_sha256,
        )
        self.assertEqual(
            receipt["evidence"][0]["relative_path"],
            "guardian-evidence/0001/E_final.json",
        )
        shutil.rmtree(self.root / "work")
        artifact_root = self.root / receipt["artifacts"]
        self.assertTrue(
            (artifact_root / receipt["evidence"][0]["relative_path"]).is_file()
        )
        runs_root = self.root / "eval-data" / "runs"
        self.assertFalse((runs_root / f".{run_id}.publish.json").exists())


if __name__ == "__main__":
    unittest.main()
